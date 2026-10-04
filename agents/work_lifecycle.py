from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from models import CaseLineageType, QuoteDraft, QuoteDraftStatus, QuoteLineageType, TechnicalCaseRecord, TechnicalCaseStatus
from repositories.sqlite import now_iso


def generate_quote_draft_id() -> str:
    return f"QUOTE-{uuid4().hex[:12].upper()}"


def generate_derived_case_id() -> str:
    return f"CASE-{uuid4().hex[:12].upper()}"


def archive_record(record: TechnicalCaseRecord) -> TechnicalCaseRecord:
    return record.model_copy(update={"archived_at": now_iso(), "deleted_at": None})


def restore_record(record: TechnicalCaseRecord) -> TechnicalCaseRecord:
    return record.model_copy(update={"archived_at": None, "deleted_at": None})


def soft_delete_record(record: TechnicalCaseRecord) -> TechnicalCaseRecord:
    return record.model_copy(update={"deleted_at": now_iso()})


def archive_quote(draft: QuoteDraft) -> QuoteDraft:
    return draft.model_copy(update={"archived_at": now_iso(), "deleted_at": None})


def restore_quote(draft: QuoteDraft) -> QuoteDraft:
    return draft.model_copy(update={"archived_at": None, "deleted_at": None})


def soft_delete_quote(draft: QuoteDraft) -> QuoteDraft:
    return draft.model_copy(update={"deleted_at": now_iso()})


def _copy_knowledge_selection(snapshot: Optional[dict]) -> Optional[dict]:
    if not snapshot:
        return None
    copied = deepcopy(snapshot)
    return copied


def duplicate_technical_case(
    record: TechnicalCaseRecord,
    *,
    relation_type: str = CaseLineageType.DUPLICATE.value,
    copy_knowledge: bool = True,
) -> TechnicalCaseRecord:
    now = now_iso()
    return TechnicalCaseRecord(
        case_id=generate_derived_case_id(),
        customer_name=record.customer_name,
        case_title=record.case_title,
        created_at=now,
        updated_at=now,
        status=TechnicalCaseStatus.DRAFT.value,
        original_inquiry=record.original_inquiry,
        requested_products=list(record.requested_products),
        requirements=deepcopy(record.requirements),
        customer_goal=deepcopy(record.customer_goal),
        existing_equipment=deepcopy(record.existing_equipment),
        end_user_name=record.end_user_name,
        knowledge_snapshot=_copy_knowledge_selection(record.knowledge_snapshot) if copy_knowledge else None,
        parent_case_id=record.case_id,
        relation_type=relation_type,
        inquiry_success=False,
        schema_version=record.schema_version,
    )


def derive_technical_case(
    record: TechnicalCaseRecord,
    *,
    relation_type: str,
    copy_knowledge: bool = True,
) -> TechnicalCaseRecord:
    return duplicate_technical_case(
        record,
        relation_type=relation_type or CaseLineageType.OTHER.value,
        copy_knowledge=copy_knowledge,
    )


def duplicate_quote(
    draft: QuoteDraft,
    *,
    relation_type: str = QuoteLineageType.DUPLICATE.value,
) -> QuoteDraft:
    copied = draft.model_copy(deep=True)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return copied.model_copy(
        update={
            "quote_draft_id": generate_quote_draft_id(),
            "quote_version": 1,
            "status": QuoteDraftStatus.DRAFT,
            "created_at": now,
            "updated_at": now,
            "archived_at": None,
            "deleted_at": None,
            "parent_quote_id": draft.quote_draft_id,
            "source_quote_id": draft.source_quote_id or draft.quote_draft_id,
            "relation_type": relation_type,
            "source_references": list(draft.source_references) + [f"Duplicated from {draft.quote_draft_id}"],
        }
    )


def derive_quote(draft: QuoteDraft, *, relation_type: str) -> QuoteDraft:
    return duplicate_quote(draft, relation_type=relation_type or QuoteLineageType.OTHER.value)
