"""Check a manufacturer online workbook against the active price master.

Fetching never activates a master. A new snapshot is registered only after a person
approves a review that found SKU or price differences. Comparison is by normalized SKU
and the official price columns, not by row position.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import logging
from typing import Optional

from agents.online_price_source import (
    FetchedWorkbook,
    OnlinePriceFetchError,
    OnlinePriceSource,
    fetch_workbook,
    resolve_online_price_source,
    resolve_registered_price_source,
)
from agents.price_master import (
    ONLINE_SYNC_MASTERS,
    XLSX_SIGNATURE,
    PriceMasterValidationError,
    get_active_master,
    import_price_master,
    parse_manufacturer_price_master,
    safe_display_filename,
    validate_price_master,
)
from models import PriceMasterImportOutcome, PriceMasterSourceType, PriceMasterType, SkuDuplicateClass
from parsers.price_book_parser import CODE_MISSING_COLUMNS, normalize_sku
from repositories.sqlite import now_iso
from repositories.manufacturer_price_source_repository import ManufacturerPriceSourceRepository
from repositories.sqlite_price_master_repository import SqlitePriceMasterRepository

logger = logging.getLogger(__name__)


class OnlinePriceReviewStatus(str, Enum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    FETCH_FAILED = "FETCH_FAILED"
    EMPTY = "EMPTY"
    NOT_XLSX = "NOT_XLSX"
    PARSER_FAILED = "PARSER_FAILED"
    DUPLICATE_SKU = "DUPLICATE_SKU"
    MISSING_COLUMNS = "MISSING_COLUMNS"
    NO_DATA = "NO_DATA"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    NO_CHANGE = "NO_CHANGE"
    CHANGES_PENDING = "CHANGES_PENDING"


_FAILURES = {
    OnlinePriceReviewStatus.NOT_CONFIGURED,
    OnlinePriceReviewStatus.FETCH_FAILED,
    OnlinePriceReviewStatus.EMPTY,
    OnlinePriceReviewStatus.NOT_XLSX,
    OnlinePriceReviewStatus.PARSER_FAILED,
    OnlinePriceReviewStatus.DUPLICATE_SKU,
    OnlinePriceReviewStatus.MISSING_COLUMNS,
    OnlinePriceReviewStatus.NO_DATA,
    OnlinePriceReviewStatus.VALIDATION_FAILED,
}


@dataclass
class OnlineSkuChange:
    sku: str
    kind: str
    old_dealer: Optional[float] = None
    new_dealer: Optional[float] = None
    old_msrp: Optional[float] = None
    new_msrp: Optional[float] = None


@dataclass
class OnlinePriceReview:
    master_type: PriceMasterType
    status: OnlinePriceReviewStatus
    active_import_id: Optional[str] = None
    source_id: Optional[str] = None
    source_key: Optional[str] = None
    source_url: Optional[str] = None
    source_enabled: Optional[bool] = None
    source_row_version: Optional[int] = None
    auth_mode: Optional[str] = None
    fetched_at: Optional[str] = None
    sha256: Optional[str] = None
    filename: Optional[str] = None
    reason_code: Optional[str] = None
    validation_summary: dict = field(default_factory=dict)
    changes: list[OnlineSkuChange] = field(default_factory=list)
    data: Optional[bytes] = field(default=None, repr=False)

    @property
    def error_count(self) -> int:
        return 1 if self.status in _FAILURES else 0

    @property
    def added_count(self) -> int:
        return sum(1 for item in self.changes if item.kind == "ADDED")

    @property
    def removed_count(self) -> int:
        return sum(1 for item in self.changes if item.kind == "REMOVED")

    @property
    def dealer_change_count(self) -> int:
        return sum(1 for item in self.changes if item.kind in {"DEALER", "DEALER_AND_MSRP"})

    @property
    def msrp_change_count(self) -> int:
        return sum(1 for item in self.changes if item.kind in {"MSRP", "DEALER_AND_MSRP"})

    @property
    def price_change_count(self) -> int:
        return sum(1 for item in self.changes if item.kind in {"DEALER", "MSRP", "DEALER_AND_MSRP"})


def review_manufacturer_online_price(
    master_type: PriceMasterType,
    *,
    repository: Optional[SqlitePriceMasterRepository] = None,
    source: Optional[OnlinePriceSource] = None,
    fetcher=None,
) -> OnlinePriceReview:
    """Fetch and diff. The active master is left as it is."""
    master_type = PriceMasterType(master_type)
    repo = repository or SqlitePriceMasterRepository()
    active_id = _active_import_id(master_type, repo)
    if master_type not in ONLINE_SYNC_MASTERS:
        return _failed(master_type, OnlinePriceReviewStatus.NOT_CONFIGURED, active_id)
    source = source or resolve_online_price_source(master_type)
    if not source.configured:
        return _failed(
            master_type,
            OnlinePriceReviewStatus.NOT_CONFIGURED,
            active_id,
            source_id=source.source_id,
            source_key=source.source_key or master_type.value,
            source_url=source.fetch_url if source.url else None,
            source_enabled=source.enabled,
            source_row_version=source.registry_row_version,
            reason_code=source.config_error,
            fetched_at=now_iso(),
        )
    fetch = fetcher or _default_fetcher
    try:
        fetched = fetch(source)
    except Exception as error:
        reason_code = error.reason_code if isinstance(error, OnlinePriceFetchError) else "FETCH_FAILED"
        logger.warning(
            "online_price_fetch_failed type=%s reason=%s",
            master_type.value,
            reason_code,
        )
        return _failed(
            master_type,
            OnlinePriceReviewStatus.FETCH_FAILED,
            active_id,
            source_id=source.source_id,
            source_key=source.source_key or master_type.value,
            source_url=source.fetch_url,
            source_enabled=source.enabled,
            source_row_version=source.registry_row_version,
            reason_code=reason_code,
            fetched_at=now_iso(),
        )
    return inspect_online_workbook(
        master_type,
        fetched.data,
        filename=fetched.filename,
        source=source,
        auth_mode=fetched.auth_mode,
        fetched_at=now_iso(),
        repository=repo,
    )


def inspect_online_workbook(
    master_type: PriceMasterType,
    data: bytes,
    *,
    filename: Optional[str] = None,
    source: Optional[OnlinePriceSource] = None,
    auth_mode: Optional[str] = None,
    fetched_at: Optional[str] = None,
    repository: Optional[SqlitePriceMasterRepository] = None,
) -> OnlinePriceReview:
    """Validate and diff bytes already in memory. Does not register or activate."""
    master_type = PriceMasterType(master_type)
    repo = repository or SqlitePriceMasterRepository()
    active_id = _active_import_id(master_type, repo)
    source_id = source.source_id if source else master_type.value
    source_key = (source.source_key or master_type.value) if source else master_type.value
    source_url = source.fetch_url if source and source.configured else None
    source_enabled = source.enabled if source else None
    source_row_version = source.registry_row_version if source else None
    display_name = _online_filename(filename, master_type)
    fetched_at = fetched_at or now_iso()
    base = dict(
        master_type=master_type,
        active_import_id=active_id,
        source_id=source_id,
        source_key=source_key,
        source_url=source_url,
        source_enabled=source_enabled,
        source_row_version=source_row_version,
        auth_mode=auth_mode,
        fetched_at=fetched_at,
        filename=display_name,
    )
    if not data:
        return OnlinePriceReview(status=OnlinePriceReviewStatus.EMPTY, reason_code="EMPTY", **base)
    if not data.startswith(XLSX_SIGNATURE):
        return OnlinePriceReview(status=OnlinePriceReviewStatus.NOT_XLSX, reason_code="NOT_XLSX", **base)

    sha256 = hashlib.sha256(data).hexdigest()
    base["sha256"] = sha256
    staging = _write_staging(repo, data)
    try:
        try:
            book = parse_manufacturer_price_master(master_type, staging, version="online-review")
        except Exception as error:
            logger.warning("online_price_parse_failed type=%s error=%s", master_type.value, type(error).__name__)
            return OnlinePriceReview(status=OnlinePriceReviewStatus.PARSER_FAILED, reason_code="PARSER_FAILED", **base)
        conflicts = sorted(
            normalize_sku(item.sku) or item.sku
            for item in book.candidates
            if item.duplicate_class == SkuDuplicateClass.PRICE_CONFLICT
        )
        if conflicts:
            return OnlinePriceReview(status=OnlinePriceReviewStatus.DUPLICATE_SKU, reason_code="DUPLICATE_SKU", **base)
        if not any(sheet.header_found for sheet in book.sheets):
            missing = any(issue.code == CODE_MISSING_COLUMNS for issue in book.errors)
            status = OnlinePriceReviewStatus.MISSING_COLUMNS if missing else OnlinePriceReviewStatus.NO_DATA
            return OnlinePriceReview(status=status, reason_code=status.value, **base)
        try:
            summary = validate_price_master(master_type, staging)
        except PriceMasterValidationError as error:
            status = _validation_status(error)
            return OnlinePriceReview(
                status=status,
                reason_code=error.code if status == OnlinePriceReviewStatus.VALIDATION_FAILED else status.value,
                **base,
            )
        current = _active_prices(master_type, repo)
        if current is None:
            return OnlinePriceReview(status=OnlinePriceReviewStatus.VALIDATION_FAILED, reason_code="ACTIVE_UNREADABLE", **base)
        changes = _diff_prices(current, _priced_by_sku(book))
        status = OnlinePriceReviewStatus.NO_CHANGE if not changes else OnlinePriceReviewStatus.CHANGES_PENDING
        return OnlinePriceReview(
            status=status,
            validation_summary=summary,
            changes=changes,
            data=data if changes else None,
            **base,
        )
    finally:
        if staging.exists():
            staging.unlink()


def activate_reviewed_online_price(
    review: OnlinePriceReview,
    *,
    repository: Optional[SqlitePriceMasterRepository] = None,
    source_repository: Optional[ManufacturerPriceSourceRepository] = None,
) -> PriceMasterImportOutcome:
    """Register the reviewed bytes only when the review found valid differences."""
    from agents.price_master import _rejected

    if review.status != OnlinePriceReviewStatus.CHANGES_PENDING or not review.data:
        return _rejected(review.master_type, "ONLINE_REVIEW_REQUIRED")
    repo = repository or SqlitePriceMasterRepository()
    try:
        active_import_id = _active_import_id(review.master_type, repo)
    except Exception:
        logger.exception("online_price_active_stale_check_failed type=%s", review.master_type.value)
        return _rejected(review.master_type, "ONLINE_REVIEW_STALE")
    if active_import_id != review.active_import_id:
        return _rejected(review.master_type, "ONLINE_REVIEW_STALE")
    if not _source_is_current(review, source_repository):
        return _rejected(review.master_type, "ONLINE_REVIEW_STALE")
    provenance = {
        "source_id": review.source_id,
        "source_key": review.source_key,
        "source_url": review.source_url,
        "source_row_version": review.source_row_version,
        "auth_mode": review.auth_mode,
        "fetched_at": review.fetched_at,
        "filename": review.filename,
        "sha256": review.sha256,
    }
    return import_price_master(
        review.master_type,
        review.filename,
        review.data,
        repository=repo,
        source_type=PriceMasterSourceType.MANUFACTURER_ONLINE,
        provenance=provenance,
    )


def _source_is_current(
    review: OnlinePriceReview,
    source_repository: Optional[ManufacturerPriceSourceRepository],
) -> bool:
    # A review without Registry identity cannot prove that its source is still current.
    if review.source_row_version is None:
        return False
    source_key = review.source_key or review.master_type.value
    repository = source_repository or ManufacturerPriceSourceRepository()
    try:
        # Probe the Registry directly so an unavailable DB cannot silently fall back to bootstrap config.
        repository.get(source_key)
        current = resolve_registered_price_source(
            source_key,
            master_type=review.master_type,
            source_repository=repository,
        )
    except Exception:
        logger.exception("online_price_source_stale_check_failed type=%s", review.master_type.value)
        return False
    return (
        current.source_key == source_key
        and current.fetch_url == review.source_url
        and current.enabled == review.source_enabled
        and current.registry_row_version == review.source_row_version
    )


def _default_fetcher(source: OnlinePriceSource) -> FetchedWorkbook:
    return fetch_workbook(source)


def _active_import_id(master_type: PriceMasterType, repository: SqlitePriceMasterRepository) -> Optional[str]:
    active = repository.get_active(master_type)
    return active.import_id if active else None


def _failed(master_type, status, active_id, **extra) -> OnlinePriceReview:
    return OnlinePriceReview(master_type=master_type, status=status, active_import_id=active_id, **extra)


def _validation_status(error: PriceMasterValidationError) -> OnlinePriceReviewStatus:
    text = str(error)
    if "No SKU with a dealer price" in text:
        return OnlinePriceReviewStatus.NO_DATA
    return OnlinePriceReviewStatus.VALIDATION_FAILED


def _active_prices(master_type: PriceMasterType, repository: SqlitePriceMasterRepository):
    active = get_active_master(master_type, repository)
    if active is None:
        # A registry row whose file cannot be read is not treated as an empty master.
        if repository.get_active(master_type) is not None:
            return None
        return {}
    try:
        book = parse_manufacturer_price_master(master_type, active.path, version=active.record.import_id)
    except Exception:
        logger.warning("online_price_active_unreadable type=%s import_id=%s", master_type.value, active.record.import_id)
        return None
    return _priced_by_sku(book)


def _priced_by_sku(book) -> dict[str, tuple[Optional[float], Optional[float]]]:
    prices = {}
    for candidate in book.candidates:
        if candidate.dealer_price_usd is None:
            continue
        sku = normalize_sku(candidate.sku)
        if not sku:
            continue
        prices[sku] = (_money(candidate.msrp_usd), _money(candidate.dealer_price_usd))
    return prices


def _diff_prices(current: dict, incoming: dict) -> list[OnlineSkuChange]:
    changes = []
    for sku in sorted(set(current) | set(incoming)):
        old = current.get(sku)
        new = incoming.get(sku)
        if old is None:
            changes.append(OnlineSkuChange(sku=sku, kind="ADDED", new_msrp=new[0], new_dealer=new[1]))
            continue
        if new is None:
            changes.append(OnlineSkuChange(sku=sku, kind="REMOVED", old_msrp=old[0], old_dealer=old[1]))
            continue
        dealer_changed = old[1] != new[1]
        msrp_changed = old[0] != new[0]
        if dealer_changed and msrp_changed:
            kind = "DEALER_AND_MSRP"
        elif dealer_changed:
            kind = "DEALER"
        elif msrp_changed:
            kind = "MSRP"
        else:
            continue
        changes.append(
            OnlineSkuChange(
                sku=sku,
                kind=kind,
                old_dealer=old[1],
                new_dealer=new[1],
                old_msrp=old[0],
                new_msrp=new[0],
            )
        )
    return changes


def _money(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), 2)


def _online_filename(filename: Optional[str], master_type: PriceMasterType) -> str:
    name = safe_display_filename(filename) if filename else f"{master_type.value}-online.xlsx"
    if not name.lower().endswith(".xlsx"):
        return f"{master_type.value}-online.xlsx"
    return name


def _write_staging(repository: SqlitePriceMasterRepository, data: bytes):
    from uuid import uuid4

    from agents.price_master import ALLOWED_EXTENSION, STAGING_DIRECTORY

    staging = repository.storage_root / STAGING_DIRECTORY / f"{uuid4().hex}{ALLOWED_EXTENSION}"
    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.write_bytes(data)
    return staging
