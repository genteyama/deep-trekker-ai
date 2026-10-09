from collections import defaultdict
from typing import Optional, Sequence

from models import (
    ManufacturerValues,
    MasterReconciliationIssue,
    MasterReconciliationReport,
    MasterReconciliationResult,
    MasterReconciliationSummary,
    MatchStatus,
    PriceBookImportResult,
    RecommendedChange,
    SKUMasterCandidate,
    SkuDuplicateClass,
    SkuSourceStatus,
    SpaceOneMasterItem,
    SpaceOneValues,
)

NEEDS_REVIEW = {
    MatchStatus.PRICE_MISMATCH,
    MatchStatus.PRICE_MISSING,
    MatchStatus.SKU_NOT_FOUND,
    MatchStatus.PART_NUMBER_INVALID,
    MatchStatus.OBSOLETE_ONLY,
    MatchStatus.SOURCE_PRICE_CONFLICT,
    MatchStatus.NO_MANUFACTURER_PRICE,
    MatchStatus.MANUAL_REVIEW_REQUIRED,
}


def get_manufacturer_price_by_sku(
    sku: Optional[str],
    price_book_candidates: Sequence[SKUMasterCandidate],
) -> Optional[SKUMasterCandidate]:
    if not sku:
        return None
    matches = [item for item in price_book_candidates if item.sku == sku]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    prices = {(item.msrp_usd, item.dealer_price_usd) for item in matches}
    if len(prices) > 1 or any(item.duplicate_class == SkuDuplicateClass.PRICE_CONFLICT for item in matches):
        merged = matches[0].model_copy(deep=True)
        merged.duplicate_class = SkuDuplicateClass.PRICE_CONFLICT
        merged.msrp_usd = None
        merged.dealer_price_usd = None
        merged.dealer_rate = None
        merged.occurrences = [occ for item in matches for occ in item.occurrences]
        return merged
    merged = matches[0].model_copy(deep=True)
    merged.occurrences = [occ for item in matches for occ in item.occurrences]
    merged.occurrence_count = len(merged.occurrences)
    return merged


def collect_manufacturer_candidates(*results: Optional[PriceBookImportResult]) -> list[SKUMasterCandidate]:
    candidates = []
    for result in results:
        if result is None:
            continue
        candidates.extend(result.candidates)
    return candidates


def reconcile_spaceone_master(
    items: Sequence[SpaceOneMasterItem],
    *price_books: Optional[PriceBookImportResult],
) -> MasterReconciliationReport:
    candidates = collect_manufacturer_candidates(*price_books)
    sku_counts: dict[str, int] = defaultdict(int)
    for item in items:
        if item.normalized_sku:
            sku_counts[item.normalized_sku] += 1

    results = []
    for item in items:
        result = _reconcile_item(item, candidates, sku_counts)
        results.append(result)
    return MasterReconciliationReport(summary=_summarize(results), results=results)


def _reconcile_item(
    item: SpaceOneMasterItem,
    candidates: Sequence[SKUMasterCandidate],
    sku_counts: dict[str, int],
) -> MasterReconciliationResult:
    issues: list[MasterReconciliationIssue] = []
    candidate = None
    manufacturer_values = None
    recommended: list[RecommendedChange] = []
    old_msrp = item.values.manufacturer_msrp_usd
    old_dealer = item.values.manufacturer_dealer_price_usd
    new_msrp = None
    new_dealer = None

    if item.is_legacy_shipping:
        primary = MatchStatus.MANUAL_REVIEW_REQUIRED
        issues.append(
            MasterReconciliationIssue(
                code="LEGACY_SHIPPING_VALUE",
                message="This SpaceOne row looks like a shipping rate, not a manufacturer SKU price.",
            )
        )
    elif item.part_number_invalid:
        primary = MatchStatus.PART_NUMBER_INVALID
        issues.append(
            MasterReconciliationIssue(
                code="PART_NUMBER_INVALID",
                message="Part Number is not a usable SKU string. It was not reconstructed.",
                details=item.sku_cell_type,
            )
        )
    else:
        candidate = get_manufacturer_price_by_sku(item.normalized_sku, candidates)
        if candidate is None:
            primary = MatchStatus.SKU_NOT_FOUND
            issues.append(
                MasterReconciliationIssue(
                    code="SKU_NOT_FOUND",
                    message="SKU was not found in the current official manufacturer master candidates.",
                )
            )
        elif candidate.duplicate_class == SkuDuplicateClass.PRICE_CONFLICT:
            primary = MatchStatus.SOURCE_PRICE_CONFLICT
            issues.append(
                MasterReconciliationIssue(
                    code="SOURCE_PRICE_CONFLICT",
                    message="Manufacturer source has a price conflict. No price candidate is suggested.",
                )
            )
            manufacturer_values = _manufacturer_values(candidate, price_conflict=True)
        elif candidate.source_status == SkuSourceStatus.OBSOLETE:
            primary = MatchStatus.OBSOLETE_ONLY
            issues.append(
                MasterReconciliationIssue(
                    code="OBSOLETE_ONLY",
                    message="SKU exists only on an obsolete manufacturer sheet, not on the active price book.",
                )
            )
            manufacturer_values = _manufacturer_values(candidate)
        elif candidate.msrp_usd is None and candidate.dealer_price_usd is None:
            primary = MatchStatus.NO_MANUFACTURER_PRICE
            issues.append(
                MasterReconciliationIssue(
                    code="NO_MANUFACTURER_PRICE",
                    message="Manufacturer SKU exists but has no MSRP or Dealer Price.",
                )
            )
            manufacturer_values = _manufacturer_values(candidate)
        else:
            new_msrp = candidate.msrp_usd
            new_dealer = candidate.dealer_price_usd
            manufacturer_values = _manufacturer_values(candidate)
            spaceone_has_price = old_msrp is not None or old_dealer is not None
            if not spaceone_has_price:
                primary = MatchStatus.PRICE_MISSING
                issues.append(
                    MasterReconciliationIssue(
                        code="PRICE_MISSING",
                        message="Manufacturer has prices, but SpaceOne manufacturer price cells are empty.",
                    )
                )
                recommended = _price_recommendations(old_msrp, old_dealer, new_msrp, new_dealer)
            elif _money(old_msrp) != _money(new_msrp) or _money(old_dealer) != _money(new_dealer):
                if old_msrp is None or old_dealer is None:
                    primary = MatchStatus.PRICE_MISSING
                    issues.append(
                        MasterReconciliationIssue(
                            code="PRICE_MISSING",
                            message="One manufacturer price is missing on the SpaceOne row.",
                        )
                    )
                else:
                    primary = MatchStatus.PRICE_MISMATCH
                    issues.append(
                        MasterReconciliationIssue(
                            code="PRICE_MISMATCH",
                            message="SpaceOne manufacturer prices differ from the official manufacturer master.",
                        )
                    )
                recommended = _price_recommendations(old_msrp, old_dealer, new_msrp, new_dealer)
            else:
                primary = MatchStatus.EXACT_MATCH

    if item.normalized_sku and sku_counts.get(item.normalized_sku, 0) > 1:
        issues.append(
            MasterReconciliationIssue(
                code="MULTIPLE_SPACEONE_ROWS",
                message="The same SKU appears more than once in the SpaceOne master. Rows were not merged.",
            )
        )

    return MasterReconciliationResult(
        spaceone_item_id=item.spaceone_item_id,
        source_sheet=item.source_sheet,
        source_row=item.source_row,
        spaceone_sku=item.spaceone_sku,
        normalized_sku=item.normalized_sku,
        manufacturer_price_book=manufacturer_values.source_price_book if manufacturer_values else None,
        manufacturer_candidate=candidate,
        primary_status=primary,
        issues=issues,
        old_reference=item.old_reference,
        current_spaceone_values=item.values,
        manufacturer_values=manufacturer_values,
        recommended_changes=recommended,
        old_msrp=old_msrp,
        new_msrp=new_msrp,
        old_dealer_price=old_dealer,
        new_dealer_price=new_dealer,
    )


