from __future__ import annotations

from typing import Optional

from agents.approval import ApprovalBoard, QuestionApprovalItem, build_approval_board
from agents.knowledge import KnowledgeContextSnapshot, KnowledgeSnapshotItem
from agents.technical_case_agent import ManufacturerResponseRun, QuestionMatchView, TechnicalCaseRun
from llm.analysis_schema import UnresolvedItem
from llm.evidence_guard import EvidenceCheck
from models import (
    ApprovalRecord,
    Case,
    CaseRequirement,
    ManufacturerResponseRevision,
    QuestionHumanReview,
    QuestionReviewStatus,
    QuestionStatus,
    ResponseMatchCandidate,
    TechnicalAnswer,
    TechnicalCaseRecord,
    TechnicalCaseStatus,
    TechnicalQuestion,
    UnmatchedInformation,
)
from repositories.sqlite import now_iso, strip_secrets
from ui.technical_case_flow import build_case_from_inputs

STATUS_ORDER = [
    TechnicalCaseStatus.DRAFT.value,
    TechnicalCaseStatus.ANALYZED.value,
    TechnicalCaseStatus.QUESTIONS_REVIEW.value,
    TechnicalCaseStatus.WAITING_MANUFACTURER.value,
    TechnicalCaseStatus.MANUFACTURER_RESPONSE_RECEIVED.value,
    TechnicalCaseStatus.RESPONSE_REVIEW.value,
    TechnicalCaseStatus.COMPLETED.value,
]


def reviews_from_questions(questions: list[TechnicalQuestion]) -> list[QuestionHumanReview]:
    reviews = []
    for question in questions:
        reviews.append(
            QuestionHumanReview(
                question_id=question.question_id,
                review_status=question.review_status or QuestionReviewStatus.PENDING.value,
                ai_original=question.ai_original_question or question.question,
                human_edited=question.human_edited_question,
            )
        )
    return reviews


def snapshot_from_dict(payload: Optional[dict]) -> Optional[KnowledgeContextSnapshot]:
    if not payload:
        return None
    items = []
    for item in payload.get("items") or []:
        items.append(KnowledgeSnapshotItem(**item))
    return KnowledgeContextSnapshot(retrieved_at=payload.get("retrieved_at") or now_iso(), items=items)


def serialize_match_view(view: QuestionMatchView) -> dict:
    return {
        "question": view.question.model_dump(mode="json"),
        "candidate": view.candidate.model_dump(mode="json"),
        "validation": view.validation.as_dict() if view.validation else {},
    }


def match_view_from_dict(payload: dict) -> QuestionMatchView:
    validation = payload.get("validation") or {}
    return QuestionMatchView(
        question=TechnicalQuestion.model_validate(payload.get("question") or {}),
        candidate=ResponseMatchCandidate.model_validate(payload.get("candidate") or {}),
        validation=EvidenceCheck(**validation) if validation else EvidenceCheck(),
    )


def serialize_approval_board(board: Optional[ApprovalBoard]) -> Optional[dict]:
    if board is None:
        return None
    items = []
    for item in board.items:
        items.append(
            {
                "question": item.question.model_dump(mode="json"),
                "candidate": item.ai_candidate.model_dump(mode="json"),
                "approval": item.approval.model_dump(mode="json") if item.approval else None,
                "answer": item.answer.model_dump(mode="json") if item.answer else None,
            }
        )
    return {"original_response_text": board.original_response_text, "items": items}


def approval_board_from_dict(payload: Optional[dict], response_run: Optional[ManufacturerResponseRun]) -> Optional[ApprovalBoard]:
    if payload and payload.get("items"):
        items = []
        for item in payload["items"]:
            board_item = QuestionApprovalItem(
                question=TechnicalQuestion.model_validate(item.get("question") or {}),
                ai_candidate=ResponseMatchCandidate.model_validate(item.get("candidate") or {}),
            )
            if item.get("approval"):
                board_item.approval = ApprovalRecord.model_validate(item["approval"])
            if item.get("answer"):
                board_item.answer = TechnicalAnswer.model_validate(item["answer"])
            items.append(board_item)
        return ApprovalBoard(payload.get("original_response_text"), items)
    if response_run and response_run.success:
        return build_approval_board(response_run)
    return None


