from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from models import ManufacturerResponseRevision, TechnicalCaseRecord
from repositories.quote_repository import SaveResult

SCHEMA_VERSION = 1


class TechnicalCaseRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class TechnicalCaseListItem:
    case_id: str
    customer_name: Optional[str]
    case_title: Optional[str]
    status: Optional[str]
    provider: Optional[str]
    updated_at: str


class TechnicalCaseRepository(Protocol):
    def save_case(self, record: TechnicalCaseRecord) -> SaveResult:
        ...

    def get_case(self, case_id: str) -> Optional[TechnicalCaseRecord]:
        ...

    def list_recent_cases(self, limit: int = 8) -> list[TechnicalCaseListItem]:
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
