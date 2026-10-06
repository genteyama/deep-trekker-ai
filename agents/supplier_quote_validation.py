from datetime import datetime, timezone
from typing import Optional, Sequence

from agents.master_reconciliation import collect_manufacturer_candidates, get_manufacturer_price_by_sku
from models import (
    PriceBookImportResult,
    QuoteKnownIssue,
    RequiredConfigurationItem,
    SKUMasterCandidate,
    SkuDuplicateClass,
    SkuSourceStatus,
    SupplierQuote,
    SupplierQuoteInsurance,
    SupplierQuoteLine,
    SupplierQuoteLineKind,
    SupplierQuoteLineValidation,
    SupplierQuoteOverallStatus,
    SupplierQuoteShippingLine,
    SupplierQuoteValidationResult,
    SupplierQuoteValidationStatus,
    SupplierQuoteValidationSummary,
)

DEFAULT_PRICE_TOLERANCE_USD = 0.01
REVIEW_STATUSES = {
    SupplierQuoteValidationStatus.MSRP_MATCH,
    SupplierQuoteValidationStatus.PRICE_MISMATCH,
    SupplierQuoteValidationStatus.SKU_NOT_FOUND,
    SupplierQuoteValidationStatus.REQUIRES_REVIEW,
    SupplierQuoteValidationStatus.MISSING_COMPONENT,
    SupplierQuoteValidationStatus.SPECIAL_PRICE,
}


def load_official_manufacturer_price_books() -> list[PriceBookImportResult]:
    # Only the DT40 / PT30 masters activated in the price master registry are official.
    from agents.price_master import active_price_books

    return [item.book for item in active_price_books()]


def prices_equal(
    left: Optional[float],
    right: Optional[float],
    tolerance_usd: float = DEFAULT_PRICE_TOLERANCE_USD,
) -> bool:
    if left is None or right is None:
        return False
    return abs(round(float(left), 2) - round(float(right), 2)) <= tolerance_usd


def validate_supplier_quote(
    quote: SupplierQuote,
    *price_books: Optional[PriceBookImportResult],
    required_items: Optional[Sequence[RequiredConfigurationItem]] = None,
    tolerance_usd: float = DEFAULT_PRICE_TOLERANCE_USD,
    special_price_skus: Optional[Sequence[str]] = None,
    validated_at: Optional[datetime] = None,
) -> SupplierQuoteValidationResult:
    candidates = collect_manufacturer_candidates(*price_books)
    versions = {
        result.source_price_book: result.version
        for result in price_books
        if result is not None and result.source_price_book
    }
    declared_special = {sku for sku in (special_price_skus or []) if sku}
    lines = []
    for line in quote.lines:
        lines.append(
            _validate_product_line(line, candidates, versions, tolerance_usd, declared_special)
        )
    for index, shipping in enumerate(quote.shipping_lines, start=1):
        lines.append(_non_product_line(shipping, index, SupplierQuoteLineKind.SHIPPING))
    if quote.insurance is not None:
        lines.append(_insurance_line(quote.insurance))

    issues = []
    for item in required_items or []:
        if not item.human_verified:
            continue
        if _requirement_is_present(quote, item):
            continue
        missing = _missing_component_line(item)
        lines.append(missing)
        issues.append(
            QuoteKnownIssue(
                code="MISSING_COMPONENT",
                message=item.required_description or "A human-verified required component is missing.",
                details=item.notes,
            )
        )

    summary = _summarize(lines)
    return SupplierQuoteValidationResult(
        supplier_quote_validation_id=f"sqv-{quote.supplier_quote_id}",
        quote_reference=quote.quote_reference,
        validated_at=validated_at or datetime.now(timezone.utc),
        price_book_versions=versions,
        lines=lines,
        summary=summary,
        known_configuration_issues=issues,
        status=_overall_status(summary),
        supplier_quote_total_usd=quote.total_usd,
        uses_supplier_quote_as_product_cost=False,
        manufacturer_cost_basis="DT40_PT30_CURRENT_DEALER",
    )