def _manufacturer_values(candidate: SKUMasterCandidate, price_conflict: bool = False) -> ManufacturerValues:
    notes = []
    seen = set()
    for occurrence in candidate.occurrences:
        if occurrence.notes and occurrence.notes not in seen:
            seen.add(occurrence.notes)
            notes.append(occurrence.notes)
    sheets = []
    for occurrence in candidate.occurrences:
        if occurrence.source_sheet and occurrence.source_sheet not in sheets:
            sheets.append(occurrence.source_sheet)
    books = []
    for occurrence in candidate.occurrences:
        if occurrence.source_price_book and occurrence.source_price_book not in books:
            books.append(occurrence.source_price_book)
    return ManufacturerValues(
        sku=candidate.sku,
        description=candidate.description,
        msrp_usd=None if price_conflict else candidate.msrp_usd,
        dealer_price_usd=None if price_conflict else candidate.dealer_price_usd,
        dealer_rate=None if price_conflict else candidate.dealer_rate,
        notes=notes,
        source_status=candidate.source_status,
        source_price_book=" / ".join(books) if books else None,
        source_sheets=sheets,
    )


def _price_recommendations(old_msrp, old_dealer, new_msrp, new_dealer) -> list[RecommendedChange]:
    changes = []
    if _money(old_msrp) != _money(new_msrp):
        changes.append(
            RecommendedChange(field="manufacturer_msrp_usd", current_value=old_msrp, manufacturer_value=new_msrp)
        )
    if _money(old_dealer) != _money(new_dealer):
        changes.append(
            RecommendedChange(
                field="manufacturer_dealer_price_usd",
                current_value=old_dealer,
                manufacturer_value=new_dealer,
            )
        )
    return changes


def _summarize(results: Sequence[MasterReconciliationResult]) -> MasterReconciliationSummary:
    def count(status: MatchStatus) -> int:
        return sum(1 for item in results if item.primary_status == status)

    return MasterReconciliationSummary(
        total_rows=len(results),
        compared_rows=len(results),
        exact_match=count(MatchStatus.EXACT_MATCH),
        price_mismatch=count(MatchStatus.PRICE_MISMATCH),
        price_missing=count(MatchStatus.PRICE_MISSING),
        sku_not_found=count(MatchStatus.SKU_NOT_FOUND),
        part_number_invalid=count(MatchStatus.PART_NUMBER_INVALID),
        obsolete_only=count(MatchStatus.OBSOLETE_ONLY),
        needs_review=sum(1 for item in results if item.primary_status in NEEDS_REVIEW or _has_issue(item, "MULTIPLE_SPACEONE_ROWS")),
        multiple_spaceone_rows=sum(1 for item in results if _has_issue(item, "MULTIPLE_SPACEONE_ROWS")),
        source_price_conflict=count(MatchStatus.SOURCE_PRICE_CONFLICT),
        legacy_shipping=sum(1 for item in results if _has_issue(item, "LEGACY_SHIPPING_VALUE")),
    )


def _has_issue(item: MasterReconciliationResult, code: str) -> bool:
    return any(issue.code == code for issue in item.issues)


def _money(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), 2)


def spaceone_values_unchanged(before: SpaceOneValues, after: SpaceOneValues) -> bool:
    return before == after
