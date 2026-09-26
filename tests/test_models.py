import json

import pytest
from pydantic import ValidationError

import app
from models import (
    Case,
    CaseRequirement,
    Configuration,
    ConfigurationItem,
    FactConfidence,
    QuestionStatus,
    QuestionTarget,
    RecommendationOrigin,
    TechnicalAnswer,
    TechnicalFact,
    TechnicalQuestion,
    create_sample_case,
    sample_case_json,
)


def test_case_allows_unknown_fields_as_none():
    case = Case(case_id="CASE-EMPTY")

    assert case.case_name is None
    assert case.customer_name is None
    assert case.end_user_name is None
    assert case.status is None
    assert case.requested_products == []
    assert case.created_at is None
    assert case.updated_at is None


def test_sample_case_can_be_created():
    case = create_sample_case()

    assert case.case_id == "CASE-2026-001"
    assert case.case_name == "PipeTrekker 管内点検"
    assert case.end_user_name is None
    assert case.requested_products == ["PipeTrekker"]


def test_sample_case_converts_to_json():
    payload = json.loads(sample_case_json())

    assert payload["case_id"] == "CASE-2026-001"
    assert payload["end_user_name"] is None
    assert payload["created_at"] == "2026-09-26T13:00:00Z"
    assert payload["updated_at"] == "2026-09-26T13:00:00Z"


def test_requirement_is_unconfirmed_until_reviewed():
    requirement = CaseRequirement(
        requirement_id="REQ-001",
        case_id="CASE-2026-001",
        category="pipe",
        label="pipe_diameter",
        value="300",
        unit="mm",
        source="AI_EXTRACTED_UNVERIFIED",
    )

    assert requirement.confirmed is False


def test_related_models_share_case_id():
    case = create_sample_case()
    question = TechnicalQuestion(
        question_id="Q-001",
        case_id=case.case_id,
        target=QuestionTarget.MANUFACTURER,
        question="What crawler is required for a 300mm pipe?",
        status=QuestionStatus.DRAFT,
    )
    configuration = Configuration(
        configuration_id="CFG-001",
        case_id=case.case_id,
        name="PipeTrekker base",
        recommendation_origin=RecommendationOrigin.CUSTOMER_REQUESTED,
        items=[
            ConfigurationItem(sku="PT-BASE", description="PipeTrekker base unit", quantity=1),
        ],
    )

    assert question.case_id == case.case_id
    assert configuration.case_id == case.case_id
    assert configuration.items[0].sku == "PT-BASE"


def test_technical_answer_keeps_original_text():
    answer = TechnicalAnswer(
        answer_id="A-001",
        question_id="Q-001",
        answer=None,
        source_type="EMAIL",
        confidence="AI_EXTRACTED_UNVERIFIED",
        original_text="Please confirm the pipe diameter.",
    )

    assert answer.answer is None
    assert answer.original_text == "Please confirm the pipe diameter."


def test_ai_extracted_fact_is_marked_unverified():
    fact = TechnicalFact(
        fact_id="FACT-001",
        case_id="CASE-2026-001",
        product="PipeTrekker",
        topic="pipe_diameter",
        fact="300mm",
        confidence=FactConfidence.AI_EXTRACTED_UNVERIFIED,
    )

    assert fact.confidence == FactConfidence.AI_EXTRACTED_UNVERIFIED
    assert fact.model_dump(mode="json")["confidence"] == "AI_EXTRACTED_UNVERIFIED"


def test_invalid_fact_confidence_is_rejected():
    with pytest.raises(ValidationError):
        TechnicalFact(
            fact_id="FACT-002",
            case_id="CASE-2026-001",
            confidence="GUESSED",
        )


def test_streamlit_app_still_imports():
    texts = app.load_texts("ja")

    assert texts["app_title"] == "Deep Trekker 業務支援AI"
    assert texts["agents"]["technical_case"]["name"] == "営業・技術受付AI"
    assert texts["agents"]["quote_control"]["name"] == "見積・価格管理AI"
