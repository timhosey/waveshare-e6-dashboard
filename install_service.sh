#!/bin/bash
# install_service.sh — helper to install eink-rotator systemd service
# Usage: ./install_service.sh [--user|--system]

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SERVICE_NAME="eink-rotator.service"
SERVICE_SRC="$(dirname "$0")/systemd/$SERVICE_NAME"

# Get current directory (should be the project root)
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="$(whoami)"

echo -e "${BLUE}E-Ink Dashboard Service Installer${NC}"
echo "=================================="

# Validation functions
check_file_exists() {
    local file="$1"
    local description="$2"
    if [[ ! -f "$file" ]]; then
        echo -e "${RED}Error: $description not found: $file${NC}" >&2
        exit 1
    fi
}

check_directory_exists() {
    local dir="$1"
    local description="$2"
    if [[ ! -d "$dir" ]]; then
        echo -e "${RED}Error: $description not found: $dir${NC}" >&2
        exit 1
    fi
}

# Validate prerequisites
echo -e "${YELLOW}Validating prerequisites...${NC}"

check_file_exists "$SERVICE_SRC" "Service template"
check_file_exists "$PROJECT_ROOT/.env" "Environment file (.env)"
check_directory_exists "$PROJECT_ROOT/.venv" "Virtual environment (.venv)"
check_file_exists "$PROJECT_ROOT/.venv/bin/activate" "Virtual environment activation script"
check_file_exists "$PROJECT_ROOT/dashboard.py" "Main dashboard script"

# Check if user is in required groups
echo -e "${YELLOW}Checking user permissions...${NC}"
if ! groups "$USER_NAME" | grep -q "gpio\|spi"; then
    echo -e "${YELLOW}Warning: User $USER_NAME may not be in 'gpio' or 'spi' groups.${NC}"
    echo -e "${YELLOW}If you have display issues, run:${NC}"
    echo -e "${BLUE}  sudo usermod -aG gpio,spi $USER_NAME${NC}"
    echo -e "${YELLOW}Then log out and back in.${NC}"
fi

# Create service file with dynamic paths
echo -e "${YELLOW}Preparing service file...${NC}"
TEMP_SERVICE="/tmp/${SERVICE_NAME}.$$"

# Replace placeholders in the service file
sed -e "s|%WORKING_DIR%|$PROJECT_ROOT|g" \
    -e "s|%USER%|$USER_NAME|g" \
    "$SERVICE_SRC" > "$TEMP_SERVICE"

echo -e "${GREEN}Service configuration:${NC}"
echo "  Project root: $PROJECT_ROOT"
echo "  User: $USER_NAME"
echo "  Virtual env: $PROJECT_ROOT/.venv"
echo "  Environment: $PROJECT_ROOT/.env"

# Install service
if [[ "${1:-}" == "--system" ]]; then
    echo -e "${YELLOW}Installing system-wide service...${NC}"
    
    # Check if running as root for system service
    if [[ "$EUID" -ne 0 ]]; then
        echo -e "${RED}Error: System service installation requires root privileges.${NC}" >&2
        echo -e "${YELLOW}Either run with sudo or use --user for user service.${NC}"
        exit 1
    fi
    
    cp "$TEMP_SERVICE" "/etc/systemd/system/$SERVICE_NAME"
    systemctl daemon-reload
    systemctl enable --now "$SERVICE_NAME"
    
    echo -e "${GREEN}System-wide service installed successfully!${NC}"
    echo -e "${BLUE}View logs with: sudo journalctl -u $SERVICE_NAME -f${NC}"
    
else
    echo -e "${YELLOW}Installing user service...${NC}"
    
    # Create user systemd directory
    mkdir -p "$HOME/.config/systemd/user"
    
    # Install service file
    cp "$TEMP_SERVICE" "$HOME/.config/systemd/user/$SERVICE_NAME"
    
    # Reload and enable
    systemctl --user daemon-reload
    systemctl --user enable --now "$SERVICE_NAME"
    
    echo -e "${GREEN}User service installed successfully!${NC}"
    echo -e "${BLUE}View logs with: journalctl --user -u $SERVICE_NAME -f${NC}"
    
    # Check if user lingering is enabled
    if ! loginctl show-user "$USER_NAME" | grep -q "Linger=yes"; then
        echo -e "${YELLOW}Note: Service will only run when you're logged in.${NC}"
        echo -e "${YELLOW}To run at boot without login, enable user lingering:${NC}"
        echo -e "${BLUE}  loginctl enable-linger $USER_NAME${NC}"
    else
        echo -e "${GREEN}User lingering is enabled - service will start at boot.${NC}"
    fi
fi

# Clean up temp file
rm -f "$TEMP_SERVICE"

# Show service status
echo -e "\n${BLUE}Service Status:${NC}"
if [[ "${1:-}" == "--system" ]]; then
    systemctl status "$SERVICE_NAME" --no-pager -l
else
    systemctl --user status "$SERVICE_NAME" --no-pager -l
fi

echo -e "\n${GREEN}Installation complete! 🎉${NC}"
echo -e "${YELLOW}Useful commands:${NC}"
if [[ "${1:-}" == "--system" ]]; then
    echo "  Stop:   sudo systemctl stop $SERVICE_NAME"
    echo "  Start:  sudo systemctl start $SERVICE_NAME"
    echo "  Restart: sudo systemctl restart $SERVICE_NAME"
    echo "  Logs:   sudo journalctl -u $SERVICE_NAME -f"
else
    echo "  Stop:   systemctl --user stop $SERVICE_NAME"
    echo "  Start:  systemctl --user start $SERVICE_NAME"
    echo "  Restart: systemctl --user restart $SERVICE_NAME"
    echo "  Logs:   journalctl --user -u $SERVICE_NAME -f"
fi