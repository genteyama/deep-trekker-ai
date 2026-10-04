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
PENDING_FORM_KEY = "quote_pending_form"

SHIPPING_PRICE_KEY = "input_draft_shipping_price"
TAX_RATE_KEY = "input_draft_tax_rate"
PRESENTATION_2601_KEY = "input_2601_presentation"
OFFICIAL_QUOTE_NUMBER_KEY = "input_official_quote_number"
GENERATED_BY_KEY = "input_export_generated_by"
AMBIGUOUS_SKU_REASON = "ambiguous_sku"


def session_get(session, key, default=None):
    try:
        if key in session:
            return session[key]
    except Exception:
        pass
    return default


def get_quote_repository():
    import streamlit as st
    from repositories.sqlite_quote_repository import SqliteQuoteRepository

    repo = st.session_state.get(SESSION_REPO)
    if repo is None:
        repo = SqliteQuoteRepository()
        st.session_state[SESSION_REPO] = repo
    return repo


def manual_price_widget_key(line_id: str) -> str:
    return f"manual_price_{line_id}"


def customer_description_widget_key(line_id: str) -> str:
    return f"pending_customer_description_{line_id}"


def empty_ui_state(step: int = 1) -> dict:
    return {
        "schema_version": 3,
        "step": step,
        "current_step": step,
        "pending_final_prices": {},
        "pending_final_price_reviews": [],
        "pending_shipping_customer_price": "",
        "pending_tax_rate": "",
        "pending_customer_descriptions": {},
        "pending_presentation_modes": {},
        "selected_remarks": [],
        "lead_time_text": "",
        "issue_date": None,
        "valid_until": None,
        "auto_valid_until": True,
        "confirm_configuration": False,
        "confirm_presentation": False,
        "confirm_sales_price": False,
        "confirm_remarks": False,
        "presentation_2601": None,
        "pending_official_quote_number": "",
        "pending_generated_by": "",
    }


def migrate_pending_final_prices(prices: dict, draft: Optional[QuoteDraft]) -> tuple[dict, list[dict]]:
    raw = dict(prices or {})
    if draft is None:
        return raw, []
    line_ids = {line.line_id for line in draft.configuration_lines}
    by_sku = {}
    for line in draft.configuration_lines:
        sku = line.manufacturer_sku
        if sku:
            by_sku.setdefault(sku, []).append(line.line_id)
    canonical = {key: value for key, value in raw.items() if key in line_ids}
    reviews = []
    for key, value in raw.items():
        if key in line_ids:
            continue
        matches = by_sku.get(key) or []
        if len(matches) == 1:
            line_id = matches[0]
            if line_id not in canonical:
                canonical[line_id] = value
            continue
        if len(matches) > 1:
            reviews.append(
                {
                    "sku": key,
                    "amount": value,
                    "reason": AMBIGUOUS_SKU_REASON,
                    "candidate_line_ids": list(matches),
                }
            )
    return canonical, reviews


