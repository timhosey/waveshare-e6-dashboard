#!/bin/bash
# setup_archive_cron.sh
# Sets up daily archiving at 1 AM

set -euo pipefail

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}Setting up daily dashboard archiving...${NC}"

# Get the current directory
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="$(whoami)"

echo "Project root: $PROJECT_ROOT"
echo "User: $USER_NAME"

# Create cron job entry
CRON_ENTRY="0 1 * * * cd $PROJECT_ROOT && $PROJECT_ROOT/.venv/bin/python $PROJECT_ROOT/archive_dashboards.py >> $PROJECT_ROOT/logs/archive.log 2>&1"

echo -e "${YELLOW}Adding cron job:${NC}"
echo "$CRON_ENTRY"

# Add to crontab
(crontab -l 2>/dev/null; echo "$CRON_ENTRY") | crontab -

# Create logs directory
mkdir -p "$PROJECT_ROOT/logs"

echo -e "${GREEN}Daily archiving setup complete!${NC}"
echo ""
echo -e "${BLUE}Schedule:${NC} Every day at 1:00 AM"
echo -e "${BLUE}Logs:${NC} $PROJECT_ROOT/logs/archive.log"
echo -e "${BLUE}Archives:${NC} $PROJECT_ROOT/archive/"
echo ""
echo -e "${YELLOW}Useful commands:${NC}"
echo "  View current crontab:    crontab -l"
echo "  Edit crontab:           crontab -e"
echo "  Remove cron job:        crontab -e  # Delete the line"
echo "  Test archiving:         python archive_dashboards.py"
echo "  View archive summary:   python archive_dashboards.py --summary-only"
echo "  Cleanup old archives:   python archive_dashboards.py --cleanup-only"
