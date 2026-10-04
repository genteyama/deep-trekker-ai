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
from agents.fact_retrieval import (
    detect_requested_products,
    load_human_approved_catalog,
    retrieve_approved_facts_for_products,
)
from agents.knowledge import is_default_selected
from agents.question_review import apply_question_review
from agents.technical_case_agent import (
    ERROR_EMPTY_RESPONSE,
    ERROR_NO_QUESTIONS,
    ManufacturerResponseRun,
    TechnicalCaseRun,
    get_active_provider_name,
    run_manufacturer_response_analysis,
    run_technical_case_analysis,
)
from llm.completeness import ERROR_COMPLETENESS
from llm.provider import (
    ERROR_MISSING_API_KEY,
    get_provider_runtime_status,
    run_provider_connection_test,
)
from models import (
    CaseRequirement,
    FactConfidence,
    FactScope,
    SuggestedQuestionStatus,
    TechnicalQuestion,
)
from ui.navigation import PAGE_HOME, set_current_page
from ui.technical_case_flow import (
    SESSION_ANALYSIS,
    SESSION_APPROVAL_BOARD,
    SESSION_CASE,
    SESSION_INQUIRY,
    SESSION_RESPONSE_RUN,
    SESSION_RUN,
)
from ui.components.lifecycle import apply_case_lifecycle, render_case_actions_menu, render_lineage_card
from ui.components.status import item_badge_label, render_progress_summary, render_work_card
from ui.technical_case_persistence import (
    get_technical_case_repository,
    persist_technical_case,
    resume_case_into_session,
    start_new_technical_case,
)
from ui.work_status import summarize_technical_case

FACT_SELECT_PREFIX = "use_fact_"
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
    _apply_pending_resume()

    if st.button(texts["back_to_home"], key="back_to_home", type="secondary"):
        set_current_page(PAGE_HOME)
        st.rerun()

    st.title(page["title"])
    st.caption(page["internal_name"])
    st.write(page["description"])
    summary = _current_work_summary()
    _render_case_summary(page, summary)
    _render_case_actions(page)
    _render_case_lifecycle(texts, page)

    if get_active_provider_name() == "mock":
        st.warning(page["mock_warning"])
    with st.expander(page.get("provider_status_label", "AI Provider"), expanded=False):
        _render_provider_status(page)

    inquiry_text = ""
    with render_work_card(
        page["section_inquiry"],
        item_badge_label(summary, "inquiry"),
        expanded=True,
        key="card_inquiry",
    ):
        inquiry_text = st.text_area(
            page["inquiry_label"],
            key="input_customer_inquiry",
            height=180,
        )
        _render_knowledge_selection(page, inquiry_text)

    submitted = False
    with render_work_card(
        page["section_case_info"],
        item_badge_label(summary, "case_info"),
        expanded=True,
        key="card_case_info",
    ):
        with st.form("technical_case_intake"):
            case_name = st.text_input(page["case_name"], key="input_case_name")
            customer_name = st.text_input(page["customer_name"], key="input_customer_name")
            end_user_name = st.text_input(page["end_user_name"], key="input_end_user_name")
            st.caption(page["end_user_hint"])
            submitted = st.form_submit_button(
                page["analyze_button"],
                key="analyze_inquiry",
                type="primary",
            )

    if submitted:
        existing_case = st.session_state.get(SESSION_CASE)
        run = run_technical_case_analysis(
            case_name,
            customer_name,
            end_user_name,
            inquiry_text,
            selected_fact_ids=_selected_fact_ids(inquiry_text),
            case_id=existing_case.case_id if existing_case is not None else None,
            created_at=existing_case.created_at if existing_case is not None else None,
        )
        st.session_state[SESSION_RUN] = run
        st.session_state[SESSION_CASE] = run.case
        st.session_state[SESSION_INQUIRY] = run.inquiry_text
        st.session_state[SESSION_ANALYSIS] = run.analysis_json
        persist_technical_case(st.session_state, run)

    run = st.session_state.get(SESSION_RUN)
    analyzed = bool(run and run.success)
    with render_work_card(
        page["section_results"],
        item_badge_label(summary, "requirements"),
        expanded=run is None or analyzed,
        key="card_results",
    ):
        _render_run_result(page, run)

    with render_work_card(
        page["retrieved_facts_label"],
        item_badge_label(summary, "knowledge"),
        expanded=analyzed,
        key="card_knowledge",
    ):
        if analyzed:
            _render_retrieved_facts(page, run)
        else:
            st.text(page["no_results"])

    with render_work_card(
        page["section_manufacturer_checks"],
        item_badge_label(summary, "human_review") if summary.review_required else item_badge_label(summary, "manufacturer_questions"),
        expanded=analyzed,
        key="card_manufacturer_questions",
    ):
        if analyzed:
            _render_question_section(page["section_manufacturer_checks"], run.manufacturer_questions, page)
        else:
            st.text(page["no_results"])

    with render_work_card(
        page["section_manufacturer_response"],
        item_badge_label(summary, "manufacturer_response"),
        expanded=True,
        key="card_manufacturer_response",
    ):
        _render_manufacturer_response_section(page, run)

    with render_work_card(
        page.get("section_evidence", "Evidence Validation"),
        item_badge_label(summary, "evidence_validation"),
        expanded=bool(st.session_state.get(SESSION_RESPONSE_RUN)),
        key="card_evidence",
    ):
        _render_evidence_card(page, st.session_state.get(SESSION_RESPONSE_RUN))

    with render_work_card(
        page.get("section_customer_reply", "顧客回答準備"),
        item_badge_label(summary, "customer_reply"),
        expanded=bool(st.session_state.get(SESSION_APPROVAL_BOARD)),
        key="card_customer_reply",
    ):
        board = st.session_state.get(SESSION_APPROVAL_BOARD)
        if board:
            _render_approval_summary(page, board)
        else:
            st.text(page.get("response_no_results", page["no_results"]))

    _render_technical_fact_view(page)
    _render_recent_cases(page)


