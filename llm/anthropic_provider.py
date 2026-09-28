from __future__ import annotations

from json import dumps
import logging
import os
import re
import time
from typing import Optional

import anthropic

from llm.analysis_schema import TechnicalCaseAnalysisResponse
from llm.provider import (
    CONNECTION_CONNECTED,
    CONNECTION_ERROR,
    ERROR_MISSING_API_KEY,
    ConnectionTestResult,
    ProviderError,
    TechnicalCaseProvider,
    record_runtime_status,
)
from llm.usage import TokenUsageRecord, tokens_from_response, utc_now_iso
from models import ManufacturerResponseAnalysis
from pydantic import BaseModel, ConfigDict

DEFAULT_MODEL = "claude-opus-5"
MAX_TOKENS = 16000
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MISSING_API_KEY_MESSAGE = "Claude APIキーが設定されていません"
CONNECTION_TEST_USER_MESSAGE = (
    "Deep Trekker connection test. Reply with ok=true. "
    "Do not use customer or case data."
)
CONNECTION_TEST_SYSTEM_PROMPT = "Return structured output only."
_SECRET_RE = re.compile(r"sk-ant-[A-Za-z0-9_-]+")

logger = logging.getLogger(__name__)


class ConnectionTestOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ok: bool = False


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def fallbacks_enabled() -> bool:
    return env_flag("ANTHROPIC_ENABLE_FALLBACKS", default=False)


def configured_model() -> str:
    return (os.getenv("ANTHROPIC_MODEL") or "").strip() or DEFAULT_MODEL


def has_api_key() -> bool:
    return bool((os.getenv("ANTHROPIC_API_KEY") or "").strip())


def redact_secrets(text: str) -> str:
    return _SECRET_RE.sub("[REDACTED]", text)


class AnthropicTechnicalCaseProvider(TechnicalCaseProvider):
    name = "anthropic"

    def __init__(
        self,
        client: Optional[anthropic.Anthropic] = None,
        model: Optional[str] = None,
        enable_fallbacks: Optional[bool] = None,
    ) -> None:
        self._injected_client = client is not None
        self._client = client
        self._model = (model or "").strip() or configured_model()
        self._enable_fallbacks = fallbacks_enabled() if enable_fallbacks is None else bool(enable_fallbacks)
        self.last_usage: Optional[TokenUsageRecord] = None

    @property
    def model(self) -> str:
        return self._model

    @property
    def fallbacks_enabled(self) -> bool:
        return self._enable_fallbacks

    def analyze_technical_case(
        self,
        inquiry_text: Optional[str],
        case_name: Optional[str] = None,
        customer_name: Optional[str] = None,
        end_user_name: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> dict:
        user_input = {
            "case_name": case_name,
            "customer_name": customer_name,
            "end_user_name": end_user_name,
            "inquiry_text": inquiry_text,
        }
        return self._parse(system_prompt, user_input, TechnicalCaseAnalysisResponse, operation="analyze_technical_case")

    def analyze_manufacturer_response(
        self,
        questions: list,
        response_text: Optional[str],
        system_prompt: Optional[str] = None,
    ) -> dict:
        user_input = {
            "questions": questions,
            "manufacturer_response_text": response_text,
        }
        return self._parse(
            system_prompt,
            user_input,
            ManufacturerResponseAnalysis,
            operation="analyze_manufacturer_response",
        )

    def test_connection(self) -> ConnectionTestResult:
        payload = self._parse(
            CONNECTION_TEST_SYSTEM_PROMPT,
            CONNECTION_TEST_USER_MESSAGE,
            ConnectionTestOutput,
            operation="connection_test",
        )
        if not payload.get("ok"):
            raise ProviderError("Claude connection test did not return ok=true")
        return ConnectionTestResult(
            success=True,
            provider=self.name,
            model=self._model,
            fallbacks_enabled=self._enable_fallbacks,
            usage=self.last_usage,
        )

    def _client_or_create(self):
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def _require_api_key(self) -> None:
        if self._injected_client:
            return
        if not has_api_key():
            raise ProviderError(MISSING_API_KEY_MESSAGE, error_code=ERROR_MISSING_API_KEY)

    def _parse(self, system_prompt: Optional[str], user_input, output_format: type, *, operation: str) -> dict:
        content = user_input if isinstance(user_input, str) else dumps(user_input, ensure_ascii=False, indent=2)
        request = {
            "model": self._model,
            "max_tokens": MAX_TOKENS,
            "system": system_prompt or "",
            "messages": [{"role": "user", "content": content}],
            "output_format": output_format,
        }
        if self._enable_fallbacks:
            request["fallbacks"] = "default"
            request["betas"] = [FALLBACK_BETA]
        started = time.perf_counter()
        http_status = None
        success = False
        input_tokens = None
        output_tokens = None
        try:
            self._require_api_key()
            client = self._client_or_create()
            if self._enable_fallbacks:
                response = client.beta.messages.parse(**request)
            else:
                response = client.messages.parse(**request)
            http_status = 200
            input_tokens, output_tokens = tokens_from_response(response)
            if getattr(response, "stop_reason", None) == "refusal":
                raise ProviderError("Anthropic API declined the request (refusal)")
            if getattr(response, "stop_reason", None) == "max_tokens":
                raise ProviderError("Anthropic API response was cut off (max_tokens)")
            parsed = getattr(response, "parsed_output", None)
            if parsed is None:
                raise ProviderError("Anthropic API returned no structured output")
            success = True
            return parsed.model_dump(mode="json")
        except ProviderError:
            raise
        except anthropic.APIConnectionError as error:
            raise ProviderError(f"Anthropic API connection failed: {redact_secrets(str(error))}") from error
        except anthropic.APIStatusError as error:
            http_status = getattr(error, "status_code", None)
            message = redact_secrets(getattr(error, "message", None) or str(error))
            raise ProviderError(f"Anthropic API error ({http_status}): {message}") from error
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            usage = TokenUsageRecord(
                provider=self.name,
                model=self._model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                timestamp=utc_now_iso(),
                case_id=None,
                operation=operation,
                success=success,
                http_status=http_status,
                duration_ms=duration_ms,
                fallbacks_enabled=self._enable_fallbacks,
            )
            self.last_usage = usage
            record_runtime_status(
                connection=CONNECTION_CONNECTED if success else CONNECTION_ERROR,
                usage=usage,
            )
            logger.info(
                "provider_call provider=%s model=%s operation=%s success=%s http_status=%s duration_ms=%s "
                "input_tokens=%s output_tokens=%s fallbacks=%s",
                usage.provider,
                usage.model,
                usage.operation,
                usage.success,
                usage.http_status,
                usage.duration_ms,
                usage.input_tokens,
                usage.output_tokens,
                usage.fallbacks_enabled,
            )
