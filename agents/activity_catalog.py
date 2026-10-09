from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from models import ActivityCategory, QuoteDraft, QuoteDraftStatus, QuoteLineageType, TechnicalCaseRecord, TechnicalCaseStatus


CATEGORY_LABELS = {
    ActivityCategory.INQUIRY.value: "問い合わせ",
    ActivityCategory.TECHNICAL_CASE.value: "営業・技術案件",
    ActivityCategory.QUOTE.value: "見積",
    ActivityCategory.DERIVED_CASE.value: "派生案件",
    ActivityCategory.DERIVED_QUOTE.value: "派生見積",
    ActivityCategory.REVISION.value: "修正版",
    ActivityCategory.OTHER.value: "その他",
}

EVENT_LABELS = {
    "CASE_CREATED": "問い合わせ受付",
    "CASE_UPDATED": "案件更新",
    "MANUFACTURER_QUESTION_CREATED": "メーカー確認事項作成",
    "MANUFACTURER_RESPONSE_RECEIVED": "メーカー回答受領",
    "QUOTE_CREATED": "見積作成",
    "QUOTE_DERIVED": "派生見積作成",
    "QUOTE_APPROVED": "見積承認",
    "QUOTE_SUBMITTED": "見積提出",
    "QUOTE_DOCUMENT_GENERATED": "正式見積書作成",
    "CASE_DERIVED": "派生案件作成",
    "CASE_CLOSED": "案件終了",
    "CASE_REOPENED": "案件再開",
    "ARCHIVED": "アーカイブ",
    "RESTORED": "復元",
    "MOVED_TO_TRASH": "ゴミ箱へ移動",
    "RESTORED_FROM_TRASH": "ゴミ箱から復元",
}


def timeline_event_label(event_type: str) -> str:
    return EVENT_LABELS.get(event_type, event_type)

SORT_FIELDS = (
    "last_activity_at",
    "date",
    "customer",
    "end_user",
    "category",
    "product",
    "title",
    "status",
    "updated_at",
)


@dataclass
class ActivityRow:
    row_id: str
    entity_kind: str
    entity_id: str
    category: str
    date: str
    last_activity_at: str
    customer: str
    end_user: str
    product: str
    title: str
    status: str
    updated_at: str
    parent_id: Optional[str] = None
    parent_kind: Optional[str] = None
    archived: bool = False
    deleted: bool = False
    quote_version: Optional[int] = None
    case_id: Optional[str] = None

    def category_label(self) -> str:
        return CATEGORY_LABELS.get(self.category, self.category)


@dataclass
class ActivityFilter:
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    customers: tuple[str, ...] = ()
    end_users: tuple[str, ...] = ()
    products: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    statuses: tuple[str, ...] = ()
    keyword: str = ""
    include_archived: bool = False
    include_deleted: bool = False


@dataclass
class ActivitySort:
    field: str = "last_activity_at"
    descending: bool = True


@dataclass
class ActivitySelection:
    selected: set[str] = field(default_factory=set)

    def select_one(self, row_id: str) -> None:
        self.selected.add(row_id)

    def select_many(self, row_ids) -> None:
        self.selected.update(row_ids)

    def select_all(self, rows: list[ActivityRow]) -> None:
        self.selected = {row.row_id for row in rows}

    def deselect_all(self) -> None:
        self.selected.clear()

    def selected_rows(self, rows: list[ActivityRow]) -> list[ActivityRow]:
        return [row for row in rows if row.row_id in self.selected]


def reset_activity_filter() -> ActivityFilter:
    return ActivityFilter()


def reset_activity_sort() -> ActivitySort:
    return ActivitySort(field="last_activity_at", descending=True)


def classify_case(record: TechnicalCaseRecord) -> str:
    if record.parent_case_id:
        return ActivityCategory.DERIVED_CASE.value
    if record.status == TechnicalCaseStatus.DRAFT.value and not record.inquiry_success:
        return ActivityCategory.INQUIRY.value
    return ActivityCategory.TECHNICAL_CASE.value


