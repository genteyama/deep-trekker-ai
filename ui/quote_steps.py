from __future__ import annotations

from agents.pricing_policy import DEFAULT_QUOTE_EXCHANGE_RATE
from agents.sku_link import is_official_price_snapshot, price_source_type_of
from models import (
    CustomerPresentationMode,
    ExchangeRateSource,
    PriceSourceType,
    QuoteDraftStatus,
    RequirementType,
)
from ui.quote_format import display_number

SESSION_QUOTE_STEP = "quote_workspace_step"
SESSION_NEW_QUOTE_FX = "quote_new_exchange_rate"
SESSION_NEW_QUOTE_FX_CHANGED = "quote_new_exchange_rate_changed"
SESSION_FX_EDITOR = "quote_fx_editor"
SESSION_FX_EDITOR_TOKEN = "quote_fx_editor_token"
# Exchange rate decision metadata inputs, keyed by pricing_context field.
FX_METADATA_KEYS = {
    "market_reference_rate": "quote_fx_market_rate",
    "market_reference_date": "quote_fx_market_date",
    "market_reference_source": "quote_fx_market_source",
    "exchange_rate_buffer": "quote_fx_buffer",
    "exchange_rate_reason_code": "quote_fx_reason",
    "exchange_rate_reason_note": "quote_fx_reason_note",
    "exchange_rate_set_by": "quote_fx_set_by",
}
REVIEW_WIDGET_KEYS = (
    "confirm_configuration",
    "confirm_presentation",
    "confirm_sales_price",
    "confirm_remarks",
    "input_selected_remarks",
    "input_lead_time",
)


def persist_review_key(key: str) -> str:
    return f"quote_persist_{key}"


def restore_review_widget_state(session) -> None:
    for key in REVIEW_WIDGET_KEYS:
        stored = persist_review_key(key)
        if key not in session and stored in session:
            session[key] = session[stored]


def save_review_widget_state(session) -> None:
    for key in REVIEW_WIDGET_KEYS:
        if key in session:
            session[persist_review_key(key)] = session[key]


QUOTE_STEP_IDS = (1, 2, 3, 4, 5)
STEP_KEYS = {
    1: "configuration",
    2: "costing",
    3: "customer",
    4: "review",
    5: "export",
}
INTERNAL_CUSTOMER_VIEW_KEYS = {
    "landed_cost_jpy",
    "dealer_price_usd",
    "dealer_cost_jpy",
    "import_tax_jpy",
    "insurance_jpy",
    "gross_margin_rate",
    "gross_profit_jpy",
    "standard_sales_price_candidate_jpy",
    "manufacturer_price_snapshot",
}

STATUS_MARK = {
    "done": "✓",
    "current": "●",
    "todo": "○",
}


def normalize_quote_step(value) -> int:
    try:
        step = int(value)
    except (TypeError, ValueError):
        return 1
    return step if step in QUOTE_STEP_IDS else 1


def step_button_key(step: int) -> str:
    return f"quote_step_{step}"


def unresolved_required_lines(draft) -> list:
    if draft is None:
        return []
    return [
        line
        for line in draft.configuration_lines
        if line.requirement_type == RequirementType.REQUIRED_DEPENDENCY
        and line.customer_presentation_status == CustomerPresentationMode.UNDECIDED
    ]


def non_official_price_lines(draft) -> list:
    if draft is None:
        return []
    return [
        line
        for line in draft.configuration_lines
        if line.manufacturer_price_snapshot is not None
        and not is_official_price_snapshot(line.manufacturer_price_snapshot)
    ]


def price_source_display(workspace: dict, line) -> tuple[str, str]:
    snapshot = line.manufacturer_price_snapshot
    source = price_source_type_of(snapshot).value
    sources = workspace.get("price_sources", {})
    states = workspace.get("price_states", {})
    if source == PriceSourceType.OFFICIAL_PRICE_BOOK.value:
        book = snapshot.price_book or workspace.get("official_price_book_fallback", "")
        label = sources.get(source, "{price_book}").format(price_book=book)
    else:
        label = sources.get(source, source)
    return label, states.get(source, source)


