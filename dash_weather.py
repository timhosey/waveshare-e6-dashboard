import logging
import os
import sys
import time
import json
import requests
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logging.info("[dash_weather] starting up…")

from dotenv import load_dotenv, find_dotenv
dotenv_path = find_dotenv(usecwd=True)
load_dotenv(dotenv_path=dotenv_path)
logging.info("[dash_weather] dotenv loaded from: %s", dotenv_path if dotenv_path else "<none>")

OWM_API_KEY = os.getenv("OWM_API_KEY")
OWM_LAT     = os.getenv("OWM_LAT")
OWM_LON     = os.getenv("OWM_LON")
OWM_UNITS   = os.getenv("OWM_UNITS", "metric")

missing = [k for k, v in {"OWM_API_KEY": OWM_API_KEY, "OWM_LAT": OWM_LAT, "OWM_LON": OWM_LON}.items() if not v]
if missing:
    logging.warning("[dash_weather] missing env: %s (set them in your .env)", ", ".join(missing))

os.environ.setdefault("GPIOZERO_PIN_FACTORY", "lgpio")

EPD_LIB = "./lib"
if os.path.exists(EPD_LIB):
    sys.path.append(EPD_LIB)

epd_driver = None

WIDTH, HEIGHT = 800, 480
CACHE_DIR = Path("cache"); CACHE_DIR.mkdir(exist_ok=True)
WEATHER_CACHE = CACHE_DIR / "weather.json"
HEADERS = {"User-Agent": "SakuraWeather/1.0 (personal use)"}

WEATHER_CACHE_TTL_MIN = int(os.environ.get("WEATHER_CACHE_TTL_MIN", "30"))
CACHE_TTL = timedelta(minutes=WEATHER_CACHE_TTL_MIN)

# ── Fonts ──────────────────────────────────────────────────────────────────────
# Low-DPI e-ink dithers thin anti-aliased strokes into near-invisibility, so we
# prefer a bold weight wherever one exists and fall back through progressively
# lighter weights — and ultimately the default PIL font — if it doesn't.
FONT_DIR = Path("fonts")
_BOLD_CHAIN = [
    "MPLUSRounded1c-Bold.ttf",
    "MPLUSRounded1c-ExtraBold.ttf",
    "MPLUSRounded1c-Medium.ttf",
    "MPLUSRounded1c-Regular.ttf",
]

def _load_font(size: int, chain: list[str] = _BOLD_CHAIN) -> ImageFont.FreeTypeFont:
    for name in chain:
        p = FONT_DIR / name
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception as e:
                logging.warning("[dash_weather] failed to load %s: %s", name, e)
    logging.warning("[dash_weather] no bundled font found in %s; using PIL default", chain)
    return ImageFont.load_default()

FONT_HEADER  = _load_font(22)
FONT_TEMP    = _load_font(64)
FONT_COND    = _load_font(24)
FONT_VALUE   = _load_font(20)
FONT_LABEL   = _load_font(18)
FONT_DAY     = _load_font(20)
FONT_FC_TEMP = _load_font(18)
FONT_SMALL   = _load_font(16)
logging.info("[dash_weather] fonts loaded")

# Stroke width applied to small/medium text so glyphs stay solid under e-ink
# dithering instead of fading at the anti-aliased edges. Skipped for FONT_TEMP,
# which is already large enough that stroking would just blob the digits.
_TEXT_STROKE = 1

def dtext(draw: ImageDraw.ImageDraw, xy, text: str, font, fill, stroke: int = _TEXT_STROKE):
    """draw.text with an outline stroke for legibility on low-DPI e-ink."""
    if stroke:
        draw.text(xy, text, font=font, fill=fill, stroke_width=stroke, stroke_fill=fill)
    else:
        draw.text(xy, text, font=font, fill=fill)

def text_w(draw: ImageDraw.ImageDraw, text: str, font, stroke: int = _TEXT_STROKE) -> int:
    """Width of text as it will actually render, including stroke."""
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
    return bbox[2] - bbox[0]

WEATHER_ICON_DIR = Path("img/weather")

# ── Helpers ────────────────────────────────────────────────────────────────────

def load_cache(path: Path, ttl: timedelta) -> dict | None:
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        age = datetime.now().timestamp() - float(data.get("_ts", 0))
        if age <= ttl.total_seconds():
            logging.info("[dash_weather] using cached weather (age: %.0fs)", age)
            return data
        logging.info("[dash_weather] cache stale (age: %.0fs > %.0fs)", age, ttl.total_seconds())
    except Exception as e:
        logging.warning("[dash_weather] failed to load cache: %s", e)
    return None

