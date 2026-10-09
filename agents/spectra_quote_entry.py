from __future__ import annotations

import math
from typing import Optional, Sequence
from uuid import uuid4

from agents.landed_cost import build_shipping_line, calculate_landed_cost_scenario
from agents.master_reconciliation import get_manufacturer_price_by_sku
from agents.price_master import (
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
)
from repositories.sqlite_price_master_repository import SqlitePriceMasterRepository


class SpectraQuoteEntryError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def create_spectra_quote_draft(
    *,
    customer: str,
    title: Optional[str],
    sku: str,
    quantity: int,
    exchange_rate: float,
    international_shipping_usd: Optional[float],
    domestic_shipping_jpy: Optional[float],
    sales_candidates: Optional[Sequence[SalesPriceCandidate]] = None,
    exchange_rate_source: Optional[ExchangeRateSource] = None,
    tax_rate: Optional[float] = None,
    repository: Optional[SqlitePriceMasterRepository] = None,
):
    """Build one SPECTRA draft from the active SPECTRA master without cross-book fallback."""
    customer = (customer or "").strip()
    sku = (sku or "").strip()
    title = (title or "").strip() or f"SPECTRA {sku} 御見積"
    if not customer:
        raise SpectraQuoteEntryError("CUSTOMER_REQUIRED")
    if not sku:
        raise SpectraQuoteEntryError("SKU_REQUIRED")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        raise SpectraQuoteEntryError("QUANTITY_INVALID")
    _require_positive_number(exchange_rate, "EXCHANGE_RATE_INVALID")
    _require_non_negative_optional(international_shipping_usd, "INTERNATIONAL_SHIPPING_INVALID")
    _require_non_negative_optional(domestic_shipping_jpy, "DOMESTIC_SHIPPING_INVALID")

    repo = repository or SqlitePriceMasterRepository()
    active = get_active_master(PriceMasterType.SPECTRA_GOLD, repo)
    if active is None:
        raise SpectraQuoteEntryError("SPECTRA_MASTER_MISSING")
    book = parse_manufacturer_price_master(
        PriceMasterType.SPECTRA_GOLD,
        active.path,
        version=active.record.import_id,
    )
    candidate = get_manufacturer_price_by_sku(sku, book.candidates)
    if candidate is None:
        raise SpectraQuoteEntryError("SKU_NOT_FOUND")
    policy = load_active_landed_policy(repo)
    if policy is None:
        raise SpectraQuoteEntryError("QUOTE_CALC_MISSING")

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
                source_reference="SPECTRA quote entry",
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
                source_reference="SPECTRA quote entry",
                rule_status="REVIEW_REQUIRED",
                notes=", ".join(unresolved),
            )
        )

    identifier = uuid4().hex
    sales = list(sales_candidates or [])
    scenario, _ = calculate_landed_cost_scenario(
        scenario_id=f"spectra-{identifier}",
        case_id=None,
        name="SPECTRA",
        exchange_rate=exchange_rate,
        policy=policy,
        product_inputs=[
            {
                "sku": sku,
                "quantity": quantity,
                "description": candidate.description,
                "price_book": PriceMasterType.SPECTRA_GOLD.value,
                "price_book_version": active.record.import_id,
                "sales_sheet": "SPECTRA",
            }
        ],
        shipping_lines=shipping_lines,
        sales_candidates=sales,
        unresolved_components=unresolved,
        insurance_mode=policy.insurance_mode,
        domestic_shipping_jpy=domestic_shipping_jpy,
        price_book_candidates=book.candidates,
        source_references=["Active SPECTRA_GOLD", "Human SPECTRA quote entry"],
    )
    draft = build_quote_draft(
        quote_draft_id=f"spectra-{identifier}",
        case_id=None,
        customer=customer,
        title=title,
        configuration_name="SPECTRA",
        landed_scenario=scenario,
        sales_candidates=sales,
        presentation={
            "product_presentations": [
                {
                    "sku": sku,
                    "requirement_type": "BASE_PRODUCT",
                    "presentation_mode": "SEPARATE_LINE",
                    "display_name": candidate.description,
                }
            ]
        },
        tax_rate=tax_rate,
        exchange_rate_source=exchange_rate_source,
    )
    records = [active.record]
    for master_type in (PriceMasterType.SO_MASTER, PriceMasterType.QUOTE_CALC):
        other = get_active_master(master_type, repo)
        if other is not None:
            records.append(other.record)
    attach_price_master_provenance(draft, records)
    if sales_candidates is None:
        mark_sales_master_missing(draft)
    return draft


def _require_positive_number(value: float, code: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise SpectraQuoteEntryError(code)


def _require_non_negative_optional(value: Optional[float], code: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise SpectraQuoteEntryError(code)