def proposed_status(
    *,
    has_analysis: bool,
    reviews: list[QuestionHumanReview],
    has_response: bool,
    applied_count: int,
) -> str:
    if has_response and applied_count:
        return TechnicalCaseStatus.RESPONSE_REVIEW.value
    if has_response:
        return TechnicalCaseStatus.MANUFACTURER_RESPONSE_RECEIVED.value
    manufacturer_reviews = reviews
    if manufacturer_reviews and all(
        item.review_status and item.review_status != QuestionReviewStatus.PENDING.value for item in manufacturer_reviews
    ):
        return TechnicalCaseStatus.WAITING_MANUFACTURER.value
    if any(item.review_status and item.review_status != QuestionReviewStatus.PENDING.value for item in manufacturer_reviews):
        return TechnicalCaseStatus.QUESTIONS_REVIEW.value
    if has_analysis:
        return TechnicalCaseStatus.ANALYZED.value
    return TechnicalCaseStatus.DRAFT.value


def advance_status(current: Optional[str], proposed: str, *, completed: bool = False) -> str:
    if completed:
        return TechnicalCaseStatus.COMPLETED.value
    if current == TechnicalCaseStatus.COMPLETED.value:
        return TechnicalCaseStatus.COMPLETED.value
    if proposed == TechnicalCaseStatus.COMPLETED.value:
        return current or TechnicalCaseStatus.DRAFT.value
    try:
        return STATUS_ORDER[max(STATUS_ORDER.index(current or TechnicalCaseStatus.DRAFT.value), STATUS_ORDER.index(proposed))]
    except ValueError:
        return proposed


def build_record(
    run: Optional[TechnicalCaseRun],
    response_run: Optional[ManufacturerResponseRun] = None,
    board: Optional[ApprovalBoard] = None,
    *,
    existing: Optional[TechnicalCaseRecord] = None,
    response_text: Optional[str] = None,
    completed: bool = False,
) -> TechnicalCaseRecord:
    case = run.case if run is not None else build_case_from_inputs(None, None, None)
    analysis_json = strip_secrets((run.analysis_json if run else None) or {})
    reviews = reviews_from_questions(list(run.manufacturer_questions) if run else [])
    validated = [serialize_match_view(view) for view in (response_run.matches if response_run else [])]
    evidence = [
        view.validation.as_dict()
        for view in (response_run.matches if response_run else [])
        if getattr(view, "validation", None) is not None
    ]
    applied = 0
    if board is not None:
        applied = sum(1 for item in board.items if item.is_applied)
    status = advance_status(
        existing.status if existing else (case.status if case else None),
        proposed_status(
            has_analysis=bool(run and run.success),
            reviews=reviews,
            has_response=bool(response_run and response_run.success),
            applied_count=applied,
        ),
        completed=completed,
    )
    provider = None
    model = None
    if response_run is not None:
        provider = response_run.provider_name
        model = getattr(response_run, "model", None)
    if run is not None:
        provider = provider or run.provider_name
        model = model or getattr(run, "model", None)
    if existing is not None:
        provider = provider or existing.provider
        model = model or existing.model
    record = TechnicalCaseRecord(
        case_id=case.case_id,
        customer_name=case.customer_name,
        case_title=case.case_name,
        created_at=existing.created_at if existing else (case.created_at.isoformat() if case.created_at else now_iso()),
        status=status,
        original_inquiry=run.inquiry_text if run else (existing.original_inquiry if existing else None),
        requested_products=list(run.requested_products) if run else list(getattr(case, "requested_products", []) or []),
        requirements=[item.model_dump(mode="json") for item in (run.requirements if run else [])],
        customer_goal=list(analysis_json.get("customer_goal") or []),
        existing_equipment=list(analysis_json.get("existing_equipment") or []),
        provider=provider,
        model=model,
        knowledge_snapshot=run.knowledge_snapshot.as_dict() if run and run.knowledge_snapshot else (existing.knowledge_snapshot if existing else None),
        manufacturer_questions=[item.model_dump(mode="json") for item in (run.manufacturer_questions if run else [])],
        question_human_reviews=reviews,
        manufacturer_response_input=response_text
        or (response_run.original_response_text if response_run else None)
        or (existing.manufacturer_response_input if existing else None),
        manufacturer_response_analysis=strip_secrets(response_run.analysis_json) if response_run else (existing.manufacturer_response_analysis if existing else None),
        validated_matches=validated or (existing.validated_matches if existing else []),
        evidence_validation_result=evidence or (existing.evidence_validation_result if existing else []),
        last_error=(run.error_details if run and not run.success else None)
        or (response_run.error_details if response_run and not response_run.success else None),
        end_user_name=case.end_user_name,
        case_summary=run.case_summary if run else (existing.case_summary if existing else None),
        customer_questions=[item.model_dump(mode="json") for item in (run.customer_questions if run else [])],
        technical_questions=[item.model_dump(mode="json") for item in (run.technical_questions if run else [])],
        unresolved_items=[
            item.model_dump(mode="json") if hasattr(item, "model_dump") else {"label": getattr(item, "label", None), "notes": getattr(item, "notes", None)}
            for item in (run.unresolved_items if run else [])
        ],
        analysis_json=analysis_json or None,
        inquiry_success=bool(run and run.success),
        response_revisions=list(existing.response_revisions) if existing else [],
        approval_board=serialize_approval_board(board),
        archived_at=existing.archived_at if existing else None,
        deleted_at=existing.deleted_at if existing else None,
        parent_case_id=existing.parent_case_id if existing else None,
        relation_type=existing.relation_type if existing else None,
    )
    return record


