from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Optional, Sequence, Union

from openpyxl import load_workbook

from models import (
    PriceBookImportResult,
    PriceBookIssue,
    PriceBookSheetSummary,
    SKU,
    ValidationSeverity,
)

HEADER_SCAN_ROWS = 30
NO_DEALER_DISCOUNT_MARKERS = ("NO DEALER DISCOUNT",)
REQUIRED_FIELDS = ("sku", "description", "msrp", "dealer_price")
DEFAULT_COLUMN_ALIASES = {
    "sku": ("part number", "part #", "part#", "part no", "part no.", "sku"),
    "description": ("description", "desc", "item description"),
    "msrp": ("msrp", "msrp usd", "msrp (usd)", "list price"),
    "dealer_price": ("dealer price", "dealer price usd", "dealer price (usd)", "dealer"),
    "notes": ("notes", "note", "comments", "comment"),
}
KNOWN_SHEET_HINTS = {
    "revolution": ("ROV", "REVOLUTION"),
    "pivot": ("ROV", "PIVOT"),
    "photon": ("ROV", "PHOTON"),
    "spectra": ("ROV", "SPECTRA"),
    "mag": ("Utility Crawler", "MAG"),
    "vac": ("Utility Crawler", "VAC"),
    "pipetrekker": ("PipeTrekker", "PipeTrekker"),
}
CODE_MISSING_COLUMNS = "MISSING_REQUIRED_COLUMNS"
CODE_EMPTY_SKU = "EMPTY_SKU"
CODE_DUPLICATE_SKU = "DUPLICATE_SKU"
CODE_INVALID_MSRP = "INVALID_MSRP"
CODE_INVALID_DEALER_PRICE = "INVALID_DEALER_PRICE"
CODE_DEALER_GT_MSRP = "DEALER_PRICE_GT_MSRP"
CODE_MSRP_EQUALS_DEALER = "MSRP_EQUALS_DEALER_PRICE"
CODE_NO_DEALER_DISCOUNT = "NO_DEALER_DISCOUNT"


def parse_price_book(
    source: Union[str, Path, BinaryIO],
    *,
    source_price_book: Optional[str] = None,
    version: Optional[str] = None,
    column_aliases: Optional[dict] = None,
    imported_at: Optional[datetime] = None,
) -> PriceBookImportResult:
    aliases = _merge_aliases(column_aliases)
    book_name = source_price_book or _default_book_name(source)
    timestamp = imported_at or datetime.now(timezone.utc)
    workbook = load_workbook(source, data_only=True)
    result = PriceBookImportResult(
        source_price_book=book_name,
        version=version,
        imported_at=timestamp,
    )
    seen_skus: dict[str, str] = {}

    try:
        for sheet in workbook.worksheets:
            _parse_sheet(sheet, aliases, book_name, version, timestamp, result, seen_skus)
    finally:
        workbook.close()
    return result


