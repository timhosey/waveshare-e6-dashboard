#!/usr/bin/env python3
"""
dash_comic.py
- Downloads one Calvin & Hobbes strip per day, caches it.
- Renders into 800x480 with Sakura-chan comment and optional sakura.png overlay.
- Displays one single full refresh to Waveshare E6 (epd7in3e).
"""
import os
import sys
import time
import random
import logging
from datetime import datetime, timedelta
from pathlib import Path
from io import BytesIO

import requests
from PIL import Image, ImageDraw, ImageFont
from sakura import add_to_canvas as sakura_add

# Attempt to import comics wrapper; if not available we'll fallback to scraping
try:
    import comics
except Exception:
    comics = None

from bs4 import BeautifulSoup

os.environ.setdefault("GPIOZERO_PIN_FACTORY", "lgpio")

# Waveshare driver path (adjust if your lib is elsewhere)
EPD_LIB = "./lib"
if os.path.exists(EPD_LIB):
    sys.path.append(EPD_LIB)
from waveshare_epd import epd7in3e as epd_driver

# === Config ===
COMIC_SLUG = "calvinandhobbes"   # GoComics slug
STRIP_DIR = Path("strips")
STRIP_DIR.mkdir(exist_ok=True)
WIDTH, HEIGHT = 800, 480
CACHE_TTL = timedelta(hours=24)  # don't re-download until cached file older than this

# Sakura override (set SAKURA_EMOTE to force a specific outfit; otherwise handled in sakura.py)
SAKURA_OVERRIDE = os.environ.get("SAKURA_EMOTE", "auto")

FONT_DIR = Path("fonts")

# Dashboard/info text font
FONT_INFO = ImageFont.truetype(str(FONT_DIR / "MPLUSRounded1c-Regular.ttf"), 28)

HEADERS = {
    "User-Agent": "SakuraDash/1.0 (+https://example.local) - personal use"
}

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


# === Helpers ===
def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def cached_path_for(date_str):
    return STRIP_DIR / f"{date_str}.png"


def is_stale(path: Path):
    if not path.exists():
        return True
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return (datetime.now() - mtime) > CACHE_TTL


def pick_random_archive():
    files = sorted([p for p in STRIP_DIR.glob("*.png")])
    if not files:
        return None
    return random.choice(files)


# === Fetchers ===
def fetch_with_comics(date_str):
    """Use the `comics` package correctly. Returns PIL.Image or None."""
    if comics is None:
        return None
    try:
        logging.info("Trying `comics` package for %s", date_str)
        ch = comics.search(COMIC_SLUG, date=date_str)  # returns a Comic object
        content = ch.stream()  # raw bytes of the image
        return Image.open(BytesIO(content)).convert("RGB")
    except Exception as e:
        logging.warning("comics package fetch failed: %s", e)
        return None


def fetch_from_gocomics(date_str):
    """Scrape GoComics page for the date; fragile but useful as fallback."""
    try:
        logging.info("Scraping GoComics for %s", date_str)
        url = f"https://www.gocomics.com/{COMIC_SLUG}/{date_str.replace('-', '/')}"
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        # image is usually in <picture class="item-comic-image"> <img src="...">
        img_tag = soup.select_one("picture[itemprop='image'] img") or soup.select_one("picture img")
        if not img_tag or not img_tag.get("src"):
            # try meta og:image
            meta = soup.find("meta", property="og:image")
            if meta and meta.get("content"):
                img_url = meta["content"]
            else:
                logging.warning("Could not find comic image on page.")
                return None
        else:
            img_url = img_tag["src"]
        logging.info("Found image URL: %s", img_url)
        r2 = requests.get(img_url, headers=HEADERS, timeout=15)
        r2.raise_for_status()
        from io import BytesIO
        return Image.open(BytesIO(r2.content)).convert("RGB")
    except Exception as e:
        logging.warning("GoComics scrape failed: %s", e)
        return None


def get_strip_for_date(date_str):
    """Return a PIL.Image for the given date (cached or freshly downloaded); or None."""
    p = cached_path_for(date_str)
    if not is_stale(p):
        logging.info("Using cached strip: %s", p)
        return Image.open(p).convert("RGB")

    # Try comics package first
    img = fetch_with_comics(date_str)
    if img is None:
        img = fetch_from_gocomics(date_str)

    if img is not None:
        try:
            p.parent.mkdir(exist_ok=True, parents=True)
            img.save(p, format="PNG")
            logging.info("Saved strip to cache: %s", p)
        except Exception as e:
            logging.warning("Failed to save cached strip: %s", e)
        return img

    # fallback: pick random local archive
    fallback = pick_random_archive()
    if fallback:
        logging.info("Using fallback archived strip: %s", fallback)
        return Image.open(fallback).convert("RGB")

    logging.error("No strip available for %s", date_str)
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
def compose_dashboard(strip_img: Image.Image, comment: str = None):
    """Return an 800x480 RGB image with strip and Sakura bubble/mascot."""
    canvas = Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))
    # Resize strip to fit width (800) while preserving aspect ratio
    sw, sh = strip_img.size
    scale = min(WIDTH / sw, (HEIGHT - 80) / sh)  # leave some space for bubble/mascot
    nw, nh = int(sw * scale), int(sh * scale)
    strip_resized = strip_img.resize((nw, nh), Image.LANCZOS)
    # Paste centered horizontally, top-aligned with small margin
    x = (WIDTH - nw) // 2
    y = 8
    canvas.paste(strip_resized, (x, y))

    draw = ImageDraw.Draw(canvas)

    # Sakura sprite + wrapped speech bubble via shared module
    text = comment or "Sakura: What a funny Calvin & Hobbes day! Nyaa~"
    sakura_add(
        canvas,
        text=text,
        main=None,           # not weather-based here
        temp=None,
        units="metric",
        override=SAKURA_OVERRIDE,
        position="bottom-right",
        target_h=180,
        bubble_max_w=360,
    )

    return canvas


# === EPD display ===
def display_on_epd(img: Image.Image):
    """Init device, display once, and sleep. If driver not present, save locally."""
    if epd_driver is None:
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
    date_str = today_str()
    strip = get_strip_for_date(date_str)
    if strip is None:
        # Return a placeholder image if no strip available
        canvas = Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))
        draw = ImageDraw.Draw(canvas)
        draw.text((20, 20), "No comic strip available for today", font=FONT_TEXT, fill=(100, 100, 100))
        return canvas
    
    comment = f"Sakura: Here's today's strip — enjoy, Tim! ({date_str})"
    return compose_dashboard(strip, comment=comment)

# === Main ===
def main():
    date_str = today_str()
    logging.info("Requested date: %s", date_str)
    strip = get_strip_for_date(date_str)
    if strip is None:
        logging.error("No strip available; exiting.")
        sys.exit(1)

    # create a small comment based on date or a canned line (you can extend this)
    comment = f"Sakura: Here's today's strip — enjoy, Tim! ({date_str})"
    dash_img = compose_dashboard(strip, comment=comment)
    display_on_epd(dash_img)


if __name__ == "__main__":
    main()
