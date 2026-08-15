import logging
import re
from html import escape
from openai import OpenAI
from config import NVIDIA_API_KEY, NVIDIA_BASE_URL, NVIDIA_MODEL, MAX_ARTICLES_PER_CATEGORY

logger = logging.getLogger(__name__)

client = OpenAI(
    base_url=NVIDIA_BASE_URL,
    api_key=NVIDIA_API_KEY,
)


def _call_llm(prompt: str, max_tokens: int = 2048, use_thinking: bool = True) -> str:
    """Call NVIDIA LLM with streaming. Falls back to non-thinking mode if empty."""
    text = _call_llm_inner(prompt, max_tokens, use_thinking)

    # If thinking mode returned empty, retry without thinking
    if not text and use_thinking:
        logger.warning("LLM returned empty with thinking enabled, retrying without thinking...")
        text = _call_llm_inner(prompt, max_tokens, use_thinking=False)

    return text


def _call_llm_inner(prompt: str, max_tokens: int, use_thinking: bool) -> str:
    """Inner LLM call. Always enables thinking to separate reasoning from output."""
    reasoning_budget = 2048 if use_thinking else 128

    completion = client.chat.completions.create(
        model=NVIDIA_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        top_p=0.95,
        max_tokens=max_tokens,
        extra_body={
            "chat_template_kwargs": {"enable_thinking": True},
            "reasoning_budget": reasoning_budget,
        },
        stream=True,
    )

    result = []
    for chunk in completion:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta

        # Skip reasoning tokens
        reasoning = getattr(delta, "reasoning_content", None)
        if reasoning:
            continue

        if delta.content:
            result.append(delta.content)

    text = "".join(result).strip()

    # Strip leaked reasoning patterns
    junk_patterns = [
        r"(?i)here'?s a thinking process.*",
        r"(?i)\*\*analyze.*?\*\*:?",
        r"(?i)let me (?:think|analyze|process).*?:",
        r"(?i)thinking:.*",
        r"(?i)^\d+\.\s+\*\*.*?\*\*.*$",
    ]
    for pat in junk_patterns:
        text = re.sub(pat, "", text, flags=re.MULTILINE)

    return text.strip()


def _get_summaries(articles: list[dict], category: str) -> list[str]:
    """Ask the LLM to write ONE short summary per article."""
    if not articles:
        return []

    numbered = []
    for i, a in enumerate(articles, 1):
        snippet = a['summary'][:150].replace('\n', ' ')
        numbered.append(f"{i}. {a['title']} -- {snippet}")
    block = "\n".join(numbered)

    prompt = f"""Write a 1-sentence summary (max 20 words) for each {category} article below.

Format: one line per article, numbered.
1. summary
2. summary
...

No formatting. No filler words. Just facts.

{block}"""

    try:
        raw = _call_llm(prompt, max_tokens=800)
        lines = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            # Strip "1. " prefix
            cleaned = re.sub(r"^\d+[\.\)]\s*", "", line).strip()
            if cleaned and len(cleaned) > 5:
                lines.append(cleaned)
        return lines
    except Exception as e:
        logger.error(f"LLM summary error for {category}: {e}")
        return []


def summarize_news(articles: list[dict], category: str) -> str:
    """Build a clean, readable news section."""
    if not articles:
        return "<i>No fresh news this hour.</i>"

    top = articles[:MAX_ARTICLES_PER_CATEGORY]
    summaries = _get_summaries(top, category)

    blocks = []
    for i, a in enumerate(top):
        title = escape(a["title"])
        url = a["url"]

        if i < len(summaries) and summaries[i]:
            summary = escape(summaries[i])
        elif a["summary"] and a["summary"].lower() != a["title"].lower():
            first_sentence = a["summary"].split(". ")[0].strip()
            if len(first_sentence) > 20:
                summary = escape(first_sentence[:120])
            else:
                summary = "Tap link for full story."
        else:
            summary = "Tap link for full story."

        blocks.append(
            f"📌 <b>{title}</b>\n"
            f"      {summary}\n"
            f"      🔗 <a href=\"{url}\">Read more</a>"
        )

    return "\n\n".join(blocks)


def ask_llm(question: str, context: str = "") -> str:
    """Answer a free-form user question."""
    prompt = (
        "You are an AI and crypto analyst on Telegram. "
        "Answer concisely, under 200 words. No Markdown symbols. Plain text only.\n"
    )

    if context:
        prompt += f"\nLive market data:\n{context}\n"

    prompt += f"\nUser: {question}"

    try:
        result = _call_llm(prompt, max_tokens=1024, use_thinking=False)
        return result or "Sorry, couldn't generate a response. Try rephrasing."
    except Exception as e:
        logger.error(f"LLM ask error: {e}")
        return "Sorry, couldn't process your question. Try again."


def build_digest(news: dict[str, list[dict]]) -> str:
    """Build the full hourly digest."""
    from datetime import datetime, timezone
    from prices import fetch_prices

    now = datetime.now(timezone.utc).strftime("%d %b %Y · %H:%M UTC")

    prices_block = fetch_prices()
    ai_digest = summarize_news(news["ai"], "AI")
    crypto_digest = summarize_news(news["crypto"], "Crypto")

    return (
        f"📡 <b>HOURLY DIGEST</b>\n"
        f"🗓 <i>{now}</i>\n"
        f"\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>MARKET PRICES</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{prices_block}\n"
        f"\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 <b>AI NEWS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{ai_digest}\n"
        f"\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"₿ <b>CRYPTO NEWS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{crypto_digest}\n"
        f"\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>⚡ @Mineor_bot · NVIDIA Nemotron</i>"
    )
