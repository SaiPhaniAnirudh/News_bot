import requests
import logging

logger = logging.getLogger(__name__)

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
COINGECKO_SEARCH_URL = "https://api.coingecko.com/api/v3/search"

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

# Reverse lookup: symbol -> coingecko id
SYMBOL_TO_ID = {}
for cg_id, meta in TOKENS.items():
    SYMBOL_TO_ID[meta["symbol"].lower()] = cg_id


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
        return f"${price:.6f}"


def fetch_prices() -> str:
    """Fetch live prices for top tokens and return an HTML-formatted Telegram block."""
    ids = ",".join(TOKENS.keys())
    try:
        resp = requests.get(
            COINGECKO_URL,
            params={
                "ids": ids,
                "vs_currencies": "usd",
                "include_24hr_change": "true",
                "include_market_cap": "true",
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


def fetch_single_token(query: str) -> str:
    """Fetch detailed price info for a single token by name or symbol."""
    query = query.strip().lower()

    # Check if it's a known symbol
    coin_id = SYMBOL_TO_ID.get(query)

    # Check if it's a known coingecko id
    if not coin_id and query in TOKENS:
        coin_id = query

    # Search CoinGecko for unknown tokens
    if not coin_id:
        try:
            resp = requests.get(
                COINGECKO_SEARCH_URL,
                params={"query": query},
                timeout=10,
            )
            resp.raise_for_status()
            coins = resp.json().get("coins", [])
            if coins:
                coin_id = coins[0]["id"]
            else:
                return f"Could not find a token matching '{query}'."
        except Exception as e:
            logger.warning(f"Token search failed: {e}")
            return "Token search failed. Try again later."

    try:
        resp = requests.get(
            COINGECKO_URL,
            params={
                "ids": coin_id,
                "vs_currencies": "usd",
                "include_24hr_change": "true",
                "include_market_cap": "true",
                "include_24hr_vol": "true",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get(coin_id, {})
    except Exception as e:
        logger.warning(f"Price fetch for {coin_id} failed: {e}")
        return "Price fetch failed. Try again later."

    if not data:
        return f"No price data for '{query}'."

    price = data.get("usd", 0)
    change = data.get("usd_24h_change")
    mcap = data.get("usd_market_cap", 0)
    vol = data.get("usd_24h_vol", 0)

    change_str = f"{change:+.2f}%" if change is not None else "N/A"
    arrow = _arrow(change) if change is not None else "➡️"

    def fmt_large(n):
        if n >= 1_000_000_000:
            return f"${n / 1_000_000_000:.2f}B"
        elif n >= 1_000_000:
            return f"${n / 1_000_000:.2f}M"
        elif n >= 1_000:
            return f"${n / 1_000:.2f}K"
        return f"${n:,.2f}"

    return (
        f"{arrow} <b>{coin_id.upper()}</b>\n"
        f"\n"
        f"💵 Price: <b>{_fmt_price(price)}</b>\n"
        f"📊 24h Change: <code>{change_str}</code>\n"
        f"📈 Market Cap: {fmt_large(mcap)}\n"
        f"🔄 24h Volume: {fmt_large(vol)}"
    )