def _validate_product_line(
    line: SupplierQuoteLine,
    candidates: Sequence[SKUMasterCandidate],
    versions: dict,
    tolerance_usd: float,
    declared_special: set[str],
) -> SupplierQuoteLineValidation:
    result = SupplierQuoteLineValidation(
        line_id=line.line_id,
        sku=line.sku,
        description=line.description,
        quantity=line.quantity,
        line_kind=SupplierQuoteLineKind.PRODUCT,
        supplier_unit_price_usd=line.unit_price_usd,
        validation_status=SupplierQuoteValidationStatus.REQUIRES_REVIEW,
    )
    if not line.sku:
        result.validation_status = SupplierQuoteValidationStatus.SKU_NOT_FOUND
        result.warnings.append("Supplier Quote line has no SKU. Similar SKUs were not substituted.")
        return result

    candidate = get_manufacturer_price_by_sku(line.sku, candidates)
    if candidate is None:
        result.validation_status = SupplierQuoteValidationStatus.SKU_NOT_FOUND
        result.warnings.append(
            "SKU was not found in the DT40 / PT30 Current Master. Similar SKUs were not substituted."
        )
        return result

    result.manufacturer_status = candidate.source_status
    result.manufacturer_notes = _notes(candidate)
    result.source_reference = _source_reference(candidate, versions)

    if candidate.duplicate_class == SkuDuplicateClass.PRICE_CONFLICT:
        result.validation_status = SupplierQuoteValidationStatus.REQUIRES_REVIEW
        result.warnings.append("Manufacturer source has a price conflict. Price was not judged.")
        return result
    if candidate.source_status == SkuSourceStatus.OBSOLETE:
        result.validation_status = SupplierQuoteValidationStatus.REQUIRES_REVIEW
        result.warnings.append("SKU exists only on an obsolete manufacturer sheet. Price was not judged.")
        return result

    result.manufacturer_msrp_usd = candidate.msrp_usd
    result.manufacturer_dealer_price_usd = candidate.dealer_price_usd
    result.dealer_rate = candidate.dealer_rate
    result.price_difference_vs_dealer = _delta(line.unit_price_usd, candidate.dealer_price_usd)
    result.price_difference_vs_msrp = _delta(line.unit_price_usd, candidate.msrp_usd)

    matches_dealer = prices_equal(line.unit_price_usd, candidate.dealer_price_usd, tolerance_usd)
    matches_msrp = prices_equal(line.unit_price_usd, candidate.msrp_usd, tolerance_usd)
    declared = bool(line.sku in declared_special or _notes_say_special_price(line.notes))

    if candidate.no_dealer_discount_note:
        if matches_dealer or matches_msrp:
            result.validation_status = SupplierQuoteValidationStatus.NO_DEALER_DISCOUNT
            result.warnings.append(
                "Manufacturer notes state NO DEALER DISCOUNT. Supplier price matches the Current Manufacturer Value."
            )
            return result
        result.validation_status = SupplierQuoteValidationStatus.PRICE_MISMATCH
        result.warnings.append(_mismatch_warning(line.unit_price_usd, candidate))
        return result

    if matches_dealer:
        result.validation_status = SupplierQuoteValidationStatus.DEALER_MATCH
        return result
    if matches_msrp:
        result.validation_status = SupplierQuoteValidationStatus.MSRP_MATCH
        result.warnings.append(
            "Supplier unit price matches Manufacturer MSRP, not Current Dealer Price. Review before using as dealer cost."
        )
        return result
    if declared:
        result.validation_status = SupplierQuoteValidationStatus.SPECIAL_PRICE
        result.warnings.append("Special Price was human-verified or marked on the quote. It was not inferred from the price gap.")
        return result
    result.validation_status = SupplierQuoteValidationStatus.PRICE_MISMATCH
    result.warnings.append(_mismatch_warning(line.unit_price_usd, candidate))
    return result


def _non_product_line(
    shipping: SupplierQuoteShippingLine,
    index: int,
    kind: SupplierQuoteLineKind,
) -> SupplierQuoteLineValidation:
    return SupplierQuoteLineValidation(
        line_id=f"shipping-{index}",
        description=shipping.description,
        quantity=shipping.quantity,
        line_kind=kind,
        supplier_unit_price_usd=shipping.unit_price_usd,
        validation_status=SupplierQuoteValidationStatus.NON_PRODUCT_COST,
        warnings=["Shipping is not validated against DT40 / PT30 SKU prices. Use ShippingRule."],
        source_reference=shipping.shipping_type.value if shipping.shipping_type else None,
    )


def _insurance_line(insurance: SupplierQuoteInsurance) -> SupplierQuoteLineValidation:
    return SupplierQuoteLineValidation(
        line_id="insurance-1",
        description=insurance.description or "Shipping Insurance",
        quantity=insurance.quantity,
        line_kind=SupplierQuoteLineKind.INSURANCE,
        supplier_unit_price_usd=insurance.amount_usd,
        validation_status=SupplierQuoteValidationStatus.NON_PRODUCT_COST,
        warnings=["Insurance is not validated against DT40 / PT30 SKU prices. Use Landed Cost later."],
    )


