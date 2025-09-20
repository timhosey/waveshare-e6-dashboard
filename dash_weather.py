import logging
import os
import sys
from PIL import Image, ImageDraw, ImageFont
from sakura import add_to_canvas as sakura_add
import time
import json
import requests
from datetime import datetime, timedelta
from pathlib import Path
from io import BytesIO
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logging.info("[dash_weather] starting up…")

from dotenv import load_dotenv, find_dotenv
dotenv_path = find_dotenv(usecwd=True)
load_dotenv(dotenv_path=dotenv_path)
logging.info("[dash_weather] dotenv loaded from: %s", dotenv_path if dotenv_path else "<none>")

# Read env vars (with defaults)
OWM_API_KEY = os.getenv("OWM_API_KEY")
OWM_LAT     = os.getenv("OWM_LAT")
OWM_LON     = os.getenv("OWM_LON")
OWM_UNITS   = os.getenv("OWM_UNITS", "metric")

# Optional: surface missing keys early for clarity
missing = [k for k,v in {"OWM_API_KEY": OWM_API_KEY, "OWM_LAT": OWM_LAT, "OWM_LON": OWM_LON}.items() if not v]
if missing:
    logging.warning("[dash_weather] missing env: %s (set them in your .env)", ", ".join(missing))

os.environ.setdefault("GPIOZERO_PIN_FACTORY", "lgpio")

from dotenv import load_dotenv
load_dotenv()

EPD_LIB = "./lib"
if os.path.exists(EPD_LIB):
    sys.path.append(EPD_LIB)

epd_driver = None
try:
    from waveshare_epd import epd7in3e as _epd_driver
    epd_driver = _epd_driver
    logging.info("[dash_weather] Waveshare EPD driver loaded")
except Exception as e:
    logging.warning("[dash_weather] EPD driver unavailable (%s). Will save preview PNG instead.", e)

# Basic constants (define if not already defined elsewhere)
if 'WIDTH' not in globals():
    WIDTH, HEIGHT = 800, 480
if 'CACHE_DIR' not in globals():
    CACHE_DIR = Path("cache"); CACHE_DIR.mkdir(exist_ok=True)
if 'WEATHER_CACHE' not in globals():
    WEATHER_CACHE = CACHE_DIR / "weather.json"
if 'CACHE_TTL' not in globals():
    CACHE_TTL = timedelta(minutes=30)
if 'HEADERS' not in globals():
    HEADERS = {"User-Agent": "SakuraWeather/1.0 (personal use)"}

# Allow overriding cache TTL via env (minutes)
WEATHER_CACHE_TTL_MIN = int(os.environ.get("WEATHER_CACHE_TTL_MIN", "30"))
CACHE_TTL = timedelta(minutes=WEATHER_CACHE_TTL_MIN)

def load_cache(path: Path, ttl: timedelta) -> dict | None:
    try:
        if not path.exists():
            return None
        raw = path.read_text()
        data = json.loads(raw)
        ts = data.get("_ts")
        if ts is None:
            return None
        age = datetime.now().timestamp() - float(ts)
        if age <= ttl.total_seconds():
            logging.info("[dash_weather] using cached weather (age: %.0fs)", age)
            return data
        else:
            logging.info("[dash_weather] cache stale (age: %.0fs > %.0fs)", age, ttl.total_seconds())
    except Exception as e:
        logging.warning("[dash_weather] failed to load cache: %s", e)
    return None

def save_cache(path: Path, payload: dict) -> None:
    try:
        payload = dict(payload)
        payload["_ts"] = datetime.now().timestamp()
        path.write_text(json.dumps(payload))
        logging.info("[dash_weather] wrote weather cache → %s", path)
    except Exception as e:
        logging.warning("[dash_weather] failed to write cache: %s", e)

# Fonts
if 'FONT_DIR' not in globals():
    FONT_DIR = Path("fonts")
