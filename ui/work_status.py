from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

from models import FinalPriceStatus, QuestionReviewStatus, TechnicalCaseStatus
from ui.warning_summary import summarize_draft_warnings

KIND_TECHNICAL = "technical_case"
KIND_QUOTE = "quote"

INFO_COMPLETE = "COMPLETE"
INFO_IN_PROGRESS = "IN_PROGRESS"
INFO_MISSING = "MISSING"
INFO_REVIEW_REQUIRED = "REVIEW_REQUIRED"
INFO_WAITING = "WAITING"
INFO_NOT_STARTED = "NOT_STARTED"

TECHNICAL_ITEM_KEYS = (
    "inquiry",
    "case_info",
    "requirements",
    "knowledge",
    "manufacturer_questions",
    "human_review",
    "manufacturer_response",
    "evidence_validation",
    "customer_reply",
)
QUOTE_ITEM_KEYS = (
    "configuration",
    "sku",
    "dealer_price",
    "shipping",
    "import_tax",
    "insurance",
    "landed_cost",
    "sales_price",
    "margin",
    "human_review",
    "approval",
    "export",
)

PROCESS_LABELS = {
    TechnicalCaseStatus.DRAFT.value: "作成中",
    TechnicalCaseStatus.ANALYZED.value: "解析済み",
    TechnicalCaseStatus.QUESTIONS_REVIEW.value: "メーカー質問レビュー中",
    TechnicalCaseStatus.WAITING_MANUFACTURER.value: "メーカー回答待ち",
    TechnicalCaseStatus.MANUFACTURER_RESPONSE_RECEIVED.value: "メーカー回答受領",
    TechnicalCaseStatus.RESPONSE_REVIEW.value: "回答確認中",
    TechnicalCaseStatus.COMPLETED.value: "完了",
    "QUOTE_REVIEW": "見積レビュー中",
    "APPROVAL_PENDING": "承認待ち",
    "APPROVED": "承認済み",
    "DRAFT": "作成中",
    "REVIEW_REQUIRED": "見積レビュー中",
    "READY_FOR_APPROVAL": "承認待ち",
    "SUPERSEDED": "旧版",
}
INFO_LABELS = {
    INFO_COMPLETE: "完了",
    INFO_IN_PROGRESS: "進行中",
    INFO_MISSING: "未入力",
    INFO_REVIEW_REQUIRED: "要確認",
    INFO_WAITING: "回答待ち",
    INFO_NOT_STARTED: "未実施",
}


@dataclass
class ItemStatus:
    key: str
    status: str
    review_count: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class WorkSummary:
    kind: str
    process_status: str
    items: list[ItemStatus] = field(default_factory=list)
    customer: Optional[str] = None
    title: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    updated_at: Optional[str] = None
    extra: dict = field(default_factory=dict)

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def completed(self) -> int:
        return sum(1 for item in self.items if item.status == INFO_COMPLETE)

    @property
    def review_required(self) -> int:
        counted = sum(item.review_count for item in self.items)
        if counted:
            return counted
        return sum(1 for item in self.items if item.status == INFO_REVIEW_REQUIRED)

    def item(self, key: str) -> Optional[ItemStatus]:
        for current in self.items:
            if current.key == key:
                return current
        return None

    def process_label(self, labels: Optional[dict] = None) -> str:
        mapping = labels or PROCESS_LABELS
        return mapping.get(self.process_status, self.process_status)

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "process_status": self.process_status,
            "completed": self.completed,
            "total": self.total,
            "review_required": self.review_required,
            "customer": self.customer,
            "title": self.title,
            "provider": self.provider,
            "model": self.model,
            "updated_at": self.updated_at,
            "items": [item.as_dict() for item in self.items],
            "extra": self.extra,
        }


def _info(key: str, status: str, review_count: int = 0) -> ItemStatus:
    return ItemStatus(key=key, status=status, review_count=review_count)


def _has_text(value) -> bool:
    return bool((value or "").strip()) if isinstance(value, str) else bool(value)


