from __future__ import annotations

import json
from typing import Iterable

from app.db import get_conn


def list_training_items() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, title, summary, item_status
            FROM items
            WHERE item_status IN ('interested', 'archived', 'hidden', 'expired')
            ORDER BY id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def list_unread_items() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, title, summary, authors, journal, link
            FROM items
            WHERE item_status='unread'
            ORDER BY last_seen_at DESC, id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_keyword_overrides() -> dict[str, dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT keyword, manual_direction, manual_weight, is_disabled
            FROM recommendation_keywords
            WHERE manual_direction IS NOT NULL OR manual_weight IS NOT NULL OR is_disabled=1
            """
        ).fetchall()
    return {str(row["keyword"]): dict(row) for row in rows}


def replace_model_results(
    *,
    model_version: str,
    positive_count: int,
    negative_count: int,
    unread_count: int,
    keywords: list[dict],
    scores: list[dict],
) -> None:
    with get_conn() as conn:
        overrides = {
            row["keyword"]: dict(row)
            for row in conn.execute(
                """
                SELECT keyword, manual_direction, manual_weight, is_disabled
                FROM recommendation_keywords
                WHERE manual_direction IS NOT NULL OR manual_weight IS NOT NULL OR is_disabled=1
                """
            ).fetchall()
        }
        conn.execute("DELETE FROM recommendation_keywords")
        for row in keywords:
            override = overrides.pop(row["keyword"], {})
            conn.execute(
                """
                INSERT INTO recommendation_keywords (
                    keyword, auto_weight, positive_count, negative_count,
                    manual_direction, manual_weight, is_disabled, model_version, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    row["keyword"], row["auto_weight"], row["positive_count"], row["negative_count"],
                    override.get("manual_direction"), override.get("manual_weight"),
                    int(override.get("is_disabled") or 0), model_version,
                ),
            )
        for keyword, override in overrides.items():
            conn.execute(
                """
                INSERT INTO recommendation_keywords (
                    keyword, manual_direction, manual_weight, is_disabled, model_version, updated_at
                ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    keyword, override.get("manual_direction"), override.get("manual_weight"),
                    int(override.get("is_disabled") or 0), model_version,
                ),
            )

        conn.execute("DELETE FROM recommendation_scores")
        conn.executemany(
            """
            INSERT INTO recommendation_scores (
                item_id, keyword_score, keyword_tier, final_tier, llm_tier, llm_error,
                matched_keywords, model_version, content_hash, scored_at, llm_reviewed_at
            ) VALUES (?, ?, ?, ?, NULL, NULL, ?, ?, ?, CURRENT_TIMESTAMP, NULL)
            """,
            [
                (
                    row["item_id"], row["keyword_score"], row["keyword_tier"], row["keyword_tier"],
                    json.dumps(row["matched_keywords"], ensure_ascii=False), model_version, row["content_hash"],
                )
                for row in scores
            ],
        )
        conn.execute(
            """
            INSERT INTO recommendation_models (
                model_version, positive_count, negative_count, unread_count, error_message
            ) VALUES (?, ?, ?, ?, NULL)
            """,
            (model_version, positive_count, negative_count, unread_count),
        )
        conn.commit()


def record_model_error(*, model_version: str, positive_count: int, negative_count: int, unread_count: int, error: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO recommendation_models (
                model_version, positive_count, negative_count, unread_count, error_message
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (model_version, positive_count, negative_count, unread_count, error),
        )
        conn.commit()


def get_recommendation_summary() -> dict:
    with get_conn() as conn:
        model = conn.execute(
            """
            SELECT * FROM recommendation_models ORDER BY created_at DESC, rowid DESC LIMIT 1
            """
        ).fetchone()
        counts = conn.execute(
            """
            SELECT
                SUM(CASE WHEN s.final_tier='high' THEN 1 ELSE 0 END) AS high,
                SUM(CASE WHEN s.final_tier='pending' THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN s.final_tier='low' THEN 1 ELSE 0 END) AS low,
                SUM(CASE WHEN s.item_id IS NULL THEN 1 ELSE 0 END) AS unscored
            FROM items i
            LEFT JOIN recommendation_scores s ON s.item_id=i.id
            WHERE i.item_status='unread'
            """
        ).fetchone()
    result = {"high": 0, "pending": 0, "low": 0, "unscored": 0, "model": None}
    if counts:
        result.update({key: int(counts[key] or 0) for key in ("high", "pending", "low", "unscored")})
    if model:
        result["model"] = dict(model)
    return result


def list_keywords(limit: int = 40) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT *, COALESCE(manual_weight, auto_weight) AS effective_weight
            FROM recommendation_keywords
            ORDER BY is_disabled ASC, ABS(COALESCE(manual_weight, auto_weight)) DESC, keyword
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    return [dict(row) for row in rows]


def set_keyword_override(
    keyword: str,
    *,
    direction: str | None,
    weight: float | None,
    disabled: bool,
) -> None:
    normalized = keyword.strip().casefold()
    if not normalized:
        raise ValueError("关键词不能为空")
    if direction not in {None, "positive", "negative"}:
        raise ValueError("关键词方向必须是 positive 或 negative")
    signed_weight = None
    if weight is not None:
        magnitude = abs(float(weight))
        signed_weight = -magnitude if direction == "negative" else magnitude
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO recommendation_keywords (
                keyword, manual_direction, manual_weight, is_disabled, updated_at
            ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(keyword) DO UPDATE SET
                manual_direction=excluded.manual_direction,
                manual_weight=excluded.manual_weight,
                is_disabled=excluded.is_disabled,
                updated_at=CURRENT_TIMESTAMP
            """,
            (normalized, direction, signed_weight, int(disabled)),
        )
        conn.commit()