try:
    FONT_INFO    = ImageFont.truetype(str(FONT_DIR / "MPLUSRounded1c-Regular.ttf"), 32)
    FONT_INFO_SM = ImageFont.truetype(str(FONT_DIR / "MPLUSRounded1c-Regular.ttf"), 22)
    FONT_SAKURA  = ImageFont.truetype(str(FONT_DIR / "Fredoka-Regular.ttf"), 20)
except Exception as e:
    logging.warning("[dash_weather] font load failed (%s); falling back to default PIL font", e)
    FONT_INFO = FONT_INFO_SM = FONT_SAKURA = ImageFont.load_default()
logging.info("[dash_weather] fonts loaded: MPLUSRounded1c + Fredoka")

# Sakura art + weather icons
if 'SAKURA_EMOTE' not in globals():
    # Set to 'auto' to let the code choose an outfit based on weather
    SAKURA_EMOTE = os.environ.get("SAKURA_EMOTE", "auto")
if 'SAKURA_DIR' not in globals():
    SAKURA_DIR = Path("img/sakura")
if 'WEATHER_ICON_DIR' not in globals():
    WEATHER_ICON_DIR = Path("img/weather")

# ... [assume other imports and code here]

# After creating fonts, add:
logging.info("[dash_weather] fonts loaded: MPLUSRounded1c + Fredoka")

# ------------ Helpers for layout & icons ------------
def wrap_text_to_width(text, font, max_width, draw):
    words = text.split()
    if not words:
        return [""]
    lines = []
    cur = words[0]
    for w in words[1:]:
        test = cur + " " + w
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            cur = test
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines

def load_icon(name: str, size: int) -> Image.Image | None:
    """Load a weather icon PNG by simple key (e.g., 'sun', 'clouds'). Returns RGBA or None."""
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
    """Map OWM condition to our simple icon keys."""
    if 200 <= weather_id <= 232:
        return "thunder"
    if 300 <= weather_id <= 321:
        return "drizzle"
    if 500 <= weather_id <= 531:
        return "rain"
    if 600 <= weather_id <= 622:
        return "snow"
    if 700 <= weather_id <= 781:
        return "mist"
    if weather_id == 800:
        return "sun"
    if 801 <= weather_id <= 804:
        return "clouds"
    m = (main or "").lower()
    if "rain" in m:
        return "rain"
    if "snow" in m:
        return "snow"
    if "cloud" in m:
        return "clouds"
    return "sun"

def sakura_comment(main: str, temp: float, desc: str) -> str:
    units_sym = "°C" if OWM_UNITS == "metric" else "°F"
    m = (main or "").lower()
    try:
        t = round(float(temp)) if temp is not None else "?"
    except Exception:
        t = "?"
    if "rain" in m or "drizzle" in m:
        return f"Sakura: Umbrella time, Tim-senpai! Nyaa~ ☔ ({t}{units_sym})"
    if "snow" in m:
        return f"Sakura: Brr~ bundle up! ❄️ ({t}{units_sym})"
    if "cloud" in m:
        return f"Sakura: Cloudy cuddles day~ ☁️ ({t}{units_sym})"
    if "clear" in m or "sun" in m:
        return f"Sakura: Sunny smiles! ☀️ ({t}{units_sym})"
    return f"Sakura: {main.title() if main else 'Weather'} vibes~ ({t}{units_sym})"

# --- Sakura outfit picker ---
def _to_fahrenheit(val, units):
    try:
        v = float(val)
    except Exception:
        return None
    if units == "imperial":
        return v
    # metric -> convert C to F
    return v * 9.0/5.0 + 32.0

# Map OpenWeather "main" field to outfit base key
_SAKURA_MAP = {
    "Thunderstorm": "sakura_thunder.png",
    "Rain":         "sakura_rain.png",
    "Drizzle":      "sakura_rain.png",
    "Snow":         "sakura_snow.png",
    "Mist":         "sakura_mist.png",
    "Fog":          "sakura_mist.png",
    "Clouds":       "sakura_cloudy.png",
    "Clear":        "sakura_sunny.png",
}