def classify_quote(draft: QuoteDraft) -> str:
    relation = draft.relation_type or ""
    if relation == QuoteLineageType.REVISION.value:
        return ActivityCategory.REVISION.value
    if draft.parent_quote_id:
        return ActivityCategory.DERIVED_QUOTE.value
    return ActivityCategory.QUOTE.value


def _iso(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _max_iso(*values: Optional[str]) -> str:
    cleaned = [item for item in values if item]
    return max(cleaned) if cleaned else ""


def case_row(record: TechnicalCaseRecord, *, latest_event: Optional[str] = None) -> ActivityRow:
    created = record.created_at or record.updated_at or ""
    updated = record.updated_at or created
    product = (record.requested_products or [""])[0] if record.requested_products else ""
    return ActivityRow(
        row_id=f"case:{record.case_id}",
        entity_kind="case",
        entity_id=record.case_id,
        category=classify_case(record),
        date=created,
        last_activity_at=_max_iso(latest_event, updated, created),
        customer=record.customer_name or "",
        end_user=record.end_user_name or "",
        product=product,
        title=record.case_title or "",
        status=record.status or "",
        updated_at=updated,
        parent_id=record.parent_case_id,
        parent_kind="case" if record.parent_case_id else None,
        archived=bool(record.archived_at),
        deleted=bool(record.deleted_at),
        case_id=record.case_id,
    )


def quote_row(draft: QuoteDraft, *, latest_event: Optional[str] = None) -> ActivityRow:
    created = _iso(draft.created_at) or _iso(draft.updated_at)
    updated = _iso(draft.updated_at) or created
    status = draft.status.value if draft.status else ""
    return ActivityRow(
        row_id=f"quote:{draft.quote_draft_id}:{draft.quote_version}",
        entity_kind="quote",
        entity_id=draft.quote_draft_id,
        category=classify_quote(draft),
        date=created,
        last_activity_at=_max_iso(latest_event, updated, created),
        customer=draft.customer or "",
        end_user="",
        product=draft.configuration_name or "",
        title=draft.title or draft.configuration_name or "",
        status=status,
        updated_at=updated,
        parent_id=draft.parent_quote_id,
        parent_kind="quote" if draft.parent_quote_id else None,
        archived=bool(draft.archived_at),
        deleted=bool(draft.deleted_at),
        quote_version=draft.quote_version,
        case_id=draft.case_id,
    )


def _parse_day(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10]


def apply_activity_filter(rows: list[ActivityRow], filt: Optional[ActivityFilter] = None) -> list[ActivityRow]:
    current = filt or ActivityFilter()
    result = []
    keyword = (current.keyword or "").strip().casefold()
    date_from = _parse_day(current.date_from)
    date_to = _parse_day(current.date_to)
    for row in rows:
        if row.deleted and not current.include_deleted:
            continue
        if row.archived and not current.include_archived:
            continue
        day = _parse_day(row.date)
        if date_from and day and day < date_from:
            continue
        if date_to and day and day > date_to:
            continue
        if current.customers and row.customer not in current.customers:
            continue
        if current.end_users and row.end_user not in current.end_users:
            continue
        if current.products and row.product not in current.products:
            continue
        if current.categories and row.category not in current.categories:
            continue
        if current.statuses and row.status not in current.statuses:
            continue
        if keyword:
            haystack = " ".join(
                [row.customer, row.end_user, row.product, row.title, row.status, row.category, row.entity_id]
            ).casefold()
            if keyword not in haystack:
                continue
        result.append(row)
    return result


def sort_activity_rows(rows: list[ActivityRow], sort: Optional[ActivitySort] = None) -> list[ActivityRow]:
    current = sort or reset_activity_sort()
    field = current.field if current.field in SORT_FIELDS else "last_activity_at"
    return sorted(rows, key=lambda row: (getattr(row, field) or "").casefold(), reverse=current.descending)


def summarize_activity(rows: list[ActivityRow]) -> dict:
    completed = {"COMPLETED", QuoteDraftStatus.APPROVED.value}
    return {
        "total": len(rows),
        "inquiry": sum(1 for row in rows if row.category == ActivityCategory.INQUIRY.value),
        "quote": sum(1 for row in rows if row.category in {ActivityCategory.QUOTE.value, ActivityCategory.DERIVED_QUOTE.value, ActivityCategory.REVISION.value}),
        "completed": sum(1 for row in rows if row.status in completed),
        "in_progress": sum(1 for row in rows if row.status not in completed),
    }


def quotes_for_case(drafts: list[QuoteDraft], case_id: str) -> list[QuoteDraft]:
    return [draft for draft in drafts if draft.case_id == case_id]


def link_quote_to_case(draft: QuoteDraft, case_id: str) -> QuoteDraft:
    return draft.model_copy(update={"case_id": case_id})


def related_source_label(row: ActivityRow, rows: list[ActivityRow]) -> str:
    if not row.parent_id:
        return ""
    for other in rows:
        if other.entity_id == row.parent_id:
            return other.title or other.entity_id
    return row.parent_id


def load_activity_rows(case_repo, quote_repo, activity_repo, *, limit: int = 500) -> list[ActivityRow]:
    cases = case_repo.list_recent_cases(limit=limit, view="history")
    drafts = quote_repo.list_recent_drafts(limit=limit, view="history")
    latest_cases = activity_repo.latest_for_entities("case", [item.case_id for item in cases])
    latest_quotes = activity_repo.latest_for_entities("quote", [item.quote_draft_id for item in drafts])
    rows: list[ActivityRow] = []
    for item in cases:
        record = case_repo.get_case(item.case_id)
        if record is not None:
            rows.append(case_row(record, latest_event=latest_cases.get(record.case_id)))
    for item in drafts:
        loaded = quote_repo.get_draft(item.quote_draft_id, item.version)
        if loaded is not None:
            rows.append(quote_row(loaded.draft, latest_event=latest_quotes.get(item.quote_draft_id)))
    return rows


def load_related_quotes(quote_repo, case_id: str, *, limit: int = 200) -> list:
    drafts = []
    for item in quote_repo.list_recent_drafts(limit=limit, view="history"):
        loaded = quote_repo.get_draft(item.quote_draft_id, item.version)
        if loaded is not None and loaded.draft.case_id == case_id:
            drafts.append(loaded.draft)
    return drafts


def display_day(value: Optional[str]) -> str:
    day = _parse_day(value)
    if not day:
        return ""
    return day.replace("-", "/")


def build_quote_preview(snapshot) -> dict:
    lines = []
    for line in getattr(snapshot, "customer_lines_snapshot", None) or []:
        lines.append(
            {
                "name": getattr(line, "display_name", None) or getattr(line, "item_name", None) or "",
                "detail": getattr(line, "description", None) or getattr(line, "item_detail", None) or "",
                "quantity": getattr(line, "quantity", None),
                "unit_price": getattr(line, "unit_price_jpy", None),
                "amount": getattr(line, "amount_jpy", None),
            }
        )
    shipping = []
    for line in getattr(snapshot, "shipping_snapshot", None) or []:
        shipping_type = getattr(line, "shipping_type", None)
        name = shipping_type.value if getattr(shipping_type, "value", None) else (shipping_type or "送料")
        shipping.append(
            {
                "name": str(name),
                "amount": getattr(line, "sales_price_candidate_jpy", None) or getattr(line, "cost_jpy", None),
            }
        )
    return {
        "quote_number": snapshot.official_quote_number or snapshot.quote_number_candidate,
        "customer": snapshot.customer,
        "title": snapshot.title,
        "issue_date": snapshot.issue_date,
        "valid_until": snapshot.valid_until,
        "lines": lines,
        "shipping": shipping,
        "subtotal": snapshot.subtotal_ex_tax_jpy,
        "tax": snapshot.tax_jpy,
        "total": snapshot.total_jpy,
        "remarks": [item.text if hasattr(item, "text") else str(item) for item in (snapshot.remarks or [])],
        "status": snapshot.status.value if getattr(snapshot.status, "value", None) else snapshot.status,
        "snapshot_id": snapshot.approved_quote_snapshot_id,
        "quote_draft_id": snapshot.quote_draft_id,
        "quote_version": snapshot.quote_version,
    }
