from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence
import json

from agents.quote_dates import default_issue_date, default_valid_until, to_iso_date
from models import (
    CustomerPresentationMode,
    CustomerQuoteLineDraft,
    FinalPriceStatus,
    LandedCostScenario,
    QuoteAdjustment,
    QuoteAdjustmentType,
    QuoteConfigurationLine,
    QuoteDraft,
    QuoteDraftPricingContext,
    QuoteDraftStatus,
    QuoteEconomicsResult,
    QuotePriceSnapshot,
    QuoteRemark,
    IssuerSnapshot,
    RemarkSource,
    RequirementType,
    SalesPriceCandidate,
    ScenarioCompleteness,
)

PRESENTATION_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "golden_cases" / "ihi_quote_001" / "quote_presentation.json"
)
HISTORICAL_PRICING_SOURCE = "HISTORICAL_ACCEPTANCE_PREVIEW"
STANDARD_PRICING_SOURCE = "SPACEONE_PRICING_POLICY_CANDIDATE"
MANUAL_PRICING_SOURCE = "MANUAL_OVERRIDE"


def load_quote_presentation(path: Optional[Path] = None) -> dict:
    with (path or PRESENTATION_PATH).open(encoding="utf-8") as file:
        return json.load(file)


def build_quote_draft(
    *,
    quote_draft_id: str,
    case_id: Optional[str],
    customer: Optional[str],
    title: Optional[str],
    configuration_name: str,
    landed_scenario: LandedCostScenario,
    sales_candidates: Sequence[SalesPriceCandidate],
    presentation: dict,
    tax_rate: Optional[float] = None,
    minimum_margin_reference: Optional[float] = None,
    shipping_snapshot_id: Optional[str] = None,
    created_at: Optional[datetime] = None,
) -> QuoteDraft:
    captured = created_at or datetime.now(timezone.utc)
    sales_by_sku = _sales_by_sku(sales_candidates, configuration_name)
    presentations = {item["sku"]: item for item in presentation.get("product_presentations") or []}
    configuration_lines = []
    snapshots = []
    policy_ids = []
    for index, product in enumerate(landed_scenario.product_lines, start=1):
        spec = presentations.get(product.sku or "", {})
        sales = sales_by_sku.get(product.sku or "")
        if sales and sales.pricing_policy_candidate_id:
            policy_ids.append(sales.pricing_policy_candidate_id)
        snapshot = product.manufacturer_price_snapshot
        if snapshot:
            snapshots.append(snapshot.model_copy())
        requirement = RequirementType(spec.get("requirement_type") or RequirementType.SELECTED_OPTION.value)
        presentation_mode = CustomerPresentationMode(
            spec.get("presentation_mode") or CustomerPresentationMode.UNDECIDED.value
        )
        if requirement == RequirementType.REQUIRED_DEPENDENCY:
            presentation_mode = CustomerPresentationMode.UNDECIDED
        configuration_lines.append(
            QuoteConfigurationLine(
                line_id=f"cfg-{index}-{product.sku}",
                manufacturer_sku=product.sku,
                manufacturer_description=product.description,
                customer_display_name=spec.get("display_name"),
                customer_description=spec.get("description"),
                quantity=product.quantity,
                requirement_type=requirement,
                required_by_sku=spec.get("required_by_sku"),
                dependency_source=spec.get("dependency_source"),
                manufacturer_price_snapshot=snapshot.model_copy() if snapshot else None,
                landed_cost_jpy=product.landed_cost_jpy,
                dealer_price_usd=product.dealer_price_usd,
                dealer_cost_jpy=product.dealer_cost_jpy,
                import_tax_jpy=product.import_tax_jpy,
                insurance_jpy=product.insurance_jpy,
                domestic_shipping_jpy=product.domestic_shipping_jpy,
                standard_sales_price_candidate_jpy=sales.raw_sales_price_jpy if sales else None,
                standard_sales_price_candidate_id=sales.sales_price_candidate_id if sales else None,
                final_sales_price_jpy=None,
                final_price_status=FinalPriceStatus.NOT_SET,
                customer_presentation_status=presentation_mode,
                warnings=list(product.warnings),
            )
        )
    draft = QuoteDraft(
        quote_draft_id=quote_draft_id,
        case_id=case_id,
        customer=customer or presentation.get("customer"),
        title=title or presentation.get("title"),
        configuration_name=configuration_name,
        configuration_lines=configuration_lines,
        shipping_lines=[line.model_copy() for line in landed_scenario.shipping_lines],
        exchange_rate=landed_scenario.exchange_rate,
        pricing_context=QuoteDraftPricingContext(
            exchange_rate=landed_scenario.exchange_rate,
            tax_rate=tax_rate,
            minimum_margin_reference=minimum_margin_reference,
            landed_cost_policy_candidate_id=(
                landed_scenario.calculation_policy.landed_cost_policy_candidate_id
                if landed_scenario.calculation_policy
                else None
            ),
            shipping_snapshot_id=shipping_snapshot_id,
            pricing_policy_candidate_ids=policy_ids,
            manufacturer_price_snapshots=snapshots,
            landed_cost_policy_snapshot=(
                landed_scenario.calculation_policy.model_copy()
                if landed_scenario.calculation_policy
                else None
            ),
            source_references=list(landed_scenario.source_references),
        ),
        landed_cost_scenario_id=landed_scenario.scenario_id,
        tax_rate=tax_rate,
        remarks=[],
        remark_candidates=_remark_candidates(presentation),
        issue_date=default_issue_date().isoformat(),
        valid_until=default_valid_until().isoformat(),
        auto_valid_until=True,
        created_at=captured,
        updated_at=captured,
        source_references=list(landed_scenario.source_references) + ["Quote Builder draft"],
    )
    refresh_quote_draft(draft, presentation=presentation)
    return draft


