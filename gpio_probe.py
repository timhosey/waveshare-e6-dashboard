# gpio_probe.py
import os
os.environ.setdefault("GPIOZERO_PIN_FACTORY","lgpio")
from gpiozero import Button
print("Factory:", os.environ.get("GPIOZERO_PIN_FACTORY"))
b = Button(24, pull_up=False)  # BUSY pin default for Waveshare HAT
print("Edge detection OK on GPIO24 ✨")
