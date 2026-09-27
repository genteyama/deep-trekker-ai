from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence
import json

from agents.quote_builder import (
    apply_final_price,
    apply_issue_date,
    apply_issuer_snapshot,
    apply_selected_remarks,
    apply_shipping_final_price,
    apply_tax_rate,
    apply_valid_until,
    inspect_quote_economics,
)
from models import (
    ApprovalValidationResult,
    ApprovedQuoteSnapshot,
    FinalPriceStatus,
    InternalQuoteTransferPayload,
    InternalQuoteTransferRow,
    InternalShippingEconomicsRow,
    IssuerSnapshot,
    MoneyForwardQuotePayload,
    MoneyForwardQuoteRow,
    QuoteApproval,
    QuoteDraft,
    QuoteDraftStatus,
    QuoteOutputBundle,
    QuoteReviewSummary,
    QuoteWarningItem,
    QuoteWarningSeverity,
    SpaceOneQuoteLine,
    SpaceOneQuotePayload,
)

PHOTON_HUMAN_FINAL_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "golden_cases"
    / "ihi_quote_001"
    / "human_final_price_input_photon.json"
)

CRITICAL_MARKERS = (
    "Required Component unresolved",
    "Manufacturer SKU is not set",
    "Manufacturer Price Snapshot is missing",
    "Landed cost is missing",
    "Customer presentation is UNDECIDED",
    "Final sales price is not set",
    "Shipping customer price is not set",
    "tax rate is not set",
    "not both complete",
    "Gross Margin unavailable",
    "Presentation undecided",
    "Bundle parent is required",
)

ADVISORY_MARKERS = (
    "below the entered reference",
    "Historical Customer Quote",
    "Prices were not changed",
)

REQUIRED_CONFIRMATIONS = (
    "configuration",
    "presentation",
    "sales_price",
    "remarks",
)

CUSTOMER_OUTPUT_FORBIDDEN_KEYS = {
    "dealer_price_usd",
    "dealer_amount_usd",
    "dealer_cost_jpy",
    "import_tax_jpy",
    "insurance_jpy",
    "domestic_shipping_jpy",
    "landed_subtotal_jpy",
    "landed_cost_jpy",
    "total_landed_cost_jpy",
    "gross_profit_jpy",
    "gross_margin_rate",
    "spaceone_standard_sales_jpy",
    "manufacturer_price_snapshots",
    "warnings",
    "critical_warnings",
}


class QuoteApprovalError(ValueError):
    pass


class QuoteApprovalStore:
    def __init__(self) -> None:
        self.approvals: dict[str, QuoteApproval] = {}
        self.snapshots: dict[str, ApprovedQuoteSnapshot] = {}
        self.drafts: dict[str, QuoteDraft] = {}

    def register_draft(self, draft: QuoteDraft) -> QuoteDraft:
        self.drafts[draft.quote_draft_id] = draft
        return draft

    def snapshots_for_case(self, case_id: Optional[str]) -> list[ApprovedQuoteSnapshot]:
        return [item for item in self.snapshots.values() if item.case_id == case_id]


def load_photon_human_final_input(path: Optional[Path] = None) -> dict:
    with (path or PHOTON_HUMAN_FINAL_PATH).open(encoding="utf-8") as file:
        return json.load(file)


def apply_human_final_price_inputs(
    draft: QuoteDraft,
    *,
    line_prices_jpy: dict[str, float],
    shipping_price_jpy: float,
    tax_rate: float,
    entered_by: str = "human-final-input",
) -> QuoteDraft:
    for line in draft.configuration_lines:
        amount = line_prices_jpy.get(line.manufacturer_sku or "")
        if amount is None:
            continue
        apply_final_price(
            draft,
            line.line_id,
            FinalPriceStatus.MANUAL_OVERRIDE,
            amount_jpy=amount,
            reason="Human final price input",
            entered_by=entered_by,
        )
    apply_shipping_final_price(draft, shipping_price_jpy)
    apply_tax_rate(draft, tax_rate)
    return draft


