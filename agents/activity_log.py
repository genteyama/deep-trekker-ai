from __future__ import annotations

from typing import Optional
from uuid import uuid4

from models import ActivityEvent, ActivityEventType, TechnicalCaseRecord
from repositories.sqlite import now_iso, strip_secrets
from repositories.sqlite_activity_repository import SqliteActivityRepository


def get_activity_repository(path=None) -> SqliteActivityRepository:
    return SqliteActivityRepository(path)


def append_activity_event(
    repository: SqliteActivityRepository,
    *,
    event_type: str,
    entity_kind: str,
    entity_id: str,
    entity_version: Optional[int] = None,
    customer_name: Optional[str] = None,
    title: Optional[str] = None,
    payload: Optional[dict] = None,
    occurred_at: Optional[str] = None,
) -> ActivityEvent:
    event = ActivityEvent(
        event_id=f"EVT-{uuid4().hex[:12].upper()}",
        event_type=event_type,
        occurred_at=occurred_at or now_iso(),
        entity_kind=entity_kind,
        entity_id=entity_id,
        entity_version=entity_version,
        customer_name=customer_name,
        title=title,
        payload=strip_secrets(payload or {}),
    )
    return repository.append(event)


def _append_once(
    repository: SqliteActivityRepository,
    *,
    event_type: str,
    entity_kind: str,
    entity_id: str,
    entity_version: Optional[int] = None,
    customer_name: Optional[str] = None,
    title: Optional[str] = None,
    payload: Optional[dict] = None,
    occurred_at: Optional[str] = None,
) -> Optional[ActivityEvent]:
    if repository.has_event(
        event_type=event_type,
        entity_kind=entity_kind,
        entity_id=entity_id,
        entity_version=entity_version,
    ):
        return None
    return append_activity_event(
        repository,
        event_type=event_type,
        entity_kind=entity_kind,
        entity_id=entity_id,
        entity_version=entity_version,
        customer_name=customer_name,
        title=title,
        payload=payload,
        occurred_at=occurred_at,
    )


def _status_value(value) -> Optional[str]:
    if value is None:
        return None
    return value.value if getattr(value, "value", None) else str(value)


def record_case_saved(
    repository: SqliteActivityRepository,
    existing,
    saved: TechnicalCaseRecord,
    *,
    response_received: bool = False,
    completed: bool = False,
) -> Optional[ActivityEvent]:
    if saved is None:
        return None
    event_type = None
    if response_received:
        if existing is not None and existing.manufacturer_response_analysis:
            return None
        event_type = ActivityEventType.MANUFACTURER_RESPONSE_RECEIVED.value
    elif existing is None:
        event_type = ActivityEventType.CASE_CREATED.value
    elif not existing.manufacturer_questions and saved.manufacturer_questions:
        event_type = ActivityEventType.MANUFACTURER_QUESTION_CREATED.value
    elif completed and existing.status != saved.status:
        event_type = ActivityEventType.CASE_UPDATED.value
    if event_type is None:
        return None
    return _append_once(
        repository,
        event_type=event_type,
        entity_kind="case",
        entity_id=saved.case_id,
        customer_name=saved.customer_name,
        title=saved.case_title,
        payload={"status": saved.status},
    )


def record_case_lifecycle(
    repository: SqliteActivityRepository,
    record: TechnicalCaseRecord,
    action: str,
    *,
    previous=None,
) -> Optional[ActivityEvent]:
    if action == "derive":
        return _append_once(
            repository,
            event_type=ActivityEventType.CASE_DERIVED.value,
            entity_kind="case",
            entity_id=record.case_id,
            customer_name=record.customer_name,
            title=record.case_title,
            payload={
                "parent_case_id": record.parent_case_id,
                "new_case_id": record.case_id,
                "relation_type": record.relation_type,
            },
        )
    if action == "duplicate":
        return _append_once(
            repository,
            event_type=ActivityEventType.CASE_CREATED.value,
            entity_kind="case",
            entity_id=record.case_id,
            customer_name=record.customer_name,
            title=record.case_title,
            payload={"action": action, "parent_case_id": record.parent_case_id, "relation_type": record.relation_type},
        )
    if action == "trash":
        if previous is not None and previous.deleted_at:
            return None
        if not record.deleted_at:
            return None
        return append_activity_event(
            repository,
            event_type=ActivityEventType.MOVED_TO_TRASH.value,
            entity_kind="case",
            entity_id=record.case_id,
            customer_name=record.customer_name,
            title=record.case_title,
            payload={"action": action},
        )
    if action == "restore":
        if previous is not None and previous.deleted_at:
            return append_activity_event(
                repository,
                event_type=ActivityEventType.RESTORED_FROM_TRASH.value,
                entity_kind="case",
                entity_id=record.case_id,
                customer_name=record.customer_name,
                title=record.case_title,
                payload={"action": action},
            )
        if previous is not None and previous.archived_at:
            return append_activity_event(
                repository,
                event_type=ActivityEventType.RESTORED.value,
                entity_kind="case",
                entity_id=record.case_id,
                customer_name=record.customer_name,
                title=record.case_title,
                payload={"action": action},
            )
        return None
    if action == "archive":
        if previous is not None and previous.archived_at:
            return None
        return append_activity_event(
            repository,
            event_type=ActivityEventType.ARCHIVED.value,
            entity_kind="case",
            entity_id=record.case_id,
            customer_name=record.customer_name,
            title=record.case_title,
            payload={"action": action},
        )
    return None


