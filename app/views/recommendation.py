from __future__ import annotations

from dataclasses import replace

import streamlit as st

from app.repositories import (
    batch_set_status,
    get_recommendation_summary,
    list_keywords,
    list_low_relevance_ids,
    reset_keyword_override,
    set_keyword_override,
)
from app.services.llm_service import run_pending_llm_review, test_llm_settings
from app.services.recommendation_service import rebuild_keyword_recommendations
from app.services.settings_service import load_settings, mask_secret, save_settings
from app.ui.notices import push_notice

READER_LAST_ACTION_KEY = "reader_last_action"


def _render_summary() -> None:
    summary = get_recommendation_summary()
    cols = st.columns(4)
    for col, label, key in zip(cols, ("高相关", "待判断", "低相关", "未评分"), ("high", "pending", "low", "unscored")):
        col.metric(label, summary[key])
    model = summary.get("model")
    if model:
        if model.get("error_message"):
            st.warning(str(model["error_message"]))
        else:
            st.caption(
                f"模型更新：{model['created_at']} · 正样本 {model['positive_count']} · "
                f"负样本 {model['negative_count']} · 当时未读 {model['unread_count']}"
            )
    else:
        st.caption("尚未建立关键词推荐模型。新论文会保持未评分，直到主动更新推荐。")


def _render_keyword_editor() -> None:
    keywords = list_keywords(limit=100)
    if keywords:
        st.dataframe(
            [
                {
                    "关键词": row["keyword"],
                    "方向": "正向" if float(row.get("effective_weight") or 0) > 0 else "负向",
                    "有效权重": round(float(row.get("effective_weight") or 0), 3),
                    "正样本": int(row.get("positive_count") or 0),
                    "负样本": int(row.get("negative_count") or 0),
                    "人工修正": "是" if row.get("manual_weight") is not None or row.get("is_disabled") else "否",
                    "已禁用": "是" if row.get("is_disabled") else "否",
                }
                for row in keywords
            ],
            width="stretch",
            hide_index=True,
        )

    options = [row["keyword"] for row in keywords]
    with st.form("keyword_override_form"):
        selected = st.selectbox("选择已有关键词", ["", *options])
        new_keyword = st.text_input("或输入新关键词")
        direction_label = st.selectbox("人工方向", ["正向", "负向"])
        weight = st.number_input("人工权重", min_value=0.1, max_value=5.0, value=1.0, step=0.1)
        disabled = st.checkbox("禁用这个关键词")
        save_override = st.form_submit_button("保存修正")
    target = new_keyword.strip() or selected
    if save_override:
        if not target:
            st.error("请选择或输入关键词。")
        else:
            set_keyword_override(
                target,
                direction="positive" if direction_label == "正向" else "negative",
                weight=float(weight),
                disabled=disabled,
            )
            push_notice(f"已保存关键词修正：{target}", "success")
            st.rerun()

    if options:
        reset_cols = st.columns([2, 1, 4])
        reset_target = reset_cols[0].selectbox("恢复自动权重", options, key="keyword_reset_target")
        if reset_cols[1].button("恢复", key="keyword_reset_button"):
            reset_keyword_override(reset_target)
            push_notice(f"已恢复自动权重：{reset_target}", "info")
            st.rerun()


def _render_llm_settings() -> None:
    settings = load_settings()
    with st.form("recommendation_llm_settings"):
        base_url = st.text_input("base_url", value=settings.base_url, placeholder="https://api.openai.com/v1")
        api_key = st.text_input("api_key", value=settings.api_key, type="password")
        model = st.text_input("model", value=settings.model, placeholder="gpt-4.1-mini")
        user_interest = st.text_area("研究兴趣补充描述", value=settings.user_interest, height=100)
        save_clicked = st.form_submit_button("保存 LLM 配置")
    if save_clicked:
        updated = replace(
            settings,
            base_url=base_url.strip(),
            api_key=api_key.strip(),
            model=model.strip(),
            user_interest=user_interest.strip(),
        )
        save_settings(updated)
        push_notice("LLM 配置已保存到本地", "success")
        masked = mask_secret(updated.api_key)
        if masked:
            st.caption(f"已保存 API Key：{masked}")
        st.rerun()

    if st.button("测试 API 连接", key="recommendation_llm_test"):
        result = test_llm_settings(load_settings())
        (st.success if result.ok else st.error)(result.connection_message)
        st.caption(f"认证：{result.auth_message} · 模型：{result.model_message}")


def render_recommendation_panel(*, q: str, feed_ids: list[int]) -> None:
    st.markdown("### 个性化推荐")
    st.caption("推荐只在你点击按钮时运行；RSS 自动更新不会自动评分或调用 LLM。")
    _render_summary()

    action_cols = st.columns([1.2, 1.2, 4])
    if action_cols[0].button("更新关键词推荐", type="primary", key="rebuild_keyword_recommendations"):
        try:
            with st.spinner("正在根据最新人工选择重建关键词模型……"):
                result = rebuild_keyword_recommendations()
            push_notice(
                f"推荐已更新：高相关 {result.high_count}，待判断 {result.pending_count}，低相关 {result.low_count}",
                "success",
            )
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    if action_cols[1].button("LLM 复核待判断", key="run_pending_llm_review"):
        with st.spinner("正在复核待判断论文……"):
            result = run_pending_llm_review(load_settings())
        push_notice(
            f"LLM 复核完成：升为高相关 {result.high}，降为低相关 {result.low}，失败 {result.failed}",
            "success" if result.failed == 0 else "warning",
        )
        st.rerun()

    low_ids = list_low_relevance_ids(q=q, feed_ids=feed_ids)
    with st.expander(f"批量处理低相关（当前筛选范围 {len(low_ids)} 条）"):
        st.warning("只会隐藏当前订阅源和搜索条件下的低相关未读论文，可通过“撤回”恢复。")
        confirmed = st.checkbox("我确认隐藏这些低相关论文", key="confirm_hide_low")
        if st.button("一键隐藏低相关", disabled=not confirmed or not low_ids, key="hide_low_relevance"):
            changed = batch_set_status(low_ids, status="hidden")
            st.session_state[READER_LAST_ACTION_KEY] = {
                "kind": "batch",
                "item_ids": low_ids,
                "from_status": "unread",
                "to_status": "hidden",
                "count": changed,
            }
            push_notice(f"已隐藏 {changed} 条低相关论文", "warning")
            st.rerun()

    with st.expander("推荐设置与关键词词表"):
        keyword_tab, llm_tab = st.tabs(["关键词词表", "LLM 配置"])
        with keyword_tab:
            _render_keyword_editor()
        with llm_tab:
            _render_llm_settings()