def apply_ihi_photon_human_final_fixture(draft: QuoteDraft) -> QuoteDraft:
    fixture = load_photon_human_final_input()
    apply_human_final_price_inputs(
        draft,
        line_prices_jpy=fixture["line_prices_jpy"],
        shipping_price_jpy=fixture["shipping_price_jpy"],
        tax_rate=fixture["tax_rate"],
    )
    for line in draft.configuration_lines:
        candidate = (fixture.get("standard_sales_candidates_jpy") or {}).get(line.manufacturer_sku or "")
        if candidate is not None and line.standard_sales_price_candidate_jpy is None:
            line.standard_sales_price_candidate_jpy = candidate
    if fixture.get("issue_date"):
        apply_issue_date(draft, fixture["issue_date"])
    if fixture.get("valid_until"):
        apply_valid_until(draft, fixture["valid_until"])
    if fixture.get("issuer"):
        apply_issuer_snapshot(draft, IssuerSnapshot.model_validate(fixture["issuer"]))
    if fixture.get("remarks"):
        apply_selected_remarks(draft, fixture["remarks"])
    draft.auto_valid_until = False
    return draft


def classify_warning(message: str) -> QuoteWarningSeverity:
    if any(marker in message for marker in ADVISORY_MARKERS):
        return QuoteWarningSeverity.WARNING
    if any(marker in message for marker in CRITICAL_MARKERS):
        return QuoteWarningSeverity.CRITICAL
    if "Official gross margin is withheld" in message:
        return QuoteWarningSeverity.CRITICAL
    return QuoteWarningSeverity.WARNING


def build_review_summary(draft: QuoteDraft) -> QuoteReviewSummary:
    shipping = next((item for item in draft.customer_lines if item.line_kind == "SHIPPING"), None)
    economics = draft.economics_result
    warnings = [
        QuoteWarningItem(message=item, severity=classify_warning(item))
        for item in draft.warnings
    ]
    return QuoteReviewSummary(
        quote_draft_id=draft.quote_draft_id,
        quote_version=draft.quote_version,
        status=draft.status,
        customer=draft.customer,
        title=draft.title,
        configuration_name=draft.configuration_name,
        configuration_rows=[
            {
                "sku": line.manufacturer_sku,
                "name": line.manufacturer_description,
                "quantity": line.quantity,
                "final_unit_price_jpy": line.final_sales_price_jpy,
                "presentation": line.customer_presentation_status.value,
            }
            for line in draft.configuration_lines
        ],
        customer_lines=[
            {
                "display_name": line.display_name,
                "description": line.description,
                "quantity": line.quantity,
                "unit_price_jpy": line.unit_price_jpy,
                "amount_jpy": line.amount_jpy,
                "line_kind": line.line_kind,
            }
            for line in draft.customer_lines
        ],
        shipping_description=shipping.description if shipping else None,
        shipping_price_jpy=shipping.amount_jpy if shipping else None,
        quantities=[
            {"sku": line.manufacturer_sku, "quantity": line.quantity}
            for line in draft.configuration_lines
        ],
        subtotal_ex_tax_jpy=draft.subtotal_ex_tax_jpy,
        tax_rate=draft.tax_rate,
        tax_jpy=draft.tax_jpy,
        total_jpy=draft.total_jpy,
        total_landed_cost_jpy=economics.total_landed_cost_jpy if economics else None,
        gross_profit_jpy=economics.gross_profit_jpy if economics else None,
        gross_margin_rate=economics.gross_margin_rate if economics else None,
        remarks=list(draft.remark_candidates),
        lead_time_text=draft.lead_time_text,
        valid_until=draft.valid_until,
        unresolved_warnings=warnings,
    )


