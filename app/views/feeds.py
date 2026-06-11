from __future__ import annotations

from datetime import datetime

import streamlit as st

from app.repositories import delete_feed, delete_feeds, list_feeds, update_feed_meta
from app.services.feed_service import add_feed, record_update_summary, run_data_refresh, validate_feed_input
from app.services.import_service import bulk_import_feeds, extract_feeds_from_text
from app.services.settings_service import load_settings
from app.ui.notices import push_notice


def render_result(result) -> None:
    if result.error:
        st.error(f"{result.feed_name or result.feed_id}：更新失败｜{result.error}")
        push_notice(f"{result.feed_name or result.feed_id} 更新失败", "error")
    else:
        st.success(
            f"{result.feed_name}：抓取 {result.fetched} 条，新增 {result.new_items} 条，"
            f"重复命中 {result.duplicate_hits} 条，新增订阅关联 {result.new_feed_links} 条。"
        )
        push_notice(
            f"{result.feed_name} 更新完成：新增 {result.new_items} 条，重复 {result.duplicate_hits} 条",
            "success",
        )


def _format_timestamp(value: str) -> str:
    if not value:
        return "尚未更新"
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value


def _render_last_update_summary() -> None:
    settings = load_settings()
    st.caption("应用开启时会自动静默更新启用订阅。")

    metric_cols = st.columns(3)
    metric_cols[0].metric("最后一次更新时间", _format_timestamp(settings.last_feed_update_finished_at))
    trigger_label = settings.last_feed_update_trigger or "尚无记录"
    metric_cols[1].metric(
        "更新状态",
        f"{trigger_label} · {settings.last_feed_update_success_feeds}/{settings.last_feed_update_total_feeds} 个订阅",
    )
    metric_cols[2].metric("新增不重复文章", int(settings.last_feed_update_total_new_items or 0))
    st.caption(f"本轮自动整理过期：{int(settings.last_feed_update_expired_items or 0)} 条")

    results = list(settings.last_feed_update_results or [])
    if results:
        st.dataframe(
            [
                {
                    "订阅": row.get("feed_name") or row.get("feed_id"),
                    "新增不重复文章": int(row.get("new_items") or 0),
                    "抓取条数": int(row.get("fetched") or 0),
                    "重复命中": int(row.get("duplicate_hits") or 0),
                    "状态": "失败" if row.get("error") else "成功",
                }
                for row in results
            ],
            hide_index=True,
            width="stretch",
        )
    else:
        st.info("还没有更新记录。")


