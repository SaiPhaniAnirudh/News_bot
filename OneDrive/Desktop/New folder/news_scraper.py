import feedparser
import requests
import logging
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from config import AI_FEEDS, CRYPTO_FEEDS, MAX_ARTICLES_PER_CATEGORY

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# Keywords to filter relevant articles per category
AI_KEYWORDS = {
    "ai", "artificial intelligence", "machine learning", "deep learning",
    "neural", "gpt", "llm", "openai", "google ai", "nvidia", "chip",
    "semiconductor", "gpu", "model", "chatbot", "copilot", "gemini",
    "claude", "anthropic", "meta ai", "robot", "autonomous", "training",
}

CRYPTO_KEYWORDS = {
    "bitcoin", "btc", "ethereum", "eth", "crypto", "blockchain", "token",
    "defi", "nft", "web3", "solana", "binance", "coinbase", "stablecoin",
    "mining", "wallet", "exchange", "altcoin", "doge", "xrp", "cardano",
    "polygon", "layer 2", "l2", "dao", "airdrop", "halving", "sec",
}


def _deduplicate(articles: list[dict]) -> list[dict]:
    """Remove near-duplicate articles (same headline from different outlets)."""
    seen = []
    unique = []
    for a in articles:
        # Normalize title: lowercase, strip source suffix after " - "
        title = a["title"].lower().split(" - ")[0].strip()
        # Check if we already have a similar title
        is_dup = False
        for s in seen:
            # Simple overlap check: if >60% of words match, it's a duplicate
            words_a = set(title.split())
            words_b = set(s.split())
            if not words_a or not words_b:
                continue
            overlap = len(words_a & words_b) / min(len(words_a), len(words_b))
            if overlap > 0.6:
                is_dup = True
                break
        if not is_dup:
            seen.append(title)
            unique.append(a)
    return unique


def _is_relevant(article: dict, keywords: set) -> bool:
    """Check if article title contains any relevant keyword."""
    # Only check title — summaries often contain unrelated boilerplate
    text = article["title"].lower()
    return any(kw in text for kw in keywords)


def parse_date(entry) -> datetime:
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            return datetime(*val[:6], tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def clean_html(raw: str) -> str:
    soup = BeautifulSoup(raw, "html.parser")
    return soup.get_text(separator=" ", strip=True)[:500]


def fetch_feed(feed: dict, since: datetime) -> list[dict]:
    articles = []
    try:
        resp = requests.get(feed["url"], headers=HEADERS, timeout=10)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)

        for entry in parsed.entries:
            pub_date = parse_date(entry)
            if pub_date < since:
                continue

            summary = ""
            if hasattr(entry, "summary"):
                summary = clean_html(entry.summary)
            elif hasattr(entry, "content"):
                summary = clean_html(entry.content[0].value)

            articles.append({
                "source": feed["name"],
                "title": entry.get("title", "No title").strip(),
                "url": entry.get("link", ""),
                "summary": summary,
                "published": pub_date.strftime("%Y-%m-%d %H:%M UTC"),
            })

    except Exception as e:
        logger.warning(f"Failed to fetch {feed['name']}: {e}")

    return articles


def fetch_all_news(lookback_hours: int = 2) -> dict[str, list[dict]]:
    since = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    results = {"ai": [], "crypto": []}

    logger.info("Fetching AI news...")
    for feed in AI_FEEDS:
        articles = fetch_feed(feed, since)
        # Filter to only AI-relevant articles
        relevant = [a for a in articles if _is_relevant(a, AI_KEYWORDS)]
        results["ai"].extend(relevant)
        if relevant:
            logger.info(f"  {feed['name']}: {len(relevant)} article(s)")

    logger.info("Fetching crypto news...")
    for feed in CRYPTO_FEEDS:
        articles = fetch_feed(feed, since)
        # Filter to only crypto-relevant articles
        relevant = [a for a in articles if _is_relevant(a, CRYPTO_KEYWORDS)]
        results["crypto"].extend(relevant)
        if relevant:
            logger.info(f"  {feed['name']}: {len(relevant)} article(s)")

    # Deduplicate by title similarity and sort
    for key in results:
        results[key] = _deduplicate(results[key])
        results[key].sort(key=lambda a: a["published"], reverse=True)
        results[key] = results[key][:MAX_ARTICLES_PER_CATEGORY * 2]

    logger.info(
        f"Total: {len(results['ai'])} AI, "
        f"{len(results['crypto'])} crypto articles"
    )
    return results
