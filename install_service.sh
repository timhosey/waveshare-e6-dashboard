#!/bin/bash
# install_service.sh — helper to install eink-rotator systemd service
# Usage: ./install_service.sh [--user|--system]

set -euo pipefail

SERVICE_NAME="eink-rotator.service"
SERVICE_SRC="$(dirname "$0")/systemd/$SERVICE_NAME"

if [[ ! -f "$SERVICE_SRC" ]]; then
  echo "Error: $SERVICE_SRC not found. Run this script from repo root." >&2
  exit 1
fi

if [[ "${1:-}" == "--system" ]]; then
  echo "Installing system-wide service…"
  sudo cp "$SERVICE_SRC" /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable --now $SERVICE_NAME
  echo "System-wide service installed. View logs with: sudo journalctl -u $SERVICE_NAME -f"
else
  echo "Installing user service…"
  mkdir -p ~/.config/systemd/user
  cp "$SERVICE_SRC" ~/.config/systemd/user/
  systemctl --user daemon-reload
  systemctl --user enable --now $SERVICE_NAME
  echo "User service installed. View logs with: journalctl --user -u $SERVICE_NAME -f"
  echo "If you want it to run at boot without login, run: loginctl enable-linger $USER"
fi