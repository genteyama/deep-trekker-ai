from __future__ import annotations

from json import JSONDecodeError, dumps, loads
import logging
import os
import re
import socket
import time
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, ValidationError

from llm.analysis_schema import TechnicalCaseAnalysisResponse
from llm.provider import (
    CONNECTION_CONNECTED,
    CONNECTION_ERROR,
    ERROR_MISSING_API_KEY,
    ConnectionTestResult,
    ProviderError,
    TechnicalCaseProvider,
    attach_approved_facts,
    record_runtime_status,
)
from llm.usage import TokenUsageRecord, utc_now_iso
from models import ManufacturerResponseAnalysis

DEFAULT_MODEL = "gemini-3.8-flash"
DEFAULT_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"
DEFAULT_TIMEOUT_SECONDS = 180
API_REVISION = "2026-05-20"
THINKING_LEVEL = "medium"
MISSING_API_KEY_MESSAGE = "Gemini APIキーが設定されていません"
CONNECTION_TEST_USER_MESSAGE = (
    "Deep Trekker connection test. Reply with ok=true. "
    "Do not use customer or case data."
)
CONNECTION_TEST_SYSTEM_PROMPT = "Return structured output only."
THOUGHT_STEP_TYPES = {"thought", "thinking", "reasoning"}
ERROR_AUTH = "GEMINI_AUTH"
ERROR_INVALID_JSON = "GEMINI_INVALID_JSON"
ERROR_SCHEMA = "GEMINI_SCHEMA_VALIDATION"
ERROR_HTTP = "GEMINI_HTTP"
ERROR_RATE_LIMIT = "GEMINI_RATE_LIMIT"
_SECRET_RE = re.compile(r"(AIza[0-9A-Za-z_-]{10,}|GEMINI_API_KEY\s*=\s*\S+)")

logger = logging.getLogger(__name__)


class ConnectionTestOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ok: bool = False


def configured_model() -> str:
    return (os.getenv("GEMINI_MODEL") or "").strip() or DEFAULT_MODEL


def configured_endpoint() -> str:
    return (os.getenv("GEMINI_ENDPOINT") or "").strip() or DEFAULT_ENDPOINT


def configured_timeout() -> float:
    raw = (os.getenv("GEMINI_TIMEOUT_SECONDS") or "").strip()
    if not raw:
        return float(DEFAULT_TIMEOUT_SECONDS)
    try:
        timeout = float(raw)
    except ValueError as error:
        raise ProviderError("GEMINI_TIMEOUT_SECONDS is invalid") from error
    if timeout <= 0:
        raise ProviderError("GEMINI_TIMEOUT_SECONDS must be greater than 0")
    return timeout


def has_api_key() -> bool:
    return bool((os.getenv("GEMINI_API_KEY") or "").strip())


def redact_secrets(text: str) -> str:
    return _SECRET_RE.sub("[REDACTED]", text or "")


def json_schema_for(model: type[BaseModel]) -> dict:
    return model.model_json_schema()


def tokens_from_gemini_payload(payload: dict) -> tuple[Optional[int], Optional[int]]:
    usage = payload.get("usage") or payload.get("usage_metadata") or {}
    if not isinstance(usage, dict):
        return None, None
    input_tokens = (
        usage.get("input_tokens")
        or usage.get("prompt_tokens")
        or usage.get("prompt_token_count")
        or usage.get("total_input_tokens")
    )
    output_tokens = (
        usage.get("output_tokens")
        or usage.get("candidates_tokens")
        or usage.get("candidates_token_count")
        or usage.get("total_output_tokens")
    )
    return input_tokens, output_tokens


def _step_text(step: dict) -> str:
    if isinstance(step.get("text"), str) and step["text"].strip():
        return step["text"]
    chunks = []
    content = step.get("content")
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        for part in content:
            if not isinstance(part, dict):
                continue
            part_type = (part.get("type") or "").lower()
            if part_type in THOUGHT_STEP_TYPES:
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text)
    return "\n".join(chunks)


def extract_structured_text(payload: dict) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text
    collected = ""
    for collection_key in ("outputs", "steps"):
        for step in payload.get(collection_key) or []:
            if not isinstance(step, dict):
                continue
            step_type = (step.get("type") or "").lower()
            if step_type in THOUGHT_STEP_TYPES:
                continue
            text = _step_text(step)
            if text.strip():
                collected = text
    return collected


