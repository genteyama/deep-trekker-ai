from typing import Optional

import streamlit as st

from agents.approval import (
    ERROR_ALREADY_APPLIED,
    ApprovalBoard,
    HumanApprovalInput,
    QuestionApprovalItem,
    apply_human_approval,
    build_approval_board,
    summarize_approvals,
)
from agents.facts import (
    ERROR_DUPLICATE_FACT,
    WARNING_REUSABLE,
    WARNING_TIME_SENSITIVE_REUSABLE,
    FactRegistrationInput,
    draft_fact_candidate,
    fact_registration_warnings,
    register_technical_fact,
)
from agents.technical_case_agent import (
    ERROR_EMPTY_RESPONSE,
    ERROR_NO_QUESTIONS,
    ManufacturerResponseRun,
    TechnicalCaseRun,
    get_active_provider_name,
    run_manufacturer_response_analysis,
    run_technical_case_analysis,
)
from models import (
    CaseRequirement,
    FactConfidence,
    FactScope,
    SuggestedQuestionStatus,
    TechnicalQuestion,
)
from ui.navigation import PAGE_HOME, set_current_page
from ui.technical_case_flow import SESSION_ANALYSIS, SESSION_CASE, SESSION_INQUIRY

SESSION_RUN = "technical_case_run"
SESSION_RESPONSE_RUN = "manufacturer_response_run"
SESSION_APPROVAL_BOARD = "manufacturer_approval_board"
APPROVAL_STATUS_OPTIONS = (
    SuggestedQuestionStatus.ANSWERED,
    SuggestedQuestionStatus.PARTIAL,
    SuggestedQuestionStatus.FOLLOW_UP_REQUIRED,
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
        st.session_state[SESSION_APPROVAL_BOARD] = (
            build_approval_board(run) if run.success else None
        )

    _render_response_run(
        page,
        st.session_state.get(SESSION_RESPONSE_RUN),
        st.session_state.get(SESSION_APPROVAL_BOARD),
        inquiry_run,
    )


def _render_response_run(
    page: dict,
    run: Optional[ManufacturerResponseRun],
    board: Optional[ApprovalBoard],
    inquiry_run: Optional[TechnicalCaseRun],
) -> None:
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

    if board:
        st.text_input(page["approver_label"], key="input_approver")
        st.caption(page["approver_hint"])
        for item in board.items:
            _render_approval_card(page, item, board, inquiry_run)
        _render_approval_summary(page, board)

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


def _render_approval_card(
    page: dict,
    item: QuestionApprovalItem,
    board: ApprovalBoard,
    inquiry_run: Optional[TechnicalCaseRun],
) -> None:
    candidate = item.ai_candidate
    status_key = candidate.suggested_status.value if candidate.suggested_status else None
    question_id = item.question.question_id

    with st.container(border=True):
        state_label = page["applied_label"] if item.is_applied else page["pending_label"]
        st.caption(f"{page['response_review_label']} / {state_label}")
        st.markdown(f"**{page['question_label']}**")
        st.write(item.question.question or page["unnamed_item"])
        st.markdown(f"**{page['suggested_status_label']}**")
        st.write(page["suggested_status"].get(status_key, page["unconfirmed_label"]))
        st.markdown(f"**{page['answer_summary_label']}**")
        st.write(candidate.answer_summary or page["no_value"])
        st.markdown(f"**{page['follow_up_needed_label']}**")
        st.write(page["needed_yes"] if candidate.follow_up_required else page["needed_no"])
        if candidate.follow_up_question:
            st.markdown(f"**{page['follow_up_question_label']}**")
            st.write(candidate.follow_up_question)
        st.markdown(f"**{page['confidence_label']}**")
        confidence_key = candidate.confidence.value if candidate.confidence else None
        st.write(page["confidence"].get(confidence_key, page["no_value"]))
        if candidate.evidence_text:
            st.markdown(f"**{page['evidence_label']}**")
            st.write(candidate.evidence_text)

        if item.is_applied:
            st.success(page["applied_message"])
            _render_fact_registration(page, item)
            return

        st.markdown(f"**{page['human_review_label']}**")
        default_status = candidate.suggested_status or SuggestedQuestionStatus.FOLLOW_UP_REQUIRED
        with st.form(f"approve_{question_id}"):
            selected_status = st.selectbox(
                page["suggested_status_label"],
                options=list(APPROVAL_STATUS_OPTIONS),
                index=list(APPROVAL_STATUS_OPTIONS).index(default_status),
                format_func=lambda value: page["suggested_status"][value.value],
                key=f"edit_status_{question_id}",
            )
            approved_answer = st.text_area(
                page["answer_summary_label"],
                value=candidate.answer_summary or "",
                key=f"edit_answer_{question_id}",
            )
            follow_up_required = st.checkbox(
                page["follow_up_needed_label"],
                value=candidate.follow_up_required,
                key=f"edit_follow_up_{question_id}",
            )
            follow_up_question = st.text_area(
                page["follow_up_question_label"],
                value=candidate.follow_up_question or "",
                key=f"edit_follow_up_question_{question_id}",
            )
            submitted = st.form_submit_button(
                page["apply_button"],
                key=f"apply_{question_id}",
            )

        if submitted:
            result = apply_human_approval(
                board,
                question_id,
                HumanApprovalInput(
                    approved_status=selected_status,
                    approved_answer=approved_answer,
                    follow_up_required=follow_up_required,
                    follow_up_question=follow_up_question,
                    approved_by=st.session_state.get("input_approver"),
                ),
            )
            if result.success and result.item:
                _sync_inquiry_question(inquiry_run, result.item.question)
                st.success(page["applied_message"])
                st.rerun()
            elif result.error_code == ERROR_ALREADY_APPLIED:
                st.warning(page["already_applied"])


def _render_approval_summary(page: dict, board: ApprovalBoard) -> None:
    summary = summarize_approvals(board)
    with st.container(border=True):
        st.markdown(f"**{page['summary_label']}**")
        st.write(f"{page['summary_total']}: {summary['total']}")
        st.write(f"{page['summary_applied']}: {summary['applied']}")
        st.write(f"{page['summary_pending']}: {summary['pending']}")
        st.write(f"{page['suggested_status']['ANSWERED']}: {summary['answered']}")
        st.write(f"{page['suggested_status']['PARTIAL']}: {summary['partial']}")
        st.write(f"{page['suggested_status']['FOLLOW_UP_REQUIRED']}: {summary['follow_up_required']}")


def _render_fact_registration(page: dict, item: QuestionApprovalItem) -> None:
    st.markdown(f"**{page['fact_section_label']}**")
    question_id = item.question.question_id
    candidate = draft_fact_candidate(item)
    scope = st.radio(
        page["fact_scope_label"],
        options=list(FactScope),
        format_func=lambda value: page["fact_scope"][value.value],
        key=f"fact_scope_{question_id}",
        index=0,
    )
    is_time_sensitive = st.checkbox(
        page["fact_time_sensitive_label"],
        key=f"fact_time_{question_id}",
    )
    for warning_code in fact_registration_warnings(scope, is_time_sensitive):
        if warning_code == WARNING_REUSABLE:
            st.info(page["fact_reusable_confirm"])
        if warning_code == WARNING_TIME_SENSITIVE_REUSABLE:
            st.warning(page["fact_time_sensitive_warning"])

    with st.form(f"register_fact_{question_id}"):
        product = st.text_input(page["fact_product_label"], key=f"fact_product_{question_id}")
        topic = st.text_input(page["fact_topic_label"], key=f"fact_topic_{question_id}")
        fact_text = st.text_area(
            page["fact_text_label"],
            value=candidate.fact if candidate and candidate.fact else "",
            key=f"fact_text_{question_id}",
        )
        confidence = st.selectbox(
            page["fact_confidence_label"],
            options=list(FactConfidence),
            index=list(FactConfidence).index(FactConfidence.SPACEONE_VERIFIED),
            format_func=lambda value: page["fact_confidence"][value.value],
            key=f"fact_confidence_{question_id}",
        )
        notes = st.text_area(page["fact_notes_label"], key=f"fact_notes_{question_id}")
        submitted = st.form_submit_button(
            page["fact_register_button"],
            key=f"register_fact_button_{question_id}",
        )

    if submitted:
        result = register_technical_fact(
            item,
            FactRegistrationInput(
                product=product,
                topic=topic,
                fact=fact_text,
                scope=scope,
                is_time_sensitive=is_time_sensitive,
                confidence=confidence,
                notes=notes,
            ),
        )
        if result.success:
            st.success(page["fact_registered_message"])
        elif result.error_code == ERROR_DUPLICATE_FACT:
            st.warning(page["fact_duplicate"])

    if item.registered_facts:
        st.markdown(f"**{page['registered_facts_label']}**")
        for fact in item.registered_facts:
            scope_label = page["fact_scope"].get(fact.scope.value, "") if fact.scope else ""
            st.write(f"- {fact.product or page['unnamed_item']} / {fact.topic or page['unnamed_item']}: {fact.fact}")
            if scope_label:
                st.caption(scope_label)


def _sync_inquiry_question(inquiry_run: Optional[TechnicalCaseRun], question: TechnicalQuestion) -> None:
    if inquiry_run is None:
        return
    for index, current in enumerate(inquiry_run.manufacturer_questions):
        if current.question_id == question.question_id:
            inquiry_run.manufacturer_questions[index] = question
            return


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
