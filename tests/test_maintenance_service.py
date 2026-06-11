import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.db import get_conn, init_db
from app.repositories.feed_repository import insert_feed
from app.services.maintenance_service import apply_data_maintenance
from app.services.settings_service import load_settings


class MaintenanceServiceTest(unittest.TestCase):
    def test_apply_data_maintenance_runs_once(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rss_reader.sqlite3"
            settings_path = Path(tmpdir) / "settings.json"
            with patch("app.db.DB_PATH", db_path), patch("app.config.SETTINGS_PATH", settings_path), patch(
                "app.services.settings_service.SETTINGS_PATH", settings_path
            ):
                init_db()
                feed_id = insert_feed("Canonical Journal", "https://example.com/rss")
                with get_conn() as conn:
                    cur = conn.execute(
                        """
                        INSERT INTO items(stable_guid, title, title_norm, authors, journal, year, item_status)
                        VALUES('legacy-guid', 'Same Title', 'sametitle', 'Alice', 'Legacy Journal', '2026', 'interested')
                        """
                    )
                    item_id = int(cur.lastrowid)
                    conn.execute("INSERT INTO item_feeds(item_id, feed_id) VALUES(?, ?)", (item_id, feed_id))
                    conn.commit()

                self.assertTrue(apply_data_maintenance())
                self.assertFalse(apply_data_maintenance())

                settings = load_settings()
                self.assertEqual(settings.data_maintenance_version, 2)

                with get_conn() as conn:
                    row = conn.execute("SELECT journal, stable_guid FROM items WHERE id=?", (item_id,)).fetchone()
                self.assertEqual(row["journal"], "Canonical Journal")
                self.assertNotEqual(row["stable_guid"], "legacy-guid")


if __name__ == "__main__":
    unittest.main()