class UrllibGeminiClient:
    def __init__(self, endpoint: str, api_key: str, timeout: float) -> None:
        self.endpoint = endpoint
        self._api_key = api_key
        self.timeout = timeout

    def post_interaction(self, payload: dict) -> dict:
        body = dumps(payload).encode("utf-8")
        request = Request(
            self.endpoint,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "x-goog-api-key": self._api_key,
                "Api-Revision": API_REVISION,
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
                http_status = getattr(response, "status", 200)
        except HTTPError as error:
            http_status = getattr(error, "code", None)
            raw = error.read().decode("utf-8", errors="replace") if error.fp else ""
            message = redact_secrets(_safe_error_message(raw) or str(error))
            if http_status in {401, 403}:
                code = ERROR_AUTH
            elif http_status == 429:
                code = ERROR_RATE_LIMIT
            else:
                code = ERROR_HTTP
            raise ProviderError(
                f"Gemini API error ({http_status}): {message}",
                error_code=code,
            ) from error
        except (socket.timeout, TimeoutError) as error:
            raise ProviderError("Gemini API request timed out", error_code=ERROR_HTTP) from error
        except URLError as error:
            raise ProviderError(
                f"Gemini API connection failed: {redact_secrets(str(error.reason))}",
                error_code=ERROR_HTTP,
            ) from error
        try:
            decoded = loads(raw) if raw else {}
        except JSONDecodeError as error:
            raise ProviderError(
                "Gemini API returned invalid JSON",
                error_code=ERROR_INVALID_JSON,
            ) from error
        if not isinstance(decoded, dict):
            raise ProviderError(
                "Gemini API returned invalid JSON",
                error_code=ERROR_INVALID_JSON,
            )
        decoded.setdefault("_http_status", http_status)
        return decoded


def _safe_error_message(raw: str) -> str:
    try:
        payload = loads(raw)
    except JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        return message if isinstance(message, str) else ""
    return error if isinstance(error, str) else ""


class GeminiTechnicalCaseProvider(TechnicalCaseProvider):
    name = "gemini"

    def __init__(
        self,
        client: Optional[Any] = None,
        model: Optional[str] = None,
        endpoint: Optional[str] = None,
    ) -> None:
        self._injected_client = client is not None
        self._client = client
        self._model = (model or "").strip() or configured_model()
        self._endpoint = (endpoint or "").strip() or configured_endpoint()
        self.last_usage: Optional[TokenUsageRecord] = None

    @property
    def model(self) -> str:
        return self._model

    @property
    def fallbacks_enabled(self) -> bool:
        return False

    def analyze_technical_case(
        self,
        inquiry_text: Optional[str],
        case_name: Optional[str] = None,
        customer_name: Optional[str] = None,
        end_user_name: Optional[str] = None,
        system_prompt: Optional[str] = None,
        approved_technical_facts: Optional[list] = None,
    ) -> dict:
        user_input = attach_approved_facts(
            {
                "case_name": case_name,
                "customer_name": customer_name,
                "end_user_name": end_user_name,
                "inquiry_text": inquiry_text,
            },
            approved_technical_facts,
        )
        return self._parse(
            system_prompt,
            user_input,
            TechnicalCaseAnalysisResponse,
            operation="analyze_technical_case",
        )

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
            raise ProviderError("Gemini connection test did not return ok=true")
        return ConnectionTestResult(
            success=True,
            provider=self.name,
            model=self._model,
            fallbacks_enabled=False,
            usage=self.last_usage,
        )

    def _client_or_create(self):
        if self._client is None:
            self._require_api_key()
            self._client = UrllibGeminiClient(
                self._endpoint,
                os.getenv("GEMINI_API_KEY") or "",
                configured_timeout(),
            )
        return self._client

    def _require_api_key(self) -> None:
        if self._injected_client:
            return
        if not has_api_key():
            raise ProviderError(MISSING_API_KEY_MESSAGE, error_code=ERROR_MISSING_API_KEY)

    def _parse(
        self,
        system_prompt: Optional[str],
        user_input,
        output_format: type[BaseModel],
        *,
        operation: str,
    ) -> dict:
        content = user_input if isinstance(user_input, str) else dumps(user_input, ensure_ascii=False, indent=2)
        request = {
            "model": self._model,
            "system_instruction": system_prompt or "",
            "input": content,
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": json_schema_for(output_format),
            },
            "generation_config": {
                "thinking_level": THINKING_LEVEL,
            },
        }
        started = time.perf_counter()
        http_status = None
        success = False
        input_tokens = None
        output_tokens = None
        try:
            self._require_api_key()
            response = self._client_or_create().post_interaction(request)
            http_status = response.get("_http_status", 200)
            input_tokens, output_tokens = tokens_from_gemini_payload(response)
            parsed = _validate_structured_output(response, output_format)
            success = True
            return parsed.model_dump(mode="json")
        except ProviderError as error:
            if error.args:
                error.args = (redact_secrets(str(error)),)
            raise
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
                fallbacks_enabled=False,
            )
            self.last_usage = usage
            record_runtime_status(
                connection=CONNECTION_CONNECTED if success else CONNECTION_ERROR,
                usage=usage,
            )
            logger.info(
                "provider_call provider=%s model=%s operation=%s success=%s http_status=%s "
                "duration_ms=%s input_tokens=%s output_tokens=%s fallbacks=%s",
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


def _validate_structured_output(response: dict, output_format: type[BaseModel]) -> BaseModel:
    raw_content = extract_structured_text(response)
    if not raw_content.strip():
        raise ProviderError(
            "Gemini API returned no structured output",
            error_code=ERROR_INVALID_JSON,
        )
    try:
        candidate = loads(raw_content)
    except JSONDecodeError as error:
        raise ProviderError(
            "Gemini API returned invalid JSON",
            error_code=ERROR_INVALID_JSON,
        ) from error
    if not isinstance(candidate, dict):
        raise ProviderError(
            "Gemini API returned invalid JSON",
            error_code=ERROR_INVALID_JSON,
        )
    try:
        return output_format.model_validate(candidate)
    except ValidationError as error:
        raise ProviderError(
            "Gemini API response did not match the schema",
            error_code=ERROR_SCHEMA,
        ) from error
