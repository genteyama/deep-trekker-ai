from json import dumps
import logging

import pytest

from llm.analysis_schema import TechnicalCaseAnalysisResponse
from llm.ollama_provider import (
    CHAT_PATH,
    CONNECTION_TEST_USER_MESSAGE,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    ERROR_INVALID_JSON,
    ERROR_MODEL_MISSING,
    ERROR_REMOTE_HOST,
    ERROR_SCHEMA,
    ERROR_UNREACHABLE,
    ConnectionTestOutput,
    OllamaTechnicalCaseProvider,
    configured_base_url,
    configured_model,
    json_schema_for,
    validate_local_base_url,
)
from llm.provider import (
    ProviderError,
    get_provider_runtime_status,
    get_technical_case_provider,
    run_provider_connection_test,
)
from llm.usage import TokenUsageRecord
from models import ManufacturerResponseAnalysis


class FakeOllamaClient:
    def __init__(self, chat_response=None, tags_response=None):
        self.chat_response = chat_response
        self.tags_response = tags_response or {"models": [{"name": DEFAULT_MODEL, "model": DEFAULT_MODEL}]}
        self.posts = []
        self.gets = []

    def get_json(self, path, timeout=None):
        self.gets.append({"path": path, "timeout": timeout})
        if isinstance(self.tags_response, Exception):
            raise self.tags_response
        return self.tags_response

    def post_json(self, path, payload, timeout=None):
        self.posts.append({"path": path, "payload": payload, "timeout": timeout})
        if isinstance(self.chat_response, Exception):
            raise self.chat_response
        return self.chat_response


def chat_payload(content, *, thinking="secret thinking", reasoning="secret reasoning", usage=None):
    payload = {
        "model": DEFAULT_MODEL,
        "message": {
            "role": "assistant",
            "content": content,
            "thinking": thinking,
            "reasoning": reasoning,
        },
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 21,
        "eval_count": 9,
        "_http_status": 200,
    }
    if usage:
        payload.update(usage)
    return payload


def make_provider(content, **kwargs):
    client = FakeOllamaClient(chat_response=chat_payload(content, **kwargs))
    provider = OllamaTechnicalCaseProvider(client=client, model=DEFAULT_MODEL)
    return provider, client


def test_factory_selects_ollama(monkeypatch):
    monkeypatch.setenv("TECHNICAL_CASE_PROVIDER", "ollama")
    provider = get_technical_case_provider()
    assert provider.name == "ollama"
    assert provider.model == DEFAULT_MODEL


def test_default_model_is_qwen35_9b(monkeypatch):
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    assert configured_model() == "qwen3.5:9b"


