"""PORTAL-3B.1 one-screen quote builder (DT40 / PT30).

Domain operations on a QuoteDraft. Every value a quote depends on is frozen into the draft when it is
chosen: product lines keep the price snapshot of the Active Master at the time they were added, and the
GlobalShipping choice keeps the reference value it was selected with. Later master, shipping-reference
or policy updates never change a saved draft by themselves.

Costs follow the existing landed-cost rules (dealer cost + insurance + import tax on the dealer cost) plus
the international shipping cost. Domestic shipping is not part of this builder (0 per line).
The customer shipping price is cost x the QUOTE_CALC shipping markup (policy.shipping_markup_multiplier,
1.2 in the current QUOTE_CALC), rounded with the existing customer price rule (1,000 JPY).
"""

from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Iterable, Optional, Sequence
from uuid import uuid4

from agents.general_quote_entry import create_general_quote_draft
from agents.landed_cost import build_shipping_line, reprice_product_cost_line
from agents.pricing_policy import is_customer_price_unit
from agents.quote_builder import (
    apply_exchange_rate,
    apply_final_price,
    ensure_draft_editable,
    refresh_quote_draft,
)
from models import (
    FinalPriceStatus,
    GlobalShippingSelection,
    QuoteDraft,
    ShippingType,
)

SIMPLE_BUILDER = "SIMPLE_V1"
SIMPLE_PRICE_BOOKS = ("DT40", "PT30")
GLOBAL_SHIPPING_SOURCE = "GLOBAL_SHIPPING_MASTER"
SHIPPING_PRICING_SOURCE = "GLOBAL_SHIPPING_POLICY"
SHIPPING_MANUAL_PRICING_SOURCE = "GLOBAL_SHIPPING_MANUAL"


class SimpleQuoteError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def price_list_sales_candidates(sales_candidates):
    """Sales candidates resolved with the 価格一覧 rule, so the builder shows the price list's standard price.

    The price list accepts an SKU whose several SpaceOne master rows (e.g. sheets A-150 and A-200) all give
    the same price (`build_reference_sales_map`). The quote engine would treat those rows as ambiguous, so
    for such an SKU only its first row is passed on. SKUs the price list leaves without a price keep all
    their rows and stay without a standard price. None (no Active SO_MASTER) stays None.
    """
    if sales_candidates is None:
        return None
    from agents.pricing_policy import round_customer_price_jpy
    from ui.price_catalog import build_reference_sales_map

    candidates = list(sales_candidates)
    reference = build_reference_sales_map(
        candidates, round_customer_price=round_customer_price_jpy, is_customer_price_unit=is_customer_price_unit
    )
    kept = []
    seen = set()
    for candidate in candidates:
        sku = str(candidate.manufacturer_sku or "").strip()
        if sku and reference.get(sku) is not None:
            if sku in seen:
                continue
            seen.add(sku)
        kept.append(candidate)
    return kept


def is_simple_draft(draft: Optional[QuoteDraft]) -> bool:
    return draft is not None and draft.builder == SIMPLE_BUILDER


# ---- products ------------------------------------------------------------------------------------


def create_simple_quote_draft(
    *,
    customer: str,
    title: Optional[str],
    items: Sequence[dict],
    exchange_rate: float,
    exchange_rate_source=None,
    tax_rate: Optional[float] = None,
    sales_candidates=None,
    repository=None,
) -> QuoteDraft:
    """New builder draft from {sku, quantity} items, priced from the Active DT40 / PT30 masters."""
    draft = create_general_quote_draft(
        customer=customer,
        title=title,
        lines=_merged_items(items),
        exchange_rate=exchange_rate,
        international_shipping_usd=None,
        domestic_shipping_jpy=0.0,
        sales_candidates=price_list_sales_candidates(sales_candidates),
        exchange_rate_source=exchange_rate_source,
        tax_rate=tax_rate,
        repository=repository,
    )
    draft.quote_draft_id = f"simple-{uuid4().hex}"
    draft.builder = SIMPLE_BUILDER
    # International shipping comes only from a GlobalShipping choice; drop the general-entry placeholder.
    draft.shipping_lines = []
    draft.source_references = list(draft.source_references) + ["Simple quote builder"]
    _use_standard_prices(draft, [line.line_id for line in draft.configuration_lines])
    return refresh_quote_draft(draft)


