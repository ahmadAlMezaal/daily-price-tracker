## Project Overview

Daily Price Tracker — a Python-based investment tracker that sends daily summaries and intraday spike/dip alerts via Telegram. Runs headlessly on a Raspberry Pi via cron.

## Tracked Assets

- **Gold** (`GC=F`) — USD-native, converted to GBP
- **ISWD** (`ISWD.L`) — iShares MSCI World Islamic ETF, GBP-native
- **HBKS** (`HBKS.L`) — HSBC Global Sukuk ETF, GBP-native
- **Brent Crude** (`BZ=F`) — USD-native, converted to GBP
- **GBP/USD** (`GBPUSD=X`) — exchange rate alerts

All investments are halal-compliant.

## Tech Stack

- Python 3, yfinance, requests, pytz
- Telegram Bot API for notifications
- Raspberry Pi (headless, SSH, venv, cron)
- Config-driven via `config.json` (gitignored — contains secrets)

## Key Commands

```bash
python3 tracker.py summary   # Daily price summary
python3 tracker.py watch     # Intraday spike/dip alerts
python3 tracker.py digest    # Weekly digest (Friday)
python3 tracker.py test      # Test Telegram connection
```

## Project Structure

```
tracker.py              # Main script — all logic lives here
config.json             # User config with Telegram creds + thresholds (gitignored)
config.example.json     # Template config (committed)
install_crons.sh        # Idempotent cron installer (uses venv Python)
setup_pi.sh             # First-time setup script
requirements.txt        # Python dependencies
data/                   # Runtime data (gitignored)
  price_history.json    # 90-day rolling price history
  alerts_state.json     # Today's fired alerts
logs/                   # Log files (gitignored)
```

## Development Workflow

- All work is tracked in Linear under the **Daily Price Tracker** project (Engineering team)
- Every feature or change gets a **branch** and a **PR against `main`**
- PRs must be **linked to the corresponding Linear ticket**
- Branch naming follows Linear's convention: `eng-XX/ticket-slug`
- After merge, deploy to Pi: `git pull && ./install_crons.sh`

## Architecture Notes

- Single-file architecture — all logic is in `tracker.py`
- `ASSETS` dict defines tracked assets with ticker, currency, and display config
- LSE tickers (`.L`) have smart pence-to-pounds detection (threshold > 100)
- Alert deduplication: each alert type fires once per direction per day via `alerts_state.json`
- GBP/USD rate is fetched once and shared across all USD→GBP conversions
- VIX (`^VIX`) is display-only in the daily summary — no alerts, no history
- Price history is a 90-day rolling window stored in JSON

## Config Structure

`config.json` contains:
- `telegram_bot_token` / `telegram_chat_id` — Telegram credentials
- `intraday_alerts.thresholds` — per-asset percentage thresholds for watch alerts
- `price_alerts` — absolute price levels (above/below) per asset
- GBP/USD has its own threshold and price alerts in the same structure

## Deployment

Runs on a Raspberry Pi with:
- Python venv at `~/daily-price-tracker/venv/` (PEP 668 enforced on Pi OS)
- Cron jobs installed via `./install_crons.sh` (tagged with `# daily-price-tracker`)
- Three cron schedules: daily summary (8am), intraday watch (every 15min), weekly digest (6pm Friday)

## Testing

- `python3 tracker.py test` — verifies Telegram integration
- `python3 tracker.py -v summary` — verbose mode for debugging
- Temporarily lower thresholds to test alert firing
- Check `logs/tracker.log` for application logs, `logs/cron.log` for cron output

## Important Conventions

- This repo is **public** — never commit secrets or personal financial data
- `config.json` is gitignored and must stay that way
- All prices are displayed in both GBP and USD
- Telegram messages use Markdown formatting
- Keep the single-file architecture unless there's a strong reason to split