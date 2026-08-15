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


def parse_date(entry) -> datetime:
    """Parse published date from a feed entry."""
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            return datetime(*val[:6], tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def clean_html(raw: str) -> str:
    """Strip HTML tags and return plain text."""
    soup = BeautifulSoup(raw, "html.parser")
    return soup.get_text(separator=" ", strip=True)[:500]


def fetch_feed(feed: dict, since: datetime) -> list[dict]:
    """Fetch articles from a single RSS feed published after `since`."""
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


def fetch_all_news(lookback_hours: int = 1) -> dict[str, list[dict]]:
    """
    Fetch AI and crypto news from all configured feeds.
    Returns a dict with 'ai' and 'crypto' keys containing article lists.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    results = {"ai": [], "crypto": []}

    logger.info("Fetching AI news...")
    for feed in AI_FEEDS:
        articles = fetch_feed(feed, since)
        results["ai"].extend(articles)
        if articles:
            logger.info(f"  {feed['name']}: {len(articles)} article(s)")

    logger.info("Fetching crypto news...")
    for feed in CRYPTO_FEEDS:
        articles = fetch_feed(feed, since)
        results["crypto"].extend(articles)
        if articles:
            logger.info(f"  {feed['name']}: {len(articles)} article(s)")

    # Sort by published date descending and cap per category
    for key in results:
        results[key].sort(key=lambda a: a["published"], reverse=True)
        results[key] = results[key][:MAX_ARTICLES_PER_CATEGORY * 2]

    logger.info(
        f"Total: {len(results['ai'])} AI articles, "
        f"{len(results['crypto'])} crypto articles"
    )
    return results
