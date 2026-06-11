from __future__ import annotations

import pandas as pd
import streamlit as st

from app.repositories import count_items, list_feed_interest_stats
from app.services.analytics_service import compute_interest_rate, format_interest_rate
from app.services.settings_service import load_settings

DISPLAY_COLUMNS = [
    "期刊",
    "启用",
    "总条目",
    "未读",
    "隐藏",
    "感兴趣",
    "归档",
    "过期",
    "兴趣文献",
    "感兴趣率",
]
SORT_ONLY_COLUMNS = ["_interest_rate_value"]


def render_analytics_view() -> None:
    st.subheader("兴趣分析")

    overall = count_items()
    top_cols = st.columns(6)
    top_cols[0].metric("总条目", int(overall.get("total") or 0))
    top_cols[1].metric("未读", int(overall.get("unread") or 0))
    top_cols[2].metric("隐藏", int(overall.get("hidden") or 0))
    top_cols[3].metric("感兴趣", int(overall.get("interested") or 0))
    top_cols[4].metric("归档", int(overall.get("archived") or 0))
    top_cols[5].metric("过期", int(overall.get("expired") or 0))

    settings = load_settings()
    st.caption(
        f"隐藏文献会在每次启动自动更新或手动更新订阅后，按 last_seen_at 自动检查过期。"
        f"当前过期阈值：{int(settings.hidden_expire_days or 180)} 天；上次自动整理过期："
        f"{int(settings.last_feed_update_expired_items or 0)} 条。"
    )

    rows = list_feed_interest_stats(include_disabled=True)
    table_rows = []
    for row in rows:
        interested_count = int(row.get("interested_count") or 0)
        archived_count = int(row.get("archived_count") or 0)
        hidden_count = int(row.get("hidden_count") or 0)
        interest_rate_value = compute_interest_rate(interested_count, archived_count, hidden_count)
        table_rows.append(
            {
                "期刊": row["name"],
                "启用": bool(row.get("enabled")),
                "总条目": int(row.get("total_count") or 0),
                "未读": int(row.get("unread_count") or 0),
                "隐藏": hidden_count,
                "感兴趣": interested_count,
                "归档": archived_count,
                "过期": int(row.get("expired_count") or 0),
                "兴趣文献": interested_count + archived_count,
                "_interest_rate_value": interest_rate_value,
                "感兴趣率": format_interest_rate(interested_count, archived_count, hidden_count),
            }
        )

    table_rows.sort(key=lambda row: row["_interest_rate_value"], reverse=True)
    dataframe = pd.DataFrame(table_rows, columns=DISPLAY_COLUMNS + SORT_ONLY_COLUMNS)
    dataframe = dataframe.drop(columns=SORT_ONLY_COLUMNS, errors="ignore")
    st.dataframe(dataframe, hide_index=True, width="stretch")