def build_ihi_quote_draft(
    configuration: str,
    landed_scenario: LandedCostScenario,
    sales_candidates: Sequence[SalesPriceCandidate],
    *,
    tax_rate: Optional[float] = None,
    minimum_margin_reference: Optional[float] = None,
    load_historical_preview: bool = False,
    historical_quote: Optional[dict] = None,
) -> QuoteDraft:
    presentation = load_quote_presentation()[configuration.upper()]
    draft = build_quote_draft(
        quote_draft_id=f"ihi-{configuration.lower()}-draft",
        case_id="IHI_QUOTE_001",
        customer=presentation.get("customer"),
        title=presentation.get("title"),
        configuration_name=configuration.upper(),
        landed_scenario=landed_scenario,
        sales_candidates=sales_candidates,
        presentation=presentation,
        tax_rate=tax_rate,
        minimum_margin_reference=minimum_margin_reference,
        shipping_snapshot_id="dealer-update-2026-09-shipping",
    )
    if load_historical_preview and historical_quote:
        apply_historical_acceptance_preview(draft, historical_quote)
    return draft


def ensure_draft_editable(draft: QuoteDraft) -> None:
    if draft.status == QuoteDraftStatus.APPROVED:
        raise ValueError("Approved drafts cannot be edited. Create a new version.")
    if draft.status == QuoteDraftStatus.SUPERSEDED:
        raise ValueError("Superseded drafts cannot be edited. Create a new version.")


def apply_presentation_mode(
    draft: QuoteDraft,
    line_id: str,
    mode: CustomerPresentationMode,
    *,
    bundled_into_line_id: Optional[str] = None,
    presentation: Optional[dict] = None,
) -> QuoteDraft:
    ensure_draft_editable(draft)
    line = _config_line(draft, line_id)
    if mode == CustomerPresentationMode.BUNDLED_WITH_PARENT and not bundled_into_line_id:
        raise ValueError("BUNDLED_WITH_PARENT requires bundled_into_line_id.")
    line.customer_presentation_status = mode
    line.bundled_into_line_id = bundled_into_line_id if mode == CustomerPresentationMode.BUNDLED_WITH_PARENT else None
    if mode == CustomerPresentationMode.BUNDLED_WITH_PARENT:
        line.warnings = [item for item in line.warnings if "Bundle" not in item]
        line.warnings.append("Bundled into a customer line. Landed cost remains on the parent economics.")
    refresh_quote_draft(draft, presentation=presentation)
    return draft


def apply_final_price(
    draft: QuoteDraft,
    line_id: str,
    status: FinalPriceStatus,
    *,
    amount_jpy: Optional[float] = None,
    reason: Optional[str] = None,
    entered_by: Optional[str] = None,
    presentation: Optional[dict] = None,
) -> QuoteDraft:
    ensure_draft_editable(draft)
    line = _config_line(draft, line_id)
    if status == FinalPriceStatus.USE_STANDARD_CANDIDATE:
        if line.standard_sales_price_candidate_jpy is None:
            line.warnings.append("Standard Sales Price Candidate is missing. Final price was not set.")
            line.final_price_status = FinalPriceStatus.NOT_SET
            line.final_sales_price_jpy = None
        else:
            line.final_price_status = FinalPriceStatus.USE_STANDARD_CANDIDATE
            line.final_sales_price_jpy = line.standard_sales_price_candidate_jpy
    elif status == FinalPriceStatus.MANUAL_OVERRIDE:
        if amount_jpy is None:
            raise ValueError("Manual override requires an explicit amount.")
        original = line.final_sales_price_jpy
        if original is None:
            original = line.standard_sales_price_candidate_jpy
        line.final_price_status = FinalPriceStatus.MANUAL_OVERRIDE
        line.final_sales_price_jpy = amount_jpy
        draft.adjustments.append(
            QuoteAdjustment(
                adjustment_id=f"adj-{line.line_id}-{len(draft.adjustments) + 1}",
                line_id=line.line_id,
                adjustment_type=QuoteAdjustmentType.MANUAL,
                original_price_jpy=original,
                final_price_jpy=amount_jpy,
                amount_jpy=None if original is None else round(amount_jpy - original, 4),
                reason=reason,
                entered_by=entered_by,
                entered_at=datetime.now(timezone.utc),
                source_reference="human-final-price",
            )
        )
    else:
        line.final_price_status = FinalPriceStatus.NOT_SET
        line.final_sales_price_jpy = None
    refresh_quote_draft(draft, presentation=presentation)
    return draft


def apply_shipping_final_price(draft: QuoteDraft, amount_jpy: float, *, presentation: Optional[dict] = None) -> QuoteDraft:
    ensure_draft_editable(draft)
    refresh_quote_draft(draft, presentation=presentation)
    shipping = next((item for item in draft.customer_lines if item.line_kind == "SHIPPING"), None)
    if shipping is None:
        return draft
    shipping.unit_price_jpy = amount_jpy
    shipping.amount_jpy = amount_jpy * shipping.quantity
    shipping.pricing_source = MANUAL_PRICING_SOURCE
    shipping.human_adjusted = True
    _recalculate(draft)
    return draft


def apply_tax_rate(draft: QuoteDraft, tax_rate: Optional[float], *, presentation: Optional[dict] = None) -> QuoteDraft:
    ensure_draft_editable(draft)
    draft.tax_rate = tax_rate
    draft.pricing_context.tax_rate = tax_rate
    refresh_quote_draft(draft, presentation=presentation)
    return draft


def apply_minimum_margin_reference(draft: QuoteDraft, rate: Optional[float]) -> QuoteDraft:
    ensure_draft_editable(draft)
    draft.pricing_context.minimum_margin_reference = rate
    _recalculate(draft)
    return draft


def apply_selected_remarks(draft: QuoteDraft, texts: Sequence[str], *, source: RemarkSource = RemarkSource.HUMAN_CONFIRMED) -> QuoteDraft:
    ensure_draft_editable(draft)
    selected = set(texts)
    for candidate in draft.remark_candidates:
        candidate.selected = candidate.text in selected
        if candidate.selected and candidate.source == RemarkSource.GOLDEN_HISTORICAL_SNAPSHOT:
            candidate.source = source
    extra = [
        QuoteRemark(text=text, source=RemarkSource.HUMAN_ENTERED, selected=True)
        for text in texts
        if text not in {item.text for item in draft.remark_candidates}
    ]
    draft.remark_candidates.extend(extra)
    draft.remarks = [item.text for item in draft.remark_candidates if item.selected]
    return draft


