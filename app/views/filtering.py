from __future__ import annotations

from dataclasses import asdict

import streamlit as st

from app.repositories import batch_set_status, get_items_by_ids, list_feeds, list_items
from app.services.filtering import BooleanExpressionError, filter_items_by_expression
from app.services.llm_service import run_llm_preview, test_llm_settings
from app.services.settings_service import LLMSettings, load_settings, mask_secret, save_settings
from app.ui.notices import push_notice

BOOLEAN_PREVIEW_KEY = "boolean_filter_preview"
LLM_PREVIEW_KEY = "llm_filter_preview"
BOOLEAN_EXPRESSION_KEY = "boolean_expression"


def _feed_options():
    feeds = list_feeds(include_disabled=True)
    return feeds


def _render_boolean_preview_cards(items: list[dict]) -> None:
    for item in items:
        title = str(item.get("title") or "Untitled")
        journal = str(item.get("journal") or "")
        with st.container(border=True):
            if item.get("link"):
                st.markdown(f"**[{title}]({item['link']})**")
            else:
                st.markdown(f"**{title}**")
            if journal:
                st.caption(journal)


def _render_llm_preview_cards(results: list[dict]) -> None:
    for row in results:
        title = str(row.get("title") or "Untitled")
        journal = str(row.get("journal") or "")
        status_label = "相关" if row.get("relevant") else ("不相关" if row.get("relevant") is False else "失败")
        with st.container(border=True):
            st.markdown(f"**{title}**")
            meta = " · ".join(part for part in [journal, status_label] if part)
            if meta:
                st.caption(meta)
            if row.get("error"):
                st.caption(str(row["error"]))


def _multi_feed_and_limit_controls(prefix: str, limit_label: str) -> tuple[list[int], int]:
    feeds = _feed_options()
    cols = st.columns([1.8, 0.8])
    selected_feeds = cols[0].multiselect(
        "订阅源",
        feeds,
        key=f"{prefix}_feeds",
        format_func=lambda feed: feed["name"],
    )
    limit = cols[1].number_input(limit_label, min_value=20, max_value=500, value=100, step=20, key=f"{prefix}_limit")
    return [int(feed["id"]) for feed in selected_feeds], int(limit)


def render_boolean_filter_panel() -> None:
    st.markdown("### 布尔筛选")
    settings = load_settings()
    if BOOLEAN_EXPRESSION_KEY not in st.session_state:
        st.session_state[BOOLEAN_EXPRESSION_KEY] = settings.boolean_filter_expression

    st.caption('支持 `AND` / `OR` / `NOT`、括号、引号短语')
    expression = st.text_area(
        "布尔表达式",
        height=100,
        placeholder='("knowledge graph" OR LLM) AND NOT survey',
        key=BOOLEAN_EXPRESSION_KEY,
    )
    feed_ids, limit = _multi_feed_and_limit_controls("boolean", "显示结果数")
    status = "unread"

    save_cols = st.columns([1, 4])
    if save_cols[0].button("保存规则", disabled=not expression.strip(), key="boolean_save_preset"):
        settings.boolean_filter_expression = expression.strip()
        save_settings(settings)
        push_notice("已更新布尔规则", "success")
        st.rerun()

    preview_col, preview_miss_col, apply_col = st.columns([1, 1, 1])
    preview_clicked = preview_col.button("预览匹配结果", key="boolean_preview")
    preview_unmatched_clicked = preview_miss_col.button("预览未命中结果", key="boolean_preview_unmatched")
    apply_clicked = apply_col.button("隐藏未命中结果", key="boolean_apply")

    if preview_clicked or preview_unmatched_clicked or apply_clicked:
        if not expression.strip():
            st.error("请先填写布尔表达式。")
        else:
            try:
                items = list_items(status=status, feed_ids=feed_ids, limit=None)
                matched = filter_items_by_expression(items, expression)
                matched_ids = {item["id"] for item in matched}
                unmatched = [item for item in items if item["id"] not in matched_ids]
                st.session_state[BOOLEAN_PREVIEW_KEY] = {
                    "expression": expression,
                    "feed_ids": feed_ids,
                    "display_limit": limit,
                    "active_preview": "matched" if preview_clicked else "unmatched",
                    "matched_ids": [item["id"] for item in matched],
                    "unmatched_ids": [item["id"] for item in unmatched],
                }
                if apply_clicked:
                    changed = batch_set_status([item["id"] for item in unmatched], status="hidden")
                    st.success(f"已隐藏 {changed} 条未命中文献。")
                    push_notice(f"布尔筛选已隐藏 {changed} 条未命中文献", "success")
                    st.rerun()
            except BooleanExpressionError as exc:
                st.error(f"表达式非法：{exc}")

    preview = st.session_state.get(BOOLEAN_PREVIEW_KEY)
    if preview:
        show_unmatched = preview.get("active_preview") == "unmatched"
        preview_ids = preview["unmatched_ids"] if show_unmatched else preview["matched_ids"]
        preview_items = get_items_by_ids(preview_ids)
        display_limit = int(preview.get("display_limit") or 100)
        shown_items = preview_items[:display_limit]
        label = "未命中" if show_unmatched else "命中"
        st.caption(f"本次共{label} {len(preview_items)} 条，当前展示前 {len(shown_items)} 条。")
        if preview_items:
            _render_boolean_preview_cards(shown_items)
        else:
            st.info(f"当前范围内没有{label}结果。")


