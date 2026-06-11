from __future__ import annotations

from app.config import DATA_MAINTENANCE_VERSION
from app.repositories import (
    merge_duplicate_items,
    rebuild_stable_guids,
    split_low_signal_multi_feed_items,
    sync_all_item_journals,
)
from app.services.settings_service import load_settings, save_settings


def apply_data_maintenance() -> bool:
    settings = load_settings()
    if int(settings.data_maintenance_version or 0) >= DATA_MAINTENANCE_VERSION:
        return False

    sync_all_item_journals()
    merge_duplicate_items()
    split_low_signal_multi_feed_items()
    sync_all_item_journals()
    rebuild_stable_guids()
    merge_duplicate_items()

    settings.data_maintenance_version = DATA_MAINTENANCE_VERSION
    save_settings(settings)
    return True