def _current_work_summary():
    record = None
    saved_id = st.session_state.get("technical_case_saved_id")
    if saved_id:
        record = get_technical_case_repository().get_case(saved_id)
    return summarize_technical_case(
        inquiry_text=st.session_state.get("input_customer_inquiry") or st.session_state.get(SESSION_INQUIRY),
        case_name=st.session_state.get("input_case_name"),
        customer_name=st.session_state.get("input_customer_name"),
        run=st.session_state.get(SESSION_RUN),
        response_run=st.session_state.get(SESSION_RESPONSE_RUN),
        record=record,
    )


def _render_case_summary(page: dict, summary) -> None:
    status_labels = page.get("case_status", {})
    with st.container(border=True):
        cols = st.columns([2, 1])
        with cols[0]:
            st.markdown(f"**{summary.title or page.get('unnamed_item', '項目')}**")
            st.write(summary.customer or page.get("no_value", "-"))
            st.caption(f"{page.get('end_user_name', 'End User')}: {st.session_state.get('input_end_user_name') or '-'}")
        with cols[1]:
            st.caption(
                f"{page.get('case_status_label', '案件状態')}: "
                f"{status_labels.get(summary.process_status, summary.process_label())}"
            )
            render_progress_summary(summary, page)
            st.caption(f"{page.get('provider_label', 'AI Provider')}: {summary.provider or '-'}")
            st.caption(f"{page.get('model_label', 'Model')}: {summary.model or '-'}")
            if summary.updated_at:
                st.caption(f"{page.get('updated_at_label', '最終更新')}: {summary.updated_at}")
            record = _current_record()
            if record is not None and record.deleted_at:
                st.caption("ゴミ箱")
            elif record is not None and record.archived_at:
                st.caption("アーカイブ")


def _render_case_actions(page: dict) -> None:
    cols = st.columns(3)
    if cols[0].button(page.get("new_case_button", "新規案件"), key="new_technical_case", type="secondary"):
        start_new_technical_case(st.session_state)
        st.rerun()
    if cols[1].button(page.get("save_case_button", "保存"), key="save_technical_case", type="primary"):
        persist_technical_case(
            st.session_state,
            st.session_state.get(SESSION_RUN),
            st.session_state.get(SESSION_RESPONSE_RUN),
            st.session_state.get(SESSION_APPROVAL_BOARD),
        )
        st.rerun()
    with cols[2]:
        st.markdown("<div class='dt-complete-wrap'>", unsafe_allow_html=True)
        completed = st.button(page.get("complete_case_button", "案件を完了"), key="complete_technical_case", type="secondary")
        st.markdown("</div>", unsafe_allow_html=True)
        if completed:
            persist_technical_case(
                st.session_state,
                st.session_state.get(SESSION_RUN),
                st.session_state.get(SESSION_RESPONSE_RUN),
                st.session_state.get(SESSION_APPROVAL_BOARD),
                completed=True,
            )
            st.rerun()
    if st.session_state.get("technical_case_save_status") == "saved":
        st.success(page.get("case_saved", "案件を保存しました"))
    elif st.session_state.get("technical_case_save_error"):
        st.error(page.get("case_save_error", "案件を保存できませんでした"))


def _current_record():
    saved_id = st.session_state.get("technical_case_saved_id")
    if not saved_id:
        return None
    return get_technical_case_repository().get_case(saved_id)


def _render_case_lifecycle(texts: dict, page: dict) -> None:
    repo = get_technical_case_repository()
    record = _current_record()
    action = render_case_actions_menu(page, texts, record)
    if action and record is not None:
        relation = st.session_state.pop("case_derive_relation", None)
        updated = apply_case_lifecycle(record, repo, action, relation_type=relation)
        repo.save_case(updated)
        from agents.activity_log import record_case_lifecycle
        from repositories.sqlite_activity_repository import SqliteActivityRepository

        record_case_lifecycle(SqliteActivityRepository(repo.path), updated, action, previous=record)
        if action in {"duplicate", "derive"}:
            resume_case_into_session(updated, st.session_state)
        elif action in {"archive", "trash", "restore"}:
            st.session_state["technical_case_saved_id"] = updated.case_id
        st.rerun()
    if record is None:
        return
    parent = repo.get_case(record.parent_case_id) if record.parent_case_id else None
    children = repo.list_child_cases(record.case_id)

    def _open_parent():
        if parent is not None:
            resume_case_into_session(parent, st.session_state)
            st.rerun()

    def _open_child(child):
        loaded = repo.get_case(child.case_id)
        if loaded is not None:
            resume_case_into_session(loaded, st.session_state)
            st.rerun()

    render_lineage_card(
        texts=texts,
        parent=parent,
        children=children,
        kind="case",
        parent_open=_open_parent if parent is not None else None,
        child_open=_open_child,
    )


def _render_evidence_card(page: dict, run: Optional[ManufacturerResponseRun]) -> None:
    if run is None or not run.success:
        st.text(page.get("response_no_results", page["no_results"]))
        return
    shown = False
    for view in getattr(run, "matches", None) or []:
        validation = getattr(view, "validation", None)
        question = getattr(view, "question", None)
        if validation is None:
            continue
        shown = True
        label = getattr(question, "question", None) or page.get("unnamed_item", "項目")
        st.write(f"- {label}")
        if validation.reason:
            st.caption(
                f"{page.get('validation_reason_label', 'Validation')}: {validation.reason} / "
                f"review={validation.requires_human_review}"
            )
    if not shown:
        st.caption(page.get("validation_reason_label", "Validation"))


def _render_recent_cases(page: dict) -> None:
    repo = get_technical_case_repository()
    recent = repo.list_recent_cases()
    st.markdown(f"**{page.get('recent_cases_label', '最近の案件')}**")
    with st.expander(page.get("recent_cases_label", "最近の案件"), expanded=False):
        if not recent:
            st.caption(page.get("recent_cases_empty", "保存済み案件はまだありません"))
            return
        status_labels = page.get("case_status", {})
        for item in recent:
            label = " / ".join(
                part
                for part in (
                    item.customer_name or page.get("unnamed_item", "項目"),
                    item.case_title or page.get("unnamed_item", "項目"),
                    status_labels.get(item.status, item.status or "-"),
                    item.updated_at,
                    item.provider or "-",
                )
                if part
            )
            if st.button(
                f"{page.get('resume_case_button', '案件を再開')}: {label}",
                key=f"resume_technical_case_{item.case_id}",
                type="secondary",
            ):
                st.session_state["pending_resume_case_id"] = item.case_id
                st.rerun()


def _apply_pending_resume() -> None:
    case_id = st.session_state.pop("pending_resume_case_id", None)
    if not case_id:
        return
    loaded = get_technical_case_repository().get_case(case_id)
    if loaded is not None:
        resume_case_into_session(loaded, st.session_state)


def _missing_key_text(page: dict) -> str:
    if get_active_provider_name() == "gemini":
        return page.get("gemini_missing_api_key", "Gemini APIキーが設定されていません")
    return page["missing_api_key"]


def _render_provider_status(page: dict) -> None:
    status = get_provider_runtime_status()
    connection_labels = page.get(
        "connection_states",
        {"disconnected": "未接続", "connected": "接続済み", "error": "エラー"},
    )
    st.write(f"{page.get('provider_label', 'AI Provider')}: {status['provider_label']}")
    st.write(f"{page.get('model_label', 'Model')}: {status['model'] or page.get('no_value', '-')}")
    st.write(
        f"{page.get('connection_label', 'Connection')}: "
        f"{connection_labels.get(status['connection'], status['connection'])}"
    )
    if status.get("show_fallbacks"):
        st.caption(page.get("fallbacks_label", "Fallbacks") + f": {'ON' if status['fallbacks_enabled'] else 'OFF'}")
    if status.get("supports_connection_test"):
        if status.get("provider_id") == "ollama":
            button_label = page.get("ollama_connection_test_button", "Ollama接続テスト")
            button_key = status.get("connection_test_button_key") or "ollama_connection_test"
            failed_label = page.get("ollama_connection_error", "Ollama接続テストに失敗しました")
        elif status.get("provider_id") == "gemini":
            button_label = page.get("gemini_connection_test_button", "Gemini接続テスト")
            button_key = status.get("connection_test_button_key") or "gemini_connection_test"
            failed_label = page.get("gemini_connection_error", "Gemini接続テストに失敗しました")
        else:
            button_label = page.get("connection_test_button", "Claude接続テスト")
            button_key = status.get("connection_test_button_key") or "claude_connection_test"
            failed_label = page.get("connection_error", "Claude接続テストに失敗しました")
        if st.button(button_label, key=button_key, type="secondary"):
            st.session_state["provider_connection_test"] = run_provider_connection_test()
            st.rerun()
        result = st.session_state.get("provider_connection_test")
        if result is not None:
            if result.success:
                st.success(page.get("connection_ok", "Connection OK"))
            elif result.error_code == ERROR_MISSING_API_KEY:
                st.error(_missing_key_text(page))
            else:
                st.error(failed_label)
    usage = status.get("last_usage")
    if usage is not None:
        st.caption(
            f"tokens in={usage.input_tokens} out={usage.output_tokens} "
            f"status={usage.http_status} ms={usage.duration_ms}"
        )


def _render_run_result(page: dict, run: Optional[TechnicalCaseRun]) -> None:
    if run is None:
        _render_empty_sections(page)
        return

    if not run.success:
        if run.error_code == ERROR_MISSING_API_KEY:
            st.error(_missing_key_text(page))
        elif run.error_code == ERROR_COMPLETENESS:
            st.error(page.get("completeness_error", page["analysis_error"]))
        else:
            st.error(page["analysis_error"])
        if run.error_details:
            with st.expander(page["error_details_label"]):
                st.text(run.error_details)
        _render_empty_sections(page)
        return

    _render_summary_section(page, run)
    _render_completeness_issues(page, getattr(run, "completeness_issues", []))
    _render_requirement_section(page, run.requirements)
    _render_question_section(page["section_customer_checks"], run.customer_questions, page)
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


def _selected_fact_ids(inquiry_text: Optional[str]) -> list:
    products = detect_requested_products(inquiry_text)
    selected = []
    for item in retrieve_approved_facts_for_products(products):
        fact_id = item.get("fact_id") or ""
        if st.session_state.get(f"{FACT_SELECT_PREFIX}{fact_id}", is_default_selected(item)):
            selected.append(fact_id)
    return selected


