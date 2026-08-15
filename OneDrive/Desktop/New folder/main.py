#!/usr/bin/env python3
"""
Mineor — Autonomous AI & Crypto Agent
Runs 4 background loops:
  1. Hourly news digest
  2. Price alert checker (every 5 min)
  3. Breaking news scanner (every 10 min)
  4. Watchlist snapshot (every 15 min)
"""

import hashlib
import logging
import sys

from config import NEWS_INTERVAL_MINUTES, NVIDIA_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from bot import build_application, send_to_chat
from memory import init_db

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


# ─── Job 1: Hourly News Digest ────────────────────────────────

async def job_hourly_digest(context) -> None:
    logger.info("=== [JOB] Hourly digest ===")
    try:
        from news_scraper import fetch_all_news
        from llm_processor import build_digest

        news = fetch_all_news(lookback_hours=2)
        if not news["ai"] and not news["crypto"]:
            logger.warning("No articles found.")
            return

        digest = build_digest(news)
        await send_to_chat(context.bot, digest)
        logger.info("Digest sent.")
    except Exception as e:
        logger.exception(f"Digest error: {e}")


# ─── Job 2: Price Alert Checker (every 5 min) ─────────────────

async def job_check_alerts(context) -> None:
    logger.info("[JOB] Checking price alerts...")
    try:
        from watchlist import check_watchlist_alerts

        alerts = check_watchlist_alerts()
        for alert in alerts:
            await send_to_chat(context.bot, alert["message"], chat_id=alert["chat_id"])
            logger.info(f"Alert sent to {alert['chat_id']}")
    except Exception as e:
        logger.error(f"Alert check error: {e}")


# ─── Job 3: Breaking News Scanner (every 10 min) ──────────────

async def job_breaking_news(context) -> None:
    logger.info("[JOB] Scanning for breaking news...")
    try:
        from news_scraper import fetch_all_news
        from memory import is_news_seen, mark_news_seen
        from agents import analyze_breaking_news

        news = fetch_all_news(lookback_hours=1)
        all_articles = news["ai"] + news["crypto"]

        # Breaking news criteria: keywords that signal major events
        breaking_keywords = [
            "breaking", "just in", "urgent", "officially", "approved",
            "banned", "hacked", "crash", "surge", "record", "all-time",
            "sec approves", "sec rejects", "launches", "acquires",
            "partnership", "billion", "trillion",
        ]

        for article in all_articles:
            title_lower = article["title"].lower()

            # Check if it matches breaking criteria
            is_breaking = any(kw in title_lower for kw in breaking_keywords)
            if not is_breaking:
                continue

            # Check if we've already sent this story
            title_hash = hashlib.md5(article["title"].encode()).hexdigest()
            if is_news_seen(title_hash):
                continue

            # It's new and breaking — analyze and send
            logger.info(f"BREAKING: {article['title']}")
            mark_news_seen(title_hash, article["title"])

            analysis = analyze_breaking_news(article)
            await send_to_chat(context.bot, analysis)
            logger.info("Breaking news alert sent.")

    except Exception as e:
        logger.error(f"Breaking news scan error: {e}")


# ─── Job 4: Watchlist Price Snapshots (every 15 min) ──────────

async def job_save_snapshots(context) -> None:
    """Save price snapshots for all watched tokens. Powers historical analysis."""
    try:
        import requests
        import sqlite3
        from memory import DB_PATH, save_price_snapshot
        from prices import COINGECKO_URL

        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT DISTINCT token_id FROM watchlist").fetchall()
        conn.close()

        if not rows:
            return

        ids = ",".join(r["token_id"] for r in rows)
        resp = requests.get(
            COINGECKO_URL,
            params={"ids": ids, "vs_currencies": "usd", "include_24hr_change": "true"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        for r in rows:
            info = data.get(r["token_id"], {})
            if info.get("usd"):
                save_price_snapshot(r["token_id"], info["usd"], info.get("usd_24h_change"))

    except Exception as e:
        logger.error(f"Snapshot error: {e}")


# ─── Main ──────────────────────────────────────────────────────

def main() -> None:
    if not validate_config():
        sys.exit(1)

    # Initialize database
    init_db()

    logger.info("🤖 Mineor Autonomous Agent starting...")
    logger.info(f"  📰 Digest every {NEWS_INTERVAL_MINUTES} min")
    logger.info("  🔔 Alert check every 5 min")
    logger.info("  🚨 Breaking news scan every 10 min")
    logger.info("  📊 Price snapshots every 15 min")
    logger.info("  💬 Interactive mode: ON")
    logger.info("  🧠 Agent orchestrator: ON")

    app = build_application()
    jq = app.job_queue

    # Job 1: Hourly digest
    jq.run_repeating(job_hourly_digest, interval=NEWS_INTERVAL_MINUTES * 60, first=10, name="hourly_digest")

    # Job 2: Price alerts every 5 minutes
    jq.run_repeating(job_check_alerts, interval=300, first=60, name="alert_checker")

    # Job 3: Breaking news every 10 minutes
    jq.run_repeating(job_breaking_news, interval=600, first=30, name="breaking_news")

    # Job 4: Snapshots every 15 minutes
    jq.run_repeating(job_save_snapshots, interval=900, first=120, name="snapshots")

    logger.info("All systems online. Listening for messages...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
