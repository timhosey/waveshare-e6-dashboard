#!/usr/bin/env python3
"""
dash_weather.py
- Fetches weather from OpenWeatherMap (current + 3-day forecast).
- Renders to 800x480 with Sakura-chan comment, word-wrapped bubble, and icon slots.
- Single full refresh to Waveshare E6 (epd7in3e).
Env:
  OWM_API_KEY   -> your OpenWeatherMap API key (required)
  OWM_LAT       -> latitude (e.g., 47.6062)
  OWM_LON       -> longitude (e.g., -122.3321)
  OWM_UNITS     -> "metric" (default) | "imperial"
  SAKURA_EMOTE  -> "happy" (default) | worried | sleepy | excited
"""
import os
import sys
import time
import json
import math
import logging
from datetime import datetime, timedelta
from pathlib import Path
from io import BytesIO

from dotenv import load_dotenv
load_dotenv()

import requests
from PIL import Image, ImageDraw, ImageFont

# --- GPIO / EPD wiring ---
os.environ.setdefault("GPIOZERO_PIN_FACTORY", "lgpio")
EPD_LIB = "./lib"
if os.path.exists(EPD_LIB):
    sys.path.append(EPD_LIB)
from waveshare_epd import epd7in3e as epd_driver

# --- Config ---
WIDTH, HEIGHT = 800, 480
CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)
WEATHER_CACHE = CACHE_DIR / "weather.json"
CACHE_TTL = timedelta(minutes=30)

FONT_DIR = Path("fonts")
FONT_INFO   = ImageFont.truetype(str(FONT_DIR / "MPLUSRounded1c-Regular.ttf"), 32)  # main numbers/labels
FONT_INFO_SM= ImageFont.truetype(str(FONT_DIR / "MPLUSRounded1c-Regular.ttf"), 22)  # small labels
FONT_SAKURA = ImageFont.truetype(str(FONT_DIR / "Fredoka-Regular.ttf"), 20)

SAKURA_EMOTE = os.environ.get("SAKURA_EMOTE", "happy")
SAKURA_DIR   = Path("img")
SAKURA_PNG   = SAKURA_DIR / f"sakura_{SAKURA_EMOTE}.png"

# Weather icon placeholders (will swap for cute PNGs later)
WEATHER_ICON_DIR = Path("img/weather")  # put future PNGs here, e.g., sun.png, rain.png, clouds.png

OWM_API_KEY = os.environ.get("OWM_API_KEY")
OWM_LAT     = os.environ.get("OWM_LAT")
OWM_LON     = os.environ.get("OWM_LON")
OWM_UNITS   = os.environ.get("OWM_UNITS", "metric")  # metric or imperial

HEADERS = {"User-Agent": "SakuraWeather/1.0 (personal use)"}
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# --- Helpers ---
def kelvin_to_c(k): return k - 273.15

def load_cache(path: Path):
    try:
        if path.exists():
            data = json.loads(path.read_text())
            ts = datetime.fromtimestamp(data.get("_ts", 0))
            if datetime.now() - ts < CACHE_TTL:
                return data
    except Exception:
        pass
    return None

def save_cache(path: Path, payload: dict):
    try:
        payload["_ts"] = time.time()
        path.write_text(json.dumps(payload))
    except Exception:
        logging.warning("Failed to write weather cache")

def fetch_weather():
    """Fetch current weather + daily forecast (3 days) from OWM One Call 3.0."""
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

def get_weather():
    cached = load_cache(WEATHER_CACHE)
    if cached:
        logging.info("Using cached weather")
        return cached
    logging.info("Fetching weather from OWM")
    data = fetch_weather()
    save_cache(WEATHER_CACHE, data)
    return data

def wrap_text_to_width(text, font, max_width, draw):
    words = text.split()
    if not words: return [""]
    lines, cur = [], words[0]
    for w in words[1:]:
        test = cur + " " + w
        if draw.textbbox((0,0), test, font=font)[2] <= max_width:
            cur = test
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines

def load_icon(name: str, size: int) -> Image.Image | None:
    """Try to load a weather icon PNG by name; returns RGBA or None."""
    p = WEATHER_ICON_DIR / f"{name}.png"
    if not p.exists(): return None
    img = Image.open(p).convert("RGBA")
    if img.height != size:
        scale = size / img.height
        img = img.resize((int(img.width*scale), size), Image.LANCZOS)
    return img

def owm_icon_to_simple(weather_id: int, main: str, desc: str) -> str:
    """Map OWM condition to a simple icon key we’ll generate later."""
    # Thunderstorm: 200-232, Drizzle: 300-321, Rain: 500-531, Snow: 600-622
    # Atmosphere (mist etc): 700-781, Clear: 800, Clouds: 801-804
    if 200 <= weather_id <= 232: return "thunder"
    if 300 <= weather_id <= 321: return "drizzle"
    if 500 <= weather_id <= 531: return "rain"
    if 600 <= weather_id <= 622: return "snow"
    if 700 <= weather_id <= 781: return "mist"
    if weather_id == 800:       return "sun"
    if 801 <= weather_id <= 804:
        return "clouds"
    # fallback
    m = main.lower()
    if "rain" in m: return "rain"
    if "snow" in m: return "snow"
    if "cloud" in m: return "clouds"
    return "sun"

# --- Drawing ---
def compose_weather_dashboard(data: dict) -> Image.Image:
    """Return an 800x480 RGB image with current + 3-day forecast and Sakura bubble."""
    canvas = Image.new("RGB", (WIDTH, HEIGHT), (255,255,255))
    draw = ImageDraw.Draw(canvas)

    # Precompute Sakura (paste after bubble)
    sak = None; sak_w = sak_h = 0; sak_x = sak_y = 0
    try:
        sak_path = SAKURA_PNG if SAKURA_PNG.exists() else (SAKURA_DIR / "sakura_happy.png")
        if sak_path.exists():
            _sak = Image.open(str(sak_path)).convert("RGBA")
            target_h = min(180, HEIGHT - 16)
            scale = target_h / _sak.height
            sak_w = int(_sak.width * scale); sak_h = int(_sak.height * scale)
            sak = _sak.resize((sak_w, sak_h), Image.LANCZOS)
            sak_x = WIDTH - sak_w - 8
            sak_y = HEIGHT - sak_h - 8
    except Exception as e:
        logging.warning("Failed to prepare Sakura: %s", e)

    # Extract pieces
    current = data.get("current", {})
    daily   = data.get("daily", [])[:4]  # today + next 3
    tz      = data.get("timezone", "")

    # Header row (location/time)
    now = datetime.fromtimestamp(current.get("dt", time.time()))
    header = now.strftime(f"%a %b %d  •  {tz or 'Local'}")
    draw.text((20, 18), header, font=FONT_INFO_SM, fill=(20,20,40))

    # Current conditions block (left)
    wlist = current.get("weather", [{"id":800,"main":"Clear","description":"clear sky"}])
    wid   = wlist[0].get("id", 800)
    main  = wlist[0].get("main","Clear")
    desc  = wlist[0].get("description","")
    icon_key = owm_icon_to_simple(wid, main, desc)

    # Temperature
    temp = current.get("temp", 0)
    feels= current.get("feels_like", temp)
    units_sym = "°C" if OWM_UNITS == "metric" else "°F"

    # Layout metrics
    left_x = 20
    cur_y  = 60
    icon_sz= 96

    icon = load_icon(icon_key, icon_sz)
    if icon is not None:
        canvas.paste(icon, (left_x, cur_y), icon)
    else:
        # placeholder rounded square
        draw.rounded_rectangle([left_x, cur_y, left_x+icon_sz, cur_y+icon_sz], radius=18, outline=(200,200,220), width=3)

    # Current text
    tx = left_x + icon_sz + 16
    draw.text((tx, cur_y),      f"{round(temp):d}{units_sym}", font=FONT_INFO,    fill=(0,0,0))
    draw.text((tx, cur_y+42),   main,                          font=FONT_INFO_SM, fill=(40,40,60))
    draw.text((tx, cur_y+72),   f"Feels {round(feels):d}{units_sym}", font=FONT_INFO_SM, fill=(60,60,80))

    # Forecast 3 cards (right/center)
    card_w = 200
    gap    = 12
    start_x= 20
    start_y= 200
    for i, day in enumerate(daily[1:4], start=0):  # next 3 days
        x = start_x + i*(card_w+gap)
        y = start_y
        draw.rounded_rectangle([x, y, x+card_w, y+140], radius=16, outline=(230,230,240), width=2, fill=(250,250,255))
        dt  = datetime.fromtimestamp(day.get("dt", time.time()))
        name= dt.strftime("%a")
        w   = day.get("weather",[{"id":800,"main":"Clear","description":""}])[0]
        idd = w.get("id",800)
        m   = w.get("main","Clear")
        i_key = owm_icon_to_simple(idd, m, w.get("description",""))
        ic = load_icon(i_key, 48)
        # day temps
        tmax = round(day.get("temp",{}).get("max", 0))
        tmin = round(day.get("temp",{}).get("min", 0))
        draw.text((x+14, y+12), name, font=FONT_INFO_SM, fill=(30,30,50))
        if ic: canvas.paste(ic, (x+14, y+42), ic)
        else:  draw.rounded_rectangle([x+14, y+42, x+62, y+90], radius=10, outline=(210,210,230), width=2)
        draw.text((x+80, y+50), f"{tmax}{units_sym}", font=FONT_INFO_SM, fill=(0,0,0))
        draw.text((x+80, y+80), f"{tmin}{units_sym}", font=FONT_INFO_SM, fill=(90,90,110))

    # Sakura bubble with wrap (avoid overlap with Sakura)
    comment = sakura_comment(main, temp, desc)
    pad_x, pad_y = 12, 10
    max_bubble_width = 420
    right_limit = (sak_x - 8) if sak else WIDTH - 8
    bubble_w = min(max_bubble_width, right_limit - 12)
    bubble_w = max(bubble_w, 180)
    inner_w  = bubble_w - 2*pad_x
    lines    = wrap_text_to_width(comment, FONT_SAKURA, inner_w, draw)
    line_h   = draw.textbbox((0,0), "Ay", font=FONT_SAKURA)[3]
    text_h   = line_h * len(lines)
    bubble_h = text_h + 2*pad_y
    bx = max(8, right_limit - bubble_w)
    by = HEIGHT - bubble_h - 12
    r = 12
    draw.rounded_rectangle([bx,by,bx+bubble_w,by+bubble_h], radius=r, fill=(255,245,255), outline=(230,200,230), width=2)
    tx, ty = bx + pad_x, by + pad_y
    for line in lines:
        draw.text((tx,ty), line, font=FONT_SAKURA, fill=(60,20,80))
        ty += line_h

    # Paste Sakura last
    if sak is not None:
        canvas.paste(sak, (sak_x, sak_y), sak)

    return canvas

def sakura_comment(main: str, temp: float, desc: str) -> str:
    units_sym = "°C" if OWM_UNITS == "metric" else "°F"
    # Simple cute rules
    m = (main or "").lower()
    if "rain" in m or "drizzle" in m:
        return f"Sakura: Umbrella time, Tim-senpai! Nyaa~ ☔ ({round(temp)}{units_sym})"
    if "snow" in m:
        return f"Sakura: Brr~ bundle up! ❄️ ({round(temp)}{units_sym})"
    if "cloud" in m:
        return f"Sakura: Cloudy cuddles day~ ☁️ ({round(temp)}{units_sym})"
    if "clear" in m or "sun" in m:
        return f"Sakura: Sunny smiles! ☀️ ({round(temp)}{units_sym})"
    return f"Sakura: {main.title()} vibes~ ({round(temp)}{units_sym})"

# --- EPD ---
def display_on_epd(img: Image.Image):
    epd = epd_driver.EPD()
    epd.init()
    logging.info("Displaying on EPD (single refresh)...")
    epd.display(epd.getbuffer(img))
    epd.sleep()
    logging.info("Done. EPD sleeping.")

def main():
    data = get_weather()
    dash = compose_weather_dashboard(data)
    display_on_epd(dash)

if __name__ == "__main__":
    main()