def render_feed_view() -> None:
    st.subheader("订阅管理 / 更新")
    tab_update, tab_add, tab_edit, tab_import, tab_batch_delete = st.tabs(
        ["更新订阅", "添加", "编辑", "批量导入", "批量删除"]
    )

    with tab_update:
        feeds = list_feeds(include_disabled=True)
        enabled_feeds = [f for f in feeds if f["enabled"]]
        _render_last_update_summary()
        st.divider()

        col1, col2 = st.columns([1, 1])
        if col1.button("更新全部启用订阅", type="primary"):
            with st.spinner("正在更新全部启用订阅……"):
                results, expired_count = run_data_refresh()
                record_update_summary(results, trigger="手动更新", expired_items=expired_count)
            for result in results:
                render_result(result)
            st.rerun()
        if feeds:
            selected_feeds = st.multiselect(
                "选择要更新的订阅",
                feeds,
                default=[enabled_feeds[0]] if len(enabled_feeds) == 1 else [],
                format_func=lambda f: f["name"],
                key="multi_update_select",
            )
            if selected_feeds:
                st.dataframe(
                    [
                        {
                            "名称": feed["name"],
                            "启用": bool(feed["enabled"]),
                            "条目": feed.get("item_count") or 0,
                            "URL": feed["url"],
                        }
                        for feed in selected_feeds
                    ],
                    hide_index=True,
                    width="stretch",
                )
            if col2.button("更新所选订阅", disabled=not selected_feeds):
                names = "、".join(feed["name"] for feed in selected_feeds[:3])
                if len(selected_feeds) > 3:
                    names += f" 等 {len(selected_feeds)} 个订阅"
                with st.spinner(f"正在更新：{names}……"):
                    results, expired_count = run_data_refresh([int(feed["id"]) for feed in selected_feeds])
                    record_update_summary(results, trigger="手动更新", expired_items=expired_count)
                for result in results:
                    render_result(result)
                st.rerun()
        else:
            st.info("暂无订阅可更新。")
        st.caption(f"启用订阅：{len(enabled_feeds)} / 全部订阅：{len(feeds)}")

    with tab_add:
        with st.form("add_feed_form", clear_on_submit=True):
            name = st.text_input("订阅名称", placeholder="例如：大学图书馆学报")
            url = st.text_input("RSS URL", placeholder="https://rss.cnki.net/knavi/rss/DXTS?pcode=CJFD,CCJD")
            enabled = st.checkbox("启用", value=True)
            submitted = st.form_submit_button("添加订阅")
        if submitted:
            try:
                feed_id = add_feed(name, url, enabled)
                st.success(f"已添加订阅 ID={feed_id}")
                push_notice(f"订阅已添加：{name.strip()}", "success")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
                push_notice(f"添加订阅失败：{exc}", "error")

    with tab_edit:
        feeds = list_feeds(include_disabled=True)
        if not feeds:
            st.info("暂无订阅。")
        else:
            choice = st.selectbox(
                "选择订阅",
                feeds,
                format_func=lambda f: f["name"],
            )
            with st.form(f"edit_feed_form_{choice['id']}"):
                new_name = st.text_input("订阅名称", value=choice["name"])
                new_url = st.text_input("RSS URL", value=choice["url"])
                new_enabled = st.checkbox("启用", value=bool(choice["enabled"]))
                cols = st.columns([1, 1, 4])
                save = cols[0].form_submit_button("保存修改")
                delete = cols[1].form_submit_button("删除订阅")
            if save:
                try:
                    normalized_name, normalized_url = validate_feed_input(new_name, new_url)
                    update_feed_meta(choice["id"], normalized_name, normalized_url, new_enabled)
                    st.success("已保存。")
                    push_notice(f"订阅已保存：{normalized_name}", "success")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
                    push_notice(f"保存订阅失败：{exc}", "error")
            if delete:
                delete_feed(choice["id"])
                st.warning("已删除订阅。该订阅独有的文献条目也已一并删除。")
                push_notice(f"订阅已删除：{choice['name']}", "warning")
                st.rerun()

            st.markdown("#### 当前订阅列表")
            st.dataframe(
                [
                    {
                        "ID": f["id"],
                        "名称": f["name"],
                        "启用": bool(f["enabled"]),
                        "条目": f.get("item_count") or 0,
                        "未读": f.get("unread_count") or 0,
                        "感兴趣": f.get("interested_count") or 0,
                        "归档": f.get("archived_count") or 0,
                        "隐藏": f.get("hidden_count") or 0,
                        "过期": f.get("expired_count") or 0,
                        "最后检查": f.get("last_checked_at") or "",
                        "错误": f.get("last_error") or "",
                        "URL": f["url"],
                    }
                    for f in feeds
                ],
                hide_index=True,
                width="stretch",
            )

    with tab_import:
        st.write("支持粘贴 OPML、XML，或每行一个 RSS URL。重复 URL 会自动跳过。")
        uploaded = st.file_uploader("上传 OPML / XML / TXT", type=["opml", "xml", "txt", "rtf"])
        pasted = st.text_area(
            "或直接粘贴内容",
            height=220,
            placeholder='<outline text="大学图书馆学报" xmlUrl="https://rss.cnki.net/..." />',
        )
        content = pasted
        if uploaded is not None:
            content = uploaded.read().decode("utf-8", errors="ignore") + "\n" + pasted
        candidates = extract_feeds_from_text(content) if content.strip() else []
        if candidates:
            st.caption(f"识别到 {len(candidates)} 个候选订阅。")
            st.dataframe([{"名称": n, "URL": u} for n, u in candidates], hide_index=True, width="stretch")
            if st.button("导入候选订阅"):
                result = bulk_import_feeds(candidates)
                st.success(f"新增 {result['added']} 个，跳过重复 {result['skipped']} 个。")
                push_notice(
                    f"候选订阅导入完成：新增 {result['added']} 个，跳过重复 {result['skipped']} 个",
                    "success",
                )
                if result["errors"]:
                    st.error("\n".join(result["errors"][:10]))
                    push_notice(f"有 {len(result['errors'])} 个候选订阅导入失败", "error")
                st.rerun()
        else:
            st.info("尚未识别到 RSS 链接。")

    with tab_batch_delete:
        feeds = list_feeds(include_disabled=True)
        if not feeds:
            st.info("暂无订阅可删除。")
        else:
            st.write("可多选后一次删除。删除订阅后，仅属于这些订阅的文献条目也会一并删除；若条目仍属于其他订阅，则会保留。")
            selected_feeds = st.multiselect(
                "选择要删除的订阅",
                feeds,
                format_func=lambda f: f["name"],
                key="batch_delete_feeds",
            )
            if selected_feeds:
                st.dataframe(
                    [
                        {
                            "ID": feed["id"],
                            "名称": feed["name"],
                            "启用": bool(feed["enabled"]),
                            "条目": feed.get("item_count") or 0,
                            "URL": feed["url"],
                        }
                        for feed in selected_feeds
                    ],
                    hide_index=True,
                    width="stretch",
                )
            confirm_batch_delete = st.checkbox("我确认要删除这些订阅", value=False, key="confirm_batch_delete")
            if st.button(
                "批量删除所选订阅",
                type="primary",
                disabled=not selected_feeds or not confirm_batch_delete,
                key="batch_delete_button",
            ):
                deleted = delete_feeds(feed["id"] for feed in selected_feeds)
                st.warning(f"已删除 {deleted} 个订阅。对应的独有文献条目也已一并删除。")
                push_notice(f"已批量删除 {deleted} 个订阅", "warning")
                st.rerun()
