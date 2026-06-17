#!/usr/bin/env python3
"""
dash_motivation.py — Japanese Dashboard
- Word of the day (kanji + reading + meaning) from API with fallback
- Phrase of the day (Japanese + romaji + meaning) rotated daily
- Current Tokyo time and weather conditions
- Renders into 800x480 for Waveshare E6 (epd7in3e)
"""

import os
import sys
import json
import logging
from datetime import datetime, date, timedelta
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(usecwd=True))

os.environ.setdefault("GPIOZERO_PIN_FACTORY", "lgpio")

EPD_LIB = "./lib"
if os.path.exists(EPD_LIB):
    sys.path.append(EPD_LIB)

epd_driver = None

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# Tokyo timezone — zoneinfo is stdlib since Python 3.9; fall back to fixed offset
try:
    from zoneinfo import ZoneInfo
    TOKYO_TZ = ZoneInfo("Asia/Tokyo")
except ImportError:
    from datetime import timezone
    TOKYO_TZ = timezone(timedelta(hours=9))

WIDTH, HEIGHT = 800, 480
CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)

WORD_CACHE       = CACHE_DIR / "japanese_word.json"
WEATHER_CACHE    = CACHE_DIR / "tokyo_weather.json"
WORD_CACHE_TTL   = timedelta(hours=24)
WEATHER_CACHE_TTL = timedelta(minutes=30)

OWM_API_KEY = os.getenv("OWM_API_KEY")
TOKYO_LAT, TOKYO_LON = "35.6762", "139.6503"
JAPANESE_API_URL = "https://jwotd.mary.codes/api/v1/word"
HEADERS = {"User-Agent": "JapaneseDashboard/1.0 (personal use)"}

# ── Fonts ──────────────────────────────────────────────────────────────────────
FONT_DIR = Path("fonts")
try:
    FONT_HEADER = ImageFont.truetype(str(FONT_DIR / "MPLUSRounded1c-Regular.ttf"), 26)
    FONT_KANJI  = ImageFont.truetype(str(FONT_DIR / "MPLUSRounded1c-Regular.ttf"), 56)
    FONT_PHRASE = ImageFont.truetype(str(FONT_DIR / "MPLUSRounded1c-Regular.ttf"), 30)
    FONT_TEXT   = ImageFont.truetype(str(FONT_DIR / "MPLUSRounded1c-Regular.ttf"), 20)
    FONT_SMALL  = ImageFont.truetype(str(FONT_DIR / "MPLUSRounded1c-Regular.ttf"), 16)
    FONT_TIME   = ImageFont.truetype(str(FONT_DIR / "MPLUSRounded1c-Regular.ttf"), 48)
except Exception as e:
    logging.warning("Font loading failed (%s); using defaults", e)
    FONT_HEADER = FONT_KANJI = FONT_PHRASE = FONT_TEXT = FONT_SMALL = FONT_TIME = ImageFont.load_default()

