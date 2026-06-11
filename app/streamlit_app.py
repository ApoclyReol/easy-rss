from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import APP_TITLE
from app.db import init_db
from app.services.auto_update_service import run_auto_update_fragment, should_mount_auto_update_fragment
from app.services.maintenance_service import apply_data_maintenance
from app.ui.notices import flush_notices
from app.views.analytics import render_analytics_view
from app.views.feeds import render_feed_view
from app.views.filtering import render_filter_view
from app.views.reader import render_reader_view


def init_app() -> None:
    init_db()
    apply_data_maintenance()


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    init_app()
    if should_mount_auto_update_fragment():
        run_auto_update_fragment()
    st.title(APP_TITLE)
    st.caption("本地 RSS 阅读器：推荐工作流：订阅管理-导入订阅链接-手动更新; 筛选工具-布尔筛选-隐藏未命中文献；\n文献阅读-选择篮子-开始浏览新的订阅")
    flush_notices()

    reader_tab, feed_tab, filter_tab, analytics_tab = st.tabs(["文献阅读", "订阅管理", "筛选工具", "兴趣分析"])
    with reader_tab:
        render_reader_view()
    with feed_tab:
        render_feed_view()
    with filter_tab:
        render_filter_view()
    with analytics_tab:
        render_analytics_view()


if __name__ == "__main__":
    main()
