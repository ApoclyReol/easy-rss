from __future__ import annotations

import html
import json

import streamlit as st

from app import rss_core
from app.repositories import (
    batch_set_status,
    count_items,
    count_items_for_view,
    list_feeds,
    list_items,
    set_item_status,
)
from app.ui.notices import push_notice
from app.views.recommendation import render_recommendation_panel

QUICK_REVIEW_CURSOR_KEY = "reader_quick_review_cursor"
QUICK_REVIEW_SIGNATURE_KEY = "reader_quick_review_signature"
READER_STATUS_KEY = "reader_status"
READER_FEED_KEY = "reader_feed_id"
READER_QUERY_KEY = "reader_query"
READER_LIMIT_KEY = "reader_limit"
READER_FEED_SNAPSHOT_KEY = "reader_feed_id_snapshot"
READER_QUERY_SNAPSHOT_KEY = "reader_query_snapshot"
READER_LIMIT_SNAPSHOT_KEY = "reader_limit_snapshot"
READER_LAST_ACTION_KEY = "reader_last_action"


def _snapshot_reader_filters() -> None:
    st.session_state[READER_FEED_SNAPSHOT_KEY] = st.session_state.get(READER_FEED_KEY, None)
    st.session_state[READER_QUERY_SNAPSHOT_KEY] = st.session_state.get(READER_QUERY_KEY, "")
    st.session_state[READER_LIMIT_SNAPSHOT_KEY] = int(st.session_state.get(READER_LIMIT_KEY, 100))


def _remember_single_status_change(item: dict, next_status: str) -> None:
    st.session_state[READER_LAST_ACTION_KEY] = {
        "kind": "single",
        "item_id": int(item["id"]),
        "title": item.get("title") or "Untitled",
        "from_status": item["item_status"],
        "to_status": next_status,
    }


def _undo_last_action() -> bool:
    action = st.session_state.get(READER_LAST_ACTION_KEY)
    if not action:
        return False

    if action["kind"] == "single":
        set_item_status(int(action["item_id"]), action["from_status"])
        push_notice(f"已撤回《{action['title']}》的操作", "info")
    elif action["kind"] == "batch":
        batch_set_status(action["item_ids"], action["from_status"])
        push_notice(f"已撤回批量操作，恢复 {action['count']} 条论文", "info")
    else:
        return False

    st.session_state.pop(READER_LAST_ACTION_KEY, None)
    _snapshot_reader_filters()
    return True


def _last_action_label() -> str:
    return "撤回"


def _recommendation_caption(item: dict) -> str:
    labels = {"high": "高相关", "pending": "待判断", "low": "低相关"}
    tier = item.get("final_tier")
    if not tier:
        return "未评分"
    parts = [labels.get(tier, str(tier))]
    if item.get("keyword_score") is not None:
        parts.append(str(int(round(float(item["keyword_score"])))))
    parts.append("LLM 复核" if item.get("llm_tier") else "关键词")
    try:
        matched = json.loads(item.get("matched_keywords") or "[]")
    except (TypeError, ValueError):
        matched = []
    names = [str(row.get("keyword")) for row in matched[:3] if isinstance(row, dict) and row.get("keyword")]
    if names:
        parts.append("、".join(names))
    return " · ".join(parts)


def _render_title_link(title: str, link: str | None, *, prefix: str = "", level: str = "body") -> None:
    safe_title = html.escape(title)
    safe_prefix = html.escape(prefix)
    if not link:
        if level == "heading":
            st.markdown(f"### {safe_prefix}{safe_title}")
        else:
            st.markdown(f"**{safe_prefix}{safe_title}**")
        return

    wrapper = "h3" if level == "heading" else "div"
    css_class = "reader-title-link reader-title-link-heading" if level == "heading" else "reader-title-link"
    st.markdown(
        f"""
        <{wrapper} class="reader-title-wrap">
          <a class="{css_class}" href="{html.escape(link, quote=True)}" target="_blank" rel="noopener noreferrer">
            {safe_prefix}{safe_title}
          </a>
        </{wrapper}>
        """,
        unsafe_allow_html=True,
    )


