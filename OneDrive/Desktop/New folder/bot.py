import asyncio
import logging
import sys
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)


async def send_message_async(text: str) -> bool:
    """Send a message to the configured Telegram chat."""
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    chunks = _split_message(text, limit=4000)
    for chunk in chunks:
        try:
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=chunk,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except TelegramError as e:
            logger.error(f"Telegram send failed: {e}")
            return False
        if len(chunks) > 1:
            await asyncio.sleep(1)
    return True


def send_message(text: str) -> bool:
    """Synchronous wrapper around send_message_async."""
    return asyncio.run(send_message_async(text))


def _split_message(text: str, limit: int = 4000) -> list[str]:
    """Split long messages at newlines to stay under Telegram's limit."""
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


async def get_my_chat_id() -> None:
    """Helper: print recent chat IDs so you can find your TELEGRAM_CHAT_ID."""
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
