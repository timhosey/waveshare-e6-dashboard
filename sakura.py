#!/usr/bin/env python3
"""
Sakura helper module (shared by all dashboards)

Responsibilities:
- Pick Sakura's outfit sprite based on weather ("main") + temperature or a manual override
- Load/scale the sprite and draw a wrapped speech bubble that avoids overlap
- Paste Sakura onto the provided PIL Image canvas

Usage (example):
    from sakura import add_to_canvas
    # after you computed `main`, `temp`, and a `comment` string…
    add_to_canvas(
        canvas,
        text=comment,
        main=main,            # e.g. "Clear", "Rain", … (OpenWeatherMap "main")
        temp=temp,            # numeric temperature (units specified by `units`)
        units="imperial",    # or "metric"
        override=os.getenv("SAKURA_EMOTE", "auto"),
        position="bottom-right",
        target_h=180,
        bubble_max_w=420,
    )

Assets expected:
- Sprites in: img/sakura/
    sakura_sunny.png, sakura_rain.png, sakura_snow.png, sakura_cloudy.png,
    sakura_mist.png, sakura_thunder.png, sakura_hoodie.png
- Voice font in: fonts/Fredoka-Regular.ttf (falls back to default if missing)

This module is resolution-agnostic; defaults are tuned for 800x480.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple, List
import os

from PIL import Image, ImageDraw, ImageFont

# ---------- Paths & defaults ----------
ROOT = Path(__file__).resolve().parent
SAKURA_DIR = ROOT / "img" / "sakura"
FONT_DIR = ROOT / "fonts"

# Bubble defaults (tweak here to affect all dashboards)
BUBBLE_FILL = (255, 245, 255)      # soft pink-white
BUBBLE_OUTLINE = (230, 200, 230)   # pastel outline
BUBBLE_TEXT = (60, 20, 80)         # plum text
BUBBLE_RADIUS = 12
BUBBLE_OUTLINE_WIDTH = 2
BUBBLE_PAD_X = 12
BUBBLE_PAD_Y = 10
BUBBLE_MIN_W = 180
MARGIN = 8  # edge margin from canvas sides

# Load Sakura's voice font
try:
    FONT_SAKURA = ImageFont.truetype(str(FONT_DIR / "Fredoka-Regular.ttf"), 20)
except Exception:
    FONT_SAKURA = ImageFont.load_default()

# Map OpenWeather "main" → outfit file name
_SAKURA_MAP = {
    "Thunderstorm": "sakura_thunder.png",
    "Rain":         "sakura_rain.png",
    "Drizzle":      "sakura_rain.png",
    "Snow":         "sakura_snow.png",
    "Mist":         "sakura_mist.png",
    "Fog":          "sakura_mist.png",
    "Clouds":       "sakura_cloudy.png",
    "Clear":        "sakura_sunny.png",
}

# ---------- Helpers ----------

def _to_fahrenheit(val, units: str) -> Optional[float]:
    try:
        v = float(val)
    except Exception:
        return None
    if units == "imperial":
        return v
    # metric → convert C to F
    return v * 9.0 / 5.0 + 32.0


def pick_sprite_filename(main: Optional[str], temp_val, units: str, override: Optional[str] = None) -> str:
    """Return a sprite file name (just the file, not the path) under img/sakura/.
    If `override` is provided and not 'auto', it wins (e.g., 'rain' → 'sakura_rain.png').
    """
    if override and override.lower() != "auto":
        key = override.lower().strip()
        if not key.startswith("sakura_"):
            key = f"sakura_{key}"
        if not key.endswith(".png"):
            key = f"{key}.png"
        return key

    main_t = (main or "").title()
    temp_f = _to_fahrenheit(temp_val, units)

    # Precip / special conditions take precedence
    if main_t in ("Thunderstorm", "Rain", "Drizzle", "Snow", "Mist", "Fog"):
        return _SAKURA_MAP.get(main_t, "sakura_sunny.png")

    # Hoodie window for mild temps when not precip/mist
    if temp_f is not None and 55.0 <= temp_f <= 70.0:
        return "sakura_hoodie.png"

    # Clear / Clouds behavior (hot clear → swimsuit; cold clear → cardigan/cloudy)
    if main_t == "Clear":
        if temp_f is not None and temp_f >= 80.0:
            return "sakura_sunny.png"
        return "sakura_cloudy.png" if (temp_f is not None and temp_f < 55.0) else "sakura_sunny.png"

    if main_t == "Clouds":
        return "sakura_cloudy.png"

    # Fallback
    return _SAKURA_MAP.get(main_t, "sakura_happy.png")


def _wrap_text_to_width(text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.ImageDraw) -> List[str]:
    words = (text or "").split()
    if not words:
        return [""]
    lines: List[str] = []
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


def _measure_text_height(lines: List[str], font: ImageFont.FreeTypeFont, draw: ImageDraw.ImageDraw) -> Tuple[int, int]:
    # Returns (line_height, total_height)
    # Use a representative glyph pair for height
    line_h = draw.textbbox((0, 0), "Ay", font=font)[3]
    total_h = line_h * max(1, len(lines))
    return line_h, total_h


def _draw_bubble(draw: ImageDraw.ImageDraw, bx: int, by: int, bw: int, text: str, font: ImageFont.FreeTypeFont,
                 *, fill=BUBBLE_FILL, outline=BUBBLE_OUTLINE, text_col=BUBBLE_TEXT,
                 radius=BUBBLE_RADIUS, outline_w=BUBBLE_OUTLINE_WIDTH) -> Tuple[int, int]:
    """Draw a wrapped bubble at (bx, by) with width bw. Returns (bubble_w, bubble_h)."""
    inner_w = bw - 2 * BUBBLE_PAD_X
    lines = _wrap_text_to_width(text, font, inner_w, draw)
    line_h, text_h = _measure_text_height(lines, font, draw)
    bh = text_h + 2 * BUBBLE_PAD_Y

    draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=radius, fill=fill, outline=outline, width=outline_w)
    tx, ty = bx + BUBBLE_PAD_X, by + BUBBLE_PAD_Y
    for ln in lines:
        draw.text((tx, ty), ln, font=font, fill=text_col)
        ty += line_h
    return bw, bh


# ---------- Public API ----------

def add_to_canvas(canvas: Image.Image, *, text: str = "",
                  main: Optional[str] = None, temp=None, units: str = "metric",
                  override: Optional[str] = None, position: str = "bottom-right",
                  target_h: int = 180, bubble_max_w: int = 420) -> dict:
    """Draw Sakura with a wrapped speech bubble on the provided PIL canvas.

    Returns a dict with sprite & bubble geometry for debugging/testing.
    """
    W, H = canvas.size
    draw = ImageDraw.Draw(canvas)

    # Resolve sprite file
    fname = pick_sprite_filename(main, temp, units, override)
    path = SAKURA_DIR / fname
    if not path.exists():
        # fallback to legacy project layout if needed
        legacy = ROOT / "img" / "sakura_happy.png"
        path = legacy if legacy.exists() else path

    # Load + scale sprite
    sak = None
    sak_w = sak_h = 0
    sak_x = sak_y = 0
    if path.exists():
        try:
            _sak = Image.open(str(path)).convert("RGBA")
            if _sak.height > 0:
                scale = min(1.0, float(target_h) / float(_sak.height))
            else:
                scale = 1.0
            sak_w = max(1, int(_sak.width * scale))
            sak_h = max(1, int(_sak.height * scale))
            sak = _sak.resize((sak_w, sak_h), Image.LANCZOS)
        except Exception:
            sak = None
            sak_w = sak_h = 0

    # Compute area available for bubble (avoid overlapping Sakura)
    right_limit = W - MARGIN
    if position == "bottom-right" and sak is not None:
        sak_x = W - sak_w - MARGIN
        sak_y = H - sak_h - MARGIN
        right_limit = max(MARGIN, sak_x - MARGIN)

    # Bubble geometry
    bw = min(bubble_max_w, max(BUBBLE_MIN_W, right_limit - MARGIN))
    bx = max(MARGIN, right_limit - bw)
    # measure to compute bubble height and final y
    tmp_draw = ImageDraw.Draw(Image.new("RGB", (bw, 10)))
    lines = _wrap_text_to_width(text or "", FONT_SAKURA, bw - 2 * BUBBLE_PAD_X, tmp_draw)
    line_h, text_h = _measure_text_height(lines, FONT_SAKURA, tmp_draw)
    bh = text_h + 2 * BUBBLE_PAD_Y
    by = H - bh - MARGIN

    # Draw bubble
    _draw_bubble(draw, bx, by, bw, text or "", FONT_SAKURA)

    # Paste Sakura last
    if sak is not None:
        canvas.paste(sak, (sak_x, sak_y), sak)

    return {
        "sprite": {"path": str(path), "x": sak_x, "y": sak_y, "w": sak_w, "h": sak_h},
        "bubble": {"x": bx, "y": by, "w": bw, "h": bh},
    }