def summarize_technical_case(
    *,
    inquiry_text=None,
    case_name=None,
    customer_name=None,
    run=None,
    response_run=None,
    record=None,
) -> WorkSummary:
    inquiry = inquiry_text
    name = case_name
    customer = customer_name
    process = TechnicalCaseStatus.DRAFT.value
    provider = None
    model = None
    updated = None
    if record is not None:
        inquiry = inquiry or record.original_inquiry
        name = name or record.case_title
        customer = customer or record.customer_name
        process = record.status or process
        provider = record.provider
        model = record.model
        updated = record.updated_at
    if run is not None:
        inquiry = inquiry or run.inquiry_text
        if run.case is not None:
            name = name or run.case.case_name
            customer = customer or run.case.customer_name
            process = run.case.status or process
        provider = provider or run.provider_name
        model = model or getattr(run, "model", None)
    analyzed = bool(run and run.success) or bool(record and record.inquiry_success)
    requirements = list(getattr(run, "requirements", None) or [])
    if record is not None and not requirements:
        requirements = list(record.requirements or [])
    questions = list(getattr(run, "manufacturer_questions", None) or [])
    if record is not None and not questions:
        questions = list(record.manufacturer_questions or [])
    snapshot = getattr(run, "knowledge_snapshot", None)
    snapshot_items = list(getattr(snapshot, "items", None) or [])
    if record is not None and not snapshot_items:
        snapshot_items = list((record.knowledge_snapshot or {}).get("items") or [])
    pending_reviews = 0
    reviewed = 0
    for question in questions:
        status = getattr(question, "review_status", None)
        if isinstance(question, dict):
            status = question.get("review_status")
        if status and status != QuestionReviewStatus.PENDING.value:
            reviewed += 1
        else:
            pending_reviews += 1
    has_response = bool(response_run and response_run.success) or bool(
        record and (record.manufacturer_response_analysis or record.validated_matches)
    )
    evidence_reviews = 0
    matches = list(getattr(response_run, "matches", None) or [])
    if record is not None and not matches:
        evidence_reviews = sum(
            1 for item in record.evidence_validation_result if item.get("requires_human_review")
        )
    else:
        for view in matches:
            validation = getattr(view, "validation", None)
            if validation is not None and validation.requires_human_review:
                evidence_reviews += 1
    applied = 0
    if response_run is not None:
        for view in matches:
            question = getattr(view, "question", None)
            status = getattr(question, "status", None)
            if status and str(getattr(status, "value", status)) in {"ANSWERED", "PARTIAL", "FOLLOW_UP_REQUIRED"}:
                applied += 1
    if record is not None and record.approval_board:
        applied = max(
            applied,
            sum(1 for item in (record.approval_board.get("items") or []) if item.get("approval")),
        )

    items = [
        _info("inquiry", INFO_COMPLETE if _has_text(inquiry) else INFO_MISSING),
        _info("case_info", INFO_COMPLETE if _has_text(name) and _has_text(customer) else (INFO_IN_PROGRESS if _has_text(name) or _has_text(customer) else INFO_MISSING)),
        _info("requirements", INFO_COMPLETE if requirements else (INFO_MISSING if analyzed else INFO_NOT_STARTED)),
        _info(
            "knowledge",
            INFO_COMPLETE if snapshot_items else (INFO_NOT_STARTED if not analyzed else INFO_COMPLETE),
        ),
        _info("manufacturer_questions", INFO_COMPLETE if questions else (INFO_MISSING if analyzed else INFO_NOT_STARTED)),
        _info(
            "human_review",
            INFO_COMPLETE if questions and pending_reviews == 0 else (
                INFO_IN_PROGRESS if reviewed else (INFO_REVIEW_REQUIRED if questions else INFO_NOT_STARTED)
            ),
            pending_reviews if questions else 0,
        ),
        _info(
            "manufacturer_response",
            INFO_COMPLETE if has_response else (INFO_WAITING if questions else INFO_NOT_STARTED),
        ),
        _info(
            "evidence_validation",
            INFO_REVIEW_REQUIRED if has_response and evidence_reviews else (
                INFO_COMPLETE if has_response else INFO_NOT_STARTED
            ),
            evidence_reviews,
        ),
        _info(
            "customer_reply",
            INFO_COMPLETE if questions and applied >= len(questions) else (
                INFO_IN_PROGRESS if applied else INFO_NOT_STARTED
            ),
        ),
    ]
    return WorkSummary(
        kind=KIND_TECHNICAL,
        process_status=process,
        items=items,
        customer=customer,
        title=name,
        provider=provider,
        model=model,
        updated_at=updated,
    )


