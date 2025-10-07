#!/usr/bin/env python3
"""
dash_recipe.py
- Shows daily recipe inspiration with ingredients and cooking tips
- Features Sakura-chan in cooking outfits with culinary commentary
- Renders into 800x480 for Waveshare E6 (epd7in3e)
"""

import os
import sys
import time
import json
import logging
import random
from datetime import datetime, timedelta
from pathlib import Path
from io import BytesIO

import requests
from PIL import Image, ImageDraw, ImageFont
from sakura import add_to_canvas as sakura_add

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
RECIPE_CACHE = CACHE_DIR / "recipe.json"
CACHE_TTL = timedelta(hours=6)  # Cache for 6 hours (refresh twice daily)

# Recipe sources
SPOONACULAR_API_URL = "https://api.spoonacular.com/recipes/random"
EDAMAM_API_URL = "https://api.edamam.com/search"

# Fallback recipes (curated collection)
FALLBACK_RECIPES = [
    {
        "title": "Classic Spaghetti Carbonara",
        "ingredients": ["Pasta", "Eggs", "Parmesan", "Pancetta", "Black pepper"],
        "cook_time": "20 min",
        "difficulty": "Medium",
        "tip": "Keep pasta water for the sauce!"
    },
    {
        "title": "One-Pan Chicken & Vegetables",
        "ingredients": ["Chicken thighs", "Potatoes", "Carrots", "Onion", "Herbs"],
        "cook_time": "45 min",
        "difficulty": "Easy",
        "tip": "Season generously for best flavor"
    },
    {
        "title": "Mediterranean Quinoa Bowl",
        "ingredients": ["Quinoa", "Chickpeas", "Cucumber", "Tomatoes", "Feta", "Olive oil"],
        "cook_time": "25 min",
        "difficulty": "Easy",
        "tip": "Let quinoa cool before mixing"
    },
    {
        "title": "Homemade Ramen",
        "ingredients": ["Ramen noodles", "Miso paste", "Soft-boiled egg", "Green onions", "Seaweed"],
        "cook_time": "30 min",
        "difficulty": "Medium",
        "tip": "Soft-boil eggs for 6 minutes"
    },
    {
        "title": "Baked Salmon with Herbs",
        "ingredients": ["Salmon fillet", "Lemon", "Dill", "Garlic", "Olive oil", "Salt"],
        "cook_time": "25 min",
        "difficulty": "Easy",
        "tip": "Don't overcook - salmon should flake easily"
    },
    {
        "title": "Vegetable Stir-Fry",
        "ingredients": ["Mixed vegetables", "Soy sauce", "Ginger", "Garlic", "Sesame oil"],
        "cook_time": "15 min",
        "difficulty": "Easy",
        "tip": "High heat and quick cooking keeps veggies crisp"
    },
    {
        "title": "Chocolate Chip Cookies",
        "ingredients": ["Flour", "Butter", "Sugar", "Eggs", "Chocolate chips", "Vanilla"],
        "cook_time": "35 min",
        "difficulty": "Easy",
        "tip": "Chill dough for 30 minutes before baking"
    },
    {
        "title": "Beef Tacos",
        "ingredients": ["Ground beef", "Taco shells", "Lettuce", "Cheese", "Salsa", "Sour cream"],
        "cook_time": "20 min",
        "difficulty": "Easy",
        "tip": "Warm shells in oven for extra crunch"
    }
]

# Fonts
FONT_DIR = Path("fonts")
try:
    FONT_TITLE = ImageFont.truetype(str(FONT_DIR / "MPLUSRounded1c-Regular.ttf"), 24)
    FONT_TEXT = ImageFont.truetype(str(FONT_DIR / "MPLUSRounded1c-Regular.ttf"), 18)
    FONT_SMALL = ImageFont.truetype(str(FONT_DIR / "MPLUSRounded1c-Regular.ttf"), 14)
    FONT_INGREDIENT = ImageFont.truetype(str(FONT_DIR / "MPLUSRounded1c-Regular.ttf"), 16)
except Exception as e:
    logging.warning("Font loading failed (%s); using defaults", e)
    FONT_TITLE = FONT_TEXT = FONT_SMALL = FONT_INGREDIENT = ImageFont.load_default()

