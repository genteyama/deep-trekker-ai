from __future__ import annotations

import os
from typing import Optional


def get_setting(name: str) -> Optional[str]:
    """Environment first, then Streamlit Secrets. Values are never logged."""
    value = os.environ.get(name)
    if value:
        return value.strip()
    value = _read_st_secret(name)
    return str(value).strip() if value else None


def _read_st_secret(name: str) -> Optional[str]:
    try:
        import streamlit as st

        return st.secrets.get(name)
    except Exception:
        # No secrets file (local v1) or not running under Streamlit.
        return None


def database_url() -> Optional[str]:
    return get_setting("DATABASE_URL")
