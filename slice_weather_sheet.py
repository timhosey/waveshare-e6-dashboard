#!/usr/bin/env python3
"""
Slice a kawaii weather sprite sheet into separate PNGs for the dashboard.

Usage:
  python slice_weather_sheet.py path/to/sheet.png img/weather

What it does:
- Splits the sheet using a simple grid you define (rows/cols + padding).
- For each tile: auto-trims the background (using corner color) → makes it transparent.
- Saves both 96px and 48px tall versions:
    img/weather/sun.png, img/weather/sun_48.png, etc.
"""

import sys, os
from pathlib import Path
from typing import Tuple, List
from PIL import Image

# ==== CONFIG YOU MAY TWEAK ====
# grid geometry of your sheet (measure once; adjust as needed)
SHEET_W = 1152  # width of the sheet image
SHEET_H = 768   # height of the sheet image
ROWS = 2
COLS = 3
# margins around the whole sheet (if any) and gutter between tiles
MARGIN_X = 60
MARGIN_Y = 60
GUTTER_X = 60
GUTTER_Y = 60

# map each grid cell to an icon name
# cells are (row, col) zero-indexed. adjust names to match your sheet order.
CELL_MAP = {
    (0, 0): "sun",
    (0, 1): "clouds",
    (0, 2): "thunder",
    (1, 0): "rain",
    (1, 1): "snow",
    (1, 2): "mist",
    # if you also have "drizzle" as a 7th icon on another sheet,
    # add it here with its cell position.
}

# output heights
H_BIG  = 96   # for current condition
H_SMALL = 48  # for forecast cards
# ==============================

def crop_cell(box: Tuple[int, int, int, int], im: Image.Image) -> Image.Image:
    """Crop a cell from the sheet and convert background to transparent."""
    tile = im.crop(box).convert("RGBA")
    # use top-left pixel as bg sample to cut out background
    bg = tile.getpixel((0, 0))[:3]
    px = tile.load()
    w, h = tile.size
    # make bg close to sample fully transparent
    # (tolerant threshold so minor gradients vanish)
    TH = 18
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if abs(r-bg[0]) <= TH and abs(g-bg[1]) <= TH and abs(b-bg[2]) <= TH:
                px[x, y] = (r, g, b, 0)
    # trim transparent edges
    bbox = tile.getbbox()
    return tile.crop(bbox) if bbox else tile

def resize_height(img: Image.Image, target_h: int) -> Image.Image:
    if img.height == 0:
        return img
    scale = target_h / img.height
    new_w = int(img.width * scale)
    return img.resize((new_w, target_h), Image.LANCZOS)

def main(sheet_path: Path, out_dir: Path):
    sheet = Image.open(sheet_path).convert("RGBA")
    if sheet.size != (SHEET_W, SHEET_H):
        print(f"[warn] Sheet size is {sheet.size} but config expects {(SHEET_W, SHEET_H)}. Adjust constants if needed.")

    # compute cell width/height
    total_gut_x = GUTTER_X * (COLS - 1)
    total_gut_y = GUTTER_Y * (ROWS - 1)
    cell_w = (SHEET_W - 2*MARGIN_X - total_gut_x) // COLS
    cell_h = (SHEET_H - 2*MARGIN_Y - total_gut_y) // ROWS

    out_dir.mkdir(parents=True, exist_ok=True)

    for (r, c), name in CELL_MAP.items():
        x0 = MARGIN_X + c * (cell_w + GUTTER_X)
        y0 = MARGIN_Y + r * (cell_h + GUTTER_Y)
        x1, y1 = x0 + cell_w, y0 + cell_h
        tile = crop_cell((x0, y0, x1, y1), sheet)

        big  = resize_height(tile, H_BIG)
        small= resize_height(tile, H_SMALL)

        big.save(out_dir / f"{name}.png")
        small.save(out_dir / f"{name}_48.png")
        print(f"[ok] wrote {name}.png and {name}_48.png  (sizes: {big.size}, {small.size})")

    print("Done! Meow~")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python slice_weather_sheet.py path/to/sheet.png img/weather")
        sys.exit(1)
    main(Path(sys.argv[1]), Path(sys.argv[2]))