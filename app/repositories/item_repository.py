from __future__ import annotations

from typing import Iterable

from app.db import get_conn
from app import rss_core

ITEM_STATUSES = {"unread", "interested", "archived", "hidden", "expired"}
STATUS_PRIORITY = {
    "archived": 5,
    "interested": 4,
    "hidden": 3,
    "expired": 2,
    "unread": 1,
}


def _build_item_where(
    status: str,
    q: str = "",
    feed_ids: Iterable[int] | None = None,
) -> tuple[list[str], list]:
    where: list[str] = []
    params: list = []

    if status not in ITEM_STATUSES:
        raise ValueError(f"Unsupported item status: {status}")
    where.append("i.item_status=?")
    params.append(status)

    if q.strip():
        where.append("(i.title LIKE ? OR i.authors LIKE ? OR i.summary LIKE ? OR i.journal LIKE ? OR i.doi LIKE ?)")
        needle = f"%{q.strip()}%"
        params.extend([needle, needle, needle, needle, needle])

    normalized_feed_ids = [int(value) for value in (feed_ids or []) if value is not None]
    if normalized_feed_ids:
        placeholders = ", ".join("?" for _ in normalized_feed_ids)
        where.append(
            f"EXISTS (SELECT 1 FROM item_feeds x WHERE x.item_id=i.id AND x.feed_id IN ({placeholders}))"
        )
        params.extend(normalized_feed_ids)

    if not where:
        where.append("1=1")

    return where, params


def list_items(
    status: str,
    q: str = "",
    feed_ids: Iterable[int] | None = None,
    limit: int | None = 100,
) -> list[dict]:
    where, params = _build_item_where(
        status=status,
        q=q,
        feed_ids=feed_ids,
    )
    limit_sql = ""
    if limit is not None:
        limit_sql = "LIMIT ?"
        params.append(limit)
    sql = f"""
        SELECT
            i.*,
            GROUP_CONCAT(f.name, ' / ') AS feed_names
        FROM items i
        LEFT JOIN item_feeds ifs ON ifs.item_id = i.id
        LEFT JOIN feeds f ON f.id = ifs.feed_id
        WHERE {' AND '.join(where)}
        GROUP BY i.id
        ORDER BY i.last_seen_at DESC, i.id DESC
        {limit_sql}
    """
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_items_by_ids(item_ids: Iterable[int]) -> list[dict]:
    ids = [int(item_id) for item_id in item_ids]
    if not ids:
        return []
    placeholders = ", ".join("?" for _ in ids)
    sql = f"""
        SELECT
            i.*,
            GROUP_CONCAT(f.name, ' / ') AS feed_names
        FROM items i
        LEFT JOIN item_feeds ifs ON ifs.item_id = i.id
        LEFT JOIN feeds f ON f.id = ifs.feed_id
        WHERE i.id IN ({placeholders})
        GROUP BY i.id
        ORDER BY i.id DESC
    """
    with get_conn() as conn:
        rows = conn.execute(sql, ids).fetchall()
    return [dict(r) for r in rows]


def count_items() -> dict:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN item_status NOT IN ('hidden', 'expired') THEN 1 ELSE 0 END) AS visible,
                SUM(CASE WHEN item_status='unread' THEN 1 ELSE 0 END) AS unread,
                SUM(CASE WHEN item_status='interested' THEN 1 ELSE 0 END) AS interested,
                SUM(CASE WHEN item_status='archived' THEN 1 ELSE 0 END) AS archived,
                SUM(CASE WHEN item_status='hidden' THEN 1 ELSE 0 END) AS hidden,
                SUM(CASE WHEN item_status='expired' THEN 1 ELSE 0 END) AS expired
            FROM items
            """
        ).fetchone()
    return {k: (row[k] or 0) for k in row.keys()}


def count_items_for_view(
    status: str,
    q: str = "",
    feed_ids: Iterable[int] | None = None,
) -> int:
    where, params = _build_item_where(
        status=status,
        q=q,
        feed_ids=feed_ids,
    )
    sql = f"SELECT COUNT(*) AS matched_count FROM items i WHERE {' AND '.join(where)}"
    with get_conn() as conn:
        row = conn.execute(sql, params).fetchone()
    return int(row["matched_count"] or 0)


def set_item_status(item_id: int, status: str) -> None:
    if status not in ITEM_STATUSES:
        raise ValueError(f"Unsupported item status: {status}")
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE items
            SET item_status=?
            WHERE id=?
            """,
            (status, item_id),
        )
        conn.commit()


