import streamlit as st

from ui.navigation import PAGE_HOME, set_current_page
from ui.technical_case_flow import (
    SESSION_ANALYSIS,
    SESSION_CASE,
    SESSION_INQUIRY,
    SESSION_NOTICE,
    start_inquiry_analysis,
)

RESULT_SECTIONS = (
    "section_summary",
    "section_requirements",
    "section_customer_checks",
    "section_manufacturer_checks",
    "section_technical_questions",
    "section_unconfirmed",
)


def render_technical_case(texts: dict) -> None:
    page = texts["pages"]["technical_case"]

    if st.button(texts["back_to_home"], key="back_to_home"):
        set_current_page(PAGE_HOME)
        st.rerun()

    st.title(page["title"])
    st.caption(page["internal_name"])
    st.write(page["description"])
    st.divider()

    with st.form("technical_case_intake"):
        st.subheader(page["section_case_info"])
        case_name = st.text_input(page["case_name"], key="input_case_name")
        customer_name = st.text_input(page["customer_name"], key="input_customer_name")
        end_user_name = st.text_input(page["end_user_name"], key="input_end_user_name")
        st.caption(page["end_user_hint"])

        st.subheader(page["section_inquiry"])
        inquiry_text = st.text_area(
            page["inquiry_label"],
            key="input_customer_inquiry",
            height=180,
        )

        submitted = st.form_submit_button(
            page["analyze_button"],
            key="analyze_inquiry",
            type="primary",
        )

    if submitted:
        case, inquiry, analysis = start_inquiry_analysis(
            case_name,
            customer_name,
            end_user_name,
            inquiry_text,
        )
        st.session_state[SESSION_CASE] = case
        st.session_state[SESSION_INQUIRY] = inquiry
        st.session_state[SESSION_ANALYSIS] = analysis
        st.session_state[SESSION_NOTICE] = page["analyze_pending_message"]

    notice = st.session_state.get(SESSION_NOTICE)
    if notice:
        st.info(notice)

    st.divider()
    st.subheader(page["section_results"])
    _render_analysis_sections(page)


def _render_analysis_sections(page: dict) -> None:
    for title_key in RESULT_SECTIONS:
        with st.container(border=True):
            st.markdown(f"**{page[title_key]}**")
            st.text(page["no_results"])