# ── Phrase list (rotates daily via day ordinal) ────────────────────────────────
DAILY_PHRASES = [
    {"japanese": "よろしくお願いします",     "romaji": "Yoroshiku onegaishimasu",       "meaning": "Please treat me well / Nice to meet you"},
    {"japanese": "お疲れ様でした",           "romaji": "Otsukaresama deshita",          "meaning": "Thank you for your hard work"},
    {"japanese": "いただきます",             "romaji": "Itadakimasu",                   "meaning": "I humbly receive (said before eating)"},
    {"japanese": "ご馳走様でした",           "romaji": "Gochisousama deshita",          "meaning": "Thank you for the meal (said after eating)"},
    {"japanese": "すみません",               "romaji": "Sumimasen",                     "meaning": "Excuse me / I'm sorry to bother you"},
    {"japanese": "大丈夫ですか？",           "romaji": "Daijoubu desu ka?",             "meaning": "Are you alright?"},
    {"japanese": "もう一度お願いします",     "romaji": "Mou ichido onegaishimasu",      "meaning": "Please say that one more time"},
    {"japanese": "どこですか？",             "romaji": "Doko desu ka?",                 "meaning": "Where is it?"},
    {"japanese": "いくらですか？",           "romaji": "Ikura desu ka?",                "meaning": "How much does it cost?"},
    {"japanese": "ありがとうございます",     "romaji": "Arigatou gozaimasu",            "meaning": "Thank you very much"},
    {"japanese": "お元気ですか？",           "romaji": "Ogenki desu ka?",               "meaning": "How are you?"},
    {"japanese": "日本語が少し話せます",     "romaji": "Nihongo ga sukoshi hanasemasu", "meaning": "I can speak a little Japanese"},
    {"japanese": "わかりません",             "romaji": "Wakarimasen",                   "meaning": "I don't understand"},
    {"japanese": "頑張ってください",         "romaji": "Ganbatte kudasai",              "meaning": "Please do your best / Good luck"},
    {"japanese": "お先に失礼します",         "romaji": "Osaki ni shitsurei shimasu",    "meaning": "Excuse me for leaving before you"},
    {"japanese": "行ってきます",             "romaji": "Ittekimasu",                    "meaning": "I'm heading out (said when leaving home)"},
    {"japanese": "お帰りなさい",             "romaji": "Okaeri nasai",                  "meaning": "Welcome home"},
    {"japanese": "気をつけてください",       "romaji": "Ki wo tsukete kudasai",         "meaning": "Please take care / Be careful"},
    {"japanese": "少々お待ちください",       "romaji": "Shoushou omachi kudasai",       "meaning": "Please wait just a moment"},
    {"japanese": "今日はいい天気ですね",     "romaji": "Kyou wa ii tenki desu ne",      "meaning": "The weather is nice today, isn't it?"},
    {"japanese": "失礼しました",             "romaji": "Shitsurei shimashita",          "meaning": "Excuse me / I'm sorry for the trouble"},
    {"japanese": "おめでとうございます",     "romaji": "Omedetou gozaimasu",            "meaning": "Congratulations"},
    {"japanese": "お誕生日おめでとう",       "romaji": "Otanjoubi omedetou",            "meaning": "Happy birthday"},
    {"japanese": "また明日",                 "romaji": "Mata ashita",                   "meaning": "See you tomorrow"},
    {"japanese": "どうしましたか？",         "romaji": "Dou shimashita ka?",            "meaning": "What's wrong? / What happened?"},
    {"japanese": "手伝いましょうか？",       "romaji": "Tetsudaimashou ka?",            "meaning": "Shall I help you?"},
    {"japanese": "楽しんでください",         "romaji": "Tanoshinde kudasai",            "meaning": "Please enjoy yourself"},
    {"japanese": "どうぞよろしく",           "romaji": "Douzo yoroshiku",               "meaning": "Pleased to meet you (casual)"},
]

FALLBACK_WORDS = [
    {"word": "希望", "reading": "きぼう (kibou)",       "meaning": "hope"},
    {"word": "努力", "reading": "どりょく (doryoku)",   "meaning": "effort"},
    {"word": "勇気", "reading": "ゆうき (yuuki)",       "meaning": "courage"},
    {"word": "笑顔", "reading": "えがお (egao)",        "meaning": "smile"},
    {"word": "平和", "reading": "へいわ (heiwa)",       "meaning": "peace"},
    {"word": "友達", "reading": "ともだち (tomodachi)", "meaning": "friend"},
    {"word": "夢",   "reading": "ゆめ (yume)",          "meaning": "dream"},
    {"word": "愛",   "reading": "あい (ai)",            "meaning": "love"},
    {"word": "桜",   "reading": "さくら (sakura)",      "meaning": "cherry blossom"},
    {"word": "旅",   "reading": "たび (tabi)",          "meaning": "journey / travel"},
    {"word": "空",   "reading": "そら (sora)",          "meaning": "sky"},
    {"word": "光",   "reading": "ひかり (hikari)",      "meaning": "light"},
    {"word": "風",   "reading": "かぜ (kaze)",          "meaning": "wind"},
    {"word": "星",   "reading": "ほし (hoshi)",         "meaning": "star"},
]

# ── Cache helpers ──────────────────────────────────────────────────────────────

def load_cache(path: Path, ttl: timedelta) -> dict | None:
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        age = datetime.now().timestamp() - float(data.get("_ts", 0))
        if age <= ttl.total_seconds():
            return data
        logging.info("Cache stale: %s (%.0fs old)", path.name, age)
    except Exception as e:
        logging.warning("Cache read failed %s: %s", path.name, e)
    return None

def save_cache(path: Path, payload: dict) -> None:
    try:
        out = dict(payload)
        out["_ts"] = datetime.now().timestamp()
        path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logging.warning("Cache write failed %s: %s", path.name, e)

# ── Data fetchers ──────────────────────────────────────────────────────────────

def get_daily_phrase() -> dict:
    """Pick today's phrase deterministically so it stays stable all day."""
    return DAILY_PHRASES[date.today().toordinal() % len(DAILY_PHRASES)]

def get_japanese_word() -> dict:
    cached = load_cache(WORD_CACHE, WORD_CACHE_TTL)
    if cached:
        return cached
    try:
        r = requests.get(JAPANESE_API_URL, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            word_data = {
                "word":    data.get("word", "N/A"),
                "reading": data.get("reading", "N/A"),
                "meaning": data.get("meaning", "N/A"),
            }
            save_cache(WORD_CACHE, word_data)
            logging.info("Japanese word fetched from API: %s", word_data["word"])
            return word_data
    except Exception as e:
        logging.warning("Japanese word API failed: %s", e)
    fallback = dict(FALLBACK_WORDS[date.today().toordinal() % len(FALLBACK_WORDS)])
    logging.info("Using fallback word: %s", fallback["word"])
    return fallback

def get_tokyo_weather() -> dict | None:
    cached = load_cache(WEATHER_CACHE, WEATHER_CACHE_TTL)
    if cached:
        return cached
    if not OWM_API_KEY:
        logging.warning("OWM_API_KEY not set — Tokyo weather unavailable")
        return None
    try:
        r = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"lat": TOKYO_LAT, "lon": TOKYO_LON,
                    "appid": OWM_API_KEY, "units": "metric"},
            headers=HEADERS,
            timeout=10,
        )
        r.raise_for_status()
        d = r.json()
        result = {
            "temp":        round(d["main"]["temp"]),
            "feels_like":  round(d["main"]["feels_like"]),
            "description": d["weather"][0]["description"].title(),
            "main":        d["weather"][0]["main"],
            "humidity":    d["main"]["humidity"],
        }
        save_cache(WEATHER_CACHE, result)
        logging.info("Tokyo weather fetched: %s %d°C", result["description"], result["temp"])
        return result
    except Exception as e:
        logging.warning("Tokyo weather fetch failed: %s", e)
        return None

# ── Layout helpers ─────────────────────────────────────────────────────────────

def wrap_text(text: str, font, max_width: int, draw) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines, cur = [], words[0]
    for w in words[1:]:
        test = cur + " " + w
        if draw.textbbox((0, 0), test, font=font)[2] <= max_width:
            cur = test
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines

def weather_symbol(main: str) -> str:
    m = (main or "").lower()
    if "thunder" in m: return "Thunderstorm"
    if "drizzle" in m: return "Drizzle"
    if "rain" in m:    return "Rain"
    if "snow" in m:    return "Snow"
    if "mist" in m or "fog" in m: return "Mist"
    if "cloud" in m:   return "Cloudy"
    return "Clear"

# ── Dashboard composition ──────────────────────────────────────────────────────

def compose_japanese_dashboard() -> Image.Image:
    canvas = Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    word_data     = get_japanese_word()
    phrase_data   = get_daily_phrase()
    tokyo_weather = get_tokyo_weather()
    tokyo_now     = datetime.now(TOKYO_TZ)

    PAD = 16

    # ── Header bar ────────────────────────────────────────────────────────
    draw.text((PAD, 12), "Japanese Dashboard", font=FONT_HEADER, fill=(160, 50, 110))
    date_str = datetime.now().strftime("%A, %B %d")
    date_w = draw.textbbox((0, 0), date_str, font=FONT_SMALL)[2]
    draw.text((WIDTH - date_w - PAD, 16), date_str, font=FONT_SMALL, fill=(100, 100, 130))
    draw.line([(0, 46), (WIDTH, 46)], fill=(210, 180, 220), width=2)

    # ── Zone definitions ──────────────────────────────────────────────────
    # Left column  (word of the day):  x 0–390
    # Right column (Tokyo time/weather): x 406–800
    # Bottom strip (phrase of the day): full width, y 295–480
    TOP_Y     = 56
    PHRASE_Y  = 292
    COL_SPLIT = 390
    RIGHT_X   = 406

    # ── Word of the Day (left column) ─────────────────────────────────────
    draw.rounded_rectangle(
        [PAD - 4, TOP_Y - 4, COL_SPLIT - 4, PHRASE_Y - 8],
        radius=14, outline=(180, 100, 200), width=3,
    )

    wy = TOP_Y + 6
    draw.text((PAD + 6, wy), "Word of the Day", font=FONT_SMALL, fill=(130, 60, 170))
    wy += 24

    # Large kanji
    draw.text((PAD + 6, wy), word_data["word"], font=FONT_KANJI, fill=(180, 35, 75))
    wy += 66

    # Reading (hiragana + romaji)
    reading = word_data.get("reading", "")
    draw.text((PAD + 6, wy), reading, font=FONT_TEXT, fill=(55, 100, 170))
    wy += 28

    # Meaning
    meaning = word_data.get("meaning", "")
    for line in wrap_text(f'"{meaning}"', FONT_TEXT, COL_SPLIT - PAD - 18, draw)[:2]:
        draw.text((PAD + 6, wy), line, font=FONT_TEXT, fill=(70, 70, 90))
        wy += 24

    # ── Tokyo Time & Weather (right column) ───────────────────────────────
    draw.rounded_rectangle(
        [RIGHT_X - 4, TOP_Y - 4, WIDTH - PAD + 4, PHRASE_Y - 8],
        radius=14, outline=(80, 140, 210), width=3,
    )

    ry = TOP_Y + 6
    draw.text((RIGHT_X + 6, ry), "Tokyo, Japan", font=FONT_SMALL, fill=(50, 100, 170))
    ry += 24

    # Time (large)
    time_str = tokyo_now.strftime("%H:%M")
    draw.text((RIGHT_X + 6, ry), time_str, font=FONT_TIME, fill=(30, 70, 150))
    ry += 58

    draw.text((RIGHT_X + 6, ry), "Japan Standard Time", font=FONT_SMALL, fill=(110, 130, 160))
    ry += 22

    # Divider
    draw.line([(RIGHT_X + 6, ry), (WIDTH - PAD - 4, ry)], fill=(180, 200, 220), width=1)
    ry += 8

    # Weather
    if tokyo_weather:
        temp_line = f"{tokyo_weather['temp']}°C  •  {tokyo_weather['description']}"
        for line in wrap_text(temp_line, FONT_TEXT, WIDTH - RIGHT_X - PAD - 10, draw)[:2]:
            draw.text((RIGHT_X + 6, ry), line, font=FONT_TEXT, fill=(50, 100, 160))
            ry += 24
        draw.text(
            (RIGHT_X + 6, ry),
            f"Feels like {tokyo_weather['feels_like']}°C  •  {tokyo_weather['humidity']}% humidity",
            font=FONT_SMALL, fill=(90, 115, 145),
        )
    else:
        draw.text((RIGHT_X + 6, ry), "Weather unavailable", font=FONT_SMALL, fill=(160, 100, 100))

    # ── Phrase of the Day (full-width bottom strip) ────────────────────────
    draw.rounded_rectangle(
        [PAD - 4, PHRASE_Y - 4, WIDTH - PAD + 4, HEIGHT - PAD + 4],
        radius=14, outline=(60, 155, 115), width=3,
    )

    py = PHRASE_Y + 8
    draw.text((PAD + 6, py), "Phrase of the Day", font=FONT_SMALL, fill=(35, 120, 80))
    py += 22

    # Japanese phrase text
    draw.text((PAD + 6, py), phrase_data["japanese"], font=FONT_PHRASE, fill=(160, 35, 75))
    py += 38

    # Romaji pronunciation
    draw.text((PAD + 6, py), phrase_data["romaji"], font=FONT_TEXT, fill=(55, 100, 170))
    py += 26

    # English meaning (wrapped)
    for line in wrap_text(f'"{phrase_data["meaning"]}"', FONT_TEXT, WIDTH - 2 * PAD - 16, draw)[:2]:
        draw.text((PAD + 6, py), line, font=FONT_TEXT, fill=(70, 70, 90))
        py += 24

    return canvas


# ── EPD display ────────────────────────────────────────────────────────────────

def display_on_epd(img: Image.Image):
    global epd_driver
    if epd_driver is None:
        try:
            from waveshare_epd import epd7in3e as epd_driver
        except ImportError:
            logging.warning("EPD driver unavailable — saving preview to out_motivation.png")
            img.save("out_motivation.png")
            return
    epd = epd_driver.EPD()
    epd.init()
    logging.info("Displaying Japanese dashboard on EPD…")
    epd.display(epd.getbuffer(img))
    epd.sleep()
    logging.info("Done. EPD sleeping.")

def compose_motivation_dashboard_no_display() -> Image.Image:
    """Web server hook — name kept for compatibility."""
    return compose_japanese_dashboard()


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    if "--clear-cache" in sys.argv:
        for p in [WORD_CACHE, WEATHER_CACHE]:
            if p.exists():
                p.unlink()
                logging.info("Cleared cache: %s", p)
    logging.info("Creating Japanese dashboard…")
    display_on_epd(compose_japanese_dashboard())
    logging.info("Done!")

if __name__ == "__main__":
    main()
