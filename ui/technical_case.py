from typing import Optional

import streamlit as st

from agents.technical_case_agent import (
    TechnicalCaseRun,
    get_active_provider_name,
    run_technical_case_analysis,
)
from models import CaseRequirement, TechnicalQuestion
from ui.navigation import PAGE_HOME, set_current_page
from ui.technical_case_flow import SESSION_ANALYSIS, SESSION_CASE, SESSION_INQUIRY

SESSION_RUN = "technical_case_run"
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

    if get_active_provider_name() == "mock":
        st.warning(page["mock_warning"])

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
        run = run_technical_case_analysis(
            case_name,
            customer_name,
            end_user_name,
            inquiry_text,
        )
        st.session_state[SESSION_RUN] = run
        st.session_state[SESSION_CASE] = run.case
        st.session_state[SESSION_INQUIRY] = run.inquiry_text
        st.session_state[SESSION_ANALYSIS] = run.analysis_json

    st.divider()
    st.subheader(page["section_results"])
    _render_run_result(page, st.session_state.get(SESSION_RUN))


def _render_run_result(page: dict, run: Optional[TechnicalCaseRun]) -> None:
    if run is None:
        _render_empty_sections(page)
        return

    if not run.success:
        st.error(page["analysis_error"])
        if run.error_details:
            with st.expander(page["error_details_label"]):
                st.text(run.error_details)
        _render_empty_sections(page)
        return

    _render_summary_section(page, run)
    _render_requirement_section(page, run.requirements)
    _render_question_section(page["section_customer_checks"], run.customer_questions, page)
    _render_question_section(page["section_manufacturer_checks"], run.manufacturer_questions, page)
    _render_question_section(page["section_technical_questions"], run.technical_questions, page)
    _render_unresolved_section(page, run)

    if run.analysis_json is not None:
        with st.expander(page["review_json"]):
            st.json(run.analysis_json)


def _render_empty_sections(page: dict) -> None:
    for title_key in RESULT_SECTIONS:
        with st.container(border=True):
            st.markdown(f"**{page[title_key]}**")
            st.text(page["no_results"])


def _render_summary_section(page: dict, run: TechnicalCaseRun) -> None:
    with st.container(border=True):
        st.markdown(f"**{page['section_summary']}**")
        if run.case_summary:
            st.write(run.case_summary)
        else:
            st.text(page["no_results"])

        if run.requested_products:
            st.markdown(f"**{page['requested_products_label']}**")
            for product in run.requested_products:
                st.write(f"- {product}")
            st.caption(page["requested_products_note"])


def _render_requirement_section(page: dict, requirements: list[CaseRequirement]) -> None:
    with st.container(border=True):
        st.markdown(f"**{page['section_requirements']}**")
        if not requirements:
            st.text(page["no_results"])
            return
        for requirement in requirements:
            st.write(f"- {_requirement_line(requirement, page)}")


def _render_question_section(
    title: str,
    questions: list[TechnicalQuestion],
    page: dict,
) -> None:
    with st.container(border=True):
        st.markdown(f"**{title}**")
        visible_questions = [item.question for item in questions if item.question]
        if not visible_questions:
            st.text(page["no_results"])
            return
        for question in visible_questions:
            st.write(f"- {question}")


def _render_unresolved_section(page: dict, run: TechnicalCaseRun) -> None:
    with st.container(border=True):
        st.markdown(f"**{page['section_unconfirmed']}**")
        if not run.unresolved_items:
            st.text(page["no_results"])
            return
        for item in run.unresolved_items:
            label = item.label or page["unnamed_item"]
            if item.notes:
                st.write(f"- {label}: {item.notes}")
            else:
                st.write(f"- {label}")


def _requirement_line(requirement: CaseRequirement, page: dict) -> str:
    label = requirement.label or page["unnamed_item"]
    if requirement.value:
        value = requirement.value
        if requirement.unit:
            value = f"{value} {requirement.unit}"
        line = f"{label}: {value}"
    else:
        line = f"{label}: {page['no_value']}"
    if not requirement.confirmed:
        line = f"{line}（{page['unconfirmed_label']}）"
    return line