def record_quote_saved(repository: SqliteActivityRepository, previous, draft, *, derived: bool = False) -> Optional[ActivityEvent]:
    if previous is not None and not derived:
        return None
    event_type = ActivityEventType.QUOTE_DERIVED.value if derived or getattr(draft, "parent_quote_id", None) else ActivityEventType.QUOTE_CREATED.value
    return _append_once(
        repository,
        event_type=event_type,
        entity_kind="quote",
        entity_id=draft.quote_draft_id,
        entity_version=draft.quote_version,
        customer_name=draft.customer,
        title=draft.title,
        payload={"status": _status_value(draft.status)},
    )


def record_quote_approved(repository: SqliteActivityRepository, draft, snapshot) -> Optional[ActivityEvent]:
    return _append_once(
        repository,
        event_type=ActivityEventType.QUOTE_APPROVED.value,
        entity_kind="quote",
        entity_id=draft.quote_draft_id,
        entity_version=draft.quote_version,
        customer_name=draft.customer,
        title=draft.title,
        payload={"snapshot_id": snapshot.approved_quote_snapshot_id},
    )


def _document_type_value(document_type) -> str:
    return document_type.value if getattr(document_type, "value", None) else str(document_type)


def _has_document_generated(repository: SqliteActivityRepository, draft, document_type: str) -> bool:
    for event in repository.list_events(entity_kind="quote", entity_id=draft.quote_draft_id):
        if (
            event.event_type == ActivityEventType.QUOTE_DOCUMENT_GENERATED.value
            and event.entity_version == draft.quote_version
            and event.payload.get("document_type") == document_type
        ):
            return True
    return False


def record_quote_document_generated(
    repository: SqliteActivityRepository,
    draft,
    *,
    document_type: str,
    generated_at: Optional[str] = None,
) -> Optional[ActivityEvent]:
    if draft is None:
        return None
    kind = _document_type_value(document_type)
    if _has_document_generated(repository, draft, kind):
        return None
    stamp = generated_at or now_iso()
    return append_activity_event(
        repository,
        event_type=ActivityEventType.QUOTE_DOCUMENT_GENERATED.value,
        entity_kind="quote",
        entity_id=draft.quote_draft_id,
        entity_version=draft.quote_version,
        customer_name=getattr(draft, "customer", None),
        title=getattr(draft, "title", None),
        occurred_at=stamp,
        payload={
            "quote_draft_id": draft.quote_draft_id,
            "quote_version": draft.quote_version,
            "customer_name": getattr(draft, "customer", None),
            "case_id": getattr(draft, "case_id", None),
            "document_type": kind,
            "generated_at": stamp,
        },
    )


def record_quote_submitted(repository: SqliteActivityRepository, draft, *, submitted_at: Optional[str] = None) -> Optional[ActivityEvent]:
    if draft is None:
        return None
    stamp = submitted_at or now_iso()
    return _append_once(
        repository,
        event_type=ActivityEventType.QUOTE_SUBMITTED.value,
        entity_kind="quote",
        entity_id=draft.quote_draft_id,
        entity_version=draft.quote_version,
        customer_name=draft.customer,
        title=draft.title,
        occurred_at=stamp,
        payload={
            "quote_draft_id": draft.quote_draft_id,
            "quote_version": draft.quote_version,
            "customer_name": draft.customer,
            "case_id": getattr(draft, "case_id", None),
            "submitted_at": stamp,
        },
    )


def record_quote_lifecycle(
    repository: SqliteActivityRepository,
    draft,
    action: str,
    *,
    previous=None,
) -> Optional[ActivityEvent]:
    if action in {"duplicate", "derive"}:
        return record_quote_saved(repository, None, draft, derived=True)
    if action == "trash":
        if previous is not None and previous.deleted_at:
            return None
        if not draft.deleted_at:
            return None
        return append_activity_event(
            repository,
            event_type=ActivityEventType.MOVED_TO_TRASH.value,
            entity_kind="quote",
            entity_id=draft.quote_draft_id,
            entity_version=draft.quote_version,
            customer_name=draft.customer,
            title=draft.title,
            payload={"action": action},
        )
    if action == "restore":
        if previous is not None and previous.deleted_at:
            return append_activity_event(
                repository,
                event_type=ActivityEventType.RESTORED_FROM_TRASH.value,
                entity_kind="quote",
                entity_id=draft.quote_draft_id,
                entity_version=draft.quote_version,
                customer_name=draft.customer,
                title=draft.title,
                payload={"action": action},
            )
        if previous is not None and previous.archived_at:
            return append_activity_event(
                repository,
                event_type=ActivityEventType.RESTORED.value,
                entity_kind="quote",
                entity_id=draft.quote_draft_id,
                entity_version=draft.quote_version,
                customer_name=draft.customer,
                title=draft.title,
                payload={"action": action},
            )
        return None
    if action == "archive":
        if previous is not None and previous.archived_at:
            return None
        return append_activity_event(
            repository,
            event_type=ActivityEventType.ARCHIVED.value,
            entity_kind="quote",
            entity_id=draft.quote_draft_id,
            entity_version=draft.quote_version,
            customer_name=draft.customer,
            title=draft.title,
            payload={"action": action},
        )
    return None
