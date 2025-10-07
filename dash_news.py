import logging
import os
import sys
from PIL import Image, ImageDraw, ImageFont
import time
import json
import requests
import feedparser
from datetime import datetime, timedelta
from pathlib import Path
from io import BytesIO
import html
import re
from typing import List, Dict, Optional

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logging.info("[dash_news] starting up…")

from dotenv import load_dotenv, find_dotenv
dotenv_path = find_dotenv(usecwd=True)
load_dotenv(dotenv_path=dotenv_path)
logging.info("[dash_news] dotenv loaded from: %s", dotenv_path if dotenv_path else "<none>")

# RSS Feed configuration
RSS_FEEDS = {
    "gaming": [
        "https://www.pcgamer.com/rss/",
        "https://www.gamespot.com/feeds/news/",
        "https://kotaku.com/rss",
        "https://www.polygon.com/rss/index.xml",
        "https://feeds.feedburner.com/RockPaperShotgun",
    ],
    "tech": [
        "https://www.theverge.com/rss/index.xml",
        "https://feeds.arstechnica.com/arstechnica/index/",
        "https://techcrunch.com/feed/",
        "https://www.wired.com/feed/rss",
        "https://feeds.feedburner.com/thenextweb",
    ]
}

os.environ.setdefault("GPIOZERO_PIN_FACTORY", "lgpio")

EPD_LIB = "./lib"
if os.path.exists(EPD_LIB):
    sys.path.append(EPD_LIB)

# EPD driver will be imported lazily when needed for display
epd_driver = None

# Basic constants
WIDTH, HEIGHT = 800, 480
CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)
NEWS_CACHE = CACHE_DIR / "news.json"
CACHE_TTL = timedelta(minutes=30)  # Cache news for 30 minutes
HEADERS = {"User-Agent": "SakuraNews/1.0 (personal use)"}

# Allow overriding cache TTL via env (minutes)
NEWS_CACHE_TTL_MIN = int(os.environ.get("NEWS_CACHE_TTL_MIN", "30"))
CACHE_TTL = timedelta(minutes=NEWS_CACHE_TTL_MIN)

# No Sakura integration

def load_cache(path: Path, ttl: timedelta) -> dict | None:
    """Load cached news data if it's still fresh."""
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
            logging.info("[dash_news] using cached news (age: %.0fs)", age)
            return data
        else:
            logging.info("[dash_news] cache stale (age: %.0fs > %.0fs)", age, ttl.total_seconds())
    except Exception as e:
        logging.warning("[dash_news] failed to load cache: %s", e)
    return None

def save_cache(path: Path, payload: dict) -> None:
    """Save news data to cache with timestamp."""
    try:
        payload = dict(payload)
        payload["_ts"] = datetime.now().timestamp()
        path.write_text(json.dumps(payload))
        logging.info("[dash_news] wrote news cache → %s", path)
    except Exception as e:
        logging.warning("[dash_news] failed to write cache: %s", e)

# Fonts
FONT_DIR = Path("fonts")
try:
    FONT_HEADER = ImageFont.truetype(str(FONT_DIR / "MPLUSRounded1c-Regular.ttf"), 28)
    FONT_TITLE = ImageFont.truetype(str(FONT_DIR / "MPLUSRounded1c-Regular.ttf"), 20)
    FONT_SOURCE = ImageFont.truetype(str(FONT_DIR / "MPLUSRounded1c-Regular.ttf"), 16)
    FONT_SUMMARY = ImageFont.truetype(str(FONT_DIR / "MPLUSRounded1c-Regular.ttf"), 14)
    FONT_SAKURA = ImageFont.truetype(str(FONT_DIR / "Fredoka-Regular.ttf"), 18)
except Exception as e:
    logging.warning("[dash_news] font load failed (%s); falling back to default PIL font", e)
    FONT_HEADER = FONT_TITLE = FONT_SOURCE = FONT_SUMMARY = FONT_SAKURA = ImageFont.load_default()
logging.info("[dash_news] fonts loaded: MPLUSRounded1c + Fredoka")

def clean_html(text: str) -> str:
    """Remove HTML tags and decode entities from text."""
    if not text:
        return ""
    # Decode HTML entities
    text = html.unescape(text)
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text

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

def truncate_text(text: str, max_length: int) -> str:
    """Truncate text to max_length and add ellipsis if needed."""
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + "..."

def fetch_rss_feed(url: str) -> List[Dict]:
    """Fetch and parse a single RSS feed."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
        
        articles = []
        for entry in feed.entries[:5]:  # Limit to 5 articles per feed
            title = clean_html(entry.get('title', ''))
            summary = clean_html(entry.get('summary', ''))
            link = entry.get('link', '')
            
            # Extract source name from URL or feed title
            source = feed.feed.get('title', 'Unknown Source')
            if 'pcgamer' in url.lower():
                source = "PC Gamer"
            elif 'gamespot' in url.lower():
                source = "GameSpot"
            elif 'kotaku' in url.lower():
                source = "Kotaku"
            elif 'polygon' in url.lower():
                source = "Polygon"
            elif 'rockpapershotgun' in url.lower():
                source = "Rock Paper Shotgun"
            elif 'theverge' in url.lower():
                source = "The Verge"
            elif 'arstechnica' in url.lower():
                source = "Ars Technica"
            elif 'techcrunch' in url.lower():
                source = "TechCrunch"
            elif 'wired' in url.lower():
                source = "Wired"
            elif 'thenextweb' in url.lower():
                source = "The Next Web"
            
            if title:
                articles.append({
                    'title': title,
                    'summary': summary,
                    'source': source,
                    'link': link,
                    'category': 'gaming' if any(game in url.lower() for game in ['pcgamer', 'gamespot', 'kotaku', 'polygon', 'rockpapershotgun']) else 'tech'
                })
        
        return articles
    except Exception as e:
        logging.warning("[dash_news] failed to fetch feed %s: %s", url, e)
        return []

def fetch_all_news() -> Dict:
    """Fetch news from all configured RSS feeds."""
    all_articles = []
    
    for category, feeds in RSS_FEEDS.items():
        logging.info("[dash_news] fetching %s news from %d feeds", category, len(feeds))
        for feed_url in feeds:
            articles = fetch_rss_feed(feed_url)
            all_articles.extend(articles)
            time.sleep(1)  # Be nice to RSS servers
    
    # Sort by category and take top articles
    gaming_articles = [a for a in all_articles if a['category'] == 'gaming'][:6]
    tech_articles = [a for a in all_articles if a['category'] == 'tech'][:6]
    
    return {
        'gaming': gaming_articles,
        'tech': tech_articles,
        'timestamp': datetime.now().isoformat()
    }

# Sakura functions removed - using full screen space instead

def compose_news_dashboard(data: Dict) -> Image.Image:
    """Create the news dashboard with two boxes for gaming and tech headlines."""
    canvas = Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    
    # Header
    now = datetime.now()
    header = f"News Update • {now.strftime('%a %b %d, %H:%M')}"
    draw.text((20, 20), header, font=FONT_HEADER, fill=(20, 20, 40))
    
    # Use full screen space - no Sakura reservation
    content_width = WIDTH - 40
    content_height = HEIGHT - 80  # Just header space
    
    # Two boxes side by side
    box_width = (content_width - 20) // 2  # 20px gap between boxes
    box_height = content_height
    
    y_start = 70
    
    # Gaming News Box (left)
    gaming_box_x = 20
    gaming_box_y = y_start
    draw.rounded_rectangle(
        [(gaming_box_x, gaming_box_y), (gaming_box_x + box_width, gaming_box_y + box_height)],
        radius=15,
        outline=(180, 140, 200),
        width=3,
        fill=(250, 240, 255)
    )
    
    # Gaming header
    draw.text((gaming_box_x + 15, gaming_box_y + 15), "🎮 Gaming", font=FONT_HEADER, fill=(80, 40, 120))
    
    # Gaming articles
    gaming_articles = data.get('gaming', [])
    if gaming_articles:
        for i, article in enumerate(gaming_articles[:4]):  # Show up to 4 articles
            article_y = gaming_box_y + 60 + (i * 85)
            if article_y + 80 > gaming_box_y + box_height - 20:
                break
                
            # Article title with wrapping
            title_lines = wrap_text_to_width(article['title'], FONT_TITLE, box_width - 30, draw)
            title_y = article_y
            for line in title_lines[:3]:  # Max 3 lines for title
                draw.text((gaming_box_x + 15, title_y), line, font=FONT_TITLE, fill=(60, 20, 100))
                title_y += 20
            
            # Source
            source = article['source']
            draw.text((gaming_box_x + 15, title_y + 5), f"• {source}", font=FONT_SOURCE, fill=(100, 60, 140))
    else:
        draw.text((gaming_box_x + 15, gaming_box_y + 60), "No gaming news", font=FONT_TITLE, fill=(120, 120, 140))
    
    # Tech News Box (right)
    tech_box_x = gaming_box_x + box_width + 20
    tech_box_y = y_start
    draw.rounded_rectangle(
        [(tech_box_x, tech_box_y), (tech_box_x + box_width, tech_box_y + box_height)],
        radius=15,
        outline=(140, 180, 220),
        width=3,
        fill=(240, 250, 255)
    )
    
    # Tech header
    draw.text((tech_box_x + 15, tech_box_y + 15), "💻 Tech", font=FONT_HEADER, fill=(40, 80, 120))
    
    # Tech articles
    tech_articles = data.get('tech', [])
    if tech_articles:
        for i, article in enumerate(tech_articles[:4]):  # Show up to 4 articles
            article_y = tech_box_y + 60 + (i * 85)
            if article_y + 80 > tech_box_y + box_height - 20:
                break
                
            # Article title with wrapping
            title_lines = wrap_text_to_width(article['title'], FONT_TITLE, box_width - 30, draw)
            title_y = article_y
            for line in title_lines[:3]:  # Max 3 lines for title
                draw.text((tech_box_x + 15, title_y), line, font=FONT_TITLE, fill=(20, 60, 100))
                title_y += 20
            
            # Source
            source = article['source']
            draw.text((tech_box_x + 15, title_y + 5), f"• {source}", font=FONT_SOURCE, fill=(60, 100, 140))
    else:
        draw.text((tech_box_x + 15, tech_box_y + 60), "No tech news", font=FONT_TITLE, fill=(120, 120, 140))
    
    return canvas

def display_on_epd(img: Image.Image):
    """Display the news dashboard on e-ink display."""
    global epd_driver
    
    if epd_driver is None:
        try:
            from waveshare_epd import epd7in3e as epd_driver
            logging.info("[dash_news] Waveshare EPD driver loaded")
        except Exception as e:
            logging.warning("[dash_news] EPD driver unavailable (%s) — saving preview to out_news.png", e)
            img.save("out_news.png")
            return
    
    try:
        epd = epd_driver.EPD()
        epd.init()
        logging.info("Displaying news on EPD (single refresh)…")
        epd.display(epd.getbuffer(img))
        epd.sleep()
        logging.info("Done. EPD sleeping.")
    except Exception as e:
        logging.error("[dash_news] EPD error: %s — saving preview to out_news.png", e)
        img.save("out_news.png")

def get_news() -> Dict:
    """Get news data, using cache if available."""
    cached = load_cache(NEWS_CACHE, CACHE_TTL)
    if cached is not None:
        return cached
    
    logging.info("[dash_news] fetching fresh news (no cache)…")
    data = fetch_all_news()
    save_cache(NEWS_CACHE, data)
    return data

def main():
    """Main function to run the news dashboard."""
    data = get_news()
    logging.info("[dash_news] composing dashboard…")
    dash = compose_news_dashboard(data)
    logging.info("[dash_news] displaying…")
    display_on_epd(dash)

if __name__ == "__main__":
    main()
