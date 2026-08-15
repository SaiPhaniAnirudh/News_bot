"""
SQLite-based memory system for the autonomous agent.
Stores: conversations, watchlist, alerts, user preferences.
"""

import sqlite3
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "mineor_agent.db"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Create all tables if they don't exist."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            token_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            added_price REAL,
            added_at TEXT NOT NULL,
            UNIQUE(chat_id, token_id)
        );

        CREATE TABLE IF NOT EXISTS price_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_id TEXT NOT NULL,
            price REAL NOT NULL,
            change_24h REAL,
            timestamp TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            token_id TEXT,
            condition TEXT NOT NULL,
            threshold REAL,
            triggered INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            triggered_at TEXT
        );

        CREATE TABLE IF NOT EXISTS breaking_news_seen (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title_hash TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            sent_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS user_prefs (
            chat_id TEXT PRIMARY KEY,
            data TEXT NOT NULL DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_conv_chat ON conversations(chat_id);
        CREATE INDEX IF NOT EXISTS idx_watch_chat ON watchlist(chat_id);
        CREATE INDEX IF NOT EXISTS idx_snapshots_token ON price_snapshots(token_id, timestamp);
        CREATE INDEX IF NOT EXISTS idx_alerts_chat ON alerts(chat_id, triggered);
    """)
    conn.commit()
    conn.close()
    logger.info("Database initialized.")


# ─── Conversation Memory ──────────────────────────────────────

def save_message(chat_id: str, role: str, content: str) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT INTO conversations (chat_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        (str(chat_id), role, content, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def get_recent_messages(chat_id: str, limit: int = 10) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT role, content FROM conversations WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
        (str(chat_id), limit),
    ).fetchall()
    conn.close()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


# ─── Watchlist ─────────────────────────────────────────────────

def add_to_watchlist(chat_id: str, token_id: str, symbol: str, price: float) -> bool:
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO watchlist (chat_id, token_id, symbol, added_price, added_at) VALUES (?, ?, ?, ?, ?)",
            (str(chat_id), token_id, symbol.upper(), price, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Watchlist add error: {e}")
        return False
    finally:
        conn.close()


def remove_from_watchlist(chat_id: str, token_id: str) -> bool:
    conn = _get_conn()
    cursor = conn.execute(
        "DELETE FROM watchlist WHERE chat_id = ? AND token_id = ?",
        (str(chat_id), token_id),
    )
    conn.commit()
    removed = cursor.rowcount > 0
    conn.close()
    return removed


def get_watchlist(chat_id: str) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT token_id, symbol, added_price, added_at FROM watchlist WHERE chat_id = ? ORDER BY added_at",
        (str(chat_id),),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Price Snapshots ───────────────────────────────────────────

def save_price_snapshot(token_id: str, price: float, change_24h: float = None) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT INTO price_snapshots (token_id, price, change_24h, timestamp) VALUES (?, ?, ?, ?)",
        (token_id, price, change_24h, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def get_price_history(token_id: str, limit: int = 24) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT price, change_24h, timestamp FROM price_snapshots WHERE token_id = ? ORDER BY id DESC LIMIT ?",
        (token_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


# ─── Alerts ────────────────────────────────────────────────────

def create_alert(chat_id: str, alert_type: str, token_id: str, condition: str, threshold: float) -> int:
    conn = _get_conn()
    cursor = conn.execute(
        "INSERT INTO alerts (chat_id, alert_type, token_id, condition, threshold, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (str(chat_id), alert_type, token_id, condition, threshold, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    alert_id = cursor.lastrowid
    conn.close()
    return alert_id


def get_active_alerts(chat_id: str = None) -> list[dict]:
    conn = _get_conn()
    if chat_id:
        rows = conn.execute(
            "SELECT * FROM alerts WHERE chat_id = ? AND triggered = 0", (str(chat_id),)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM alerts WHERE triggered = 0").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def trigger_alert(alert_id: int) -> None:
    conn = _get_conn()
    conn.execute(
        "UPDATE alerts SET triggered = 1, triggered_at = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), alert_id),
    )
    conn.commit()
    conn.close()


def delete_alert(alert_id: int, chat_id: str) -> bool:
    conn = _get_conn()
    cursor = conn.execute(
        "DELETE FROM alerts WHERE id = ? AND chat_id = ?", (alert_id, str(chat_id))
    )
    conn.commit()
    removed = cursor.rowcount > 0
    conn.close()
    return removed


# ─── Breaking News Dedup ──────────────────────────────────────

def is_news_seen(title_hash: str) -> bool:
    conn = _get_conn()
    row = conn.execute("SELECT 1 FROM breaking_news_seen WHERE title_hash = ?", (title_hash,)).fetchone()
    conn.close()
    return row is not None


def mark_news_seen(title_hash: str, title: str) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO breaking_news_seen (title_hash, title, sent_at) VALUES (?, ?, ?)",
        (title_hash, title, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


# ─── User Preferences ─────────────────────────────────────────

def get_user_prefs(chat_id: str) -> dict:
    conn = _get_conn()
    row = conn.execute("SELECT data FROM user_prefs WHERE chat_id = ?", (str(chat_id),)).fetchone()
    conn.close()
    if row:
        return json.loads(row["data"])
    return {}


def set_user_prefs(chat_id: str, prefs: dict) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO user_prefs (chat_id, data) VALUES (?, ?)",
        (str(chat_id), json.dumps(prefs)),
    )
    conn.commit()
    conn.close()
