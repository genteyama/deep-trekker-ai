from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

AUTH_EMAIL_KEY = "auth_email"

_override: ContextVar[Optional[str]] = ContextVar("deep_trekker_actor", default=None)


def set_current_actor(email: Optional[str]) -> None:
    """Explicit actor for scripts and tests. The app uses the logged-in session email."""
    _override.set(email)


def current_actor() -> Optional[str]:
    explicit = _override.get()
    if explicit:
        return explicit
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        import streamlit as st

        if get_script_run_ctx(suppress_warning=True) is None:
            return None
        return st.session_state.get(AUTH_EMAIL_KEY)
    except Exception:
        return None
