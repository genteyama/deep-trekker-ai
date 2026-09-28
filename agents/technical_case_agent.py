from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Optional
from uuid import uuid4

from pydantic import ValidationError

from llm.analysis_schema import (
    ExtractedQuestion,
    ExtractedRequirement,
    TechnicalCaseAnalysisResponse,
    UnresolvedItem,
)
from llm.provider import (
    ProviderError,
    TechnicalCaseProvider,
    get_technical_case_provider,
    selected_provider_name,
)
from models import (
    Case,
    CaseRequirement,
    ManufacturerResponseAnalysis,
    MatchConfidence,
    QuestionStatus,
    QuestionTarget,
    ResponseMatchCandidate,
    SuggestedQuestionStatus,
    TechnicalQuestion,
    UnmatchedInformation,
)
from ui.technical_case_flow import build_case_from_inputs, normalize_optional_text

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "technical_case_agent.md"
RESPONSE_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "manufacturer_response.md"
SOURCE_AI_EXTRACTED = "AI_EXTRACTED_UNVERIFIED"
ERROR_PROVIDER = "PROVIDER_ERROR"
ERROR_VALIDATION = "VALIDATION_ERROR"
ERROR_UNEXPECTED = "UNEXPECTED_ERROR"
ERROR_NO_QUESTIONS = "NO_QUESTIONS"
ERROR_EMPTY_RESPONSE = "EMPTY_RESPONSE"


class TechnicalCaseRun:
    def __init__(
        self,
        success: bool,
        case: Case,
        provider_name: str,
        inquiry_text: Optional[str] = None,
        case_summary: Optional[str] = None,
        requested_products: Optional[list[str]] = None,
        requirements: Optional[list[CaseRequirement]] = None,
        customer_questions: Optional[list[TechnicalQuestion]] = None,
        manufacturer_questions: Optional[list[TechnicalQuestion]] = None,
        technical_questions: Optional[list[TechnicalQuestion]] = None,
        unresolved_items: Optional[list[UnresolvedItem]] = None,
        analysis_json: Optional[dict] = None,
        error_code: Optional[str] = None,
        error_details: Optional[str] = None,
    ) -> None:
        self.success = success
        self.case = case
        self.provider_name = provider_name
        self.inquiry_text = inquiry_text
        self.case_summary = case_summary
        self.requested_products = requested_products or []
        self.requirements = requirements or []
        self.customer_questions = customer_questions or []
        self.manufacturer_questions = manufacturer_questions or []
        self.technical_questions = technical_questions or []
        self.unresolved_items = unresolved_items or []
        self.analysis_json = analysis_json
        self.error_code = error_code
        self.error_details = error_details


class ManufacturerResponseRun:
    def __init__(
        self,
        success: bool,
        provider_name: str,
        original_response_text: Optional[str] = None,
        response_summary: Optional[str] = None,
        matches: Optional[list] = None,
        unmatched_information: Optional[list[UnmatchedInformation]] = None,
        overall_follow_up_required: bool = False,
        analysis_json: Optional[dict] = None,
        error_code: Optional[str] = None,
        error_details: Optional[str] = None,
    ) -> None:
        self.success = success
        self.provider_name = provider_name
        self.original_response_text = original_response_text
        self.response_summary = response_summary
        self.matches = matches or []
        self.unmatched_information = unmatched_information or []
        self.overall_follow_up_required = overall_follow_up_required
        self.analysis_json = analysis_json
        self.error_code = error_code
        self.error_details = error_details


class QuestionMatchView:
    def __init__(self, question: TechnicalQuestion, candidate: ResponseMatchCandidate) -> None:
        self.question = question
        self.candidate = candidate


def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def load_manufacturer_response_prompt() -> str:
    return RESPONSE_PROMPT_PATH.read_text(encoding="utf-8")


def get_active_provider_name(provider: Optional[TechnicalCaseProvider] = None) -> str:
    if provider is not None:
        return provider.name
    return selected_provider_name()