def add_products(draft: QuoteDraft, items: Sequence[dict], *, sales_candidates=None, repository=None) -> QuoteDraft:
    """Add {sku, quantity} items. An SKU already in the quote gets its quantity increased (no new row)."""
    ensure_draft_editable(draft)
    incoming = _merged_items(items)
    by_sku = {line.manufacturer_sku: line for line in draft.configuration_lines}
    new_items = []
    for item in incoming:
        existing = by_sku.get(item["sku"])
        if existing is not None:
            set_quantity(draft, existing.line_id, existing.quantity + item["quantity"], refresh=False)
        else:
            new_items.append(item)
    if new_items:
        source = create_general_quote_draft(
            customer=draft.customer or "-",
            title=draft.title,
            lines=new_items,
            exchange_rate=draft.exchange_rate,
            international_shipping_usd=None,
            domestic_shipping_jpy=0.0,
            sales_candidates=price_list_sales_candidates(sales_candidates),
            tax_rate=draft.tax_rate,
            repository=repository,
        )
        taken = {line.line_id for line in draft.configuration_lines}
        added_ids = []
        for line in source.configuration_lines:
            line_id = line.line_id
            if line_id in taken:
                line_id = f"{line.line_id}-{uuid4().hex[:6]}"
            line.line_id = line_id
            taken.add(line_id)
            added_ids.append(line_id)
            draft.configuration_lines.append(line)
        draft.pricing_context.manufacturer_price_snapshots.extend(
            item.model_copy() for item in source.pricing_context.manufacturer_price_snapshots
        )
        draft.pricing_context.pricing_policy_candidate_ids = _unique(
            list(draft.pricing_context.pricing_policy_candidate_ids) + list(source.pricing_context.pricing_policy_candidate_ids)
        )
        draft.source_references = _unique(list(draft.source_references) + list(source.source_references))
        draft.pricing_context.source_references = _unique(
            list(draft.pricing_context.source_references) + list(source.pricing_context.source_references)
        )
        _use_standard_prices(draft, added_ids)
    return refresh_quote_draft(draft)


def set_quantity(draft: QuoteDraft, line_id: str, quantity: int, *, refresh: bool = True) -> QuoteDraft:
    """Change a line quantity. Costs are re-run from the line's own price snapshot, not the current master."""
    ensure_draft_editable(draft)
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        raise SimpleQuoteError("QUANTITY_INVALID")
    line = _line(draft, line_id)
    policy = draft.pricing_context.landed_cost_policy_snapshot
    if policy is None:
        raise SimpleQuoteError("POLICY_MISSING")
    product = reprice_product_cost_line(
        {
            "sku": line.manufacturer_sku,
            "quantity": quantity,
            "dealer_price_usd": line.dealer_price_usd,
            "description": line.manufacturer_description,
            "manufacturer_price_snapshot": line.manufacturer_price_snapshot,
            "standard_sales_price_jpy": line.standard_sales_price_candidate_jpy,
        },
        exchange_rate=draft.exchange_rate,
        policy=policy,
        domestic_shipping_jpy=line.domestic_shipping_jpy or 0.0,
    )
    line.quantity = quantity
    line.dealer_cost_jpy = product.dealer_cost_jpy
    line.import_tax_jpy = product.import_tax_jpy
    line.insurance_jpy = product.insurance_jpy
    line.landed_cost_jpy = product.landed_cost_jpy
    return refresh_quote_draft(draft) if refresh else draft


def remove_line(draft: QuoteDraft, line_id: str) -> QuoteDraft:
    ensure_draft_editable(draft)
    line = _line(draft, line_id)
    draft.configuration_lines = [item for item in draft.configuration_lines if item.line_id != line_id]
    snapshot_id = line.manufacturer_price_snapshot.snapshot_id if line.manufacturer_price_snapshot else None
    if snapshot_id:
        draft.pricing_context.manufacturer_price_snapshots = [
            item for item in draft.pricing_context.manufacturer_price_snapshots if item.snapshot_id != snapshot_id
        ]
    draft.adjustments = [item for item in draft.adjustments if item.line_id != line_id]
    return refresh_quote_draft(draft)


