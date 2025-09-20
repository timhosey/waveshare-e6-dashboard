#!/usr/bin/env python3
import sys, os
from PIL import Image, ImageDraw

EPD_LIB = "./lib"
if os.path.exists(EPD_LIB):
    sys.path.append(EPD_LIB)

from waveshare_epd import epd7in3e as epd_driver  # swap for your size

def main():
    epd = epd_driver.EPD()
    epd.init()  # init once

    W, H = epd.width, epd.height
    img = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle((10, 10, W-10, H-10), outline=(0, 0, 0), width=3)
    draw.text((24, 24), "Hello, Spectra 6! Nyaa~", fill=(0, 0, 0))

    epd.display(epd.getbuffer(img))  # single full refresh
    epd.sleep()                      # back to low power

if __name__ == "__main__":
    main()

