from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

from data.golden_cases.ihi_tech_eval import EvaluationReport, counts_by_class, find_thinking_leaks


@dataclass
class ProviderEvaluationReport:
    provider: Optional[str]
    model: Optional[str]
    case_id: Optional[str]
    analysis_type: str
    duration_ms: Optional[int] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    http_status: Optional[int] = None
    match_count: int = 0
    partial_count: int = 0
    missing_count: int = 0
    unsupported_count: int = 0
    product_scope_errors: int = 0
    topic_scope_errors: int = 0
    evidence_errors: int = 0
    human_review_required_count: int = 0
    thinking_leak: bool = False
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        payload = asdict(self)
        extra = payload.pop("extra") or {}
        payload.update(extra)
        return payload


def build_provider_evaluation_report(
    *,
    provider: Optional[str],
    model: Optional[str],
    case_id: Optional[str],
    analysis_type: str,
    usage: Optional[dict] = None,
    evaluation: Optional[EvaluationReport] = None,
    validation_results: Optional[list] = None,
    payload: Optional[dict] = None,
) -> ProviderEvaluationReport:
    usage = usage or {}
    counts = {"MATCH": 0, "PARTIAL": 0, "MISSING": 0, "UNSUPPORTED": 0}
    thinking_leak = False
    if evaluation is not None:
        counts = counts_by_class(evaluation.scores, evaluation.findings)
        thinking_leak = bool(evaluation.thinking_leaks)
    elif payload is not None:
        thinking_leak = bool(find_thinking_leaks(payload))

    product_errors = 0
    topic_errors = 0
    evidence_errors = 0
    review_required = 0
    for item in validation_results or []:
        reason = getattr(item, "reason", None) or (item.get("reason") if isinstance(item, dict) else None)
        if reason == "PRODUCT_SCOPE_MISMATCH":
            product_errors += 1
        elif reason == "TOPIC_SCOPE_MISMATCH":
            topic_errors += 1
        elif reason in {"EVIDENCE_MISSING", "EVIDENCE_NOT_IN_RESPONSE"}:
            evidence_errors += 1
        if getattr(item, "requires_human_review", False) or (
            isinstance(item, dict) and item.get("requires_human_review")
        ):
            review_required += 1

    return ProviderEvaluationReport(
        provider=provider or usage.get("provider"),
        model=model or usage.get("model"),
        case_id=case_id,
        analysis_type=analysis_type,
        duration_ms=usage.get("duration_ms"),
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        http_status=usage.get("http_status"),
        match_count=counts["MATCH"],
        partial_count=counts["PARTIAL"],
        missing_count=counts["MISSING"],
        unsupported_count=counts["UNSUPPORTED"],
        product_scope_errors=product_errors,
        topic_scope_errors=topic_errors,
        evidence_errors=evidence_errors,
        human_review_required_count=review_required,
        thinking_leak=thinking_leak,
    )