def apply_lead_time_text(draft: QuoteDraft, text: Optional[str]) -> QuoteDraft:
    ensure_draft_editable(draft)
    draft.lead_time_text = text
    return draft


def apply_valid_until(draft: QuoteDraft, value) -> QuoteDraft:
    ensure_draft_editable(draft)
    draft.valid_until = to_iso_date(value)
    return draft


def apply_issue_date(draft: QuoteDraft, value) -> QuoteDraft:
    ensure_draft_editable(draft)
    draft.issue_date = to_iso_date(value)
    return draft


def apply_issuer_snapshot(draft: QuoteDraft, issuer: IssuerSnapshot) -> QuoteDraft:
    ensure_draft_editable(draft)
    draft.issuer_snapshot = issuer.model_copy(deep=True)
    return draft


def apply_historical_acceptance_preview(draft: QuoteDraft, historical_quote: dict) -> QuoteDraft:
    ensure_draft_editable(draft)
    by_description = {
        line.get("description"): line.get("unit_price_jpy")
        for line in historical_quote.get("lines") or []
    }
    for line in draft.configuration_lines:
        preview = by_description.get(line.customer_display_name)
        if preview is None:
            continue
        for customer in draft.customer_lines:
            if line.line_id in customer.source_configuration_line_ids:
                customer.historical_preview_unit_price_jpy = preview
                customer.notes = "Golden Acceptance Preview. Not a current pricing source."
    shipping = next((item for item in draft.customer_lines if item.line_kind == "SHIPPING"), None)
    historical_shipping = (historical_quote.get("shipping") or {}).get("price_jpy")
    if shipping is not None and historical_shipping is not None:
        shipping.historical_preview_unit_price_jpy = historical_shipping
        shipping.notes = "Golden Acceptance Preview. Not a current pricing source."
    _recalculate(draft)
    draft.warnings = _unique(
        list(draft.warnings)
        + ["Historical Customer Quote is an acceptance preview only. It is not the pricing source."]
    )
    return draft


def customer_preview_rows(draft: QuoteDraft) -> list[dict]:
    rows = []
    for line in draft.customer_lines:
        rows.append(
            {
                "display_name": line.display_name,
                "description": line.description,
                "quantity": line.quantity,
                "unit_price_jpy": line.unit_price_jpy,
                "amount_jpy": line.amount_jpy,
                "historical_preview_unit_price_jpy": line.historical_preview_unit_price_jpy,
            }
        )
    return rows


def internal_configuration_rows(draft: QuoteDraft) -> list[dict]:
    rows = []
    for line in draft.configuration_lines:
        rows.append(
            {
                "sku": line.manufacturer_sku,
                "manufacturer_description": line.manufacturer_description,
                "requirement_type": line.requirement_type.value,
                "dealer_price_usd": line.dealer_price_usd,
                "landed_cost_jpy": line.landed_cost_jpy,
                "standard_sales_price_candidate_jpy": line.standard_sales_price_candidate_jpy,
                "final_sales_price_jpy": line.final_sales_price_jpy,
                "presentation": line.customer_presentation_status.value,
                "warnings": list(line.warnings),
            }
        )
    return rows


def refresh_quote_draft(draft: QuoteDraft, *, presentation: Optional[dict] = None) -> QuoteDraft:
    ensure_draft_editable(draft)
    spec = presentation or load_quote_presentation().get(draft.configuration_name or "", {})
    draft.customer_lines = _rebuild_customer_lines(draft, spec)
    _recalculate(draft)
    draft.updated_at = datetime.now(timezone.utc)
    return draft