def reset_keyword_override(keyword: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE recommendation_keywords
            SET manual_direction=NULL, manual_weight=NULL, is_disabled=0, updated_at=CURRENT_TIMESTAMP
            WHERE keyword=?
            """,
            (keyword,),
        )
        conn.commit()


def list_pending_for_llm() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT i.*, s.keyword_score, s.matched_keywords, s.model_version, s.content_hash
            FROM items i
            JOIN recommendation_scores s ON s.item_id=i.id
            WHERE i.item_status='unread'
              AND s.keyword_tier='pending'
              AND (s.llm_tier IS NULL OR s.llm_error IS NOT NULL)
            ORDER BY i.last_seen_at DESC, i.id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def save_llm_review(item_id: int, *, tier: str | None, error: str | None) -> None:
    if tier not in {None, "high", "low"}:
        raise ValueError("Unsupported LLM tier")
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE recommendation_scores
            SET llm_tier=?, llm_error=?, final_tier=COALESCE(?, keyword_tier), llm_reviewed_at=CURRENT_TIMESTAMP
            WHERE item_id=?
            """,
            (tier, error, tier, int(item_id)),
        )
        conn.commit()


def list_low_relevance_ids(q: str = "", feed_ids: Iterable[int] | None = None) -> list[int]:
    where = ["i.item_status='unread'", "s.final_tier='low'"]
    params: list = []
    if q.strip():
        where.append("(i.title LIKE ? OR i.authors LIKE ? OR i.summary LIKE ? OR i.journal LIKE ? OR i.doi LIKE ?)")
        needle = f"%{q.strip()}%"
        params.extend([needle] * 5)
    normalized_feed_ids = [int(value) for value in (feed_ids or []) if value is not None]
    if normalized_feed_ids:
        placeholders = ", ".join("?" for _ in normalized_feed_ids)
        where.append(f"EXISTS (SELECT 1 FROM item_feeds x WHERE x.item_id=i.id AND x.feed_id IN ({placeholders}))")
        params.extend(normalized_feed_ids)
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT i.id FROM items i
            JOIN recommendation_scores s ON s.item_id=i.id
            WHERE {' AND '.join(where)}
            ORDER BY i.id
            """,
            params,
        ).fetchall()
    return [int(row["id"]) for row in rows]
