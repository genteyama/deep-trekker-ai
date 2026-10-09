from __future__ import annotations

import os
from typing import Any, Optional


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


def get_secret_mapping(name: str) -> Optional[dict[str, Any]]:
    """Read one structured Streamlit Secret without stringifying or logging it."""
    value = _read_st_secret(name)
    if value is None:
        return None
    try:
        return {str(key): item for key, item in dict(value).items()}
    except (TypeError, ValueError, AttributeError):
        return None
