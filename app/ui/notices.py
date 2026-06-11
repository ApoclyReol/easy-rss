from __future__ import annotations

import streamlit as st

NOTICE_ICONS = {
    "success": ":material/check_circle:",
    "error": ":material/error:",
    "warning": ":material/warning:",
    "info": ":material/info:",
}


def push_notice(message: str, kind: str = "success") -> None:
    notices = st.session_state.setdefault("notices", [])
    notices.append({"message": message, "kind": kind})


def flush_notices() -> None:
    notices = st.session_state.pop("notices", [])
    for notice in notices:
        st.toast(notice["message"], icon=NOTICE_ICONS.get(notice["kind"], NOTICE_ICONS["info"]))

