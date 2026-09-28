from types import SimpleNamespace
import logging

import pytest

from llm.analysis_schema import TechnicalCaseAnalysisResponse
from llm.anthropic_provider import (
    CONNECTION_TEST_USER_MESSAGE,
    DEFAULT_MODEL,
    FALLBACK_BETA,
    MISSING_API_KEY_MESSAGE,
    AnthropicTechnicalCaseProvider,
    configured_model,
    fallbacks_enabled,
    has_api_key,
    redact_secrets,
)
from llm.provider import (
    ERROR_MISSING_API_KEY,
    ProviderError,
    get_provider_runtime_status,
    get_technical_case_provider,
    run_provider_connection_test,
)
from llm.usage import TokenUsageRecord
from models import ManufacturerResponseAnalysis


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def make_provider(parsed_output, stop_reason="end_turn", *, enable_fallbacks=False, usage=None):
    response = SimpleNamespace(
        stop_reason=stop_reason,
        parsed_output=parsed_output,
        usage=usage,
    )
    messages = FakeMessages(response)
    beta_messages = FakeMessages(response)
    client = SimpleNamespace(messages=messages, beta=SimpleNamespace(messages=beta_messages))
    provider = AnthropicTechnicalCaseProvider(
        client=client,
        model="claude-opus-5",
        enable_fallbacks=enable_fallbacks,
    )
    return provider, messages, beta_messages


def test_analyze_technical_case_returns_dict_and_sends_prompt():
    provider, messages, beta_messages = make_provider(TechnicalCaseAnalysisResponse(case_summary="管内点検"))

    payload = provider.analyze_technical_case("内径300mmの管", case_name="案件A", system_prompt="SYS")

    assert payload["case_summary"] == "管内点検"
    assert messages.calls
    assert not beta_messages.calls
    call = messages.calls[0]
    assert call["system"] == "SYS"
    assert call["output_format"] is TechnicalCaseAnalysisResponse
    assert "内径300mmの管" in call["messages"][0]["content"]
    assert "fallbacks" not in call
    assert "betas" not in call


def test_analyze_manufacturer_response_uses_response_schema():
    provider, messages, _beta = make_provider(ManufacturerResponseAnalysis(response_summary="ok"))

    payload = provider.analyze_manufacturer_response([{"question_id": "Q1"}], "回答文")

    assert payload["response_summary"] == "ok"
    assert messages.calls[0]["output_format"] is ManufacturerResponseAnalysis


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_incomplete_responses_raise_provider_error(stop_reason):
    provider, _, _ = make_provider(None, stop_reason=stop_reason)
    with pytest.raises(ProviderError):
        provider.analyze_technical_case("text")


