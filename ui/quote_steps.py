from __future__ import annotations

from models import (
    CustomerPresentationMode,
    QuoteDraftStatus,
    RequirementType,
)

SESSION_QUOTE_STEP = "quote_workspace_step"
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
