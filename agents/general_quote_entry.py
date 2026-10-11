from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence
from uuid import uuid4

from agents.landed_cost import build_shipping_line, calculate_landed_cost_scenario
from agents.master_reconciliation import get_manufacturer_price_by_sku
from agents.price_master import (
    GENERIC_MANUFACTURER_MASTERS,
    attach_price_master_provenance,
    get_active_master,
    load_active_landed_policy,
    mark_sales_master_missing,
    parse_manufacturer_price_master,
)
from agents.quote_builder import build_quote_draft
from models import (
    ExchangeRateSource,
    LandedCostShippingLine,
    PriceMasterType,
    SalesPriceCandidate,
    ShippingType,
    SkuDuplicateClass,
    SkuSourceStatus,
)
from repositories.sqlite_price_master_repository import SqlitePriceMasterRepository


class GeneralQuoteEntryError(ValueError):
    def __init__(self, code: str, sku: Optional[str] = None):
        super().__init__(code)
        self.code = code
        self.sku = sku


@dataclass(frozen=True)
class GeneralQuoteLine:
    sku: str
    quantity: int


def create_general_quote_draft(
    *,
    customer: str,
    title: Optional[str],
    lines: Sequence,
    exchange_rate: float,
    international_shipping_usd: Optional[float],
    domestic_shipping_jpy: Optional[float],
    sales_candidates: Optional[Sequence[SalesPriceCandidate]] = None,
    exchange_rate_source: Optional[ExchangeRateSource] = None,
    tax_rate: Optional[float] = None,
    case_id: Optional[str] = None,
    repository: Optional[SqlitePriceMasterRepository] = None,
):
    """Build one Deep Trekker / PipeTrekker draft from active DT40 and PT30 masters."""
    customer = (customer or "").strip()
    title = (title or "").strip() or None
    if not customer:
        raise GeneralQuoteEntryError("CUSTOMER_REQUIRED")
    normalized = _normalize_lines(lines)
    _require_positive_number(exchange_rate, "EXCHANGE_RATE_INVALID")
    _require_non_negative_optional(international_shipping_usd, "INTERNATIONAL_SHIPPING_INVALID")
    _require_non_negative_optional(domestic_shipping_jpy, "DOMESTIC_SHIPPING_INVALID")

    repo = repository or SqlitePriceMasterRepository()
    books = _active_manufacturer_books(repo)
    resolved = [_resolve_sku(line, books) for line in normalized]
    policy = load_active_landed_policy(repo)
    if policy is None:
        raise GeneralQuoteEntryError("QUOTE_CALC_MISSING")

    shipping_lines = []
    unresolved = []
    if international_shipping_usd is None:
        unresolved.append("International shipping cost")
    else:
        shipping_lines.append(
            build_shipping_line(
                ShippingType.CUSTOM,
                1,
                international_shipping_usd,
                exchange_rate,
                policy,
                source_type="HUMAN_INPUT",
                source_reference="General quote entry",
                rule_status="HUMAN_CONFIRMED",
                notes="International shipping cost entered by a person.",
            )
        )
    if domestic_shipping_jpy is None:
        unresolved.append("Domestic shipping cost")
    if unresolved:
        shipping_lines.append(
            LandedCostShippingLine(
                shipping_type=ShippingType.CUSTOM,
                quantity=1,
                exchange_rate=exchange_rate,
                cost_jpy=None,
                source_type="HUMAN_INPUT_PENDING",
                source_reference="General quote entry",
                rule_status="REVIEW_REQUIRED",
                notes=", ".join(unresolved),
            )
        )

    identifier = uuid4().hex
    sales = list(sales_candidates or [])
    used_types = []
    product_inputs = []
    chosen = []
    for master_type, active, candidate, line in resolved:
        if master_type not in used_types:
            used_types.append(master_type)
        product_inputs.append(
            {
                "sku": line.sku,
                "quantity": line.quantity,
                "description": candidate.description,
                "price_book": master_type.value,
                "price_book_version": active.record.import_id,
            }
        )
        chosen.append(candidate)
    scenario, _ = calculate_landed_cost_scenario(
        scenario_id=f"general-{identifier}",
        case_id=case_id,
        name="CUSTOM",
        exchange_rate=exchange_rate,
        policy=policy,
        product_inputs=product_inputs,
        shipping_lines=shipping_lines,
        sales_candidates=sales,
        unresolved_components=unresolved,
        insurance_mode=policy.insurance_mode,
        domestic_shipping_jpy=domestic_shipping_jpy,
        price_book_candidates=chosen,
        source_references=[f"Active {item.value}" for item in used_types] + ["Human general quote entry"],
    )
    draft = build_quote_draft(
        quote_draft_id=f"general-{identifier}",
        case_id=case_id,
        customer=customer,
        title=title,
        configuration_name="CUSTOM",
        landed_scenario=scenario,
        sales_candidates=sales,
        presentation={
            "product_presentations": [
                {
                    "sku": line.sku,
                    "requirement_type": "MANUAL_COMPONENT",
                    "presentation_mode": "SEPARATE_LINE",
                    "display_name": candidate.description,
                }
                for _master_type, _active, candidate, line in resolved
            ]
        },
        tax_rate=tax_rate,
        exchange_rate_source=exchange_rate_source,
    )
    records = []
    for master_type in used_types:
        active = get_active_master(master_type, repo)
        if active is not None:
            records.append(active.record)
    quote_calc = get_active_master(PriceMasterType.QUOTE_CALC, repo)
    if quote_calc is not None:
        records.append(quote_calc.record)
    if sales_candidates is not None:
        spaceone = get_active_master(PriceMasterType.SO_MASTER, repo)
        if spaceone is not None:
            records.append(spaceone.record)
    attach_price_master_provenance(draft, records)
    if sales_candidates is None:
        mark_sales_master_missing(draft)
    return draft