def _render_knowledge_selection(page: dict, inquiry_text: Optional[str]) -> None:
    run = st.session_state.get(SESSION_RUN)
    snapshot = getattr(run, "knowledge_snapshot", None) if run is not None else None
    scope_labels = page.get("fact_scope", {})
    if snapshot is not None and snapshot.items:
        candidates = [
            {
                "fact_id": item.fact_id,
                "product": item.product,
                "topic": item.topic,
                "fact": item.statement,
                "source_reference": item.source_reference,
                "scope": item.scope,
                "status": item.status,
                "selected": item.selected,
            }
            for item in snapshot.items
        ]
        defaults = {item["fact_id"]: item["selected"] for item in candidates}
    else:
        products = detect_requested_products(inquiry_text)
        candidates = retrieve_approved_facts_for_products(products)
        defaults = {item.get("fact_id"): is_default_selected(item) for item in candidates}
    if not candidates:
        return
    st.markdown(f"**{page.get('knowledge_select_label', '参照する確認済み技術情報')}**")
    st.caption(page.get("knowledge_select_note", "使用しないFactはProviderへ送りません。"))
    for item in candidates:
        fact_id = item.get("fact_id") or ""
        st.checkbox(
            f"{item.get('product') or '-'} / {item.get('topic') or '-'}",
            value=defaults.get(fact_id, False),
            key=f"{FACT_SELECT_PREFIX}{fact_id}",
        )
        st.write(item.get("fact") or "")
        st.caption(
            f"{page.get('fact_source_label', '情報源')}: {item.get('source_reference') or '-'} / "
            f"{page.get('fact_scope_label', 'Scope')}: {scope_labels.get(item.get('scope'), item.get('scope'))} / "
            f"{page.get('fact_status_label', '承認状態')}: {item.get('status')}"
        )
        with st.expander(page.get("knowledge_detail_label", "詳細")):
            st.text(f"fact_id: {fact_id}")
            st.text(f"source_reference: {item.get('source_reference')}")


def _render_retrieved_facts(page: dict, run: TechnicalCaseRun) -> None:
    snapshot = getattr(run, "knowledge_snapshot", None)
    facts = getattr(run, "retrieved_facts", [])
    if snapshot is None and not facts:
        return
    st.markdown(f"**{page.get('retrieved_facts_label', '参照した承認済み技術情報')}**")
    st.caption(page.get("retrieved_facts_note", "人が承認した再利用Factです。この案件への適用は未確定です。"))
    if snapshot is not None:
        for item in snapshot.items:
            mark = page.get("knowledge_used", "使用") if item.selected else page.get("knowledge_unused", "未使用")
            st.write(f"- [{mark}] {item.product or '-'} / {item.topic or '-'}: {item.statement}")
            st.caption(f"{item.fact_id} / {item.source_reference or '-'} / {item.retrieved_at}")
        return
    confidence_labels = page.get("fact_confidence", {})
    for fact in facts:
        confidence = getattr(fact.confidence, "value", fact.confidence) if fact.confidence else None
        label = confidence_labels.get(confidence, confidence or page.get("no_value", "-"))
        st.write(f"- {fact.product or page.get('unnamed_item', '項目')} / {fact.topic or '-'}: {fact.fact}")
        st.caption(f"{page.get('fact_confidence_label', '確信度')}: {label}")


