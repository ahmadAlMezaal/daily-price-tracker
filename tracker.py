#!/usr/bin/env python3
"""
Daily Investment Price Tracker

Tracks gold (GC=F), ISWD.L, and HBKS.L prices.
Sends daily summaries and intraday spike/dip alerts via Telegram.
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytz
import requests
import yfinance as yf

# Project paths
PROJECT_DIR = Path(__file__).parent.resolve()
CONFIG_PATH = PROJECT_DIR / "config.json"
DATA_DIR = PROJECT_DIR / "data"
LOGS_DIR = PROJECT_DIR / "logs"
HISTORY_PATH = DATA_DIR / "price_history.json"
ALERTS_STATE_PATH = DATA_DIR / "alerts_state.json"
LOG_PATH = LOGS_DIR / "tracker.log"

# Timezone
LONDON_TZ = pytz.timezone("Europe/London")

# Assets configuration
ASSETS = {
    "gold_gbp": {
        "ticker": "GC=F",
        "name": "Gold",
        "emoji": "🥇",
        "native_currency": "USD",
        "unit": "per oz",
    },
    "iswd": {
        "ticker": "ISWD.L",
        "name": "ISWD",
        "emoji": "📈",
        "native_currency": "GBP",
        "unit": "",
    },
    "hbks": {
        "ticker": "HBKS.L",
        "name": "HBKS",
        "emoji": "📊",
        "native_currency": "GBP",
        "unit": "",
    },
    "brent": {
        "ticker": "BZ=F",
        "name": "Brent Crude",
        "emoji": "🛢️",
        "native_currency": "USD",
        "unit": "per bbl",
    },
}

# LSE tickers that are known to be quoted in pence (not pounds)
# If raw value > 100, assume pence and divide by 100
PENCE_THRESHOLD = 100

# History retention
HISTORY_DAYS = 90


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure logging to file and optionally stdout."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("tracker")
    logger.setLevel(logging.DEBUG)

    # File handler
    file_handler = logging.FileHandler(LOG_PATH)
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s"
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Console handler (if interactive)
    if verbose or sys.stdout.isatty():
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter("%(levelname)s: %(message)s")
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

    return logger


def load_config() -> dict:
    """Load configuration from config.json."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Config file not found: {CONFIG_PATH}\n"
            "Run setup_pi.sh or copy config.example.json to config.json"
        )

    with open(CONFIG_PATH) as f:
        return json.load(f)


def send_telegram_message(config: dict, message: str, logger: logging.Logger) -> bool:
    """Send a message via Telegram bot API."""
    token = config["telegram_bot_token"]
    chat_id = config["telegram_chat_id"]

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        logger.info("Telegram message sent successfully")
        return True
    except requests.RequestException as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return False


VIX_LABELS = [
    (12, "Low volatility (calm)"),
    (20, "Normal"),
    (30, "Elevated fear"),
    (float("inf"), "High fear"),
]


def get_vix(logger: logging.Logger) -> float | None:
    """Fetch the current VIX level."""
    try:
        ticker = yf.Ticker("^VIX")
        data = ticker.history(period="1d")
        if data.empty:
            logger.debug("No data returned for ^VIX")
            return None
        value = float(data["Close"].iloc[-1])
        logger.debug(f"VIX: {value:.2f}")
        return value
    except Exception as e:
        logger.debug(f"Failed to fetch VIX: {e}")
        return None


def format_vix(value: float) -> str:
    """Format VIX value with a human-readable sentiment label."""
    label = "Unknown"
    for threshold, lbl in VIX_LABELS:
        if value < threshold:
            label = lbl
            break
    return f"🌡️ Market Sentiment: VIX {value:.1f} ({label})"


def get_gbp_usd_rate(logger: logging.Logger) -> dict | None:
    """Fetch the current GBP/USD exchange rate with open price."""
    try:
        ticker = yf.Ticker("GBPUSD=X")
        data = ticker.history(period="1d")
        if data.empty:
            logger.error("No data returned for GBPUSD=X")
            return None
        rate = float(data["Close"].iloc[-1])
        open_rate = float(data["Open"].iloc[-1])
        logger.debug(f"GBP/USD rate: {rate} (open: {open_rate})")
        return {"rate": rate, "open": open_rate}
    except Exception as e:
        logger.error(f"Failed to fetch GBP/USD rate: {e}")
        return None