def batch_set_status(item_ids: Iterable[int], status: str) -> int:
    ids = [int(item_id) for item_id in item_ids]
    if not ids:
        return 0
    if status not in ITEM_STATUSES:
        raise ValueError(f"Unsupported item status: {status}")
    placeholders = ", ".join("?" for _ in ids)
    params = [status, *ids]
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE items SET item_status=? WHERE id IN ({placeholders})",
            params,
        )
        conn.commit()
        return cur.rowcount


def set_status_for_filter(
    status: str,
    q: str = "",
    feed_ids: Iterable[int] | None = None,
    target_status: str = "hidden",
) -> int:
    if target_status not in ITEM_STATUSES:
        raise ValueError(f"Unsupported target status: {target_status}")
    where, params = _build_item_where(
        status=status,
        q=q,
        feed_ids=feed_ids,
    )
    normalized_where = [clause.replace("i.", "") for clause in where]
    sql = f"""
        UPDATE items
        SET item_status=?
        WHERE {' AND '.join(normalized_where)}
    """
    with get_conn() as conn:
        cur = conn.execute(
            sql,
            [target_status, *params],
        )
        conn.commit()
        return cur.rowcount


def expire_hidden_items_before(cutoff_iso: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            UPDATE items
            SET item_status='expired'
            WHERE item_status='hidden'
              AND COALESCE(NULLIF(last_seen_at, ''), first_seen_at) < ?
            """,
            (cutoff_iso,),
        )
        conn.commit()
        return cur.rowcount


def merge_duplicate_items() -> int:
    merged_groups = 0
    with get_conn() as conn:
        groups = conn.execute(
            """
            SELECT
                title_norm,
                COALESCE(authors, '') AS authors_key,
                COALESCE(journal, '') AS journal_key,
                COALESCE(year, '') AS year_key,
                COALESCE(doi, '') AS doi_key,
                COUNT(*) AS row_count
            FROM items
            GROUP BY title_norm, authors_key, journal_key, year_key, doi_key
            HAVING COUNT(*) > 1
               AND (authors_key <> '' OR doi_key <> '')
            """
        ).fetchall()

        for group in groups:
            rows = conn.execute(
                """
                SELECT *
                FROM items
                WHERE title_norm=?
                  AND COALESCE(authors, '')=?
                  AND COALESCE(journal, '')=?
                  AND COALESCE(year, '')=?
                  AND COALESCE(doi, '')=?
                ORDER BY id ASC
                """,
                (
                    group["title_norm"],
                    group["authors_key"],
                    group["journal_key"],
                    group["year_key"],
                    group["doi_key"],
                ),
            ).fetchall()
            if len(rows) <= 1:
                continue

            ranked = sorted(
                rows,
                key=lambda row: (
                    STATUS_PRIORITY.get(row["item_status"], 0),
                    row["last_seen_at"] or "",
                    -int(row["id"]),
                ),
                reverse=True,
            )
            winner = ranked[0]
            loser_ids = [int(row["id"]) for row in ranked[1:]]
            if not loser_ids:
                continue

            canonical_guid, _ = rss_core.stable_guid(
                winner["title"] or "",
                winner["journal"] or "",
                winner["year"] or "",
                winner["authors"] or "",
                winner["doi"] or "",
            )
            winner_id = int(winner["id"])

            placeholders = ", ".join("?" for _ in loser_ids)
            conn.execute(
                f"""
                INSERT OR IGNORE INTO item_feeds(item_id, feed_id, first_seen_at, last_seen_at)
                SELECT ?, feed_id, first_seen_at, last_seen_at
                FROM item_feeds
                WHERE item_id IN ({placeholders})
                """,
                (winner_id, *loser_ids),
            )
            conn.execute(
                f"""
                UPDATE items
                SET item_status=?,
                    first_seen_at=(
                        SELECT MIN(first_seen_at) FROM items WHERE id IN ({placeholders}, ?)
                    ),
                    last_seen_at=(
                        SELECT MAX(last_seen_at) FROM items WHERE id IN ({placeholders}, ?)
                    )
                WHERE id=?
                """,
                (
                    winner["item_status"],
                    *loser_ids,
                    winner_id,
                    *loser_ids,
                    winner_id,
                    winner_id,
                ),
            )
            conn.execute(f"DELETE FROM items WHERE id IN ({placeholders})", loser_ids)
            conn.execute(
                """
                UPDATE items
                SET stable_guid=?
                WHERE id=?
                """,
                (canonical_guid, winner_id),
            )
            merged_groups += 1

        conn.commit()
    return merged_groups


def rebuild_stable_guids() -> int:
    updated = 0
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, stable_guid, title, journal, year, authors, doi
            FROM items
            ORDER BY id ASC
            """
        ).fetchall()

        for row in rows:
            next_guid, _ = rss_core.stable_guid(
                row["title"] or "",
                row["journal"] or "",
                row["year"] or "",
                row["authors"] or "",
                row["doi"] or "",
            )
            if next_guid == row["stable_guid"]:
                continue

            conflict = conn.execute(
                "SELECT id FROM items WHERE stable_guid=? AND id<>?",
                (next_guid, int(row["id"])),
            ).fetchone()
            if conflict:
                continue

            conn.execute(
                """
                UPDATE items
                SET stable_guid=?
                WHERE id=?
                """,
                (next_guid, int(row["id"])),
            )
            updated += 1

        conn.commit()
    return updated


