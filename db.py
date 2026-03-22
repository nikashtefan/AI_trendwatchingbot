from __future__ import annotations

import sqlite3
import os

DB_PATH = os.environ.get("DB_PATH", "subscribers.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS subscribers (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            subscribed_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()
    conn.close()


def add_subscriber(user_id: int, username: str = "", first_name: str = ""):
    conn = get_connection()
    conn.execute(
        """
        INSERT OR IGNORE INTO subscribers (user_id, username, first_name)
        VALUES (?, ?, ?)
        """,
        (user_id, username, first_name),
    )
    conn.commit()
    conn.close()


def remove_subscriber(user_id: int):
    conn = get_connection()
    cur = conn.execute("DELETE FROM subscribers WHERE user_id = ?", (user_id,))
    conn.commit()
    deleted = cur.rowcount
    conn.close()
    return deleted > 0


def get_all_subscribers() -> list[int]:
    conn = get_connection()
    rows = conn.execute("SELECT user_id FROM subscribers").fetchall()
    conn.close()
    return [r[0] for r in rows]


def subscriber_count() -> int:
    conn = get_connection()
    count = conn.execute("SELECT COUNT(*) FROM subscribers").fetchone()[0]
    conn.close()
    return count
