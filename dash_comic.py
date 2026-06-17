#!/usr/bin/env python3
"""
dash_comic.py
- Fetches random XKCD comic strips with alt text.
- Renders into 800x480 with colorful header and alt text below.
- Displays one single full refresh to Waveshare E6 (epd7in3e).
"""
import os
import sys
import time
import random
import logging
import json
from datetime import datetime, timedelta
from pathlib import Path
from io import BytesIO

import requests
from PIL import Image, ImageDraw, ImageFont
# Sakura integration removed for full screen usage

# XKCD API - no external dependencies needed

os.environ.setdefault("GPIOZERO_PIN_FACTORY", "lgpio")

# Waveshare driver path (adjust if your lib is elsewhere)
EPD_LIB = "./lib"
if os.path.exists(EPD_LIB):
    sys.path.append(EPD_LIB)

# EPD driver will be imported lazily when needed for display
epd_driver = None

# === Config ===
XKCD_API_BASE = "https://xkcd.com"
XKCD_JSON_API = "https://xkcd.com/info.0.json"
CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)
WIDTH, HEIGHT = 800, 480
CACHE_TTL = timedelta(hours=6)  # Cache comics for 6 hours

FONT_DIR = Path("fonts")

# Dashboard/info text font
FONT_INFO = ImageFont.truetype(str(FONT_DIR / "MPLUSRounded1c-Regular.ttf"), 28)
FONT_TITLE = ImageFont.truetype(str(FONT_DIR / "MPLUSRounded1c-Regular.ttf"), 24)
FONT_TEXT = ImageFont.truetype(str(FONT_DIR / "MPLUSRounded1c-Regular.ttf"), 20)

HEADERS = {
    "User-Agent": "XKCDDashboard/1.0 (+https://example.local) - personal use"
}

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


# === Helpers ===
def get_latest_comic_number():
    """Get the latest XKCD comic number."""
    try:
        response = requests.get(XKCD_JSON_API, headers=HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("num", 1)
    except Exception as e:
        logging.warning("Failed to get latest comic number: %s", e)
        return 2000  # Fallback to a reasonable number


def get_random_comic_number():
    """Get a random comic number (excluding #404, which returns 404)."""
    latest = get_latest_comic_number()
    num = random.randint(1, latest)
    if num == 404:
        num = 405
    return num


def cached_path_for(comic_num):
    return CACHE_DIR / f"xkcd_{comic_num}.json"


def is_stale(path: Path):
    if not path.exists():
        return True
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return (datetime.now() - mtime) > CACHE_TTL


# === Fetchers ===
def fetch_xkcd_comic(comic_num):
    """Fetch XKCD comic data and image from the API."""
    try:
        # Get comic metadata
        url = f"{XKCD_API_BASE}/{comic_num}/info.0.json"
        logging.info("Fetching XKCD comic #%d", comic_num)
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        # Download the comic image
        img_url = data.get("img")
        if not img_url:
            logging.warning("No image URL in comic data")
            return None
            
        logging.info("Downloading image: %s", img_url)
        img_response = requests.get(img_url, headers=HEADERS, timeout=15)
        img_response.raise_for_status()
        
        # Convert to PIL Image
        comic_image = Image.open(BytesIO(img_response.content)).convert("RGB")
        
        return {
            "num": data.get("num", comic_num),
            "title": data.get("title", ""),
            "alt": data.get("alt", ""),
            "img": comic_image,
            "date": f"{data.get('month', 1)}/{data.get('day', 1)}/{data.get('year', 2024)}"
        }
    except Exception as e:
        logging.warning("Failed to fetch XKCD comic #%d: %s", comic_num, e)
        return None


def cached_img_path_for(comic_num):
    return CACHE_DIR / f"xkcd_{comic_num}.png"


def get_comic_data(comic_num):
    """Get XKCD comic data (cached or freshly downloaded)."""
    p = cached_path_for(comic_num)
    img_p = cached_img_path_for(comic_num)

    # Check cache first
    if not is_stale(p):
        try:
            logging.info("Using cached comic data: %s", p)
            with open(p, 'r') as f:
                cached_data = json.load(f)
            if img_p.exists():
                cached_data['img'] = Image.open(img_p).convert("RGB")
                return cached_data
        except Exception as e:
            logging.warning("Failed to load cached comic data: %s", e)

    # Fetch fresh data
    comic_data = fetch_xkcd_comic(comic_num)
    if comic_data is not None:
        try:
            p.parent.mkdir(exist_ok=True, parents=True)
            # Save image as a real PNG file
            if 'img' in comic_data:
                comic_data['img'].save(img_p, format='PNG')
            # Save metadata without the PIL object
            cache_data = {k: v for k, v in comic_data.items() if k != 'img'}
            with open(p, 'w') as f:
                json.dump(cache_data, f)
            logging.info("Saved comic data to cache: %s", p)
        except Exception as e:
            logging.warning("Failed to save cached comic data: %s", e)

    return comic_data

def get_random_comic():
    """Get a random XKCD comic."""
    for attempt in range(3):
        comic_num = get_random_comic_number()
        logging.info("Attempting comic #%d (attempt %d/3)", comic_num, attempt + 1)
        comic_data = get_comic_data(comic_num)
        if comic_data is not None:
            return comic_data
    
    logging.error("Failed to fetch any XKCD comic")
    return None


def wrap_text_to_width(text, font, max_width, draw):
    """Wrap text into lines that fit within max_width using the provided draw+font."""
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


# Layout constants
_HEADER_Y = 65      # top of image area (below title + date)
_ALT_LINE_H = 20    # pixels per alt text line
_ALT_LABEL_H = 22   # pixels for the "Alt text:" label
_ALT_GAP = 10       # gap between image and alt text block
_ALT_MAX_LINES = 3  # cap so alt text never swamps the image
_MAX_UPSCALE = 1.5  # never blow a comic up more than 1.5× (avoids blurry pixel-doubled look)
_MIN_SCALE = 0.55   # never shrink below 55% — prefer clipping on the right to illegibility


# === Compose dashboard image ===
def compose_dashboard(comic_data: dict):
    """Return an 800x480 RGB image with XKCD comic and alt text."""
    canvas = Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    # Header
    title = comic_data.get("title", "XKCD Comic")
    comic_num = comic_data.get("num", "?")
    date = comic_data.get("date", "")
    draw.text((20, 10), f"XKCD #{comic_num}: {title}", font=FONT_TITLE, fill=(220, 100, 40))
    if date:
        draw.text((20, 35), date, font=FONT_TEXT, fill=(100, 120, 140))

    strip_img = comic_data.get("img")
    if strip_img is None:
        draw.text((20, _HEADER_Y + 10), "No comic image available", font=FONT_TEXT, fill=(180, 60, 40))
        return canvas

    alt_text = comic_data.get("alt", "")

    # Pass 1 — measure alt text so we can reserve space before placing the image.
    alt_lines = []
    if alt_text:
        alt_lines = wrap_text_to_width(alt_text, FONT_TEXT, WIDTH - 40, draw)[:_ALT_MAX_LINES]
    alt_block_h = (_ALT_GAP + _ALT_LABEL_H + len(alt_lines) * _ALT_LINE_H) if alt_lines else 0

    # Pass 2 — fit the comic into whatever height remains above the alt text block.
    img_area_h = HEIGHT - _HEADER_Y - alt_block_h
    sw, sh = strip_img.size
    scale = min(WIDTH / sw, img_area_h / sh, _MAX_UPSCALE)
    scale = max(scale, _MIN_SCALE)  # never shrink so far the comic becomes illegible
    nw, nh = int(sw * scale), int(sh * scale)

    # If _MIN_SCALE kicked in and the image is taller than the area, clip the bottom
    # (XKCD panels almost always have the punchline in the center/top).
    nh_display = min(nh, img_area_h)
    strip_resized = strip_img.resize((nw, nh), Image.LANCZOS)
    if nh_display < nh:
        strip_resized = strip_resized.crop((0, 0, nw, nh_display))

    x = max(0, (WIDTH - nw) // 2)  # center; if wider than canvas, left-align
    y = _HEADER_Y
    canvas.paste(strip_resized, (x, y))
    draw.rounded_rectangle(
        [x - 5, y - 5, x + min(nw, WIDTH) + 5, y + nh_display + 5],
        radius=8, outline=(160, 120, 200), width=3, fill=None,
    )

    # Pass 3 — draw alt text in its reserved block at the bottom.
    if alt_lines:
        alt_y = HEIGHT - alt_block_h + _ALT_GAP
        draw.text((20, alt_y), "Alt text:", font=FONT_TEXT, fill=(120, 80, 160))
        alt_y += _ALT_LABEL_H
        for line in alt_lines:
            draw.text((20, alt_y), line, font=FONT_TEXT, fill=(80, 80, 100))
            alt_y += _ALT_LINE_H

    return canvas


# === EPD display ===
def display_on_epd(img: Image.Image):
    """Init device, display once, and sleep. If driver not present, save locally."""
    global epd_driver
    
    # Import EPD driver lazily only when we actually need to display
    if epd_driver is None:
        try:
            from waveshare_epd import epd7in3e as epd_driver
        except ImportError:
            logging.warning("Waveshare EPD driver not available — saving preview to out_preview.png")
            img.save("out_preview.png")
            return

    epd = epd_driver.EPD()
    epd.init()
    # Do NOT call epd.Clear() here — single display only
    logging.info("Displaying on EPD (single refresh)...")
    epd.display(epd.getbuffer(img))
    epd.sleep()
    logging.info("Done. EPD in sleep.")

def compose_dashboard_no_display():
    """Create the comic dashboard image without displaying it on e-ink."""
    comic_data = get_random_comic()
    if comic_data is None:
        # Return a placeholder image if no comic available
        canvas = Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))
        draw = ImageDraw.Draw(canvas)
        # Add colorful header even for error case
        header = "XKCD Comic Dashboard"
        draw.text((20, 10), header, font=FONT_TITLE, fill=(220, 100, 40))  # Orange header
        draw.text((20, 50), "No comic available", font=FONT_TEXT, fill=(180, 60, 40))  # Red for error
        return canvas
    
    return compose_dashboard(comic_data)

# === Main ===
def main():
    logging.info("Fetching random XKCD comic...")
    comic_data = get_random_comic()
    
    if comic_data is None:
        logging.error("No comic available; exiting.")
        sys.exit(1)

    dash_img = compose_dashboard(comic_data)
    display_on_epd(dash_img)


if __name__ == "__main__":
    main()
