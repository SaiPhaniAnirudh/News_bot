import logging
from openai import OpenAI
from config import NVIDIA_API_KEY, NVIDIA_BASE_URL, NVIDIA_MODEL, MAX_ARTICLES_PER_CATEGORY

logger = logging.getLogger(__name__)

client = OpenAI(
    base_url=NVIDIA_BASE_URL,
    api_key=NVIDIA_API_KEY,
)


def _articles_to_text(articles: list[dict]) -> str:
    lines = []
    for i, a in enumerate(articles, 1):
        lines.append(
            f"{i}. [{a['source']}] {a['title']}\n"
            f"   Published: {a['published']}\n"
            f"   Summary: {a['summary']}\n"
            f"   URL: {a['url']}"
        )
    return "\n\n".join(lines)


def summarize_news(articles: list[dict], category: str) -> str:
    """
    Use NVIDIA Nemotron (with reasoning + streaming) to select the most
    important articles and produce a concise Telegram-ready digest.
    """
    if not articles:
        return f"_No new {category} news in the last hour._"

    articles_text = _articles_to_text(articles)
    max_picks = MAX_ARTICLES_PER_CATEGORY

    prompt = f"""You are a sharp {category} news editor writing for a Telegram channel.

From the articles below, pick the {max_picks} most important stories from the last hour.

For EACH story output EXACTLY this format (no deviations):
📌 [Title of the story]
↳ One or two crisp sentences explaining what happened and why it matters.
🔗 [URL]

After all stories, add one line:
💡 Trend: one sentence on the pattern you see across these stories.

Rules:
- Use the exact article title
- No Markdown symbols (* _ ` # ~) anywhere — plain text only
- No bullet points, numbers, or extra headers
- No filler phrases like "In a surprising move" or "According to reports"
- Factual, direct language

Articles:
{articles_text}

Output the digest now:"""

    try:
        completion = client.chat.completions.create(
            model=NVIDIA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=1,
            top_p=0.95,
            max_tokens=16384,
            extra_body={
                "chat_template_kwargs": {"enable_thinking": True},
                "reasoning_budget": 4096,  # keep reasoning fast for news digests
            },
            stream=True,
        )

        result = []
        reasoning_shown = False
        for chunk in completion:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            # Log reasoning tokens (model's thinking process) but don't include in output
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning and not reasoning_shown:
                logger.debug(f"[{category}] Model reasoning: {reasoning[:200]}...")
                reasoning_shown = True

            if delta.content:
                result.append(delta.content)

        return "".join(result).strip()

    except Exception as e:
        logger.error(f"LLM error for {category}: {e}")
        return _manual_digest(articles[:max_picks])


def _manual_digest(articles: list[dict]) -> str:
    """Simple fallback digest without LLM."""
    lines = []
    for a in articles:
        lines.append(
            f"📌 *{a['title']}*\n"
            f"↳ {a['summary'] or 'No summary available.'}\n"
            f"🔗 {a['url']}"
        )
    return "\n\n".join(lines)


def build_digest(news: dict[str, list[dict]]) -> str:
    """Build the full hourly digest message using HTML formatting."""
    from datetime import datetime, timezone
    from prices import fetch_prices

    now = datetime.now(timezone.utc).strftime("%d %b %Y · %H:%M UTC")

    prices_block = fetch_prices()
    ai_digest = summarize_news(news["ai"], "AI")
    crypto_digest = summarize_news(news["crypto"], "Crypto")

    message = (
        f"📡 <b>HOURLY DIGEST</b>\n"
        f"🗓 <i>{now}</i>\n"
        f"\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>LIVE CRYPTO PRICES</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{prices_block}\n"
        f"\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 <b>AI &amp; TECH NEWS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{ai_digest}\n"
        f"\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"₿ <b>CRYPTO NEWS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{crypto_digest}\n"
        f"\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>⚡ Powered by NVIDIA Nemotron · @Mineor_bot</i>"
    )
    return message