def _missing_component_line(item: RequiredConfigurationItem) -> SupplierQuoteLineValidation:
    return SupplierQuoteLineValidation(
        line_id=f"missing-{item.configuration_id}",
        sku=item.required_sku,
        description=item.required_description,
        line_kind=SupplierQuoteLineKind.MISSING_COMPONENT,
        validation_status=SupplierQuoteValidationStatus.MISSING_COMPONENT,
        warnings=[
            item.notes
            or "A human-verified required component is missing from the Supplier Quote."
        ],
        source_reference=item.requirement_reference,
    )


def manufacturer_package_includes_component(
    package_notes: Optional[str],
    *,
    sku: Optional[str] = None,
    markers: Optional[Sequence[str]] = None,
) -> bool:
    text = (package_notes or "").upper()
    if sku and sku.upper() in text:
        return True
    if markers and all(marker.upper() in text for marker in markers):
        return True
    return False


def _requirement_is_present(quote: SupplierQuote, item: RequiredConfigurationItem) -> bool:
    for line in quote.lines:
        sku = line.sku or ""
        if item.required_sku and sku == item.required_sku:
            return True
        if sku and sku in item.exclude_skus:
            continue
        blob = (line.description or "").upper()
        if item.exclude_markers and any(marker.upper() in blob for marker in item.exclude_markers):
            continue
        if item.match_markers and all(marker.upper() in blob for marker in item.match_markers):
            return True
    return False


def _notes(candidate: SKUMasterCandidate) -> list[str]:
    notes = []
    for occurrence in candidate.occurrences:
        if occurrence.notes and occurrence.notes not in notes:
            notes.append(occurrence.notes)
    return notes


def _source_reference(candidate: SKUMasterCandidate, versions: dict) -> str:
    books = []
    sheets = []
    for occurrence in candidate.occurrences:
        if occurrence.source_price_book and occurrence.source_price_book not in books:
            books.append(occurrence.source_price_book)
        if occurrence.source_sheet and occurrence.source_sheet not in sheets:
            sheets.append(occurrence.source_sheet)
    book = " / ".join(books)
    version = versions.get(books[0]) if books else None
    sheet = ", ".join(sheets)
    parts = [part for part in (book, version, sheet) if part]
    return " | ".join(parts)


def _notes_say_special_price(notes: Optional[str]) -> bool:
    return "SPECIAL PRICE" in (notes or "").upper()


def _mismatch_warning(supplier_price: Optional[float], candidate: SKUMasterCandidate) -> str:
    return (
        f"supplier_quote_price={supplier_price} "
        f"manufacturer_dealer_price={candidate.dealer_price_usd} "
        f"manufacturer_msrp={candidate.msrp_usd}"
    )


def _delta(current: Optional[float], baseline: Optional[float]) -> Optional[float]:
    if current is None or baseline is None:
        return None
    return round(float(current) - float(baseline), 2)


def _summarize(lines: Sequence[SupplierQuoteLineValidation]) -> SupplierQuoteValidationSummary:
    def count(status: SupplierQuoteValidationStatus) -> int:
        return sum(1 for line in lines if line.validation_status == status)

    return SupplierQuoteValidationSummary(
        product_lines=sum(1 for line in lines if line.line_kind == SupplierQuoteLineKind.PRODUCT),
        dealer_match_count=count(SupplierQuoteValidationStatus.DEALER_MATCH),
        msrp_match_count=count(SupplierQuoteValidationStatus.MSRP_MATCH),
        no_dealer_discount_count=count(SupplierQuoteValidationStatus.NO_DEALER_DISCOUNT),
        price_mismatch_count=count(SupplierQuoteValidationStatus.PRICE_MISMATCH),
        sku_not_found_count=count(SupplierQuoteValidationStatus.SKU_NOT_FOUND),
        requires_review_count=count(SupplierQuoteValidationStatus.REQUIRES_REVIEW),
        missing_component_count=count(SupplierQuoteValidationStatus.MISSING_COMPONENT),
        special_price_count=count(SupplierQuoteValidationStatus.SPECIAL_PRICE),
        shipping_line_count=sum(1 for line in lines if line.line_kind == SupplierQuoteLineKind.SHIPPING),
        insurance_line_count=sum(1 for line in lines if line.line_kind == SupplierQuoteLineKind.INSURANCE),
    )


def _overall_status(summary: SupplierQuoteValidationSummary) -> SupplierQuoteOverallStatus:
    if summary.product_lines == 0:
        return SupplierQuoteOverallStatus.INVALID
    if summary.sku_not_found_count == summary.product_lines and summary.product_lines > 0:
        return SupplierQuoteOverallStatus.INVALID
    if (
        summary.msrp_match_count
        or summary.price_mismatch_count
        or summary.sku_not_found_count
        or summary.requires_review_count
        or summary.missing_component_count
        or summary.special_price_count
    ):
        return SupplierQuoteOverallStatus.REVIEW_REQUIRED
    return SupplierQuoteOverallStatus.VALID
