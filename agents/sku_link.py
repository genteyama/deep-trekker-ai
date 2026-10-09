from datetime import datetime, timezone
from typing import Optional, Sequence

from agents.master_reconciliation import (
    collect_manufacturer_candidates,
    get_manufacturer_price_by_sku,
    reconcile_spaceone_master,
)
from models import (
    CurrentManufacturerValues,
    LegacyManufacturerValues,
    LinkMethod,
    LinkStatus,
    ManualLinkResult,
    ManufacturerSkuLink,
    MatchStatus,
    PriceBookImportResult,
    PriceDifference,
    PriceSourceType,
    QuotePriceSnapshot,
    SKUMasterCandidate,
    SkuDuplicateClass,
    SkuLinkPreview,
    SkuLinkPreviewItem,
    SkuSourceStatus,
    SpaceOneMasterItem,
)

AUTO_LINK_MATCHES = {
    MatchStatus.EXACT_MATCH,
    MatchStatus.PRICE_MISMATCH,
    MatchStatus.PRICE_MISSING,
    MatchStatus.NO_MANUFACTURER_PRICE,
}
REVIEW_MATCHES = {
    MatchStatus.SKU_NOT_FOUND,
    MatchStatus.PART_NUMBER_INVALID,
    MatchStatus.SOURCE_PRICE_CONFLICT,
    MatchStatus.OBSOLETE_ONLY,
}


def build_current_manufacturer_master(
    candidates: Sequence[SKUMasterCandidate],
) -> list[SKUMasterCandidate]:
    current = []
    for candidate in candidates:
        if candidate.duplicate_class == SkuDuplicateClass.PRICE_CONFLICT:
            continue
        if candidate.source_status == SkuSourceStatus.OBSOLETE:
            continue
        current.append(candidate)
    return current


def get_current_manufacturer_values(
    manufacturer_sku: Optional[str],
    price_book_candidates: Sequence[SKUMasterCandidate],
    *,
    price_book_version: Optional[str] = None,
) -> Optional[CurrentManufacturerValues]:
    candidate = get_manufacturer_price_by_sku(manufacturer_sku, price_book_candidates)
    if candidate is None or candidate.duplicate_class == SkuDuplicateClass.PRICE_CONFLICT:
        return None
    notes = []
    sheets = []
    books = []
    for occurrence in candidate.occurrences:
        if occurrence.notes and occurrence.notes not in notes:
            notes.append(occurrence.notes)
        if occurrence.source_sheet and occurrence.source_sheet not in sheets:
            sheets.append(occurrence.source_sheet)
        if occurrence.source_price_book and occurrence.source_price_book not in books:
            books.append(occurrence.source_price_book)
    return CurrentManufacturerValues(
        sku=candidate.sku,
        description=candidate.description,
        msrp_usd=candidate.msrp_usd,
        dealer_price_usd=candidate.dealer_price_usd,
        dealer_rate=candidate.dealer_rate,
        notes=notes,
        source_status=candidate.source_status,
        price_book=" / ".join(books) if books else None,
        source_sheets=sheets,
        price_book_version=price_book_version,
    )


def create_quote_price_snapshot(
    sku: str,
    price_book_candidates: Sequence[SKUMasterCandidate],
    *,
    snapshot_id: str,
    price_book_version: Optional[str] = None,
    source_reference: Optional[str] = None,
    captured_at: Optional[datetime] = None,
    exchange_rate: Optional[float] = None,
) -> QuotePriceSnapshot:
    current = get_current_manufacturer_values(sku, price_book_candidates, price_book_version=price_book_version)
    found = current is not None and current.dealer_price_usd is not None
    return QuotePriceSnapshot(
        snapshot_id=snapshot_id,
        sku=sku,
        price_book=current.price_book if current else None,
        price_book_version=price_book_version,
        manufacturer_msrp_usd=current.msrp_usd if current else None,
        manufacturer_dealer_price_usd=current.dealer_price_usd if current else None,
        exchange_rate=exchange_rate,
        captured_at=captured_at or datetime.now(timezone.utc),
        source_reference=source_reference,
        price_source_type=PriceSourceType.OFFICIAL_PRICE_BOOK if found else PriceSourceType.UNKNOWN,
    )