def reference_value(text: str, line, workspace: dict) -> str:
    if line.manufacturer_price_snapshot is not None and not is_official_price_snapshot(line.manufacturer_price_snapshot):
        return f"{text}{workspace.get('reference_value_suffix', '')}"
    return text


def ensure_new_quote_exchange_rate(session) -> None:
    if not session.get(SESSION_NEW_QUOTE_FX):
        session[SESSION_NEW_QUOTE_FX] = display_number(DEFAULT_QUOTE_EXCHANGE_RATE, "")


def mark_new_quote_exchange_rate_changed(session) -> None:
    session[SESSION_NEW_QUOTE_FX_CHANGED] = True


def new_quote_exchange_rate_source(session) -> ExchangeRateSource:
    # Decided by what the person did, not by the value: 160 typed by a person is still a manual choice.
    if session.get(SESSION_NEW_QUOTE_FX_CHANGED):
        return ExchangeRateSource.MANUAL_OVERRIDE
    return ExchangeRateSource.STANDARD_DEFAULT


def sync_exchange_rate_editor(session, draft) -> None:
    # The saved draft is the source of truth; the editor is reset whenever another draft/version/rate is shown.
    token = f"{draft.quote_draft_id}:{draft.quote_version}:{draft.exchange_rate}"
    if session.get(SESSION_FX_EDITOR_TOKEN) != token:
        session[SESSION_FX_EDITOR] = display_number(draft.exchange_rate, "")
        context = draft.pricing_context
        for field, key in FX_METADATA_KEYS.items():
            value = getattr(context, field, None)
            if field == "exchange_rate_reason_code":
                session[key] = getattr(value, "value", value) or ""
            elif isinstance(value, (int, float)):
                session[key] = display_number(value, "")
            else:
                session[key] = value or ""
        session[SESSION_FX_EDITOR_TOKEN] = token


def exchange_rate_summary(workspace: dict, source) -> tuple[str, str]:
    rate = getattr(source, "exchange_rate", None)
    context = getattr(source, "pricing_context", None)
    origin = getattr(context, "exchange_rate_source", None) if context is not None else getattr(source, "exchange_rate_source", None)
    origin_key = getattr(origin, "value", origin) or "UNRECORDED"
    unset = workspace.get("unset_label", "未設定")
    value = workspace.get("fx_value", "{rate}").format(rate=display_number(rate, unset)) if rate is not None else unset
    return value, workspace.get("fx_sources", {}).get(origin_key, origin_key)


def warning_count(draft) -> int:
    if draft is None:
        return 0
    count = len(draft.warnings)
    count += sum(len(line.warnings) for line in draft.configuration_lines)
    count += len(unresolved_required_lines(draft))
    return count


def customer_facing_preview(draft) -> list[dict]:
    if draft is None:
        return []
    rows = []
    for line in draft.customer_lines:
        rows.append(
            {
                "customer_quote_line_id": line.customer_quote_line_id,
                "source_configuration_line_ids": list(line.source_configuration_line_ids),
                "display_name": line.display_name,
                "description": line.description,
                "quantity": line.quantity,
                "unit_price_jpy": line.unit_price_jpy,
                "amount_jpy": line.amount_jpy,
                "presentation_mode": (
                    line.presentation_mode.value if line.presentation_mode else None
                ),
                "line_kind": line.line_kind,
            }
        )
    return rows


def customer_preview_has_internal_cost(rows: list[dict]) -> bool:
    for row in rows:
        if INTERNAL_CUSTOMER_VIEW_KEYS.intersection(row):
            return True
    return False


def separate_product_lines(draft) -> list:
    if draft is None:
        return []
    return [
        line
        for line in draft.configuration_lines
        if line.customer_presentation_status == CustomerPresentationMode.SEPARATE_LINE
        and line.requirement_type != RequirementType.SHIPPING
    ]


def shipping_customer_lines(draft) -> list:
    if draft is None:
        return []
    return [line for line in draft.customer_lines if line.line_kind == "SHIPPING"]