def validate_for_approval(draft: QuoteDraft) -> ApprovalValidationResult:
    inspected = inspect_quote_economics(draft)
    warnings = list(inspected["warnings"]) + list(draft.warnings)
    if inspected["total_sales"] is None or inspected["total_landed"] is None:
        warnings.append("Gross Margin unavailable.")
    elif inspected["ready"] is False:
        warnings.append("Gross Margin unavailable.")
    critical = []
    regular = []
    for message in _unique(warnings):
        if classify_warning(message) == QuoteWarningSeverity.CRITICAL:
            critical.append(message)
        else:
            regular.append(message)
    ready = not critical and inspected["ready"] and inspected["total_sales"] is not None
    blocking = None
    if draft.status != QuoteDraftStatus.READY_FOR_APPROVAL:
        ready = False
        blocking = (
            f"Approval requires QuoteDraft.status == READY_FOR_APPROVAL. Current status is {draft.status.value}."
        )
    elif critical:
        ready = False
        blocking = "Critical warnings block approval."
    return ApprovalValidationResult(
        ready_for_approval=inspected["ready"] and not critical,
        current_status=draft.status,
        can_approve=ready and blocking is None,
        blocking_reason=blocking,
        critical_warnings=critical,
        regular_warnings=regular,
        review_summary=build_review_summary(draft),
    )


def approve_quote(
    draft: QuoteDraft,
    *,
    approved_by: str,
    confirmations: Optional[dict[str, bool]] = None,
    warnings_acknowledged: Optional[Sequence[str]] = None,
    approval_comment: Optional[str] = None,
    reviewed_by: Optional[str] = None,
    store: Optional[QuoteApprovalStore] = None,
    approved_at: Optional[datetime] = None,
    quote_number_candidate: Optional[str] = None,
) -> tuple[QuoteApproval, ApprovedQuoteSnapshot]:
    captured = approved_at or datetime.now(timezone.utc)
    acknowledged = list(warnings_acknowledged or [])
    confirmation_map = dict(confirmations or {})
    missing = [key for key in REQUIRED_CONFIRMATIONS if not confirmation_map.get(key)]
    if missing:
        raise QuoteApprovalError(f"Human confirmations are incomplete: {', '.join(missing)}")
    validation = validate_for_approval(draft)
    if not validation.can_approve:
        raise QuoteApprovalError(validation.blocking_reason or "Quote is not ready for approval.")
    if draft.economics_result is None or draft.economics_result.gross_margin_rate is None:
        raise QuoteApprovalError("Gross Margin unavailable. Approval is blocked.")
    approval = QuoteApproval(
        quote_approval_id=f"qa-{draft.quote_draft_id}-v{draft.quote_version}",
        quote_draft_id=draft.quote_draft_id,
        quote_version=draft.quote_version,
        status=QuoteDraftStatus.APPROVED,
        reviewed_by=reviewed_by or approved_by,
        reviewed_at=captured,
        approved_by=approved_by,
        approved_at=captured,
        approval_comment=approval_comment,
        warnings_acknowledged=acknowledged,
        confirmations=confirmation_map,
        critical_warnings=list(validation.critical_warnings),
        warnings=list(validation.regular_warnings),
        source_references=list(draft.source_references) + ["Quote Approval"],
    )
    snapshot = _build_approved_snapshot(
        draft,
        approved_by=approved_by,
        approved_at=captured,
        quote_number_candidate=quote_number_candidate,
    )
    draft.status = QuoteDraftStatus.APPROVED
    draft.updated_at = captured
    if store is not None:
        _supersede_previous(store, snapshot)
        store.register_draft(draft)
        store.approvals[approval.quote_approval_id] = approval
        store.snapshots[snapshot.approved_quote_snapshot_id] = snapshot
    return approval, snapshot


