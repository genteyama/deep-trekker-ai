from uuid import uuid4

from ui.quote_steps import SESSION_QUOTE_STEP

SESSION_QUOTE_HANDOFF_PENDING = "quote_handoff_pending"
SESSION_QUOTE_HANDOFF_CASE_ID = "quote_handoff_case_id"
SESSION_QUOTE_HANDOFF_CUSTOMER = "quote_handoff_customer"
SESSION_QUOTE_HANDOFF_TITLE = "quote_handoff_title"
SESSION_QUOTE_HANDOFF_PRODUCTS = "quote_handoff_products"

SOURCE_CASE_ID = "generic_quote_source_case_id"
SOURCE_PRODUCTS = "generic_quote_source_products"

_QUOTE_RUNTIME_KEYS = (
    "quote_draft",
    "approved_quote_snapshot",
    "quote_approval_validation",
    "quote_outputs",
)


def handoff_allowed(record) -> bool:
    if record is None or not getattr(record, "case_id", None):
        return False
    status = getattr(record, "case_lifecycle_status", None)
    status_value = getattr(status, "value", status)
    if status_value != "ACTIVE":
        return False
    if getattr(record, "archived_at", None) or getattr(record, "deleted_at", None):
        return False
    return True


def stage_quote_handoff(session, record) -> None:
    session[SESSION_QUOTE_HANDOFF_PENDING] = True
    session[SESSION_QUOTE_HANDOFF_CASE_ID] = record.case_id
    session[SESSION_QUOTE_HANDOFF_CUSTOMER] = record.customer_name or ""
    session[SESSION_QUOTE_HANDOFF_TITLE] = record.case_title or ""
    session[SESSION_QUOTE_HANDOFF_PRODUCTS] = [
        str(item) for item in (record.requested_products or []) if str(item).strip()
    ]


def apply_pending_quote_handoff(session) -> None:
    """Apply a staged handoff after navigation restore has copied older quote input."""
    if not session.get(SESSION_QUOTE_HANDOFF_PENDING):
        return
    session["generic_quote_customer"] = session.get(SESSION_QUOTE_HANDOFF_CUSTOMER) or ""
    session["generic_quote_title"] = session.get(SESSION_QUOTE_HANDOFF_TITLE) or ""
    session[SOURCE_CASE_ID] = session.get(SESSION_QUOTE_HANDOFF_CASE_ID) or None
    session[SOURCE_PRODUCTS] = list(session.get(SESSION_QUOTE_HANDOFF_PRODUCTS) or [])
    _reset_generic_entry(session)
    for key in _QUOTE_RUNTIME_KEYS:
        session.pop(key, None)
    session.pop("quote_save_error", None)
    conflict = session.get("edit_conflict")
    if isinstance(conflict, dict) and conflict.get("kind") == "quote":
        session.pop("edit_conflict", None)
    session[SESSION_QUOTE_STEP] = 1
    _clear_staged_handoff(session)


def clear_quote_handoff_source(session) -> None:
    """Drop the case relation. Customer and title inputs stay as entered."""
    session.pop(SOURCE_CASE_ID, None)
    session.pop(SOURCE_PRODUCTS, None)
    _clear_staged_handoff(session)


def _clear_staged_handoff(session) -> None:
    for key in (
        SESSION_QUOTE_HANDOFF_PENDING,
        SESSION_QUOTE_HANDOFF_CASE_ID,
        SESSION_QUOTE_HANDOFF_CUSTOMER,
        SESSION_QUOTE_HANDOFF_TITLE,
        SESSION_QUOTE_HANDOFF_PRODUCTS,
    ):
        session.pop(key, None)


def source_case_id(session):
    value = session.get(SOURCE_CASE_ID)
    if value is None or str(value).strip() == "":
        return None
    return str(value)


def _reset_generic_entry(session) -> None:
    for line in session.get("generic_quote_lines") or []:
        if not isinstance(line, dict):
            continue
        line_id = line.get("id")
        if not line_id:
            continue
        session.pop(f"generic_quote_sku_{line_id}", None)
        session.pop(f"generic_quote_qty_{line_id}", None)
    session["generic_quote_lines"] = [{"id": uuid4().hex, "sku": "", "quantity": 1}]
    session["generic_quote_international_shipping"] = ""
    session["generic_quote_domestic_shipping"] = ""