def _normalize_lines(lines: Sequence) -> list[GeneralQuoteLine]:
    if not lines:
        raise GeneralQuoteEntryError("NO_LINES")
    merged: list[GeneralQuoteLine] = []
    positions: dict[str, int] = {}
    for item in lines:
        sku, quantity = _line_parts(item)
        sku = (sku or "").strip()
        if not sku:
            raise GeneralQuoteEntryError("SKU_REQUIRED")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise GeneralQuoteEntryError("QUANTITY_INVALID", sku=sku)
        if sku in positions:
            current = merged[positions[sku]]
            merged[positions[sku]] = GeneralQuoteLine(sku, current.quantity + quantity)
            continue
        positions[sku] = len(merged)
        merged.append(GeneralQuoteLine(sku, quantity))
    return merged


def _line_parts(item):
    if isinstance(item, GeneralQuoteLine):
        return item.sku, item.quantity
    if isinstance(item, dict):
        return item.get("sku"), item.get("quantity")
    return getattr(item, "sku", None), getattr(item, "quantity", None)


def _active_manufacturer_books(repo: SqlitePriceMasterRepository):
    books = []
    for master_type in GENERIC_MANUFACTURER_MASTERS:
        active = get_active_master(master_type, repo)
        if active is None:
            continue
        book = parse_manufacturer_price_master(
            master_type,
            active.path,
            version=active.record.import_id,
        )
        books.append((master_type, active, book))
    if not books:
        raise GeneralQuoteEntryError("MANUFACTURER_MASTER_MISSING")
    return books


def _resolve_sku(line: GeneralQuoteLine, books):
    found = []
    for master_type, active, book in books:
        candidate = get_manufacturer_price_by_sku(line.sku, book.candidates)
        if candidate is not None:
            found.append((master_type, active, candidate))
    if not found:
        raise GeneralQuoteEntryError("SKU_NOT_FOUND", sku=line.sku)
    for _master_type, _active, candidate in found:
        if candidate.duplicate_class == SkuDuplicateClass.PRICE_CONFLICT:
            raise GeneralQuoteEntryError("PRICE_CONFLICT", sku=line.sku)
        if candidate.source_status == SkuSourceStatus.OBSOLETE:
            raise GeneralQuoteEntryError("OBSOLETE_SKU", sku=line.sku)
    dealers = {item.dealer_price_usd for _master_type, _active, item in found}
    msrps = {item.msrp_usd for _master_type, _active, item in found}
    if len(dealers) > 1 or len(msrps) > 1:
        raise GeneralQuoteEntryError("PRICE_CONFLICT", sku=line.sku)
    master_type, active, candidate = found[0]
    if candidate.dealer_price_usd is None:
        raise GeneralQuoteEntryError("DEALER_PRICE_MISSING", sku=line.sku)
    return master_type, active, candidate, line


def _require_positive_number(value: float, code: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise GeneralQuoteEntryError(code)


def _require_non_negative_optional(value: Optional[float], code: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise GeneralQuoteEntryError(code)