def _rebuild_customer_lines(draft: QuoteDraft, presentation: dict) -> list[CustomerQuoteLineDraft]:
    previous = {item.customer_quote_line_id: item for item in draft.customer_lines}
    previous_by_source = {}
    for item in draft.customer_lines:
        for source_id in item.source_configuration_line_ids:
            previous_by_source[source_id] = item
    lines = []
    order = 1
    for config in draft.configuration_lines:
        if config.customer_presentation_status != CustomerPresentationMode.SEPARATE_LINE:
            continue
        bundled = [
            item.line_id
            for item in draft.configuration_lines
            if item.customer_presentation_status == CustomerPresentationMode.BUNDLED_WITH_PARENT
            and item.bundled_into_line_id == config.line_id
        ]
        customer_id = f"cust-{config.line_id}"
        prior = previous.get(customer_id) or previous_by_source.get(config.line_id)
        lines.append(
            CustomerQuoteLineDraft(
                customer_quote_line_id=customer_id,
                display_name=config.customer_display_name or config.manufacturer_description,
                description=config.customer_description,
                quantity=config.quantity,
                unit_price_jpy=config.final_sales_price_jpy,
                amount_jpy=_amount(config.final_sales_price_jpy, config.quantity),
                source_configuration_line_ids=[config.line_id, *bundled],
                presentation_mode=CustomerPresentationMode.SEPARATE_LINE,
                display_order=order,
                notes=prior.notes if prior else None,
                pricing_source=_pricing_source(config),
                human_adjusted=config.final_price_status == FinalPriceStatus.MANUAL_OVERRIDE,
                adjustment_reference=prior.adjustment_reference if prior else None,
                historical_preview_unit_price_jpy=prior.historical_preview_unit_price_jpy if prior else None,
                line_kind="PRODUCT",
            )
        )
        order += 1
    if draft.shipping_lines:
        shipping_id = f"cust-shipping-{draft.quote_draft_id}"
        prior_shipping = previous.get(shipping_id) or next(
            (item for item in draft.customer_lines if item.line_kind == "SHIPPING"),
            None,
        )
        lines.append(
            CustomerQuoteLineDraft(
                customer_quote_line_id=shipping_id,
                display_name=presentation.get("shipping_display_name") or "国際輸送費",
                description=presentation.get("shipping_description"),
                quantity=1,
                unit_price_jpy=prior_shipping.unit_price_jpy if prior_shipping else None,
                amount_jpy=prior_shipping.amount_jpy if prior_shipping else None,
                source_configuration_line_ids=[],
                presentation_mode=CustomerPresentationMode.SEPARATE_LINE,
                display_order=order,
                notes=prior_shipping.notes if prior_shipping else None,
                pricing_source=prior_shipping.pricing_source if prior_shipping else None,
                human_adjusted=prior_shipping.human_adjusted if prior_shipping else False,
                historical_preview_unit_price_jpy=(
                    prior_shipping.historical_preview_unit_price_jpy if prior_shipping else None
                ),
                line_kind="SHIPPING",
            )
        )
    return lines


def inspect_quote_economics(draft: QuoteDraft) -> dict:
    product_sales = 0.0
    shipping_sales = None
    product_sales_complete = True
    for line in draft.customer_lines:
        if line.line_kind == "SHIPPING":
            shipping_sales = line.amount_jpy
            continue
        if line.amount_jpy is None:
            product_sales_complete = False
            continue
        product_sales += line.amount_jpy
    product_cost = 0.0
    product_cost_complete = True
    for line in draft.configuration_lines:
        if line.landed_cost_jpy is None:
            product_cost_complete = False
            continue
        product_cost += line.landed_cost_jpy
    shipping_cost = 0.0
    for line in draft.shipping_lines:
        if line.cost_jpy is None:
            shipping_cost = None
            break
        shipping_cost += line.cost_jpy
    total_sales = None
    if product_sales_complete and shipping_sales is not None:
        total_sales = round(product_sales + shipping_sales, 4)
    elif product_sales_complete and not draft.shipping_lines:
        total_sales = round(product_sales, 4)
    total_landed = None
    if product_cost_complete and shipping_cost is not None:
        total_landed = round(product_cost + shipping_cost, 4)
    ready, ready_warnings = _readiness(draft, total_sales, total_landed)
    return {
        "product_sales": round(product_sales, 4) if product_sales_complete else None,
        "shipping_sales": shipping_sales,
        "product_cost": round(product_cost, 4) if product_cost_complete else None,
        "shipping_cost": None if shipping_cost is None else round(shipping_cost, 4),
        "total_sales": total_sales,
        "total_landed": total_landed,
        "ready": ready,
        "warnings": list(ready_warnings),
    }