def create_revision_draft(
    snapshot: ApprovedQuoteSnapshot,
    *,
    store: Optional[QuoteApprovalStore] = None,
) -> QuoteDraft:
    from agents.quote_builder import refresh_quote_draft
    from agents.quote_dates import parse_quote_date, valid_until_matches_auto_rule
    from models import ScenarioCompleteness

    next_version = snapshot.quote_version + 1
    draft = QuoteDraft(
        quote_draft_id=f"{snapshot.quote_draft_id}-v{next_version}",
        quote_version=next_version,
        case_id=snapshot.case_id,
        customer=snapshot.customer,
        title=snapshot.title,
        configuration_name=snapshot.configuration_name,
        configuration_lines=[line.model_copy(deep=True) for line in snapshot.configuration_snapshot],
        customer_lines=[line.model_copy(deep=True) for line in snapshot.customer_lines_snapshot],
        shipping_lines=[line.model_copy(deep=True) for line in snapshot.shipping_snapshot],
        exchange_rate=snapshot.exchange_rate,
        pricing_context=draft_pricing_from_snapshot(snapshot),
        landed_cost_scenario_id=None,
        subtotal_ex_tax_jpy=snapshot.subtotal_ex_tax_jpy,
        tax_rate=snapshot.tax_rate,
        tax_jpy=snapshot.tax_jpy,
        total_jpy=snapshot.total_jpy,
        completeness=ScenarioCompleteness.INCOMPLETE,
        status=QuoteDraftStatus.DRAFT,
        remarks=[item.text for item in snapshot.remarks if item.selected],
        remark_candidates=[item.model_copy(deep=True) for item in snapshot.remarks],
        lead_time_text=snapshot.lead_time_text,
        issue_date=snapshot.issue_date,
        valid_until=snapshot.valid_until,
        auto_valid_until=valid_until_matches_auto_rule(
            parse_quote_date(snapshot.issue_date),
            parse_quote_date(snapshot.valid_until),
        ),
        issuer_snapshot=(
            snapshot.issuer_snapshot.model_copy(deep=True) if snapshot.issuer_snapshot else None
        ),
        source_references=list(snapshot.source_references) + [f"Revised from {snapshot.approved_quote_snapshot_id}"],
    )
    refresh_quote_draft(draft)
    if store is not None:
        store.register_draft(draft)
    return draft


def draft_pricing_from_snapshot(snapshot: ApprovedQuoteSnapshot):
    from models import QuoteDraftPricingContext

    return QuoteDraftPricingContext(
        exchange_rate=snapshot.exchange_rate,
        tax_rate=snapshot.tax_rate,
        landed_cost_policy_candidate_id=(
            snapshot.landed_cost_policy_snapshot.landed_cost_policy_candidate_id
            if snapshot.landed_cost_policy_snapshot
            else None
        ),
        pricing_policy_candidate_ids=list(snapshot.pricing_policy_references),
        manufacturer_price_snapshots=[item.model_copy(deep=True) for item in snapshot.manufacturer_price_snapshots],
        landed_cost_policy_snapshot=(
            snapshot.landed_cost_policy_snapshot.model_copy(deep=True)
            if snapshot.landed_cost_policy_snapshot
            else None
        ),
        source_references=list(snapshot.source_references),
    )


def generate_quote_outputs(snapshot: ApprovedQuoteSnapshot) -> QuoteOutputBundle:
    return QuoteOutputBundle(
        source_approved_quote_snapshot_id=snapshot.approved_quote_snapshot_id,
        internal_transfer=build_internal_transfer_payload(snapshot),
        spaceone_quote=build_spaceone_quote_payload(snapshot),
        moneyforward=build_moneyforward_payload(snapshot),
    )


