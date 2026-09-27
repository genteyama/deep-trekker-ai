from __future__ import annotations

from datetime import datetime
from typing import Optional

from agents.quote_dates import apply_date_widget_defaults, date_widget_keys
from models import QuoteDraft
from repositories.quote_repository import QuoteRepository, QuoteRepositoryError, SaveResult
from ui.quote_steps import (
    SESSION_QUOTE_STEP,
    persist_review_key,
    restore_review_widget_state,
    save_review_widget_state,
)

SESSION_REPO = "quote_repository"
SESSION_SAVE_STATUS = "quote_save_status"
SESSION_SAVE_AT = "quote_save_at"
SESSION_SAVE_HASH = "quote_save_hash"
SESSION_SAVE_ERROR = "quote_save_error"


def get_quote_repository():
    import streamlit as st
    from repositories.sqlite_quote_repository import SqliteQuoteRepository

    repo = st.session_state.get(SESSION_REPO)
    if repo is None:
        repo = SqliteQuoteRepository()
        st.session_state[SESSION_REPO] = repo
    return repo


def collect_ui_state(session, draft: Optional[QuoteDraft] = None) -> dict:
    save_review_widget_state(session)
    state = {
        "step": session.get(SESSION_QUOTE_STEP, 1),
        "confirm_configuration": bool(session.get(persist_review_key("confirm_configuration"), session.get("confirm_configuration", False))),
        "confirm_presentation": bool(session.get(persist_review_key("confirm_presentation"), session.get("confirm_presentation", False))),
        "confirm_sales_price": bool(session.get(persist_review_key("confirm_sales_price"), session.get("confirm_sales_price", False))),
        "confirm_remarks": bool(session.get(persist_review_key("confirm_remarks"), session.get("confirm_remarks", False))),
        "selected_remarks": list(session.get(persist_review_key("input_selected_remarks"), session.get("input_selected_remarks", []))),
        "lead_time_text": session.get(persist_review_key("input_lead_time"), session.get("input_lead_time") or (draft.lead_time_text if draft else None)),
        "auto_valid_until": bool(getattr(draft, "auto_valid_until", True)) if draft is not None else True,
        "presentation_2601": session.get("input_2601_presentation"),
    }
    return state


def apply_ui_state(session, draft: QuoteDraft, ui_state: dict, *, init_dates) -> None:
    session[SESSION_QUOTE_STEP] = ui_state.get("step", 1)
    session[persist_review_key("confirm_configuration")] = bool(ui_state.get("confirm_configuration"))
    session[persist_review_key("confirm_presentation")] = bool(ui_state.get("confirm_presentation"))
    session[persist_review_key("confirm_sales_price")] = bool(ui_state.get("confirm_sales_price"))
    session[persist_review_key("confirm_remarks")] = bool(ui_state.get("confirm_remarks"))
    session[persist_review_key("input_selected_remarks")] = list(ui_state.get("selected_remarks") or [])
    session[persist_review_key("input_lead_time")] = ui_state.get("lead_time_text") or draft.lead_time_text or ""
    restore_review_widget_state(session)
    apply_date_widget_defaults(session, draft, overwrite=True)
    keys = date_widget_keys(draft.quote_draft_id)
    session[keys["auto"]] = bool(ui_state.get("auto_valid_until", draft.auto_valid_until))
    session.pop(keys["pending"], None)
    if ui_state.get("presentation_2601"):
        session["input_2601_presentation"] = ui_state["presentation_2601"]
    if callable(init_dates) and init_dates is not apply_date_widget_defaults:
        init_dates(draft, overwrite=True)


def maybe_autosave(repository: QuoteRepository, draft: QuoteDraft, session) -> SaveResult:
    ui_state = collect_ui_state(session, draft)
    result = repository.save_draft(draft, ui_state, force=False)
    _remember_result(session, result)
    return result


def save_draft_now(repository: QuoteRepository, draft: QuoteDraft, session) -> SaveResult:
    ui_state = collect_ui_state(session, draft)
    result = repository.save_draft(draft, ui_state, force=True)
    _remember_result(session, result)
    return result


def _remember_result(session, result: SaveResult) -> None:
    session[SESSION_SAVE_STATUS] = "saved" if result.saved else "skipped"
    session[SESSION_SAVE_AT] = result.updated_at
    session[SESSION_SAVE_HASH] = result.content_hash
    session[SESSION_SAVE_ERROR] = None


def format_saved_at(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%H:%M")
    except ValueError:
        return value


def persist_error_message(error: Exception) -> str:
    if isinstance(error, QuoteRepositoryError):
        return str(error)
    return f"{error}"
