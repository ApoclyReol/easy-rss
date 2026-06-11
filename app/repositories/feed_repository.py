from __future__ import annotations

from typing import Iterable

from app.db import get_conn


def list_feeds(include_disabled: bool = True) -> list[dict]:
    where = "" if include_disabled else "WHERE f.enabled=1"
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT
                f.*,
                COUNT(DISTINCT ifs.item_id) AS item_count,
                SUM(CASE WHEN i.item_status='unread' THEN 1 ELSE 0 END) AS unread_count,
                SUM(CASE WHEN i.item_status='interested' THEN 1 ELSE 0 END) AS interested_count,
                SUM(CASE WHEN i.item_status='archived' THEN 1 ELSE 0 END) AS archived_count,
                SUM(CASE WHEN i.item_status='hidden' THEN 1 ELSE 0 END) AS hidden_count,
                SUM(CASE WHEN i.item_status='expired' THEN 1 ELSE 0 END) AS expired_count
            FROM feeds f
            LEFT JOIN item_feeds ifs ON ifs.feed_id = f.id
            LEFT JOIN items i ON i.id = ifs.item_id
            {where}
            GROUP BY f.id
            ORDER BY f.enabled DESC, f.name COLLATE NOCASE ASC, f.id DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def list_feed_interest_stats(include_disabled: bool = True) -> list[dict]:
    where = "" if include_disabled else "WHERE f.enabled=1"
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT
                f.id,
                f.name,
                f.enabled,
                COUNT(DISTINCT ifs.item_id) AS total_count,
                SUM(CASE WHEN i.item_status='unread' THEN 1 ELSE 0 END) AS unread_count,
                SUM(CASE WHEN i.item_status='interested' THEN 1 ELSE 0 END) AS interested_count,
                SUM(CASE WHEN i.item_status='archived' THEN 1 ELSE 0 END) AS archived_count,
                SUM(CASE WHEN i.item_status='hidden' THEN 1 ELSE 0 END) AS hidden_count,
                SUM(CASE WHEN i.item_status='expired' THEN 1 ELSE 0 END) AS expired_count
            FROM feeds f
            LEFT JOIN item_feeds ifs ON ifs.feed_id = f.id
            LEFT JOIN items i ON i.id = ifs.item_id
            {where}
            GROUP BY f.id
            ORDER BY f.enabled DESC, f.name COLLATE NOCASE ASC, f.id DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_feed(feed_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM feeds WHERE id=?", (feed_id,)).fetchone()
    return dict(row) if row else None


def insert_feed(name: str, url: str, enabled: bool = True) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO feeds(name, url, enabled, updated_at)
            VALUES(?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (name, url, 1 if enabled else 0),
        )
        conn.commit()
        return int(cur.lastrowid)


def sync_item_journals_for_feed(feed_id: int) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            UPDATE items
            SET journal = (
                SELECT f.name
                FROM item_feeds ifs
                JOIN feeds f ON f.id = ifs.feed_id
                WHERE ifs.item_id = items.id
                ORDER BY ifs.feed_id
                LIMIT 1
            )
            WHERE id IN (
                SELECT ifs.item_id
                FROM item_feeds ifs
                WHERE ifs.feed_id = ?
            )
            """,
            (feed_id,),
        )
        conn.commit()
        return int(cur.rowcount or 0)


def sync_all_item_journals() -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            UPDATE items
            SET journal = (
                SELECT f.name
                FROM item_feeds ifs
                JOIN feeds f ON f.id = ifs.feed_id
                WHERE ifs.item_id = items.id
                ORDER BY ifs.feed_id
                LIMIT 1
            )
            WHERE EXISTS (
                SELECT 1
                FROM item_feeds ifs
                JOIN feeds f ON f.id = ifs.feed_id
                WHERE ifs.item_id = items.id
                  AND COALESCE(items.journal, '') <> COALESCE(f.name, '')
            )
            """
        )
        conn.commit()
        return int(cur.rowcount or 0)


def update_feed_meta(feed_id: int, name: str, url: str, enabled: bool) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE feeds
            SET name=?, url=?, enabled=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (name, url, 1 if enabled else 0, feed_id),
        )
        conn.commit()
    sync_item_journals_for_feed(feed_id)


def delete_feed(feed_id: int) -> None:
    delete_feeds([feed_id])


def delete_feeds(feed_ids: Iterable[int]) -> int:
    ids = [int(feed_id) for feed_id in feed_ids]
    if not ids:
        return 0
    placeholders = ", ".join("?" for _ in ids)
    with get_conn() as conn:
        cur = conn.execute(f"DELETE FROM feeds WHERE id IN ({placeholders})", ids)
        conn.execute(
            """
            DELETE FROM items
            WHERE id IN (
                SELECT i.id
                FROM items i
                LEFT JOIN item_feeds ifs ON ifs.item_id = i.id
                WHERE ifs.item_id IS NULL
            )
            """
        )
        conn.commit()
        return cur.rowcount
