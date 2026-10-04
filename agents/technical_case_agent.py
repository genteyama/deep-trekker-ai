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
from agents.fact_retrieval import (
    build_fact_grounded_questions,
    detect_requested_products,
    facts_to_models,
    merge_manufacturer_questions,
)
from agents.knowledge import (
    KnowledgeContextSnapshot,
    build_knowledge_snapshot,
    provider_knowledge_payload,
    selected_catalog_facts,
)
from agents.question_review import default_review_status
from llm.evidence_guard import (
    REASON_NO_MODEL_MATCH,
    EvidenceCheck,
    apply_evidence_guard,
    extract_product_entities,
    missing_match_candidate,
)
from llm.completeness import (
    ERROR_COMPLETENESS,
    CompletenessError,
    harden_analysis,
    raise_if_fail,
    validate_analysis_completeness,
    validate_manufacturer_match_completeness,
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
        completeness_issues: Optional[list] = None,
        retrieved_facts: Optional[list] = None,
        detected_products: Optional[list] = None,
        knowledge_snapshot: Optional[KnowledgeContextSnapshot] = None,
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
        self.completeness_issues = completeness_issues or []
        self.retrieved_facts = retrieved_facts or []
        self.detected_products = detected_products or []
        self.knowledge_snapshot = knowledge_snapshot


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
        completeness_issues: Optional[list] = None,
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
        self.completeness_issues = completeness_issues or []


class QuestionMatchView:
    def __init__(
        self,
        question: TechnicalQuestion,
        candidate: ResponseMatchCandidate,
        validation: Optional[EvidenceCheck] = None,
    ) -> None:
        self.question = question
        self.candidate = candidate
        self.validation = validation or EvidenceCheck()


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
                original_text=item.original_text,
                normalized_meaning=item.normalized_meaning,
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
                classification=item.classification,
                source=item.source,
                original_text=item.original_text,
                normalized_meaning=item.normalized_meaning,
                grounding=item.grounding,
                related_products=extract_product_entities(
                    " ".join([item.question or "", item.grounding or "", item.normalized_meaning or ""])
                ),
                review_status=default_review_status(
                    TechnicalQuestion(
                        question_id="TMP",
                        case_id=case_id,
                        classification=item.classification,
                        source=item.source,
                    )
                ),
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
    selected_fact_ids: Optional[list] = None,
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
    detected_products = detect_requested_products(inquiry)
    knowledge_snapshot = build_knowledge_snapshot(detected_products, selected_fact_ids)
    retrieved_facts = selected_catalog_facts(detected_products, selected_fact_ids)
    if knowledge_snapshot.items:
        logger.info(
            "retrieved_facts products=%s selected=%s fact_ids=%s",
            detected_products,
            [item.fact_id for item in knowledge_snapshot.selected_facts()],
            [item.fact_id for item in knowledge_snapshot.items],
        )

    try:
        payload = active_provider.analyze_technical_case(
            inquiry_text=inquiry,
            case_name=case.case_name,
            customer_name=case.customer_name,
            end_user_name=case.end_user_name,
            system_prompt=load_system_prompt(),
            approved_technical_facts=provider_knowledge_payload(retrieved_facts),
        )
        analysis = harden_analysis(inquiry, validate_analysis_payload(payload))
        issues = validate_analysis_completeness(inquiry, analysis)
        raise_if_fail(issues)
        manufacturer_items = merge_manufacturer_questions(
            list(analysis.manufacturer_questions),
            build_fact_grounded_questions(inquiry, retrieved_facts),
        )
        analysis = analysis.model_copy(
            update={
                "manufacturer_questions": [
                    item if isinstance(item, ExtractedQuestion) else ExtractedQuestion.model_validate(item)
                    for item in manufacturer_items
                ]
            }
        )
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
            requirements=convert_requirements(
                updated_case.case_id,
                list(analysis.requirements)
                + list(analysis.customer_goal)
                + list(analysis.existing_equipment),
            ),
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
            completeness_issues=issues,
            retrieved_facts=facts_to_models(retrieved_facts),
            detected_products=detected_products,
            knowledge_snapshot=knowledge_snapshot,
        )
    except CompletenessError as error:
        logger.exception("Technical case completeness failed")
        return _failed_run(
            case,
            inquiry,
            active_provider.name,
            ERROR_COMPLETENESS,
            str(error),
            completeness_issues=error.issues,
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
    completeness_issues: Optional[list] = None,
) -> TechnicalCaseRun:
    return TechnicalCaseRun(
        success=False,
        case=case,
        provider_name=provider_name,
        inquiry_text=inquiry,
        error_code=error_code,
        error_details=error_details,
        completeness_issues=completeness_issues,
        retrieved_facts=facts_to_models(selected_catalog_facts(detect_requested_products(inquiry))),
        detected_products=detect_requested_products(inquiry),
        knowledge_snapshot=build_knowledge_snapshot(detect_requested_products(inquiry)),
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
    response_text: Optional[str] = None,
) -> list[QuestionMatchView]:
    matches_by_id = {item.question_id: item for item in analysis.matches}
    views = []
    for question in questions:
        candidate = matches_by_id.get(question.question_id)
        validation = EvidenceCheck(reason=REASON_NO_MODEL_MATCH, requires_human_review=True)
        if candidate is None:
            candidate = missing_match_candidate(question)
        else:
            candidate, validation = apply_evidence_guard(question, candidate, response_text)
        views.append(QuestionMatchView(question=question, candidate=candidate, validation=validation))
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
        matches = merge_response_matches(questions, analysis, original_text)
        guarded = analysis.model_copy(update={"matches": [view.candidate for view in matches]})
        issues = validate_manufacturer_match_completeness(questions, guarded, original_text)
        raise_if_fail(issues)
        return ManufacturerResponseRun(
            success=True,
            provider_name=active_provider.name,
            original_response_text=original_text,
            response_summary=analysis.response_summary,
            matches=matches,
            unmatched_information=list(analysis.unmatched_information),
            overall_follow_up_required=guarded.overall_follow_up_required
            or any(view.candidate.follow_up_required for view in matches),
            analysis_json=guarded.model_dump(mode="json"),
            completeness_issues=issues,
        )
    except CompletenessError as error:
        logger.exception("Manufacturer response completeness failed")
        return ManufacturerResponseRun(
            success=False,
            provider_name=active_provider.name,
            original_response_text=original_text,
            error_code=ERROR_COMPLETENESS,
            error_details=str(error),
            completeness_issues=error.issues,
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
