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
from llm.provider import ProviderError, TechnicalCaseProvider, get_technical_case_provider
from models import Case, CaseRequirement, QuestionStatus, QuestionTarget, TechnicalQuestion
from ui.technical_case_flow import build_case_from_inputs, normalize_optional_text

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "technical_case_agent.md"
SOURCE_AI_EXTRACTED = "AI_EXTRACTED_UNVERIFIED"
ERROR_PROVIDER = "PROVIDER_ERROR"
ERROR_VALIDATION = "VALIDATION_ERROR"
ERROR_UNEXPECTED = "UNEXPECTED_ERROR"


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


def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def get_active_provider_name(provider: Optional[TechnicalCaseProvider] = None) -> str:
    return (provider or get_technical_case_provider()).name


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
        return _failed_run(case, inquiry, active_provider.name, ERROR_PROVIDER, str(error))
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
