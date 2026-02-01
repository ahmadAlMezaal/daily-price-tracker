#!/bin/bash
#
# Daily Price Tracker - Raspberry Pi Setup Script
#
# This script:
# 1. Installs Python dependencies
# 2. Creates config.json from your Telegram credentials
# 3. Sets up cron jobs for daily summaries and intraday alerts
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================"
echo "  Daily Price Tracker - Setup"
echo "========================================"
echo

# Check Python 3
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required but not installed."
    echo "Install it with: sudo apt install python3 python3-pip"
    exit 1
fi

# Install dependencies
echo "Installing Python dependencies..."
pip3 install --user -r requirements.txt
echo "Dependencies installed."
echo

# Create config.json if it doesn't exist
if [ -f "config.json" ]; then
    echo "config.json already exists."
    read -p "Do you want to reconfigure? (y/N): " reconfigure
    if [[ ! "$reconfigure" =~ ^[Yy]$ ]]; then
        echo "Keeping existing configuration."
        SKIP_CONFIG=true
    fi
fi

if [ "$SKIP_CONFIG" != "true" ]; then
    echo "========================================"
    echo "  Telegram Configuration"
    echo "========================================"
    echo
    echo "You need a Telegram bot token and chat ID."
    echo
    echo "To get these:"
    echo "1. Open Telegram and search for @BotFather"
    echo "2. Send /newbot and follow the prompts"
    echo "3. Copy the bot token (looks like: 123456789:ABCdef...)"
    echo "4. Start a chat with your new bot"
    echo "5. Visit: https://api.telegram.org/bot<TOKEN>/getUpdates"
    echo "6. Send a message to your bot, refresh the page"
    echo "7. Find your chat_id in the response"
    echo
    read -p "Enter your Telegram bot token: " BOT_TOKEN
    read -p "Enter your Telegram chat ID: " CHAT_ID

    if [ -z "$BOT_TOKEN" ] || [ -z "$CHAT_ID" ]; then
        echo "Error: Bot token and chat ID are required."
        exit 1
    fi

    # Create config.json
    cat > config.json << EOF
{
    "telegram_bot_token": "$BOT_TOKEN",
    "telegram_chat_id": "$CHAT_ID",
    "intraday_alerts": {
        "default_threshold_pct": 2.0,
        "thresholds": {
            "gold_gbp": 1.5,
            "iswd": 2.0,
            "hbks": 2.0
        }
    },
    "price_alerts": {
        "gold_gbp": {
            "above": 2200.00,
            "below": 1800.00
        }
    }
}
EOF
    echo "Configuration saved to config.json"
    echo
fi

# Create data and logs directories
echo "Creating data and logs directories..."
mkdir -p data logs
echo "Directories created."
echo

# Make tracker.py executable
chmod +x tracker.py

# Test the configuration
echo "========================================"
echo "  Testing Telegram Connection"
echo "========================================"
echo
python3 tracker.py test

if [ $? -ne 0 ]; then
    echo
    echo "Test failed! Please check your bot token and chat ID."
    echo "You can re-run this script to reconfigure."
    exit 1
fi

echo
echo "========================================"
echo "  Setting up Cron Jobs"
echo "========================================"
echo

# Get absolute path to tracker.py
TRACKER_PATH="$SCRIPT_DIR/tracker.py"
PYTHON_PATH=$(which python3)

# Remove any existing tracker cron jobs
crontab -l 2>/dev/null | grep -v "daily-price-tracker" | grep -v "$TRACKER_PATH" > /tmp/crontab.tmp || true

# Add new cron jobs
# Daily summary at 8:00 AM London time (weekdays)
echo "0 8 * * 1-5 cd $SCRIPT_DIR && $PYTHON_PATH $TRACKER_PATH summary >> $SCRIPT_DIR/logs/cron.log 2>&1 # daily-price-tracker" >> /tmp/crontab.tmp

# Intraday watch every 15 minutes during market hours (8-17, weekdays)
echo "*/15 8-17 * * 1-5 cd $SCRIPT_DIR && $PYTHON_PATH $TRACKER_PATH watch >> $SCRIPT_DIR/logs/cron.log 2>&1 # daily-price-tracker" >> /tmp/crontab.tmp

# Install new crontab
crontab /tmp/crontab.tmp
rm /tmp/crontab.tmp

echo "Cron jobs installed:"
echo "  - Daily summary: 8:00 AM (Mon-Fri)"
echo "  - Intraday watch: Every 15 min, 8AM-5PM (Mon-Fri)"
echo
echo "To view cron jobs: crontab -l"
echo "To edit cron jobs: crontab -e"
echo

echo "========================================"
echo "  Setup Complete!"
echo "========================================"
echo
echo "Your Daily Price Tracker is now configured."
echo
echo "Manual commands:"
echo "  python3 tracker.py summary  - Send daily summary now"
echo "  python3 tracker.py watch    - Check for alerts now"
echo "  python3 tracker.py test     - Send test message"
echo
echo "Logs are saved to: $SCRIPT_DIR/logs/"
echo "Price history is saved to: $SCRIPT_DIR/data/"
echo
echo "To customize alert thresholds, edit config.json"
echo