def split_low_signal_multi_feed_items() -> int:
    created = 0
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT i.*
            FROM items i
            JOIN item_feeds ifs ON ifs.item_id = i.id
            GROUP BY i.id
            HAVING COUNT(DISTINCT ifs.feed_id) > 1
               AND COALESCE(i.authors, '') = ''
               AND COALESCE(i.doi, '') = ''
            ORDER BY i.id ASC
            """
        ).fetchall()

        for row in rows:
            feed_rows = conn.execute(
                """
                SELECT ifs.feed_id, ifs.first_seen_at, ifs.last_seen_at, f.name
                FROM item_feeds ifs
                JOIN feeds f ON f.id = ifs.feed_id
                WHERE ifs.item_id=?
                ORDER BY ifs.feed_id ASC
                """,
                (int(row["id"]),),
            ).fetchall()
            if len(feed_rows) <= 1:
                continue

            primary_feed = feed_rows[0]
            primary_guid, _ = rss_core.stable_guid(
                row["title"] or "",
                primary_feed["name"] or "",
                row["year"] or "",
                row["authors"] or "",
                row["doi"] or "",
            )
            conn.execute(
                """
                UPDATE items
                SET journal=?, stable_guid=?
                WHERE id=?
                """,
                (primary_feed["name"], primary_guid, int(row["id"])),
            )

            for feed_row in feed_rows[1:]:
                next_guid, _ = rss_core.stable_guid(
                    row["title"] or "",
                    feed_row["name"] or "",
                    row["year"] or "",
                    row["authors"] or "",
                    row["doi"] or "",
                )
                cur = conn.execute(
                    """
                    INSERT INTO items(
                        stable_guid, title, title_norm, authors, journal, year, doi, link, pub_date, summary, first_seen_at, last_seen_at, item_status
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        next_guid,
                        row["title"],
                        row["title_norm"],
                        row["authors"],
                        feed_row["name"],
                        row["year"],
                        row["doi"],
                        row["link"],
                        row["pub_date"],
                        row["summary"],
                        row["first_seen_at"],
                        row["last_seen_at"],
                        row["item_status"],
                    ),
                )
                clone_id = int(cur.lastrowid)
                conn.execute(
                    """
                    UPDATE item_feeds
                    SET item_id=?
                    WHERE item_id=? AND feed_id=?
                    """,
                    (clone_id, int(row["id"]), int(feed_row["feed_id"])),
                )
                created += 1

        conn.commit()
    return created
