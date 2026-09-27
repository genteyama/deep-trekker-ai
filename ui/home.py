import streamlit as st

from ui.components.portal import (
    render_home_hero,
    render_menu_card,
    render_portal_section_title,
    render_recent_draft_list,
    resume_draft_into_session,
)
from ui.navigation import PAGE_QUOTE_CONTROL, PAGE_TECHNICAL_CASE, set_current_page
from ui.quote_persistence import get_quote_repository


def render_home(texts: dict) -> None:
    technical_case = texts["agents"]["technical_case"]
    quote_control = texts["agents"]["quote_control"]
    quote_page = texts["pages"]["quote_control"]

    render_home_hero(
        texts["app_title"],
        texts["app_description"],
        texts.get("hero_english", ""),
    )
    render_portal_section_title(texts["menu_label"])

    left_column, right_column = st.columns(2)
    with left_column:
        render_menu_card(
            technical_case["name"],
            technical_case.get("english", "Technical Support"),
            technical_case["description"],
            product_key="PIPETREKKER",
        )
        if st.button(
            texts.get("open_label", "開く"),
            key="open_technical_case",
            use_container_width=True,
        ):
            set_current_page(PAGE_TECHNICAL_CASE)
            st.rerun()

    with right_column:
        render_menu_card(
            quote_control["name"],
            quote_control.get("english", "Quote & Price Control"),
            quote_control["description"],
            product_key="PHOTON",
        )
        if st.button(
            texts.get("open_label", "開く"),
            key="open_quote_control",
            use_container_width=True,
        ):
            set_current_page(PAGE_QUOTE_CONTROL)
            st.rerun()

    render_portal_section_title(quote_page["workspace"].get("recent_drafts_label", "最近の下書き"))
    items = get_quote_repository().list_recent_drafts(limit=8)
    render_recent_draft_list(
        quote_page,
        items,
        resume_key_prefix="home_resume_draft_",
        on_resume=lambda draft_id, version: _resume_from_home(quote_page, draft_id, version),
    )


def _resume_from_home(page: dict, quote_draft_id: str, version: int) -> None:
    if resume_draft_into_session(quote_draft_id, version):
        set_current_page(PAGE_QUOTE_CONTROL)
        st.rerun()
    st.error(page["workspace"].get("resume_failed", "下書きを開けませんでした。"))