def validate_analysis_payload(payload: object) -> TechnicalCaseAnalysisResponse:
    return TechnicalCaseAnalysisResponse.model_validate(payload)


def convert_requirements(
    case_id: str,
    items: list[ExtractedRequirement],
) -> list[CaseRequirement]:
    requirements = []
    for item in items:
        requirements.append(
            CaseRequirement(
                requirement_id=f"REQ-{uuid4().hex[:10].upper()}",
                case_id=case_id,
                category=item.category,
                label=item.label,
                value=item.value,
                unit=item.unit,
                source=SOURCE_AI_EXTRACTED,
                confirmed=False,
                notes=item.notes,
            )
        )
    return requirements


def convert_questions(
    case_id: str,
    items: list[ExtractedQuestion],
    target: QuestionTarget,
    created_at: Optional[datetime] = None,
) -> list[TechnicalQuestion]:
    timestamp = created_at or datetime.now(timezone.utc)
    questions = []
    for item in items:
        questions.append(
            TechnicalQuestion(
                question_id=f"Q-{uuid4().hex[:10].upper()}",
                case_id=case_id,
                target=target,
                question=item.question,
                status=QuestionStatus.DRAFT,
                follow_up_required=False,
                created_at=timestamp,
            )
        )
    return questions


def run_technical_case_analysis(
    case_name: Optional[str],
    customer_name: Optional[str],
    end_user_name: Optional[str],
    inquiry_text: Optional[str],
    provider: Optional[TechnicalCaseProvider] = None,
    case_id: Optional[str] = None,
    created_at: Optional[datetime] = None,
) -> TechnicalCaseRun:
    active_provider = provider or get_technical_case_provider()
    case = build_case_from_inputs(
        case_name,
        customer_name,
        end_user_name,
        case_id=case_id,
        created_at=created_at,
    )
    inquiry = normalize_optional_text(inquiry_text)

    try:
        payload = active_provider.analyze_technical_case(
            inquiry_text=inquiry,
            case_name=case.case_name,
            customer_name=case.customer_name,
            end_user_name=case.end_user_name,
            system_prompt=load_system_prompt(),
        )
        analysis = validate_analysis_payload(payload)
        updated_case = case.model_copy(
            update={"requested_products": list(analysis.requested_products)}
        )
        return TechnicalCaseRun(
            success=True,
            case=updated_case,
            provider_name=active_provider.name,
            inquiry_text=inquiry,
            case_summary=analysis.case_summary,
            requested_products=list(analysis.requested_products),
            requirements=convert_requirements(updated_case.case_id, analysis.requirements),
            customer_questions=convert_questions(
                updated_case.case_id,
                analysis.customer_questions,
                QuestionTarget.CUSTOMER,
                created_at=created_at,
            ),
            manufacturer_questions=convert_questions(
                updated_case.case_id,
                analysis.manufacturer_questions,
                QuestionTarget.MANUFACTURER,
                created_at=created_at,
            ),
            technical_questions=convert_questions(
                updated_case.case_id,
                analysis.technical_questions,
                QuestionTarget.INTERNAL,
                created_at=created_at,
            ),
            unresolved_items=list(analysis.unresolved_items),
            analysis_json=analysis.model_dump(mode="json"),
        )
    except ProviderError as error:
        logger.exception("Technical case provider failed")
        code = getattr(error, "error_code", None) or ERROR_PROVIDER
        return _failed_run(case, inquiry, active_provider.name, code, str(error))
    except ValidationError as error:
        logger.exception("Technical case analysis validation failed")
        return _failed_run(case, inquiry, active_provider.name, ERROR_VALIDATION, str(error))
    except Exception as error:
        logger.exception("Technical case analysis failed")
        return _failed_run(case, inquiry, active_provider.name, ERROR_UNEXPECTED, str(error))


