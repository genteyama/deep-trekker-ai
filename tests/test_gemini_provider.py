from json import dumps
import logging

import pytest

from llm.analysis_schema import TechnicalCaseAnalysisResponse
from llm.gemini_provider import (
    CONNECTION_TEST_USER_MESSAGE,
    DEFAULT_ENDPOINT,
    DEFAULT_MODEL,
    ERROR_AUTH,
    ERROR_INVALID_JSON,
    ERROR_SCHEMA,
    MISSING_API_KEY_MESSAGE,
    THINKING_LEVEL,
    ConnectionTestOutput,
    GeminiTechnicalCaseProvider,
    configured_model,
    extract_structured_text,
    has_api_key,
    json_schema_for,
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


class FakeGeminiClient:
    def __init__(self, response=None):
        self.response = response
        self.posts = []

    def post_interaction(self, payload):
        self.posts.append(payload)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def interaction_payload(content, *, usage=None, thought="secret gemini reasoning"):
    payload = {
        "status": "completed",
        "output_text": content,
        "steps": [
            {"type": "thought", "text": thought},
            {"type": "model_output", "text": content},
        ],
        "usage": {
            "input_tokens": 21,
            "output_tokens": 9,
        },
        "_http_status": 200,
    }
    if usage:
        payload["usage"] = usage
    return payload


def make_provider(content, **kwargs):
    client = FakeGeminiClient(interaction_payload(content, **kwargs))
    provider = GeminiTechnicalCaseProvider(client=client, model=DEFAULT_MODEL)
    return provider, client


def test_factory_selects_gemini(monkeypatch):
    monkeypatch.setenv("TECHNICAL_CASE_PROVIDER", "gemini")
    provider = get_technical_case_provider()
    assert provider.name == "gemini"
    assert provider.model == DEFAULT_MODEL


def test_default_model_is_gemini_38_flash(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert configured_model() == "gemini-3.8-flash"
    assert DEFAULT_ENDPOINT.endswith("/v1beta/interactions")


def test_model_env_override(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3-flash")
    provider, client = make_provider(dumps({"case_summary": "管内点検"}))
    env_provider = GeminiTechnicalCaseProvider(client=client)
    env_provider.analyze_technical_case("管内点検")
    assert configured_model() == "gemini-3-flash"
    assert env_provider.model == "gemini-3-flash"
    assert client.posts[0]["model"] == "gemini-3-flash"


def test_missing_api_key_raises_on_execute_not_on_init(monkeypatch):
    monkeypatch.setenv("TECHNICAL_CASE_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert has_api_key() is False
    provider = get_technical_case_provider()
    assert provider.name == "gemini"
    with pytest.raises(ProviderError, match=MISSING_API_KEY_MESSAGE) as raised:
        provider.analyze_technical_case("管内点検")
    assert raised.value.error_code == ERROR_MISSING_API_KEY


def test_missing_api_key_does_not_use_mock_or_ollama(monkeypatch):
    monkeypatch.setenv("TECHNICAL_CASE_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from agents.technical_case_agent import run_technical_case_analysis
    from llm.mock_provider import DEFAULT_MOCK_PAYLOAD

    run = run_technical_case_analysis("案件", "顧客", None, "問い合わせ")
    assert run.success is False
    assert run.provider_name == "gemini"
    assert run.error_code == ERROR_MISSING_API_KEY
    assert run.error_details == MISSING_API_KEY_MESSAGE
    assert run.analysis_json is None
    assert run.case_summary != DEFAULT_MOCK_PAYLOAD["case_summary"]


def test_analyze_sends_shared_prompt_and_existing_schema():
    provider, client = make_provider(dumps({"case_summary": "管内点検"}))
    payload = provider.analyze_technical_case("内径300mmの管", case_name="案件A", system_prompt="SYS")
    assert payload["case_summary"] == "管内点検"
    request = client.posts[0]
    assert request["system_instruction"] == "SYS"
    assert "内径300mmの管" in request["input"]
    assert request["response_format"]["type"] == "text"
    assert request["response_format"]["mime_type"] == "application/json"
    assert request["response_format"]["schema"] == json_schema_for(TechnicalCaseAnalysisResponse)
    assert request["generation_config"]["thinking_level"] == THINKING_LEVEL
    assert "temperature" not in request
    assert "temperature" not in request["generation_config"]
    assert "GEMINI_API_KEY" not in dumps(request)
    assert "AIza" not in dumps(request)


def test_manufacturer_response_uses_existing_schema():
    provider, client = make_provider(dumps({"response_summary": "ok"}))
    payload = provider.analyze_manufacturer_response([{"question_id": "Q1"}], "回答文")
    assert payload["response_summary"] == "ok"
    assert client.posts[0]["response_format"]["schema"] == json_schema_for(ManufacturerResponseAnalysis)


def test_invalid_schema_raises_provider_error():
    provider, _ = make_provider(dumps({"requirements": "not-a-list"}))
    with pytest.raises(ProviderError, match="schema") as raised:
        provider.analyze_technical_case("管内点検")
    assert raised.value.error_code == ERROR_SCHEMA


def test_invalid_json_raises_provider_error():
    provider, _ = make_provider("Thinking...\nnot json")
    with pytest.raises(ProviderError, match="JSON") as raised:
        provider.analyze_technical_case("管内点検")
    assert raised.value.error_code == ERROR_INVALID_JSON


def test_authentication_error_raises_provider_error_without_fallback(monkeypatch):
    monkeypatch.setenv("TECHNICAL_CASE_PROVIDER", "gemini")
    client = FakeGeminiClient(
        ProviderError("Gemini API error (401): invalid api key", error_code=ERROR_AUTH)
    )
    provider = GeminiTechnicalCaseProvider(client=client)
    with pytest.raises(ProviderError) as raised:
        provider.analyze_technical_case("管内点検")
    assert raised.value.error_code == ERROR_AUTH

    from agents.technical_case_agent import run_technical_case_analysis
    from llm.mock_provider import DEFAULT_MOCK_PAYLOAD

    failing = FakeGeminiClient(
        ProviderError("Gemini API error (401): invalid api key", error_code=ERROR_AUTH)
    )
    run = run_technical_case_analysis(
        "案件",
        "顧客",
        None,
        "問い合わせ",
        provider=GeminiTechnicalCaseProvider(client=failing),
    )
    assert run.success is False
    assert run.provider_name == "gemini"
    assert run.analysis_json is None
    assert run.case_summary != DEFAULT_MOCK_PAYLOAD["case_summary"]


def test_thinking_is_not_included_in_result_or_logs(caplog):
    caplog.set_level(logging.INFO)
    content = dumps({"case_summary": "管内点検", "thinking": "should be ignored by extra=ignore"})
    provider, _ = make_provider(content, thought="IHI confidential ATEX reasoning")
    payload = provider.analyze_technical_case("顧客の生メール全文", customer_name="秘密顧客")
    assert payload["case_summary"] == "管内点検"
    assert "thinking" not in payload
    assert "reasoning" not in payload
    assert "IHI confidential" not in caplog.text
    assert "ATEX reasoning" not in caplog.text
    assert "秘密顧客" not in caplog.text
    assert "生メール" not in caplog.text
    assert "provider=gemini" in caplog.text
    assert "model=gemini-3.8-flash" in caplog.text
    assert provider.last_usage.input_tokens == 21
    assert provider.last_usage.output_tokens == 9
    assert isinstance(provider.last_usage, TokenUsageRecord)


def test_extract_structured_text_ignores_thought_steps():
    payload = {
        "steps": [
            {"type": "thought", "text": "do not expose"},
            {"type": "model_output", "text": '{"ok": true}'},
        ]
    }
    assert extract_structured_text(payload) == '{"ok": true}'


def test_secrets_are_not_logged(caplog):
    caplog.set_level(logging.INFO)
    secret = "AIzaSySecretGeminiKeyValue"
    provider, _ = make_provider(dumps({"case_summary": "ok"}))
    provider.analyze_technical_case("顧客の生メール全文を含む問い合わせ", customer_name="秘密顧客")
    combined = caplog.text + redact_secrets(secret)
    assert secret not in caplog.text
    assert "GEMINI_API_KEY" not in caplog.text
    assert "x-goog-api-key" not in caplog.text.lower()
    assert "秘密顧客" not in caplog.text
    assert "生メール" not in caplog.text
    assert "[REDACTED]" in combined
    assert provider.last_usage.provider == "gemini"


def test_auth_error_redacts_api_key():
    message = redact_secrets("Gemini API error (401): AIzaSySecretGeminiKeyValue")
    assert "AIzaSySecretGeminiKeyValue" not in message
    assert "[REDACTED]" in message


def test_connection_test_does_not_send_customer_data():
    provider, client = make_provider(dumps({"ok": True}))
    result = provider.test_connection()
    request = client.posts[0]
    content = request["input"]
    assert result.success is True
    assert request["response_format"]["schema"] == json_schema_for(ConnectionTestOutput)
    assert content == CONNECTION_TEST_USER_MESSAGE
    assert "customer_name" not in content
    assert "inquiry_text" not in content
    assert "案件" not in content
    assert "IHI" not in content
    assert "fixture" not in content.lower()


def test_connection_test_via_factory_without_key(monkeypatch):
    monkeypatch.setenv("TECHNICAL_CASE_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    result = run_provider_connection_test()
    assert result.success is False
    assert result.provider == "gemini"
    assert result.error_code == ERROR_MISSING_API_KEY
    assert result.error_message == MISSING_API_KEY_MESSAGE


def test_connection_test_via_factory_does_not_fallback(monkeypatch):
    monkeypatch.setenv("TECHNICAL_CASE_PROVIDER", "gemini")
    result = run_provider_connection_test(
        GeminiTechnicalCaseProvider(
            client=FakeGeminiClient(
                ProviderError("Gemini API error (401): invalid api key", error_code=ERROR_AUTH)
            )
        )
    )
    assert result.success is False
    assert result.provider == "gemini"
    assert result.error_code == ERROR_AUTH


def test_runtime_status_for_gemini(monkeypatch):
    monkeypatch.setenv("TECHNICAL_CASE_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    status = get_provider_runtime_status()
    assert status["provider_label"] == "Gemini"
    assert status["model"] == "gemini-3.8-flash"
    assert status["api_key_configured"] is False
    assert status["connection"] == "disconnected"
    assert status["supports_connection_test"] is True
    assert status["show_fallbacks"] is False
    assert status["connection_test_button_key"] == "gemini_connection_test"
    assert status["fallbacks_enabled"] is False
