from json import dumps

from scripts.eval_ihi_tech_001_gemini_mr_only import MAX_API_CALLS, run_mr_only
from llm.gemini_provider import ERROR_HTTP, ERROR_RATE_LIMIT, GeminiTechnicalCaseProvider
from llm.provider import ProviderError
from models import ManufacturerResponseAnalysis


class CountingClient:
    def __init__(self, response=None):
        self.response = response
        self.posts = []

    def post_interaction(self, payload):
        self.posts.append(payload)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class CountingProvider(GeminiTechnicalCaseProvider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.technical_case_calls = 0
        self.manufacturer_response_calls = 0

    def analyze_technical_case(self, *args, **kwargs):
        self.technical_case_calls += 1
        return super().analyze_technical_case(*args, **kwargs)

    def analyze_manufacturer_response(self, *args, **kwargs):
        self.manufacturer_response_calls += 1
        return super().analyze_manufacturer_response(*args, **kwargs)


def _analysis_payload():
    return ManufacturerResponseAnalysis(
        response_summary="ok",
        matches=[],
        unmatched_information=[],
        overall_follow_up_required=True,
    ).model_dump(mode="json")


def test_mr_only_runner_makes_max_one_call_on_success():
    client = CountingClient(
        {
            "output_text": dumps(_analysis_payload()),
            "usage": {"input_tokens": 3, "output_tokens": 2},
            "_http_status": 200,
        }
    )
    provider = CountingProvider(client=client, model="gemini-3.8-flash")
    result = run_mr_only(provider)
    assert MAX_API_CALLS == 1
    assert provider.technical_case_calls == 0
    assert provider.manufacturer_response_calls == 1
    assert len(client.posts) == 1
    assert result["api_calls"] == 1
    assert result["retry"] == 0
    assert result["fallback"] == 0
    assert result["provider_report"]["analysis_type"] == "manufacturer_response"
    assert result["provider_report"]["thinking_leak"] is False
    assert "GEMINI_API_KEY" not in dumps(result)


def test_mr_only_runner_does_not_retry_429():
    client = CountingClient(ProviderError("Gemini API error (429): Rate limit exceeded", error_code=ERROR_RATE_LIMIT))
    provider = CountingProvider(client=client, model="gemini-3.8-flash")
    result = run_mr_only(provider)
    assert provider.technical_case_calls == 0
    assert provider.manufacturer_response_calls == 1
    assert len(client.posts) == 1
    assert result["success"] is False
    assert result["retry"] == 0
    assert result["fallback"] == 0
    assert result["error_code"] == ERROR_RATE_LIMIT
    assert "GEMINI_API_KEY" not in dumps(result)


def test_mr_only_runner_does_not_retry_503():
    client = CountingClient(ProviderError("Gemini API error (503): high demand", error_code=ERROR_HTTP))
    provider = CountingProvider(client=client, model="gemini-3.8-flash")
    result = run_mr_only(provider)
    assert provider.technical_case_calls == 0
    assert provider.manufacturer_response_calls == 1
    assert len(client.posts) == 1
    assert result["success"] is False
    assert result["retry"] == 0
    assert result["fallback"] == 0
    assert result["error_code"] == ERROR_HTTP
    assert "GEMINI_API_KEY" not in dumps(result)


def test_mr_only_runner_stops_without_api_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    result = run_mr_only()
    dumped = dumps(result)
    assert result["success"] is False
    assert result["error_code"] == "MISSING_API_KEY"
    assert result["api_calls"] == 0
    assert result["error_message"] == "GEMINI_API_KEY is not configured"
    assert "AIza" not in dumped
    assert "=" not in dumped
