#!/usr/bin/env python3
"""
Mineor News Bot — Hourly AI & Crypto digests + interactive Q&A
Powered by NVIDIA Nemotron via NIM API
"""

import logging
import sys

from config import NEWS_INTERVAL_MINUTES, NVIDIA_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from bot import build_application, send_message_to_chat

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def validate_config() -> bool:
    missing = []
    if not NVIDIA_API_KEY:
        missing.append("NVIDIA_API_KEY")
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")
    if missing:
        logger.error(f"Missing config: {', '.join(missing)}")
        return False
    return True


async def scheduled_digest(context) -> None:
    """Scheduled job: fetch news, build digest, send to chat."""
    logger.info("=== Scheduled digest run ===")
    try:
        from news_scraper import fetch_all_news
        from llm_processor import build_digest

        news = fetch_all_news(lookback_hours=2)

        if not news["ai"] and not news["crypto"]:
            logger.warning("No new articles found.")
            return

        logger.info("Building LLM digest...")
        digest = build_digest(news)

        logger.info("Sending digest to Telegram...")
        await send_message_to_chat(context.bot, digest)
        logger.info("Digest sent successfully.")

    except Exception as e:
        logger.exception(f"Digest error: {e}")
        try:
            await send_message_to_chat(context.bot, f"⚠️ News bot error: {e}")
        except Exception:
            pass


def main() -> None:
    if not validate_config():
        sys.exit(1)

    logger.info("🚀 Mineor News Bot starting...")
    logger.info(f"  Digest interval: {NEWS_INTERVAL_MINUTES} min")
    logger.info("  Interactive mode: ON")

    app = build_application()

    # Schedule the hourly digest using python-telegram-bot's built-in job queue
    job_queue = app.job_queue
    job_queue.run_repeating(
        scheduled_digest,
        interval=NEWS_INTERVAL_MINUTES * 60,
        first=10,  # first run 10 seconds after startup
        name="hourly_digest",
    )

    logger.info("Bot is live! Listening for messages + sending hourly digests.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