def save_cache(path: Path, payload: dict) -> None:
    try:
        out = dict(payload)
        out["_ts"] = datetime.now().timestamp()
        path.write_text(json.dumps(out))
        logging.info("[dash_weather] wrote weather cache → %s", path)
    except Exception as e:
        logging.warning("[dash_weather] failed to write cache: %s", e)

def load_icon(name: str, size: int) -> Image.Image | None:
    p = WEATHER_ICON_DIR / f"{name}.png"
    p_alt = WEATHER_ICON_DIR / f"{name}_48.png"
    if not p.exists() and size == 48 and p_alt.exists():
        p = p_alt
    if not p.exists():
        return None
    img = Image.open(p).convert("RGBA")
    if img.height != size:
        scale = size / img.height
        img = img.resize((int(img.width * scale), size), Image.LANCZOS)
    return img

def owm_icon_to_simple(weather_id: int, main: str, desc: str) -> str:
    if 200 <= weather_id <= 232: return "thunder"
    if 300 <= weather_id <= 321: return "drizzle"
    if 500 <= weather_id <= 531: return "rain"
    if 600 <= weather_id <= 622: return "snow"
    if 700 <= weather_id <= 781: return "mist"
    if weather_id == 800:        return "sun"
    if 801 <= weather_id <= 804: return "clouds"
    m = (main or "").lower()
    if "rain"  in m: return "rain"
    if "snow"  in m: return "snow"
    if "cloud" in m: return "clouds"
    return "sun"

def wind_cardinal(deg) -> str:
    if deg is None:
        return ""
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[round(deg / 45) % 8]

# ── Main compositor ────────────────────────────────────────────────────────────

# Per-condition border colors for forecast cards (maps to e-ink palette well)
_COND_COLORS = {
    "sun":     (220, 140,   0),
    "clouds":  (120, 140, 185),
    "rain":    ( 60, 130, 210),
    "drizzle": ( 80, 150, 215),
    "snow":    (150, 180, 235),
    "mist":    (140, 160, 190),
    "thunder": (200, 120,  40),
}

