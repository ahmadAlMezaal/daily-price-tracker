#!/bin/bash
#
# Daily Price Tracker - Cron Job Installer
#
# Idempotently installs all required cron jobs.
# Safe to re-run after every git pull — removes old entries first,
# so running it multiple times never creates duplicates.
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRACKER_PATH="$SCRIPT_DIR/tracker.py"
CRON_TAG="# daily-price-tracker"

# Use venv Python if available, fall back to system python3
VENV_PYTHON="$SCRIPT_DIR/venv/bin/python3"
if [ -x "$VENV_PYTHON" ]; then
    PYTHON_PATH="$VENV_PYTHON"
else
    PYTHON_PATH=$(which python3)
fi

echo "Installing cron jobs for Daily Price Tracker..."
echo "  Repo: $SCRIPT_DIR"
echo "  Python: $PYTHON_PATH"
echo

# Remove any existing tracker cron entries, then add fresh ones
crontab -l 2>/dev/null | grep -v "$CRON_TAG" > /tmp/crontab_tracker.tmp || true

cat >> /tmp/crontab_tracker.tmp << EOF
0 8 * * 1-5 cd $SCRIPT_DIR && $PYTHON_PATH $TRACKER_PATH summary >> $SCRIPT_DIR/logs/cron.log 2>&1 $CRON_TAG
*/15 8-17 * * 1-5 cd $SCRIPT_DIR && $PYTHON_PATH $TRACKER_PATH watch >> $SCRIPT_DIR/logs/cron.log 2>&1 $CRON_TAG
0 18 * * 5 cd $SCRIPT_DIR && $PYTHON_PATH $TRACKER_PATH digest >> $SCRIPT_DIR/logs/cron.log 2>&1 $CRON_TAG
EOF

crontab /tmp/crontab_tracker.tmp
rm /tmp/crontab_tracker.tmp

echo "Cron jobs installed:"
echo "  - Daily summary:   8:00 AM Mon-Fri"
echo "  - Intraday watch:  Every 15 min, 8AM-5PM Mon-Fri"
echo "  - Weekly digest:   6:00 PM Friday"
echo
echo "Verify with: crontab -l"