def test_fallbacks_are_off_by_default(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_ENABLE_FALLBACKS", raising=False)
    assert fallbacks_enabled() is False
    parsed = TechnicalCaseAnalysisResponse(case_summary="x")
    messages = FakeMessages(SimpleNamespace(stop_reason="end_turn", parsed_output=parsed, usage=None))
    beta_messages = FakeMessages(SimpleNamespace(stop_reason="end_turn", parsed_output=parsed, usage=None))
    client = SimpleNamespace(messages=messages, beta=SimpleNamespace(messages=beta_messages))
    provider = AnthropicTechnicalCaseProvider(client=client, model="claude-opus-5")
    provider.analyze_technical_case("text")
    assert provider.fallbacks_enabled is False
    assert "fallbacks" not in messages.calls[0]
    assert not beta_messages.calls


def test_fallbacks_sent_only_when_enabled(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_ENABLE_FALLBACKS", "true")
    parsed = TechnicalCaseAnalysisResponse(case_summary="x")
    messages = FakeMessages(SimpleNamespace(stop_reason="end_turn", parsed_output=parsed, usage=None))
    beta_messages = FakeMessages(SimpleNamespace(stop_reason="end_turn", parsed_output=parsed, usage=None))
    client = SimpleNamespace(messages=messages, beta=SimpleNamespace(messages=beta_messages))
    provider = AnthropicTechnicalCaseProvider(client=client, model="claude-opus-5")
    provider.analyze_technical_case("text")
    assert provider.fallbacks_enabled is True
    assert not messages.calls
    call = beta_messages.calls[0]
    assert call["fallbacks"] == "default"
    assert FALLBACK_BETA in call["betas"]


def test_model_env_override(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-4")
    parsed = TechnicalCaseAnalysisResponse(case_summary="x")
    messages = FakeMessages(SimpleNamespace(stop_reason="end_turn", parsed_output=parsed, usage=None))
    client = SimpleNamespace(
        messages=messages,
        beta=SimpleNamespace(messages=FakeMessages(SimpleNamespace(stop_reason="end_turn", parsed_output=parsed, usage=None))),
    )
    provider = AnthropicTechnicalCaseProvider(client=client)
    provider.analyze_technical_case("text")
    assert configured_model() == "claude-sonnet-4"
    assert provider.model == "claude-sonnet-4"
    assert messages.calls[0]["model"] == "claude-sonnet-4"


def test_default_model_is_opus_5(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    assert configured_model() == DEFAULT_MODEL


def test_missing_api_key_raises_on_execute_not_on_init(monkeypatch):
    monkeypatch.setenv("TECHNICAL_CASE_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert has_api_key() is False
    provider = get_technical_case_provider()
    assert provider.name == "anthropic"
    with pytest.raises(ProviderError, match=MISSING_API_KEY_MESSAGE) as raised:
        provider.analyze_technical_case("管内点検")
    assert raised.value.error_code == ERROR_MISSING_API_KEY


def test_missing_api_key_does_not_use_mock(monkeypatch):
    monkeypatch.setenv("TECHNICAL_CASE_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from agents.technical_case_agent import run_technical_case_analysis
    from llm.mock_provider import DEFAULT_MOCK_PAYLOAD

    run = run_technical_case_analysis("案件", "顧客", None, "問い合わせ")
    assert run.success is False
    assert run.provider_name == "anthropic"
    assert run.error_code == ERROR_MISSING_API_KEY
    assert run.error_details == MISSING_API_KEY_MESSAGE
    assert run.analysis_json is None
    assert run.case_summary != DEFAULT_MOCK_PAYLOAD["case_summary"]


def test_connection_test_does_not_send_customer_data():
    from llm.anthropic_provider import ConnectionTestOutput

    parsed = ConnectionTestOutput(ok=True)
    provider, messages, _ = make_provider(parsed)
    result = provider.test_connection()
    content = messages.calls[0]["messages"][0]["content"]
    assert result.success is True
    assert messages.calls[0]["output_format"] is ConnectionTestOutput
    assert content == CONNECTION_TEST_USER_MESSAGE
    assert "customer_name" not in content
    assert "inquiry_text" not in content
    assert "案件" not in content


def test_connection_test_via_factory_without_key(monkeypatch):
    monkeypatch.setenv("TECHNICAL_CASE_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = run_provider_connection_test()
    assert result.success is False
    assert result.error_code == ERROR_MISSING_API_KEY
    assert result.error_message == MISSING_API_KEY_MESSAGE


def test_secrets_are_not_logged(caplog):
    caplog.set_level(logging.INFO)
    secret = "sk-ant-secret-value-123456"
    provider, messages, _ = make_provider(
        TechnicalCaseAnalysisResponse(case_summary="ok"),
        usage=SimpleNamespace(input_tokens=11, output_tokens=7),
    )
    provider.analyze_technical_case("顧客の生メール全文を含む問い合わせ", customer_name="秘密顧客")
    combined = caplog.text + redact_secrets(secret)
    assert secret not in caplog.text
    assert "ANTHROPIC_API_KEY" not in caplog.text
    assert "x-api-key" not in caplog.text.lower()
    assert "秘密顧客" not in caplog.text
    assert "生メール" not in caplog.text
    assert "provider=anthropic" in caplog.text
    assert "model=claude-opus-5" in caplog.text
    assert "fallbacks=False" in caplog.text
    assert "[REDACTED]" in combined
    assert provider.last_usage.input_tokens == 11
    assert provider.last_usage.output_tokens == 7
    assert isinstance(provider.last_usage, TokenUsageRecord)


def test_usage_record_is_ready_for_future_persistence():
    record = TokenUsageRecord(
        provider="anthropic",
        model="claude-opus-5",
        input_tokens=10,
        output_tokens=4,
        timestamp="2026-09-28T00:00:00+00:00",
        case_id="case-1",
        operation="analyze_technical_case",
        success=True,
        http_status=200,
        duration_ms=12,
        fallbacks_enabled=False,
    )
    payload = record.as_dict()
    assert payload["input_tokens"] == 10
    assert payload["output_tokens"] == 4
    assert payload["model"] == "claude-opus-5"
    assert payload["timestamp"] == "2026-09-28T00:00:00+00:00"
    assert payload["case_id"] == "case-1"


def test_runtime_status_for_anthropic(monkeypatch):
    monkeypatch.setenv("TECHNICAL_CASE_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-5")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_ENABLE_FALLBACKS", "false")
    status = get_provider_runtime_status()
    assert status["provider_label"] == "Claude"
    assert status["model"] == "claude-opus-5"
    assert status["fallbacks_enabled"] is False
    assert status["api_key_configured"] is False
    assert status["connection"] == "disconnected"
    assert status["supports_connection_test"] is True
