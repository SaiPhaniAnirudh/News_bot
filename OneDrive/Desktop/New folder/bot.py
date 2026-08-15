import asyncio
import logging
import sys
from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import TelegramError
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)


# ─── Send helper (used by scheduler) ───────────────────────────

async def send_message_to_chat(bot: Bot, text: str) -> bool:
    """Send a message to the configured chat. Used by the scheduler."""
    chunks = _split_message(text, limit=4000)
    for chunk in chunks:
        try:
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=chunk,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except TelegramError:
            # Retry without HTML if parsing fails
            try:
                await bot.send_message(
                    chat_id=TELEGRAM_CHAT_ID,
                    text=chunk,
                    disable_web_page_preview=True,
                )
            except TelegramError as e:
                logger.error(f"Telegram send failed: {e}")
                return False
        if len(chunks) > 1:
            await asyncio.sleep(1)
    return True


# ─── Reply helper (used by handlers) ───────────────────────────

async def reply(update: Update, text: str) -> None:
    """Reply to a user message with HTML. Falls back to plain text."""
    chunks = _split_message(text, limit=4000)
    for chunk in chunks:
        try:
            await update.message.reply_text(
                text=chunk,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except TelegramError:
            await update.message.reply_text(
                text=chunk,
                disable_web_page_preview=True,
            )
        if len(chunks) > 1:
            await asyncio.sleep(0.5)


# ─── Command handlers ──────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await reply(update, (
        "👋 <b>Welcome to Mineor News Bot!</b>\n"
        "\n"
        "I deliver hourly AI &amp; crypto digests and answer your questions.\n"
        "\n"
        "<b>Commands:</b>\n"
        "/news — Get latest AI &amp; crypto digest now\n"
        "/ai — Get AI news only\n"
        "/crypto — Get crypto news only\n"
        "/price — Top 10 token prices\n"
        "/price btc — Price of a specific token\n"
        "/ask [question] — Ask me anything about AI or crypto\n"
        "/help — Show this message\n"
        "\n"
        "Or just <b>type any question</b> and I'll answer it!"
    ))


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


async def cmd_news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a full digest right now."""
    await update.message.reply_text("⏳ Fetching latest news...")
    from news_scraper import fetch_all_news
    from llm_processor import build_digest
    news = fetch_all_news(lookback_hours=2)
    digest = build_digest(news)
    await reply(update, digest)


async def cmd_ai(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send AI news only."""
    await update.message.reply_text("⏳ Fetching AI news...")
    from news_scraper import fetch_all_news
    from llm_processor import summarize_news
    from prices import fetch_prices
    news = fetch_all_news(lookback_hours=2)
    ai_digest = summarize_news(news["ai"], "AI")
    msg = (
        f"🤖 <b>AI &amp; TECH NEWS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{ai_digest}"
    )
    await reply(update, msg)


async def cmd_crypto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send crypto news only."""
    await update.message.reply_text("⏳ Fetching crypto news...")
    from news_scraper import fetch_all_news
    from llm_processor import summarize_news
    news = fetch_all_news(lookback_hours=2)
    crypto_digest = summarize_news(news["crypto"], "Crypto")
    msg = (
        f"₿ <b>CRYPTO NEWS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{crypto_digest}"
    )
    await reply(update, msg)


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show prices. /price for top 10, /price btc for specific token."""
    from prices import fetch_prices, fetch_single_token
    args = context.args
    if args:
        token_query = " ".join(args)
        await update.message.reply_text(f"⏳ Looking up {token_query}...")
        result = fetch_single_token(token_query)
    else:
        result = (
            f"💰 <b>LIVE CRYPTO PRICES</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"{fetch_prices()}"
        )
    await reply(update, result)


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Answer a free-form question using the LLM."""
    if not context.args:
        await reply(update, "Usage: /ask [your question]\n\nExample: /ask What is the latest on GPT-5?")
        return
    question = " ".join(context.args)
    await update.message.reply_text("🤔 Thinking...")
    from llm_processor import ask_llm
    answer = ask_llm(question)
    await reply(update, answer)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle any plain text message as a question to the LLM."""
    text = update.message.text.strip()
    if not text:
        return

    # Detect if user is asking about a token price
    lower = text.lower()
    price_keywords = ["price of", "price for", "how much is", "what is the price"]
    is_price_query = any(kw in lower for kw in price_keywords)

    if is_price_query:
        from prices import fetch_single_token
        # Extract token name from the query
        for kw in price_keywords:
            if kw in lower:
                token = lower.split(kw)[-1].strip().rstrip("?").strip()
                break
        await update.message.reply_text(f"⏳ Looking up {token}...")
        result = fetch_single_token(token)
        await reply(update, result)
        return

    # Otherwise, use LLM to answer
    await update.message.reply_text("🤔 Thinking...")
    from llm_processor import ask_llm
    from prices import fetch_prices

    # Give LLM live price context if user asks about crypto
    context_data = ""
    crypto_words = ["btc", "eth", "bitcoin", "ethereum", "solana", "crypto", "token", "coin", "market"]
    if any(w in lower for w in crypto_words):
        context_data = fetch_prices()

    answer = ask_llm(text, context=context_data)
    await reply(update, answer)


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
    """Build and return the Telegram bot application with all handlers."""
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("news", cmd_news))
    app.add_handler(CommandHandler("ai", cmd_ai))
    app.add_handler(CommandHandler("crypto", cmd_crypto))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CommandHandler("ask", cmd_ask))
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
            print(
                f"Chat ID: {update.message.chat_id}  "
                f"From: {update.message.from_user.username or update.message.from_user.first_name}"
            )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "get-chat-id":
        asyncio.run(get_my_chat_id())
    else:
        print("Usage: python bot.py get-chat-id")
