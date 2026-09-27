from typing import Optional
from uuid import uuid4

from agents.approval import QuestionApprovalItem
from models import (
    AnswerSourceType,
    FactConfidence,
    FactScope,
    TechnicalFact,
    TechnicalFactCandidate,
)
from ui.technical_case_flow import normalize_optional_text

ERROR_NOT_APPROVED = "NOT_APPROVED"
ERROR_NO_ANSWER = "NO_ANSWER"
ERROR_DUPLICATE_FACT = "DUPLICATE_FACT"
ERROR_MISSING_FACT_TEXT = "MISSING_FACT_TEXT"
FACT_STATUS_HUMAN_REGISTERED = "HUMAN_REGISTERED"
WARNING_REUSABLE = "REUSABLE_CONFIRM"
WARNING_TIME_SENSITIVE_REUSABLE = "TIME_SENSITIVE_REUSABLE"
SPACEONE_DERIVED_HOLDING_FORCE_MARKERS = ("約45kgf", "45kgf", "45 kgf")


class FactRegistrationInput:
    def __init__(
        self,
        product: Optional[str] = None,
        topic: Optional[str] = None,
        fact: Optional[str] = None,
        scope: Optional[FactScope] = None,
        is_time_sensitive: bool = False,
        confidence: Optional[FactConfidence] = None,
        notes: Optional[str] = None,
    ) -> None:
        self.product = normalize_optional_text(product)
        self.topic = normalize_optional_text(topic)
        self.fact = normalize_optional_text(fact)
        self.scope = scope or FactScope.CASE_ONLY
        self.is_time_sensitive = is_time_sensitive
        self.confidence = confidence
        self.notes = normalize_optional_text(notes)


class FactRegistrationResult:
    def __init__(
        self,
        success: bool,
        fact: Optional[TechnicalFact] = None,
        candidate: Optional[TechnicalFactCandidate] = None,
        error_code: Optional[str] = None,
        warnings: Optional[list[str]] = None,
    ) -> None:
        self.success = success
        self.fact = fact
        self.candidate = candidate
        self.error_code = error_code
        self.warnings = warnings or []


def build_source_reference(item: QuestionApprovalItem) -> str:
    parts = [f"question_id={item.question.question_id}"]
    if item.answer is not None:
        parts.insert(0, f"answer_id={item.answer.answer_id}")
    if item.approval is not None:
        parts.append(f"approval_id={item.approval.approval_id}")
    return ";".join(parts)


def draft_fact_candidate(item: QuestionApprovalItem) -> Optional[TechnicalFactCandidate]:
    if not item.is_applied or item.answer is None:
        return None
    fact_text = item.answer.answer
    if fact_text is None and item.approval is not None:
        fact_text = item.approval.approved_answer
    return TechnicalFactCandidate(
        fact_candidate_id=f"FC-{uuid4().hex[:10].upper()}",
        case_id=item.question.case_id,
        question_id=item.question.question_id,
        answer_id=item.answer.answer_id,
        product=None,
        topic=None,
        fact=fact_text,
        scope=FactScope.CASE_ONLY,
        source_type=AnswerSourceType.MANUFACTURER_RESPONSE.value,
        source_reference=build_source_reference(item),
        suggested_confidence=FactConfidence.AI_EXTRACTED_UNVERIFIED,
        notes=None,
        is_time_sensitive=False,
    )


def fact_signature(product: Optional[str], topic: Optional[str], fact: Optional[str]) -> tuple:
    return (
        (product or "").strip().lower(),
        (topic or "").strip().lower(),
        (fact or "").strip().lower(),
    )


def is_duplicate_fact(item: QuestionApprovalItem, human_input: FactRegistrationInput) -> bool:
    signature = fact_signature(human_input.product, human_input.topic, human_input.fact)
    for existing in item.registered_facts:
        if fact_signature(existing.product, existing.topic, existing.fact) == signature:
            return True
    return False


def looks_like_spaceone_derived_holding_force(text: Optional[str]) -> bool:
    content = text or ""
    return any(marker in content for marker in SPACEONE_DERIVED_HOLDING_FORCE_MARKERS)


def fact_registration_warnings(scope: FactScope, is_time_sensitive: bool) -> list[str]:
    warnings = []
    if scope == FactScope.PRODUCT_REUSABLE:
        warnings.append(WARNING_REUSABLE)
    if scope == FactScope.PRODUCT_REUSABLE and is_time_sensitive:
        warnings.append(WARNING_TIME_SENSITIVE_REUSABLE)
    return warnings


def register_technical_fact(
    item: QuestionApprovalItem,
    human_input: FactRegistrationInput,
) -> FactRegistrationResult:
    if not item.is_applied:
        return FactRegistrationResult(success=False, error_code=ERROR_NOT_APPROVED)
    if item.answer is None:
        return FactRegistrationResult(success=False, error_code=ERROR_NO_ANSWER)
    if human_input.fact is None:
        return FactRegistrationResult(success=False, error_code=ERROR_MISSING_FACT_TEXT)
    if is_duplicate_fact(item, human_input):
        return FactRegistrationResult(success=False, error_code=ERROR_DUPLICATE_FACT)

    warnings = fact_registration_warnings(human_input.scope, human_input.is_time_sensitive)
    fact = TechnicalFact(
        fact_id=f"FACT-{uuid4().hex[:10].upper()}",
        case_id=item.question.case_id,
        product=human_input.product,
        topic=human_input.topic,
        fact=human_input.fact,
        source_type=AnswerSourceType.MANUFACTURER_RESPONSE.value,
        source_reference=build_source_reference(item),
        confidence=human_input.confidence,
        status=FACT_STATUS_HUMAN_REGISTERED,
        scope=human_input.scope,
        is_time_sensitive=human_input.is_time_sensitive,
        notes=human_input.notes,
    )
    item.registered_facts.append(fact)
    return FactRegistrationResult(success=True, fact=fact, warnings=warnings)
