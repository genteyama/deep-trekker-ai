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

from agents.technical_case_agent import run_manufacturer_response_analysis
from data.golden_cases.ihi_tech_eval import (
    evaluate_manufacturer_response,
    find_thinking_leaks,
    load_ihi_tech_fixtures,
    manufacturer_questions_from_golden,
    manufacturer_response_fixture_text,
    usage_dict,
)
from llm.evaluation_report import build_provider_evaluation_report
from llm.gemini_provider import GeminiTechnicalCaseProvider, has_api_key


MAX_API_CALLS = 1


def run_mr_only(provider=None) -> dict:
    if provider is None:
        if not has_api_key():
            return {
                "success": False,
                "error_code": "MISSING_API_KEY",
                "error_message": "GEMINI_API_KEY is not configured",
                "api_calls": 0,
            }
        provider = GeminiTechnicalCaseProvider()

    fixtures = load_ihi_tech_fixtures()
    run = run_manufacturer_response_analysis(
        manufacturer_questions_from_golden(),
        manufacturer_response_fixture_text(),
        provider=provider,
    )
    if not run.success:
        return {
            "success": False,
            "error_code": run.error_code,
            "error_message": run.error_details,
            "api_calls": 1,
            "retry": 0,
            "fallback": 0,
        }

    usage = usage_dict(getattr(provider, "last_usage", None))
    analysis = run.analysis_json or {}
    evaluation = evaluate_manufacturer_response(
        analysis,
        fixtures["response_expected"],
        usage=usage,
    )
    report = build_provider_evaluation_report(
        provider=run.provider_name,
        model=getattr(provider, "model", None),
        case_id=fixtures["input"]["case_id"],
        analysis_type="manufacturer_response",
        usage=usage,
        evaluation=evaluation,
        validation_results=[getattr(view, "validation", None) for view in run.matches],
        payload=analysis,
    )
    return {
        "success": run.success,
        "error_code": run.error_code,
        "api_calls": 1,
        "retry": 0,
        "fallback": 0,
        "thinking_leaks": find_thinking_leaks(analysis),
        "usage": usage,
        "evaluation": evaluation.as_dict(),
        "provider_report": report.as_dict(),
        "analysis": analysis,
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = run_mr_only()
    print(
        dumps(
            {
                key: result[key]
                for key in result
                if key != "analysis"
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if result.get("success"):
        print(dumps({"analysis": result.get("analysis")}, ensure_ascii=False, indent=2))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
