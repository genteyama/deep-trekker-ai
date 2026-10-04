import pytest

from agents.technical_case_agent import run_manufacturer_response_analysis
from llm.analysis_schema import ExtractedQuestion, TechnicalCaseAnalysisResponse
from llm.completeness import (
    harden_analysis,
    validate_analysis_completeness,
    validate_manufacturer_match_completeness,
)
from llm.mock_provider import MockTechnicalCaseProvider
from models import (
    ManufacturerResponseAnalysis,
    QuestionStatus,
    QuestionTarget,
    ResponseMatchCandidate,
    SuggestedQuestionStatus,
    TechnicalQuestion,
)


INQUIRY = (
    "PipeTrekker で管内点検したい。内径は300mm、水温は20℃です。"
    "測定した場所を把握したいです。"
)


def _question(question_id: str) -> TechnicalQuestion:
    return TechnicalQuestion(
        question_id=question_id,
        case_id="CASE-COMP",
        target=QuestionTarget.MANUFACTURER,
        question="Can this configuration be used?",
        status=QuestionStatus.DRAFT,
    )


def test_explicit_product_extraction_completeness():
    empty = TechnicalCaseAnalysisResponse(case_summary="summary only")
    issues = validate_analysis_completeness(INQUIRY, empty)
    assert any(item.code == "EMPTY_REQUESTED_PRODUCTS" for item in issues)

    hardened = harden_analysis(INQUIRY, empty)
    assert "PipeTrekker" in hardened.requested_products
    assert not any(
        item.code == "EMPTY_REQUESTED_PRODUCTS"
        for item in validate_analysis_completeness(INQUIRY, hardened)
    )


def test_requirements_completeness():
    empty = TechnicalCaseAnalysisResponse(requested_products=["PipeTrekker"])
    issues = validate_analysis_completeness(INQUIRY, empty)
    assert any(item.code == "EMPTY_REQUIREMENTS" for item in issues)

    hardened = harden_analysis(INQUIRY, empty)
    assert hardened.requirements
    assert any(item.value and "300mm" in item.value for item in hardened.requirements)
    assert not any(
        item.code == "EMPTY_REQUIREMENTS"
        for item in validate_analysis_completeness(INQUIRY, hardened)
    )


def test_customer_wording_preservation():
    payload = TechnicalCaseAnalysisResponse(
        requested_products=["PipeTrekker"],
        requirements=[{"label": "内径", "value": "300mm", "original_text": "内径は300mm"}],
        customer_questions=[
            ExtractedQuestion(
                question="GPS/IMUで位置を取れますか",
                classification="CUSTOMER_REQUIRED",
                source="CUSTOMER_INPUT",
                original_text="測定した場所を把握したい",
            )
        ],
    )
    issues = validate_analysis_completeness(INQUIRY, payload)
    assert any(item.code == "CUSTOMER_WORDING_NARROWED" for item in issues)

    hardened = harden_analysis(INQUIRY, payload)
    assert hardened.customer_questions[0].classification == "AI_SUGGESTED"
    assert hardened.customer_questions[0].source == "AI_SUGGESTED"


def test_ai_suggested_separation_cannot_be_customer_required():
    payload = TechnicalCaseAnalysisResponse(
        requested_products=["PipeTrekker"],
        requirements=[{"value": "300mm"}],
        manufacturer_questions=[
            ExtractedQuestion(
                question="Is a Doppler log required?",
                classification="CUSTOMER_REQUIRED",
                source="AI_SUGGESTED",
            )
        ],
    )
    issues = validate_analysis_completeness("PipeTrekker 300mm", payload)
    assert any(item.code == "AI_SUGGESTED_AS_CUSTOMER_REQUIRED" for item in issues)


def test_manufacturer_question_full_matching_and_missing_answer():
    questions = [_question("Q-1"), _question("Q-2"), _question("Q-3")]
    analysis = ManufacturerResponseAnalysis(
        matches=[
            ResponseMatchCandidate(
                question_id="Q-1",
                suggested_status=SuggestedQuestionStatus.ANSWERED,
                evidence_text="compatible with the stated vehicle",
            ),
            ResponseMatchCandidate(
                question_id="Q-2",
                suggested_status=SuggestedQuestionStatus.FOLLOW_UP_REQUIRED,
                follow_up_required=True,
            ),
            ResponseMatchCandidate(
                question_id="Q-3",
                suggested_status=SuggestedQuestionStatus.FOLLOW_UP_REQUIRED,
                follow_up_required=True,
            ),
        ]
    )
    assert validate_manufacturer_match_completeness(questions, analysis) == []


def test_empty_matches_failure():
    questions = [_question("Q-1"), _question("Q-2")]
    issues = validate_manufacturer_match_completeness(
        questions,
        ManufacturerResponseAnalysis(matches=[], unmatched_information=[{"original_text": "whole reply"}]),
        response_text="whole reply",
    )
    assert any(item.code == "EMPTY_MATCHES" for item in issues)
    assert any(item.severity == "FAIL" for item in issues)


def test_missing_and_duplicate_question_match_failure():
    questions = [_question("Q-1"), _question("Q-2")]
    missing = validate_manufacturer_match_completeness(
        questions,
        ManufacturerResponseAnalysis(
            matches=[
                ResponseMatchCandidate(
                    question_id="Q-1",
                    suggested_status=SuggestedQuestionStatus.FOLLOW_UP_REQUIRED,
                    follow_up_required=True,
                )
            ]
        ),
    )
    assert any(item.code == "MISSING_QUESTION_MATCH" for item in missing)

    duplicate = validate_manufacturer_match_completeness(
        questions,
        ManufacturerResponseAnalysis(
            matches=[
                ResponseMatchCandidate(question_id="Q-1", suggested_status=SuggestedQuestionStatus.FOLLOW_UP_REQUIRED),
                ResponseMatchCandidate(question_id="Q-1", suggested_status=SuggestedQuestionStatus.ANSWERED, evidence_text="x"),
                ResponseMatchCandidate(question_id="Q-2", suggested_status=SuggestedQuestionStatus.FOLLOW_UP_REQUIRED),
            ]
        ),
    )
    assert any(item.code == "DUPLICATE_QUESTION_MATCH" for item in duplicate)


def test_empty_matches_are_filled_as_follow_up():
    provider = MockTechnicalCaseProvider(
        response_payload={
            "response_summary": "empty",
            "matches": [],
            "unmatched_information": [{"original_text": "dumped reply"}],
            "overall_follow_up_required": True,
        }
    )
    run = run_manufacturer_response_analysis([_question("Q-1")], "dumped reply", provider=provider)
    assert run.success is True
    assert len(run.matches) == 1
    assert run.matches[0].candidate.suggested_status.value == "FOLLOW_UP_REQUIRED"
    assert run.matches[0].validation.reason == "NO_MODEL_MATCH"


def test_unsupported_assertion_failure():
    payload = TechnicalCaseAnalysisResponse(
        case_summary="ATEXが必要。納期は2週間。",
        requested_products=["PipeTrekker"],
        requirements=[{"label": "認証", "value": "ATEXが必要"}],
    )
    issues = validate_analysis_completeness("PipeTrekker で点検したい。", payload)
    assert any(item.code == "UNSUPPORTED_ASSERTION" for item in issues)
    assert any(item.severity == "FAIL" for item in issues)
