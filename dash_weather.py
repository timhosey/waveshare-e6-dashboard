import logging
import os
import sys
from PIL import Image, ImageDraw, ImageFont
import time
import json
import requests
from datetime import datetime, timedelta
from pathlib import Path
from io import BytesIO
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logging.info("[dash_weather] starting up…")

os.environ.setdefault("GPIOZERO_PIN_FACTORY", "lgpio")
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

# ... [assume other imports and code here]

# After creating fonts, add:
logging.info("[dash_weather] fonts loaded: MPLUSRounded1c + Fredoka")

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

def main():
    logging.info("[dash_weather] fetching weather…")
    data = fetch_weather()
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