def collect_ui_state(session, draft: Optional[QuoteDraft] = None, *, from_widgets: bool = True) -> dict:
    save_review_widget_state(session)
    if from_widgets:
        sync_pending_from_widgets(session, draft)
    stored = dict(session_get(session, PENDING_FORM_KEY) or {})
    dates = _collect_dates(session, draft)
    stored.update(dates)
    step = session_get(session, SESSION_QUOTE_STEP, stored.get("current_step", stored.get("step", 1)))
    remarks = session_get(session, persist_review_key("input_selected_remarks"))
    if remarks is None:
        remarks = session_get(session, "input_selected_remarks", stored.get("selected_remarks", []))
    lead = session_get(session, persist_review_key("input_lead_time"))
    if lead is None:
        lead = session_get(session, "input_lead_time", stored.get("lead_time_text") or (draft.lead_time_text if draft else None))
    prices, reviews = migrate_pending_final_prices(stored.get("pending_final_prices") or {}, draft)
    stored_reviews = list(stored.get("pending_final_price_reviews") or [])
    if reviews:
        stored_reviews = reviews
    state = empty_ui_state(step)
    state.update(
        {
            "pending_final_prices": prices,
            "pending_final_price_reviews": stored_reviews,
            "pending_shipping_customer_price": stored.get("pending_shipping_customer_price", ""),
            "pending_tax_rate": stored.get("pending_tax_rate", ""),
            "pending_customer_descriptions": dict(stored.get("pending_customer_descriptions") or {}),
            "pending_presentation_modes": dict(stored.get("pending_presentation_modes") or {}),
            "selected_remarks": list(remarks or []),
            "lead_time_text": lead or "",
            "issue_date": dates.get("issue_date"),
            "valid_until": dates.get("valid_until"),
            "auto_valid_until": dates.get("auto_valid_until"),
            "pending_official_quote_number": stored.get("pending_official_quote_number", ""),
            "pending_generated_by": stored.get("pending_generated_by", ""),
            "confirm_configuration": bool(
                session_get(
                    session,
                    persist_review_key("confirm_configuration"),
                    session_get(session, "confirm_configuration", stored.get("confirm_configuration", False)),
                )
            ),
            "confirm_presentation": bool(
                session_get(
                    session,
                    persist_review_key("confirm_presentation"),
                    session_get(session, "confirm_presentation", stored.get("confirm_presentation", False)),
                )
            ),
            "confirm_sales_price": bool(
                session_get(
                    session,
                    persist_review_key("confirm_sales_price"),
                    session_get(session, "confirm_sales_price", stored.get("confirm_sales_price", False)),
                )
            ),
            "confirm_remarks": bool(
                session_get(
                    session,
                    persist_review_key("confirm_remarks"),
                    session_get(session, "confirm_remarks", stored.get("confirm_remarks", False)),
                )
            ),
            "presentation_2601": (stored.get("pending_presentation_modes") or {}).get("2601")
            or session_get(session, PRESENTATION_2601_KEY),
        }
    )
    session[PENDING_FORM_KEY] = {
        key: state[key]
        for key in (
            "step",
            "current_step",
            "pending_final_prices",
            "pending_final_price_reviews",
            "pending_shipping_customer_price",
            "pending_tax_rate",
            "pending_customer_descriptions",
            "pending_presentation_modes",
            "selected_remarks",
            "lead_time_text",
            "issue_date",
            "valid_until",
            "auto_valid_until",
            "confirm_configuration",
            "confirm_presentation",
            "confirm_sales_price",
            "confirm_remarks",
            "pending_official_quote_number",
            "pending_generated_by",
        )
    }
    return state


def apply_ui_state(session, draft: QuoteDraft, ui_state: dict, *, init_dates) -> None:
    state = ui_state or {}
    step = state.get("current_step", state.get("step", 1))
    session[SESSION_QUOTE_STEP] = step
    prices, reviews = migrate_pending_final_prices(state.get("pending_final_prices") or {}, draft)
    pending = {
        "step": step,
        "pending_final_prices": prices,
        "pending_final_price_reviews": list(state.get("pending_final_price_reviews") or reviews),
        "pending_shipping_customer_price": state.get("pending_shipping_customer_price") or "",
        "pending_tax_rate": state.get("pending_tax_rate") or "",
        "pending_customer_descriptions": dict(state.get("pending_customer_descriptions") or {}),
        "pending_presentation_modes": dict(state.get("pending_presentation_modes") or {}),
        "selected_remarks": list(state.get("selected_remarks") or []),
        "lead_time_text": state.get("lead_time_text") or draft.lead_time_text or "",
        "issue_date": draft.issue_date,
        "valid_until": draft.valid_until,
        "auto_valid_until": bool(getattr(draft, "auto_valid_until", True)),
        "confirm_configuration": bool(state.get("confirm_configuration")),
        "confirm_presentation": bool(state.get("confirm_presentation")),
        "confirm_sales_price": bool(state.get("confirm_sales_price")),
        "confirm_remarks": bool(state.get("confirm_remarks")),
        "pending_official_quote_number": state.get("pending_official_quote_number") or "",
        "pending_generated_by": state.get("pending_generated_by") or "",
    }
    if reviews:
        pending["pending_final_price_reviews"] = reviews
    if state.get("presentation_2601") and "2601" not in pending["pending_presentation_modes"]:
        pending["pending_presentation_modes"]["2601"] = state["presentation_2601"]
    session[PENDING_FORM_KEY] = pending
    session[persist_review_key("confirm_configuration")] = pending["confirm_configuration"]
    session[persist_review_key("confirm_presentation")] = pending["confirm_presentation"]
    session[persist_review_key("confirm_sales_price")] = pending["confirm_sales_price"]
    session[persist_review_key("confirm_remarks")] = pending["confirm_remarks"]
    session[persist_review_key("input_selected_remarks")] = pending["selected_remarks"]
    session[persist_review_key("input_lead_time")] = pending["lead_time_text"] or ""
    restore_review_widget_state(session)
    _restore_pending_widgets(session, draft, pending)
    _restore_date_widgets(session, draft, state, init_dates)


