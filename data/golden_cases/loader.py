from pathlib import Path
import json
from typing import Any

GOLDEN_CASES_ROOT = Path(__file__).resolve().parent
IHI_TECH_001 = "ihi_tech_001"
IHI_TECH_001_MR_001 = "ihi_tech_001"


def load_json_file(path: Path) -> Any:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def load_golden_case(slug: str) -> dict:
    case_dir = GOLDEN_CASES_ROOT / slug
    return {
        "case_dir": case_dir,
        "input": load_json_file(case_dir / "input.json"),
        "expected": load_json_file(case_dir / "expected.json"),
    }


def load_manufacturer_response_golden_case(slug: str = IHI_TECH_001_MR_001) -> dict:
    case_dir = GOLDEN_CASES_ROOT / slug / "manufacturer_response"
    return {
        "case_dir": case_dir,
        "expected": load_json_file(case_dir / "expected.json"),
        "source_notes": load_json_file(case_dir / "source_notes.json"),
    }
