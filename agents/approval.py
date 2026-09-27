from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from agents.technical_case_agent import ManufacturerResponseRun
from models import (
    AnswerSourceType,
    ApprovalRecord,
    QuestionStatus,
    SuggestedQuestionStatus,
    TechnicalAnswer,
    TechnicalQuestion,
)
from ui.technical_case_flow import normalize_optional_text

ERROR_ALREADY_APPLIED = "ALREADY_APPLIED"
ERROR_CLOSED_NOT_ALLOWED = "CLOSED_NOT_ALLOWED"
ERROR_UNKNOWN_QUESTION = "UNKNOWN_QUESTION"
ALLOWED_APPROVED_STATUSES = {
    SuggestedQuestionStatus.ANSWERED,
    SuggestedQuestionStatus.PARTIAL,
    SuggestedQuestionStatus.FOLLOW_UP_REQUIRED,
}
STATUS_TO_QUESTION_STATUS = {
    SuggestedQuestionStatus.ANSWERED: QuestionStatus.ANSWERED,
    SuggestedQuestionStatus.PARTIAL: QuestionStatus.PARTIAL,
    SuggestedQuestionStatus.FOLLOW_UP_REQUIRED: QuestionStatus.FOLLOW_UP_REQUIRED,
}


class HumanApprovalInput:
    def __init__(
        self,
        approved_status: SuggestedQuestionStatus,
        approved_answer: Optional[str] = None,
        follow_up_required: bool = False,
        follow_up_question: Optional[str] = None,
        approved_by: Optional[str] = None,
    ) -> None:
        self.approved_status = approved_status
        self.approved_answer = normalize_optional_text(approved_answer)
        self.follow_up_required = follow_up_required
        self.follow_up_question = normalize_optional_text(follow_up_question)
        self.approved_by = normalize_optional_text(approved_by)


class QuestionApprovalItem:
    def __init__(self, question: TechnicalQuestion, ai_candidate) -> None:
        self.question = question
        self.ai_candidate = ai_candidate
        self.approval: Optional[ApprovalRecord] = None
        self.answer: Optional[TechnicalAnswer] = None
        self.registered_facts: list = []

    @property
    def is_applied(self) -> bool:
        return self.approval is not None


class ApprovalBoard:
    def __init__(self, original_response_text: Optional[str], items: list[QuestionApprovalItem]) -> None:
        self.original_response_text = original_response_text
        self.items = items

    def get_item(self, question_id: str) -> Optional[QuestionApprovalItem]:
        for item in self.items:
            if item.question.question_id == question_id:
                return item
        return None


class ApprovalApplyResult:
    def __init__(
        self,
        success: bool,
        item: Optional[QuestionApprovalItem] = None,
        error_code: Optional[str] = None,
    ) -> None:
        self.success = success
        self.item = item
        self.error_code = error_code


def build_approval_board(run: ManufacturerResponseRun) -> ApprovalBoard:
    items = []
    for view in run.matches:
        items.append(
            QuestionApprovalItem(
                question=view.question.model_copy(),
                ai_candidate=view.candidate.model_copy(),
            )
        )
    return ApprovalBoard(original_response_text=run.original_response_text, items=items)


def summarize_approvals(board: ApprovalBoard) -> dict:
    applied_items = [item for item in board.items if item.is_applied]
    return {
        "total": len(board.items),
        "applied": len(applied_items),
        "pending": len(board.items) - len(applied_items),
        "answered": _count_status(applied_items, SuggestedQuestionStatus.ANSWERED),
        "partial": _count_status(applied_items, SuggestedQuestionStatus.PARTIAL),
        "follow_up_required": _count_status(applied_items, SuggestedQuestionStatus.FOLLOW_UP_REQUIRED),
    }


def apply_human_approval(
    board: ApprovalBoard,
    question_id: str,
    human_input: HumanApprovalInput,
    approved_at: Optional[datetime] = None,
) -> ApprovalApplyResult:
    item = board.get_item(question_id)
    if item is None:
        return ApprovalApplyResult(success=False, error_code=ERROR_UNKNOWN_QUESTION)
    if item.is_applied:
        return ApprovalApplyResult(success=False, item=item, error_code=ERROR_ALREADY_APPLIED)
    if human_input.approved_status not in ALLOWED_APPROVED_STATUSES:
        return ApprovalApplyResult(success=False, item=item, error_code=ERROR_CLOSED_NOT_ALLOWED)

    timestamp = approved_at or datetime.now(timezone.utc)
    follow_up_required = human_input.follow_up_required
    if human_input.approved_status == SuggestedQuestionStatus.FOLLOW_UP_REQUIRED:
        follow_up_required = True

    item.approval = ApprovalRecord(
        approval_id=f"APR-{uuid4().hex[:10].upper()}",
        question_id=question_id,
        approved_status=human_input.approved_status,
        approved_answer=human_input.approved_answer,
        approved_follow_up_required=follow_up_required,
        approved_follow_up_question=human_input.follow_up_question,
        approved_at=timestamp,
        approved_by=human_input.approved_by,
        ai_suggested_status=item.ai_candidate.suggested_status,
        ai_suggested_answer=item.ai_candidate.answer_summary,
        ai_suggested_follow_up_question=item.ai_candidate.follow_up_question,
    )
    item.answer = TechnicalAnswer(
        answer_id=f"A-{uuid4().hex[:10].upper()}",
        question_id=question_id,
        answer=human_input.approved_answer,
        answered_by=None,
        answered_at=timestamp,
        source_type=AnswerSourceType.MANUFACTURER_RESPONSE.value,
        confidence=item.ai_candidate.confidence.value if item.ai_candidate.confidence else None,
        original_text=board.original_response_text,
    )
    item.question = item.question.model_copy(
        update={
            "status": STATUS_TO_QUESTION_STATUS[human_input.approved_status],
            "follow_up_required": follow_up_required,
        }
    )
    return ApprovalApplyResult(success=True, item=item)


def _count_status(items: list[QuestionApprovalItem], status: SuggestedQuestionStatus) -> int:
    return sum(1 for item in items if item.approval and item.approval.approved_status == status)
