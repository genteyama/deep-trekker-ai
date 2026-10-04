import pytest
from pydantic import ValidationError

from agents.technical_case_agent import (
    ERROR_EMPTY_RESPONSE,
    ERROR_NO_QUESTIONS,
    ERROR_PROVIDER,
    ERROR_VALIDATION,
    merge_response_matches,
    run_manufacturer_response_analysis,
    validate_manufacturer_response_payload,
)
from llm.mock_provider import (
    DEFAULT_RESPONSE_SUMMARY,
    MockTechnicalCaseProvider,
    build_default_manufacturer_response_payload,
)
from llm.provider import ProviderError
from models import (
    ManufacturerResponseAnalysis,
    MatchConfidence,
    QuestionStatus,
    QuestionTarget,
    ResponseMatchCandidate,
    SuggestedQuestionStatus,
    TechnicalQuestion,
)


def _question(question_id: str, text: str) -> TechnicalQuestion:
    return TechnicalQuestion(
        question_id=question_id,
        case_id="CASE-MR-001",
        target=QuestionTarget.MANUFACTURER,
        question=text,
        status=QuestionStatus.SENT,
        follow_up_required=False,
    )


SAMPLE_QUESTIONS = [
    _question("Q-MR-001", "指定アクセサリと組み合わせて使用できるか"),
    _question("Q-MR-002", "追加カメラを同時搭載できるか"),
    _question("Q-MR-003", "水深情報を取得できるか"),
    _question("Q-MR-004", "メーカー推奨構成は何か"),
]


def test_mock_manufacturer_response_returns_fixed_pattern():
    provider = MockTechnicalCaseProvider()
    first = provider.analyze_manufacturer_response(
        [{"question_id": "Q-MR-001", "question": "組み合わせは可能か"}],
        "まったく関係ない本文A",
    )
    second = provider.analyze_manufacturer_response(
        [{"question_id": "Q-MR-001", "question": "組み合わせは可能か"}],
        "まったく別の本文B",
    )

    assert first["response_summary"] == DEFAULT_RESPONSE_SUMMARY
    assert first == second
    analysis = validate_manufacturer_response_payload(first)
    assert isinstance(analysis, ManufacturerResponseAnalysis)


def test_mock_payload_covers_answered_partial_and_follow_up():
    payload = build_default_manufacturer_response_payload(
        [
            {"question_id": "Q-MR-001"},
            {"question_id": "Q-MR-002"},
            {"question_id": "Q-MR-003"},
            {"question_id": "Q-MR-004"},
        ]
    )
    statuses = [item["suggested_status"] for item in payload["matches"]]

    assert statuses == [
        "ANSWERED",
        "PARTIAL",
        "FOLLOW_UP_REQUIRED",
        "FOLLOW_UP_REQUIRED",
    ]
    assert payload["matches"][0]["follow_up_required"] is False
    assert payload["matches"][1]["follow_up_required"] is True
    assert payload["matches"][2]["follow_up_question"]
    assert payload["matches"][0]["confidence"] == "HIGH"
    assert payload["unmatched_information"]


def test_run_converts_mock_matches_without_changing_question_status():
    run = run_manufacturer_response_analysis(
        SAMPLE_QUESTIONS,
        "メーカーからの返信サンプルです。",
    )

    assert run.success is True
    assert run.provider_name == "mock"
    assert len(run.matches) == 4
    assert run.matches[0].candidate.suggested_status == SuggestedQuestionStatus.ANSWERED
    assert run.matches[1].candidate.suggested_status == SuggestedQuestionStatus.PARTIAL
    assert run.matches[2].candidate.suggested_status == SuggestedQuestionStatus.FOLLOW_UP_REQUIRED
    assert run.matches[3].candidate.suggested_status == SuggestedQuestionStatus.FOLLOW_UP_REQUIRED
    assert all(view.question.status == QuestionStatus.SENT for view in run.matches)
    assert all(view.candidate.confidence in MatchConfidence for view in run.matches if view.candidate.confidence)
    assert run.unmatched_information
    assert run.original_response_text == "メーカーからの返信サンプルです。"


def test_missing_question_stays_as_follow_up_required():
    analysis = ManufacturerResponseAnalysis(
        response_summary="部分的な照合結果",
        matches=[
            ResponseMatchCandidate(
                question_id="Q-MR-001",
                suggested_status=SuggestedQuestionStatus.ANSWERED,
                follow_up_required=False,
                confidence=MatchConfidence.HIGH,
                evidence_text="部分的な照合結果",
            )
        ],
        unmatched_information=[],
        overall_follow_up_required=True,
    )

    views = merge_response_matches(SAMPLE_QUESTIONS, analysis, "部分的な照合結果")
    remaining_ids = [view.question.question_id for view in views]

    assert remaining_ids == ["Q-MR-001", "Q-MR-002", "Q-MR-003", "Q-MR-004"]
    assert views[0].candidate.suggested_status == SuggestedQuestionStatus.ANSWERED
    assert views[1].candidate.suggested_status == SuggestedQuestionStatus.FOLLOW_UP_REQUIRED
    assert views[1].candidate.follow_up_required is True


def test_invalid_response_payload_returns_validation_error():
    provider = MockTechnicalCaseProvider(response_payload={"matches": "bad-data"})
    run = run_manufacturer_response_analysis(
        SAMPLE_QUESTIONS,
        "メーカー回答",
        provider=provider,
    )

    assert run.success is False
    assert run.error_code == ERROR_VALIDATION
    assert run.error_details


def test_closed_is_not_a_valid_suggested_status():
    with pytest.raises(ValidationError):
        validate_manufacturer_response_payload(
            {
                "matches": [
                    {
                        "question_id": "Q-MR-001",
                        "suggested_status": "CLOSED",
                    }
                ]
            }
        )


def test_provider_error_does_not_crash_response_analysis():
    provider = MockTechnicalCaseProvider(response_error=ProviderError("response mock failed"))
    run = run_manufacturer_response_analysis(
        SAMPLE_QUESTIONS,
        "メーカー回答",
        provider=provider,
    )

    assert run.success is False
    assert run.error_code == ERROR_PROVIDER
    assert "response mock failed" in run.error_details


def test_zero_questions_returns_error():
    run = run_manufacturer_response_analysis([], "メーカー回答があります。")

    assert run.success is False
    assert run.error_code == ERROR_NO_QUESTIONS
    assert run.matches == []


def test_empty_response_text_returns_error():
    run = run_manufacturer_response_analysis(SAMPLE_QUESTIONS, "   ")

    assert run.success is False
    assert run.error_code == ERROR_EMPTY_RESPONSE
    assert run.matches == []
