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