def set_customer_info(draft: QuoteDraft, customer: str, title: Optional[str]) -> QuoteDraft:
    ensure_draft_editable(draft)
    name = (customer or "").strip()
    if not name:
        raise SimpleQuoteError("CUSTOMER_REQUIRED")
    draft.customer = name
    draft.title = (title or "").strip() or None
    draft.updated_at = datetime.now(timezone.utc)
    return draft


# ---- GlobalShipping ------------------------------------------------------------------------------


def select_global_shipping(
    draft: QuoteDraft,
    rate,
    *,
    actual_rate_usd: Optional[float] = None,
    rate_reason: Optional[str] = None,
    customer_price_jpy: Optional[float] = None,
    customer_reason: Optional[str] = None,
    selected_by: Optional[str] = None,
) -> QuoteDraft:
    """Freeze a GlobalShipping reference (ActiveStandardShippingRate) into the draft as its shipping cost.

    actual_rate_usd / customer_price_jpy are explicit human adjustments and each needs a reason.
    """
    ensure_draft_editable(draft)
    rule = rate.rule
    master = float(rule.rate_usd)
    actual, adjusted = _actual_rate(master, actual_rate_usd, rate_reason)
    selection = GlobalShippingSelection(
        shipping_rule_id=rule.shipping_rule_id,
        shipping_type=rule.shipping_type.value if rule.shipping_type else None,
        label=_shipping_label(rule),
        charge_basis=rule.charge_basis.value if rule.charge_basis else None,
        master_rate_usd=master,
        master_effective_from=rule.effective_from.date().isoformat() if rule.effective_from else None,
        master_source_reference=rule.source_reference,
        actual_rate_usd=actual,
        rate_adjusted=adjusted,
        rate_adjustment_reason=(rate_reason or "").strip() or None if adjusted else None,
        selected_by=selected_by,
        selected_at=datetime.now(timezone.utc),
    )
    draft.global_shipping = selection
    _set_customer_override(draft, customer_price_jpy, customer_reason)
    return apply_global_shipping(draft)


def adjust_global_shipping(
    draft: QuoteDraft,
    *,
    actual_rate_usd: Optional[float] = None,
    rate_reason: Optional[str] = None,
    customer_price_jpy: Optional[float] = None,
    customer_reason: Optional[str] = None,
) -> QuoteDraft:
    """Change the DT shipping cost and/or the customer shipping price of the current selection."""
    ensure_draft_editable(draft)
    selection = draft.global_shipping
    if selection is None:
        raise SimpleQuoteError("SHIPPING_NOT_SELECTED")
    actual, adjusted = _actual_rate(selection.master_rate_usd, actual_rate_usd, rate_reason)
    selection.actual_rate_usd = actual
    selection.rate_adjusted = adjusted
    selection.rate_adjustment_reason = (rate_reason or "").strip() or None if adjusted else None
    _set_customer_override(draft, customer_price_jpy, customer_reason)
    return apply_global_shipping(draft)


def clear_global_shipping(draft: QuoteDraft) -> QuoteDraft:
    ensure_draft_editable(draft)
    draft.global_shipping = None
    draft.shipping_lines = []
    return refresh_quote_draft(draft)