def get_asset_price(
    asset_key: str,
    asset_config: dict,
    gbp_usd_rate: float | None,
    logger: logging.Logger
) -> dict | None:
    """
    Fetch current price for an asset.
    Returns dict with prices in both GBP and USD, or None on failure.
    """
    ticker_symbol = asset_config["ticker"]
    native_currency = asset_config["native_currency"]

    try:
        ticker = yf.Ticker(ticker_symbol)
        data = ticker.history(period="2d")

        if data.empty:
            logger.error(f"No data returned for {ticker_symbol}")
            return None

        current_raw = float(data["Close"].iloc[-1])
        open_raw = float(data["Open"].iloc[-1])

        # Get previous close if available
        if len(data) > 1:
            prev_close_raw = float(data["Close"].iloc[-2])
        else:
            prev_close_raw = open_raw

        # Smart pence detection for LSE tickers
        # If the ticker ends in .L and raw value > 100, it's likely in pence
        if ticker_symbol.endswith(".L") and current_raw > PENCE_THRESHOLD:
            logger.debug(f"{ticker_symbol} raw value {current_raw} > {PENCE_THRESHOLD}, converting from pence to pounds")
            current_raw = current_raw / 100
            open_raw = open_raw / 100
            prev_close_raw = prev_close_raw / 100

        # Calculate prices in both currencies
        if native_currency == "USD":
            # Native is USD, convert to GBP
            price_usd = current_raw
            open_usd = open_raw
            prev_close_usd = prev_close_raw

            if gbp_usd_rate is None:
                logger.error(f"Cannot convert {ticker_symbol} to GBP - no exchange rate")
                return None

            price_gbp = price_usd / gbp_usd_rate
            open_gbp = open_usd / gbp_usd_rate
            prev_close_gbp = prev_close_usd / gbp_usd_rate

        else:  # native_currency == "GBP"
            # Native is GBP, convert to USD
            price_gbp = current_raw
            open_gbp = open_raw
            prev_close_gbp = prev_close_raw

            if gbp_usd_rate is not None:
                price_usd = price_gbp * gbp_usd_rate
                open_usd = open_gbp * gbp_usd_rate
                prev_close_usd = prev_close_gbp * gbp_usd_rate
            else:
                price_usd = None
                open_usd = None
                prev_close_usd = None

        return {
            "price_gbp": price_gbp,
            "open_gbp": open_gbp,
            "prev_close_gbp": prev_close_gbp,
            "price_usd": price_usd,
            "open_usd": open_usd,
            "prev_close_usd": prev_close_usd,
        }

    except Exception as e:
        logger.error(f"Failed to fetch price for {ticker_symbol}: {e}")
        return None


def load_history() -> dict:
    """Load price history from file."""
    if not HISTORY_PATH.exists():
        return {"entries": []}

    with open(HISTORY_PATH) as f:
        return json.load(f)


def save_history(history: dict) -> None:
    """Save price history to file, trimming to HISTORY_DAYS."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Trim old entries
    cutoff = datetime.now(LONDON_TZ) - timedelta(days=HISTORY_DAYS)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    history["entries"] = [
        entry for entry in history["entries"]
        if entry["date"] >= cutoff_str
    ]

    with open(HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2)


def calculate_trend(history: dict, asset_key: str, days: int) -> float | None:
    """Calculate percentage change over the last N trading days."""
    entries = history.get("entries", [])

    # Get entries for this asset with prices
    relevant = [
        e for e in entries
        if asset_key in e.get("prices", {}) and e["prices"][asset_key] is not None
    ]

    if len(relevant) < 2:
        return None

    # Sort by date descending
    relevant.sort(key=lambda x: x["date"], reverse=True)

    current = relevant[0]["prices"][asset_key]

    # Find entry approximately N days ago
    if len(relevant) <= days:
        past = relevant[-1]["prices"][asset_key]
    else:
        past = relevant[days]["prices"][asset_key]

    if past == 0:
        return None

    return ((current - past) / past) * 100


def load_alerts_state() -> dict:
    """Load today's alert state."""
    if not ALERTS_STATE_PATH.exists():
        return {"date": None, "fired": []}

    with open(ALERTS_STATE_PATH) as f:
        state = json.load(f)

    # Reset if it's a new day
    today = datetime.now(LONDON_TZ).strftime("%Y-%m-%d")
    if state.get("date") != today:
        return {"date": today, "fired": []}

    return state


def save_alerts_state(state: dict) -> None:
    """Save alert state to file."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    today = datetime.now(LONDON_TZ).strftime("%Y-%m-%d")
    state["date"] = today

    with open(ALERTS_STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def format_price_gbp(price: float) -> str:
    """Format price in GBP."""
    return f"£{price:,.2f}"


def format_price_usd(price: float) -> str:
    """Format price in USD."""
    return f"${price:,.2f}"


def format_change(change: float, change_pct: float) -> str:
    """Format price change with indicator."""
    indicator = "🟢" if change >= 0 else "🔴"
    sign = "+" if change >= 0 else ""
    return f"{indicator} {sign}{format_price_gbp(change)} ({sign}{change_pct:.2f}%)"


def format_trend(trend: float | None, label: str) -> str:
    """Format trend percentage."""
    if trend is None:
        return f"{label}: N/A"
    sign = "+" if trend >= 0 else ""
    return f"{label}: {sign}{trend:.2f}%"


def cmd_summary(config: dict, logger: logging.Logger) -> None:
    """Generate and send daily summary."""
    logger.info("Generating daily summary...")

    # Get exchange rate
    gbp_usd_data = get_gbp_usd_rate(logger)
    gbp_usd_rate = gbp_usd_data["rate"] if gbp_usd_data else None
    if gbp_usd_rate is None:
        logger.warning("Could not fetch exchange rate, USD assets will be skipped")

    # Load history
    history = load_history()

    # Fetch all prices
    prices = {}
    today = datetime.now(LONDON_TZ).strftime("%Y-%m-%d")

    lines = ["*Daily Investment Summary*"]
    lines.append(f"_{datetime.now(LONDON_TZ).strftime('%A, %d %B %Y')}_")
    lines.append("")

    for asset_key, asset_config in ASSETS.items():
        price_data = get_asset_price(asset_key, asset_config, gbp_usd_rate, logger)

        if price_data is None:
            lines.append(f"*{asset_config['name']}*: ⚠️ Data unavailable")
            lines.append("")
            continue

        current_gbp = price_data["price_gbp"]
        current_usd = price_data["price_usd"]
        prev_close_gbp = price_data["prev_close_gbp"]
        prices[asset_key] = current_gbp

        # Daily change (in GBP)
        daily_change = current_gbp - prev_close_gbp
        daily_change_pct = (daily_change / prev_close_gbp) * 100 if prev_close_gbp != 0 else 0

        # Format header with emoji
        emoji = asset_config.get("emoji", "📊")
        unit = asset_config.get("unit", "")
        unit_suffix = f" {unit}" if unit else ""

        lines.append(f"{emoji} *{asset_config['name']}*")

        # Show prices in both currencies
        # Native currency first (USD for gold, GBP for ETFs)
        if asset_config["native_currency"] == "USD":
            # Gold: show USD first, then GBP
            price_line = f"   {format_price_gbp(current_gbp)} / {format_price_usd(current_usd)}{unit_suffix}"
        else:
            # ETFs: show GBP first, then USD
            if current_usd is not None:
                price_line = f"   {format_price_gbp(current_gbp)} / {format_price_usd(current_usd)}{unit_suffix}"
            else:
                price_line = f"   {format_price_gbp(current_gbp)}{unit_suffix}"

        lines.append(price_line)
        lines.append(f"   {format_change(daily_change, daily_change_pct)}")

        # Weekly trend (5 trading days)
        weekly = calculate_trend(history, asset_key, 5)
        monthly = calculate_trend(history, asset_key, 22)

        if weekly is not None or monthly is not None:
            trends = []
            if weekly is not None:
                trends.append(format_trend(weekly, "5d"))
            if monthly is not None:
                trends.append(format_trend(monthly, "22d"))
            lines.append(f"   {' | '.join(trends)}")

        lines.append("")

    # VIX sentiment
    vix = get_vix(logger)
    if vix is not None:
        lines.append(format_vix(vix))
        lines.append("")

    # Exchange rate
    if gbp_usd_rate:
        lines.append(f"_GBP/USD: {gbp_usd_rate:.4f}_")

    # Save today's prices to history
    if prices:
        # Remove any existing entry for today
        history["entries"] = [e for e in history["entries"] if e["date"] != today]
        history["entries"].append({
            "date": today,
            "prices": prices,
            "gbp_usd_rate": gbp_usd_rate,
        })
        save_history(history)
        logger.info(f"Saved prices to history for {today}")

    # Send message
    message = "\n".join(lines)
    logger.debug(f"Summary message:\n{message}")
    send_telegram_message(config, message, logger)


def cmd_watch(config: dict, logger: logging.Logger) -> None:
    """Check for intraday spikes/dips and price alerts."""
    logger.info("Running intraday watch...")

    # Load alert state
    state = load_alerts_state()
    alerts_to_send = []

    # Get exchange rate
    gbp_usd_data = get_gbp_usd_rate(logger)
    gbp_usd_rate = gbp_usd_data["rate"] if gbp_usd_data else None
    if gbp_usd_rate is None:
        logger.warning("Could not fetch exchange rate, USD assets will be skipped")

    # Get alert thresholds
    intraday_config = config.get("intraday_alerts", {})
    default_threshold = intraday_config.get("default_threshold_pct", 2.0)
    thresholds = intraday_config.get("thresholds", {})
    price_alerts = config.get("price_alerts", {})

    for asset_key, asset_config in ASSETS.items():
        price_data = get_asset_price(asset_key, asset_config, gbp_usd_rate, logger)

        if price_data is None:
            continue

        current = price_data["price_gbp"]
        open_price = price_data["open_gbp"]

        # Check intraday threshold
        threshold = thresholds.get(asset_key, default_threshold)
        if open_price != 0:
            change_pct = ((current - open_price) / open_price) * 100

            if abs(change_pct) >= threshold:
                alert_key = f"intraday_{asset_key}_{'+' if change_pct > 0 else '-'}"

                if alert_key not in state["fired"]:
                    direction = "📈 SPIKE" if change_pct > 0 else "📉 DIP"
                    alerts_to_send.append(
                        f"{direction}: *{asset_config['name']}*\n"
                        f"Current: {format_price_gbp(current)}\n"
                        f"Open: {format_price_gbp(open_price)}\n"
                        f"Change: {change_pct:+.2f}% (threshold: ±{threshold}%)"
                    )
                    state["fired"].append(alert_key)
                    logger.info(f"Alert triggered: {alert_key}")

        # Check absolute price alerts
        asset_price_alerts = price_alerts.get(asset_key, {})

        above = asset_price_alerts.get("above")
        if above is not None and current >= above:
            alert_key = f"price_above_{asset_key}"
            if alert_key not in state["fired"]:
                alerts_to_send.append(
                    f"🔔 *{asset_config['name']}* above {format_price_gbp(above)}!\n"
                    f"Current: {format_price_gbp(current)}"
                )
                state["fired"].append(alert_key)
                logger.info(f"Alert triggered: {alert_key}")

        below = asset_price_alerts.get("below")
        if below is not None and current <= below:
            alert_key = f"price_below_{asset_key}"
            if alert_key not in state["fired"]:
                alerts_to_send.append(
                    f"🔔 *{asset_config['name']}* below {format_price_gbp(below)}!\n"
                    f"Current: {format_price_gbp(current)}"
                )
                state["fired"].append(alert_key)
                logger.info(f"Alert triggered: {alert_key}")

    # GBP/USD exchange rate alerts
    if gbp_usd_data is not None:
        gbp_usd_current = gbp_usd_data["rate"]
        gbp_usd_open = gbp_usd_data["open"]

        # Intraday threshold check
        gbpusd_threshold = thresholds.get("gbpusd", 1.0)
        if gbp_usd_open != 0:
            gbpusd_change_pct = ((gbp_usd_current - gbp_usd_open) / gbp_usd_open) * 100

            if abs(gbpusd_change_pct) >= gbpusd_threshold:
                alert_key = f"intraday_gbpusd_{'+' if gbpusd_change_pct > 0 else '-'}"

                if alert_key not in state["fired"]:
                    direction = "📈 SPIKE" if gbpusd_change_pct > 0 else "📉 DIP"
                    alerts_to_send.append(
                        f"{direction}: *GBP/USD*\n"
                        f"Current: {gbp_usd_current:.4f}\n"
                        f"Open: {gbp_usd_open:.4f}\n"
                        f"Change: {gbpusd_change_pct:+.2f}% (threshold: ±{gbpusd_threshold}%)"
                    )
                    state["fired"].append(alert_key)
                    logger.info(f"Alert triggered: {alert_key}")

        # Absolute price alerts for GBP/USD
        gbpusd_price_alerts = price_alerts.get("gbpusd", {})

        above = gbpusd_price_alerts.get("above")
        if above is not None and gbp_usd_current >= above:
            alert_key = "price_above_gbpusd"
            if alert_key not in state["fired"]:
                alerts_to_send.append(
                    f"🔔 *GBP/USD* above {above:.4f}!\n"
                    f"Current: {gbp_usd_current:.4f}"
                )
                state["fired"].append(alert_key)
                logger.info(f"Alert triggered: {alert_key}")

        below = gbpusd_price_alerts.get("below")
        if below is not None and gbp_usd_current <= below:
            alert_key = "price_below_gbpusd"
            if alert_key not in state["fired"]:
                alerts_to_send.append(
                    f"🔔 *GBP/USD* below {below:.4f}!\n"
                    f"Current: {gbp_usd_current:.4f}"
                )
                state["fired"].append(alert_key)
                logger.info(f"Alert triggered: {alert_key}")

    # Save state
    save_alerts_state(state)

    # Send alerts
    if alerts_to_send:
        now = datetime.now(LONDON_TZ).strftime("%H:%M")
        header = f"*Intraday Alert* ({now})\n\n"
        message = header + "\n\n".join(alerts_to_send)
        send_telegram_message(config, message, logger)
    else:
        logger.info("No new alerts to send")


def _alert_key_to_human(alert_key: str) -> tuple[str, str]:
    """Convert an alert key to (emoji, human-readable name).

    Examples:
        intraday_gold_gbp_+ → ("📈", "Gold spike")
        intraday_brent_-    → ("📉", "Brent Crude dip")
        price_above_gbpusd  → ("🔔", "GBP/USD above")
    """
    # Intraday alerts: intraday_{asset_key}_{+/-}
    if alert_key.startswith("intraday_"):
        rest = alert_key[len("intraday_"):]
        if rest.endswith("_+"):
            direction_word = "spike"
            emoji = "📈"
            asset_part = rest[:-2]
        elif rest.endswith("_-"):
            direction_word = "dip"
            emoji = "📉"
            asset_part = rest[:-2]
        else:
            return ("🔔", alert_key)

        if asset_part == "gbpusd":
            name = "GBP/USD"
        elif asset_part in ASSETS:
            name = ASSETS[asset_part]["name"]
        else:
            name = asset_part
        return (emoji, f"{name} {direction_word}")

    # Price alerts: price_above_{asset_key} / price_below_{asset_key}
    if alert_key.startswith("price_above_"):
        asset_part = alert_key[len("price_above_"):]
        word = "above"
    elif alert_key.startswith("price_below_"):
        asset_part = alert_key[len("price_below_"):]
        word = "below"
    else:
        return ("🔔", alert_key)

    if asset_part == "gbpusd":
        name = "GBP/USD"
    elif asset_part in ASSETS:
        name = ASSETS[asset_part]["name"]
    else:
        name = asset_part
    return ("🔔", f"{name} {word}")


def cmd_digest(config: dict, logger: logging.Logger) -> None:
    """Generate and send weekly digest summary."""
    logger.info("Generating weekly digest...")

    now = datetime.now(LONDON_TZ)
    # Calculate Monday-Friday of the current week
    monday = now - timedelta(days=now.weekday())
    friday = monday + timedelta(days=4)
    mon_str = monday.strftime("%Y-%m-%d")
    fri_str = friday.strftime("%Y-%m-%d")

    # Load history and filter to this week
    history = load_history()
    week_entries = [
        e for e in history.get("entries", [])
        if mon_str <= e["date"] <= fri_str
    ]
    week_entries.sort(key=lambda x: x["date"])

    lines = ["📊 *Weekly Digest*"]
    lines.append(f"_Week of {monday.strftime('%d %b')} - {friday.strftime('%d %b %Y')}_")
    lines.append("")

    if not week_entries:
        lines.append("No trading data available this week")
    else:
        for asset_key, asset_config in ASSETS.items():
            emoji = asset_config.get("emoji", "📊")
            name = asset_config["name"]

            # Collect days with data for this asset
            asset_days = [
                e for e in week_entries
                if asset_key in e.get("prices", {})
                and e["prices"][asset_key] is not None
            ]

            if len(asset_days) < 2:
                lines.append(f"{emoji} *{name}*")
                lines.append("  Insufficient data")
                lines.append("")
                continue

            week_open = asset_days[0]["prices"][asset_key]
            week_close = asset_days[-1]["prices"][asset_key]
            weekly_pct = ((week_close - week_open) / week_open) * 100 if week_open != 0 else 0
            week_indicator = "🟢" if weekly_pct >= 0 else "🔴"
            sign = "+" if weekly_pct >= 0 else ""

            # Best / worst day (day-over-day changes)
            best_day = None
            worst_day = None
            best_pct = float("-inf")
            worst_pct = float("inf")

            for i in range(1, len(asset_days)):
                prev_price = asset_days[i - 1]["prices"][asset_key]
                curr_price = asset_days[i]["prices"][asset_key]
                if prev_price == 0:
                    continue
                day_pct = ((curr_price - prev_price) / prev_price) * 100
                day_date = datetime.strptime(asset_days[i]["date"], "%Y-%m-%d")
                day_abbr = day_date.strftime("%a")

                if day_pct > best_pct:
                    best_pct = day_pct
                    best_day = day_abbr
                if day_pct < worst_pct:
                    worst_pct = day_pct
                    worst_day = day_abbr

            lines.append(f"{emoji} *{name}*")
            lines.append(
                f"  Open: {format_price_gbp(week_open)} → Close: {format_price_gbp(week_close)}"
            )
            lines.append(f"  Week: {week_indicator} {sign}{weekly_pct:.2f}%")

            if best_day and worst_day:
                lines.append(
                    f"  Best day: {best_day} ({'+' if best_pct >= 0 else ''}{best_pct:.1f}%)"
                    f" | Worst: {worst_day} ({'+' if worst_pct >= 0 else ''}{worst_pct:.1f}%)"
                )
            lines.append("")

    # --- Alerts summary from log file ---
    DAY_ABBRS = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
    alert_items: list[tuple[str, str, str]] = []  # (emoji, label, day_abbr)

    if LOG_PATH.exists():
        try:
            with open(LOG_PATH) as f:
                for line in f:
                    if "Alert triggered: " not in line:
                        continue
                    # Format: 2026-03-03 14:30:00,000 - INFO - Alert triggered: key
                    parts = line.strip().split(" - ", 2)
                    if len(parts) < 3:
                        continue
                    timestamp_str = parts[0].strip()
                    try:
                        log_date = datetime.strptime(
                            timestamp_str[:10], "%Y-%m-%d"
                        )
                    except ValueError:
                        continue
                    log_date_str = log_date.strftime("%Y-%m-%d")
                    if not (mon_str <= log_date_str <= fri_str):
                        continue
                    alert_key = parts[2].strip().removeprefix("Alert triggered: ").strip()
                    day_abbr = DAY_ABBRS.get(log_date.weekday(), "?")
                    emoji_a, label = _alert_key_to_human(alert_key)
                    alert_items.append((emoji_a, label, day_abbr))
        except OSError:
            pass

    lines.append(f"_Alerts fired this week: {len(alert_items)}_")
    for emoji_a, label, day_abbr in alert_items:
        lines.append(f"  {emoji_a} {label} ({day_abbr})")

    message = "\n".join(lines)
    logger.debug(f"Digest message:\n{message}")
    send_telegram_message(config, message, logger)


def cmd_test(config: dict, logger: logging.Logger) -> None:
    """Send a test message to verify Telegram configuration."""
    logger.info("Sending test message...")

    message = (
        "✅ *Daily Price Tracker - Test*\n\n"
        "Your Telegram integration is working correctly!\n\n"
        f"_Sent at {datetime.now(LONDON_TZ).strftime('%Y-%m-%d %H:%M:%S')} London time_"
    )

    if send_telegram_message(config, message, logger):
        print("Test message sent successfully!")
    else:
        print("Failed to send test message. Check logs for details.")
        sys.exit(1)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Daily Investment Price Tracker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("summary", help="Generate and send daily summary")
    subparsers.add_parser("watch", help="Check for intraday alerts")
    subparsers.add_parser("digest", help="Send weekly digest summary")
    subparsers.add_parser("test", help="Send a test Telegram message")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Setup
    logger = setup_logging(args.verbose)

    try:
        config = load_config()
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Ensure data directory exists
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Execute command
    commands = {
        "summary": cmd_summary,
        "watch": cmd_watch,
        "digest": cmd_digest,
        "test": cmd_test,
    }

    try:
        commands[args.command](config, logger)
    except Exception as e:
        logger.exception(f"Command '{args.command}' failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