def restore_pending_form_widgets(session, draft: Optional[QuoteDraft] = None) -> None:
    restore_review_widget_state(session)
    stored = session_get(session, PENDING_FORM_KEY) or {}
    if stored:
        _restore_pending_widgets(session, draft, stored)


def _mounted_text(session, key, *, mounted: bool):
    if key not in session:
        return None
    value = "" if session[key] is None else str(session[key])
    if mounted or value != "":
        return value
    return None


def sync_pending_from_widgets(session, draft: Optional[QuoteDraft] = None) -> None:
    stored = dict(session_get(session, PENDING_FORM_KEY) or {})
    prices = dict(stored.get("pending_final_prices") or {})
    descriptions = dict(stored.get("pending_customer_descriptions") or {})
    presentations = dict(stored.get("pending_presentation_modes") or {})
    step = session_get(session, SESSION_QUOTE_STEP, stored.get("current_step", stored.get("step", 1)))
    if draft is not None:
        prices, _reviews = migrate_pending_final_prices(prices, draft)
        for line in draft.configuration_lines:
            value = _mounted_text(session, manual_price_widget_key(line.line_id), mounted=step == 2)
            if value is not None:
                prices[line.line_id] = value
        for line in draft.customer_lines:
            value = _mounted_text(session, customer_description_widget_key(line.customer_quote_line_id), mounted=step == 3)
            if value is not None:
                descriptions[line.customer_quote_line_id] = value
    for key, value in list(session.items()):
        if isinstance(key, str) and key.startswith("manual_price_"):
            text = "" if value is None else str(value)
            if step == 2 or text != "":
                prices[key.replace("manual_price_", "", 1)] = text
        if isinstance(key, str) and key.startswith("pending_customer_description_"):
            text = "" if value is None else str(value)
            if step == 3 or text != "":
                descriptions[key.replace("pending_customer_description_", "", 1)] = text
    shipping = _mounted_text(session, SHIPPING_PRICE_KEY, mounted=step == 2)
    if shipping is not None:
        stored["pending_shipping_customer_price"] = shipping
    tax = _mounted_text(session, TAX_RATE_KEY, mounted=step == 3)
    if tax is not None:
        stored["pending_tax_rate"] = tax
    if PRESENTATION_2601_KEY in session and (step == 1 or session[PRESENTATION_2601_KEY]):
        presentations["2601"] = session[PRESENTATION_2601_KEY]
    official = _mounted_text(session, OFFICIAL_QUOTE_NUMBER_KEY, mounted=step == 5)
    if official is not None:
        stored["pending_official_quote_number"] = official
    generated = _mounted_text(session, GENERATED_BY_KEY, mounted=step == 5)
    if generated is not None:
        stored["pending_generated_by"] = generated
    if draft is not None:
        prices, reviews = migrate_pending_final_prices(prices, draft)
        if reviews:
            stored["pending_final_price_reviews"] = reviews
    stored["pending_final_prices"] = prices
    stored["pending_customer_descriptions"] = descriptions
    stored["pending_presentation_modes"] = presentations
    stored["step"] = step
    stored["current_step"] = step
    session[PENDING_FORM_KEY] = stored


def clear_pending_final_price(session, line) -> None:
    stored = dict(session_get(session, PENDING_FORM_KEY) or {})
    prices = dict(stored.get("pending_final_prices") or {})
    prices.pop(getattr(line, "line_id", ""), None)
    stored["pending_final_prices"] = prices
    session[PENDING_FORM_KEY] = stored


def clear_pending_shipping(session) -> None:
    stored = dict(session_get(session, PENDING_FORM_KEY) or {})
    stored["pending_shipping_customer_price"] = ""
    session[PENDING_FORM_KEY] = stored


def clear_pending_tax(session) -> None:
    stored = dict(session_get(session, PENDING_FORM_KEY) or {})
    stored["pending_tax_rate"] = ""
    session[PENDING_FORM_KEY] = stored


def clear_pending_description(session, line_id: str) -> None:
    stored = dict(session_get(session, PENDING_FORM_KEY) or {})
    descriptions = dict(stored.get("pending_customer_descriptions") or {})
    descriptions.pop(line_id, None)
    stored["pending_customer_descriptions"] = descriptions
    session[PENDING_FORM_KEY] = stored


def clear_pending_presentation(session, sku: str = "2601") -> None:
    stored = dict(session_get(session, PENDING_FORM_KEY) or {})
    presentations = dict(stored.get("pending_presentation_modes") or {})
    presentations.pop(sku, None)
    stored["pending_presentation_modes"] = presentations
    session[PENDING_FORM_KEY] = stored


