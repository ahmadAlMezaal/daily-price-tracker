# Daily Price Tracker

A Python-based investment tracker that sends daily summaries and intraday spike/dip alerts for Gold, ISWD, and HBKS via Telegram. Designed to run on a Raspberry Pi via cron.

## Features

- **Daily Summary**: Prices in GBP, daily/weekly/monthly trends
- **Intraday Alerts**: Notifications when assets move beyond configurable thresholds
- **Price Alerts**: Notifications when assets cross absolute price levels
- **Deduplication**: Won't spam you with the same alert multiple times per day

## Tracked Assets

| Asset | Ticker | Description |
|-------|--------|-------------|
| Gold | `GC=F` | Gold futures, converted from USD to GBP |
| ISWD | `ISWD.L` | iShares MSCI World Islamic ETF |
| HBKS | `HBKS.L` | HSBC Global Sukuk ETF |

## Quick Start (Raspberry Pi)

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/daily-price-tracker.git
cd daily-price-tracker

# Run the setup script
./setup_pi.sh
```

The setup script will:
1. Install Python dependencies
2. Prompt for your Telegram credentials
3. Send a test message
4. Configure cron jobs

## Telegram Bot Setup

Before running the setup script, you'll need a Telegram bot:

### 1. Create a Bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Choose a name (e.g., "My Price Tracker")
4. Choose a username (e.g., "mypricetracker_bot")
5. Copy the **bot token** (looks like `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 2. Get Your Chat ID

1. Start a chat with your new bot (search for it and press "Start")
2. Send any message to the bot
3. Open this URL in your browser (replace `YOUR_TOKEN` with your bot token):
   ```
   https://api.telegram.org/botYOUR_TOKEN/getUpdates
   ```
4. Find the `"chat":{"id":` value — this is your **chat ID**

## Manual Installation

If you prefer to set things up manually:

```bash
# Install dependencies
pip3 install -r requirements.txt

# Create config from template
cp config.example.json config.json

# Edit config.json with your Telegram credentials
nano config.json

# Create directories
mkdir -p data logs

# Test the setup
python3 tracker.py test

# Set up cron jobs manually (see below)
```

### Manual Cron Setup

Edit your crontab with `crontab -e` and add:

```cron
# Daily summary at 8:00 AM (Mon-Fri)
0 8 * * 1-5 cd /path/to/daily-price-tracker && python3 tracker.py summary >> logs/cron.log 2>&1

# Intraday watch every 15 min during market hours (Mon-Fri)
*/15 8-17 * * 1-5 cd /path/to/daily-price-tracker && python3 tracker.py watch >> logs/cron.log 2>&1
```

## Usage

```bash
# Send daily summary
python3 tracker.py summary

# Check for intraday alerts
python3 tracker.py watch

# Test Telegram connection
python3 tracker.py test

# Verbose output
python3 tracker.py -v summary
```

## Configuration

Edit `config.json` to customize:

```json
{
    "telegram_bot_token": "YOUR_BOT_TOKEN",
    "telegram_chat_id": "YOUR_CHAT_ID",
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
```

### Alert Thresholds

- `default_threshold_pct`: Default percentage threshold for intraday alerts
- `thresholds`: Per-asset percentage thresholds
- `price_alerts`: Absolute price levels that trigger alerts

## Adding New Assets

Edit `tracker.py` and add to the `ASSETS` dictionary:

```python
ASSETS = {
    # ... existing assets ...
    "new_asset": {
        "ticker": "TICKER.L",      # Yahoo Finance ticker
        "name": "Display Name",     # Name shown in messages
        "currency": "GBP",          # Native currency
        "convert_to_gbp": False,    # True if needs USD→GBP conversion
        "pence_to_pounds": True,    # True if quoted in pence
    },
}
```

Then add thresholds in `config.json`:

```json
{
    "intraday_alerts": {
        "thresholds": {
            "new_asset": 2.0
        }
    }
}
```

## Example Daily Summary

```
Daily Investment Summary
Saturday, 01 February 2025

Gold
Price: £2,145.32
🟢 +£12.45 (+0.58%)
5d: +1.23% | 22d: +3.45%

ISWD
Price: £5.67
🔴 -£0.03 (-0.53%)
5d: -0.12% | 22d: +2.10%

HBKS
Price: £23.45
🟢 +£0.15 (+0.64%)
5d: +0.89% | 22d: +1.56%

GBP/USD: 1.2650
```

## Example Alert

```
Intraday Alert (14:30)

📈 SPIKE: Gold
Current: £2,178.50
Open: £2,145.32
Change: +1.55% (threshold: ±1.5%)
```

## Troubleshooting

### Check the logs

```bash
# View recent logs
tail -50 logs/tracker.log

# View cron output
tail -50 logs/cron.log
```

### Test Telegram connection

```bash
python3 tracker.py test
```

### Common Issues

**"Config file not found"**
- Run `./setup_pi.sh` or copy `config.example.json` to `config.json`

**"Failed to send Telegram message"**
- Verify your bot token is correct
- Verify your chat ID is correct
- Make sure you've started a conversation with your bot

**"No data returned for ticker"**
- Yahoo Finance may be temporarily unavailable
- Check your internet connection
- The market may be closed (no live data)

**Alerts not sending**
- Check if an alert has already fired today (see `data/alerts_state.json`)
- Verify the threshold hasn't been met yet
- Check logs for errors

### Reset Alert State

To clear today's fired alerts and allow them to fire again:

```bash
rm data/alerts_state.json
```

### View Price History

```bash
cat data/price_history.json | python3 -m json.tool
```

## File Structure

```
daily-price-tracker/
├── tracker.py              # Main script
├── config.json             # Your configuration (gitignored)
├── config.example.json     # Template configuration
├── requirements.txt        # Python dependencies
├── setup_pi.sh             # Setup script
├── .gitignore
├── README.md
├── data/
│   ├── price_history.json  # 90-day rolling price history
│   └── alerts_state.json   # Today's fired alerts
└── logs/
    ├── tracker.log         # Application logs
    └── cron.log            # Cron job output
```

## License

MIT
