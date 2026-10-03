from __future__ import annotations

from json import JSONDecodeError, dumps, loads
import logging
import os
import socket
import time
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, ValidationError

from llm.analysis_schema import TechnicalCaseAnalysisResponse
from llm.provider import (
    CONNECTION_CONNECTED,
    CONNECTION_ERROR,
    ConnectionTestResult,
    ProviderError,
    TechnicalCaseProvider,
    attach_approved_facts,
    record_runtime_status,
)
from llm.usage import TokenUsageRecord, utc_now_iso
from models import ManufacturerResponseAnalysis

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen3.5:9b"
DEFAULT_TIMEOUT_SECONDS = 180
TAGS_TIMEOUT_SECONDS = 10
TEMPERATURE = 0
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}
CHAT_PATH = "/api/chat"
TAGS_PATH = "/api/tags"
ERROR_UNREACHABLE = "OLLAMA_UNREACHABLE"
ERROR_MODEL_MISSING = "OLLAMA_MODEL_MISSING"
ERROR_TIMEOUT = "OLLAMA_TIMEOUT"
ERROR_INVALID_JSON = "OLLAMA_INVALID_JSON"
ERROR_SCHEMA = "OLLAMA_SCHEMA_VALIDATION"
ERROR_INTERRUPTED = "OLLAMA_INTERRUPTED"
ERROR_REMOTE_HOST = "OLLAMA_REMOTE_HOST"
CONNECTION_TEST_USER_MESSAGE = (
    "Deep Trekker connection test. Reply with ok=true. "
    "Do not use customer or case data."
)
CONNECTION_TEST_SYSTEM_PROMPT = "Return structured output only. Do not include thinking."

logger = logging.getLogger(__name__)


class ConnectionTestOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ok: bool = False


def configured_model() -> str:
    return (os.getenv("OLLAMA_MODEL") or "").strip() or DEFAULT_MODEL


def configured_timeout() -> float:
    raw = (os.getenv("OLLAMA_TIMEOUT_SECONDS") or "").strip()
    if not raw:
        return float(DEFAULT_TIMEOUT_SECONDS)
    try:
        timeout = float(raw)
    except ValueError as error:
        raise ProviderError("OLLAMA_TIMEOUT_SECONDS is invalid") from error
    if timeout <= 0:
        raise ProviderError("OLLAMA_TIMEOUT_SECONDS must be greater than 0")
    return timeout


def configured_base_url() -> str:
    raw = (os.getenv("OLLAMA_BASE_URL") or "").strip() or DEFAULT_BASE_URL
    return validate_local_base_url(raw)


def validate_local_base_url(raw: str) -> str:
    parsed = urlparse(raw)
    host = (parsed.hostname or "").strip().lower()
    if parsed.scheme not in {"http", "https"} or host not in ALLOWED_HOSTS:
        raise ProviderError(
            "Ollamaはlocalhostのみ接続できます",
            error_code=ERROR_REMOTE_HOST,
        )
    return raw.rstrip("/")


def json_schema_for(model: type[BaseModel]) -> dict:
    return model.model_json_schema()


def tokens_from_ollama_response(payload: dict) -> tuple[Optional[int], Optional[int]]:
    return payload.get("prompt_eval_count"), payload.get("eval_count")


class UrllibOllamaClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = validate_local_base_url(base_url)
        self.timeout = timeout

    def get_json(self, path: str, timeout: Optional[float] = None) -> dict:
        return self._request("GET", path, None, timeout=timeout)

    def post_json(self, path: str, payload: dict, timeout: Optional[float] = None) -> dict:
        return self._request("POST", path, payload, timeout=timeout)

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[dict],
        timeout: Optional[float] = None,
    ) -> dict:
        url = f"{self.base_url}{path}"
        body = None if payload is None else dumps(payload).encode("utf-8")
        request = Request(
            url,
            data=body,
            method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=timeout if timeout is not None else self.timeout) as response:
                raw = response.read().decode("utf-8")
                http_status = getattr(response, "status", 200)
        except HTTPError as error:
            http_status = getattr(error, "code", None)
            raw = error.read().decode("utf-8", errors="replace") if error.fp else ""
            message = _safe_ollama_error_message(raw) or str(error)
            if http_status == 404:
                raise ProviderError(
                    f"指定モデルがOllamaにありません: {message}",
                    error_code=ERROR_MODEL_MISSING,
                ) from error
            raise ProviderError(
                f"Ollama API error ({http_status})",
                error_code=ERROR_UNREACHABLE,
            ) from error
        except socket.timeout as error:
            raise ProviderError(
                "Ollamaの応答がタイムアウトしました",
                error_code=ERROR_TIMEOUT,
            ) from error
        except URLError as error:
            reason = getattr(error, "reason", error)
            if isinstance(reason, socket.timeout):
                raise ProviderError(
                    "Ollamaの応答がタイムアウトしました",
                    error_code=ERROR_TIMEOUT,
                ) from error
            raise ProviderError(
                "Ollamaに接続できません。ローカルサーバーが起動しているか確認してください。",
                error_code=ERROR_UNREACHABLE,
            ) from error
        except TimeoutError as error:
            raise ProviderError(
                "Ollamaの応答がタイムアウトしました",
                error_code=ERROR_TIMEOUT,
            ) from error
        try:
            decoded = loads(raw) if raw else {}
        except JSONDecodeError as error:
            raise ProviderError(
                "Ollamaの応答がJSONではありません",
                error_code=ERROR_INVALID_JSON,
            ) from error
        if not isinstance(decoded, dict):
            raise ProviderError(
                "Ollamaの応答がJSONではありません",
                error_code=ERROR_INVALID_JSON,
            )
        decoded.setdefault("_http_status", http_status)
        return decoded


