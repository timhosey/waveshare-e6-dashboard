

#!/usr/bin/env python3
"""
Simple Dashboard Rotator (clean slate)
- Runs your dashboard scripts in sequence, sleeping between runs.
- Default rotate interval: 120s (override with ROTATE_SECONDS in .env or env).
- Child scripts (dash_comic.py, dash_weather.py, etc.) perform a single refresh.

Environment (optional):
  ROTATE_SECONDS   Interval between dashboards (default: 120)
  DASH_CYCLE       Comma-separated list of dashboards to run (default: "comic,weather")
  DASH_TIMEOUT     Per-script timeout in seconds (default: 90)
  PYTHON_BIN       Path to Python interpreter for child scripts (default: sys.executable)

Your existing .env for Sakura/OWM is still honored by the child scripts.
"""

import os
import sys
import time
import signal
import logging
import subprocess
from itertools import cycle
from pathlib import Path

# ---------------- Logging ----------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("rotator")

# ---------------- Dotenv (optional) ----------------
try:
    from dotenv import load_dotenv, find_dotenv
    env_path = find_dotenv(usecwd=True)
    load_dotenv(dotenv_path=env_path)
    if env_path:
        log.info("Loaded .env: %s", env_path)
except Exception as e:
    log.debug("dotenv not used (%s)", e)

# ---------------- Config ----------------
PYTHON_BIN = os.environ.get("PYTHON_BIN", sys.executable)
ROTATE_SECONDS = int(os.environ.get("ROTATE_SECONDS", "120"))
DASH_TIMEOUT = int(os.environ.get("DASH_TIMEOUT", "90"))

# Order of dashboards to run
raw_cycle = os.environ.get("DASH_CYCLE", "comic,weather")
DASH_CYCLE = [s.strip().lower() for s in raw_cycle.split(',') if s.strip()]

ROOT = Path(__file__).resolve().parent
SCRIPT_MAP = {
    "comic": ROOT / "dash_comic.py",
    "weather": ROOT / "dash_weather.py",
    "motivation": ROOT / "dash_motivation.py",
}

ORDER = []
for name in DASH_CYCLE:
    p = SCRIPT_MAP.get(name)
    if not p:
        log.warning("Unknown dashboard '%s' (skipping)", name)
        continue
    if not p.exists():
        log.warning("Script not found for '%s': %s (skipping)", name, p)
        continue
    ORDER.append((name, p))

if not ORDER:
    log.error("No valid dashboards to run. Check DASH_CYCLE and script paths.")
    sys.exit(1)

log.info("Rotation order: %s", ", ".join(n for n, _ in ORDER))
log.info("Rotate interval: %ds | Timeout: %ds", ROTATE_SECONDS, DASH_TIMEOUT)

# ---------------- Signals ----------------
_stop = False

def _sig_handler(signum, frame):
    global _stop
    log.info("Signal %s received — will stop after current run.", signum)
    _stop = True

signal.signal(signal.SIGINT, _sig_handler)
signal.signal(signal.SIGTERM, _sig_handler)

# ---------------- Runner ----------------

def run_script(path: Path) -> int:
    """Run a dashboard script and stream its stdout to our logs. Return exit code."""
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
        # Stream output and enforce timeout
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
                return 124
        return proc.returncode
    except FileNotFoundError:
        log.exception("Interpreter or script not found: %s", path)
        return 127
    except Exception:
        log.exception("Error running %s", path)
        return 1

# ---------------- Main loop ----------------

def main():
    for name, path in cycle(ORDER):
        if _stop:
            break
        rc = run_script(path)
        if rc == 0:
            log.info("%s completed successfully.", name)
        else:
            log.warning("%s exited with code %s.", name, rc)

        # Sleep until next rotation or until stopped
        remaining = ROTATE_SECONDS
        while remaining > 0 and not _stop:
            time.sleep(1)
            remaining -= 1
        if _stop:
            break

    log.info("Rotator exiting. Bye-bye! ✨")

if __name__ == "__main__":
    main()