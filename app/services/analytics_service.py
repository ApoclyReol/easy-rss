from __future__ import annotations

from datetime import datetime, timedelta


def compute_interest_rate(interested_count: int, archived_count: int, hidden_count: int) -> float:
    numerator = int(interested_count or 0) + int(archived_count or 0)
    denominator = numerator + int(hidden_count or 0)
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def format_interest_rate(interested_count: int, archived_count: int, hidden_count: int) -> str:
    return f"{compute_interest_rate(interested_count, archived_count, hidden_count) * 100:.1f}%"


def build_expire_cutoff(days: int, now: datetime | None = None) -> str:
    base = now or datetime.now().astimezone()
    cutoff = base - timedelta(days=max(1, int(days)))
    return cutoff.isoformat(timespec="seconds")