def test_model_env_override(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2:3b")
    provider, client = make_provider(dumps({"case_summary": "管内点検"}))
    env_provider = OllamaTechnicalCaseProvider(client=client)
    env_provider.analyze_technical_case("管内点検")
    assert configured_model() == "llama3.2:3b"
    assert env_provider.model == "llama3.2:3b"
    assert client.posts[0]["payload"]["model"] == "llama3.2:3b"


def test_localhost_is_default(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    assert configured_base_url() == DEFAULT_BASE_URL
    assert DEFAULT_BASE_URL.startswith("http://127.0.0.1")


def test_remote_base_url_is_rejected(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://example.com:11434")
    with pytest.raises(ProviderError, match="localhost") as raised:
        configured_base_url()
    assert raised.value.error_code == ERROR_REMOTE_HOST
    with pytest.raises(ProviderError) as created:
        validate_local_base_url("https://8.8.8.8:11434")
    assert created.value.error_code == ERROR_REMOTE_HOST


def test_analyze_sends_structured_schema_and_temperature_zero():
    provider, client = make_provider(dumps({"case_summary": "管内点検"}))
    payload = provider.analyze_technical_case("内径300mmの管", case_name="案件A", system_prompt="SYS")
    assert payload["case_summary"] == "管内点検"
    request = client.posts[0]["payload"]
    assert client.posts[0]["path"] == CHAT_PATH
    assert request["think"] is False
    assert request["stream"] is False
    assert request["options"]["temperature"] == 0
    assert request["format"] == json_schema_for(TechnicalCaseAnalysisResponse)
    assert request["messages"][0]["content"] == "SYS"
    assert "内径300mmの管" in request["messages"][1]["content"]


def test_manufacturer_response_uses_existing_schema():
    provider, client = make_provider(dumps({"response_summary": "ok"}))
    payload = provider.analyze_manufacturer_response([{"question_id": "Q1"}], "回答文")
    assert payload["response_summary"] == "ok"
    assert client.posts[0]["payload"]["format"] == json_schema_for(ManufacturerResponseAnalysis)


def test_invalid_schema_raises_provider_error():
    provider, _ = make_provider(dumps({"requirements": "not-a-list"}))
    with pytest.raises(ProviderError, match="スキーマ") as raised:
        provider.analyze_technical_case("管内点検")
    assert raised.value.error_code == ERROR_SCHEMA


def test_invalid_json_raises_provider_error():
    provider, _ = make_provider("Thinking...\nnot json")
    with pytest.raises(ProviderError, match="JSON") as raised:
        provider.analyze_technical_case("管内点検")
    assert raised.value.error_code == ERROR_INVALID_JSON


def test_connection_failure_raises_provider_error_without_fallback(monkeypatch):
    monkeypatch.setenv("TECHNICAL_CASE_PROVIDER", "ollama")
    client = FakeOllamaClient(
        chat_response=ProviderError("Ollamaに接続できません。ローカルサーバーが起動しているか確認してください。", error_code=ERROR_UNREACHABLE)
    )
    provider = OllamaTechnicalCaseProvider(client=client)
    with pytest.raises(ProviderError) as raised:
        provider.analyze_technical_case("管内点検")
    assert raised.value.error_code == ERROR_UNREACHABLE

    from agents.technical_case_agent import run_technical_case_analysis
    from llm.mock_provider import DEFAULT_MOCK_PAYLOAD

    failing = FakeOllamaClient(
        chat_response=ProviderError("Ollamaに接続できません。ローカルサーバーが起動しているか確認してください。", error_code=ERROR_UNREACHABLE)
    )
    run = run_technical_case_analysis(
        "案件",
        "顧客",
        None,
        "問い合わせ",
        provider=OllamaTechnicalCaseProvider(client=failing),
    )
    assert run.success is False
    assert run.provider_name == "ollama"
    assert run.analysis_json is None
    assert run.case_summary != DEFAULT_MOCK_PAYLOAD["case_summary"]


def test_thinking_is_not_included_in_result_or_logs(caplog):
    caplog.set_level(logging.INFO)
    content = dumps({"case_summary": "管内点検", "thinking": "should be ignored by extra=ignore"})
    provider, _ = make_provider(content, thinking="IHI confidential ATEX reasoning")
    payload = provider.analyze_technical_case("顧客の生メール全文", customer_name="秘密顧客")
    assert payload["case_summary"] == "管内点検"
    assert "thinking" not in payload
    assert "reasoning" not in payload
    assert "IHI confidential" not in caplog.text
    assert "ATEX reasoning" not in caplog.text
    assert "秘密顧客" not in caplog.text
    assert "生メール" not in caplog.text
    assert "provider=ollama" in caplog.text
    assert "model=qwen3.5:9b" in caplog.text
    assert provider.last_usage.input_tokens == 21
    assert provider.last_usage.output_tokens == 9
    assert isinstance(provider.last_usage, TokenUsageRecord)


def test_no_api_key_required(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("TECHNICAL_CASE_PROVIDER", "ollama")
    provider, _client = make_provider(dumps({"ok": True}))
    result = OllamaTechnicalCaseProvider(client=_client).test_connection()
    assert result.success is True
    assert result.provider == "ollama"


def test_connection_test_does_not_send_customer_data():
    provider, client = make_provider(dumps({"ok": True}))
    result = provider.test_connection()
    request = client.posts[0]["payload"]
    content = request["messages"][1]["content"]
    assert result.success is True
    assert request["format"] == json_schema_for(ConnectionTestOutput)
    assert content == CONNECTION_TEST_USER_MESSAGE
    assert "customer_name" not in content
    assert "inquiry_text" not in content
    assert "案件" not in content
    assert request["think"] is False


def test_connection_test_requires_installed_model():
    client = FakeOllamaClient(
        chat_response=chat_payload(dumps({"ok": True})),
        tags_response={"models": [{"name": "llama3.2:3b"}]},
    )
    provider = OllamaTechnicalCaseProvider(client=client, model=DEFAULT_MODEL)
    with pytest.raises(ProviderError) as raised:
        provider.test_connection()
    assert raised.value.error_code == ERROR_MODEL_MISSING
    assert not client.posts


def test_connection_test_via_factory_does_not_fallback(monkeypatch):
    monkeypatch.setenv("TECHNICAL_CASE_PROVIDER", "ollama")
    result = run_provider_connection_test(
        OllamaTechnicalCaseProvider(
            client=FakeOllamaClient(
                tags_response=ProviderError(
                    "Ollamaに接続できません。ローカルサーバーが起動しているか確認してください。",
                    error_code=ERROR_UNREACHABLE,
                )
            )
        )
    )
    assert result.success is False
    assert result.provider == "ollama"
    assert result.error_code == ERROR_UNREACHABLE


def test_runtime_status_for_ollama(monkeypatch):
    monkeypatch.setenv("TECHNICAL_CASE_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3.5:9b")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    status = get_provider_runtime_status()
    assert status["provider_label"] == "Local AI (Ollama)"
    assert status["model"] == "qwen3.5:9b"
    assert status["api_key_configured"] is False
    assert status["connection"] == "disconnected"
    assert status["supports_connection_test"] is True
    assert status["show_fallbacks"] is False
    assert status["connection_test_button_key"] == "ollama_connection_test"
