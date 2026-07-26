#!/usr/bin/env python3
"""
Telegram Subscription Listener

Long-polls the Telegram Bot API for /subscribe and /unsubscribe commands.
Manages subscriber list in data/subscribers.json.

Usage:
    python3 subscribe.py          # Run in foreground
    tmux new -d -s subscribe 'python3 subscribe.py'  # Run in tmux
"""

import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import pytz
import requests

# Project paths (same as tracker.py)
PROJECT_DIR = Path(__file__).parent.resolve()
CONFIG_PATH = PROJECT_DIR / "config.json"
DATA_DIR = PROJECT_DIR / "data"
LOGS_DIR = PROJECT_DIR / "logs"
SUBSCRIBERS_PATH = DATA_DIR / "subscribers.json"
LOG_PATH = LOGS_DIR / "subscribe.log"

LONDON_TZ = pytz.timezone("Europe/London")

# Long polling timeout (seconds)
POLL_TIMEOUT = 60

# Telegram bot tokens appear inside API URLs, and requests embeds the full URL
# in its exception messages — so an unredacted error log leaks the token.
TOKEN_IN_URL_RE = re.compile(r"/bot[0-9]+:[A-Za-z0-9_-]+")


def redact(text: object) -> str:
    """Strip any Telegram bot token out of text before it reaches the logs."""
    return TOKEN_IN_URL_RE.sub("/bot<redacted>", str(text))


def setup_logging() -> logging.Logger:
    """Configure logging to file and stdout."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("subscribe")
    logger.setLevel(logging.DEBUG)

    file_handler = logging.FileHandler(LOG_PATH)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
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


def load_subscribers(logger: logging.Logger | None = None) -> list[str]:
    """Load subscriber chat IDs from subscribers.json.

    A corrupt file must not kill the listener — losing the subscriber list is
    recoverable (people can re-subscribe), a crash loop is not.
    """
    if not SUBSCRIBERS_PATH.exists():
        return []

    try:
        with open(SUBSCRIBERS_PATH) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        if logger:
            logger.error(f"Could not read subscribers.json ({e}) — treating as empty")
        return []

    return data.get("subscribers", [])


def save_subscribers(chat_ids: list[str]) -> None:
    """Save subscriber chat IDs to subscribers.json.

    Written via temp file and rename so that tracker.py, which reads this file
    from a separate process, never observes a half-written list.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = SUBSCRIBERS_PATH.with_suffix(SUBSCRIBERS_PATH.suffix + ".tmp")

    with open(tmp_path, "w") as f:
        json.dump({"subscribers": chat_ids}, f, indent=2)
        f.flush()
        os.fsync(f.fileno())

    os.replace(tmp_path, SUBSCRIBERS_PATH)


def send_reply(token: str, chat_id: str, text: str, logger: logging.Logger) -> None:
    """Send a reply to a specific chat."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to send reply to {chat_id}: {redact(e)}")


def poll_updates(token: str, offset: int, logger: logging.Logger) -> tuple[list, int]:
    """Long-poll for new updates from Telegram."""
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    params = {
        "offset": offset,
        "timeout": POLL_TIMEOUT,
        "allowed_updates": '["message"]',
    }

    try:
        response = requests.get(url, params=params, timeout=POLL_TIMEOUT + 10)
        response.raise_for_status()
        data = response.json()

        if not data.get("ok"):
            logger.error(f"Telegram API error: {redact(data)}")
            return [], offset

        updates = data.get("result", [])
        if updates:
            offset = updates[-1]["update_id"] + 1

        return updates, offset

    except requests.RequestException as e:
        logger.error(f"Polling error: {redact(e)}")
        return [], offset


def handle_update(update: dict, token: str, logger: logging.Logger) -> None:
    """Process a single update from Telegram."""
    message = update.get("message")
    if not message:
        return

    text = message.get("text", "").strip()
    chat_id = str(message["chat"]["id"])
    user = message.get("from", {})
    username = user.get("username", "unknown")

    if text == "/subscribe":
        subscribers = load_subscribers(logger)

        if chat_id in subscribers:
            send_reply(token, chat_id, "You're already subscribed.", logger)
            logger.info(f"Already subscribed: {username} ({chat_id})")
            return

        subscribers.append(chat_id)
        save_subscribers(subscribers)

        now = datetime.now(LONDON_TZ).strftime("%H:%M %d %b %Y")
        send_reply(
            token, chat_id,
            f"*Subscribed!* You'll now receive daily price summaries "
            f"and intraday alerts.\n\n_Subscribed at {now}_",
            logger,
        )
        logger.info(f"New subscriber: {username} ({chat_id}) — total: {len(subscribers)}")

    elif text == "/unsubscribe":
        subscribers = load_subscribers(logger)

        if chat_id not in subscribers:
            send_reply(token, chat_id, "You're not currently subscribed.", logger)
            logger.info(f"Not subscribed: {username} ({chat_id})")
            return

        subscribers.remove(chat_id)
        save_subscribers(subscribers)

        send_reply(
            token, chat_id,
            "You've been unsubscribed. Send /subscribe to re-subscribe.",
            logger,
        )
        logger.info(f"Unsubscribed: {username} ({chat_id}) — total: {len(subscribers)}")


def main() -> None:
    """Main polling loop."""
    logger = setup_logging()

    try:
        config = load_config()
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)

    token = config["telegram_bot_token"]
    offset = 0

    logger.info("Subscription listener started — waiting for /subscribe commands...")

    while True:
        try:
            updates, offset = poll_updates(token, offset, logger)

            for update in updates:
                handle_update(update, token, logger)

        except KeyboardInterrupt:
            logger.info("Shutting down subscription listener")
            break
        except Exception as e:
            logger.exception(f"Unexpected error: {redact(e)}")
            time.sleep(5)


if __name__ == "__main__":
    main()
