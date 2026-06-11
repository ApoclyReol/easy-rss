import unittest

from app.rss_core import canonicalize_link, entry_to_item, stable_guid


class RSSCoreTest(unittest.TestCase):
    def test_canonicalize_link_preserves_cnki_query_parameters(self):
        link = "https://kns.cnki.net/kcms2/article/abstract?v=abc123&uniplatform=NZKPT"
        self.assertEqual(
            canonicalize_link(link),
            "https://kns.cnki.net/kcms2/article/abstract?v=abc123&uniplatform=NZKPT",
        )

    def test_canonicalize_link_strips_non_cnki_query_parameters(self):
        link = "https://example.com/article?id=123&utm_source=rss"
        self.assertEqual(canonicalize_link(link), "https://example.com/article")

    def test_entry_to_item_prefers_feed_name_as_canonical_journal(self):
        entry = {
            "title": "Example Title",
            "summary": "Source: Some Journal, Volume 10 Author(s): A",
            "link": "https://example.com/article?id=123",
        }
        item = entry_to_item(entry, "Canonical Journal")
        self.assertEqual(item["journal"], "Canonical Journal")

    def test_stable_guid_no_longer_depends_on_journal_name(self):
        guid_a, _ = stable_guid("Same Title", "Journal A", "2026", "Alice", "")
        guid_b, _ = stable_guid("Same Title", "Journal B", "2026", "Alice", "")
        self.assertEqual(guid_a, guid_b)


if __name__ == "__main__":
    unittest.main()