def build_internal_transfer_payload(snapshot: ApprovedQuoteSnapshot) -> InternalQuoteTransferPayload:
    rows = []
    product_landed = 0.0
    product_landed_complete = True
    for line in snapshot.configuration_snapshot:
        quantity = line.quantity or 1
        dealer_amount = None if line.dealer_price_usd is None else round(line.dealer_price_usd * quantity, 4)
        sales_amount = None if line.final_sales_price_jpy is None else round(line.final_sales_price_jpy * quantity, 4)
        gross_profit = None
        gross_margin = None
        if sales_amount is not None and line.landed_cost_jpy is not None:
            gross_profit = round(sales_amount - line.landed_cost_jpy, 4)
            if sales_amount:
                gross_margin = round(gross_profit / sales_amount, 6)
        if line.landed_cost_jpy is None:
            product_landed_complete = False
        else:
            product_landed += line.landed_cost_jpy
        rows.append(
            InternalQuoteTransferRow(
                part_number=line.manufacturer_sku,
                item_name=line.manufacturer_description,
                quantity=quantity,
                dealer_unit_price_usd=line.dealer_price_usd,
                dealer_amount_usd=dealer_amount,
                dealer_cost_jpy=line.dealer_cost_jpy,
                import_tax_jpy=line.import_tax_jpy,
                insurance_jpy=line.insurance_jpy,
                domestic_shipping_jpy=line.domestic_shipping_jpy,
                landed_subtotal_jpy=line.landed_cost_jpy,
                spaceone_standard_sales_jpy=line.standard_sales_price_candidate_jpy,
                adjusted_unit_price_jpy=line.final_sales_price_jpy,
                sales_amount_jpy=sales_amount,
                gross_profit_jpy=gross_profit,
                gross_margin_rate=gross_margin,
                presentation_mode=line.customer_presentation_status,
                requirement_type=line.requirement_type,
            )
        )
    product_sales = 0.0
    product_sales_complete = True
    shipping_sales = None
    for line in snapshot.customer_lines_snapshot:
        if line.line_kind == "SHIPPING":
            shipping_sales = line.amount_jpy
            continue
        if line.amount_jpy is None:
            product_sales_complete = False
            continue
        product_sales += line.amount_jpy
    shipping_cost = 0.0
    shipping_cost_complete = True
    shipping_rows = []
    for line in snapshot.shipping_snapshot:
        quantity = line.quantity or 1
        usd_amount = None if line.rate_usd is None else round(line.rate_usd * quantity, 4)
        shipping_rows.append(
            InternalShippingEconomicsRow(
                shipping_type=line.shipping_type.value if line.shipping_type else None,
                quantity=quantity,
                usd_rate=line.rate_usd,
                usd_amount=usd_amount,
                exchange_rate=line.exchange_rate,
                cost_jpy=line.cost_jpy,
                standard_sales_candidate_jpy=line.sales_price_candidate_jpy,
                final_sales_price_jpy=None,
                source_snapshot_id=snapshot.approved_quote_snapshot_id,
                line_role="COMPONENT",
            )
        )
        if line.cost_jpy is None:
            shipping_cost_complete = False
        else:
            shipping_cost += line.cost_jpy
    shipping_cost_total = round(shipping_cost, 4) if shipping_cost_complete else None
    if snapshot.shipping_snapshot:
        shipping_gp = None
        shipping_gm = None
        if shipping_sales is not None and shipping_cost_total is not None:
            shipping_gp = round(shipping_sales - shipping_cost_total, 4)
            if shipping_sales:
                shipping_gm = round(shipping_gp / shipping_sales, 6)
        shipping_rows.append(
            InternalShippingEconomicsRow(
                shipping_type="INTERNATIONAL_SHIPPING",
                quantity=1,
                usd_rate=None,
                usd_amount=None,
                exchange_rate=snapshot.exchange_rate,
                cost_jpy=shipping_cost_total,
                standard_sales_candidate_jpy=None,
                final_sales_price_jpy=shipping_sales,
                gross_profit_jpy=shipping_gp,
                gross_margin_rate=shipping_gm,
                source_snapshot_id=snapshot.approved_quote_snapshot_id,
                line_role="AGGREGATE",
            )
        )
    return InternalQuoteTransferPayload(
        source_approved_quote_snapshot_id=snapshot.approved_quote_snapshot_id,
        rows=rows,
        shipping_rows=shipping_rows,
        product_sales_ex_tax_jpy=round(product_sales, 4) if product_sales_complete else None,
        shipping_sales_ex_tax_jpy=shipping_sales,
        customer_subtotal_ex_tax_jpy=snapshot.subtotal_ex_tax_jpy,
        customer_tax_jpy=snapshot.tax_jpy,
        customer_total_jpy=snapshot.total_jpy,
        product_landed_cost_jpy=round(product_landed, 4) if product_landed_complete else None,
        shipping_cost_jpy=shipping_cost_total,
        total_landed_cost_jpy=snapshot.total_landed_cost_jpy,
        gross_profit_jpy=snapshot.gross_profit_jpy,
        gross_margin_rate=snapshot.gross_margin_rate,
    )