def reset_pending_form(session, step: int = 1) -> None:
    session[PENDING_FORM_KEY] = empty_ui_state(step)


def maybe_autosave(repository: QuoteRepository, draft: QuoteDraft, session, *, from_widgets: bool = True) -> SaveResult:
    previous = repository.get_draft(draft.quote_draft_id, draft.quote_version)
    ui_state = collect_ui_state(session, draft, from_widgets=from_widgets)
    result = repository.save_draft(draft, ui_state, force=False)
    _remember_result(session, result)
    if result.saved:
        _record_quote_activity(repository, previous, draft)
    return result


def save_draft_now(repository: QuoteRepository, draft: QuoteDraft, session, *, from_widgets: bool = True) -> SaveResult:
    previous = repository.get_draft(draft.quote_draft_id, draft.quote_version)
    ui_state = collect_ui_state(session, draft, from_widgets=from_widgets)
    result = repository.save_draft(draft, ui_state, force=True)
    _remember_result(session, result)
    if result.saved:
        _record_quote_activity(repository, previous, draft)
    return result


def _record_quote_activity(repository, previous, draft) -> None:
    from agents.activity_log import record_quote_saved
    from repositories.sqlite_activity_repository import SqliteActivityRepository
    from repositories.sqlite_customer_repository import SqliteCustomerRepository
    from models import CustomerRecord

    path = getattr(repository, "path", None)
    record_quote_saved(
        SqliteActivityRepository(path),
        None if previous is None else previous.draft,
        draft,
        derived=bool(getattr(draft, "parent_quote_id", None)) and previous is None,
    )
    if draft.customer:
        customers = SqliteCustomerRepository(path)
        if customers.find(draft.customer, None) is None:
            customers.save(CustomerRecord(customer_id="", customer_name=draft.customer))


def _restore_pending_widgets(session, draft: Optional[QuoteDraft], pending: dict) -> None:
    prices, reviews = migrate_pending_final_prices(pending.get("pending_final_prices") or {}, draft)
    if reviews:
        pending["pending_final_price_reviews"] = reviews
        pending["pending_final_prices"] = prices
    if draft is not None:
        for line in draft.configuration_lines:
            value = prices.get(line.line_id)
            if value is not None:
                key = manual_price_widget_key(line.line_id)
                if key not in session:
                    session[key] = value
        for line in draft.customer_lines:
            value = (pending.get("pending_customer_descriptions") or {}).get(line.customer_quote_line_id)
            if value is not None:
                key = customer_description_widget_key(line.customer_quote_line_id)
                if key not in session:
                    session[key] = value
    else:
        for line_id, value in prices.items():
            key = manual_price_widget_key(line_id)
            if key not in session:
                session[key] = value
    shipping = pending.get("pending_shipping_customer_price")
    if shipping not in (None, "") and SHIPPING_PRICE_KEY not in session:
        session[SHIPPING_PRICE_KEY] = shipping
    tax = pending.get("pending_tax_rate")
    if tax not in (None, "") and TAX_RATE_KEY not in session:
        session[TAX_RATE_KEY] = tax
    presentation = (pending.get("pending_presentation_modes") or {}).get("2601")
    if presentation and PRESENTATION_2601_KEY not in session:
        session[PRESENTATION_2601_KEY] = presentation
    official = pending.get("pending_official_quote_number")
    if official not in (None, "") and OFFICIAL_QUOTE_NUMBER_KEY not in session:
        session[OFFICIAL_QUOTE_NUMBER_KEY] = official
    generated = pending.get("pending_generated_by")
    if generated not in (None, "") and GENERATED_BY_KEY not in session:
        session[GENERATED_BY_KEY] = generated


def _collect_dates(session, draft: Optional[QuoteDraft]) -> dict:
    if draft is not None:
        return {
            "issue_date": draft.issue_date,
            "valid_until": draft.valid_until,
            "auto_valid_until": bool(getattr(draft, "auto_valid_until", True)),
        }
    stored = session_get(session, PENDING_FORM_KEY) or {}
    return {
        "issue_date": stored.get("issue_date"),
        "valid_until": stored.get("valid_until"),
        "auto_valid_until": stored.get("auto_valid_until", True),
    }


def _restore_date_widgets(session, draft: QuoteDraft, ui_state: dict, init_dates) -> None:
    keys = date_widget_keys(draft.quote_draft_id)
    apply_date_widget_defaults(session, draft, overwrite=False)
    session.pop(keys["pending"], None)
    if callable(init_dates) and init_dates is not apply_date_widget_defaults:
        init_dates(draft, overwrite=False)


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
