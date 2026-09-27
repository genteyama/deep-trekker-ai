from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Optional, Sequence, Union

from models import PriceBookDiff, PriceBookDiffItem, PriceBookDiffType, PriceBookImportResult, SKU
from parsers.price_book_parser import parse_price_book

AGENT_INTERNAL_NAME = "quote_control_agent"


class SkuMasterStore:
    def __init__(self, items: Optional[list[SKU]] = None) -> None:
        self.items: list[SKU] = list(items or [])

    def snapshot(self) -> list[SKU]:
        return list(self.items)


def import_price_book(
    source: Union[str, Path, BinaryIO],
    *,
    source_price_book: Optional[str] = None,
    version: Optional[str] = None,
    column_aliases: Optional[dict] = None,
    imported_at: Optional[datetime] = None,
    official_master: Optional[SkuMasterStore] = None,
) -> PriceBookImportResult:
    result = parse_price_book(
        source,
        source_price_book=source_price_book,
        version=version,
        column_aliases=column_aliases,
        imported_at=imported_at,
    )
    if official_master is not None:
        _ = official_master.snapshot()
    return result


def diff_price_books(
    current_items: Sequence[SKU],
    incoming_items: Sequence[SKU],
) -> PriceBookDiff:
    current_by_sku = {item.sku: item for item in current_items}
    incoming_by_sku = {item.sku: item for item in incoming_items}
    items = []

    for sku, incoming in incoming_by_sku.items():
        current = current_by_sku.get(sku)
        if current is None:
            items.append(
                PriceBookDiffItem(
                    sku=sku,
                    change_types=[PriceBookDiffType.NEW_SKU],
                    new_msrp=incoming.msrp_usd,
                    new_dealer_price=incoming.dealer_price_usd,
                    new_description=incoming.description,
                    new_notes=incoming.notes,
                )
            )
            continue
        change_types = []
        if _money(current.msrp_usd) != _money(incoming.msrp_usd) or _money(
            current.dealer_price_usd
        ) != _money(incoming.dealer_price_usd):
            change_types.append(PriceBookDiffType.PRICE_CHANGED)
        if _text(current.description) != _text(incoming.description):
            change_types.append(PriceBookDiffType.DESCRIPTION_CHANGED)
        if _text(current.notes) != _text(incoming.notes):
            change_types.append(PriceBookDiffType.NOTES_CHANGED)
        if not change_types:
            change_types.append(PriceBookDiffType.UNCHANGED)
        items.append(
            PriceBookDiffItem(
                sku=sku,
                change_types=change_types,
                old_msrp=current.msrp_usd,
                new_msrp=incoming.msrp_usd,
                old_dealer_price=current.dealer_price_usd,
                new_dealer_price=incoming.dealer_price_usd,
                old_description=current.description,
                new_description=incoming.description,
                old_notes=current.notes,
                new_notes=incoming.notes,
            )
        )

    for sku, current in current_by_sku.items():
        if sku in incoming_by_sku:
            continue
        items.append(
            PriceBookDiffItem(
                sku=sku,
                change_types=[PriceBookDiffType.REMOVED_SKU],
                old_msrp=current.msrp_usd,
                old_dealer_price=current.dealer_price_usd,
                old_description=current.description,
                old_notes=current.notes,
            )
        )
    return PriceBookDiff(items=items)


def _money(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), 2)


def _text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = value.strip()
    return text or None
