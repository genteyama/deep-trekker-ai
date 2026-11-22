"""CSV fallback for a manufacturer price master (one sheet only).

A CSV holds one sheet, so it is never a master on its own. The current Active workbook is copied
(cell values only), the sheet the person selected is replaced with the CSV rows as-is, and the
whole workbook goes through the existing parser, validate_price_master() and the same diff used
for the online review. Nothing is activated until a person explicitly approves the review.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
import hashlib
import io
import logging
from pathlib import PurePosixPath
from typing import Optional

from openpyxl import load_workbook

from agents.online_price_master import (
    OnlinePriceReview,
    OnlinePriceReviewStatus,
    _active_import_id,
    inspect_online_workbook,
)
from agents.price_master import (
    GENERIC_MANUFACTURER_MASTERS,
    _rejected,
    get_active_master,
    import_price_master,
    parse_manufacturer_price_master,
    safe_display_filename,
)
from models import PriceMasterImportOutcome, PriceMasterSourceType, PriceMasterType
from parsers.price_book_parser import CODE_MISSING_COLUMNS
from parsers.spectra_gold_parser import CODE_COLUMNS_MISSING as SPECTRA_COLUMNS_MISSING
from repositories.actor import current_actor
from repositories.sqlite import now_iso
from repositories.sqlite_price_master_repository import SqlitePriceMasterRepository

logger = logging.getLogger(__name__)

# Sheets a CSV may replace. Hidden sheets (CONFIG, SPECTRA GOLD's other product tabs) are never targets.
CSV_FALLBACK_SHEETS: dict[PriceMasterType, tuple[str, ...]] = {
    PriceMasterType.DT40: ("DTG3", "PHOTON", "PIVOT", "REVOLUTION-DC", "VAC & MAG", "REVOLUTION-OBSOLETE"),
    PriceMasterType.PT30: ("A-150", "A-200", "PT-VAN"),
    PriceMasterType.SPECTRA_GOLD: ("SPECTRA",),
}
MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_CSV_ROWS = 20000
MAX_CSV_COLUMNS = 100


class CsvFallbackError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class CsvFallbackReview:
    master_type: PriceMasterType
    sheet_name: str
    csv_filename: str
    csv_sha256: str
    base_import_id: str
    review: OnlinePriceReview
    created_at: str = field(default_factory=now_iso)

    @property
    def status(self) -> OnlinePriceReviewStatus:
        return self.review.status


def build_csv_fallback_review(
    master_type: Optional[PriceMasterType],
    sheet_name: Optional[str],
    csv_filename: Optional[str],
    csv_bytes: Optional[bytes],
    *,
    repository: Optional[SqlitePriceMasterRepository] = None,
) -> CsvFallbackReview:
    """Validate a CSV against the current Active master and diff it. Never registers or activates.

    Raises CsvFallbackError for anything that must be rejected before a workbook can be built.
    Workbook-level validation failures come back as a review with a failure status.
    """
    if not master_type:
        raise CsvFallbackError("PRICE_BOOK_REQUIRED")
    try:
        master_type = PriceMasterType(master_type)
    except ValueError:
        raise CsvFallbackError("PRICE_BOOK_NOT_ALLOWED") from None
    if master_type not in CSV_FALLBACK_SHEETS:
        raise CsvFallbackError("PRICE_BOOK_NOT_ALLOWED")
    if not sheet_name:
        raise CsvFallbackError("SHEET_REQUIRED")
    if sheet_name not in CSV_FALLBACK_SHEETS[master_type]:
        raise CsvFallbackError("SHEET_NOT_ALLOWED")
    display_name = safe_display_filename(csv_filename or "upload.csv")
    if not display_name.lower().endswith(".csv"):
        raise CsvFallbackError("NOT_CSV")
    if not csv_bytes or not csv_bytes.strip():
        raise CsvFallbackError("CSV_EMPTY")
    if len(csv_bytes) > MAX_CSV_BYTES:
        raise CsvFallbackError("CSV_TOO_LARGE")

    repo = repository or SqlitePriceMasterRepository()
    active = get_active_master(master_type, repo)
    if active is None:
        raise CsvFallbackError("ACTIVE_MASTER_REQUIRED")

    rows = _read_csv(csv_bytes)
    data = _replace_sheet(active.path, sheet_name, rows)
    _require_sheet_columns(master_type, data, sheet_name, repo)
    review = inspect_online_workbook(
        master_type,
        data,
        filename=_snapshot_filename(master_type, sheet_name),
        repository=repo,
    )
    if review.active_import_id != active.record.import_id:
        raise CsvFallbackError("CSV_REVIEW_STALE")
    return CsvFallbackReview(
        master_type=master_type,
        sheet_name=sheet_name,
        csv_filename=display_name,
        csv_sha256=hashlib.sha256(csv_bytes).hexdigest(),
        base_import_id=active.record.import_id,
        review=review,
    )


def activate_csv_fallback(
    fallback: CsvFallbackReview,
    *,
    repository: Optional[SqlitePriceMasterRepository] = None,
) -> PriceMasterImportOutcome:
    """Explicit human approval: register the reviewed workbook as the new Active master."""
    review = fallback.review
    if review.status != OnlinePriceReviewStatus.CHANGES_PENDING or not review.data:
        return _rejected(fallback.master_type, "CSV_REVIEW_REQUIRED")
    repo = repository or SqlitePriceMasterRepository()
    try:
        current = _active_import_id(fallback.master_type, repo)
    except Exception:
        logger.exception("csv_fallback_active_check_failed type=%s", fallback.master_type.value)
        return _rejected(fallback.master_type, "CSV_REVIEW_STALE")
    if current != fallback.base_import_id:
        return _rejected(fallback.master_type, "CSV_REVIEW_STALE")
    provenance = {
        "csv_filename": fallback.csv_filename,
        "csv_sha256": fallback.csv_sha256,
        "price_book": fallback.master_type.value,
        "replaced_sheet": fallback.sheet_name,
        "base_import_id": fallback.base_import_id,
        "reviewed_at": fallback.created_at,
        "approved_by": current_actor(),
    }
    return import_price_master(
        fallback.master_type,
        review.filename,
        review.data,
        repository=repo,
        source_type=PriceMasterSourceType.CSV_UPLOAD,
        provenance=provenance,
    )


def _read_csv(csv_bytes: bytes) -> list[list[str]]:
    try:
        text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise CsvFallbackError("CSV_UNREADABLE") from None
    try:
        rows = list(csv.reader(io.StringIO(text, newline="")))
    except csv.Error:
        raise CsvFallbackError("CSV_UNREADABLE") from None
    if not any(any(cell.strip() for cell in row) for row in rows):
        raise CsvFallbackError("CSV_EMPTY")
    if len(rows) > MAX_CSV_ROWS or any(len(row) > MAX_CSV_COLUMNS for row in rows):
        raise CsvFallbackError("CSV_TOO_LARGE")
    return rows


def _replace_sheet(base_path, sheet_name: str, rows: list[list[str]]) -> bytes:
    """Copy the Active workbook as values and replace only the selected sheet with the CSV rows."""
    try:
        # data_only keeps the cached values the parsers read; formulas would lose them on save.
        workbook = load_workbook(base_path, data_only=True)
    except Exception:
        logger.exception("csv_fallback_base_unreadable")
        raise CsvFallbackError("ACTIVE_MASTER_UNREADABLE") from None
    try:
        # Exact name match (case / surrounding spaces ignored); never a partial or fuzzy match.
        wanted = sheet_name.strip().casefold()
        matches = [item for item in workbook.worksheets if item.title.strip().casefold() == wanted]
        if len(matches) != 1:
            raise CsvFallbackError("SHEET_NOT_IN_ACTIVE_MASTER")
        sheet = matches[0]
        if sheet.sheet_state != "visible":
            raise CsvFallbackError("SHEET_NOT_ALLOWED")
        for merged in list(sheet.merged_cells.ranges):
            sheet.unmerge_cells(str(merged))
        for row in sheet.iter_rows():
            for cell in row:
                cell.value = None
        for row_index, values in enumerate(rows, start=1):
            for column_index, value in enumerate(values, start=1):
                # Written as-is: the existing parsers interpret text prices and SKUs themselves.
                sheet.cell(row=row_index, column=column_index, value=value if value != "" else None)
        buffer = io.BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()
    finally:
        workbook.close()


def _require_sheet_columns(master_type: PriceMasterType, data: bytes, sheet_name: str, repository) -> None:
    """The replaced sheet must be readable by the Price Book's own parser (header found, SKUs present)."""
    from agents.online_price_master import _write_staging

    staging = _write_staging(repository, data)
    try:
        try:
            book = parse_manufacturer_price_master(master_type, staging, version="csv-fallback")
        except Exception:
            raise CsvFallbackError("PARSER_FAILED") from None
    finally:
        if staging.exists():
            staging.unlink()
    if master_type in GENERIC_MANUFACTURER_MASTERS:
        wanted = sheet_name.strip().casefold()
        summary = next((item for item in book.sheets if item.sheet_name.strip().casefold() == wanted), None)
        missing_columns = any(
            issue.code == CODE_MISSING_COLUMNS and (issue.source_sheet or "").strip().casefold() == wanted
            for issue in book.errors
        )
        if summary is None or not summary.header_found or missing_columns:
            raise CsvFallbackError("CSV_MISSING_COLUMNS")
        if summary.item_count == 0:
            raise CsvFallbackError("CSV_NO_SKUS")
        return
    if any(issue.code == SPECTRA_COLUMNS_MISSING for issue in book.errors):
        raise CsvFallbackError("CSV_MISSING_COLUMNS")
    if not book.candidates:
        raise CsvFallbackError("CSV_NO_SKUS")


def _snapshot_filename(master_type: PriceMasterType, sheet_name: str) -> str:
    safe_sheet = "".join(char if char.isalnum() or char in "-_" else "_" for char in sheet_name)
    return PurePosixPath(f"{master_type.value}_{safe_sheet}_csv-fallback.xlsx").name
