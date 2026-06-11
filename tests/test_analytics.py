import unittest
from datetime import datetime

from app.services.analytics_service import build_expire_cutoff, compute_interest_rate, format_interest_rate


class AnalyticsServiceTest(unittest.TestCase):
    def test_compute_interest_rate_uses_interested_and_archived_over_processed(self):
        rate = compute_interest_rate(interested_count=3, archived_count=2, hidden_count=5)
        self.assertAlmostEqual(rate, 0.5)

    def test_compute_interest_rate_returns_zero_when_no_processed_items(self):
        self.assertEqual(compute_interest_rate(0, 0, 0), 0.0)

    def test_format_interest_rate_returns_percentage_text(self):
        self.assertEqual(format_interest_rate(1, 1, 2), "50.0%")

    def test_build_expire_cutoff_subtracts_days(self):
        now = datetime.fromisoformat("2026-06-07T12:00:00+08:00")
        self.assertEqual(build_expire_cutoff(180, now=now), "2025-12-09T12:00:00+08:00")


if __name__ == "__main__":
    unittest.main()