def compose_weather_dashboard(data: dict) -> Image.Image:
    canvas = Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    current = data.get("current", {})
    daily   = data.get("daily", [])
    tz_name = data.get("timezone", "")

    # Current conditions
    now_ts = current.get("dt", time.time())
    try:
        now = datetime.fromtimestamp(now_ts)
    except Exception:
        now = datetime.now()

    wlist     = current.get("weather", [{"id": 800, "main": "Clear", "description": "clear sky"}])
    wid       = wlist[0].get("id", 800)
    cond_main = wlist[0].get("main", "Clear")
    cond_desc = wlist[0].get("description", "").title()
    icon_key  = owm_icon_to_simple(wid, cond_main, cond_desc)

    temp     = current.get("temp")
    feels    = current.get("feels_like")
    humidity = current.get("humidity")
    wind_spd = current.get("wind_speed")
    wind_deg = current.get("wind_deg")
    uvi      = current.get("uvi")

    # Today H/L: provided by 2.5 free path; fall back to daily[0] for OneCall 3.0
    today_hi = current.get("today_max") or (daily[0].get("temp", {}).get("max") if daily else None)
    today_lo = current.get("today_min") or (daily[0].get("temp", {}).get("min") if daily else None)

    units_sym = "°C" if OWM_UNITS == "metric" else "°F"
    speed_sym = "km/h" if OWM_UNITS == "metric" else "mph"

    # OWM returns wind in m/s for metric — convert to km/h for display
    if wind_spd is not None and OWM_UNITS == "metric":
        wind_spd = round(wind_spd * 3.6)
    elif wind_spd is not None:
        wind_spd = round(wind_spd)

    def fmt(val) -> str:
        return f"{round(val)}{units_sym}" if isinstance(val, (int, float)) else "–"

    # ── HEADER ────────────────────────────────────────────────────────────
    loc = tz_name.replace("_", " ").split("/")[-1] if tz_name else "Weather"
    date_str = now.strftime("%A, %b %d  •  %I:%M %p").lstrip("0")

    dtext(draw, (16, 10), loc, FONT_HEADER, (50, 80, 165))
    date_w = text_w(draw, date_str, FONT_LABEL)
    dtext(draw, (WIDTH - date_w - 16, 12), date_str, FONT_LABEL, (90, 110, 145))
    draw.line([(0, 44), (WIDTH, 44)], fill=(180, 195, 215), width=2)

    # ── LEFT PANEL: icon + big temperature + condition ─────────────────────
    LP = (8, 50, 390, 270)   # x1, y1, x2, y2
    draw.rounded_rectangle(LP, radius=14, outline=(175, 188, 215), width=2)

    ICON_SZ = 90
    icon_img = load_icon(icon_key, ICON_SZ)
    ix, iy = LP[0] + 14, LP[1] + 14
    if icon_img:
        canvas.paste(icon_img, (ix, iy), icon_img)
    else:
        draw.rounded_rectangle([ix, iy, ix + ICON_SZ, iy + ICON_SZ],
                               radius=12, outline=(180, 190, 215), width=2)

    # Temperature to the right of the icon (no stroke — already huge)
    temp_str = fmt(temp)
    tx = ix + ICON_SZ + 14
    ty = LP[1] + 10
    dtext(draw, (tx, ty), temp_str, FONT_TEMP, (30, 75, 180), stroke=0)

    # Condition description below icon
    cond_y = iy + ICON_SZ + 10
    dtext(draw, (LP[0] + 14, cond_y), cond_desc or cond_main, FONT_COND, (70, 55, 120))

    # Soft "updated" timestamp at bottom of panel
    upd = now.strftime("Updated %I:%M %p").replace(" 0", " ")
    dtext(draw, (LP[0] + 14, LP[3] - 22), upd, FONT_SMALL, (160, 165, 180))

    # ── RIGHT PANEL: detail stats ─────────────────────────────────────────
    RP = (400, 50, 792, 270)
    draw.rounded_rectangle(RP, radius=14, outline=(175, 188, 215), width=2)

    rx = RP[0] + 16          # left edge of text inside panel
    rr = RP[2] - 16          # right edge for value alignment

    dtext(draw, (rx, RP[1] + 10), "Today's Details", FONT_SMALL, (110, 120, 150))
    draw.line([(RP[0] + 12, RP[1] + 32), (RP[2] - 12, RP[1] + 32)], fill=(190, 200, 218), width=1)

    def stat_row(y: int, label: str, value: str, val_color=(28, 38, 60)):
        dtext(draw, (rx, y), label, FONT_LABEL, (105, 115, 140))
        vw = text_w(draw, value, FONT_VALUE)
        dtext(draw, (rr - vw, y - 1), value, FONT_VALUE, val_color)

    ROW_START = RP[1] + 42
    ROW_STEP  = 38

    # Today H/L — two right-aligned values side by side
    dtext(draw, (rx, ROW_START), "Today", FONT_LABEL, (105, 115, 140))
    hi_s = f"↑ {fmt(today_hi)}"
    lo_s = f"↓ {fmt(today_lo)}"
    hi_w = text_w(draw, hi_s, FONT_VALUE)
    lo_w = text_w(draw, lo_s, FONT_VALUE)
    lo_x = rr - lo_w
    hi_x = lo_x - hi_w - 14
    dtext(draw, (hi_x, ROW_START - 1), hi_s, FONT_VALUE, (210, 55, 35))
    dtext(draw, (lo_x, ROW_START - 1), lo_s, FONT_VALUE, (40, 100, 200))

    stat_row(ROW_START + ROW_STEP,     "Feels Like",
             fmt(feels))
    stat_row(ROW_START + ROW_STEP * 2, "Humidity",
             f"{humidity}%" if humidity is not None else "–")
    wind_val = (f"{wind_spd} {speed_sym} {wind_cardinal(wind_deg)}"
                if wind_spd is not None else "–")
    stat_row(ROW_START + ROW_STEP * 3, "Wind", wind_val)

    if uvi is not None:
        uvi_labels = ["Low","Low","Low","Moderate","Moderate","Moderate",
                      "High","High","Very High","Very High","Very High","Extreme"]
        uvi_str = f"{round(uvi)} – {uvi_labels[min(int(uvi), 11)]}"
        stat_row(ROW_START + ROW_STEP * 4, "UV Index", uvi_str)

    # ── DIVIDER ───────────────────────────────────────────────────────────
    draw.line([(8, 278), (WIDTH - 8, 278)], fill=(175, 192, 215), width=2)

    # ── FORECAST STRIP: next 4 days ───────────────────────────────────────
    forecast_days = daily[1:5]
    if not forecast_days:
        return canvas

    N = len(forecast_days)
    CARD_MARGIN = 8
    CARD_GAP    = 8
    card_w = (WIDTH - 2 * CARD_MARGIN - CARD_GAP * (N - 1)) // N
    FC_Y1, FC_Y2 = 284, 474

    for i, day in enumerate(forecast_days):
        cx1 = CARD_MARGIN + i * (card_w + CARD_GAP)
        cx2 = cx1 + card_w
        cx_mid = cx1 + card_w // 2

        dt  = datetime.fromtimestamp(day.get("dt", time.time()))
        dw  = day.get("weather", [{"id": 800, "main": "Clear", "description": ""}])[0]
        dk  = owm_icon_to_simple(dw.get("id", 800), dw.get("main", "Clear"), dw.get("description", ""))
        col = _COND_COLORS.get(dk, (175, 188, 210))

        draw.rounded_rectangle([cx1, FC_Y1, cx2, FC_Y2], radius=14, outline=col, width=3)

        # Day name (centered)
        day_name = dt.strftime("%a")
        dnw = text_w(draw, day_name, FONT_DAY)
        dtext(draw, (cx_mid - dnw // 2, FC_Y1 + 8), day_name, FONT_DAY, (65, 52, 115))

        # Short date (centered)
        date_lbl = dt.strftime("%b %d")
        dlw = text_w(draw, date_lbl, FONT_SMALL)
        dtext(draw, (cx_mid - dlw // 2, FC_Y1 + 32), date_lbl, FONT_SMALL, (115, 125, 150))

        # Icon (centered)
        ic = load_icon(dk, 56)
        if ic:
            canvas.paste(ic, (cx_mid - 28, FC_Y1 + 54), ic)
        else:
            draw.rounded_rectangle([cx1 + 20, FC_Y1 + 54, cx2 - 20, FC_Y1 + 110],
                                   radius=10, outline=col, width=2)

        # High / Low temps (centered)
        tmax = day.get("temp", {}).get("max")
        tmin = day.get("temp", {}).get("min")
        hi_s = fmt(tmax)
        lo_s = fmt(tmin)
        hiw = text_w(draw, hi_s, FONT_FC_TEMP)
        low = text_w(draw, lo_s, FONT_FC_TEMP)
        dtext(draw, (cx_mid - hiw // 2, FC_Y1 + 118), hi_s, FONT_FC_TEMP, (210, 55, 35))
        dtext(draw, (cx_mid - low  // 2, FC_Y1 + 142), lo_s, FONT_FC_TEMP, (40, 100, 200))

        # Condition label (centered, truncated)
        cond_lbl = (dw.get("description") or dw.get("main", "")).title()
        if cond_lbl:
            cond_lbl = cond_lbl[:18]
            clw = text_w(draw, cond_lbl, FONT_SMALL)
            dtext(draw, (cx_mid - clw // 2, FC_Y1 + 168), cond_lbl, FONT_SMALL, (88, 95, 118))

    return canvas


# ── EPD display ────────────────────────────────────────────────────────────────

def display_on_epd(img: Image.Image):
    global epd_driver
    if epd_driver is None:
        try:
            from waveshare_epd import epd7in3e as epd_driver
            logging.info("[dash_weather] EPD driver loaded")
        except Exception as e:
            logging.warning("[dash_weather] EPD driver unavailable (%s) — saving to out_weather.png", e)
            img.save("out_weather.png")
            return
    try:
        epd = epd_driver.EPD()
        epd.init()
        logging.info("Displaying on EPD…")
        epd.display(epd.getbuffer(img))
        epd.sleep()
        logging.info("Done. EPD sleeping.")
    except Exception as e:
        logging.error("[dash_weather] EPD error: %s — saving to out_weather.png", e)
        img.save("out_weather.png")

def compose_weather_dashboard_no_display() -> Image.Image:
    return compose_weather_dashboard(get_weather())


# ── Data fetching ──────────────────────────────────────────────────────────────

def get_weather() -> dict:
    cached = load_cache(WEATHER_CACHE, CACHE_TTL)
    if cached is not None:
        return cached
    logging.info("[dash_weather] fetching weather (no fresh cache)…")
    data = fetch_weather()
    save_cache(WEATHER_CACHE, data)
    return data

def fetch_weather_3_0() -> dict:
    """One Call 3.0 (paid). Returns native JSON."""
    if not (OWM_API_KEY and OWM_LAT and OWM_LON):
        raise RuntimeError("Set OWM_API_KEY, OWM_LAT, OWM_LON in env.")
    r = requests.get(
        "https://api.openweathermap.org/data/3.0/onecall",
        params={"lat": OWM_LAT, "lon": OWM_LON, "appid": OWM_API_KEY,
                "units": OWM_UNITS, "exclude": "minutely,hourly,alerts"},
        headers=HEADERS, timeout=15,
    )
    r.raise_for_status()
    return r.json()

def fetch_weather_2_5() -> dict:
    """Free 2.5 endpoints, normalized to a OneCall-compatible shape."""
    if not (OWM_API_KEY and OWM_LAT and OWM_LON):
        raise RuntimeError("Set OWM_API_KEY, OWM_LAT, OWM_LON in env.")

    params = {"lat": OWM_LAT, "lon": OWM_LON, "appid": OWM_API_KEY, "units": OWM_UNITS}
    rc = requests.get("https://api.openweathermap.org/data/2.5/weather",
                      params=params, headers=HEADERS, timeout=15)
    rc.raise_for_status()
    cur = rc.json()

    rf = requests.get("https://api.openweathermap.org/data/2.5/forecast",
                      params=params, headers=HEADERS, timeout=15)
    rf.raise_for_status()
    fc = rf.json()

    now       = int(cur.get("dt", time.time()))
    tz_offset = cur.get("timezone", 0)
    tz_name   = cur.get("name") or fc.get("city", {}).get("name", "")

    main_blk = cur.get("main", {})
    wind_blk = cur.get("wind", {})

    current = {
        "dt":        now,
        "temp":      main_blk.get("temp"),
        "feels_like":main_blk.get("feels_like"),
        "humidity":  main_blk.get("humidity"),
        "today_min": main_blk.get("temp_min"),
        "today_max": main_blk.get("temp_max"),
        "wind_speed":wind_blk.get("speed"),
        "wind_deg":  wind_blk.get("deg"),
        "weather":   cur.get("weather", [{"id": 800, "main": "Clear", "description": ""}]),
        # uvi not available on free 2.5 tier
    }

    # Build daily aggregates from 3-hour forecast list
    buckets = defaultdict(list)
    for item in fc.get("list", []):
        ts = item.get("dt")
        if ts is None:
            continue
        day = datetime.utcfromtimestamp(ts + tz_offset).date()
        buckets[day].append(item)

    today = datetime.utcfromtimestamp(now + tz_offset).date()
    daily = []
    for d in sorted(d for d in buckets if d >= today)[:5]:
        entries = buckets[d]
        temps = [e["main"]["temp"] for e in entries if e.get("main", {}).get("temp") is not None]
        tmin = min(temps) if temps else None
        tmax = max(temps) if temps else None

        # Representative weather: most common condition id across all 3-hour slots
        mains = [(w.get("id", 800), w.get("main", "Clear"), w.get("description", ""))
                 for e in entries for w in e.get("weather", [])]
        if mains:
            top_id = Counter(m[0] for m in mains).most_common(1)[0][0]
            top    = next(m for m in mains if m[0] == top_id)
            rep_weather = [{"id": top[0], "main": top[1], "description": top[2]}]
        else:
            rep_weather = [{"id": 800, "main": "Clear", "description": ""}]

        # Prefer a noon entry as the representative timestamp
        noon = next((e for e in entries
                     if 11 <= datetime.utcfromtimestamp(e["dt"] + tz_offset).hour <= 13), None)
        daily.append({
            "dt":      (noon or entries[0])["dt"],
            "temp":    {"min": tmin, "max": tmax},
            "weather": rep_weather,
        })

    return {"timezone": tz_name, "current": current, "daily": daily}

def fetch_weather() -> dict:
    """Try OneCall 3.0; fall back to free 2.5 on auth errors."""
    try:
        return fetch_weather_3_0()
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status in (401, 403):
            logging.warning("OneCall 3.0 unauthorized (%s). Falling back to free 2.5.", status)
            return fetch_weather_2_5()
        raise


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    data = get_weather()
    logging.info("[dash_weather] composing dashboard…")
    display_on_epd(compose_weather_dashboard(data))

if __name__ == "__main__":
    main()