def run_from_record(record: TechnicalCaseRecord) -> TechnicalCaseRun:
    created = None
    try:
        if record.created_at:
            from datetime import datetime

            created = datetime.fromisoformat(record.created_at)
    except ValueError:
        created = None
    case = Case(
        case_id=record.case_id,
        case_name=record.case_title,
        customer_name=record.customer_name,
        end_user_name=record.end_user_name,
        status=record.status,
        requested_products=list(record.requested_products),
        created_at=created,
    )
    return TechnicalCaseRun(
        success=record.inquiry_success,
        case=case,
        provider_name=record.provider or "mock",
        model=record.model,
        inquiry_text=record.original_inquiry,
        case_summary=record.case_summary,
        requested_products=list(record.requested_products),
        requirements=[CaseRequirement.model_validate(item) for item in record.requirements],
        customer_questions=[TechnicalQuestion.model_validate(item) for item in record.customer_questions],
        manufacturer_questions=[TechnicalQuestion.model_validate(item) for item in record.manufacturer_questions],
        technical_questions=[TechnicalQuestion.model_validate(item) for item in record.technical_questions],
        unresolved_items=[UnresolvedItem.model_validate(item) for item in record.unresolved_items],
        analysis_json=record.analysis_json,
        error_details=record.last_error,
        knowledge_snapshot=snapshot_from_dict(record.knowledge_snapshot),
    )


def response_run_from_record(record: TechnicalCaseRecord) -> Optional[ManufacturerResponseRun]:
    if not record.manufacturer_response_analysis and not record.validated_matches:
        return None
    matches = [match_view_from_dict(item) for item in record.validated_matches]
    analysis = record.manufacturer_response_analysis or {}
    return ManufacturerResponseRun(
        success=True,
        provider_name=record.provider or "mock",
        model=record.model,
        original_response_text=record.manufacturer_response_input,
        response_summary=analysis.get("response_summary"),
        matches=matches,
        unmatched_information=[UnmatchedInformation.model_validate(item) for item in analysis.get("unmatched_information") or []],
        overall_follow_up_required=bool(analysis.get("overall_follow_up_required")),
        analysis_json=analysis,
    )


def revision_from_response_run(response_run: ManufacturerResponseRun) -> ManufacturerResponseRevision:
    return ManufacturerResponseRevision(
        revision=0,
        analyzed_at=now_iso(),
        provider=response_run.provider_name,
        model=getattr(response_run, "model", None),
        original_response=response_run.original_response_text,
        analysis=strip_secrets(response_run.analysis_json),
        validated_matches=[serialize_match_view(view) for view in response_run.matches],
        evidence_validation_result=[
            view.validation.as_dict() for view in response_run.matches if getattr(view, "validation", None) is not None
        ],
    )


def record_contains_secrets(record: TechnicalCaseRecord) -> bool:
    dumped = record.model_dump(mode="json")
    text = str(dumped)
    return "AIza" in text or "sk-ant-" in text or "GEMINI_API_KEY=" in text or "ANTHROPIC_API_KEY=" in text