def render_item_card(item: dict) -> None:
    title = item["title"] or "Untitled"
    prefix = "⭐ " if item["item_status"] == "interested" else ("✓ " if item["item_status"] == "archived" else "")
    display_journal = rss_core.normalize_journal_name(item.get("journal"))
    with st.container(border=True):
        _render_title_link(title, item.get("link"), prefix=prefix, level="body")
        if display_journal:
            st.caption(display_journal)
        if item["item_status"] == "unread":
            st.caption(_recommendation_caption(item))
        cols = st.columns([0.9, 0.9, 0.9, 6])

        primary_label = ""
        primary_next_status = ""
        primary_notice = ""
        if item["item_status"] == "unread":
            primary_label = "感兴趣"
            primary_next_status = "interested"
            primary_notice = "标记为感兴趣"
        elif item["item_status"] == "interested":
            primary_label = "归档"
            primary_next_status = "archived"
            primary_notice = "归档"
        elif item["item_status"] == "archived":
            primary_label = "恢复兴趣"
            primary_next_status = "interested"
            primary_notice = "恢复到感兴趣"
        elif item["item_status"] in {"hidden", "expired"}:
            primary_label = "恢复到未读"
            primary_next_status = "unread"
            primary_notice = "恢复显示"

        if primary_label and cols[0].button(primary_label, key=f"primary-{item['id']}", width="content"):
            _remember_single_status_change(item, primary_next_status)
            set_item_status(item["id"], primary_next_status)
            push_notice(f"《{title}》已{primary_notice}", "success")
            _snapshot_reader_filters()
            st.rerun()

        secondary_label = ""
        secondary_next_status = ""
        secondary_notice = ""
        if item["item_status"] == "interested":
            secondary_label = "恢复未读"
            secondary_next_status = "unread"
            secondary_notice = "恢复到未读"
        elif item["item_status"] == "archived":
            secondary_label = "隐藏"
            secondary_next_status = "hidden"
            secondary_notice = "隐藏"
        elif item["item_status"] not in {"hidden", "expired"}:
            secondary_label = "隐藏"
            secondary_next_status = "hidden"
            secondary_notice = "隐藏"

        if secondary_label and cols[1].button(secondary_label, key=f"secondary-{item['id']}", width="content"):
            _remember_single_status_change(item, secondary_next_status)
            set_item_status(item["id"], secondary_next_status)
            push_notice(f"《{title}》已{secondary_notice}", "warning" if secondary_next_status == "hidden" else "success")
            _snapshot_reader_filters()
            st.rerun()

        if item["item_status"] == "interested" and cols[2].button("隐藏", key=f"tertiary-hide-{item['id']}", width="content"):
            _remember_single_status_change(item, "hidden")
            set_item_status(item["id"], "hidden")
            push_notice(f"《{title}》已隐藏", "warning")
            _snapshot_reader_filters()
            st.rerun()