def prices_adjusted(line) -> bool:
    standard = getattr(line, "standard_sales_price_candidate_jpy", None)
    final = getattr(line, "final_sales_price_jpy", None)
    if standard is None or final is None:
        return False
    return standard != final


def step_is_complete(step: int, draft, snapshot=None, validation=None) -> bool:
    if step == 1:
        return draft is not None and not unresolved_required_lines(draft)
    if step == 2:
        if draft is None:
            return False
        products_ready = all(line.final_sales_price_jpy is not None for line in separate_product_lines(draft))
        shipping_lines = shipping_customer_lines(draft)
        shipping_ready = all(line.unit_price_jpy is not None for line in shipping_lines) if shipping_lines else True
        return products_ready and shipping_ready
    if step == 3:
        if draft is None:
            return False
        rows = customer_facing_preview(draft)
        return bool(rows) and all(row["unit_price_jpy"] is not None for row in rows)
    if step == 4:
        if snapshot is not None and getattr(snapshot, "status", None) == QuoteDraftStatus.APPROVED:
            return True
        if draft is None or validation is None:
            return False
        return bool(getattr(validation, "can_approve", False)) and draft.status == QuoteDraftStatus.READY_FOR_APPROVAL
    if step == 5:
        return snapshot is not None
    return False


def step_marker(step: int, current: int, draft, snapshot=None, validation=None) -> str:
    if step == current:
        return STATUS_MARK["current"]
    if step_is_complete(step, draft, snapshot, validation):
        return STATUS_MARK["done"]
    return STATUS_MARK["todo"]


def build_header_summary(draft, snapshot=None) -> dict:
    source = snapshot or draft
    if source is None:
        return {
            "customer": None,
            "title": None,
            "configuration_name": None,
            "quote_number": None,
            "status": None,
            "subtotal": None,
            "total": None,
            "gross_margin": None,
            "warning_count": 0,
            "quote_draft_id": None,
            "quote_version": None,
        }
    economics = getattr(draft, "economics_result", None) if draft is not None else None
    return {
        "customer": getattr(source, "customer", None),
        "title": getattr(source, "title", None),
        "configuration_name": getattr(source, "configuration_name", None),
        "quote_number": (
            getattr(snapshot, "official_quote_number", None)
            or getattr(snapshot, "quote_number_candidate", None)
            if snapshot is not None
            else None
        ),
        "status": getattr(draft, "status", None) or getattr(source, "status", None),
        "subtotal": getattr(source, "subtotal_ex_tax_jpy", None),
        "total": getattr(source, "total_jpy", None),
        "gross_margin": (
            getattr(snapshot, "gross_margin_rate", None)
            if snapshot is not None
            else getattr(economics, "gross_margin_rate", None)
        ),
        "warning_count": warning_count(draft),
        "quote_draft_id": getattr(source, "quote_draft_id", None),
        "quote_version": getattr(source, "quote_version", None),
    }


def costing_summary(draft) -> dict:
    economics = getattr(draft, "economics_result", None) if draft is not None else None
    standard_total = None
    final_total = None
    if draft is not None:
        standards = [line.standard_sales_price_candidate_jpy for line in separate_product_lines(draft)]
        finals = [line.final_sales_price_jpy for line in separate_product_lines(draft)]
        if any(value is not None for value in standards):
            standard_total = sum(value or 0 for value in standards)
        if any(value is not None for value in finals):
            final_total = sum(value or 0 for value in finals)
        shipping = shipping_customer_lines(draft)
        if shipping:
            ship_total = sum(line.amount_jpy or 0 for line in shipping)
            if final_total is not None:
                final_total += ship_total
    return {
        "product_cost": getattr(economics, "product_landed_cost_total_jpy", None),
        "shipping_cost": getattr(economics, "shipping_cost_total_jpy", None),
        "total_cost": getattr(economics, "total_landed_cost_jpy", None),
        "standard_sales": standard_total,
        "final_sales": final_total if final_total is not None else getattr(draft, "subtotal_ex_tax_jpy", None),
        "gross_profit": getattr(economics, "gross_profit_jpy", None),
        "gross_margin": getattr(economics, "gross_margin_rate", None),
    }