def _recalculate(draft: QuoteDraft) -> None:
    if draft.status in {QuoteDraftStatus.APPROVED, QuoteDraftStatus.SUPERSEDED}:
        return
    inspected = inspect_quote_economics(draft)
    warnings = list(inspected["warnings"])
    total_sales = inspected["total_sales"]
    total_landed = inspected["total_landed"]
    ready = inspected["ready"]
    product_sales = inspected["product_sales"]
    shipping_sales = inspected["shipping_sales"]
    product_cost = inspected["product_cost"]
    shipping_cost = inspected["shipping_cost"]
    gross_profit = None
    gross_margin = None
    if ready and total_sales and total_landed is not None:
        gross_profit = round(total_sales - total_landed, 4)
        gross_margin = round(gross_profit / total_sales, 6)
    elif not ready:
        warnings.append("Official gross margin is withheld because the quote draft is incomplete.")
    minimum = draft.pricing_context.minimum_margin_reference
    if minimum is not None and gross_margin is not None and gross_margin < minimum:
        warnings.append(
            f"Gross margin {gross_margin:.1%} is below the entered reference {minimum:.1%}. Prices were not changed."
        )
    draft.subtotal_ex_tax_jpy = total_sales
    if draft.tax_rate is None:
        draft.tax_jpy = None
        draft.total_jpy = None
    elif total_sales is None:
        draft.tax_jpy = None
        draft.total_jpy = None
    else:
        draft.tax_jpy = round(total_sales * draft.tax_rate, 4)
        draft.total_jpy = round(total_sales + draft.tax_jpy, 4)
    draft.economics_result = QuoteEconomicsResult(
        scenario_id=draft.landed_cost_scenario_id or draft.quote_draft_id,
        product_sales_total_jpy=product_sales,
        shipping_sales_total_jpy=shipping_sales,
        total_sales_ex_tax_jpy=total_sales,
        product_landed_cost_total_jpy=product_cost,
        shipping_cost_total_jpy=shipping_cost,
        other_cost_total_jpy=0.0,
        total_landed_cost_jpy=total_landed,
        gross_profit_jpy=gross_profit,
        gross_margin_rate=gross_margin,
        status=ScenarioCompleteness.COMPLETE if ready else ScenarioCompleteness.INCOMPLETE,
        warnings=_unique(warnings),
    )
    draft.completeness = draft.economics_result.status
    draft.status = QuoteDraftStatus.READY_FOR_APPROVAL if ready else QuoteDraftStatus.REVIEW_REQUIRED
    draft.warnings = _unique(warnings)