def apply_global_shipping(draft: QuoteDraft) -> QuoteDraft:
    """Recompute the shipping line and customer shipping price from the frozen selection and policy."""
    ensure_draft_editable(draft)
    selection = draft.global_shipping
    if selection is None:
        return refresh_quote_draft(draft)
    policy = draft.pricing_context.landed_cost_policy_snapshot
    if policy is None:
        raise SimpleQuoteError("POLICY_MISSING")
    shipping_type = ShippingType(selection.shipping_type) if selection.shipping_type else ShippingType.CUSTOM
    line = build_shipping_line(
        shipping_type,
        1,
        selection.actual_rate_usd,
        draft.exchange_rate,
        policy,
        source_type=GLOBAL_SHIPPING_SOURCE,
        source_reference=selection.shipping_rule_id,
        rule_status="HUMAN_ADJUSTED" if selection.rate_adjusted else "APPROVED",
        notes=selection.rate_adjustment_reason,
    )
    selection.exchange_rate = draft.exchange_rate
    selection.markup_multiplier = line.sales_markup_multiplier
    selection.cost_jpy = line.cost_jpy
    selection.auto_customer_price_jpy = line.sales_price_candidate_jpy
    if not selection.customer_price_overridden:
        selection.customer_price_jpy = line.sales_price_candidate_jpy
    draft.shipping_lines = [line]
    refresh_quote_draft(draft)
    shipping = next((item for item in draft.customer_lines if item.line_kind == "SHIPPING"), None)
    if shipping is not None:
        shipping.unit_price_jpy = selection.customer_price_jpy
        shipping.amount_jpy = None if selection.customer_price_jpy is None else selection.customer_price_jpy * shipping.quantity
        shipping.pricing_source = (
            SHIPPING_MANUAL_PRICING_SOURCE if selection.customer_price_overridden else SHIPPING_PRICING_SOURCE
        )
        shipping.human_adjusted = selection.customer_price_overridden
        shipping.notes = selection.customer_price_reason if selection.customer_price_overridden else None
    # Totals, tax and readiness follow the customer lines just set.
    from agents.quote_builder import _recalculate

    _recalculate(draft)
    return draft


# ---- exchange rate -------------------------------------------------------------------------------


def change_exchange_rate(
    draft: QuoteDraft,
    rate,
    *,
    sales_candidates=None,
    reason_code=None,
    reason_note: Optional[str] = None,
    set_by: Optional[str] = None,
) -> QuoteDraft:
    """Existing audited exchange-rate change, then lines on the standard price and shipping follow it."""
    standard_ids = [
        line.line_id for line in draft.configuration_lines if line.final_price_status == FinalPriceStatus.USE_STANDARD_CANDIDATE
    ]
    apply_exchange_rate(
        draft,
        rate,
        sales_candidates=price_list_sales_candidates(sales_candidates),
        reason_code=reason_code,
        reason_note=reason_note,
        set_by=set_by,
        set_at=datetime.now(timezone.utc),
    )
    return sync_after_rate_change(draft, standard_ids)


def sync_after_rate_change(draft: QuoteDraft, standard_line_ids: Optional[Iterable[str]] = None) -> QuoteDraft:
    """Keep standard-priced lines and the shipping price on the draft's current exchange rate.

    Lines that use the standard price follow a changed standard; manual prices are never touched.
    Idempotent: does nothing when everything already matches.
    """
    if draft.status.value in {"APPROVED", "SUPERSEDED"}:
        return draft
    ids = set(standard_line_ids or [])
    for line in draft.configuration_lines:
        if (
            line.final_price_status == FinalPriceStatus.USE_STANDARD_CANDIDATE
            and line.standard_sales_price_candidate_jpy is not None
            and line.final_sales_price_jpy != line.standard_sales_price_candidate_jpy
        ):
            ids.add(line.line_id)
    _use_standard_prices(draft, [line.line_id for line in draft.configuration_lines if line.line_id in ids])
    if draft.global_shipping is not None and draft.global_shipping.exchange_rate != draft.exchange_rate:
        return apply_global_shipping(draft)
    return draft


# ---- summaries -----------------------------------------------------------------------------------


def customer_summary(draft: QuoteDraft) -> dict:
    products = None
    shipping = None
    for line in draft.customer_lines:
        if line.line_kind == "SHIPPING":
            shipping = line.amount_jpy
        elif line.amount_jpy is not None:
            products = (products or 0.0) + line.amount_jpy
    return {
        "product_subtotal": products,
        "shipping": shipping,
        "subtotal_ex_tax": draft.subtotal_ex_tax_jpy,
        "tax_rate": draft.tax_rate,
        "tax": draft.tax_jpy,
        "total": draft.total_jpy,
    }


def revenue_summary(draft: QuoteDraft) -> dict:
    """Internal margin view: cost = dealer purchase + insurance + import tax + international shipping."""
    purchase = _sum(line.dealer_cost_jpy for line in draft.configuration_lines)
    insurance = _sum(line.insurance_jpy for line in draft.configuration_lines)
    import_tax = _sum(line.import_tax_jpy for line in draft.configuration_lines)
    shipping = _sum(line.cost_jpy for line in draft.shipping_lines) if draft.shipping_lines else None
    parts = (purchase, insurance, import_tax, shipping)
    total_cost = None if any(item is None for item in parts) else round(sum(parts), 4)
    sales = draft.subtotal_ex_tax_jpy
    gross = None if sales is None or total_cost is None else round(sales - total_cost, 4)
    margin = None if gross is None or not sales else round(gross / sales, 6)
    return {
        "purchase": purchase,
        "insurance": insurance,
        "import_tax": import_tax,
        "shipping": shipping,
        "total_cost": total_cost,
        "sales_ex_tax": sales,
        "gross_profit": gross,
        "gross_margin_rate": margin,
    }


