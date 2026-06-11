from __future__ import annotations

import importlib
import time
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

import feedparser
import httpx

from app import rss_core as rss_core_module
from app.config import DEFAULT_HIDDEN_EXPIRE_DAYS, FETCH_RETRY_ATTEMPTS, FETCH_RETRY_BACKOFF_SECONDS, USER_AGENT
from app.db import get_conn
from app.repositories import expire_hidden_items_before, sync_item_journals_for_feed
from app.repositories.feed_repository import get_feed, insert_feed
from app.services.analytics_service import build_expire_cutoff
from app.services.settings_service import load_settings, save_settings

rss_core = importlib.reload(rss_core_module)


@dataclass
class UpdateResult:
    feed_id: int
    feed_name: str
    fetched: int = 0
    new_items: int = 0
    duplicate_hits: int = 0
    new_feed_links: int = 0
    error: str | None = None


TRANSIENT_FETCH_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ReadError,
    httpx.ReadTimeout,
    httpx.WriteError,
    httpx.WriteTimeout,
    httpx.RemoteProtocolError,
)


def _find_existing_item_id(conn, item: dict[str, str]) -> int | None:
    row = conn.execute("SELECT id FROM items WHERE stable_guid=?", (item["stable_guid"],)).fetchone()
    if row:
        return int(row["id"])

    if item["doi"]:
        row = conn.execute(
            "SELECT id FROM items WHERE doi=? ORDER BY id DESC LIMIT 1",
            (item["doi"],),
        ).fetchone()
        if row:
            return int(row["id"])

    if item["link"]:
        row = conn.execute(
            "SELECT id FROM items WHERE link=? ORDER BY id DESC LIMIT 1",
            (item["link"],),
        ).fetchone()
        if row:
            return int(row["id"])

    if item["authors"]:
        rows = conn.execute(
            """
            SELECT id, journal
            FROM items
            WHERE title_norm=?
              AND COALESCE(authors, '')=?
              AND COALESCE(year, '')=?
            ORDER BY id DESC
            """,
            (item["title_norm"], item["authors"] or "", item["year"] or ""),
        ).fetchall()
        if len(rows) == 1:
            return int(rows[0]["id"])

        exact_journal_rows = [row for row in rows if (row["journal"] or "") == (item["journal"] or "")]
        if len(exact_journal_rows) == 1:
            return int(exact_journal_rows[0]["id"])
    return None


def valid_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def add_feed(name: str, url: str, enabled: bool = True) -> int:
    name = name.strip()
    url = url.strip()
    if not name:
        raise ValueError("订阅名称不能为空")
    if not valid_url(url):
        raise ValueError("RSS URL 必须是 http/https 链接")
    return insert_feed(name, url, enabled)


def validate_feed_input(name: str, url: str) -> tuple[str, str]:
    normalized_name = name.strip()
    normalized_url = url.strip()
    if not normalized_name:
        raise ValueError("订阅名称不能为空")
    if not valid_url(normalized_url):
        raise ValueError("RSS URL 必须是 http/https 链接")
    return normalized_name, normalized_url


def fetch_feed_content(url: str) -> bytes:
    last_error: Exception | None = None
    for attempt in range(1, FETCH_RETRY_ATTEMPTS + 1):
        try:
            with httpx.Client(timeout=30, follow_redirects=True, http2=False) as client:
                resp = client.get(
                    url,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
                    },
                )
                resp.raise_for_status()
                return resp.content
        except TRANSIENT_FETCH_EXCEPTIONS as exc:
            last_error = exc
            if attempt == FETCH_RETRY_ATTEMPTS:
                break
            time.sleep(FETCH_RETRY_BACKOFF_SECONDS * attempt)
        except Exception:
            raise
    assert last_error is not None
    raise last_error


