from datetime import datetime
from html import escape
from typing import Callable, Optional

import streamlit as st

from agents.quote_dates import apply_date_widget_defaults
from ui.components.product_badge import product_badge_html
from ui.product_assets import product_image_html
from ui.quote_persistence import apply_ui_state, get_quote_repository


def render_home_hero(title: str, description: str, english: str) -> None:
    st.title(title)
    parts = [f"<p class='app-subtitle'>{escape(description)}</p>"]
    if english:
        parts.append(f"<p class='portal-hero-en'>{escape(english)}</p>")
    strip = "".join(
        product_image_html(key, css_class="portal-hero-product")
        for key in ("PHOTON", "PIPETREKKER", "REVOLUTION")
    )
    if strip:
        parts.append(f"<div class='portal-hero-products'>{strip}</div>")
    st.markdown(f"<div class='portal-hero'>{''.join(parts)}</div>", unsafe_allow_html=True)


def render_portal_section_title(label: str) -> None:
    st.markdown(f"<h3 class='portal-section-title'>{escape(label)}</h3>", unsafe_allow_html=True)


def render_menu_card(title: str, english: str, description: str, *, product_key: Optional[str] = None) -> None:
    image = product_image_html(product_key, css_class="portal-card-thumb")
    st.markdown(
        f"<div class='portal-card'>"
        f"{image}"
        f"<div class='portal-card-title'>{escape(title)}</div>"
        f"<div class='portal-card-en'>{escape(english)}</div>"
        f"<div class='portal-card-desc'>{escape(description)}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def render_product_choice_card(product_key: str, caption: str) -> None:
    image = product_image_html(product_key, css_class="portal-card-thumb")
    badge = product_badge_html(product_key)
    st.markdown(
        f"<div class='portal-card portal-product-card'>"
        f"{image}"
        f"{badge}"
        f"<div class='portal-card-desc'>{escape(caption)}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def format_portal_datetime(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%Y/%m/%d %H:%M")
    except ValueError:
        return value


def render_draft_list_card(
    *,
    customer: str,
    subject: str,
    product: str,
    status: str,
    updated_at: str,
    updated_label: str,
    status_label: str,
) -> None:
    badge = product_badge_html(product)
    st.markdown(
        f"<div class='portal-draft-card'>"
        f"<div class='portal-draft-title'>{escape(customer)}</div>"
        f"<div class='portal-draft-badge-row'>{badge}</div>"
        f"<div class='portal-draft-subject'>{escape(subject)}</div>"
        f"<div class='portal-draft-meta'>{escape(updated_label)} {escape(updated_at)}</div>"
        f"<div class='portal-draft-meta'>{escape(status_label)}{escape(status)}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def render_recent_draft_list(
    page: dict,
    items,
    *,
    resume_key_prefix: str,
    on_resume: Callable,
) -> None:
    workspace = page["workspace"]
    status_labels = page["draft_statuses"]
    empty = workspace.get("unset_label", "未設定")
    if not items:
        st.caption(workspace.get("no_recent_drafts", "保存済みの下書きはありません。"))
        return
    for item in items:
        customer = item.customer_name or empty
        subject = item.subject or item.configuration_name or empty
        if subject == customer and item.configuration_name:
            subject = item.configuration_name
        status = status_labels.get(item.status, item.status or empty)
        render_draft_list_card(
            customer=customer,
            subject=subject,
            product=item.configuration_name or "",
            status=status,
            updated_at=format_portal_datetime(item.updated_at),
            updated_label=workspace.get("updated_at_label", "最終更新"),
            status_label=workspace.get("status_prefix", "状態："),
        )
        if st.button(
            workspace.get("resume_draft_button", "作業を再開"),
            key=f"{resume_key_prefix}{item.quote_draft_id}_{item.version}",
        ):
            on_resume(item.quote_draft_id, item.version)


def resume_draft_into_session(quote_draft_id: str, version: int, *, init_dates=None) -> bool:
    loaded = get_quote_repository().get_draft(quote_draft_id, version)
    if loaded is None:
        return False
    apply_ui_state(
        st.session_state,
        loaded.draft,
        loaded.ui_state,
        init_dates=init_dates or apply_date_widget_defaults,
    )
    st.session_state["quote_draft"] = loaded.draft
    st.session_state["approved_quote_snapshot"] = get_quote_repository().get_snapshot_for_draft(
        quote_draft_id,
        version,
    )
    st.session_state["quote_approval_validation"] = None
    return True
