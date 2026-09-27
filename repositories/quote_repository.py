from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol

from models import ApprovedQuoteSnapshot, QuoteDraft

SCHEMA_VERSION = 1


class QuoteRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class SaveResult:
    saved: bool
    skipped: bool
    updated_at: Optional[str] = None
    content_hash: Optional[str] = None


@dataclass(frozen=True)
class DraftListItem:
    quote_draft_id: str
    version: int
    status: Optional[str]
    customer_name: Optional[str]
    subject: Optional[str]
    configuration_name: Optional[str]
    updated_at: str


@dataclass
class LoadedDraft:
    draft: QuoteDraft
    ui_state: dict = field(default_factory=dict)
    updated_at: Optional[str] = None
    content_hash: Optional[str] = None


class QuoteRepository(Protocol):
    def save_draft(self, draft: QuoteDraft, ui_state: Optional[dict] = None, *, force: bool = False) -> SaveResult:
        ...

    def get_draft(self, quote_draft_id: str, version: Optional[int] = None) -> Optional[LoadedDraft]:
        ...

    def list_recent_drafts(self, limit: int = 8) -> list[DraftListItem]:
        ...

    def save_snapshot(self, snapshot: ApprovedQuoteSnapshot) -> bool:
        ...

    def get_snapshot(self, approved_quote_snapshot_id: str) -> Optional[ApprovedQuoteSnapshot]:
        ...

    def get_snapshot_for_draft(self, quote_draft_id: str, version: int) -> Optional[ApprovedQuoteSnapshot]:
        ...