HEADERS = {
    "User-Agent": "SakuraRecipe/1.0 (personal dashboard)"
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
            logging.info("Using cached recipe data (age: %.0fs)", age)
            return data
        else:
            logging.info("Recipe cache stale (age: %.0fs > %.0fs)", age, ttl.total_seconds())
    except Exception as e:
        logging.warning("Failed to load recipe cache: %s", e)
    return None

def save_cache(path: Path, payload: dict) -> None:
    """Save data to cache with timestamp."""
    try:
        payload = dict(payload)
        payload["_ts"] = datetime.now().timestamp()
        path.write_text(json.dumps(payload, indent=2))
        logging.info("Cached recipe data")
    except Exception as e:
        logging.warning("Failed to save recipe cache: %s", e)

# === Recipe Fetching ===

def fetch_spoonacular_recipe():
    """Try to fetch a random recipe from Spoonacular API."""
    api_key = os.environ.get("SPOONACULAR_API_KEY")
    if not api_key:
        return None
    
    try:
        params = {
            "apiKey": api_key,
            "number": 1,
            "tags": "main course,dinner"
        }
        response = requests.get(SPOONACULAR_API_URL, params=params, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("recipes"):
                recipe = data["recipes"][0]
                return {
                    "title": recipe.get("title", "Delicious Recipe"),
                    "ingredients": [ing.get("name", "") for ing in recipe.get("extendedIngredients", [])[:6]],
                    "cook_time": f"{recipe.get('readyInMinutes', 30)} min",
                    "difficulty": "Medium",  # Spoonacular doesn't provide difficulty
                    "tip": "Follow the recipe for best results!",
                    "source": "spoonacular"
                }
    except Exception as e:
        logging.warning("Spoonacular API failed: %s", e)
    return None

def fetch_edamam_recipe():
    """Try to fetch a recipe from Edamam API."""
    app_id = os.environ.get("EDAMAM_APP_ID")
    app_key = os.environ.get("EDAMAM_APP_KEY")
    if not (app_id and app_key):
        return None
    
    try:
        params = {
            "app_id": app_id,
            "app_key": app_key,
            "q": "dinner",
            "from": 0,
            "to": 1
        }
        response = requests.get(EDAMAM_API_URL, params=params, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("hits"):
                recipe = data["hits"][0]["recipe"]
                return {
                    "title": recipe.get("label", "Delicious Recipe"),
                    "ingredients": recipe.get("ingredientLines", [])[:6],
                    "cook_time": f"{recipe.get('totalTime', 30)} min",
                    "difficulty": "Medium",
                    "tip": "Check seasoning before serving!",
                    "source": "edamam"
                }
    except Exception as e:
        logging.warning("Edamam API failed: %s", e)
    return None

def get_daily_recipe():
    """Get today's recipe with caching."""
    cached = load_cache(RECIPE_CACHE, CACHE_TTL)
    if cached is not None:
        return cached
    
    logging.info("Fetching fresh recipe...")
    
    # Try APIs first
    recipe = fetch_spoonacular_recipe()
    if recipe is None:
        recipe = fetch_edamam_recipe()
    
    # Fallback to curated recipes
    if recipe is None:
        recipe = random.choice(FALLBACK_RECIPES)
        recipe["source"] = "fallback"
        logging.info("Using fallback recipe: %s", recipe["title"])
    else:
        logging.info("Using API recipe: %s", recipe["title"])
    
    save_cache(RECIPE_CACHE, recipe)
    return recipe

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

def compose_recipe_dashboard():
    """Create the recipe dashboard image."""
    canvas = Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    
    # Get recipe data
    recipe = get_daily_recipe()
    
    # Header
    today = datetime.now().strftime("%A, %B %d")
    header = f"Recipe Inspiration • {today}"
    draw.text((20, 20), header, font=FONT_TITLE, fill=(40, 40, 60))
    
    # Recipe card background
    recipe_x = 20
    recipe_y = 70
    recipe_width = 500
    recipe_height = 320
    
    # Recipe card with white background for e-ink
    draw.rounded_rectangle([recipe_x - 10, recipe_y - 10, recipe_x + recipe_width, recipe_y + recipe_height], 
                          radius=12, outline=(200, 200, 220), width=2, fill=(255, 255, 255))
    
    # Recipe title
    draw.text((recipe_x, recipe_y), recipe["title"], font=FONT_TITLE, fill=(0, 0, 0))
    
    # Recipe info (time, difficulty)
    info_text = f"⏱️ {recipe['cook_time']} • 🎯 {recipe['difficulty']}"
    draw.text((recipe_x, recipe_y + 35), info_text, font=FONT_SMALL, fill=(80, 80, 100))
    
    # Ingredients section
    draw.text((recipe_x, recipe_y + 65), "Ingredients:", font=FONT_TEXT, fill=(40, 40, 60))
    
    ingredients = recipe["ingredients"]
    y_offset = recipe_y + 90
    
    for i, ingredient in enumerate(ingredients[:8]):  # Show max 8 ingredients
        if y_offset > recipe_y + 280:
            break
        
        # Truncate long ingredient names
        if len(ingredient) > 35:
            ingredient = ingredient[:32] + "..."
        
        draw.text((recipe_x + 20, y_offset), f"• {ingredient}", font=FONT_INGREDIENT, fill=(60, 60, 80))
        y_offset += 22
    
    # Cooking tip section (right side)
    tip_x = 550
    tip_y = 70
    tip_width = 230
    tip_height = 200
    
    draw.rounded_rectangle([tip_x - 10, tip_y - 10, tip_x + tip_width, tip_y + tip_height], 
                          radius=12, outline=(200, 200, 220), width=2, fill=(255, 255, 255))
    
    draw.text((tip_x, tip_y), "💡 Chef's Tip", font=FONT_TEXT, fill=(40, 40, 60))
    
    # Wrap tip text
    tip_text = recipe.get("tip", "Cook with love and patience!")
    tip_lines = wrap_text_to_width(tip_text, FONT_SMALL, tip_width - 20, draw)
    
    tip_y_offset = tip_y + 30
    for line in tip_lines:
        draw.text((tip_x, tip_y_offset), line, font=FONT_SMALL, fill=(80, 80, 100))
        tip_y_offset += 18
    
    # Seasonal cooking advice
    seasonal_tips = [
        "🍂 Perfect for autumn comfort!",
        "❄️ Warm up with this hearty dish",
        "🌸 Light and fresh for spring",
        "☀️ Great for summer cooking",
        "🌶️ Add extra spice if you like heat",
        "🧄 Garlic makes everything better",
        "🥬 Fresh herbs brighten any dish",
        "🧂 Taste and adjust seasoning"
    ]
    
    seasonal_tip = random.choice(seasonal_tips)
    draw.text((tip_x, tip_y + 150), seasonal_tip, font=FONT_SMALL, fill=(100, 100, 120))
    
    # Motivational cooking quote
    cooking_quotes = [
        "Cooking is love made visible ✨",
        "Good food is the foundation of happiness 🍽️",
        "The kitchen is the heart of the home ❤️",
        "Every meal is a chance to create magic 🪄",
        "Cooking is an art, and you're the artist 🎨"
    ]
    
    quote = random.choice(cooking_quotes)
    quote_y = 400
    draw.text((20, quote_y), quote, font=FONT_SMALL, fill=(100, 100, 120))
    
    # Sakura with cooking-themed commentary
    cook_time = recipe["cook_time"]
    difficulty = recipe["difficulty"]
    
    if difficulty == "Easy":
        comment = f"Sakura: Perfect for a relaxing evening! This {cook_time} recipe will be delicious! 👩‍🍳"
    elif difficulty == "Medium":
        comment = f"Sakura: A fun cooking challenge! Take your time with this {cook_time} recipe! Nyaa~ ✨"
    else:
        comment = f"Sakura: Ready for an adventure? This {cook_time} recipe will be worth the effort! 💪"
    
    sakura_add(
        canvas,
        text=comment,
        main=None,
        temp=None,
        units="metric",
        override="cooking",  # Force cooking outfit
        position="bottom-right",
        target_h=160,
        bubble_max_w=380,
    )
    
    return canvas

# === EPD Display ===

def display_on_epd(img: Image.Image):
    """Display on e-ink or save preview."""
    if epd_driver is None:
        logging.warning("Waveshare EPD driver not available — saving preview to out_recipe.png")
        img.save("out_recipe.png")
        return
    
    epd = epd_driver.EPD()
    epd.init()
    logging.info("Displaying recipe dashboard on EPD...")
    epd.display(epd.getbuffer(img))
    epd.sleep()
    logging.info("Done. EPD in sleep.")

def compose_recipe_dashboard_no_display():
    """Create the recipe dashboard image without displaying it on e-ink."""
    return compose_recipe_dashboard()

# === Main ===

def main():
    # Check for debug flag to clear cache
    if "--clear-cache" in sys.argv:
        logging.info("Clearing recipe cache...")
        if RECIPE_CACHE.exists():
            RECIPE_CACHE.unlink()
            logging.info("Recipe cache cleared")
    
    logging.info("Creating recipe dashboard...")
    dash_img = compose_recipe_dashboard()
    display_on_epd(dash_img)
    logging.info("Recipe dashboard complete!")

if __name__ == "__main__":
    main()
