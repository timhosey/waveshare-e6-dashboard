import logging
import os
import sys
from PIL import Image, ImageDraw, ImageFont
from sakura import add_to_canvas as sakura_add
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
        "https://feeds.feedburner.com/oreilly/radar/",
        "https://www.theverge.com/rss/index.xml",
        "https://feeds.arstechnica.com/arstechnica/index/",
        "https://techcrunch.com/feed/",
        "https://www.wired.com/feed/rss",
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

# Sakura configuration
SAKURA_EMOTE = os.environ.get("SAKURA_EMOTE", "auto")
SAKURA_DIR = Path("img/sakura")

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

def pick_sakura_outfit(category: str, article_count: int) -> str:
    """Choose Sakura outfit based on news category and activity."""
    if SAKURA_EMOTE and SAKURA_EMOTE.lower() != 'auto':
        return f"sakura_{SAKURA_EMOTE.lower()}.png"
    
    if category == "gaming":
        if article_count >= 5:
            return "sakura_excited.png"  # Lots of gaming news!
        else:
            return "sakura_gaming.png"
    else:  # tech
        if article_count >= 5:
            return "sakura_tech.png"  # Tech enthusiast mode
        else:
            return "sakura_sunny.png"  # Default tech mode

def sakura_comment(category: str, article_count: int) -> str:
    """Generate Sakura's comment based on news category."""
    if category == "gaming":
        if article_count >= 5:
            return "Sakura: So many gaming updates! Ready to play? 🎮✨"
        elif article_count >= 3:
            return "Sakura: Gaming news is exciting today! 🎮"
        else:
            return "Sakura: Quiet gaming day~ maybe time for a marathon? 🎮"
    else:  # tech
        if article_count >= 5:
            return "Sakura: Tech world is buzzing today! So many updates! 💻⚡"
        elif article_count >= 3:
            return "Sakura: Interesting tech developments~ 💻"
        else:
            return "Sakura: Tech news is calm today~ perfect for coding! 💻"

def compose_news_dashboard(data: Dict) -> Image.Image:
    """Create the news dashboard with gaming and tech sections."""
    canvas = Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    
    # Header
    now = datetime.now()
    header = f"News Update • {now.strftime('%a %b %d, %H:%M')}"
    draw.text((20, 15), header, font=FONT_HEADER, fill=(20, 20, 40))
    
    # Draw separator line
    draw.line([(20, 55), (WIDTH-20, 55)], fill=(200, 200, 220), width=2)
    
    y_pos = 70
    section_gap = 20
    
    # Gaming News Section
    gaming_articles = data.get('gaming', [])
    draw.text((20, y_pos), "🎮 Gaming News", font=FONT_HEADER, fill=(80, 40, 120))
    y_pos += 40
    
    if gaming_articles:
        for i, article in enumerate(gaming_articles[:3]):  # Show top 3 gaming articles
            # Article card background
            card_y = y_pos
            card_height = 80
            draw.rounded_rectangle(
                [(20, card_y), (WIDTH-20, card_y + card_height)], 
                radius=12, 
                outline=(200, 180, 220), 
                width=2, 
                fill=(250, 245, 255)
            )
            
            # Title
            title = truncate_text(article['title'], 80)
            draw.text((30, card_y + 10), title, font=FONT_TITLE, fill=(60, 20, 100))
            
            # Source
            source = f"via {article['source']}"
            draw.text((30, card_y + 35), source, font=FONT_SOURCE, fill=(100, 60, 140))
            
            # Summary (if space allows)
            if article['summary']:
                summary = truncate_text(article['summary'], 120)
                draw.text((30, card_y + 55), summary, font=FONT_SUMMARY, fill=(80, 80, 100))
            
            y_pos += card_height + 10
    else:
        draw.text((30, y_pos), "No gaming news available", font=FONT_TITLE, fill=(120, 120, 140))
        y_pos += 60
    
    y_pos += section_gap
    
    # Tech News Section  
    tech_articles = data.get('tech', [])
    draw.text((20, y_pos), "💻 Tech News", font=FONT_HEADER, fill=(40, 80, 120))
    y_pos += 40
    
    if tech_articles:
        for i, article in enumerate(tech_articles[:3]):  # Show top 3 tech articles
            # Article card background
            card_y = y_pos
            card_height = 80
            draw.rounded_rectangle(
                [(20, card_y), (WIDTH-20, card_y + card_height)], 
                radius=12, 
                outline=(180, 200, 220), 
                width=2, 
                fill=(245, 250, 255)
            )
            
            # Title
            title = truncate_text(article['title'], 80)
            draw.text((30, card_y + 10), title, font=FONT_TITLE, fill=(20, 60, 100))
            
            # Source
            source = f"via {article['source']}"
            draw.text((30, card_y + 35), source, font=FONT_SOURCE, fill=(60, 100, 140))
            
            # Summary (if space allows)
            if article['summary']:
                summary = truncate_text(article['summary'], 120)
                draw.text((30, card_y + 55), summary, font=FONT_SUMMARY, fill=(80, 80, 100))
            
            y_pos += card_height + 10
    else:
        draw.text((30, y_pos), "No tech news available", font=FONT_TITLE, fill=(120, 120, 140))
        y_pos += 60
    
    # Sakura integration - determine which category has more news
    total_gaming = len(data.get('gaming', []))
    total_tech = len(data.get('tech', []))
    
    if total_gaming >= total_tech:
        category = "gaming"
        article_count = total_gaming
    else:
        category = "tech" 
        article_count = total_tech
    
    comment = sakura_comment(category, article_count)
    outfit = pick_sakura_outfit(category, article_count)
    
    sakura_add(
        canvas,
        text=comment,
        main=category.title(),
        temp=None,  # No temperature for news
        units=None,  # No units for news
        override=outfit.replace('.png', '').replace('sakura_', ''),
        position="bottom-right",
        target_h=160,
        bubble_max_w=380,
    )
    
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
