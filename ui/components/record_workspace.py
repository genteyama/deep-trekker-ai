from __future__ import annotations

from html import escape
from typing import Optional, Sequence

import streamlit as st


def render_record_header(
    *,
    customer: str,
    title: str,
    end_user: str,
    status: str,
    current_step: str,
    progress: str,
    review: str,
    updated: str,
    flags: Optional[Sequence[str]] = None,
) -> None:
    flag_html = "".join(f"<span class='record-flag'>{escape(flag)}</span>" for flag in flags or [])
    st.markdown(
        f"<div class='record-header'>"
        f"<div class='record-header-identity'>"
        f"<div class='record-customer'>{escape(customer)}</div>"
        f"<div class='record-title'>{escape(title)}</div>"
        f"</div>"
        f"<div class='record-header-status'>"
        f"<div class='record-status'>{escape(status)}</div>"
        f"<div class='record-meta-row'>{escape(current_step)}</div>"
        f"<div class='record-meta-row'>{escape(progress)}</div>"
        f"<div class='record-meta-row'>{escape(review)}</div>"
        f"{flag_html}"
        f"</div>"
        f"<div class='record-header-meta'>"
        f"<span>{escape(end_user)}</span>"
        f"<span>{escape(updated)}</span>"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def render_side_card(title: str, rows: Sequence[tuple[str, str]]) -> None:
    body = "".join(
        f"<div class='record-meta-row'><span>{escape(label)}</span><span>{escape(value)}</span></div>"
        for label, value in rows
    )
    st.markdown(
        f"<div class='record-side-card'>"
        f"<div class='record-side-title'>{escape(title)}</div>"
        f"{body}"
        f"</div>",
        unsafe_allow_html=True,
    )


def render_related_list(title: str, count_label: str, items: Sequence[str]) -> None:
    body = "".join(f"<div class='record-related-item'>{escape(item)}</div>" for item in items)
    if not body:
        body = "<div class='record-related-item'>-</div>"
    st.markdown(
        f"<div class='record-side-card'>"
        f"<div class='record-side-title'>{escape(title)}</div>"
        f"<div class='record-meta-row'>{escape(count_label)}</div>"
        f"{body}"
        f"</div>",
        unsafe_allow_html=True,
    )
