"""
Multi-agent system with orchestrator.
Each agent has a specific role and tools. The orchestrator decides which to invoke.
"""

import logging
import re
import json
from html import escape
from llm_processor import _call_llm
from prices import fetch_prices, fetch_single_token
from news_scraper import fetch_all_news
from watchlist import resolve_token, get_token_price
from memory import get_recent_messages, save_message, get_price_history

logger = logging.getLogger(__name__)


# ─── Individual Agents ─────────────────────────────────────────

def price_agent(query: str) -> str:
    """Handles any price-related query. Can look up any token."""
    # Try to extract token name from query
    token_words = re.findall(r'\b[a-zA-Z]{2,10}\b', query.lower())
    # Common words to ignore
    ignore = {"what", "how", "much", "the", "price", "of", "for", "is", "are",
              "show", "me", "get", "check", "tell", "current", "live", "today"}
    tokens = [w for w in token_words if w not in ignore]

    if tokens:
        result = fetch_single_token(tokens[0])
        # If first token doesn't match, try next
        if "Could not find" in result and len(tokens) > 1:
            result = fetch_single_token(tokens[1])
        return result

    return fetch_prices()


def news_agent(query: str) -> str:
    """Handles news-related queries. Can filter by topic."""
    from llm_processor import summarize_news

    lower = query.lower()
    news = fetch_all_news(lookback_hours=3)

    if any(w in lower for w in ["ai", "artificial", "tech", "openai", "nvidia", "model"]):
        digest = summarize_news(news["ai"], "AI")
        return f"🤖 <b>AI NEWS</b>\n━━━━━━━━━━━━━━━━━━━━━\n\n{digest}"
    elif any(w in lower for w in ["crypto", "bitcoin", "btc", "eth", "token", "blockchain", "defi"]):
        digest = summarize_news(news["crypto"], "Crypto")
        return f"₿ <b>CRYPTO NEWS</b>\n━━━━━━━━━━━━━━━━━━━━━\n\n{digest}"
    else:
        from llm_processor import build_digest
        return build_digest(news)


def research_agent(query: str) -> str:
    """
    Deep research agent. Multi-step: searches news, fetches prices,
    analyzes data, then synthesizes a comprehensive answer.
    """
    logger.info(f"Research agent activated: {query}")

    # Step 1: Gather news
    news = fetch_all_news(lookback_hours=6)
    all_articles = news["ai"] + news["crypto"]
    relevant = []
    query_words = set(query.lower().split())
    for a in all_articles:
        title_words = set(a["title"].lower().split())
        if query_words & title_words:
            relevant.append(a)

    # Step 2: Gather price data if crypto-related
    price_context = ""
    lower = query.lower()
    crypto_words = ["btc", "eth", "bitcoin", "ethereum", "solana", "crypto",
                    "token", "coin", "market", "defi", "nft"]
    if any(w in lower for w in crypto_words):
        price_context = fetch_prices()

        # Try to find specific token mentioned
        for w in lower.split():
            token = resolve_token(w)
            if token:
                data = get_token_price(token["id"])
                if data:
                    price_context += f"\n\n{token['symbol']}: ${data['price']:,.2f} ({data['change_24h']:+.2f}% 24h)"
                    history = get_price_history(token["id"], limit=24)
                    if history:
                        prices_list = [h["price"] for h in history]
                        price_context += f"\nRecent range: ${min(prices_list):,.2f} - ${max(prices_list):,.2f}"
                break

    # Step 3: Build research context
    news_context = ""
    if relevant:
        news_context = "\n\nRelevant articles found:\n"
        for a in relevant[:8]:
            news_context += f"- [{a['source']}] {a['title']}\n  {a['summary'][:100]}\n  URL: {a['url']}\n"

    # Step 4: Synthesize with LLM
    prompt = f"""You are a research analyst. The user asked: "{query}"

You have gathered the following data:

MARKET DATA:
{price_context or "No specific market data."}

NEWS:
{news_context or "No directly relevant articles found."}

Write a comprehensive research brief (200-300 words):
1. Answer the user's question directly
2. Reference specific data points and news
3. Include relevant article URLs as sources
4. End with a forward-looking assessment

Rules: No Markdown (* _ ` #). Plain text only. Be factual and specific."""

    try:
        return _call_llm(prompt, max_tokens=1500)
    except Exception as e:
        logger.error(f"Research agent error: {e}")
        return "Research failed. Please try again."


def sentiment_agent(query: str = "") -> str:
    """Analyze market sentiment based on recent news headlines."""
    news = fetch_all_news(lookback_hours=6)
    all_articles = news["ai"][:10] + news["crypto"][:10]

    if not all_articles:
        return "Not enough data to analyze sentiment right now."

    headlines = "\n".join(f"- {a['title']}" for a in all_articles)

    prompt = f"""Analyze the market sentiment from these recent news headlines.

Headlines:
{headlines}

Provide:
1. Overall AI sector sentiment (Bullish / Neutral / Bearish) with a 1-sentence reason
2. Overall crypto market sentiment (Bullish / Neutral / Bearish) with a 1-sentence reason
3. Top risk factor right now (1 sentence)
4. Top opportunity right now (1 sentence)

Keep it under 150 words. No Markdown. Plain text only."""

    try:
        analysis = _call_llm(prompt, max_tokens=600)
        return f"📊 <b>MARKET SENTIMENT ANALYSIS</b>\n━━━━━━━━━━━━━━━━━━━━━\n\n{analysis}"
    except Exception as e:
        logger.error(f"Sentiment agent error: {e}")
        return "Sentiment analysis failed."


# ─── Orchestrator ──────────────────────────────────────────────

AGENT_DESCRIPTIONS = """
Available agents:
1. PRICE — look up token prices, market data, portfolio
2. NEWS — fetch latest AI or crypto news
3. RESEARCH — deep multi-step research on any topic
4. SENTIMENT — analyze current market sentiment
5. CHAT — general conversation, explanations, opinions
"""


def orchestrate(user_message: str, chat_id: str) -> str:
    """
    The brain of the system. Decides which agent to invoke
    based on the user's message and conversation history.
    """
    lower = user_message.lower().strip()

    # ─── Fast routing (no LLM needed) ───────────────────────
    # Direct price queries
    price_triggers = ["price of", "price for", "how much is", "what is the price",
                      "what's the price", "check price"]
    if any(t in lower for t in price_triggers):
        return price_agent(user_message)

    # Direct news queries
    if lower in ["news", "latest news", "whats happening", "what's happening"]:
        return news_agent(user_message)

    # Sentiment
    if any(w in lower for w in ["sentiment", "mood", "fear", "greed", "bullish", "bearish"]):
        return sentiment_agent(user_message)

    # ─── LLM-based routing (complex queries) ────────────────
    history = get_recent_messages(chat_id, limit=4)
    history_text = ""
    if history:
        history_text = "Recent conversation:\n"
        for msg in history[-4:]:
            history_text += f"{msg['role'].upper()}: {msg['content'][:100]}\n"

    routing_prompt = f"""You are a routing agent. Given the user's message, decide which specialized agent should handle it.

{AGENT_DESCRIPTIONS}

{history_text}

User message: "{user_message}"

Reply with ONLY the agent name in caps: PRICE, NEWS, RESEARCH, SENTIMENT, or CHAT
Nothing else. Just the agent name."""

    try:
        agent = _call_llm(routing_prompt, max_tokens=20).strip().upper()
        # Clean up LLM response — just get the agent name
        for name in ["RESEARCH", "PRICE", "NEWS", "SENTIMENT", "CHAT"]:
            if name in agent:
                agent = name
                break
        else:
            agent = "CHAT"
    except Exception:
        agent = "CHAT"

    logger.info(f"Orchestrator routed to: {agent}")

    # Save conversation
    save_message(chat_id, "user", user_message)

    # Dispatch to agent
    if agent == "PRICE":
        result = price_agent(user_message)
    elif agent == "NEWS":
        result = news_agent(user_message)
    elif agent == "RESEARCH":
        result = research_agent(user_message)
    elif agent == "SENTIMENT":
        result = sentiment_agent(user_message)
    else:
        # CHAT — general LLM with context
        context = fetch_prices() if any(w in lower for w in ["crypto", "btc", "eth", "market", "coin"]) else ""
        prompt = (
            "You are Mineor, an AI and crypto analyst on Telegram. "
            "You have conversation memory and can reference past interactions. "
            "Answer concisely under 200 words. No Markdown symbols. Plain text only.\n"
        )
        if history:
            prompt += "\nConversation history:\n"
            for msg in history[-4:]:
                prompt += f"{msg['role']}: {msg['content'][:150]}\n"
        if context:
            prompt += f"\nLive market data:\n{context}\n"
        prompt += f"\nUser: {user_message}"

        try:
            result = _call_llm(prompt, max_tokens=1024)
        except Exception:
            result = "Sorry, couldn't process that. Try again."

    save_message(chat_id, "assistant", result[:500])
    return result


# ─── Autonomous Breaking News Analysis ────────────────────────

def analyze_breaking_news(article: dict) -> str:
    """
    When a breaking news story is detected, autonomously analyze its impact.
    Called by the breaking news detector in main.py.
    """
    prompt = f"""BREAKING NEWS detected. Analyze the impact:

Title: {article['title']}
Source: {article['source']}
Summary: {article['summary'][:300]}

Write a quick impact analysis (under 100 words):
1. What happened (1 sentence)
2. Why it matters (1-2 sentences)
3. Who is affected (tokens, companies, sectors)
4. Your 1-sentence outlook

No Markdown. Plain text. Be specific and actionable."""

    try:
        analysis = _call_llm(prompt, max_tokens=500)
    except Exception:
        analysis = article['summary'][:200]

    url = article.get('url', '')
    return (
        f"🚨 <b>BREAKING NEWS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📰 <b>{escape(article['title'])}</b>\n"
        f"📡 {escape(article['source'])}\n\n"
        f"{analysis}\n\n"
        f"🔗 <a href=\"{url}\">Full article</a>"
    )
