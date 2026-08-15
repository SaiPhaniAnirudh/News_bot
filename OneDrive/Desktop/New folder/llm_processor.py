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


def _call_llm(prompt: str, max_tokens: int = 2048) -> str:
    """Call NVIDIA LLM with streaming and return the content (skip reasoning)."""
    completion = client.chat.completions.create(
        model=NVIDIA_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        top_p=0.95,
        max_tokens=max_tokens,
        extra_body={
            "chat_template_kwargs": {"enable_thinking": True},
            "reasoning_budget": 4096,
        },
        stream=True,
    )

    result = []
    for chunk in completion:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content:
            result.append(delta.content)

    return "".join(result).strip()


def summarize_news(articles: list[dict], category: str) -> str:
    """Summarize articles into a Telegram-ready digest."""
    if not articles:
        return f"<i>No new {category} news in the last hour.</i>"

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
        return _call_llm(prompt, max_tokens=2048)
    except Exception as e:
        logger.error(f"LLM error for {category}: {e}")
        return _manual_digest(articles[:max_picks])


def ask_llm(question: str, context: str = "") -> str:
    """Answer a free-form user question using the NVIDIA LLM."""
    system_context = (
        "You are a knowledgeable AI and crypto analyst assistant on Telegram. "
        "Answer the user's question concisely and accurately. "
        "Do NOT use Markdown symbols (* _ ` # ~). Use plain text only. "
        "Keep answers under 300 words."
    )

    if context:
        system_context += f"\n\nHere is some live data for context:\n{context}"

    prompt = f"{system_context}\n\nUser question: {question}"

    try:
        return _call_llm(prompt, max_tokens=1024)
    except Exception as e:
        logger.error(f"LLM ask error: {e}")
        return "Sorry, I couldn't process your question right now. Try again later."


def _manual_digest(articles: list[dict]) -> str:
    """Simple fallback digest without LLM."""
    lines = []
    for a in articles:
        lines.append(
            f"📌 {a['title']}\n"
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
