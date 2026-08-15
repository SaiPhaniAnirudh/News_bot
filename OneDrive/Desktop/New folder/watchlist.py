"""
Portfolio watchlist + autonomous price alert engine.
Runs in background, detects big moves, sends alerts.
"""

import logging
import requests
from html import escape
from memory import (
    get_watchlist, add_to_watchlist, remove_from_watchlist,
    get_active_alerts, create_alert, trigger_alert,
    save_price_snapshot, get_price_history,
)
from prices import COINGECKO_URL, COINGECKO_SEARCH_URL, _fmt_price, _arrow

logger = logging.getLogger(__name__)


def resolve_token(query: str) -> dict | None:
    """Resolve a user query (symbol or name) to a CoinGecko token."""
    from prices import SYMBOL_TO_ID, TOKENS
    query = query.strip().lower()

    # Known symbol
    if query in SYMBOL_TO_ID:
        cg_id = SYMBOL_TO_ID[query]
        return {"id": cg_id, "symbol": query.upper()}

    # Known id
    if query in TOKENS:
        return {"id": query, "symbol": TOKENS[query]["symbol"]}

    # Search CoinGecko
    try:
        resp = requests.get(COINGECKO_SEARCH_URL, params={"query": query}, timeout=10)
        resp.raise_for_status()
        coins = resp.json().get("coins", [])
        if coins:
            return {"id": coins[0]["id"], "symbol": coins[0]["symbol"].upper()}
    except Exception as e:
        logger.warning(f"Token resolve failed: {e}")

    return None