def normalize_sku(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    text = str(value).strip()
    return text or None


def parse_money(value) -> tuple[Optional[float], bool]:
    if value is None or value == "":
        return None, False
    if isinstance(value, bool):
        return None, True
    if isinstance(value, (int, float)):
        return round(float(value), 2), False
    text = str(value).replace("$", "").replace(",", "").replace("USD", "").strip()
    if text == "":
        return None, False
    try:
        return round(float(text), 2), False
    except ValueError:
        return None, True


def calculate_dealer_rate(msrp_usd: Optional[float], dealer_price_usd: Optional[float]) -> Optional[float]:
    if msrp_usd is None or dealer_price_usd is None or msrp_usd == 0:
        return None
    return round(dealer_price_usd / msrp_usd, 4)


def sheet_product_hint(sheet_name: str) -> tuple[Optional[str], Optional[str]]:
    key = "".join(str(sheet_name).lower().split()).replace("_", "")
    return KNOWN_SHEET_HINTS.get(key, (None, None))


def notes_has_no_dealer_discount(notes: Optional[str]) -> bool:
    content = notes or ""
    return any(marker in content.upper() for marker in NO_DEALER_DISCOUNT_MARKERS)


def _parse_sheet(sheet, aliases, book_name, version, timestamp, result, seen_skus) -> None:
    family, model = sheet_product_hint(sheet.title)
    summary = PriceBookSheetSummary(
        sheet_name=sheet.title,
        product_family=family,
        model=model,
    )
    header = _find_header(sheet, aliases)
    if header is None:
        _add_issue(
            result,
            ValidationSeverity.BLOCKER,
            CODE_MISSING_COLUMNS,
            "Required columns were not found.",
            source_sheet=sheet.title,
            details="sku, description, msrp, dealer_price",
        )
        result.sheets.append(summary)
        return

    summary.header_found = True
    missing = [field for field in REQUIRED_FIELDS if field not in header["columns"]]
    if missing:
        _add_issue(
            result,
            ValidationSeverity.BLOCKER,
            CODE_MISSING_COLUMNS,
            "Required columns were not found.",
            source_sheet=sheet.title,
            details=", ".join(missing),
        )
        result.sheets.append(summary)
        return

    for row_number, values in header["rows"]:
        item, issues = _row_to_sku(
            values,
            header["columns"],
            sheet.title,
            family,
            model,
            book_name,
            version,
            timestamp,
            row_number,
            seen_skus,
        )
        for issue in issues:
            _add_issue_model(result, issue)
        if item is not None:
            result.items.append(item)
            summary.item_count += 1
            seen_skus[item.sku] = sheet.title
    result.sheets.append(summary)


def _find_header(sheet, aliases) -> Optional[dict]:
    rows = [(index, list(row)) for index, row in enumerate(sheet.iter_rows(values_only=True), start=1)]
    for header_index, (_, values) in enumerate(rows[:HEADER_SCAN_ROWS]):
        columns = _map_columns(values, aliases)
        if "sku" not in columns:
            continue
        return {"columns": columns, "rows": rows[header_index + 1 :]}
    return None


def _map_columns(values: Sequence, aliases: dict) -> dict:
    mapped = {}
    for index, value in enumerate(values):
        normalized = _normalize_header(value)
        if not normalized:
            continue
        for field, names in aliases.items():
            if field in mapped:
                continue
            if normalized in names:
                mapped[field] = index
                break
    return mapped


def _row_to_sku(
    values,
    columns,
    sheet_name,
    family,
    model,
    book_name,
    version,
    timestamp,
    row_number,
    seen_skus,
) -> tuple[Optional[SKU], list[PriceBookIssue]]:
    issues = []
    sku = normalize_sku(_cell(values, columns["sku"]))
    description = _optional_text(_cell(values, columns.get("description")))
    notes = _optional_text(_cell(values, columns.get("notes")))
    msrp, msrp_invalid = parse_money(_cell(values, columns.get("msrp")))
    dealer_price, dealer_invalid = parse_money(_cell(values, columns.get("dealer_price")))
    if sku is None and description is None and msrp is None and dealer_price is None and notes is None:
        return None, issues
    if sku is None:
        if description or msrp is not None or dealer_price is not None:
            issues.append(
                _issue(
                    ValidationSeverity.BLOCKER,
                    CODE_EMPTY_SKU,
                    "SKU is empty.",
                    source_sheet=sheet_name,
                    details=f"row={row_number}",
                )
            )
        return None, issues
    if sku in seen_skus:
        issues.append(
            _issue(
                ValidationSeverity.BLOCKER,
                CODE_DUPLICATE_SKU,
                "SKU is duplicated.",
                sku=sku,
                source_sheet=sheet_name,
                details=f"first_sheet={seen_skus[sku]};row={row_number}",
            )
        )
        return None, issues
    if msrp_invalid:
        issues.append(
            _issue(
                ValidationSeverity.BLOCKER,
                CODE_INVALID_MSRP,
                "MSRP is not a number.",
                sku=sku,
                source_sheet=sheet_name,
                details=f"row={row_number}",
            )
        )
    if dealer_invalid:
        issues.append(
            _issue(
                ValidationSeverity.BLOCKER,
                CODE_INVALID_DEALER_PRICE,
                "Dealer Price is not a number.",
                sku=sku,
                source_sheet=sheet_name,
                details=f"row={row_number}",
            )
        )
    if msrp is not None and dealer_price is not None and dealer_price > msrp:
        issues.append(
            _issue(
                ValidationSeverity.WARNING,
                CODE_DEALER_GT_MSRP,
                "Dealer Price is greater than MSRP.",
                sku=sku,
                source_sheet=sheet_name,
            )
        )
    if msrp is not None and dealer_price is not None and dealer_price == msrp:
        issues.append(
            _issue(
                ValidationSeverity.INFO,
                CODE_MSRP_EQUALS_DEALER,
                "Dealer Price equals MSRP.",
                sku=sku,
                source_sheet=sheet_name,
            )
        )
    if notes_has_no_dealer_discount(notes):
        issues.append(
            _issue(
                ValidationSeverity.INFO,
                CODE_NO_DEALER_DISCOUNT,
                "Notes include NO DEALER DISCOUNT.",
                sku=sku,
                source_sheet=sheet_name,
            )
        )
    item = SKU(
        sku=sku,
        product_family=family,
        model=model,
        description=description,
        msrp_usd=msrp,
        dealer_price_usd=dealer_price,
        dealer_rate=calculate_dealer_rate(msrp, dealer_price),
        notes=notes,
        source_price_book=book_name,
        source_sheet=sheet_name,
        price_book_version=version,
        last_synced_at=timestamp,
    )
    return item, issues


def _cell(values, index: Optional[int]):
    if index is None or index < 0 or index >= len(values):
        return None
    return values[index]


def _optional_text(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_header(value) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().split())


def _merge_aliases(column_aliases: Optional[dict]) -> dict:
    merged = {field: tuple(names) for field, names in DEFAULT_COLUMN_ALIASES.items()}
    if not column_aliases:
        return merged
    for field, names in column_aliases.items():
        extra = tuple(_normalize_header(name) for name in names)
        merged[field] = extra + merged.get(field, ())
    return merged


def _default_book_name(source) -> Optional[str]:
    name = getattr(source, "name", None)
    if name:
        return Path(name).stem
    if isinstance(source, (str, Path)):
        return Path(source).stem
    return None


def _issue(
    severity: ValidationSeverity,
    code: str,
    message: str,
    sku: Optional[str] = None,
    source_sheet: Optional[str] = None,
    details: Optional[str] = None,
) -> PriceBookIssue:
    return PriceBookIssue(
        severity=severity,
        code=code,
        message=message,
        sku=sku,
        source_sheet=source_sheet,
        details=details,
    )


def _add_issue(result: PriceBookImportResult, severity, code, message, **kwargs) -> None:
    _add_issue_model(result, _issue(severity, code, message, **kwargs))


def _add_issue_model(result: PriceBookImportResult, issue: PriceBookIssue) -> None:
    if issue.severity == ValidationSeverity.BLOCKER:
        result.errors.append(issue)
    elif issue.severity == ValidationSeverity.WARNING:
        result.warnings.append(issue)
    else:
        result.infos.append(issue)
