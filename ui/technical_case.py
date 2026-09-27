from typing import Optional

import streamlit as st

from agents.technical_case_agent import (
    ERROR_EMPTY_RESPONSE,
    ERROR_NO_QUESTIONS,
    ManufacturerResponseRun,
    QuestionMatchView,
    TechnicalCaseRun,
    get_active_provider_name,
    run_manufacturer_response_analysis,
    run_technical_case_analysis,
)
from models import CaseRequirement, TechnicalQuestion
from ui.navigation import PAGE_HOME, set_current_page
from ui.technical_case_flow import SESSION_ANALYSIS, SESSION_CASE, SESSION_INQUIRY

SESSION_RUN = "technical_case_run"
SESSION_RESPONSE_RUN = "manufacturer_response_run"
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

    st.divider()
    _render_manufacturer_response_section(page, st.session_state.get(SESSION_RUN))


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


def _render_manufacturer_response_section(
    page: dict,
    inquiry_run: Optional[TechnicalCaseRun],
) -> None:
    st.subheader(page["section_manufacturer_response"])
    if get_active_provider_name() == "mock":
        st.warning(page["response_mock_warning"])
    st.caption(page["response_review_label"])

    with st.form("manufacturer_response_review"):
        response_text = st.text_area(
            page["manufacturer_response_label"],
            key="input_manufacturer_response",
            height=180,
        )
        submitted = st.form_submit_button(
            page["organize_response_button"],
            key="organize_manufacturer_response",
            type="primary",
        )

    if submitted:
        questions = []
        if inquiry_run and inquiry_run.success:
            questions = list(inquiry_run.manufacturer_questions)
        run = run_manufacturer_response_analysis(questions, response_text)
        st.session_state[SESSION_RESPONSE_RUN] = run

    _render_response_run(page, st.session_state.get(SESSION_RESPONSE_RUN))


def _render_response_run(page: dict, run: Optional[ManufacturerResponseRun]) -> None:
    if run is None:
        st.text(page["response_no_results"])
        return

    if not run.success:
        error_text = page["response_error"]
        if run.error_code == ERROR_NO_QUESTIONS:
            error_text = page["response_no_questions"]
        elif run.error_code == ERROR_EMPTY_RESPONSE:
            error_text = page["response_empty_text"]
        st.error(error_text)
        if run.error_details:
            with st.expander(page["error_details_label"]):
                st.text(run.error_details)
        return

    if run.response_summary:
        st.write(run.response_summary)

    for view in run.matches:
        _render_match_card(page, view)

    with st.container(border=True):
        st.markdown(f"**{page['unmatched_information_label']}**")
        if not run.unmatched_information:
            st.text(page["no_results"])
        else:
            for item in run.unmatched_information:
                summary = item.summary or page["unnamed_item"]
                st.write(f"- {summary}")

    if run.original_response_text:
        with st.expander(page["review_original_response"]):
            st.text(run.original_response_text)
    if run.analysis_json is not None:
        with st.expander(page["review_response_json"]):
            st.json(run.analysis_json)


def _render_match_card(page: dict, view: QuestionMatchView) -> None:
    candidate = view.candidate
    status_key = candidate.suggested_status.value if candidate.suggested_status else None
    status_label = page["suggested_status"].get(status_key, page["unconfirmed_label"])
    confidence_key = candidate.confidence.value if candidate.confidence else None
    confidence_label = page["confidence"].get(confidence_key, page["no_value"])
    follow_up_label = page["needed_yes"] if candidate.follow_up_required else page["needed_no"]

    with st.container(border=True):
        st.markdown(f"**{page['question_label']}**")
        st.write(view.question.question or page["unnamed_item"])
        st.markdown(f"**{page['suggested_status_label']}**")
        st.write(status_label)
        st.markdown(f"**{page['answer_summary_label']}**")
        st.write(candidate.answer_summary or page["no_value"])
        st.markdown(f"**{page['follow_up_needed_label']}**")
        st.write(follow_up_label)
        if candidate.follow_up_question:
            st.markdown(f"**{page['follow_up_question_label']}**")
            st.write(candidate.follow_up_question)
        st.markdown(f"**{page['confidence_label']}**")
        st.write(confidence_label)


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
