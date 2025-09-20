#!/usr/bin/env python3
"""
Sakura helper module
- Centralized sprite loading, outfit picking, and speech-bubble rendering.
- Designed for Waveshare E-ink dashboards (800x480 default), but resolution-agnostic.

Usage (in a dashboard):

    from sakura import add_to_canvas
    # ... build your PIL Image canvas and comment string ...
    add_to_canvas(canvas, text=comment, main=main, temp=temp, units=OWM_UNITS,
                  override=os.environ.get("SAKURA_EMOTE", "auto"),
                  position="bottom-right", target_h=180)

This will:
- choose the Sakura outfit based on weather+temp (unless override != 'auto')
- draw a wrapped speech bubble that avoids overlapping the sprite
- paste Sakura bottom-right

Assets:
- sprites under img/sakura/ e.g. sakura_sunny.png, sakura_rain.png, ...
- fonts under fonts/ (Fredoka for voice)
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional, Tuple
from PIL import Image, ImageDraw, ImageFont
import os

# -------- Paths & Fonts --------
ROOT = Path(__file__).resolve().parent
SAKURA_DIR = ROOT / "img" / "sakura"
FONT_DIR = ROOT / "fonts"

try:
    FONT_SAKURA = ImageFont.truetype(str(FONT_DIR / "Fredoka-Regular.ttf"), 20)
except Exception:
    FONT_SAKURA = ImageFont.load_default()

# -------- Outfit logic --------
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

def _to_fahrenheit(val, units: str) -> Optional[float]:
    try:
        v = float(val)
    except Exception:
        return None
    if units == "imperial":
        return v
    return v * 9.0/5.0 + 32.0

def pick_sprite_filename(main: Optional[str], temp_val, units: str, override: Optional[str] = None) -> str:
    """Return a file name under img/sakura for the selected outfit."""
    if override and override.lower() != "auto":
        return f"sakura_{override.lower()}.png"
    main_t = (main or "").title()
    temp_f = _to_fahrenheit(temp_val, units)

    if main_t in ("Thunderstorm", "Rain", "Drizzle", "Snow", "Mist", "Fog"):
        return _SAKURA_MAP.get(main_t, "sakura_sunny.png")

    # Hoodie rule for mild temps
    if temp_f is not None and 55.0 <= temp_f <= 70.0:
        return "sakura_hoodie.png"

    if main_t == "Clear":
        if temp_f is not None and temp_f >= 80.0:
            return "sakura_sunny.png"
        return "sakura_cloudy.png" if (temp_f is not None and temp_f < 55.0) else "sakura_sunny.png"

    if main_t == "Clouds":
        return "sakura_cloudy.png"

    return _SAKURA_MAP.get(main_t, "sakura_sunny.png")

# -------- Drawing helpers --------

def _wrap_text_to_width(text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.ImageDraw):
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

def _draw_bubble(draw: ImageDraw.ImageDraw, bx: int, by: int, bw: int, text: str, font: ImageFont.FreeTypeFont,
                 text_col=(60, 20, 80), fill_col=(255, 245, 255), outline_col=(230, 200, 230), radius=12) -> Tuple[int,int]:
    pad_x, pad_y = 12, 10
    inner_w = bw - 2*pad_x
    lines = _wrap_text_to_width(text, font, inner_w, draw)
    line_h = draw.textbbox((0, 0), "Ay", font=font)[3]
    text_h = line_h * len(lines)
    bh = text_h + 2*pad_y
    draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=radius, fill=fill_col, outline=outline_col, width=2)
    tx, ty = bx + pad_x, by + pad_y
    for ln in lines:
        draw.text((tx, ty), ln, font=font, fill=text_col)
        ty += line_h
    return bw, bh

# -------- Public API --------

def add_to_canvas(canvas: Image.Image, text: str, *, main: Optional[str] = None, temp=None, units: str = "metric",
                  override: Optional[str] = None, position: str = "bottom-right", target_h: int = 180,
                  bubble_max_w: int = 420):
    """Draw Sakura with a wrapped speech bubble on the provided PIL canvas.
    - Chooses outfit automatically unless `override` is set to a sprite key (e.g., "rain").
    - Positions Sakura bottom-right and draws the bubble to her left, avoiding overlap.
    """
    W, H = canvas.size
    draw = ImageDraw.Draw(canvas)

    # Load sprite
    fname = pick_sprite_filename(main, temp, units, override)
    path = SAKURA_DIR / fname
    if not path.exists():
        # fallback legacy path (old project layout)
        legacy = ROOT / "img" / "sakura_happy.png"
        path = legacy if legacy.exists() else path
    sak = None
    sak_w = sak_h = 0
    if path.exists():
        _sak = Image.open(str(path)).convert("RGBA")
        scale = min(1.0, target_h / max(1, _sak.height))
        sak_w = int(_sak.width * scale)
        sak_h = int(_sak.height * scale)
        sak = _sak.resize((sak_w, sak_h), Image.LANCZOS)

    # Compute right limit (avoid overlapping Sakura)
    if position == "bottom-right" and sak is not None:
        sak_x = W - sak_w - 8
        sak_y = H - sak_h - 8
        right_limit = sak_x - 8
    else:
        sak_x = W - sak_w - 8 if sak is not None else W - 8
        sak_y = H - sak_h - 8 if sak is not None else H - 8
        right_limit = W - 8

    # Bubble geometry and draw
    bw = min(bubble_max_w, max(180, right_limit - 12))
    bx = max(8, right_limit - bw)
    # place bubble above bottom margin
    by = H - 12  # provisional, we will adjust up by bubble height inside _draw_bubble
    # First pass to compute height then redraw at correct y
    # (quick trick: draw off-screen to measure, then draw properly)
    pad_draw = ImageDraw.Draw(canvas)
    # Use measurement routine: we can draw once at target y after getting height
    # Do a measurement on a temporary image to compute text height cleanly
    temp_img = Image.new("RGBA", (bw, 2000), (0,0,0,0))
    temp_draw = ImageDraw.Draw(temp_img)
    lines = _wrap_text_to_width(text, FONT_SAKURA, bw - 24, temp_draw)
    line_h = temp_draw.textbbox((0, 0), "Ay", font=FONT_SAKURA)[3]
    text_h = line_h * len(lines)
    bh = text_h + 20
    by = H - bh - 12
    _draw_bubble(draw, bx, by, bw, text, FONT_SAKURA)

    # Paste Sakura last
    if sak is not None:
        canvas.paste(sak, (sak_x, sak_y), sak)

    return {"sprite": {"path": str(path), "x": sak_x, "y": sak_y, "w": sak_w, "h": sak_h},
            "bubble": {"x": bx, "y": by, "w": bw, "h": bh}}

- [ ] **Integrate `sakura.py` in `dash_comic.py`**  
  - Import `from sakura import add_to_canvas as sakura_add` and replace local bubble/Sakura code with a single `sakura_add(...)` call.