def price_source_type_of(snapshot: Optional[QuotePriceSnapshot]) -> PriceSourceType:
    if snapshot is None:
        return PriceSourceType.UNKNOWN
    if snapshot.price_source_type is not None:
        return PriceSourceType(snapshot.price_source_type)
    # Snapshots saved before price_source_type existed: only create_quote_price_snapshot() read values
    # from an imported price book. "scenario-input" snapshots never had a verified source.
    if (
        snapshot.source_reference != "scenario-input"
        and snapshot.price_book
        and snapshot.manufacturer_dealer_price_usd is not None
    ):
        return PriceSourceType.OFFICIAL_PRICE_BOOK
    return PriceSourceType.UNKNOWN


def is_official_price_snapshot(snapshot: Optional[QuotePriceSnapshot]) -> bool:
    return price_source_type_of(snapshot) == PriceSourceType.OFFICIAL_PRICE_BOOK


def build_sku_link_preview(
    items: Sequence[SpaceOneMasterItem],
    *price_books: Optional[PriceBookImportResult],
    linked_by: Optional[str] = None,
) -> SkuLinkPreview:
    report = reconcile_spaceone_master(items, *price_books)
    candidates = collect_manufacturer_candidates(*price_books)
    versions = {
        result.source_price_book: result.version
        for result in price_books
        if result is not None and result.source_price_book
    }
    preview_items = []
    for item, recon in zip(items, report.results):
        link = _auto_link(item, recon, linked_by)
        current = None
        if link.link_status in {LinkStatus.AUTO_LINKED, LinkStatus.MANUALLY_LINKED} and link.manufacturer_sku:
            version = versions.get(link.manufacturer_price_book) if link.manufacturer_price_book else None
            current = get_current_manufacturer_values(
                link.manufacturer_sku,
                candidates,
                price_book_version=version,
            )
        legacy = LegacyManufacturerValues(
            legacy_manufacturer_msrp=item.values.manufacturer_msrp_usd,
            legacy_manufacturer_dealer_price=item.values.manufacturer_dealer_price_usd,
            legacy_reference=item.old_reference,
        )
        preview_items.append(
            SkuLinkPreviewItem(
                spaceone_item_id=item.spaceone_item_id,
                spaceone_sku=item.spaceone_sku,
                name_ja=item.values.name_ja,
                spaceone_sales_price=item.values.sales_price,
                match_status=recon.primary_status,
                link=link,
                current_values=current,
                legacy=legacy,
                price_difference=_price_difference(legacy, current),
                review_reason=_review_reason(recon, link),
            )
        )
    return _with_counts(
        SkuLinkPreview(items=preview_items, current_candidates=list(candidates))
    )


def try_manual_link(
    preview: SkuLinkPreview,
    spaceone_item_id: str,
    manufacturer_sku: Optional[str],
    *,
    linked_by: Optional[str] = None,
) -> ManualLinkResult:
    sku = (manufacturer_sku or "").strip()
    if not sku:
        return ManualLinkResult(accepted=False, message="Manufacturer SKU is empty.", preview=preview)
    target = next((item for item in preview.items if item.spaceone_item_id == spaceone_item_id), None)
    if target is None:
        return ManualLinkResult(accepted=False, message="SpaceOne item was not found.", preview=preview)
    candidate = get_manufacturer_price_by_sku(sku, preview.current_candidates)
    if candidate is None:
        return ManualLinkResult(
            accepted=False,
            message="That SKU does not exist in the current official Manufacturer Master.",
            preview=preview,
        )
    if candidate.duplicate_class == SkuDuplicateClass.PRICE_CONFLICT:
        return ManualLinkResult(
            accepted=False,
            message="That SKU has a manufacturer price conflict, so it cannot be linked.",
            preview=preview,
        )
    if candidate.source_status == SkuSourceStatus.OBSOLETE:
        target.review_reason = "SKU exists only on an obsolete manufacturer sheet. It was not linked."
        target.link.link_status = LinkStatus.REVIEW_REQUIRED
        target.link.manufacturer_sku = None
        target.link.link_method = LinkMethod.NONE
        return ManualLinkResult(
            accepted=False,
            message="Obsolete-only SKU stays REVIEW_REQUIRED.",
            preview=_with_counts(preview),
        )
    now = datetime.now(timezone.utc)
    books = []
    for occurrence in candidate.occurrences:
        if occurrence.source_price_book and occurrence.source_price_book not in books:
            books.append(occurrence.source_price_book)
    target.link.manufacturer_sku = candidate.sku
    target.link.manufacturer_price_book = " / ".join(books) if books else None
    target.link.link_status = LinkStatus.MANUALLY_LINKED
    target.link.link_method = LinkMethod.MANUAL_SKU_ENTRY
    target.link.linked_at = now
    target.link.linked_by = linked_by
    target.link.notes = "Human entered a manufacturer SKU that exists on the current active master."
    target.current_values = get_current_manufacturer_values(candidate.sku, preview.current_candidates)
    target.price_difference = _price_difference(target.legacy, target.current_values)
    target.review_reason = None
    return ManualLinkResult(accepted=True, message="SKU was linked.", preview=_with_counts(preview))


