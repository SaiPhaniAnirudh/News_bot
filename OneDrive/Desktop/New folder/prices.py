import requests
import logging

logger = logging.getLogger(__name__)

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"

TOKENS = {
    "bitcoin":       {"symbol": "BTC",  "emoji": "₿"},
    "ethereum":      {"symbol": "ETH",  "emoji": "Ξ"},
    "solana":        {"symbol": "SOL",  "emoji": "◎"},
    "binancecoin":   {"symbol": "BNB",  "emoji": "🔶"},
    "ripple":        {"symbol": "XRP",  "emoji": "✕"},
    "dogecoin":      {"symbol": "DOGE", "emoji": "🐕"},
    "cardano":       {"symbol": "ADA",  "emoji": "₳"},
    "avalanche-2":   {"symbol": "AVAX", "emoji": "🔺"},
    "chainlink":     {"symbol": "LINK", "emoji": "🔗"},
    "sui":           {"symbol": "SUI",  "emoji": "💧"},
}


def _arrow(change: float) -> str:
    if change >= 2:
        return "🚀"
    elif change >= 0.5:
        return "📈"
    elif change <= -2:
        return "🔻"
    elif change <= -0.5:
        return "📉"
    return "➡️"


def _fmt_price(price: float) -> str:
    if price >= 1000:
        return f"${price:,.0f}"
    elif price >= 1:
        return f"${price:,.2f}"
    else:
        return f"${price:.4f}"


def fetch_prices() -> str:
    """Fetch live prices from CoinGecko and return an HTML-formatted Telegram block."""
    ids = ",".join(TOKENS.keys())
    try:
        resp = requests.get(
            COINGECKO_URL,
            params={
                "ids": ids,
                "vs_currencies": "usd",
                "include_24hr_change": "true",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"Price fetch failed: {e}")
        return "<i>Price data unavailable</i>"

    lines = []
    for coin_id, meta in TOKENS.items():
        info = data.get(coin_id, {})
        price = info.get("usd")
        change = info.get("usd_24h_change")
        if price is None:
            continue
        change_str = f"{change:+.2f}%" if change is not None else "N/A"
        arrow = _arrow(change) if change is not None else "➡️"
        lines.append(
            f"{arrow} <b>{meta['symbol']}</b>  {_fmt_price(price)}  <code>{change_str} 24h</code>"
        )

    return "\n".join(lines) if lines else "<i>Price data unavailable</i>"
