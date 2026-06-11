import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.db import get_conn, init_db
from app.repositories.feed_repository import insert_feed, sync_all_item_journals, update_feed_meta
from app.repositories.item_repository import merge_duplicate_items, rebuild_stable_guids, split_low_signal_multi_feed_items


class FeedRepositoryJournalSyncTest(unittest.TestCase):
    def test_sync_all_item_journals_aligns_items_to_feed_names(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rss_reader.sqlite3"
            with patch("app.db.DB_PATH", db_path):
                init_db()
                feed_id = insert_feed("Canonical Journal", "https://example.com/rss")
                with get_conn() as conn:
                    cur = conn.execute(
                        """
                        INSERT INTO items(stable_guid, title, title_norm, journal, item_status)
                        VALUES('guid-1', 'Title', 'title', 'Canonical Journal, Volume 1', 'hidden')
                        """
                    )
                    item_id = int(cur.lastrowid)
                    conn.execute("INSERT INTO item_feeds(item_id, feed_id) VALUES(?, ?)", (item_id, feed_id))
                    conn.commit()

                changed = sync_all_item_journals()
                self.assertEqual(changed, 1)

                with get_conn() as conn:
                    journal = conn.execute("SELECT journal FROM items WHERE id=?", (item_id,)).fetchone()["journal"]
                self.assertEqual(journal, "Canonical Journal")

    def test_update_feed_meta_propagates_renamed_feed_to_items(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rss_reader.sqlite3"
            with patch("app.db.DB_PATH", db_path):
                init_db()
                feed_id = insert_feed("Old Journal", "https://example.com/rss")
                with get_conn() as conn:
                    cur = conn.execute(
                        """
                        INSERT INTO items(stable_guid, title, title_norm, journal, item_status)
                        VALUES('guid-2', 'Title', 'title', 'Old Journal', 'interested')
                        """
                    )
                    item_id = int(cur.lastrowid)
                    conn.execute("INSERT INTO item_feeds(item_id, feed_id) VALUES(?, ?)", (item_id, feed_id))
                    conn.commit()

                update_feed_meta(feed_id, "Renamed Journal", "https://example.com/rss", True)

                with get_conn() as conn:
                    journal = conn.execute("SELECT journal FROM items WHERE id=?", (item_id,)).fetchone()["journal"]
                self.assertEqual(journal, "Renamed Journal")

    def test_merge_duplicate_items_keeps_manual_status_over_unread(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rss_reader.sqlite3"
            with patch("app.db.DB_PATH", db_path):
                init_db()
                feed_id = insert_feed("Canonical Journal", "https://example.com/rss")
                with get_conn() as conn:
                    conn.execute(
                        """
                        INSERT INTO items(stable_guid, title, title_norm, authors, journal, year, item_status)
                        VALUES('guid-a', 'Same Title', 'sametitle', 'Alice', 'Canonical Journal', '2026', 'interested')
                        """
                    )
                    conn.execute(
                        """
                        INSERT INTO items(stable_guid, title, title_norm, authors, journal, year, item_status)
                        VALUES('guid-b', 'Same Title', 'sametitle', 'Alice', 'Canonical Journal', '2026', 'unread')
                        """
                    )
                    rows = conn.execute("SELECT id FROM items ORDER BY id").fetchall()
                    conn.execute("INSERT INTO item_feeds(item_id, feed_id) VALUES(?, ?)", (int(rows[0]["id"]), feed_id))
                    conn.execute("INSERT INTO item_feeds(item_id, feed_id) VALUES(?, ?)", (int(rows[1]["id"]), feed_id))
                    conn.commit()

                merged = merge_duplicate_items()
                self.assertEqual(merged, 1)

                with get_conn() as conn:
                    remaining = conn.execute("SELECT item_status, COUNT(*) AS cnt FROM items GROUP BY item_status").fetchall()
                self.assertEqual(len(remaining), 1)
                self.assertEqual(remaining[0]["item_status"], "interested")
                self.assertEqual(remaining[0]["cnt"], 1)

    def test_rebuild_stable_guids_updates_non_conflicting_legacy_guids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rss_reader.sqlite3"
            with patch("app.db.DB_PATH", db_path):
                init_db()
                with get_conn() as conn:
                    conn.execute(
                        """
                        INSERT INTO items(stable_guid, title, title_norm, authors, journal, year, item_status)
                        VALUES('legacy-guid', 'Same Title', 'sametitle', 'Alice', 'Canonical Journal', '2026', 'unread')
                        """
                    )
                    conn.commit()

                changed = rebuild_stable_guids()
                self.assertEqual(changed, 1)

                with get_conn() as conn:
                    row = conn.execute("SELECT stable_guid FROM items").fetchone()
                self.assertNotEqual(row["stable_guid"], "legacy-guid")

    def test_split_low_signal_multi_feed_items_separates_cross_feed_generic_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rss_reader.sqlite3"
            with patch("app.db.DB_PATH", db_path):
                init_db()
                feed_a = insert_feed("Journal A", "https://example.com/a")
                feed_b = insert_feed("Journal B", "https://example.com/b")
                with get_conn() as conn:
                    cur = conn.execute(
                        """
                        INSERT INTO items(stable_guid, title, title_norm, authors, journal, year, item_status)
                        VALUES('legacy-guid', 'Editorial Board', 'editorialboard', '', 'Journal A', '2026', 'hidden')
                        """
                    )
                    item_id = int(cur.lastrowid)
                    conn.execute("INSERT INTO item_feeds(item_id, feed_id) VALUES(?, ?)", (item_id, feed_a))
                    conn.execute("INSERT INTO item_feeds(item_id, feed_id) VALUES(?, ?)", (item_id, feed_b))
                    conn.commit()

                created = split_low_signal_multi_feed_items()
                self.assertEqual(created, 1)

                with get_conn() as conn:
                    rows = conn.execute(
                        """
                        SELECT i.journal, COUNT(*) AS cnt
                        FROM items i
                        WHERE i.title='Editorial Board'
                        GROUP BY i.journal
                        ORDER BY i.journal
                        """
                    ).fetchall()
                self.assertEqual([(row["journal"], row["cnt"]) for row in rows], [("Journal A", 1), ("Journal B", 1)])


if __name__ == "__main__":
    unittest.main()