def _failed_run(
    case: Case,
    inquiry: Optional[str],
    provider_name: str,
    error_code: str,
    error_details: str,
) -> TechnicalCaseRun:
    return TechnicalCaseRun(
        success=False,
        case=case,
        provider_name=provider_name,
        inquiry_text=inquiry,
        error_code=error_code,
        error_details=error_details,
    )


def validate_manufacturer_response_payload(payload: object) -> ManufacturerResponseAnalysis:
    return ManufacturerResponseAnalysis.model_validate(payload)


def build_question_payloads(questions: list[TechnicalQuestion]) -> list[dict]:
    payloads = []
    for question in questions:
        payloads.append(
            {
                "question_id": question.question_id,
                "question": question.question,
                "target": question.target.value if question.target else None,
            }
        )
    return payloads


def merge_response_matches(
    questions: list[TechnicalQuestion],
    analysis: ManufacturerResponseAnalysis,
) -> list[QuestionMatchView]:
    matches_by_id = {item.question_id: item for item in analysis.matches}
    views = []
    for question in questions:
        candidate = matches_by_id.get(question.question_id)
        if candidate is None:
            candidate = ResponseMatchCandidate(
                question_id=question.question_id,
                answer_summary=None,
                suggested_status=SuggestedQuestionStatus.FOLLOW_UP_REQUIRED,
                follow_up_required=True,
                follow_up_question=question.question,
                confidence=MatchConfidence.LOW,
                evidence_text=None,
            )
        views.append(QuestionMatchView(question=question, candidate=candidate))
    return views


def run_manufacturer_response_analysis(
    questions: list[TechnicalQuestion],
    response_text: Optional[str],
    provider: Optional[TechnicalCaseProvider] = None,
) -> ManufacturerResponseRun:
    active_provider = provider or get_technical_case_provider()
    original_text = normalize_optional_text(response_text)

    if not questions:
        return ManufacturerResponseRun(
            success=False,
            provider_name=active_provider.name,
            original_response_text=original_text,
            error_code=ERROR_NO_QUESTIONS,
            error_details="No TechnicalQuestion items were provided.",
        )
    if original_text is None:
        return ManufacturerResponseRun(
            success=False,
            provider_name=active_provider.name,
            original_response_text=None,
            error_code=ERROR_EMPTY_RESPONSE,
            error_details="Manufacturer response text is empty.",
        )

    try:
        payload = active_provider.analyze_manufacturer_response(
            questions=build_question_payloads(questions),
            response_text=original_text,
            system_prompt=load_manufacturer_response_prompt(),
        )
        analysis = validate_manufacturer_response_payload(payload)
        matches = merge_response_matches(questions, analysis)
        return ManufacturerResponseRun(
            success=True,
            provider_name=active_provider.name,
            original_response_text=original_text,
            response_summary=analysis.response_summary,
            matches=matches,
            unmatched_information=list(analysis.unmatched_information),
            overall_follow_up_required=analysis.overall_follow_up_required,
            analysis_json=analysis.model_dump(mode="json"),
        )
    except ProviderError as error:
        logger.exception("Manufacturer response provider failed")
        return ManufacturerResponseRun(
            success=False,
            provider_name=active_provider.name,
            original_response_text=original_text,
            error_code=getattr(error, "error_code", None) or ERROR_PROVIDER,
            error_details=str(error),
        )
    except ValidationError as error:
        logger.exception("Manufacturer response validation failed")
        return ManufacturerResponseRun(
            success=False,
            provider_name=active_provider.name,
            original_response_text=original_text,
            error_code=ERROR_VALIDATION,
            error_details=str(error),
        )
    except Exception as error:
        logger.exception("Manufacturer response analysis failed")
        return ManufacturerResponseRun(
            success=False,
            provider_name=active_provider.name,
            original_response_text=original_text,
            error_code=ERROR_UNEXPECTED,
            error_details=str(error),
        )