def _readiness(
    draft: QuoteDraft,
    total_sales: Optional[float],
    total_landed: Optional[float],
) -> tuple[bool, list[str]]:
    warnings = []
    for line in draft.configuration_lines:
        if not line.manufacturer_sku:
            warnings.append(f"{line.line_id}: Manufacturer SKU is not set.")
        if line.manufacturer_price_snapshot is None:
            warnings.append(f"{line.manufacturer_sku or line.line_id}: Manufacturer Price Snapshot is missing.")
        if line.landed_cost_jpy is None:
            warnings.append(f"{line.manufacturer_sku or line.line_id}: Landed cost is missing.")
        if line.customer_presentation_status == CustomerPresentationMode.UNDECIDED:
            if line.requirement_type == RequirementType.REQUIRED_DEPENDENCY:
                warnings.append(
                    f"{line.manufacturer_sku or line.line_id}: Required Component unresolved."
                )
            warnings.append(f"{line.manufacturer_sku or line.line_id}: Customer presentation is UNDECIDED.")
        if (
            line.customer_presentation_status == CustomerPresentationMode.SEPARATE_LINE
            and line.final_price_status == FinalPriceStatus.NOT_SET
        ):
            warnings.append(f"{line.manufacturer_sku or line.line_id}: Final sales price is not set.")
        if (
            line.customer_presentation_status == CustomerPresentationMode.SEPARATE_LINE
            and line.standard_sales_price_candidate_jpy is None
            and line.final_price_status != FinalPriceStatus.MANUAL_OVERRIDE
        ):
            if line.requirement_type == RequirementType.REQUIRED_DEPENDENCY:
                warnings.append(
                    f"{line.manufacturer_sku}: Separate customer line needs a human sales price because no Pricing Policy exists."
                )
        if (
            line.customer_presentation_status == CustomerPresentationMode.BUNDLED_WITH_PARENT
            and not line.bundled_into_line_id
        ):
            warnings.append(f"{line.manufacturer_sku}: Bundle parent is required.")
    if draft.shipping_lines:
        shipping = next((item for item in draft.customer_lines if item.line_kind == "SHIPPING"), None)
        if shipping is None or shipping.amount_jpy is None:
            warnings.append("Shipping customer price is not set.")
    if draft.tax_rate is None:
        warnings.append("Customer tax rate is not set. 10% is not hardcoded.")
    if total_sales is None or total_landed is None:
        warnings.append("Final sales and landed cost are not both complete.")
    return not warnings, warnings


def customer_line_landed_cost(draft: QuoteDraft, customer_line: CustomerQuoteLineDraft) -> Optional[float]:
    total = 0.0
    for line_id in customer_line.source_configuration_line_ids:
        config = next((item for item in draft.configuration_lines if item.line_id == line_id), None)
        if config is None or config.landed_cost_jpy is None:
            return None
        total += config.landed_cost_jpy
    return round(total, 4)


def _sales_by_sku(candidates: Sequence[SalesPriceCandidate], configuration: str) -> dict[str, SalesPriceCandidate]:
    matches = {}
    for candidate in candidates:
        sku = candidate.manufacturer_sku
        if not sku:
            continue
        current = matches.get(sku)
        if current is None or (candidate.source_reference or "").upper() == configuration.upper():
            matches[sku] = candidate
    return matches


def _config_line(draft: QuoteDraft, line_id: str) -> QuoteConfigurationLine:
    for line in draft.configuration_lines:
        if line.line_id == line_id:
            return line
    raise KeyError(line_id)


def _pricing_source(line: QuoteConfigurationLine) -> Optional[str]:
    if line.final_price_status == FinalPriceStatus.USE_STANDARD_CANDIDATE:
        return STANDARD_PRICING_SOURCE
    if line.final_price_status == FinalPriceStatus.MANUAL_OVERRIDE:
        return MANUAL_PRICING_SOURCE
    return None


def _amount(unit: Optional[float], quantity: int) -> Optional[float]:
    if unit is None:
        return None
    return round(unit * quantity, 4)


def _unique(values: Sequence[str]) -> list[str]:
    seen = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def _remark_candidates(presentation: dict) -> list[QuoteRemark]:
    kind = presentation.get("remarks_kind") or RemarkSource.GOLDEN_HISTORICAL_SNAPSHOT.value
    try:
        source = RemarkSource(kind)
    except ValueError:
        source = RemarkSource.GOLDEN_HISTORICAL_SNAPSHOT
    candidates = [
        QuoteRemark(text=text, source=source, selected=False)
        for text in presentation.get("remarks") or []
    ]
    current_lead = presentation.get("current_lead_time_text")
    if current_lead:
        candidates.append(
            QuoteRemark(text=current_lead, source=RemarkSource.CURRENT_LEAD_TIME, selected=False)
        )
    return candidates
