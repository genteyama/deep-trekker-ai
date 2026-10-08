from __future__ import annotations

from typing import Optional

import streamlit as st

from repositories.quote_repository import CONFLICT_MESSAGE

SESSION_CONFLICT = "edit_conflict"


def flag_conflict(kind: str, key: str, version: Optional[int] = None) -> None:
    st.session_state[SESSION_CONFLICT] = {"kind": kind, "key": key, "version": version}


def render_conflict_banner() -> None:
    conflict = st.session_state.get(SESSION_CONFLICT)
    if not conflict:
        return
    st.error(CONFLICT_MESSAGE)
    if st.button("最新状態を再読み込み", key="conflict_reload", type="primary"):
        reload_conflicted(conflict)
        st.session_state.pop(SESSION_CONFLICT, None)
        st.rerun()


def reload_conflicted(conflict: dict) -> None:
    if conflict["kind"] == "quote":
        from ui.components.portal import resume_draft_into_session
        from ui.quote_persistence import SESSION_SAVE_ERROR

        resume_draft_into_session(conflict["key"], conflict["version"])
        st.session_state[SESSION_SAVE_ERROR] = None
    elif conflict["kind"] == "technical_case":
        from ui.technical_case_persistence import (
            SESSION_SAVE_ERROR,
            SESSION_SAVE_STATUS,
            get_technical_case_repository,
            resume_case_into_session,
        )

        repo = get_technical_case_repository()
        repo.forget_row_version(conflict["key"])
        loaded = repo.get_case(conflict["key"])
        if loaded is not None:
            resume_case_into_session(loaded, st.session_state)
        st.session_state[SESSION_SAVE_ERROR] = None
        st.session_state[SESSION_SAVE_STATUS] = None
