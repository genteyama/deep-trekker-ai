from pathlib import Path

from data.golden_cases.ihi_tech_eval import load_ihi_tech_fixtures


def test_gemini_eval_script_reuses_existing_harness_and_fixtures():
    script = (Path(__file__).resolve().parents[1] / "scripts" / "eval_ihi_tech_001_gemini.py").read_text(
        encoding="utf-8"
    )
    fixtures = load_ihi_tech_fixtures()
    assert fixtures["input"]["case_id"] == "IHI-TECH-001"
    assert "from data.golden_cases.ihi_tech_eval import" in script
    assert "evaluate_initial_analysis" in script
    assert "evaluate_manufacturer_response" in script
    assert "GeminiTechnicalCaseProvider" in script
    assert "MAG Utility Crawlerをrequested_products" not in script
    assert "GPS" not in script
    assert "ATEX" not in script
    assert "qwen3.5:9b" not in script