def _render_question_review_controls(page: dict, question: TechnicalQuestion) -> None:
    cols = st.columns(3)
    status_by_button = {
        0: "APPROVED",
        1: "EDITED",
        2: "REJECTED",
    }
    labels = [
        page.get("question_approve", "APPROVED"),
        page.get("question_edit", "EDITED"),
        page.get("question_reject", "REJECTED"),
    ]
    for index, column in enumerate(cols):
        if column.button(labels[index], key=f"qrev_{status_by_button[index]}_{question.question_id}"):
            run = st.session_state.get(SESSION_RUN)
            if run is None:
                return
            edited = question.question
            if status_by_button[index] == "EDITED":
                edited = st.session_state.get(f"qrev_text_{question.question_id}", question.question)
            updated = apply_question_review(question, status_by_button[index], edited)
            for offset, current in enumerate(run.manufacturer_questions):
                if current.question_id == question.question_id:
                    run.manufacturer_questions[offset] = updated
            persist_technical_case(
                st.session_state,
                run,
                st.session_state.get(SESSION_RESPONSE_RUN),
                st.session_state.get(SESSION_APPROVAL_BOARD),
            )
            st.rerun()
    if (question.classification or question.source) == "AI_SUGGESTED":
        st.caption(page.get("ai_suggested_not_auto", "AI_SUGGESTEDは自動APPROVEDしません。"))


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
        visible_questions = [item for item in questions if item.question]
        if not visible_questions:
            st.text(page["no_results"])
            return
        for item in visible_questions:
            suffix = ""
            if (item.classification or item.source) == "AI_SUGGESTED":
                suffix = f" ({page.get('ai_suggested_review', 'AI_SUGGESTED・要確認')})"
            st.write(f"- {item.question}{suffix}")
            st.caption(
                f"{page.get('question_class_label', 'classification')}: {item.classification or '-'} / "
                f"{page.get('question_source_label', 'source')}: {item.source or '-'} / "
                f"{page.get('question_review_label', 'Human Review')}: {item.review_status or 'PENDING'}"
            )
            if item.related_products:
                st.caption(f"{page.get('related_products_label', '関連product')}: {', '.join(item.related_products)}")
            if item.grounding:
                st.caption(f"{page.get('related_fact_label', '関連Fact')}: {item.grounding}")
            if item.original_text:
                st.caption(f"{page.get('original_text_label', 'customer wording')}: {item.original_text}")
            if item.review_status == "EDITED" and item.ai_original_question:
                st.caption(f"{page.get('ai_original_label', 'AI original')}: {item.ai_original_question}")
            if title == page["section_manufacturer_checks"]:
                _render_question_review_controls(page, item)
                st.text_area(
                    page.get("question_edit_label", "質問文"),
                    value=item.question or "",
                    key=f"qrev_text_{item.question_id}",
                )


def _render_completeness_issues(page: dict, issues: list) -> None:
    warnings = [item for item in issues if getattr(item, "severity", None) == "WARNING"]
    if not warnings:
        return
    with st.expander(page.get("completeness_warnings_label", "Completeness warnings"), expanded=False):
        for item in warnings:
            st.warning(getattr(item, "message", str(item)))


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
        persist_technical_case(
            st.session_state,
            inquiry_run,
            run,
            st.session_state.get(SESSION_APPROVAL_BOARD),
            append_response_revision=True,
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
        elif run.error_code == ERROR_MISSING_API_KEY:
            error_text = _missing_key_text(page)
        elif run.error_code == ERROR_COMPLETENESS:
            error_text = page.get("completeness_error", page["response_error"])
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
        validation = getattr(item, "validation", None)
        if validation is not None and validation.reason:
            st.caption(
                f"{page.get('validation_reason_label', 'Validation')}: {validation.reason} / "
                f"review={validation.requires_human_review}"
            )

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
                persist_technical_case(
                    st.session_state,
                    inquiry_run,
                    st.session_state.get(SESSION_RESPONSE_RUN),
                    board,
                )
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


def _render_technical_fact_view(page: dict) -> None:
    with st.expander(page.get("fact_catalog_label", "確認済み技術情報一覧"), expanded=False):
        st.caption(page.get("fact_catalog_note", "社内確認用です。Masterの参照であり、案件Snapshotではありません。"))
        for item in load_human_approved_catalog():
            st.write(f"- {item.get('product') or '-'} / {item.get('topic') or '-'}: {item.get('fact') or ''}")
            st.caption(
                f"{page.get('fact_status_label', '承認状態')}: {item.get('status') or '-'} / "
                f"{page.get('fact_scope_label', 'Scope')}: {item.get('scope') or '-'} / "
                f"{page.get('fact_source_label', '情報源')}: {item.get('source_reference') or '-'} / "
                f"approved_at: {item.get('approved_at') or '-'} / "
                f"superseded: {item.get('superseded')}"
            )


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
