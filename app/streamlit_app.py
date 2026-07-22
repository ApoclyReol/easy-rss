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
    st.caption("本地 RSS 阅读器：自动获取新论文，在未读篮子主动更新个性化推荐，再进行阅读和分拣。")
    flush_notices()

    reader_tab, feed_tab, analytics_tab = st.tabs(["文献阅读", "订阅管理", "兴趣分析"])
    with reader_tab:
        render_reader_view()
    with feed_tab:
        render_feed_view()
    with analytics_tab:
        render_analytics_view()


if __name__ == "__main__":
    main()