def summarize_quote(draft=None, snapshot=None, updated_at=None) -> WorkSummary:
    process = "DRAFT"
    if snapshot is not None:
        process = "APPROVED"
    elif draft is not None and getattr(draft, "status", None) is not None:
        process = getattr(draft.status, "value", draft.status)
    warnings = summarize_draft_warnings(draft) if draft is not None else {"count": 0}
    lines = list(getattr(draft, "configuration_lines", None) or [])
    product_lines = [line for line in lines if getattr(line, "requirement_type", None) and line.requirement_type.value != "SHIPPING"]
    if not product_lines:
        product_lines = lines
    economics = getattr(draft, "economics_result", None)
    shipping_lines = list(getattr(draft, "shipping_lines", None) or [])

    def _all(pred) -> bool:
        return bool(product_lines) and all(pred(line) for line in product_lines)

    def _any(pred) -> bool:
        return any(pred(line) for line in product_lines)

    items = [
        _info("configuration", INFO_COMPLETE if lines else INFO_NOT_STARTED),
        _info("sku", INFO_COMPLETE if _all(lambda line: line.manufacturer_sku) else (INFO_REVIEW_REQUIRED if lines else INFO_NOT_STARTED)),
        _info("dealer_price", INFO_COMPLETE if _all(lambda line: line.dealer_price_usd is not None) else (INFO_REVIEW_REQUIRED if lines else INFO_NOT_STARTED)),
        _info("shipping", INFO_COMPLETE if shipping_lines or (draft and not any("Shipping" in item for item in (draft.warnings or []))) else (INFO_REVIEW_REQUIRED if draft else INFO_NOT_STARTED)),
        _info("import_tax", INFO_COMPLETE if _any(lambda line: line.import_tax_jpy is not None) else (INFO_MISSING if lines else INFO_NOT_STARTED)),
        _info("insurance", INFO_COMPLETE if _any(lambda line: line.insurance_jpy is not None) else (INFO_MISSING if lines else INFO_NOT_STARTED)),
        _info("landed_cost", INFO_COMPLETE if economics and getattr(economics, "total_landed_cost_jpy", None) is not None else (INFO_MISSING if draft else INFO_NOT_STARTED)),
        _info(
            "sales_price",
            INFO_COMPLETE
            if _all(lambda line: getattr(line, "final_price_status", None) != FinalPriceStatus.NOT_SET and line.final_sales_price_jpy is not None)
            else (INFO_REVIEW_REQUIRED if lines else INFO_NOT_STARTED),
        ),
        _info("margin", INFO_COMPLETE if economics and getattr(economics, "gross_margin_rate", None) is not None else (INFO_MISSING if draft else INFO_NOT_STARTED)),
        _info("human_review", INFO_REVIEW_REQUIRED if warnings.get("count") else (INFO_COMPLETE if draft else INFO_NOT_STARTED), warnings.get("count") or 0),
        _info("approval", INFO_COMPLETE if snapshot is not None else (INFO_WAITING if draft else INFO_NOT_STARTED)),
        _info("export", INFO_WAITING if snapshot is not None else INFO_NOT_STARTED),
    ]
    return WorkSummary(
        kind=KIND_QUOTE,
        process_status=process,
        items=items,
        customer=getattr(draft, "customer", None) if draft is not None else getattr(snapshot, "customer", None),
        title=getattr(draft, "title", None) if draft is not None else getattr(snapshot, "title", None),
        updated_at=updated_at or (getattr(draft, "updated_at", None).isoformat() if getattr(draft, "updated_at", None) else None),
        extra={"gross_margin": getattr(economics, "gross_margin_rate", None) if economics is not None else None},
    )


def operations_are_blocked(summary: WorkSummary) -> bool:
    return False
