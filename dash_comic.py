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

# Sakura-chan art (separate PNGs per expression) under ./img/
SAKURA_EMOTE = os.environ.get("SAKURA_EMOTE", "happy")  # e.g., happy, worried, sleepy, excited
SAKURA_DIR = Path("img")
SAKURA_PNG = SAKURA_DIR / f"sakura_{SAKURA_EMOTE}.png"  # default: img/sakura_happy.png

FONT_DIR = Path("fonts")

# Dashboard/info text font
FONT_INFO = ImageFont.truetype(str(FONT_DIR / "MPLUSRounded1c-Regular.ttf"), 28)

# Sakura’s speech bubble font
FONT_SAKURA = ImageFont.truetype(str(FONT_DIR / "Fredoka-Regular.ttf"), 20)

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

    # Sakura bubble bottom-right
    bubble_w, bubble_h = 360, 70
    bx = WIDTH - bubble_w - 12
    by = HEIGHT - bubble_h - 12
    # rounded rectangle background
    r = 12
    draw.rounded_rectangle([bx, by, bx + bubble_w, by + bubble_h], radius=r, fill=(255, 245, 255), outline=(230, 200, 230), width=2)
    text = comment or "Sakura: What a funny Calvin & Hobbes day! Nyaa~"
    draw.text((bx + 12, by + 12), text, font=FONT_SAKURA, fill=(60, 20, 80))

    # Sakura PNG overlay (bottom-right), scaled to a friendly height
    try:
        sak_path = SAKURA_PNG if SAKURA_PNG.exists() else (SAKURA_DIR / "sakura_happy.png")
        if sak_path.exists():
            sak = Image.open(str(sak_path)).convert("RGBA")
            target_h = min(180, HEIGHT - 16)  # keep her around 150-180px tall
            scale = target_h / sak.height
            sak_w = int(sak.width * scale)
            sak_h = int(sak.height * scale)
            sak = sak.resize((sak_w, sak_h), Image.LANCZOS)
            # place her at the bottom-right, overlapping bubble slightly
            sak_x = WIDTH - sak_w - 8
            sak_y = HEIGHT - sak_h - 8
            canvas.paste(sak, (sak_x, sak_y), sak)
    except Exception as e:
        logging.warning("Failed to draw sakura overlay: %s", e)

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