def render_llm_filter_panel() -> None:
    st.markdown("### LLM 筛选（测试中）")
    settings = load_settings()

    with st.expander("LLM 配置", expanded=True):
        with st.form("llm_settings_form"):
            base_url = st.text_input("base_url", value=settings.base_url, placeholder="https://api.openai.com/v1")
            api_key = st.text_input("api_key", value=settings.api_key, type="password")
            model = st.text_input("model", value=settings.model, placeholder="gpt-4.1-mini")
            user_interest = st.text_area("研究兴趣描述", value=settings.user_interest, height=120)
            prompt_template = st.text_area("prompt_template", value=settings.prompt_template, height=320)
            save_clicked = st.form_submit_button("保存本地配置")
        if save_clicked:
            try:
                settings = LLMSettings(
                    base_url=base_url.strip(),
                    api_key=api_key.strip(),
                    model=model.strip(),
                    user_interest=user_interest.strip(),
                    prompt_template=prompt_template,
                )
                save_settings(settings)
                st.success("配置已保存到本地。")
                masked = mask_secret(settings.api_key)
                if masked:
                    st.caption(f"已保存 API Key：{masked}")
                push_notice("LLM 配置已保存到本地", "success")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

        test_button = st.button("测试 API 连接", key="llm_test_button")
        if test_button:
            test_result = test_llm_settings(load_settings())
            if test_result.ok:
                st.success("测试成功。")
            else:
                st.error("测试失败。")
            st.write(f"连接：{test_result.connection_message}")
            st.write(f"认证：{test_result.auth_message}")
            st.write(f"模型：{test_result.model_message}")
            if test_result.raw_response_preview:
                st.caption(f"响应预览：{test_result.raw_response_preview}")

    st.caption("LLM 筛选只处理当前未读文献。可多选订阅源，先预览，再确认隐藏不相关结果。")
    feed_ids, limit = _multi_feed_and_limit_controls("llm", "显示结果数")
    run_preview = st.button("运行 LLM 预览", type="primary", key="llm_preview_button")

    if run_preview:
        current_settings = load_settings()
        items = list_items(status="unread", feed_ids=feed_ids, limit=limit)
        if not items:
            st.info("当前范围内没有可处理文献。")
        else:
            with st.spinner(f"正在判定 {len(items)} 条文献……"):
                preview_results = run_llm_preview(items, current_settings)
            item_map = {int(item["id"]): item for item in items}
            st.session_state[LLM_PREVIEW_KEY] = {
                "feed_ids": feed_ids,
                "limit": limit,
                "results": [
                    {
                        **asdict(result),
                        "journal": str(item_map.get(int(result.item_id), {}).get("journal") or ""),
                    }
                    for result in preview_results
                ],
            }

    preview = st.session_state.get(LLM_PREVIEW_KEY)
    if preview:
        results = preview["results"]
        success_rows = [row for row in results if row["error"] is None]
        non_relevant_ids = [row["item_id"] for row in success_rows if row["relevant"] is False]
        failed_rows = [row for row in results if row["error"]]

        c1, c2, c3 = st.columns(3)
        c1.metric("总条目", len(results))
        c2.metric("判定为不相关", len(non_relevant_ids))
        c3.metric("失败", len(failed_rows))

        _render_llm_preview_cards(results[: int(preview.get("limit") or 100)])

        if st.button("确认隐藏所有不相关结果", disabled=not non_relevant_ids, key="llm_confirm_hide"):
            changed = batch_set_status(non_relevant_ids, status="hidden")
            st.success(f"已隐藏 {changed} 条不相关文献。")
            push_notice(f"LLM 筛选已隐藏 {changed} 条不相关文献", "success")
            st.rerun()


def render_filter_view() -> None:
    st.subheader("筛选")
    boolean_tab, llm_tab = st.tabs(["布尔筛选", "LLM 筛选"])
    with boolean_tab:
        render_boolean_filter_panel()
    with llm_tab:
        render_llm_filter_panel()
