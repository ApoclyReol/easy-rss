from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from app.config import (
    AUTO_UPDATE_ENABLED,
    DEFAULT_HIDDEN_EXPIRE_DAYS,
    DEFAULT_PROMPT_TEMPLATE,
    SETTINGS_PATH,
)

REQUIRED_PROMPT_FIELDS = {"user_interest", "title", "authors", "journal", "summary", "content", "url"}


@dataclass
class LLMSettings:
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    user_interest: str = ""
    prompt_template: str = DEFAULT_PROMPT_TEMPLATE
    boolean_filter_expression: str = ""
    auto_update_enabled: bool = AUTO_UPDATE_ENABLED
    hidden_expire_days: int = DEFAULT_HIDDEN_EXPIRE_DAYS
    last_feed_update_started_at: str = ""
    last_feed_update_finished_at: str = ""
    last_feed_update_trigger: str = ""
    last_feed_update_total_feeds: int = 0
    last_feed_update_success_feeds: int = 0
    last_feed_update_total_new_items: int = 0
    last_feed_update_expired_items: int = 0
    last_feed_update_results: list[dict] | None = None
    data_maintenance_version: int = 0


def load_settings() -> LLMSettings:
    if not SETTINGS_PATH.exists():
        return LLMSettings()
    data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    return LLMSettings(
        base_url=str(data.get("base_url") or ""),
        api_key=str(data.get("api_key") or ""),
        model=str(data.get("model") or ""),
        user_interest=str(data.get("user_interest") or ""),
        prompt_template=str(data.get("prompt_template") or DEFAULT_PROMPT_TEMPLATE),
        boolean_filter_expression=str(data.get("boolean_filter_expression") or ""),
        auto_update_enabled=bool(data.get("auto_update_enabled", AUTO_UPDATE_ENABLED)),
        hidden_expire_days=max(1, int(data.get("hidden_expire_days") or DEFAULT_HIDDEN_EXPIRE_DAYS)),
        last_feed_update_started_at=str(data.get("last_feed_update_started_at") or ""),
        last_feed_update_finished_at=str(data.get("last_feed_update_finished_at") or ""),
        last_feed_update_trigger=str(data.get("last_feed_update_trigger") or ""),
        last_feed_update_total_feeds=int(data.get("last_feed_update_total_feeds") or 0),
        last_feed_update_success_feeds=int(data.get("last_feed_update_success_feeds") or 0),
        last_feed_update_total_new_items=int(data.get("last_feed_update_total_new_items") or 0),
        last_feed_update_expired_items=int(data.get("last_feed_update_expired_items") or 0),
        last_feed_update_results=list(data.get("last_feed_update_results") or []),
        data_maintenance_version=int(data.get("data_maintenance_version") or 0),
    )


def save_settings(settings: LLMSettings) -> None:
    missing = [field for field in sorted(REQUIRED_PROMPT_FIELDS) if f"{{{field}}}" not in settings.prompt_template]
    if missing:
        raise ValueError(f"prompt_template 缺少必要占位符：{', '.join(missing)}")
    payload = asdict(settings)
    payload["data_maintenance_version"] = max(0, int(payload.get("data_maintenance_version") or 0))
    SETTINGS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def mask_secret(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:3]}{'*' * max(4, len(value) - 6)}{value[-3:]}"