def get_token_price(token_id: str) -> dict | None:
    """Fetch current price data for a single token."""
    try:
        resp = requests.get(
            COINGECKO_URL,
            params={
                "ids": token_id,
                "vs_currencies": "usd",
                "include_24hr_change": "true",
                "include_market_cap": "true",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get(token_id)
        if data:
            return {
                "price": data.get("usd", 0),
                "change_24h": data.get("usd_24h_change"),
                "market_cap": data.get("usd_market_cap", 0),
            }
    except Exception as e:
        logger.warning(f"Price fetch for {token_id} failed: {e}")
    return None


# ─── Watchlist Commands ────────────────────────────────────────

def cmd_watch(chat_id: str, query: str) -> str:
    """Add a token to watchlist."""
    token = resolve_token(query)
    if not token:
        return f"Could not find token '{escape(query)}'. Try the symbol (BTC) or full name (bitcoin)."

    price_data = get_token_price(token["id"])
    price = price_data["price"] if price_data else 0

    success = add_to_watchlist(chat_id, token["id"], token["symbol"], price)
    if success:
        return (
            f"✅ Added <b>{token['symbol']}</b> to your watchlist\n"
            f"   Entry price: {_fmt_price(price)}\n"
            f"   I'll alert you on big moves (>5% swing)"
        )
    return "Failed to add to watchlist. Try again."


def cmd_unwatch(chat_id: str, query: str) -> str:
    """Remove a token from watchlist."""
    token = resolve_token(query)
    if not token:
        return f"Could not find token '{escape(query)}'."

    if remove_from_watchlist(chat_id, token["id"]):
        return f"🗑 Removed <b>{token['symbol']}</b> from your watchlist."
    return f"{token['symbol']} is not in your watchlist."


def cmd_portfolio(chat_id: str) -> str:
    """Show current watchlist with live prices and P&L."""
    items = get_watchlist(chat_id)
    if not items:
        return (
            "📋 Your watchlist is empty.\n\n"
            "Add tokens with:\n"
            "/watch btc\n"
            "/watch solana\n"
            "/watch pepe"
        )

    # Fetch all prices in one call
    ids = ",".join(item["token_id"] for item in items)
    try:
        resp = requests.get(
            COINGECKO_URL,
            params={"ids": ids, "vs_currencies": "usd", "include_24hr_change": "true"},
            timeout=10,
        )
        resp.raise_for_status()
        prices = resp.json()
    except Exception:
        prices = {}

    lines = ["📋 <b>YOUR WATCHLIST</b>\n━━━━━━━━━━━━━━━━━━━━━"]
    for item in items:
        data = prices.get(item["token_id"], {})
        price = data.get("usd", 0)
        change = data.get("usd_24h_change")
        entry = item["added_price"] or 0

        change_str = f"{change:+.2f}%" if change is not None else "N/A"
        arrow = _arrow(change) if change is not None else "➡️"

        # P&L since added
        if entry > 0 and price > 0:
            pnl = ((price - entry) / entry) * 100
            pnl_str = f"  |  PnL: <code>{pnl:+.1f}%</code>"
        else:
            pnl_str = ""

        lines.append(
            f"{arrow} <b>{item['symbol']}</b>  {_fmt_price(price)}  "
            f"<code>{change_str} 24h</code>{pnl_str}"
        )

    return "\n".join(lines)


# ─── Autonomous Alert Engine ──────────────────────────────────

def check_watchlist_alerts(chat_id: str = None) -> list[dict]:
    """
    Check all watchlists for big moves. Returns list of alert messages.
    Called autonomously every 5 minutes.
    """
    from memory import get_watchlist
    import sqlite3

    conn = sqlite3.connect(str(__import__('memory').DB_PATH))
    conn.row_factory = sqlite3.Row

    # Get all watchlists across all users (or for one user)
    if chat_id:
        rows = conn.execute("SELECT DISTINCT chat_id FROM watchlist WHERE chat_id = ?", (str(chat_id),)).fetchall()
    else:
        rows = conn.execute("SELECT DISTINCT chat_id FROM watchlist").fetchall()
    conn.close()

    alerts_to_send = []

    for row in rows:
        cid = row["chat_id"]
        items = get_watchlist(cid)
        if not items:
            continue

        ids = ",".join(i["token_id"] for i in items)
        try:
            resp = requests.get(
                COINGECKO_URL,
                params={"ids": ids, "vs_currencies": "usd", "include_24hr_change": "true"},
                timeout=10,
            )
            resp.raise_for_status()
            prices = resp.json()
        except Exception:
            continue

        for item in items:
            data = prices.get(item["token_id"], {})
            price = data.get("usd")
            change = data.get("usd_24h_change")
            if price is None or change is None:
                continue

            # Save snapshot for history
            save_price_snapshot(item["token_id"], price, change)

            # Check for big moves (>5% in 24h)
            if abs(change) >= 5:
                direction = "surged" if change > 0 else "dropped"
                emoji = "🚀" if change > 0 else "🔻"

                # P&L since watchlist entry
                entry = item["added_price"] or 0
                pnl_line = ""
                if entry > 0:
                    pnl = ((price - entry) / entry) * 100
                    pnl_line = f"\n📊 Since you added: <code>{pnl:+.1f}%</code>"

                msg = (
                    f"{emoji} <b>ALERT: {item['symbol']} {direction} {abs(change):.1f}%</b>\n"
                    f"\n"
                    f"💵 Price: <b>{_fmt_price(price)}</b>\n"
                    f"📉 24h Change: <code>{change:+.2f}%</code>"
                    f"{pnl_line}"
                )
                alerts_to_send.append({"chat_id": cid, "message": msg})

    # Also check custom price alerts
    active_alerts = get_active_alerts()
    for alert in active_alerts:
        token_id = alert["token_id"]
        try:
            resp = requests.get(
                COINGECKO_URL,
                params={"ids": token_id, "vs_currencies": "usd"},
                timeout=10,
            )
            resp.raise_for_status()
            price = resp.json().get(token_id, {}).get("usd")
        except Exception:
            continue

        if price is None:
            continue

        triggered = False
        if alert["condition"] == "above" and price >= alert["threshold"]:
            triggered = True
        elif alert["condition"] == "below" and price <= alert["threshold"]:
            triggered = True

        if triggered:
            trigger_alert(alert["id"])
            msg = (
                f"🔔 <b>PRICE ALERT TRIGGERED</b>\n"
                f"\n"
                f"{token_id.upper()} hit <b>{_fmt_price(price)}</b>\n"
                f"Your alert: {alert['condition']} {_fmt_price(alert['threshold'])}"
            )
            alerts_to_send.append({"chat_id": alert["chat_id"], "message": msg})

    return alerts_to_send