# ---- helpers -------------------------------------------------------------------------------------


def _merged_items(items: Sequence[dict]) -> list[dict]:
    merged: dict[str, int] = {}
    for item in items or []:
        sku = str(item.get("sku") or "").strip()
        quantity = item.get("quantity", 1)
        if not sku:
            raise SimpleQuoteError("SKU_REQUIRED")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise SimpleQuoteError("QUANTITY_INVALID")
        merged[sku] = merged.get(sku, 0) + quantity
    if not merged:
        raise SimpleQuoteError("NO_ITEMS")
    return [{"sku": sku, "quantity": quantity} for sku, quantity in merged.items()]


def _use_standard_prices(draft: QuoteDraft, line_ids: Iterable[str]) -> None:
    for line_id in line_ids:
        line = next((item for item in draft.configuration_lines if item.line_id == line_id), None)
        if line is not None and line.standard_sales_price_candidate_jpy is not None:
            apply_final_price(draft, line_id, FinalPriceStatus.USE_STANDARD_CANDIDATE)


def _actual_rate(master: float, actual_rate_usd, reason: Optional[str]) -> tuple[float, bool]:
    if actual_rate_usd is None:
        return master, False
    if isinstance(actual_rate_usd, bool) or not isinstance(actual_rate_usd, (int, float)):
        raise SimpleQuoteError("SHIPPING_RATE_INVALID")
    value = round(float(actual_rate_usd), 2)
    if not math.isfinite(value) or value <= 0:
        raise SimpleQuoteError("SHIPPING_RATE_INVALID")
    if value == round(master, 2):
        return master, False
    if not (reason or "").strip():
        raise SimpleQuoteError("SHIPPING_REASON_REQUIRED")
    return value, True


def _set_customer_override(draft: QuoteDraft, amount, reason: Optional[str]) -> None:
    selection = draft.global_shipping
    if amount is None:
        selection.customer_price_overridden = False
        selection.customer_price_reason = None
        return
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount < 0:
        raise SimpleQuoteError("CUSTOMER_SHIPPING_INVALID")
    if not is_customer_price_unit(amount):
        raise SimpleQuoteError("CUSTOMER_SHIPPING_UNIT")
    if not (reason or "").strip():
        raise SimpleQuoteError("CUSTOMER_SHIPPING_REASON_REQUIRED")
    selection.customer_price_overridden = True
    selection.customer_price_jpy = float(amount)
    selection.customer_price_reason = reason.strip()


def _shipping_label(rule) -> str:
    from repositories.shipping_rule_repository import SHIPPING_TYPE_LABELS

    return SHIPPING_TYPE_LABELS.get(rule.shipping_type, rule.shipping_type.value if rule.shipping_type else "-")


def _line(draft: QuoteDraft, line_id: str):
    line = next((item for item in draft.configuration_lines if item.line_id == line_id), None)
    if line is None:
        raise SimpleQuoteError("LINE_NOT_FOUND")
    return line


def _sum(values) -> Optional[float]:
    total = 0.0
    for value in values:
        if value is None:
            return None
        total += value
    return round(total, 4)


def _unique(values: Sequence[str]) -> list[str]:
    seen = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


__all__ = [
    "SIMPLE_BUILDER",
    "SIMPLE_PRICE_BOOKS",
    "SimpleQuoteError",
    "add_products",
    "adjust_global_shipping",
    "apply_global_shipping",
    "change_exchange_rate",
    "clear_global_shipping",
    "create_simple_quote_draft",
    "customer_summary",
    "is_simple_draft",
    "remove_line",
    "revenue_summary",
    "select_global_shipping",
    "set_customer_info",
    "set_quantity",
    "sync_after_rate_change",
]