def build_spaceone_quote_payload(snapshot: ApprovedQuoteSnapshot) -> SpaceOneQuotePayload:
    shipping = next((item for item in snapshot.customer_lines_snapshot if item.line_kind == "SHIPPING"), None)
    payload = SpaceOneQuotePayload(
        source_approved_quote_snapshot_id=snapshot.approved_quote_snapshot_id,
        customer=snapshot.customer,
        title=snapshot.title,
        quote_number_candidate=snapshot.quote_number_candidate,
        official_quote_number=snapshot.official_quote_number,
        issue_date=snapshot.issue_date,
        valid_until=snapshot.valid_until,
        lines=[
            SpaceOneQuoteLine(
                item_name=line.display_name,
                item_detail=_customer_description(line.description),
                unit_price_jpy=line.unit_price_jpy,
                quantity=line.quantity,
                amount_jpy=line.amount_jpy,
            )
            for line in snapshot.customer_lines_snapshot
        ],
        subtotal=snapshot.subtotal_ex_tax_jpy,
        tax_rate=snapshot.tax_rate,
        tax=snapshot.tax_jpy,
        total=snapshot.total_jpy,
        international_shipping_description=shipping.description if shipping else None,
        remarks=[item.text for item in snapshot.remarks],
    )
    _assert_customer_output_safe(payload.model_dump())
    return payload


def build_moneyforward_payload(snapshot: ApprovedQuoteSnapshot) -> MoneyForwardQuotePayload:
    rows = [
        MoneyForwardQuoteRow(
            item_name=line.display_name,
            item_detail=_customer_description(line.description),
            unit_price_jpy=line.unit_price_jpy,
            quantity=line.quantity,
            amount_jpy=line.amount_jpy,
            notes=None,
        )
        for line in snapshot.customer_lines_snapshot
    ]
    payload = MoneyForwardQuotePayload(
        source_approved_quote_snapshot_id=snapshot.approved_quote_snapshot_id,
        rows=rows,
        subtotal_ex_tax_jpy=snapshot.subtotal_ex_tax_jpy,
        tax_jpy=snapshot.tax_jpy,
        total_jpy=snapshot.total_jpy,
        tsv_preview=moneyforward_tsv_preview(rows),
    )
    _assert_customer_output_safe(payload.model_dump())
    return payload


def moneyforward_tsv_preview(rows: Sequence[MoneyForwardQuoteRow]) -> str:
    header = "品目\t品目詳細\t単価\t数量\t金額\t備考"
    lines = [header]
    for row in rows:
        lines.append(
            "\t".join(
                [
                    _tsv_cell(row.item_name),
                    _tsv_cell(row.item_detail),
                    _tsv_number(row.unit_price_jpy),
                    str(row.quantity),
                    _tsv_number(row.amount_jpy),
                    _tsv_cell(row.notes),
                ]
            )
        )
    return "\n".join(lines)


def all_confirmations() -> dict[str, bool]:
    return {key: True for key in REQUIRED_CONFIRMATIONS}


