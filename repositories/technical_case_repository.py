from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from models import CaseCloseReason, CaseLifecycleStatus, ManufacturerResponseRevision, TechnicalCaseRecord
from repositories.quote_repository import CONFLICT_MESSAGE, SaveResult

SCHEMA_VERSION = 1


class TechnicalCaseRepositoryError(RuntimeError):
    pass


class TechnicalCaseConflictError(TechnicalCaseRepositoryError):
    """Optimistic lock failure: the case changed after it was loaded. Nothing was written."""

    def __init__(self, case_id: str, expected_row_version: Optional[int]):
        super().__init__(CONFLICT_MESSAGE)
        self.key = case_id
        self.expected_row_version = expected_row_version


@dataclass(frozen=True)
class TechnicalCaseListItem:
    case_id: str
    customer_name: Optional[str]
    case_title: Optional[str]
    status: Optional[str]
    provider: Optional[str]
    updated_at: str
    archived_at: Optional[str] = None
    deleted_at: Optional[str] = None
    parent_case_id: Optional[str] = None
    relation_type: Optional[str] = None
    case_lifecycle_status: CaseLifecycleStatus = CaseLifecycleStatus.ACTIVE
    close_reason: Optional[CaseCloseReason] = None
    closed_at: Optional[str] = None


class TechnicalCaseRepository(Protocol):
    def save_case(self, record: TechnicalCaseRecord) -> SaveResult:
        ...

    def get_case(self, case_id: str) -> Optional[TechnicalCaseRecord]:
        ...

    def list_recent_cases(self, limit: int = 8, *, view: str = "active") -> list[TechnicalCaseListItem]:
        ...

    def update_case(self, record: TechnicalCaseRecord) -> SaveResult:
        ...

    def save_analysis_snapshot(self, record: TechnicalCaseRecord) -> SaveResult:
        ...

    def save_manufacturer_response_result(
        self,
        case_id: str,
        revision: ManufacturerResponseRevision,
        record: Optional[TechnicalCaseRecord] = None,
    ) -> TechnicalCaseRecord:
        ...