def pick_sakura_sprite(main: str, temp_val, units: str) -> str:
    """Return filename for Sakura outfit based on weather + temperature.
    Hoodie rule: 55–70°F when not precip/snow/thunder/mist.
    Sunny hot rule: if Clear and >= 80°F → sunny swimsuit.
    """
    # Allow manual override via SAKURA_EMOTE (unless it's 'auto')
    if SAKURA_EMOTE and SAKURA_EMOTE.lower() != 'auto':
        return f"sakura_{SAKURA_EMOTE.lower()}.png"

    main = (main or "").title()
    temp_f = _to_fahrenheit(temp_val, units)

    # Precip-type outfits take precedence
    if main in ("Thunderstorm", "Rain", "Drizzle", "Snow", "Mist", "Fog"):
        return _SAKURA_MAP.get(main, "sakura_sunny.png")

    # Hoodie window if not precip/mist/snow/thunder
    if temp_f is not None and 55.0 <= temp_f <= 70.0:
        return "sakura_hoodie.png"

    # Clear / Clouds
    if main == "Clear":
        if temp_f is not None and temp_f >= 80.0:
            return "sakura_sunny.png"  # swimsuit + shades
        return "sakura_cloudy.png" if temp_f is not None and temp_f < 55.0 else "sakura_sunny.png"

    if main == "Clouds":
        return "sakura_cloudy.png"

    # Fallback
    return _SAKURA_MAP.get(main, "sakura_sunny.png")

# ------------ Main compositor ------------
def compose_weather_dashboard(data: dict) -> Image.Image:
    """Return an 800x480 RGB image with current + 3-day forecast and Sakura bubble."""
    canvas = Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    # Extract weather pieces
    current = data.get("current", {})
    daily = data.get("daily", [])[:4]  # today + next 3
    tz = data.get("timezone", "")

    # Header
    now_ts = current.get("dt", time.time())
    try:
        now = datetime.fromtimestamp(now_ts)
    except Exception:
        now = datetime.now()
    header = now.strftime(f"%a %b %d  •  {tz or 'Local'}")
    draw.text((20, 18), header, font=FONT_INFO_SM, fill=(20, 20, 40))

    # Current conditions (left)
    wlist = current.get("weather", [{"id": 800, "main": "Clear", "description": "clear"}])
    wid = wlist[0].get("id", 800)
    main = wlist[0].get("main", "Clear")
    desc = wlist[0].get("description", "")
    icon_key = owm_icon_to_simple(wid, main, desc)

    temp = current.get("temp", 0)
    feels = current.get("feels_like", temp)
    units_sym = "°C" if OWM_UNITS == "metric" else "°F"


    left_x = 20
    cur_y = 60
    icon_sz = 96

    icon = load_icon(icon_key, icon_sz)
    if icon is not None:
        canvas.paste(icon, (left_x, cur_y), icon)
    else:
        draw.rounded_rectangle([left_x, cur_y, left_x + icon_sz, cur_y + icon_sz], radius=18, outline=(200, 200, 220), width=3)

    tx = left_x + icon_sz + 16
    draw.text((tx, cur_y), f"{round(temp) if isinstance(temp, (int, float)) else temp}{units_sym}", font=FONT_INFO, fill=(0, 0, 0))
    draw.text((tx, cur_y + 42), main, font=FONT_INFO_SM, fill=(40, 40, 60))
    if isinstance(feels, (int, float)):
        draw.text((tx, cur_y + 72), f"Feels {round(feels)}{units_sym}", font=FONT_INFO_SM, fill=(60, 60, 80))

    # Forecast cards (next 3 days)
    card_w = 200
    gap = 12
    start_x = 20
    start_y = 200
    # Pastel outline colors per condition (subtle, e-ink friendly)
    pastel = {
        "sun":      (255, 210, 90),   # warm yellow
        "clouds":   (200, 200, 220),  # soft gray-lavender
        "rain":     (150, 190, 240),  # pastel blue
        "drizzle":  (160, 200, 245),  # lighter blue
        "snow":     (200, 230, 255),  # icy blue
        "mist":     (210, 210, 230),  # very soft gray
        "thunder":  (240, 180, 120),  # muted amber
    }
    for i, day in enumerate(daily[1:4], start=0):
        x = start_x + i * (card_w + gap)
        y = start_y
        dt = datetime.fromtimestamp(day.get("dt", time.time()))
        name = dt.strftime("%a")
        w = day.get("weather", [{"id": 800, "main": "Clear", "description": ""}])[0]
        i_key = owm_icon_to_simple(w.get("id", 800), w.get("main", "Clear"), w.get("description", ""))
        # Choose outline color based on icon key
        outline_col = pastel.get(i_key, (230, 230, 240))
        draw.rounded_rectangle([x, y, x + card_w, y + 140], radius=16, outline=outline_col, width=4, fill=None)
        ic = load_icon(i_key, 48)
        tmax = day.get("temp", {}).get("max")
        tmin = day.get("temp", {}).get("min")

        draw.text((x + 14, y + 12), name, font=FONT_INFO_SM, fill=(30, 30, 50))
        if ic:
            canvas.paste(ic, (x + 14, y + 42), ic)
        else:
            draw.rounded_rectangle([x + 14, y + 42, x + 62, y + 90], radius=10, outline=(210, 210, 230), width=2)
        if isinstance(tmax, (int, float)):
            draw.text((x + 80, y + 50), f"{round(tmax)}{units_sym}", font=FONT_INFO_SM, fill=(0, 0, 0))
        if isinstance(tmin, (int, float)):
            draw.text((x + 80, y + 80), f"{round(tmin)}{units_sym}", font=FONT_INFO_SM, fill=(90, 90, 110))

    # Sakura sprite + wrapped speech bubble via shared module
    comment = sakura_comment(main, temp, desc)
    sakura_add(
        canvas,
        text=comment,
        main=main,
        temp=temp,
        units=OWM_UNITS,
        override=SAKURA_EMOTE,
        position="bottom-right",
        target_h=180,
        bubble_max_w=420,
    )

    return canvas

def display_on_epd(img: Image.Image):
    if epd_driver is None:
        logging.warning("[dash_weather] No EPD driver; saving preview to out_weather.png")
        img.save("out_weather.png")
        return
    try:
        epd = epd_driver.EPD()
        epd.init()
        logging.info("Displaying on EPD (single refresh)…")
        epd.display(epd.getbuffer(img))
        epd.sleep()
        logging.info("Done. EPD sleeping.")
    except Exception as e:
        logging.error("[dash_weather] EPD error: %s — saving preview to out_weather.png", e)
        img.save("out_weather.png")


# Convenience wrapper: use cache if fresh, else fetch and cache
def get_weather() -> dict:
    cached = load_cache(WEATHER_CACHE, CACHE_TTL)
    if cached is not None:
        return cached
    logging.info("[dash_weather] fetching weather (no fresh cache)…")
    data = fetch_weather()
    save_cache(WEATHER_CACHE, data)
    return data

def main():
    data = get_weather()
    logging.info("[dash_weather] composing dashboard…")
    dash = compose_weather_dashboard(data)
    logging.info("[dash_weather] displaying…")
    display_on_epd(dash)

def fetch_weather_3_0():
    """Fetch using One Call 3.0 (paid). Returns native OneCall 3.0 JSON or raises for non-200."""
    if not (OWM_API_KEY and OWM_LAT and OWM_LON):
        raise RuntimeError("Set OWM_API_KEY, OWM_LAT, OWM_LON in env.")
    params = {
        "lat": OWM_LAT,
        "lon": OWM_LON,
        "appid": OWM_API_KEY,
        "units": OWM_UNITS,
        "exclude": "minutely,hourly,alerts",
    }
    r = requests.get("https://api.openweathermap.org/data/3.0/onecall", params=params, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()

def fetch_weather_2_5():
    """Fetch using free 2.5 endpoints (current + 5 day / 3 hour forecast) and normalize to OneCall-like."""
    if not (OWM_API_KEY and OWM_LAT and OWM_LON):
        raise RuntimeError("Set OWM_API_KEY, OWM_LAT, OWM_LON in env.")
    # Current weather
    params_c = {"lat": OWM_LAT, "lon": OWM_LON, "appid": OWM_API_KEY, "units": OWM_UNITS}
    rc = requests.get("https://api.openweathermap.org/data/2.5/weather", params=params_c, headers=HEADERS, timeout=15)
    rc.raise_for_status()
    cur = rc.json()
    # 5 day / 3 hour forecast
    rf = requests.get("https://api.openweathermap.org/data/2.5/forecast", params=params_c, headers=HEADERS, timeout=15)
    rf.raise_for_status()
    fc = rf.json()

    # Normalize
    now = int(cur.get("dt", time.time()))
    tz_offset = cur.get("timezone", 0)  # seconds offset
    tz_name = cur.get("name") or fc.get("city", {}).get("name", "")
    current = {
        "dt": now,
        "temp": cur.get("main", {}).get("temp"),
        "feels_like": cur.get("main", {}).get("feels_like", cur.get("main", {}).get("temp")),
        "weather": cur.get("weather", [{"id":800,"main":"Clear","description":""}]),
    }

    # Build daily aggregates for next 3 days from forecast list
    from collections import defaultdict, Counter
    buckets = defaultdict(list)
    for item in fc.get("list", []):
        ts = item.get("dt")
        if ts is None:
            continue
        day = datetime.utcfromtimestamp(ts + tz_offset).date()
        buckets[day].append(item)

    today = datetime.utcfromtimestamp(now + tz_offset).date()
    days_sorted = sorted([d for d in buckets.keys() if d >= today])
    # Create up to 4 entries: today + next 3
    daily = []
    for d in days_sorted[:4]:
        entries = buckets[d]
        if not entries:
            continue
        temps = [e.get("main", {}).get("temp") for e in entries if e.get("main", {}).get("temp") is not None]
        tmin = min(temps) if temps else None
        tmax = max(temps) if temps else None
        # choose representative weather by most common main
        mains = [ (w.get("id",800), w.get("main","Clear"), w.get("description",""))
                  for e in entries for w in e.get("weather",[]) ]
        if mains:
            id_counts = Counter([m[0] for m in mains])
            top_id = id_counts.most_common(1)[0][0]
            top_tuple = next(m for m in mains if m[0]==top_id)
            rep_weather = [{"id": top_tuple[0], "main": top_tuple[1], "description": top_tuple[2]}]
        else:
            rep_weather = [{"id":800,"main":"Clear","description":""}]

        # dt: noon local if available, else first entry
        noon_entry = None
        for e in entries:
            h = datetime.utcfromtimestamp(e["dt"] + tz_offset).hour
            if 11 <= h <= 13:
                noon_entry = e
                break
        dt_rep = noon_entry["dt"] if noon_entry else entries[0]["dt"]

        daily.append({
            "dt": dt_rep,
            "temp": {"min": tmin, "max": tmax},
            "weather": rep_weather,
        })

    return {
        "timezone": tz_name,
        "current": current,
        "daily": daily,
    }

def fetch_weather():
    """Try One Call 3.0; on 401/403 fall back to free 2.5 endpoints and normalize."""
    try:
        return fetch_weather_3_0()
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status in (401, 403):
            logging.warning("One Call 3.0 unauthorized (%s). Falling back to free 2.5 endpoints.", status)
            return fetch_weather_2_5()
        raise


if __name__ == "__main__":
    main()