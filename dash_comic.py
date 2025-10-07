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

# Sakura override (set SAKURA_EMOTE to force a specific outfit; otherwise handled in sakura.py)
SAKURA_OVERRIDE = os.environ.get("SAKURA_EMOTE", "auto")

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
    """Get a random comic number (excluding #0 and #404)."""
    latest = get_latest_comic_number()
    # Exclude comic 0 (special) and 404 (not found)
    valid_numbers = [i for i in range(1, latest + 1) if i not in [0, 404]]
    return random.choice(valid_numbers)


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


def get_comic_data(comic_num):
    """Get XKCD comic data (cached or freshly downloaded)."""
    p = cached_path_for(comic_num)
    
    # Check cache first
    if not is_stale(p):
        try:
            logging.info("Using cached comic data: %s", p)
            with open(p, 'r') as f:
                cached_data = json.load(f)
            # Reconstruct the PIL image from cached data
            if 'img_data' in cached_data:
                img_data = cached_data['img_data']
                img_bytes = bytes(img_data)
                cached_data['img'] = Image.open(BytesIO(img_bytes)).convert("RGB")
                return cached_data
        except Exception as e:
            logging.warning("Failed to load cached comic data: %s", e)
    
    # Fetch fresh data
    comic_data = fetch_xkcd_comic(comic_num)
    if comic_data is not None:
        try:
            # Save to cache (excluding the PIL image)
            cache_data = dict(comic_data)
            if 'img' in cache_data:
                # Convert PIL image to bytes for caching
                img_buffer = BytesIO()
                cache_data['img'].save(img_buffer, format='PNG')
                cache_data['img_data'] = list(img_buffer.getvalue())
                del cache_data['img']  # Remove PIL object
            
            p.parent.mkdir(exist_ok=True, parents=True)
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


# === Compose dashboard image ===
def compose_dashboard(comic_data: dict):
    """Return an 800x480 RGB image with XKCD comic and alt text."""
    canvas = Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    
    # Add colorful header with comic info
    title = comic_data.get("title", "XKCD Comic")
    comic_num = comic_data.get("num", "?")
    date = comic_data.get("date", "")
    header = f"XKCD #{comic_num}: {title}"
    draw.text((20, 10), header, font=FONT_TITLE, fill=(220, 100, 40))  # Orange header
    
    # Add date below header
    if date:
        draw.text((20, 35), date, font=FONT_TEXT, fill=(100, 120, 140))  # Gray date
    
    # Get comic image
    strip_img = comic_data.get("img")
    if strip_img is None:
        draw.text((20, 70), "No comic image available", font=FONT_TEXT, fill=(180, 60, 40))
        return canvas
    
    # Resize comic to fit width while leaving space for alt text
    sw, sh = strip_img.size
    available_height = HEIGHT - 120  # Leave space for header, date, and alt text
    scale = min(WIDTH / sw, available_height / sh)
    nw, nh = int(sw * scale), int(sh * scale)
    strip_resized = strip_img.resize((nw, nh), Image.LANCZOS)
    
    # Paste centered horizontally
    x = (WIDTH - nw) // 2
    y = 70  # Below header and date
    canvas.paste(strip_resized, (x, y))
    
    # Add colorful border around comic
    draw.rounded_rectangle([x-5, y-5, x + nw + 5, y + nh + 5], 
                          radius=8, outline=(160, 120, 200), width=3, fill=None)  # Purple border
    
    # Add alt text below the comic
    alt_text = comic_data.get("alt", "")
    if alt_text:
        # Wrap alt text to fit width
        alt_lines = wrap_text_to_width(alt_text, FONT_TEXT, WIDTH - 40, draw)
        alt_y = y + nh + 20  # Below comic with some spacing
        
        # Alt text header
        draw.text((20, alt_y), "Alt text:", font=FONT_TEXT, fill=(120, 80, 160))  # Purple header
        alt_y += 25
        
        # Alt text content
        for line in alt_lines[:4]:  # Max 4 lines to fit
            if alt_y + 20 < HEIGHT - 10:  # Make sure we don't go off screen
                draw.text((20, alt_y), line, font=FONT_TEXT, fill=(80, 80, 100))  # Gray text
                alt_y += 20

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
