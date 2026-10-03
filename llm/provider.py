from abc import ABC, abstractmethod
from dataclasses import dataclass
import os
from typing import Optional

from llm.usage import TokenUsageRecord

CONNECTION_DISCONNECTED = "disconnected"
CONNECTION_CONNECTED = "connected"
CONNECTION_ERROR = "error"
ERROR_MISSING_API_KEY = "MISSING_API_KEY"

_RUNTIME = {
    "connection": CONNECTION_DISCONNECTED,
    "last_usage": None,
    "last_error_code": None,
}


class ProviderError(Exception):
    def __init__(self, message: str, *, error_code: Optional[str] = None) -> None:
        super().__init__(message)
        self.error_code = error_code


class TechnicalCaseProvider(ABC):
    name = "base"

    @abstractmethod
    def analyze_technical_case(
        self,
        inquiry_text: Optional[str],
        case_name: Optional[str] = None,
        customer_name: Optional[str] = None,
        end_user_name: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> dict:
        raise NotImplementedError

    @abstractmethod
    def analyze_manufacturer_response(
        self,
        questions: list,
        response_text: Optional[str],
        system_prompt: Optional[str] = None,
    ) -> dict:
        raise NotImplementedError

    def test_connection(self) -> "ConnectionTestResult":
        raise ProviderError("Connection test is not available for this provider")


@dataclass
class ConnectionTestResult:
    success: bool
    provider: str
    model: Optional[str]
    fallbacks_enabled: bool
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    usage: Optional[TokenUsageRecord] = None


def selected_provider_name(provider_name: Optional[str] = None) -> str:
    selected = (provider_name or os.getenv("TECHNICAL_CASE_PROVIDER") or "mock")
    return selected.strip().lower()


def get_technical_case_provider(
    provider_name: Optional[str] = None,
) -> TechnicalCaseProvider:
    from llm.mock_provider import MockTechnicalCaseProvider

    selected = selected_provider_name(provider_name)
    if selected == "mock":
        return MockTechnicalCaseProvider()
    if selected == "ollama":
        from llm.ollama_provider import OllamaTechnicalCaseProvider

        return OllamaTechnicalCaseProvider()
    if selected == "gemini":
        from llm.gemini_provider import GeminiTechnicalCaseProvider

        return GeminiTechnicalCaseProvider()
    if selected == "anthropic":
        from llm.anthropic_provider import AnthropicTechnicalCaseProvider

        return AnthropicTechnicalCaseProvider()

    raise ProviderError(f"Provider '{selected}' is not available")


def record_runtime_status(
    *,
    connection: str,
    usage: Optional[TokenUsageRecord] = None,
    error_code: Optional[str] = None,
) -> None:
    _RUNTIME["connection"] = connection
    _RUNTIME["last_usage"] = usage
    _RUNTIME["last_error_code"] = error_code


def reset_runtime_status() -> None:
    record_runtime_status(connection=CONNECTION_DISCONNECTED)


def get_provider_runtime_status() -> dict:
    selected = selected_provider_name()
    if selected == "anthropic":
        from llm.anthropic_provider import (
            configured_model,
            fallbacks_enabled,
            has_api_key,
        )

        return {
            "provider_id": "anthropic",
            "provider_label": "Claude",
            "model": configured_model(),
            "fallbacks_enabled": fallbacks_enabled(),
            "api_key_configured": has_api_key(),
            "connection": _RUNTIME["connection"],
            "last_usage": _RUNTIME["last_usage"],
            "supports_connection_test": True,
            "show_fallbacks": True,
            "connection_test_button_key": "claude_connection_test",
        }
    if selected == "ollama":
        from llm.ollama_provider import configured_model as ollama_model

        return {
            "provider_id": "ollama",
            "provider_label": "Local AI (Ollama)",
            "model": ollama_model(),
            "fallbacks_enabled": False,
            "api_key_configured": False,
            "connection": _RUNTIME["connection"],
            "last_usage": _RUNTIME["last_usage"],
            "supports_connection_test": True,
            "show_fallbacks": False,
            "connection_test_button_key": "ollama_connection_test",
        }
    if selected == "gemini":
        from llm.gemini_provider import configured_model as gemini_model
        from llm.gemini_provider import has_api_key as gemini_has_key

        return {
            "provider_id": "gemini",
            "provider_label": "Gemini",
            "model": gemini_model(),
            "fallbacks_enabled": False,
            "api_key_configured": gemini_has_key(),
            "connection": _RUNTIME["connection"],
            "last_usage": _RUNTIME["last_usage"],
            "supports_connection_test": True,
            "show_fallbacks": False,
            "connection_test_button_key": "gemini_connection_test",
        }
    return {
        "provider_id": selected if selected == "mock" else selected,
        "provider_label": "Mock" if selected == "mock" else selected,
        "model": None,
        "fallbacks_enabled": False,
        "api_key_configured": False,
        "connection": CONNECTION_DISCONNECTED,
        "last_usage": None,
        "supports_connection_test": False,
        "show_fallbacks": False,
        "connection_test_button_key": None,
    }


def run_provider_connection_test(
    provider: Optional[TechnicalCaseProvider] = None,
) -> ConnectionTestResult:
    active = provider or get_technical_case_provider()
    try:
        result = active.test_connection()
    except ProviderError as error:
        result = ConnectionTestResult(
            success=False,
            provider=active.name,
            model=getattr(active, "model", None),
            fallbacks_enabled=bool(getattr(active, "fallbacks_enabled", False)),
            error_code=getattr(error, "error_code", None),
            error_message=str(error),
        )
    record_runtime_status(
        connection=CONNECTION_CONNECTED if result.success else CONNECTION_ERROR,
        usage=result.usage,
        error_code=result.error_code,
    )
    return result
