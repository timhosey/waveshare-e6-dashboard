#!/usr/bin/env python3
"""
dash_motivation.py
- Shows Google Calendar events for today and tomorrow
- Displays daily Japanese word/phrase with pronunciation and meaning
- Features Sakura-chan with motivation-themed commentary
- Renders into 800x480 for Waveshare E6 (epd7in3e)
"""

import os
import sys
import time
import json
import logging
from datetime import datetime, timedelta, date
from pathlib import Path
from io import BytesIO
import random

import requests
from PIL import Image, ImageDraw, ImageFont
from sakura import add_to_canvas as sakura_add

# Attempt to import Google Calendar API (optional)
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    GOOGLE_CALENDAR_AVAILABLE = True
except ImportError:
    GOOGLE_CALENDAR_AVAILABLE = False
    logging.warning("Google Calendar API not available. Install with: pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client")

os.environ.setdefault("GPIOZERO_PIN_FACTORY", "lgpio")

# Waveshare driver path (adjust if your lib is elsewhere)
EPD_LIB = "./lib"
if os.path.exists(EPD_LIB):
    sys.path.append(EPD_LIB)

try:
    from waveshare_epd import epd7in3e as epd_driver
except ImportError:
    epd_driver = None

# === Config ===
WIDTH, HEIGHT = 800, 480
CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)

# Cache files
CALENDAR_CACHE = CACHE_DIR / "calendar.json"
JAPANESE_CACHE = CACHE_DIR / "japanese.json"
CACHE_TTL = timedelta(hours=1)  # Cache for 1 hour

# Google Calendar settings
GOOGLE_CREDENTIALS_FILE = "credentials.json"
GOOGLE_SERVICE_ACCOUNT_FILE = "service_account.json"
GOOGLE_TOKEN_FILE = "token.json"
GOOGLE_SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

# Japanese word API
JAPANESE_API_URL = "https://jwotd.mary.codes/api/v1/word"
JAPANESE_FALLBACK_WORDS = [
    {"word": "希望", "reading": "きぼう (kibou)", "meaning": "hope"},
    {"word": "努力", "reading": "どりょく (doryoku)", "meaning": "effort"},
    {"word": "勇気", "reading": "ゆうき (yuuki)", "meaning": "courage"},
    {"word": "笑顔", "reading": "えがお (egao)", "meaning": "smile"},
    {"word": "平和", "reading": "へいわ (heiwa)", "meaning": "peace"},
    {"word": "友達", "reading": "ともだち (tomodachi)", "meaning": "friend"},
    {"word": "夢", "reading": "ゆめ (yume)", "meaning": "dream"},
    {"word": "愛", "reading": "あい (ai)", "meaning": "love"},
]

# Fonts
FONT_DIR = Path("fonts")
try:
    FONT_TITLE = ImageFont.truetype(str(FONT_DIR / "MPLUSRounded1c-Regular.ttf"), 24)
    FONT_TEXT = ImageFont.truetype(str(FONT_DIR / "MPLUSRounded1c-Regular.ttf"), 18)
    FONT_SMALL = ImageFont.truetype(str(FONT_DIR / "MPLUSRounded1c-Regular.ttf"), 14)
    FONT_JAPANESE = ImageFont.truetype(str(FONT_DIR / "MPLUSRounded1c-Regular.ttf"), 20)
except Exception as e:
    logging.warning("Font loading failed (%s); using defaults", e)
    FONT_TITLE = FONT_TEXT = FONT_SMALL = FONT_JAPANESE = ImageFont.load_default()

HEADERS = {
    "User-Agent": "SakuraMotivation/1.0 (personal dashboard)"
}

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# === Helper Functions ===

def load_cache(path: Path, ttl: timedelta) -> dict | None:
    """Load cached data if it's still fresh."""
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
            logging.info("Using cached data from %s (age: %.0fs)", path.name, age)
            return data
        else:
            logging.info("Cache stale for %s (age: %.0fs > %.0fs)", path.name, age, ttl.total_seconds())
    except Exception as e:
        logging.warning("Failed to load cache %s: %s", path.name, e)
    return None

def save_cache(path: Path, payload: dict) -> None:
    """Save data to cache with timestamp."""
    try:
        payload = dict(payload)
        payload["_ts"] = datetime.now().timestamp()
        path.write_text(json.dumps(payload, indent=2))
        logging.info("Cached data to %s", path.name)
    except Exception as e:
        logging.warning("Failed to save cache %s: %s", path.name, e)

def format_time_for_display(dt_str: str) -> str:
    """Format datetime string for display."""
    try:
        # Handle both date and datetime formats
        if 'T' in dt_str:
            dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            return dt.strftime("%H:%M")
        else:
            dt = datetime.fromisoformat(dt_str)
            return dt.strftime("%a %m/%d")
    except Exception:
        return dt_str

# === Google Calendar Integration ===

def get_google_calendar_events():
    """Fetch events from Google Calendar API."""
    if not GOOGLE_CALENDAR_AVAILABLE:
        return {"events": [], "error": "Google Calendar API not available"}
    
    try:
        creds = None
        
        # Try service account first (for headless servers)
        if os.path.exists(GOOGLE_SERVICE_ACCOUNT_FILE):
            logging.info("Using service account authentication...")
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_file(
                GOOGLE_SERVICE_ACCOUNT_FILE, scopes=GOOGLE_SCOPES)
        
        # Fall back to OAuth flow (for interactive use)
        elif os.path.exists(GOOGLE_CREDENTIALS_FILE):
            logging.info("Using OAuth authentication...")
            if os.path.exists(GOOGLE_TOKEN_FILE):
                creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_FILE, GOOGLE_SCOPES)
            
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    # Check if we're in a headless environment
                    if os.environ.get('DISPLAY') is None and os.environ.get('SSH_TTY'):
                        return {"events": [], "error": "Headless environment detected. Use service account authentication instead of OAuth."}
                    
                    flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDENTIALS_FILE, GOOGLE_SCOPES)
                    creds = flow.run_local_server(port=0)
                with open(GOOGLE_TOKEN_FILE, 'w') as token:
                    token.write(creds.to_json())
        else:
            return {"events": [], "error": "No Google credentials found. Place either credentials.json (OAuth) or service_account.json (service account) in project root."}
        
        service = build('calendar', 'v3', credentials=creds)
        
        # Get events for today and tomorrow
        now = datetime.utcnow().isoformat() + 'Z'
        tomorrow = (datetime.utcnow() + timedelta(days=2)).isoformat() + 'Z'
        
        events_result = service.events().list(
            calendarId='primary',
            timeMin=now,
            timeMax=tomorrow,
            maxResults=8,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        event_list = []
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            summary = event.get('summary', 'No title')
            time_display = format_time_for_display(start)
            event_list.append({
                "time": time_display,
                "title": summary,
                "start": start
            })
        
        return {"events": event_list, "error": None}
        
    except Exception as e:
        logging.error("Google Calendar error: %s", e)
        return {"events": [], "error": str(e)}

# === Japanese Word Integration ===

def get_japanese_word():
    """Fetch daily Japanese word from API or use fallback."""
    try:
        response = requests.get(JAPANESE_API_URL, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return {
                "word": data.get("word", "N/A"),
                "reading": data.get("reading", "N/A"),
                "meaning": data.get("meaning", "N/A"),
                "source": "api"
            }
    except Exception as e:
        logging.warning("Japanese API failed: %s", e)
    
    # Fallback to random word from our list
    word_data = random.choice(JAPANESE_FALLBACK_WORDS)
    word_data["source"] = "fallback"
    return word_data

# === Data Fetching with Caching ===

def get_calendar_data():
    """Get calendar events with caching."""
    cached = load_cache(CALENDAR_CACHE, CACHE_TTL)
    if cached is not None:
        return cached
    
    logging.info("Fetching fresh calendar data...")
    data = get_google_calendar_events()
    save_cache(CALENDAR_CACHE, data)
    return data

def get_japanese_data():
    """Get Japanese word with caching."""
    cached = load_cache(JAPANESE_CACHE, timedelta(hours=24))  # Daily cache for Japanese word
    if cached is not None:
        return cached
    
    logging.info("Fetching fresh Japanese word...")
    data = get_japanese_word()
    save_cache(JAPANESE_CACHE, data)
    return data

# === Layout Functions ===

def wrap_text_to_width(text, font, max_width, draw):
    """Wrap text into lines that fit within max_width."""
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

# === Dashboard Composition ===

def compose_motivation_dashboard():
    """Create the motivation dashboard image."""
    canvas = Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    
    # Get data
    calendar_data = get_calendar_data()
    japanese_data = get_japanese_data()
    
    # Header
    today = date.today()
    header = f"Motivation Dashboard • {today.strftime('%A, %B %d')}"
    draw.text((20, 20), header, font=FONT_TITLE, fill=(40, 40, 60))
    
    # Japanese Word Section (top-right)
    jp_x = 420
    jp_y = 60
    jp_width = 360
    
    # Japanese word background
    draw.rounded_rectangle([jp_x - 10, jp_y - 10, jp_x + jp_width, jp_y + 120], 
                          radius=12, outline=(200, 200, 220), width=2, fill=(250, 250, 255))
    
    draw.text((jp_x, jp_y), "Japanese Word of the Day", font=FONT_SMALL, fill=(80, 80, 100))
    draw.text((jp_x, jp_y + 20), japanese_data["word"], font=FONT_JAPANESE, fill=(0, 0, 0))
    draw.text((jp_x, jp_y + 45), japanese_data["reading"], font=FONT_TEXT, fill=(60, 60, 80))
    draw.text((jp_x, jp_y + 70), japanese_data["meaning"], font=FONT_TEXT, fill=(80, 80, 100))
    
    # Calendar Section (left side)
    cal_x = 20
    cal_y = 80
    
    # Calendar background
    draw.rounded_rectangle([cal_x - 10, cal_y - 10, cal_x + 380, cal_y + 280], 
                          radius=12, outline=(200, 200, 220), width=2, fill=(250, 250, 255))
    
    draw.text((cal_x, cal_y), "Upcoming Events", font=FONT_TITLE, fill=(40, 40, 60))
    
    events = calendar_data.get("events", [])
    if not events:
        if calendar_data.get("error"):
            error_msg = f"Calendar error: {calendar_data['error'][:30]}..."
            draw.text((cal_x, cal_y + 30), error_msg, font=FONT_SMALL, fill=(200, 100, 100))
        else:
            draw.text((cal_x, cal_y + 30), "No upcoming events", font=FONT_TEXT, fill=(120, 120, 140))
    else:
        y_offset = cal_y + 30
        for i, event in enumerate(events[:6]):  # Show max 6 events
            if y_offset > cal_y + 250:
                break
            
            # Event time and title
            time_text = f"{event['time']}"
            title_text = event['title']
            
            # Truncate long titles
            if len(title_text) > 35:
                title_text = title_text[:32] + "..."
            
            draw.text((cal_x, y_offset), time_text, font=FONT_TEXT, fill=(0, 100, 200))
            draw.text((cal_x + 80, y_offset), title_text, font=FONT_TEXT, fill=(40, 40, 60))
            
            y_offset += 25
    
    # Motivational quote section (bottom)
    quotes = [
        "今日も頑張りましょう！ (Let's do our best today!)",
        "小さな進歩も進歩です (Small progress is still progress)",
        "一歩ずつ前に進もう (Let's move forward step by step)",
        "毎日が新しい始まり (Every day is a new beginning)",
        "笑顔は最高の化粧 (A smile is the best makeup)",
    ]
    
    quote = random.choice(quotes)
    quote_y = 380
    draw.text((20, quote_y), f"💫 {quote}", font=FONT_SMALL, fill=(100, 100, 120))
    
    # Sakura with motivation-themed commentary
    calendar_events = calendar_data.get("events", [])
    if calendar_events:
        event_count = len(calendar_events)
        if event_count > 5:
            comment = f"Sakura: Busy day ahead! You've got {event_count} events planned. Ganbatte! 💪"
        elif event_count > 2:
            comment = f"Sakura: Nice schedule today! {event_count} events to keep you productive! ✨"
        else:
            comment = f"Sakura: Relaxed day ahead with {event_count} events. Perfect time to focus! 🌸"
    else:
        comment = f"Sakura: Free day! Time to learn '{japanese_data['word']}' and chase your dreams! Nyaa~ ✨"
    
    sakura_add(
        canvas,
        text=comment,
        main=None,
        temp=None,
        units="metric",
        override="auto",  # Let Sakura pick outfit based on mood
        position="bottom-right",
        target_h=160,
        bubble_max_w=380,
    )
    
    return canvas

# === EPD Display ===

def display_on_epd(img: Image.Image):
    """Display on e-ink or save preview."""
    if epd_driver is None:
        logging.warning("Waveshare EPD driver not available — saving preview to out_motivation.png")
        img.save("out_motivation.png")
        return
    
    epd = epd_driver.EPD()
    epd.init()
    logging.info("Displaying motivation dashboard on EPD...")
    epd.display(epd.getbuffer(img))
    epd.sleep()
    logging.info("Done. EPD in sleep.")

# === Main ===

def main():
    logging.info("Creating motivation dashboard...")
    dash_img = compose_motivation_dashboard()
    display_on_epd(dash_img)
    logging.info("Motivation dashboard complete!")

if __name__ == "__main__":
    main()
