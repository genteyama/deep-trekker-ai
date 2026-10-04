from llm.evaluation_report import ProviderEvaluationReport, build_provider_evaluation_report
from llm.evidence_guard import EvidenceCheck, REASON_PRODUCT_SCOPE_MISMATCH, REASON_TOPIC_SCOPE_MISMATCH


def test_provider_independent_evaluation_report():
    report = build_provider_evaluation_report(
        provider="ollama",
        model="qwen3.5:9b",
        case_id="IHI-TECH-001",
        analysis_type="manufacturer_response",
        usage={
            "duration_ms": 100,
            "input_tokens": 10,
            "output_tokens": 8,
            "http_status": 200,
        },
        validation_results=[
            EvidenceCheck(reason=REASON_PRODUCT_SCOPE_MISMATCH, requires_human_review=True),
            EvidenceCheck(reason=REASON_TOPIC_SCOPE_MISMATCH, requires_human_review=True),
            EvidenceCheck(reason="EVIDENCE_MISSING", requires_human_review=True),
        ],
        payload={"response_summary": "ok"},
    )
    assert isinstance(report, ProviderEvaluationReport)
    payload = report.as_dict()
    assert payload["provider"] == "ollama"
    assert payload["model"] == "qwen3.5:9b"
    assert payload["case_id"] == "IHI-TECH-001"
    assert payload["analysis_type"] == "manufacturer_response"
    assert payload["duration_ms"] == 100
    assert payload["input_tokens"] == 10
    assert payload["output_tokens"] == 8
    assert payload["http_status"] == 200
    assert payload["product_scope_errors"] == 1
    assert payload["topic_scope_errors"] == 1
    assert payload["evidence_errors"] == 1
    assert payload["human_review_required_count"] == 3
    assert payload["thinking_leak"] is False
