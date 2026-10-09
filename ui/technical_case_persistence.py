from __future__ import annotations

from typing import Optional

from agents.approval import ApprovalBoard
from agents.technical_case_agent import ManufacturerResponseRun, TechnicalCaseRun
from agents.technical_case_persistence import (
    approval_board_from_dict,
    build_record,
    response_run_from_record,
    revision_from_response_run,
    run_from_record,
)
from models import TechnicalCaseRecord, TechnicalCaseStatus
from repositories.sqlite_technical_case_repository import SqliteTechnicalCaseRepository
from repositories.technical_case_repository import TechnicalCaseConflictError, TechnicalCaseRepositoryError
from ui.technical_case_flow import (
    SESSION_ANALYSIS,
    SESSION_APPROVAL_BOARD,
    SESSION_CASE,
    SESSION_INQUIRY,
    SESSION_RESPONSE_RUN,
    SESSION_RUN,
)
from ui.technical_case_steps import SESSION_CASE_STEP

SESSION_REPO = "technical_case_repository"
SESSION_RECORD_ID = "technical_case_saved_id"
SESSION_SAVE_STATUS = "technical_case_save_status"
SESSION_SAVE_ERROR = "technical_case_save_error"
FACT_SELECT_PREFIX = "use_fact_"
WIDGET_KEYS = (
    "input_customer_inquiry",
    "input_case_name",
    "input_customer_name",
    "input_end_user_name",
    "input_manufacturer_response",
)


def session_get(session, key, default=None):
    try:
        if key in session:
            return session[key]
    except Exception:
        pass
    return default


def get_technical_case_repository():
    import streamlit as st

    repo = st.session_state.get(SESSION_REPO)
    if repo is None:
        repo = SqliteTechnicalCaseRepository()
        st.session_state[SESSION_REPO] = repo
    return repo


def persist_technical_case(
    session,
    run: Optional[TechnicalCaseRun],
    response_run: Optional[ManufacturerResponseRun] = None,
    board: Optional[ApprovalBoard] = None,
    *,
    completed: bool = False,
    append_response_revision: bool = False,
    repository=None,
) -> Optional[TechnicalCaseRecord]:
    repo = repository or get_technical_case_repository()
    existing = None
    case_id = run.case.case_id if run is not None else session_get(session, SESSION_RECORD_ID)
    if case_id:
        existing = repo.get_case(case_id)
    if run is None and existing is None:
        from ui.technical_case_flow import build_case_from_inputs

        run = TechnicalCaseRun(
            success=False,
            case=build_case_from_inputs(
                session_get(session, "input_case_name"),
                session_get(session, "input_customer_name"),
                session_get(session, "input_end_user_name"),
            ),
            provider_name="",
            inquiry_text=session_get(session, "input_customer_inquiry"),
        )
    record = build_record(
        run,
        response_run,
        board,
        existing=existing,
        response_text=session_get(session, "input_manufacturer_response"),
        completed=completed,
    )
    try:
        repo.save_case(record)
        if append_response_revision and response_run is not None and response_run.success:
            saved = repo.save_manufacturer_response_result(
                record.case_id,
                revision_from_response_run(response_run),
                record=repo.get_case(record.case_id),
            )
        else:
            saved = repo.get_case(record.case_id)
        session[SESSION_RECORD_ID] = saved.case_id if saved else record.case_id
        session[SESSION_SAVE_STATUS] = "saved"
        session[SESSION_SAVE_ERROR] = None
        _record_case_activity(repo, existing, saved, response_received=append_response_revision, completed=completed)
        return saved
    except TechnicalCaseConflictError as error:
        # Never overwrite another user's update; the conflict banner offers a reload.
        session[SESSION_SAVE_STATUS] = "error"
        session[SESSION_SAVE_ERROR] = str(error)
        session["edit_conflict"] = {"kind": "technical_case", "key": error.key, "version": None}
        return None
    except TechnicalCaseRepositoryError as error:
        session[SESSION_SAVE_STATUS] = "error"
        session[SESSION_SAVE_ERROR] = str(error)
        raise


def resume_case_into_session(record: TechnicalCaseRecord, session) -> TechnicalCaseRun:
    repo = session_get(session, SESSION_REPO)
    if hasattr(repo, "mark_loaded"):
        # Opening a case makes the version loaded now the base for the next save.
        repo.mark_loaded(record.case_id)
    run = run_from_record(record)
    response_run = response_run_from_record(record)
    board = approval_board_from_dict(record.approval_board, response_run)
    session[SESSION_CASE] = run.case
    session[SESSION_RUN] = run
    session[SESSION_RESPONSE_RUN] = response_run
    session[SESSION_APPROVAL_BOARD] = board
    session[SESSION_INQUIRY] = record.original_inquiry
    session[SESSION_ANALYSIS] = record.analysis_json
    session[SESSION_RECORD_ID] = record.case_id
    session["input_customer_inquiry"] = record.original_inquiry or ""
    session["input_case_name"] = record.case_title or ""
    session["input_customer_name"] = record.customer_name or ""
    session["input_end_user_name"] = record.end_user_name or ""
    session["input_manufacturer_response"] = record.manufacturer_response_input or ""
    snapshot = record.knowledge_snapshot or {}
    for item in snapshot.get("items") or []:
        fact_id = item.get("fact_id")
        if fact_id:
            session[f"{FACT_SELECT_PREFIX}{fact_id}"] = bool(item.get("selected"))
    return run


def start_new_technical_case(session) -> None:
    for key in (
        SESSION_RUN,
        SESSION_RESPONSE_RUN,
        SESSION_APPROVAL_BOARD,
        SESSION_CASE,
        SESSION_INQUIRY,
        SESSION_ANALYSIS,
        SESSION_RECORD_ID,
        SESSION_SAVE_STATUS,
        SESSION_SAVE_ERROR,
        SESSION_CASE_STEP,
        "technical_case_close_form",
        "technical_case_close_reason",
        "technical_case_close_memo",
        *WIDGET_KEYS,
    ):
        if key in session:
            del session[key]
    for key in list(session.keys()) if hasattr(session, "keys") else []:
        if str(key).startswith(FACT_SELECT_PREFIX) or str(key).startswith("qrev_"):
            del session[key]


def mark_completed(session, repository=None) -> Optional[TechnicalCaseRecord]:
    return persist_technical_case(
        session,
        session_get(session, "technical_case_run"),
        session_get(session, "manufacturer_response_run"),
        session_get(session, "manufacturer_approval_board"),
        completed=True,
        repository=repository,
    )


def status_is_completed(status: Optional[str]) -> bool:
    return status == TechnicalCaseStatus.COMPLETED.value


def _record_case_activity(repo, existing, saved, *, response_received: bool, completed: bool) -> None:
    if saved is None:
        return
    from agents.activity_log import record_case_saved
    from repositories.sqlite_activity_repository import SqliteActivityRepository
    from repositories.sqlite_customer_repository import SqliteCustomerRepository
    from models import CustomerRecord

    path = getattr(repo, "path", None)
    record_case_saved(
        SqliteActivityRepository(path),
        existing,
        saved,
        response_received=response_received and existing is not None,
        completed=completed,
    )
    if saved.customer_name:
        customers = SqliteCustomerRepository(path)
        found = customers.find(saved.customer_name, None)
        if found is None:
            customers.save(
                CustomerRecord(
                    customer_id="",
                    customer_name=saved.customer_name,
                    end_user=saved.end_user_name,
                )
            )
        elif saved.end_user_name and not found.end_user:
            customers.save(found.model_copy(update={"end_user": saved.end_user_name}))
