from __future__ import annotations

from json import dumps
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")
os.environ.setdefault("TECHNICAL_CASE_PROVIDER", "gemini")
os.environ.setdefault("GEMINI_MODEL", "gemini-3.8-flash")
os.environ.setdefault("GEMINI_TIMEOUT_SECONDS", "600")

from agents.technical_case_agent import run_manufacturer_response_analysis, run_technical_case_analysis
from data.golden_cases.ihi_tech_eval import (
    evaluate_initial_analysis,
    evaluate_manufacturer_response,
    find_thinking_leaks,
    load_ihi_tech_fixtures,
    manufacturer_questions_from_golden,
    manufacturer_response_fixture_text,
    usage_dict,
)
from llm.gemini_provider import GeminiTechnicalCaseProvider, has_api_key


def _safe_print(title: str, payload: dict) -> None:
    print(title)
    print(
        dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not has_api_key():
        print("GEMINI_API_KEY is not configured")
        return 1

    fixtures = load_ihi_tech_fixtures()
    case_input = fixtures["input"]
    provider = GeminiTechnicalCaseProvider()
    print("provider", provider.name)
    print("model", provider.model)

    inquiry_run = run_technical_case_analysis(
        case_input["case_name"],
        case_input["customer_name"],
        case_input.get("end_user_name"),
        case_input["customer_inquiry"],
        provider=provider,
        case_id=case_input["case_id"],
    )
    inquiry_usage = usage_dict(provider.last_usage)
    inquiry_eval = evaluate_initial_analysis(
        inquiry_run.analysis_json or {},
        fixtures["expected"],
        usage=inquiry_usage,
    )

    response_run = run_manufacturer_response_analysis(
        manufacturer_questions_from_golden(),
        manufacturer_response_fixture_text(),
        provider=provider,
    )
    response_usage = usage_dict(provider.last_usage)
    response_eval = evaluate_manufacturer_response(
        response_run.analysis_json or {},
        fixtures["response_expected"],
        usage=response_usage,
    )

    analysis = inquiry_run.analysis_json or {}
    response_analysis = response_run.analysis_json or {}
    _safe_print(
        "TECHNICAL_CASE_RUN",
        {
            "success": inquiry_run.success,
            "error_code": inquiry_run.error_code,
            "provider_name": inquiry_run.provider_name,
            "usage": inquiry_usage,
            "thinking_leaks": find_thinking_leaks(analysis),
            "structured_counts": {
                "requested_products": len(analysis.get("requested_products") or []),
                "requirements": len(analysis.get("requirements") or []),
                "customer_goal": len(analysis.get("customer_goal") or []),
                "existing_equipment": len(analysis.get("existing_equipment") or []),
                "manufacturer_questions": len(analysis.get("manufacturer_questions") or []),
                "ai_suggested_questions": sum(
                    1
                    for item in (analysis.get("manufacturer_questions") or [])
                    + (analysis.get("customer_questions") or [])
                    + (analysis.get("technical_questions") or [])
                    if item.get("classification") == "AI_SUGGESTED"
                    or item.get("source") == "AI_SUGGESTED"
                ),
            },
            "completeness_issues": [
                item.as_dict() if hasattr(item, "as_dict") else item
                for item in inquiry_run.completeness_issues
            ],
            "analysis": analysis,
            "evaluation": inquiry_eval.as_dict(),
        },
    )
    _safe_print(
        "MANUFACTURER_RESPONSE_RUN",
        {
            "success": response_run.success,
            "error_code": response_run.error_code,
            "provider_name": response_run.provider_name,
            "usage": response_usage,
            "thinking_leaks": find_thinking_leaks(response_analysis),
            "structured_counts": {
                "matches": len(response_analysis.get("matches") or []),
                "unmatched_information": len(response_analysis.get("unmatched_information") or []),
            },
            "completeness_issues": [
                item.as_dict() if hasattr(item, "as_dict") else item
                for item in response_run.completeness_issues
            ],
            "analysis": response_analysis,
            "evaluation": response_eval.as_dict(),
        },
    )
    return 0 if inquiry_run.success and response_run.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
