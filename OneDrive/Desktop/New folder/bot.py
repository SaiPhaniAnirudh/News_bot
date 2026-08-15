"""
Telegram bot with full agent routing, watchlist commands, and autonomous alerts.
"""

import asyncio
import logging
import sys
from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import TelegramError
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)


# ─── Send helpers ──────────────────────────────────────────────

async def send_to_chat(bot: Bot, text: str, chat_id: str = None) -> bool:
    cid = chat_id or TELEGRAM_CHAT_ID
    chunks = _split_message(text, limit=4000)
    for chunk in chunks:
        try:
            await bot.send_message(
                chat_id=cid, text=chunk,
                parse_mode=ParseMode.HTML, disable_web_page_preview=True,
            )
        except TelegramError:
            try:
                await bot.send_message(
                    chat_id=cid, text=chunk, disable_web_page_preview=True,
                )
            except TelegramError as e:
                logger.error(f"Telegram send failed: {e}")
                return False
        if len(chunks) > 1:
            await asyncio.sleep(0.5)
    return True


async def reply(update: Update, text: str) -> None:
    chunks = _split_message(text, limit=4000)
    for chunk in chunks:
        try:
            await update.message.reply_text(
                text=chunk, parse_mode=ParseMode.HTML, disable_web_page_preview=True,
            )
        except TelegramError:
            await update.message.reply_text(text=chunk, disable_web_page_preview=True)
        if len(chunks) > 1:
            await asyncio.sleep(0.5)


# ─── Command Handlers ─────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await reply(update, (
        "🤖 <b>Welcome to Mineor — Your Autonomous AI Agent</b>\n"
        "\n"
        "I monitor AI &amp; crypto 24/7, alert you on big moves,\n"
        "and answer any question with live data.\n"
        "\n"
        "📰 <b>News</b>\n"
        "/news — Full AI + crypto digest\n"
        "/ai — AI news only\n"
        "/crypto — Crypto news only\n"
        "\n"
        "💰 <b>Prices</b>\n"
        "/price — Top 10 prices\n"
        "/price btc — Any token lookup\n"
        "\n"
        "📋 <b>Watchlist &amp; Alerts</b>\n"
        "/watch btc — Add token to watchlist\n"
        "/unwatch btc — Remove token\n"
        "/portfolio — View watchlist with P&amp;L\n"
        "/alert btc above 70000 — Set price alert\n"
        "/alerts — View active alerts\n"
        "\n"
        "🔍 <b>Agent Mode</b>\n"
        "/research [topic] — Deep research report\n"
        "/sentiment — Market sentiment analysis\n"
        "\n"
        "💬 Or just <b>type anything</b> — I'll figure out what you need!"
    ))


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


async def cmd_news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("⏳ Fetching latest news...")
    from llm_processor import build_digest
    from news_scraper import fetch_all_news
    news = fetch_all_news(lookback_hours=3)
    await reply(update, build_digest(news))


