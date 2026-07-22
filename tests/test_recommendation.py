import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.db import get_conn, init_db
from app.relevance import parse_llm_review_response
from app.repositories.item_repository import list_items
from app.repositories.recommendation_repository import (
    get_recommendation_summary,
    list_low_relevance_ids,
    set_keyword_override,
)
from app.services.recommendation_service import (
    rebuild_keyword_recommendations,
    score_to_tier,
    tokenize_text,
)


class RecommendationServiceTest(unittest.TestCase):
    def test_status_thresholds_are_stable(self):
        self.assertEqual(score_to_tier(70), "high")
        self.assertEqual(score_to_tier(69.9), "pending")
        self.assertEqual(score_to_tier(31), "pending")
        self.assertEqual(score_to_tier(30), "low")

    def test_tokenizer_supports_english_and_chinese(self):
        tokens = tokenize_text("Large language models 与 社会模拟研究")
        self.assertIn("large", tokens)
        self.assertIn("language", tokens)
        self.assertTrue(any(token in tokens for token in ("社会", "模拟", "社会模拟")))

    def test_llm_review_parser_accepts_only_high_or_low(self):
        self.assertEqual(parse_llm_review_response(" high\n"), "high")
        self.assertEqual(parse_llm_review_response("LOW"), "low")
        with self.assertRaises(ValueError):
            parse_llm_review_response("high because relevant")

    def test_rebuild_uses_manual_labels_and_scores_unread(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rss_reader.sqlite3"
            with patch("app.db.DB_PATH", db_path):
                init_db()
                rows = [
                    ("p1", "LLM social simulation", "large language model agent society", "interested"),
                    ("p2", "Computational social science", "language model social agents", "archived"),
                    ("p3", "Agent based social simulation", "computational sociology", "archived"),
                    ("n1", "Protein folding", "molecular biology proteins", "hidden"),
                    ("n2", "Medical imaging", "clinical radiology diagnosis", "expired"),
                    ("n3", "Cancer biomarkers", "oncology clinical trial", "hidden"),
                    ("u1", "LLM agents simulate society", "computational social science", "unread"),
                    ("u2", "Clinical protein imaging", "radiology oncology", "unread"),
                    ("u3", "", "", "unread"),
                ]
                with get_conn() as conn:
                    conn.executemany(
                        """
                        INSERT INTO items(stable_guid, title, title_norm, summary, item_status)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        [(guid, title, title.casefold(), summary, status) for guid, title, summary, status in rows],
                    )
                    conn.commit()

                result = rebuild_keyword_recommendations()
                self.assertEqual(result.positive_count, 3)
                self.assertEqual(result.negative_count, 3)
                self.assertEqual(result.unread_count, 3)
                self.assertEqual(result.unscored_count, 1)

                summary = get_recommendation_summary()
                self.assertEqual(summary["unscored"], 1)
                scored = [item for item in list_items("unread", limit=None) if item["keyword_score"] is not None]
                self.assertEqual(len(scored), 2)
                score_map = {item["stable_guid"]: item["keyword_score"] for item in scored}
                self.assertGreater(score_map["u1"], score_map["u2"])

    def test_unread_order_and_low_scope_use_persisted_tiers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rss_reader.sqlite3"
            with patch("app.db.DB_PATH", db_path):
                init_db()
                with get_conn() as conn:
                    for guid, title in (("low", "Low paper"), ("high", "High paper"), ("none", "Unscored paper")):
                        conn.execute(
                            "INSERT INTO items(stable_guid, title, title_norm, item_status) VALUES (?, ?, ?, 'unread')",
                            (guid, title, title.casefold()),
                        )
                    ids = {row["stable_guid"]: row["id"] for row in conn.execute("SELECT id, stable_guid FROM items")}
                    for guid, score, tier in (("low", 10, "low"), ("high", 90, "high")):
                        conn.execute(
                            """
                            INSERT INTO recommendation_scores(
                                item_id, keyword_score, keyword_tier, final_tier,
                                model_version, content_hash
                            ) VALUES (?, ?, ?, ?, 'v1', 'hash')
                            """,
                            (ids[guid], score, tier, tier),
                        )
                    conn.commit()

                ordered = list_items("unread", limit=None)
                self.assertEqual([row["stable_guid"] for row in ordered], ["high", "none", "low"])
                self.assertEqual(list_low_relevance_ids(q="Low"), [ids["low"]])
                self.assertEqual(list_low_relevance_ids(q="High"), [])

    def test_manual_keyword_override_is_persisted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rss_reader.sqlite3"
            with patch("app.db.DB_PATH", db_path):
                init_db()
                set_keyword_override("Social Simulation", direction="positive", weight=2.5, disabled=False)
                with get_conn() as conn:
                    row = conn.execute(
                        "SELECT * FROM recommendation_keywords WHERE keyword='social simulation'"
                    ).fetchone()
                self.assertEqual(row["manual_direction"], "positive")
                self.assertEqual(row["manual_weight"], 2.5)


if __name__ == "__main__":
    unittest.main()
