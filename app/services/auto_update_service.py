from __future__ import annotations

import os
import threading
from datetime import datetime

import streamlit as st

from app.config import AUTO_UPDATE_CHECK_SECONDS
from app.services.feed_service import record_update_summary, run_data_refresh
from app.services.settings_service import load_settings
from app.ui.notices import push_notice

AUTO_UPDATE_READY_KEY = "auto_update_ready"
AUTO_UPDATE_REQUESTED_KEY = "auto_update_requested"

_AUTO_UPDATE_LOCK = threading.Lock()
_PROCESS_RUN_ID = f"{os.getpid()}:{datetime.now().astimezone().isoformat(timespec='seconds')}"
_AUTO_UPDATE_STATE = {
    "status": "idle",
    "started_at": "",
    "finished_at": "",
    "total_new_items": 0,
    "error": "",
    "process_run_id": _PROCESS_RUN_ID,
    "start_notice_sent": False,
    "finish_notice_sent": False,
}


def _auto_update_worker() -> None:
    started_at = datetime.now().astimezone()
    with _AUTO_UPDATE_LOCK:
        _AUTO_UPDATE_STATE["status"] = "running"
        _AUTO_UPDATE_STATE["started_at"] = started_at.isoformat(timespec="seconds")
        _AUTO_UPDATE_STATE["finished_at"] = ""
        _AUTO_UPDATE_STATE["total_new_items"] = 0
        _AUTO_UPDATE_STATE["error"] = ""
        _AUTO_UPDATE_STATE["start_notice_sent"] = False
        _AUTO_UPDATE_STATE["finish_notice_sent"] = False

    try:
        results, expired_count = run_data_refresh()
        record_update_summary(results, trigger="自动更新", started_at=started_at, expired_items=expired_count)
        total_new_items = sum(int(result.new_items or 0) for result in results)
        with _AUTO_UPDATE_LOCK:
            _AUTO_UPDATE_STATE["status"] = "done"
            _AUTO_UPDATE_STATE["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            _AUTO_UPDATE_STATE["total_new_items"] = total_new_items
    except Exception as exc:
        with _AUTO_UPDATE_LOCK:
            _AUTO_UPDATE_STATE["status"] = "error"
            _AUTO_UPDATE_STATE["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            _AUTO_UPDATE_STATE["error"] = str(exc)


def _snapshot_state() -> dict[str, str | int]:
    with _AUTO_UPDATE_LOCK:
        return dict(_AUTO_UPDATE_STATE)


def _start_background_update_if_needed() -> None:
    settings = load_settings()
    if not settings.auto_update_enabled:
        return
    if _snapshot_state()["status"] != "idle":
        return
    if st.session_state.get(AUTO_UPDATE_REQUESTED_KEY):
        return
    thread = threading.Thread(target=_auto_update_worker, daemon=True, name="rss-reader-auto-update")
    thread.start()

    st.session_state[AUTO_UPDATE_REQUESTED_KEY] = True


def should_mount_auto_update_fragment() -> bool:
    settings = load_settings()
    return bool(settings.auto_update_enabled)


@st.fragment(run_every=AUTO_UPDATE_CHECK_SECONDS)
def run_auto_update_fragment() -> None:
    if not st.session_state.get(AUTO_UPDATE_READY_KEY):
        st.session_state[AUTO_UPDATE_READY_KEY] = True
        return

    _start_background_update_if_needed()
    state = _snapshot_state()

    if state["status"] == "running" and not bool(state["start_notice_sent"]):
        push_notice("后台正在自动更新订阅", "info")
        with _AUTO_UPDATE_LOCK:
            _AUTO_UPDATE_STATE["start_notice_sent"] = True
        st.rerun()

    if state["status"] == "done" and not bool(state["finish_notice_sent"]):
        total_new_items = int(state["total_new_items"] or 0)
        if total_new_items > 0:
            push_notice(f"后台自动更新完成，已更新 {total_new_items} 条，请刷新列表", "success")
        else:
            push_notice("后台自动更新完成，无更新", "info")
        with _AUTO_UPDATE_LOCK:
            _AUTO_UPDATE_STATE["finish_notice_sent"] = True
        st.rerun()

    if state["status"] == "error" and not bool(state["finish_notice_sent"]):
        push_notice(f"后台自动更新失败：{state['error']}", "error")
        with _AUTO_UPDATE_LOCK:
            _AUTO_UPDATE_STATE["finish_notice_sent"] = True
        st.rerun()
