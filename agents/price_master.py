"""Managed price masters (DT40 / PT30 / SpaceOne master / quote-calc).

Every consumer resolves the active master through this module. Files are imported once, validated
with the existing parsers, stored immutably under <db dir>/price_masters (runtime/price_masters in
production) and activated only after validation succeeds. No fixed local folder is ever searched.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import logging
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Optional, Sequence
from uuid import uuid4

from agents.pricing_policy import extract_pricing_policies
from agents.quote_control_agent import import_price_book
from models import (
    LandedCostPolicyCandidate,
    PriceBookImportResult,
    PriceMasterImport,
    PriceMasterImportOutcome,
    PriceMasterImportStatus,
    PriceMasterSourceType,
    PriceMasterType,
    PriceMasterValidationStatus,
    PriceSourceType,
    QuoteDraft,
    SpaceOneMasterImportResult,
)
from parsers.quote_calc_parser import extract_quote_calc_audit
from parsers.spaceone_master_parser import parse_spaceone_master
from repositories.sqlite import now_iso
from repositories.sqlite_price_master_repository import SqlitePriceMasterRepository

logger = logging.getLogger(__name__)

MANUFACTURER_MASTERS = (PriceMasterType.DT40, PriceMasterType.PT30)
ALLOWED_EXTENSION = ".xlsx"
XLSX_SIGNATURE = b"PK\x03\x04"
STAGING_DIRECTORY = ".staging"


class PriceMasterValidationError(ValueError):
    def __init__(self, message: str, code: str = "VALIDATION_FAILED"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ActivePriceMaster:
    record: PriceMasterImport
    path: Path


@dataclass(frozen=True)
class ActivePriceBook:
    record: PriceMasterImport
    book: PriceBookImportResult


def import_price_master(
    master_type: PriceMasterType,
    original_filename: Optional[str],
    data: bytes,
    *,
    repository: Optional[SqlitePriceMasterRepository] = None,
    source_type: PriceMasterSourceType = PriceMasterSourceType.FILE_UPLOAD,
    provenance: Optional[dict] = None,
) -> PriceMasterImportOutcome:
    """Validate, store and activate one upload. A rejected upload never changes the active master."""
    master_type = PriceMasterType(master_type)
    repo = repository or SqlitePriceMasterRepository()
    display_name = safe_display_filename(original_filename)
    if not display_name.lower().endswith(ALLOWED_EXTENSION):
        return _rejected(master_type, "NOT_XLSX")
    if not data or not data.startswith(XLSX_SIGNATURE):
        return _rejected(master_type, "NOT_XLSX")

    sha256 = hashlib.sha256(data).hexdigest()
    existing = repo.find_by_sha(master_type, sha256)
    if existing is not None and materialize_stored_file(repo, existing).is_file():
        if existing.active:
            return PriceMasterImportOutcome(
                status=PriceMasterImportStatus.ALREADY_ACTIVE, master_type=master_type, record=existing
            )
        try:
            # An earlier import is re-checked against the current rules before it becomes active again.
            validate_price_master(master_type, resolve_stored_path(repo, existing))
        except PriceMasterValidationError as error:
            logger.warning("price_master_reactivation_rejected type=%s import_id=%s reason=%s", master_type.value, existing.import_id, error)
            return _rejected(master_type, error.code)
        return PriceMasterImportOutcome(
            status=PriceMasterImportStatus.REACTIVATED, master_type=master_type, record=repo.activate(existing.import_id)
        )

    root = repo.storage_root
    staging = root / STAGING_DIRECTORY / f"{uuid4().hex}{ALLOWED_EXTENSION}"
    staging.parent.mkdir(parents=True, exist_ok=True)
    try:
        staging.write_bytes(data)
        try:
            summary = validate_price_master(master_type, staging)
            if provenance:
                summary = {**summary, "online_source": dict(provenance)}
        except PriceMasterValidationError as error:
            logger.warning("price_master_rejected type=%s file=%s reason=%s", master_type.value, display_name, error)
            return _rejected(master_type, error.code)
        import_id = _new_import_id(master_type)
        relative = PurePosixPath(master_type.value, f"{import_id}{ALLOWED_EXTENSION}")
        target = root.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, target)
        record = PriceMasterImport(
            import_id=import_id,
            master_type=master_type,
            source_type=source_type,
            original_filename=display_name,
            stored_path=relative.as_posix(),
            sha256=sha256,
            size_bytes=len(data),
            imported_at=now_iso(),
            validation_status=PriceMasterValidationStatus.VALID,
            validation_summary=summary,
        )
        try:
            repo.add(record)
            activated = repo.activate(import_id)
        except Exception:
            logger.exception("price_master_register_failed type=%s import_id=%s", master_type.value, import_id)
            if target.exists():
                target.unlink()
            return _rejected(master_type, "STORAGE_FAILED")
        return PriceMasterImportOutcome(status=PriceMasterImportStatus.ACTIVATED, master_type=master_type, record=activated)
    except OSError:
        logger.exception("price_master_storage_failed type=%s", master_type.value)
        return _rejected(master_type, "STORAGE_FAILED")
    finally:
        if staging.exists():
            staging.unlink()


def validate_price_master(master_type: PriceMasterType, path: Path) -> dict:
    """Run the existing parser for the master type. Opening as xlsx alone is not enough."""
    master_type = PriceMasterType(master_type)
    try:
        if master_type in MANUFACTURER_MASTERS:
            book = import_price_book(path, source_price_book=master_type.value, version="validation")
            priced = [item for item in book.candidates if item.dealer_price_usd is not None]
            if not priced:
                raise PriceMasterValidationError("No SKU with a dealer price was found.")
            _require_manufacturer_identity(master_type, book)
            return {
                "sku_count": len(priced),
                "sheet_count": sum(1 for sheet in book.sheets if sheet.header_found),
                "error_count": len(book.errors),
                "warning_count": len(book.warnings),
            }
        if master_type == PriceMasterType.SO_MASTER:
            master = parse_spaceone_master(path, source_name=master_type.value)
            items = [item for item in master.items if item.normalized_sku]
            policies = extract_pricing_policies(master.items)
            if not items or not policies:
                raise PriceMasterValidationError("No SpaceOne SKU rows with pricing formulas were found.")
            return {"item_count": len(items), "policy_count": len(policies)}
        audit = extract_quote_calc_audit(path)
        policy = audit.policy_candidate
        # Quotes take all three values from QUOTE_CALC: a missing insurance rate would silently drop
        # insurance from landed cost, and a missing markup drops shipping sales candidates.
        values = {
            "import_tax_rate": policy.import_tax_rate if policy else None,
            "insurance_rate": policy.insurance_rate if policy else None,
            "shipping_markup": policy.shipping_markup_multiplier if policy else None,
        }
        missing = [name for name, value in values.items() if not _is_real_number(value)]
        if missing:
            raise PriceMasterValidationError(f"Quote-calc policy values missing: {', '.join(missing)}", "POLICY_INCOMPLETE")
        # Only values that cannot work arithmetically are refused; no business value or upper limit is imposed.
        unusable = [
            name
            for name, value in values.items()
            if (value <= 0 if name == "shipping_markup" else value < 0)
        ]
        if unusable:
            raise PriceMasterValidationError(f"Quote-calc policy values unusable: {', '.join(unusable)}")
        return {
            "import_tax_rate": policy.import_tax_rate,
            "insurance_rate": policy.insurance_rate,
            "shipping_markup": policy.shipping_markup_multiplier,
        }
    except PriceMasterValidationError:
        raise
    except Exception as error:  # parser failures on arbitrary uploads must not reach staff as tracebacks
        logger.exception("price_master_parse_failed type=%s", master_type.value)
        raise PriceMasterValidationError(f"{type(error).__name__}: {error}") from error


def _require_manufacturer_identity(master_type: PriceMasterType, book: PriceBookImportResult) -> None:
    # Manufacturer books label their dealer column with the book code ("DT40" / "PT30"). Every sheet that
    # produced SKUs must carry this slot's own code; another code, a generic header or a mix is rejected.
    labels = {sheet.dealer_price_label for sheet in book.sheets if sheet.item_count > 0}
    if labels != {master_type.value.lower()}:
        raise PriceMasterValidationError(
            f"Dealer price column labels {sorted(str(item) for item in labels)} do not identify {master_type.value}.",
            "MASTER_TYPE_UNCONFIRMED",
        )


def _is_real_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def get_active_master(
    master_type: PriceMasterType,
    repository: Optional[SqlitePriceMasterRepository] = None,
) -> Optional[ActivePriceMaster]:
    repo = repository or SqlitePriceMasterRepository()
    record = repo.get_active(PriceMasterType(master_type))
    if record is None:
        return None
    path = materialize_stored_file(repo, record)
    if not path.is_file():
        logger.error("price_master_file_missing type=%s import_id=%s", record.master_type.value, record.import_id)
        return None
    return ActivePriceMaster(record=record, path=path)


def active_price_books(repository: Optional[SqlitePriceMasterRepository] = None) -> list[ActivePriceBook]:
    repo = repository or SqlitePriceMasterRepository()
    books = []
    for master_type in MANUFACTURER_MASTERS:
        active = get_active_master(master_type, repo)
        if active is None:
            continue
        book = import_price_book(active.path, source_price_book=master_type.value, version=active.record.import_id)
        books.append(ActivePriceBook(record=active.record, book=book))
    return books


def load_active_spaceone_master(
    repository: Optional[SqlitePriceMasterRepository] = None,
) -> Optional[tuple[SpaceOneMasterImportResult, PriceMasterImport]]:
    active = get_active_master(PriceMasterType.SO_MASTER, repository)
    if active is None:
        return None
    return parse_spaceone_master(active.path, source_name=PriceMasterType.SO_MASTER.value), active.record


def load_active_landed_policy(
    repository: Optional[SqlitePriceMasterRepository] = None,
) -> Optional[LandedCostPolicyCandidate]:
    active = get_active_master(PriceMasterType.QUOTE_CALC, repository)
    if active is None:
        return None
    policy = extract_quote_calc_audit(active.path).policy_candidate
    if policy is None:
        return None
    record = active.record
    return policy.model_copy(
        update={
            "landed_cost_policy_candidate_id": f"lcp-quote-calc:{record.import_id}",
            "notes": f"{policy.notes or ''} Source: {master_reference(record)}".strip(),
        }
    )


def attach_price_master_provenance(draft: QuoteDraft, records: Sequence[PriceMasterImport]) -> QuoteDraft:
    """Record which DT40/PT30 import each official price came from. Used only when a draft is created."""
    by_book = {record.master_type.value: record for record in records}
    snapshots = [line.manufacturer_price_snapshot for line in draft.configuration_lines]
    snapshots += list(draft.pricing_context.manufacturer_price_snapshots)
    for snapshot in snapshots:
        if snapshot is None or snapshot.price_source_type != PriceSourceType.OFFICIAL_PRICE_BOOK:
            continue
        matched = [by_book[name.strip()] for name in (snapshot.price_book or "").split("/") if name.strip() in by_book]
        if not matched:
            continue
        snapshot.price_master_import_id = ",".join(item.import_id for item in matched)
        snapshot.price_master_sha256 = ",".join(item.sha256 for item in matched)
        snapshot.price_master_filename = ",".join(item.original_filename or "" for item in matched)
        snapshot.price_book_version = snapshot.price_book_version or snapshot.price_master_import_id
    references = [master_reference(record) for record in records]
    draft.source_references = _unique(list(draft.source_references) + references)
    draft.pricing_context.source_references = _unique(list(draft.pricing_context.source_references) + references)
    return draft


SALES_MASTER_MISSING_WARNING = (
    "SpaceOne price master (SO_MASTER) is not set. Standard sales price candidate is unavailable."
)


def mark_sales_master_missing(draft: QuoteDraft) -> QuoteDraft:
    for line in draft.configuration_lines:
        already = any(SALES_MASTER_MISSING_WARNING in item for item in line.warnings)
        if line.standard_sales_price_candidate_jpy is None and not already:
            line.warnings.append(f"{line.manufacturer_sku}: {SALES_MASTER_MISSING_WARNING}")
    return draft


def master_reference(record: PriceMasterImport) -> str:
    return (
        f"Price master {record.master_type.value} import {record.import_id} "
        f"({record.original_filename or '-'}, sha256 {record.sha256[:12]})"
    )


def resolve_stored_path(repository: SqlitePriceMasterRepository, record: PriceMasterImport) -> Path:
    # stored_path is always relative with "/" separators, so the same row resolves on macOS and Windows.
    relative = PurePosixPath(record.stored_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Invalid stored price master path: {record.stored_path}")
    return repository.storage_root.joinpath(*relative.parts)


def materialize_stored_file(repository: SqlitePriceMasterRepository, record: PriceMasterImport) -> Path:
    """Local path for parsing. With central storage the PostgreSQL bytes are written to a local cache
    after SHA-256 verification; the database row stays the Source of Truth."""
    path = resolve_stored_path(repository, record)
    if path.is_file() or not getattr(repository, "is_central", False):
        return path
    data = repository.get_file_bytes(record.import_id)
    if data is None:
        return path
    if hashlib.sha256(data).hexdigest() != record.sha256:
        logger.error("price_master_sha_mismatch type=%s import_id=%s", record.master_type.value, record.import_id)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f"{path.name}.{uuid4().hex}.part")
    partial.write_bytes(data)
    os.replace(partial, path)
    return path


def safe_display_filename(original_filename: Optional[str]) -> str:
    # Only for display; managed file names never use the uploaded name.
    name = PureWindowsPath(str(original_filename or "")).name
    return PurePosixPath(name).name.strip() or "upload.xlsx"


def _new_import_id(master_type: PriceMasterType) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{master_type.value}-{stamp}-{uuid4().hex[:8]}"


def _rejected(master_type: PriceMasterType, reason_code: str) -> PriceMasterImportOutcome:
    return PriceMasterImportOutcome(
        status=PriceMasterImportStatus.REJECTED, master_type=master_type, reason_code=reason_code
    )


def _unique(values: Sequence[str]) -> list[str]:
    seen = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen
