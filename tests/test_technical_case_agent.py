import inspect

import pytest
from pydantic import ValidationError

from agents.technical_case_agent import (
    ERROR_PROVIDER,
    ERROR_VALIDATION,
    convert_questions,
    convert_requirements,
    get_active_provider_name,
    load_system_prompt,
    run_technical_case_analysis,
    validate_analysis_payload,
)
from llm.analysis_schema import ExtractedQuestion, ExtractedRequirement
from llm.mock_provider import DEFAULT_MOCK_PAYLOAD, MockTechnicalCaseProvider
from llm.provider import ProviderError, TechnicalCaseProvider, get_technical_case_provider
from models import QuestionStatus, QuestionTarget


class AlternateProvider(TechnicalCaseProvider):
    name = "alternate"

    def analyze_technical_case(
        self,
        inquiry_text,
        case_name=None,
        customer_name=None,
        end_user_name=None,
        system_prompt=None,
    ) -> dict:
        return {
            "case_summary": "Alternate provider sample",
            "requested_products": ["Deep Trekker"],
            "requirements": [
                {
                    "category": "usage",
                    "label": "用途",
                    "value": "水中点検",
                    "unit": None,
                    "notes": None,
                }
            ],
            "customer_questions": [{"question": "点検場所を教えてください。"}],
            "manufacturer_questions": [{"question": "水深条件を確認してください。"}],
            "technical_questions": [{"question": "推奨扱いしていないか確認してください。"}],
            "unresolved_items": [{"label": "水深", "notes": "未確認です。"}],
        }

    def analyze_manufacturer_response(
        self,
        questions,
        response_text=None,
        system_prompt=None,
    ) -> dict:
        return {
            "response_summary": "Alternate provider sample",
            "matches": [],
            "unmatched_information": [],
            "overall_follow_up_required": True,
        }


def test_mock_provider_returns_fixed_payload():
    provider = MockTechnicalCaseProvider()
    first = provider.analyze_technical_case("直径300mmの管を点検したい。")
    second = provider.analyze_technical_case("まったく別の問い合わせです。")

    assert first == DEFAULT_MOCK_PAYLOAD
    assert first == second
    assert first["case_summary"].startswith("これは開発確認用の固定サンプルです。")


def test_mock_payload_passes_pydantic_validation():
    analysis = validate_analysis_payload(DEFAULT_MOCK_PAYLOAD)

    assert analysis.case_summary is not None
    assert analysis.requested_products == ["PipeTrekker"]
    assert len(analysis.requirements) == 2
    assert len(analysis.customer_questions) == 2
    assert len(analysis.manufacturer_questions) == 1
    assert len(analysis.technical_questions) == 1
    assert len(analysis.unresolved_items) == 2


def test_invalid_payload_fails_validation():
    with pytest.raises(ValidationError):
        validate_analysis_payload({"requirements": "not-a-list"})


def test_requirements_convert_to_unconfirmed_case_requirements():
    items = [
        ExtractedRequirement(
            category="environment",
            label="管内径",
            value=None,
            unit="mm",
            notes="未確認",
        )
    ]

    requirements = convert_requirements("CASE-TEST-010", items)

    assert len(requirements) == 1
    assert requirements[0].case_id == "CASE-TEST-010"
    assert requirements[0].confirmed is False
    assert requirements[0].source == "AI_EXTRACTED_UNVERIFIED"
    assert requirements[0].value is None


def test_questions_are_routed_to_expected_targets():
    customer = convert_questions(
        "CASE-TEST-011",
        [ExtractedQuestion(question="管種を教えてください。")],
        QuestionTarget.CUSTOMER,
    )
    manufacturer = convert_questions(
        "CASE-TEST-011",
        [ExtractedQuestion(question="走行可否を確認してください。")],
        QuestionTarget.MANUFACTURER,
    )
    internal = convert_questions(
        "CASE-TEST-011",
        [ExtractedQuestion(question="推奨扱いしていないか確認してください。")],
        QuestionTarget.INTERNAL,
    )

    assert customer[0].target == QuestionTarget.CUSTOMER
    assert manufacturer[0].target == QuestionTarget.MANUFACTURER
    assert internal[0].target == QuestionTarget.INTERNAL
    assert customer[0].status == QuestionStatus.DRAFT
    assert manufacturer[0].status == QuestionStatus.DRAFT
    assert internal[0].status == QuestionStatus.DRAFT
    assert customer[0].follow_up_required is False


def test_run_uses_mock_provider_and_converts_models():
    run = run_technical_case_analysis(
        "PipeTrekker 管内点検",
        "サンプル株式会社",
        "",
        "直径300mmの管を点検したい。",
        case_id="CASE-TEST-012",
    )

    assert run.success is True
    assert run.provider_name == "mock"
    assert run.case.requested_products == ["PipeTrekker"]
    assert all(item.confirmed is False for item in run.requirements)
    assert all(item.target == QuestionTarget.CUSTOMER for item in run.customer_questions)
    assert all(item.target == QuestionTarget.MANUFACTURER for item in run.manufacturer_questions)
    assert all(item.target == QuestionTarget.INTERNAL for item in run.technical_questions)
    assert run.analysis_json["requested_products"] == ["PipeTrekker"]


def test_run_does_not_change_when_inquiry_text_changes():
    first = run_technical_case_analysis("A", "B", None, "最初の問い合わせ")
    second = run_technical_case_analysis("A", "B", None, "まったく別の問い合わせ")

    assert first.case_summary == second.case_summary
    assert first.analysis_json == second.analysis_json


def test_invalid_mock_data_returns_validation_error():
    provider = MockTechnicalCaseProvider(payload={"requirements": "bad-data"})
    run = run_technical_case_analysis(
        "案件",
        "顧客",
        None,
        "問い合わせ",
        provider=provider,
        case_id="CASE-TEST-013",
    )

    assert run.success is False
    assert run.error_code == ERROR_VALIDATION
    assert run.error_details
    assert run.requirements == []
    assert run.customer_questions == []


def test_provider_error_does_not_crash():
    provider = MockTechnicalCaseProvider(error=ProviderError("mock failed"))
    run = run_technical_case_analysis(
        "案件",
        "顧客",
        None,
        "問い合わせ",
        provider=provider,
    )

    assert run.success is False
    assert run.error_code == ERROR_PROVIDER
    assert "mock failed" in run.error_details


def test_ui_flow_stays_the_same_when_provider_is_swapped():
    mock_run = run_technical_case_analysis(
        "案件",
        "顧客",
        None,
        "問い合わせ",
        provider=MockTechnicalCaseProvider(),
    )
    alternate_run = run_technical_case_analysis(
        "案件",
        "顧客",
        None,
        "問い合わせ",
        provider=AlternateProvider(),
    )

    assert mock_run.success is True
    assert alternate_run.success is True
    assert mock_run.provider_name == "mock"
    assert alternate_run.provider_name == "alternate"
    assert alternate_run.case_summary == "Alternate provider sample"
    assert all(item.confirmed is False for item in alternate_run.requirements)
    assert alternate_run.customer_questions[0].target == QuestionTarget.CUSTOMER
    assert alternate_run.manufacturer_questions[0].target == QuestionTarget.MANUFACTURER
    assert alternate_run.technical_questions[0].target == QuestionTarget.INTERNAL


def test_factory_defaults_to_mock():
    provider = get_technical_case_provider()
    assert provider.name == "mock"
    assert get_active_provider_name() == "mock"


def test_unknown_provider_is_rejected():
    with pytest.raises(ProviderError):
        get_technical_case_provider("unknown-provider")


def test_system_prompt_keeps_proposal_origin_rules():
    prompt = load_system_prompt()

    assert "CUSTOMER_REQUESTED" in prompt
    assert "MANUFACTURER_RECOMMENDED" in prompt
    assert "SPACEONE_PROPOSAL" in prompt
    assert "AI_SUGGESTED" in prompt
    assert "Guess price" in prompt or "価格" in prompt


def test_agent_and_ui_do_not_call_anthropic():
    import agents.technical_case_agent as agent_module
    import ui.technical_case as ui_module

    assert "anthropic" not in inspect.getsource(agent_module).lower()
    assert "anthropic" not in inspect.getsource(ui_module).lower()