def update_one_feed(feed_id: int) -> UpdateResult:
    feed = get_feed(feed_id)
    if not feed:
        return UpdateResult(feed_id=feed_id, feed_name="", error="订阅不存在")

    try:
        content = fetch_feed_content(feed["url"])
        parsed = feedparser.parse(content)
        if parsed.bozo and not parsed.entries:
            raise RuntimeError(f"RSS 解析失败：{parsed.bozo_exception}")
    except Exception as exc:
        with get_conn() as conn:
            conn.execute(
                "UPDATE feeds SET last_checked_at=CURRENT_TIMESTAMP, last_error=? WHERE id=?",
                (str(exc), feed_id),
            )
            conn.commit()
        return UpdateResult(feed_id=feed_id, feed_name=feed["name"], error=str(exc))

    inserted = 0
    updated = 0
    linked = 0
    feed_name = feed["name"] or parsed.feed.get("title", "")

    with get_conn() as conn:
        for entry in parsed.entries:
            item = rss_core.entry_to_item(entry, feed_name)
            existing_item_id = _find_existing_item_id(conn, item)

            if existing_item_id is not None:
                item_id = existing_item_id
                conn.execute(
                    """
                    UPDATE items
                    SET last_seen_at=CURRENT_TIMESTAMP,
                        title=COALESCE(NULLIF(?, ''), title),
                        authors=COALESCE(NULLIF(?, ''), authors),
                        journal=COALESCE(NULLIF(?, ''), journal),
                        year=COALESCE(NULLIF(?, ''), year),
                        doi=COALESCE(NULLIF(?, ''), doi),
                        link=COALESCE(NULLIF(?, ''), link),
                        pub_date=COALESCE(NULLIF(?, ''), pub_date),
                        summary=COALESCE(NULLIF(?, ''), summary)
                    WHERE id=?
                    """,
                    (
                        item["title"],
                        item["authors"],
                        item["journal"],
                        item["year"],
                        item["doi"],
                        item["link"],
                        item["pub_date"],
                        item["summary"],
                        item_id,
                    ),
                )
                conn.execute(
                    """
                    UPDATE items
                    SET stable_guid=?
                    WHERE id=?
                      AND NOT EXISTS (
                          SELECT 1 FROM items x WHERE x.stable_guid=? AND x.id<>?
                      )
                    """,
                    (item["stable_guid"], item_id, item["stable_guid"], item_id),
                )
                updated += 1
            else:
                cur = conn.execute(
                    """
                    INSERT INTO items(stable_guid, title, title_norm, authors, journal, year, doi, link, pub_date, summary)
                    VALUES(:stable_guid, :title, :title_norm, :authors, :journal, :year, :doi, :link, :pub_date, :summary)
                    """,
                    item,
                )
                item_id = int(cur.lastrowid)
                inserted += 1

            rel = conn.execute(
                "SELECT 1 FROM item_feeds WHERE item_id=? AND feed_id=?",
                (item_id, feed_id),
            ).fetchone()
            if rel:
                conn.execute(
                    "UPDATE item_feeds SET last_seen_at=CURRENT_TIMESTAMP WHERE item_id=? AND feed_id=?",
                    (item_id, feed_id),
                )
            else:
                conn.execute("INSERT INTO item_feeds(item_id, feed_id) VALUES(?, ?)", (item_id, feed_id))
                linked += 1

        conn.execute(
            "UPDATE feeds SET last_checked_at=CURRENT_TIMESTAMP, last_error=NULL WHERE id=?",
            (feed_id,),
        )
        conn.commit()

    sync_item_journals_for_feed(feed_id)

    return UpdateResult(
        feed_id=feed_id,
        feed_name=feed_name,
        fetched=len(parsed.entries),
        new_items=inserted,
        duplicate_hits=updated,
        new_feed_links=linked,
    )


def update_all_feeds() -> list[UpdateResult]:
    with get_conn() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM feeds WHERE enabled=1 ORDER BY id").fetchall()]
    return [update_one_feed(feed_id) for feed_id in ids]


def run_feed_update(feed_ids: list[int] | None = None) -> list[UpdateResult]:
    if feed_ids is None:
        return update_all_feeds()
    normalized_ids = [int(feed_id) for feed_id in feed_ids]
    return [update_one_feed(feed_id) for feed_id in normalized_ids]


def run_post_update_expiration() -> int:
    settings = load_settings()
    expire_days = max(1, int(settings.hidden_expire_days or DEFAULT_HIDDEN_EXPIRE_DAYS))
    return expire_hidden_items_before(build_expire_cutoff(expire_days))


def run_data_refresh(feed_ids: list[int] | None = None) -> tuple[list[UpdateResult], int]:
    results = run_feed_update(feed_ids)
    expired_count = run_post_update_expiration()
    return results, expired_count


def record_update_summary(
    results: list[UpdateResult],
    trigger: str,
    started_at: datetime | None = None,
    expired_items: int = 0,
) -> None:
    settings = load_settings()
    finished_at = datetime.now().astimezone()
    settings.last_feed_update_started_at = (started_at or finished_at).isoformat(timespec="seconds")
    settings.last_feed_update_finished_at = finished_at.isoformat(timespec="seconds")
    settings.last_feed_update_trigger = trigger
    settings.last_feed_update_total_feeds = len(results)
    settings.last_feed_update_success_feeds = sum(1 for result in results if not result.error)
    settings.last_feed_update_total_new_items = sum(int(result.new_items or 0) for result in results)
    settings.last_feed_update_expired_items = int(expired_items or 0)
    settings.last_feed_update_results = [
        {
            "feed_id": int(result.feed_id),
            "feed_name": result.feed_name,
            "fetched": int(result.fetched or 0),
            "new_items": int(result.new_items or 0),
            "duplicate_hits": int(result.duplicate_hits or 0),
            "new_feed_links": int(result.new_feed_links or 0),
            "error": result.error or "",
        }
        for result in results
    ]
    save_settings(settings)