def _render_basket_cards(counts: dict) -> str:
    allowed_statuses = {"unread", "interested", "archived", "hidden", "expired"}
    if READER_STATUS_KEY not in st.session_state or st.session_state[READER_STATUS_KEY] not in allowed_statuses:
        st.session_state[READER_STATUS_KEY] = "unread"

    st.markdown(
        """
        <style>
        div[data-testid="stButton"] > button[kind="primary"] {
            background-color: #2563eb;
            border-color: #2563eb;
            color: white;
        }
        div[data-testid="stButton"] > button[kind="primary"]:hover {
            background-color: #1d4ed8;
            border-color: #1d4ed8;
            color: white;
        }
        .reader-title-wrap {
            margin: 0 0 0.15rem 0;
        }
        .reader-title-link {
            color: inherit !important;
            text-decoration: none !important;
            font-weight: 650;
            line-height: 1.45;
        }
        .reader-title-link:hover {
            color: inherit !important;
            text-decoration: underline !important;
            text-decoration-color: rgba(148, 163, 184, 0.55) !important;
            text-underline-offset: 0.14em;
        }
        .reader-title-link:visited {
            color: inherit !important;
        }
        .reader-title-link-heading {
            font-size: 1.05em;
            font-weight: 700;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    cards = [
        ("unread", "未读", counts["unread"]),
        ("interested", "感兴趣", counts["interested"]),
        ("archived", "已归档", counts["archived"]),
        ("hidden", "已隐藏", counts["hidden"]),
        ("expired", "已过期", counts["expired"]),
    ]
    current_status = st.session_state[READER_STATUS_KEY]
    cols = st.columns(len(cards))

    for col, (status, label, value) in zip(cols, cards):
        with col:
            button_label = f"{label}\n{value}"
            if st.button(
                button_label,
                key=f"basket-card-{status}",
                width="stretch",
                type="primary" if current_status == status else "secondary",
            ):
                st.session_state[READER_STATUS_KEY] = status
                _snapshot_reader_filters()
                st.rerun()

    return st.session_state[READER_STATUS_KEY]


def _advance_quick_review_cursor(current_index: int, total_count: int, *, remove_from_current_view: bool) -> None:
    if total_count <= 1:
        st.session_state[QUICK_REVIEW_CURSOR_KEY] = 0
        return
    if remove_from_current_view:
        st.session_state[QUICK_REVIEW_CURSOR_KEY] = min(current_index, total_count - 2)
        return
    st.session_state[QUICK_REVIEW_CURSOR_KEY] = min(current_index + 1, total_count - 1)


def _render_quick_review_item(item: dict, current_index: int, total_count: int, current_status: str) -> None:
    title = item["title"] or "Untitled"
    prefix = "⭐ " if item["item_status"] == "interested" else ("✓ " if item["item_status"] == "archived" else "")
    display_summary = rss_core.clean_summary_text(item.get("summary"))
    meta = rss_core.extract_summary_metadata(item.get("summary"))
    has_summary_metadata_only = bool(item.get("summary")) and not display_summary and any(meta.values())
    has_no_rss_abstract = not display_summary
    display_journal = rss_core.normalize_journal_name(item.get("journal"))

    with st.container(border=True):
        st.caption(f"第 {current_index + 1} / {total_count} 条")
        _render_title_link(title, item.get("link"), prefix=prefix, level="heading")
        if display_journal:
            st.caption(display_journal)
        if item["item_status"] == "unread":
            st.caption(_recommendation_caption(item))

        if display_summary:
            st.write(display_summary)
        elif has_summary_metadata_only:
            st.info("这个 RSS 条目未提供摘要，当前只有发布日期、来源和作者等元信息。")
        elif has_no_rss_abstract:
            st.info("这个 RSS 链接未提供摘要。")

        nav_cols = st.columns([0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 5])
        if nav_cols[0].button("上一条", disabled=current_index <= 0, key=f"quick-prev-{item['id']}", width="content"):
            st.session_state[QUICK_REVIEW_CURSOR_KEY] = max(0, current_index - 1)
            _snapshot_reader_filters()
            st.rerun()

        primary_label = ""
        primary_next_status = ""
        primary_notice = ""
        remove_from_current_view = False
        if item["item_status"] == "unread":
            primary_label = "感兴趣"
            primary_next_status = "interested"
            primary_notice = "标记为感兴趣"
            remove_from_current_view = current_status == "unread"
        elif item["item_status"] == "interested":
            primary_label = "归档"
            primary_next_status = "archived"
            primary_notice = "归档"
            remove_from_current_view = current_status == "interested"
        elif item["item_status"] == "archived":
            primary_label = "恢复兴趣"
            primary_next_status = "interested"
            primary_notice = "恢复到感兴趣"
            remove_from_current_view = current_status == "archived"
        elif item["item_status"] in {"hidden", "expired"}:
            primary_label = "恢复未读"
            primary_next_status = "unread"
            primary_notice = "恢复显示"
            remove_from_current_view = current_status in {"hidden", "expired"}

        if primary_label and nav_cols[1].button(primary_label, key=f"quick-primary-{item['id']}", width="content"):
            _advance_quick_review_cursor(current_index, total_count, remove_from_current_view=remove_from_current_view)
            _remember_single_status_change(item, primary_next_status)
            set_item_status(item["id"], primary_next_status)
            push_notice(f"《{title}》已{primary_notice}", "success")
            _snapshot_reader_filters()
            st.rerun()

        secondary_label = ""
        secondary_next_status = ""
        secondary_notice = ""
        secondary_remove = False
        if item["item_status"] == "interested":
            secondary_label = "恢复未读"
            secondary_next_status = "unread"
            secondary_notice = "恢复到未读"
            secondary_remove = current_status == "interested"
        elif item["item_status"] == "archived":
            secondary_label = "隐藏"
            secondary_next_status = "hidden"
            secondary_notice = "隐藏"
            secondary_remove = current_status == "archived"
        elif item["item_status"] not in {"hidden", "expired"}:
            secondary_label = "隐藏"
            secondary_next_status = "hidden"
            secondary_notice = "隐藏"
            secondary_remove = current_status in {"unread", "interested"}

        if secondary_label and nav_cols[2].button(secondary_label, key=f"quick-secondary-{item['id']}", width="content"):
            _advance_quick_review_cursor(current_index, total_count, remove_from_current_view=secondary_remove)
            _remember_single_status_change(item, secondary_next_status)
            set_item_status(item["id"], secondary_next_status)
            push_notice(f"《{title}》已{secondary_notice}", "warning" if secondary_next_status == "hidden" else "success")
            _snapshot_reader_filters()
            st.rerun()

        if item["item_status"] == "interested" and nav_cols[3].button("隐藏", key=f"quick-tertiary-hide-{item['id']}", width="content"):
            _advance_quick_review_cursor(current_index, total_count, remove_from_current_view=current_status == "interested")
            _remember_single_status_change(item, "hidden")
            set_item_status(item["id"], "hidden")
            push_notice(f"《{title}》已隐藏", "warning")
            _snapshot_reader_filters()
            st.rerun()

        if item.get("link"):
            nav_cols[4].link_button("打开原文", item["link"], width="content")

        if nav_cols[5].button("下一条", disabled=current_index >= total_count - 1, key=f"quick-next-{item['id']}", width="content"):
            st.session_state[QUICK_REVIEW_CURSOR_KEY] = min(total_count - 1, current_index + 1)
            _snapshot_reader_filters()
            st.rerun()

        if item.get("doi"):
            nav_cols[6].caption(f"DOI: {item['doi']}")


def render_reader_view() -> None:
    st.subheader("阅读")
    feeds = list_feeds(include_disabled=True)
    counts = count_items()
    status = _render_basket_cards(counts)

    filter_cols = st.columns([1.4, 1.8, 0.8])
    feed_label_map = {None: "全部订阅"}
    feed_label_map.update(
        {int(feed["id"]): feed["name"] for feed in feeds}
    )
    feed_option_ids = [None, *[int(feed["id"]) for feed in feeds]]
    saved_feed_id = st.session_state.get(READER_FEED_SNAPSHOT_KEY, None)
    if saved_feed_id not in feed_label_map:
        saved_feed_id = None
    if READER_FEED_KEY not in st.session_state or st.session_state[READER_FEED_KEY] not in feed_label_map:
        st.session_state[READER_FEED_KEY] = saved_feed_id
    if READER_QUERY_KEY not in st.session_state:
        st.session_state[READER_QUERY_KEY] = st.session_state.get(READER_QUERY_SNAPSHOT_KEY, "")
    if READER_LIMIT_KEY not in st.session_state:
        st.session_state[READER_LIMIT_KEY] = int(st.session_state.get(READER_LIMIT_SNAPSHOT_KEY, 100))

    feed_id = filter_cols[0].selectbox(
        "订阅源",
        feed_option_ids,
        key=READER_FEED_KEY,
        format_func=lambda option_id: feed_label_map.get(option_id, "全部订阅"),
    )
    q = filter_cols[1].text_input("搜索", placeholder="题名 / 作者 / 摘要 / 期刊 / DOI", key=READER_QUERY_KEY)
    limit = filter_cols[2].number_input(
        "显示数量",
        min_value=20,
        max_value=500,
        step=20,
        key=READER_LIMIT_KEY,
    )

    selected_feed_ids = [feed_id] if feed_id else []
    if status == "unread":
        render_recommendation_panel(q=q, feed_ids=selected_feed_ids)

    action_cols = st.columns([0.9, 0.9, 6])
    if action_cols[0].button("刷新列表", width="content"):
        push_notice("列表已刷新", "info")
        _snapshot_reader_filters()
        st.rerun()
    if action_cols[1].button(_last_action_label(), disabled=READER_LAST_ACTION_KEY not in st.session_state, width="content"):
        if _undo_last_action():
            st.rerun()

    matched_count = count_items_for_view(status=status, q=q, feed_ids=selected_feed_ids)
    items = list_items(status=status, q=q, feed_ids=selected_feed_ids, limit=int(limit))
    signature = (status, feed_id, q.strip(), int(limit))
    if st.session_state.get(QUICK_REVIEW_SIGNATURE_KEY) != signature:
        st.session_state[QUICK_REVIEW_SIGNATURE_KEY] = signature
        st.session_state[QUICK_REVIEW_CURSOR_KEY] = 0

    st.caption(f"当前篮子共有 {matched_count} 条，当前显示前 {len(items)} 条。搜索和筛选作用于全部结果")
    list_tab, quick_tab = st.tabs(["列表浏览", "快速处理"])

    with list_tab:
        if not items:
            st.info("这个篮子里当前没有文献。")
        else:
            for item in items:
                render_item_card(item)

    with quick_tab:
        if not items:
            st.info("这个篮子里当前没有文献。")
        else:
            current_index = int(st.session_state.get(QUICK_REVIEW_CURSOR_KEY, 0))
            if current_index >= len(items):
                current_index = max(0, len(items) - 1)
                st.session_state[QUICK_REVIEW_CURSOR_KEY] = current_index
            _render_quick_review_item(items[current_index], current_index, len(items), status)