def _safe_ollama_error_message(raw: str) -> str:
    try:
        payload = loads(raw)
    except JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    return error if isinstance(error, str) else ""


def _model_names(tags: dict) -> set[str]:
    names = set()
    for item in tags.get("models") or []:
        if not isinstance(item, dict):
            continue
        for key in ("name", "model"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                names.add(value.strip())
    return names


def _assistant_content(payload: dict) -> Any:
    message = payload.get("message")
    if not isinstance(message, dict):
        raise ProviderError(
            "Ollamaの応答がJSONではありません",
            error_code=ERROR_INVALID_JSON,
        )
    if payload.get("done") is False or payload.get("done_reason") in {"length", "unload"}:
        raise ProviderError(
            "Ollamaの生成が中断されました",
            error_code=ERROR_INTERRUPTED,
        )
    return message.get("content")


class OllamaTechnicalCaseProvider(TechnicalCaseProvider):
    name = "ollama"

    def __init__(
        self,
        client: Optional[Any] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self._injected_client = client is not None
        self._client = client
        self._model = (model or "").strip() or configured_model()
        self._base_url = validate_local_base_url(base_url) if base_url else None
        self._timeout = float(timeout) if timeout is not None else None
        self.last_usage: Optional[TokenUsageRecord] = None

    @property
    def model(self) -> str:
        return self._model

    @property
    def fallbacks_enabled(self) -> bool:
        return False

    @property
    def base_url(self) -> str:
        return self._base_url or configured_base_url()

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
        self._require_model_available()
        payload = self._parse(
            CONNECTION_TEST_SYSTEM_PROMPT,
            CONNECTION_TEST_USER_MESSAGE,
            ConnectionTestOutput,
            operation="connection_test",
        )
        if not payload.get("ok"):
            raise ProviderError("Ollama connection test did not return ok=true")
        return ConnectionTestResult(
            success=True,
            provider=self.name,
            model=self._model,
            fallbacks_enabled=False,
            usage=self.last_usage,
        )

    def _client_or_create(self):
        if self._client is None:
            self._client = UrllibOllamaClient(self.base_url, self._timeout or configured_timeout())
        return self._client

    def _require_model_available(self) -> None:
        client = self._client_or_create()
        tags = client.get_json(TAGS_PATH, timeout=min(self._timeout or configured_timeout(), TAGS_TIMEOUT_SECONDS))
        if self._model not in _model_names(tags):
            raise ProviderError(
                f"指定モデルがOllamaにありません: {self._model}",
                error_code=ERROR_MODEL_MISSING,
            )

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
            "stream": False,
            "think": False,
            "format": json_schema_for(output_format),
            "options": {"temperature": TEMPERATURE},
            "messages": [
                {"role": "system", "content": system_prompt or ""},
                {"role": "user", "content": content},
            ],
        }
        started = time.perf_counter()
        http_status = None
        success = False
        input_tokens = None
        output_tokens = None
        try:
            client = self._client_or_create()
            response = client.post_json(CHAT_PATH, request)
            http_status = response.get("_http_status", 200)
            input_tokens, output_tokens = tokens_from_ollama_response(response)
            parsed = _validate_structured_output(response, output_format)
            success = True
            return parsed.model_dump(mode="json")
        except ProviderError:
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
    raw_content = _assistant_content(response)
    if isinstance(raw_content, dict):
        candidate = raw_content
    elif isinstance(raw_content, str):
        try:
            candidate = loads(raw_content)
        except JSONDecodeError as error:
            raise ProviderError(
                "Ollamaの応答がJSONではありません",
                error_code=ERROR_INVALID_JSON,
            ) from error
    else:
        raise ProviderError(
            "Ollamaの応答がJSONではありません",
            error_code=ERROR_INVALID_JSON,
        )
    if not isinstance(candidate, dict):
        raise ProviderError(
            "Ollamaの応答がJSONではありません",
            error_code=ERROR_INVALID_JSON,
        )
    try:
        return output_format.model_validate(candidate)
    except ValidationError as error:
        raise ProviderError(
            "Ollamaの応答がスキーマと一致しません",
            error_code=ERROR_SCHEMA,
        ) from error