async def cmd_ai(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("⏳ Fetching AI news...")
    from agents import news_agent
    result = news_agent("ai news")
    await reply(update, result)


async def cmd_crypto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("⏳ Fetching crypto news...")
    from agents import news_agent
    result = news_agent("crypto news")
    await reply(update, result)


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from prices import fetch_prices, fetch_single_token
    if context.args:
        token = " ".join(context.args)
        await update.message.reply_text(f"⏳ Looking up {token}...")
        result = fetch_single_token(token)
    else:
        result = f"💰 <b>LIVE PRICES</b>\n━━━━━━━━━━━━━━━━━━━━━\n{fetch_prices()}"
    await reply(update, result)


# ─── Watchlist Commands ────────────────────────────────────────

async def cmd_watch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await reply(update, "Usage: /watch btc\n/watch solana\n/watch pepe")
        return
    from watchlist import cmd_watch
    result = cmd_watch(str(update.effective_chat.id), " ".join(context.args))
    await reply(update, result)


async def cmd_unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await reply(update, "Usage: /unwatch btc")
        return
    from watchlist import cmd_unwatch
    result = cmd_unwatch(str(update.effective_chat.id), " ".join(context.args))
    await reply(update, result)


async def cmd_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from watchlist import cmd_portfolio
    result = cmd_portfolio(str(update.effective_chat.id))
    await reply(update, result)


# ─── Alert Commands ────────────────────────────────────────────

async def cmd_alert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set a price alert. Usage: /alert btc above 70000"""
    args = context.args
    if not args or len(args) < 3:
        await reply(update, (
            "Usage: /alert [token] [above/below] [price]\n\n"
            "Examples:\n"
            "/alert btc above 70000\n"
            "/alert eth below 1500\n"
            "/alert sol above 100"
        ))
        return

    token_query = args[0]
    condition = args[1].lower()
    try:
        threshold = float(args[2].replace(",", ""))
    except ValueError:
        await reply(update, "Invalid price. Use a number like 70000 or 1500.50")
        return

    if condition not in ("above", "below"):
        await reply(update, "Condition must be 'above' or 'below'.")
        return

    from watchlist import resolve_token
    from memory import create_alert
    from prices import _fmt_price

    token = resolve_token(token_query)
    if not token:
        await reply(update, f"Could not find token '{token_query}'.")
        return

    alert_id = create_alert(
        str(update.effective_chat.id), "price", token["id"], condition, threshold
    )
    await reply(update, (
        f"🔔 Alert #{alert_id} set!\n"
        f"<b>{token['symbol']}</b> {condition} {_fmt_price(threshold)}\n"
        f"I'll notify you when it triggers."
    ))


async def cmd_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show all active alerts."""
    from memory import get_active_alerts
    from prices import _fmt_price

    alerts = get_active_alerts(str(update.effective_chat.id))
    if not alerts:
        await reply(update, "No active alerts. Set one with:\n/alert btc above 70000")
        return

    lines = ["🔔 <b>ACTIVE ALERTS</b>\n━━━━━━━━━━━━━━━━━━━━━"]
    for a in alerts:
        lines.append(
            f"#{a['id']} — <b>{a['token_id'].upper()}</b> "
            f"{a['condition']} {_fmt_price(a['threshold'])}"
        )
    lines.append("\nDelete with: /delalert [id]")
    await reply(update, "\n".join(lines))


async def cmd_delalert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await reply(update, "Usage: /delalert [alert_id]")
        return
    try:
        alert_id = int(context.args[0].replace("#", ""))
    except ValueError:
        await reply(update, "Invalid alert ID.")
        return
    from memory import delete_alert
    if delete_alert(alert_id, str(update.effective_chat.id)):
        await reply(update, f"🗑 Alert #{alert_id} deleted.")
    else:
        await reply(update, f"Alert #{alert_id} not found.")


# ─── Agent Commands ────────────────────────────────────────────

async def cmd_research(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await reply(update, (
            "Usage: /research [topic]\n\n"
            "Examples:\n"
            "/research Chainlink partnerships 2026\n"
            "/research Impact of EU AI Act on tech stocks\n"
            "/research Solana vs Ethereum transaction speed"
        ))
        return
    topic = " ".join(context.args)
    await update.message.reply_text(f"🔍 Researching: {topic}...")
    from agents import research_agent
    result = research_agent(topic)
    await reply(update, result)


async def cmd_sentiment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("📊 Analyzing market sentiment...")
    from agents import sentiment_agent
    result = sentiment_agent()
    await reply(update, result)


# ─── Free-form Message Handler (Orchestrator) ─────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    if not text:
        return

    await update.message.reply_text("🧠 Processing...")
    from agents import orchestrate
    result = orchestrate(text, str(update.effective_chat.id))
    await reply(update, result)


# ─── Utilities ──────────────────────────────────────────────────

def _split_message(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks = []
    current = []
    current_len = 0
    for line in text.splitlines(keepends=True):
        if current_len + len(line) > limit and current:
            chunks.append("".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line)
    if current:
        chunks.append("".join(current))
    return chunks


def build_application() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Basic
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))

    # News
    app.add_handler(CommandHandler("news", cmd_news))
    app.add_handler(CommandHandler("ai", cmd_ai))
    app.add_handler(CommandHandler("crypto", cmd_crypto))

    # Prices
    app.add_handler(CommandHandler("price", cmd_price))

    # Watchlist
    app.add_handler(CommandHandler("watch", cmd_watch))
    app.add_handler(CommandHandler("unwatch", cmd_unwatch))
    app.add_handler(CommandHandler("portfolio", cmd_portfolio))

    # Alerts
    app.add_handler(CommandHandler("alert", cmd_alert))
    app.add_handler(CommandHandler("alerts", cmd_alerts))
    app.add_handler(CommandHandler("delalert", cmd_delalert))

    # Agent
    app.add_handler(CommandHandler("research", cmd_research))
    app.add_handler(CommandHandler("sentiment", cmd_sentiment))

    # Catch-all: route through orchestrator
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app


# ─── CLI helper ─────────────────────────────────────────────────

async def get_my_chat_id() -> None:
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    updates = await bot.get_updates()
    if not updates:
        print("No updates found. Send any message to your bot first, then run this again.")
        return
    for update in updates:
        if update.message:
            print(f"Chat ID: {update.message.chat_id}  From: {update.message.from_user.username or update.message.from_user.first_name}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "get-chat-id":
        asyncio.run(get_my_chat_id())
    else:
        print("Usage: python bot.py get-chat-id")