def _build_approved_snapshot(
    draft: QuoteDraft,
    *,
    approved_by: str,
    approved_at: datetime,
    quote_number_candidate: Optional[str],
) -> ApprovedQuoteSnapshot:
    economics = draft.economics_result
    remarks = [
        item.model_copy(deep=True)
        for item in draft.remark_candidates
        if item.selected
    ]
    candidate = quote_number_candidate or f"{draft.case_id or draft.quote_draft_id}-v{draft.quote_version}"
    return ApprovedQuoteSnapshot(
        approved_quote_snapshot_id=f"aqs-{draft.quote_draft_id}-v{draft.quote_version}",
        quote_draft_id=draft.quote_draft_id,
        quote_version=draft.quote_version,
        case_id=draft.case_id,
        configuration_name=draft.configuration_name,
        customer=draft.customer,
        title=draft.title,
        approved_at=approved_at,
        approved_by=approved_by,
        status=QuoteDraftStatus.APPROVED,
        configuration_snapshot=[line.model_copy(deep=True) for line in draft.configuration_lines],
        customer_lines_snapshot=[line.model_copy(deep=True) for line in draft.customer_lines],
        shipping_snapshot=[line.model_copy(deep=True) for line in draft.shipping_lines],
        manufacturer_price_snapshots=[
            item.model_copy(deep=True) for item in draft.pricing_context.manufacturer_price_snapshots
        ],
        pricing_policy_references=list(draft.pricing_context.pricing_policy_candidate_ids),
        landed_cost_policy_snapshot=(
            draft.pricing_context.landed_cost_policy_snapshot.model_copy(deep=True)
            if draft.pricing_context.landed_cost_policy_snapshot
            else None
        ),
        exchange_rate=draft.exchange_rate,
        subtotal_ex_tax_jpy=draft.subtotal_ex_tax_jpy,
        tax_rate=draft.tax_rate,
        tax_jpy=draft.tax_jpy,
        total_jpy=draft.total_jpy,
        total_landed_cost_jpy=economics.total_landed_cost_jpy if economics else None,
        gross_profit_jpy=economics.gross_profit_jpy if economics else None,
        gross_margin_rate=economics.gross_margin_rate if economics else None,
        remarks=remarks,
        lead_time_text=draft.lead_time_text,
        issue_date=draft.issue_date,
        valid_until=draft.valid_until,
        issuer_snapshot=(
            draft.issuer_snapshot.model_copy(deep=True) if draft.issuer_snapshot else None
        ),
        quote_number_candidate=candidate,
        official_quote_number=None,
        source_references=list(draft.source_references) + ["ApprovedQuoteSnapshot"],
    )


def _supersede_previous(store: QuoteApprovalStore, incoming: ApprovedQuoteSnapshot) -> None:
    for snapshot_id, snapshot in list(store.snapshots.items()):
        if (
            snapshot.case_id == incoming.case_id
            and snapshot.configuration_name == incoming.configuration_name
            and snapshot.status == QuoteDraftStatus.APPROVED
            and snapshot.approved_quote_snapshot_id != incoming.approved_quote_snapshot_id
        ):
            store.snapshots[snapshot_id] = snapshot.model_copy(update={"status": QuoteDraftStatus.SUPERSEDED})
    for draft in store.drafts.values():
        if (
            draft.case_id == incoming.case_id
            and draft.configuration_name == incoming.configuration_name
            and draft.status == QuoteDraftStatus.APPROVED
            and draft.quote_draft_id != incoming.quote_draft_id
        ):
            draft.status = QuoteDraftStatus.SUPERSEDED
    for approval in store.approvals.values():
        related = store.drafts.get(approval.quote_draft_id)
        if (
            related is not None
            and related.case_id == incoming.case_id
            and related.configuration_name == incoming.configuration_name
            and approval.status == QuoteDraftStatus.APPROVED
            and approval.quote_draft_id != incoming.quote_draft_id
        ):
            approval.status = QuoteDraftStatus.SUPERSEDED


def _assert_customer_output_safe(payload: object) -> None:
    keys = _collect_keys(payload)
    leaked = keys & CUSTOMER_OUTPUT_FORBIDDEN_KEYS
    if leaked:
        raise QuoteApprovalError(f"Customer output must not include internal fields: {sorted(leaked)}")


def _collect_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(str(key))
            keys.update(_collect_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.update(_collect_keys(item))
    return keys


def _customer_description(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _tsv_cell(value: Optional[str]) -> str:
    return "" if value is None else str(value).replace("\t", " ").replace("\n", " ")


def _tsv_number(value: Optional[float]) -> str:
    if value is None:
        return ""
    if float(value).is_integer():
        return str(int(value))
    return str(value)


def _unique(values: Sequence[str]) -> list[str]:
    seen = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen
