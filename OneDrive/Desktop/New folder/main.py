#!/usr/bin/env python3
"""
Hourly AI & Crypto News Bot
Scrapes RSS feeds worldwide, summarizes with NVIDIA NIM, delivers via Telegram.
"""

import logging
import sys
import time
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import NEWS_INTERVAL_MINUTES, NVIDIA_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from news_scraper import fetch_all_news
from llm_processor import build_digest
from bot import send_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("news_bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


def validate_config() -> bool:
    missing = []
    if not NVIDIA_API_KEY:
        missing.append("NVIDIA_API_KEY")
    if not TELEGRAM_BOT_TOKEN or "your_bot" in TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID or "your_chat" in TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")

    if missing:
        logger.error(f"Missing or placeholder values in .env: {', '.join(missing)}")
        logger.error("Copy .env.example to .env and fill in the real values.")
        return False
    return True


def run_digest(lookback_hours: int = 1) -> None:
    """Fetch news, build digest, and send to Telegram."""
    logger.info("=== Starting news digest run ===")

    try:
        news = fetch_all_news(lookback_hours=lookback_hours)

        if not news["ai"] and not news["crypto"]:
            logger.warning("No new articles found in this period.")
            send_message("⚠️ No new AI or crypto articles found in the last hour.")
            return

        logger.info("Building LLM digest...")
        digest = build_digest(news)

        logger.info("Sending digest to Telegram...")
        success = send_message(digest)

        if success:
            logger.info("Digest sent successfully.")
        else:
            logger.error("Failed to send digest.")

    except Exception as e:
        logger.exception(f"Unexpected error during digest run: {e}")
        try:
            send_message(f"⚠️ News bot error: {e}")
        except Exception:
            pass


def main() -> None:
    if not validate_config():
        sys.exit(1)

    logger.info(f"News Bot starting — digest every {NEWS_INTERVAL_MINUTES} minute(s)")

    # Run immediately on startup
    logger.info("Running initial digest...")
    run_digest(lookback_hours=NEWS_INTERVAL_MINUTES / 60 + 1)

    # Schedule subsequent runs
    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        func=run_digest,
        trigger=IntervalTrigger(minutes=NEWS_INTERVAL_MINUTES),
        id="hourly_digest",
        name="Hourly News Digest",
        misfire_grace_time=300,
    )

    logger.info(f"Scheduler active. Next run in {NEWS_INTERVAL_MINUTES} minute(s). Press Ctrl+C to stop.")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
        scheduler.shutdown()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        # Manual one-shot run: python main.py once
        if not validate_config():
            sys.exit(1)
        hours = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
        run_digest(lookback_hours=hours)
    else:
        main()
