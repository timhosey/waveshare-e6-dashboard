📄 File to include in repo

Save this as: systemd/eink-rotator.service

[Unit]
Description=E-Ink Dashboard Rotator (Sakura-chan)
After=network-online.target

[Service]
Type=simple
# — Change to your repo location —
WorkingDirectory=/home/tim/Scripting/e-ink_display

# Load environment (for OWM_API_KEY, coords, ROTATE_SECONDS, etc.)
EnvironmentFile=/home/tim/Scripting/e-ink_display/.env

# GPIO backend hint (works with your Waveshare lib)
Environment=GPIOZERO_PIN_FACTORY=lgpio

# Use your venv’s python
ExecStart=/home/tim/Scripting/e-ink_display/.venv/bin/python /home/tim/Scripting/e-ink_display/dashboard.py

# Make sure the service keeps coming back if it crashes
Restart=always
RestartSec=5

# Access to SPI/GPIO devices without running as root
SupplementaryGroups=spi gpio

# A little limit bump just in case
NoNewPrivileges=true

[Install]
WantedBy=default.target

Tip: if your project path/user is different on the Pi, update those paths before installing.

⸻

📘 README: How to install on Raspberry Pi (user service)

1) Prereqs
	•	You’ve created a venv and can run:

/home/tim/Scripting/e-ink_display/.venv/bin/python dashboard.py


	•	Your .env exists at:

/home/tim/Scripting/e-ink_display/.env

with values like:

OWM_API_KEY=xxxxx
OWM_LAT=47.6062
OWM_LON=-122.3321
OWM_UNITS=imperial
ROTATE_SECONDS=120

(The app also supports DASH_CYCLE, DASH_TIMEOUT, etc.)

2) Install as a user service (recommended)

# from the repo root
mkdir -p ~/.config/systemd/user
cp systemd/eink-rotator.service ~/.config/systemd/user/

# reload user units
systemctl --user daemon-reload

# enable on login/boot and start now
systemctl --user enable --now eink-rotator.service

If you want it to start even when you’re not logged in (headless boot), enable user lingering:

loginctl enable-linger $USER

3) Check logs

journalctl --user -u eink-rotator.service -f

You should see logs from the rotator like:

Rotation order: comic, weather
Rotate interval: 120s | Timeout: 90s
Launching: /home/tim/.../.venv/bin/python dash_weather.py
...

4) Common tweaks
	•	Change the rotate interval:
	•	Edit .env → ROTATE_SECONDS=300, then:

systemctl --user restart eink-rotator.service


	•	Run a specific sequence:
	•	.env → DASH_CYCLE=weather,comic
	•	If you move the project:
	•	Update WorkingDirectory, EnvironmentFile, and ExecStart in the unit, then:

systemctl --user daemon-reload
systemctl --user restart eink-rotator.service



5) Permissions (GPIO/SPI)

Make sure your user is in the gpio and spi groups (usually default on Pi OS, but just in case):

sudo usermod -aG gpio,spi $USER
# log out/in or reboot for group changes to apply


⸻

🧪 Optional: system-wide service (root)

If you prefer a system service instead of user service, copy to /etc/systemd/system/ and drop the --user bits in the commands:

sudo cp systemd/eink-rotator.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now eink-rotator.service
sudo journalctl -u eink-rotator.service -f

Make sure paths and permissions still point to your user venv and user .env.