def _auto_link(item: SpaceOneMasterItem, recon, linked_by: Optional[str]) -> ManufacturerSkuLink:
    now = datetime.now(timezone.utc)
    link = ManufacturerSkuLink(
        manufacturer_sku_link_id=f"link-{item.spaceone_item_id}",
        spaceone_item_id=item.spaceone_item_id,
        spaceone_sku=item.spaceone_sku,
        link_status=LinkStatus.UNLINKED,
        link_method=LinkMethod.NONE,
    )
    if item.is_legacy_shipping:
        link.link_status = LinkStatus.NO_LINK_REQUIRED
        link.notes = "Shipping rows are managed by ShippingRule, not Manufacturer SKU Master."
        return link
    if recon.primary_status in REVIEW_MATCHES or not item.normalized_sku or item.part_number_invalid:
        link.link_status = LinkStatus.REVIEW_REQUIRED
        return link
    candidate = recon.manufacturer_candidate
    if (
        recon.primary_status in AUTO_LINK_MATCHES
        and candidate is not None
        and candidate.duplicate_class != SkuDuplicateClass.PRICE_CONFLICT
        and candidate.source_status != SkuSourceStatus.OBSOLETE
    ):
        link.manufacturer_sku = candidate.sku
        link.manufacturer_price_book = recon.manufacturer_price_book
        link.link_status = LinkStatus.AUTO_LINKED
        link.link_method = LinkMethod.AUTO_SKU_MATCH
        link.linked_at = now
        link.linked_by = linked_by
        link.notes = "SKU uniquely matched an active manufacturer candidate."
        return link
    link.link_status = LinkStatus.REVIEW_REQUIRED
    return link


def _price_difference(
    legacy: LegacyManufacturerValues,
    current: Optional[CurrentManufacturerValues],
) -> Optional[PriceDifference]:
    if current is None:
        return None
    return PriceDifference(
        legacy_msrp=legacy.legacy_manufacturer_msrp,
        current_msrp=current.msrp_usd,
        msrp_delta=_delta(current.msrp_usd, legacy.legacy_manufacturer_msrp),
        legacy_dealer_price=legacy.legacy_manufacturer_dealer_price,
        current_dealer_price=current.dealer_price_usd,
        dealer_price_delta=_delta(current.dealer_price_usd, legacy.legacy_manufacturer_dealer_price),
    )


def _delta(current: Optional[float], legacy: Optional[float]) -> Optional[float]:
    if current is None or legacy is None:
        return None
    return round(current - legacy, 2)


def _review_reason(recon, link: ManufacturerSkuLink) -> Optional[str]:
    if link.link_status != LinkStatus.REVIEW_REQUIRED:
        return None
    messages = [issue.message for issue in recon.issues if issue.code != "MULTIPLE_SPACEONE_ROWS"]
    return "; ".join(messages) or "Manufacturer SKU could not be determined uniquely."


def _with_counts(preview: SkuLinkPreview) -> SkuLinkPreview:
    preview.total_items = len(preview.items)
    preview.auto_linked = _count(preview, LinkStatus.AUTO_LINKED)
    preview.review_required = _count(preview, LinkStatus.REVIEW_REQUIRED)
    preview.manually_linked = _count(preview, LinkStatus.MANUALLY_LINKED)
    preview.no_link_required = _count(preview, LinkStatus.NO_LINK_REQUIRED)
    preview.unlinked = _count(preview, LinkStatus.UNLINKED)
    return preview


def _count(preview: SkuLinkPreview, status: LinkStatus) -> int:
    return sum(1 for item in preview.items if item.link.link_status == status)
