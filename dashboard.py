#!/usr/bin/env python3
import sys, os, random, requests
from PIL import Image, ImageDraw, ImageFont

EPD_LIB = "./lib"
if os.path.exists(EPD_LIB):
    sys.path.append(EPD_LIB)
from waveshare_epd import epd7in3e as epd_driver

# --- Fonts ---
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BIG = ImageFont.truetype(FONT_PATH, 36)
FONT_SMALL = ImageFont.truetype(FONT_PATH, 20)

# --- Widgets ---
class ComicWidget:
    def render(self, draw, W, H):
        # Placeholder: solid background with “Comic” text
        draw.rectangle((0, 0, W, H), fill=(255, 255, 255))
        draw.text((W//4, H//2), "Comic goes here", font=FONT_BIG, fill=(0,0,0))

class WeatherWidget:
    def __init__(self, api_key, city="Seattle,US"):
        self.api_key = api_key
        self.city = city

    def render(self, draw, W, H):
        # Example fetch
        try:
            r = requests.get(f"https://api.openweathermap.org/data/2.5/weather",
                             params={"q": self.city, "appid": self.api_key, "units": "metric"})
            data = r.json()
            temp = data["main"]["temp"]
            desc = data["weather"][0]["description"]
        except Exception as e:
            temp, desc = "?", "error"

        draw.rectangle((0, 0, W, H), fill=(255, 230, 250))  # pastel pink bg
        draw.text((20, 40), f"{self.city}", font=FONT_BIG, fill=(255,105,180))  # hot pink
        draw.text((20, 100), f"{temp}°C", font=FONT_BIG, fill=(0,0,0))
        draw.text((20, 160), desc, font=FONT_SMALL, fill=(0,0,0))

# --- Dashboard Manager ---
def render_dashboard(widget):
    W, H = 800, 480
    img = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    widget.render(draw, W, H)
    return img

def main():
    epd = epd_driver.EPD()
    epd.init()

    # Example rotation of dashboards
    widgets = [ComicWidget(), WeatherWidget(api_key="YOUR_API_KEY_HERE")]
    widget = random.choice(widgets)

    img = render_dashboard(widget)
    epd.display(epd.getbuffer(img))
    epd.sleep()

if __name__ == "__main__":
    main()


#!/usr/bin/env python3
"""
Dashboard Orchestrator (timer/rotator)
- Runs your dashboard scripts in sequence on a schedule.
- Each child script (e.g., dash_comic.py, dash_weather.py) handles drawing + single-refresh.
- This orchestrator simply invokes them periodically.

Env/config (all optional):
  DASH_CYCLE          Comma-separated names in rotation (default: "comic,weather")
  DASH_HOLD_SECONDS   Seconds to wait between dashboards (default: 900 = 15 min)
  DASH_TIMEOUT        Per-script timeout seconds (default: 120)
  DASH_JITTER_SECONDS Random jitter added to each sleep (default: 0)
  PYTHON_BIN          Python interpreter for child scripts (default: sys.executable)

  SAKURA_EMOTE, OWM_* etc. are still picked up by child scripts (via .env or systemd EnvironmentFile).

Example:
  DASH_CYCLE=comic,weather DASH_HOLD_SECONDS=600 python dashboard.py
"""

import os
import sys
import time
import random
import signal
import logging
import subprocess
from itertools import cycle
from pathlib import Path

# --- Logging ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("orchestrator")

# --- Dotenv (optional) so child scripts inherit) ---
try:
    from dotenv import load_dotenv, find_dotenv
    env_path = find_dotenv(usecwd=True)
    load_dotenv(dotenv_path=env_path)
    if env_path:
        log.info("Loaded .env: %s", env_path)
except Exception as e:
    log.debug("dotenv not used (%s)", e)

# --- Config ---
PYTHON_BIN = os.environ.get("PYTHON_BIN", sys.executable)
DASH_CYCLE = [s.strip().lower() for s in os.environ.get("DASH_CYCLE", "comic,weather").split(",") if s.strip()]
DASH_HOLD_SECONDS = int(os.environ.get("DASH_HOLD_SECONDS", "900"))  # 15 min default
DASH_TIMEOUT = int(os.environ.get("DASH_TIMEOUT", "120"))
DASH_JITTER_SECONDS = int(os.environ.get("DASH_JITTER_SECONDS", "0"))

ROOT = Path(__file__).resolve().parent

# Map names -> scripts
SCRIPT_MAP = {
    "comic": ROOT / "dash_comic.py",
    "weather": ROOT / "dash_weather.py",
    # add more here later, e.g. "system": ROOT / "dash_system.py",
}

# Validate cycle entries
ORDER = []
for name in DASH_CYCLE:
    path = SCRIPT_MAP.get(name)
    if not path:
        log.warning("Unknown dashboard name in DASH_CYCLE: %s (skipping)", name)
        continue
    if not path.exists():
        log.warning("Script not found for '%s': %s (skipping)", name, path)
        continue
    ORDER.append((name, path))

if not ORDER:
    log.error("No valid dashboards to run. Check DASH_CYCLE and script paths.")
    sys.exit(1)

log.info("Rotation order: %s", ", ".join(n for n, _ in ORDER))
log.info("Hold per dashboard: %ds | Timeout: %ds | Jitter: %ds", DASH_HOLD_SECONDS, DASH_TIMEOUT, DASH_JITTER_SECONDS)

# Graceful shutdown
_terminate = False

def _sig_handler(signum, frame):
    global _terminate
    log.info("Received signal %s — shutting down after current cycle.", signum)
    _terminate = True

signal.signal(signal.SIGINT, _sig_handler)
signal.signal(signal.SIGTERM, _sig_handler)


def run_script(path: Path) -> int:
    """Run a child dashboard script, stream its logs, and return exit code."""
    cmd = [PYTHON_BIN, str(path)]
    log.info("Launching: %s", " ".join(cmd))
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            env=os.environ.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        start = time.time()
        # Stream output until completion or timeout
        while True:
            line = proc.stdout.readline()
            if line:
                log.info("[%s] %s", path.name, line.rstrip())
            if proc.poll() is not None:
                break
            if time.time() - start > DASH_TIMEOUT:
                log.error("Timeout after %ds — terminating %s", DASH_TIMEOUT, path.name)
                proc.terminate()
                try:
                    proc.wait(5)
                except Exception:
                    proc.kill()
                return 124  # timeout
        return proc.returncode
    except FileNotFoundError:
        log.exception("Interpreter or script not found: %s", path)
        return 127
    except Exception:
        log.exception("Error running %s", path)
        return 1


def main():
    for name, path in cycle(ORDER):
        if _terminate:
            break

        rc = run_script(path)
        if rc == 0:
            log.info("%s completed successfully.", name)
        else:
            log.warning("%s exited with code %s.", name, rc)

        # Sleep/hold before next dashboard
        hold = DASH_HOLD_SECONDS + (random.randint(0, DASH_JITTER_SECONDS) if DASH_JITTER_SECONDS > 0 else 0)
        log.info("Sleeping %ds before next dashboard…", hold)
        for _ in range(hold):
            if _terminate:
                break
            time.sleep(1)
        if _terminate:
            break

    log.info("Goodbye from the dashboard orchestrator. ✨")


if __name__ == "__main__":
    main()