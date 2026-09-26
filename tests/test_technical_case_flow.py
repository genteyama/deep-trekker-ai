from datetime import datetime, timezone

from models import Case
from ui.technical_case_flow import (
    build_case_from_inputs,
    empty_analysis_result,
    has_analysis_results,
    normalize_optional_text,
    start_inquiry_analysis,
)


def test_normalize_optional_text_treats_blank_as_none():
    assert normalize_optional_text(None) is None
    assert normalize_optional_text("") is None
    assert normalize_optional_text("   ") is None
    assert normalize_optional_text(" 管内点検 ") == "管内点検"


def test_build_case_from_inputs_keeps_unknown_end_user_empty():
    created_at = datetime(2026, 9, 26, 13, 30, 0, tzinfo=timezone.utc)
    case = build_case_from_inputs(
        "PipeTrekker 管内点検",
        "サンプル株式会社",
        "",
        case_id="CASE-TEST-001",
        created_at=created_at,
    )

    assert case.case_id == "CASE-TEST-001"
    assert case.case_name == "PipeTrekker 管内点検"
    assert case.customer_name == "サンプル株式会社"
    assert case.end_user_name is None
    assert case.requested_products == []
    assert case.status is None


def test_start_inquiry_analysis_does_not_invent_results():
    case, inquiry, analysis = start_inquiry_analysis(
        "PipeTrekker 管内点検",
        "サンプル株式会社",
        None,
        "直径300mmの管を点検したい。PipeTrekkerを希望。",
        case_id="CASE-TEST-002",
    )

    assert isinstance(case, Case)
    assert inquiry == "直径300mmの管を点検したい。PipeTrekkerを希望。"
    assert case.requested_products == []
    assert analysis == empty_analysis_result()
    assert has_analysis_results(analysis) is False
