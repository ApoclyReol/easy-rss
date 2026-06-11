from __future__ import annotations

import sqlite3
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
BASE_DIR = APP_DIR.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "rss_reader.sqlite3"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS feeds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_checked_at TEXT,
                last_error TEXT
            );

            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stable_guid TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                title_norm TEXT NOT NULL,
                authors TEXT,
                journal TEXT,
                year TEXT,
                doi TEXT,
                link TEXT,
                pub_date TEXT,
                summary TEXT,
                first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                item_status TEXT NOT NULL DEFAULT 'unread'
            );

            CREATE TABLE IF NOT EXISTS item_feeds (
                item_id INTEGER NOT NULL,
                feed_id INTEGER NOT NULL,
                first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (item_id, feed_id),
                FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE,
                FOREIGN KEY (feed_id) REFERENCES feeds(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_items_title_norm ON items(title_norm);
            CREATE INDEX IF NOT EXISTS idx_items_status ON items(item_status);
            CREATE INDEX IF NOT EXISTS idx_item_feeds_feed ON item_feeds(feed_id);
            """
        )
        conn.commit()
