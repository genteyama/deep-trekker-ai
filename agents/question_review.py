from __future__ import annotations

from typing import Optional

from models import QuestionReviewStatus, TechnicalQuestion
from ui.technical_case_flow import normalize_optional_text

SOURCE_AI_SUGGESTED = "AI_SUGGESTED"
CLASSIFICATION_AI_SUGGESTED = "AI_SUGGESTED"


def default_review_status(question: TechnicalQuestion) -> str:
    if (question.classification or question.source) == SOURCE_AI_SUGGESTED:
        return QuestionReviewStatus.PENDING.value
    return QuestionReviewStatus.PENDING.value


def is_auto_approvable(question: TechnicalQuestion) -> bool:
    return False


def apply_question_review(
    question: TechnicalQuestion,
    status: str,
    edited_text: Optional[str] = None,
) -> TechnicalQuestion:
    review = QuestionReviewStatus(status)
    update = {"review_status": review.value}
    if review == QuestionReviewStatus.EDITED:
        text = normalize_optional_text(edited_text)
        if text:
            if not question.ai_original_question:
                update["ai_original_question"] = question.question
            update["human_edited_question"] = text
            update["question"] = text
    if review == QuestionReviewStatus.REJECTED:
        update["follow_up_required"] = False
    return question.model_copy(update=update)
