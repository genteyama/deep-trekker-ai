from data.golden_cases.ihi_tech_eval import (
    MATCH,
    MISSING,
    PARTIAL,
    UNSUPPORTED,
    evaluate_initial_analysis,
    evaluate_manufacturer_response,
    find_thinking_leaks,
    load_ihi_tech_fixtures,
    manufacturer_questions_from_golden,
    manufacturer_response_fixture_text,
)
from llm.analysis_schema import TechnicalCaseAnalysisResponse
from models import ManufacturerResponseAnalysis


def test_eval_reuses_existing_golden_fixtures():
    fixtures = load_ihi_tech_fixtures()
    assert fixtures["input"]["case_id"] == "IHI-TECH-001"
    assert fixtures["expected"]["stage"] == "INITIAL_CUSTOMER_INQUIRY"
    assert fixtures["response_expected"]["response_golden_case_id"] == "IHI-TECH-001-MR-001"
    assert fixtures["source_notes"]["raw_response_text"] is None
    questions = manufacturer_questions_from_golden()
    assert [item.question_id for item in questions] == [
        item["question_topic"] for item in fixtures["response_expected"]["question_expectations"]
    ]
    response_text = manufacturer_response_fixture_text()
    assert "HUMAN_VERIFIED_MANUFACTURER_RESPONSE_SUMMARY" in response_text
    assert "From:" not in response_text
    assert "45kgf" not in response_text
    assert "ATEX" not in response_text


def test_initial_schema_and_required_topics_match():
    payload = TechnicalCaseAnalysisResponse(
        case_summary="IHI検査計測から鋼製円筒タンクの水中肉厚測定相談。指定製品はMAG Utility Crawler。適否は未確定。",
        requested_products=["MAG Utility Crawler"],
        requirements=[
            {"label": "用途", "value": "肉厚測定", "notes": "超音波厚さ計"},
            {"label": "対象", "value": "鋼製円筒タンク 側面 底面", "notes": "水中環境"},
            {"label": "内径", "value": "約10m"},
            {"label": "高さ", "value": "約15m"},
            {"label": "鋼板厚", "value": "約12～25mm"},
            {"label": "塗膜", "value": "約0.5mm"},
            {"label": "水温", "value": "常温水"},
            {"label": "視界", "value": "比較的良好"},
            {"label": "位置", "value": None, "notes": "測定した場所を把握したい。要確認"},
            {"label": "既存", "value": "CHASING ROV", "notes": "目視点検"},
        ],
        manufacturer_questions=[
            {"question": "Cygnus厚さ計と組み合わせて使用できるか"},
            {"question": "Elevated Pan Tiltと同時搭載できるか確認"},
            {"question": "水中タンク内部に適しているか"},
            {"question": "90度の面移動は可能か"},
            {"question": "自己位置を把握できるか"},
            {"question": "水深情報は取得できるか"},
            {"question": "テザー繰出長や走行距離は分かるか"},
            {"question": "方位情報はあるか"},
            {"question": "測定した位置を記録・管理できるか"},
            {"question": "メーカーが推奨する構成は何か"},
            {"question": "想定納期はどの程度か確認したい"},
        ],
        unresolved_items=[{"label": "適否", "notes": "UNKNOWN / 要確認"}],
    ).model_dump(mode="json")
    report = evaluate_initial_analysis(payload, load_ihi_tech_fixtures()["expected"])
    assert all(score.classification in {MATCH, PARTIAL} for score in report.scores)
    assert not any(item.classification == UNSUPPORTED for item in report.findings)
    assert not report.thinking_leaks


def test_initial_missing_and_unsupported_are_detected():
    payload = {
        "case_summary": "MAGが最適。ATEXが必要。PHOTONを推奨。水深センサーがない。納期は2週間。価格は100万円。",
        "requested_products": ["PHOTON"],
        "requirements": [{"label": "認証", "value": "ATEX", "notes": "防爆認証が必要"}],
        "customer_questions": [],
        "manufacturer_questions": [],
        "technical_questions": [],
        "unresolved_items": [],
        "thinking": "secret thinking",
    }
    report = evaluate_initial_analysis(payload, load_ihi_tech_fixtures()["expected"])
    classes = {item.classification for item in report.scores + report.findings}
    assert MISSING in classes
    assert UNSUPPORTED in classes
    assert any(item.item_id == "hallucination_marker" for item in report.findings)
    assert any(item.item_id == "later_fact" for item in report.findings)
    assert report.thinking_leaks


def test_thinking_is_detected_and_not_treated_as_content_match():
    leaks = find_thinking_leaks({"case_summary": "ok", "reasoning": "do not keep"})
    assert leaks
    assert all("reasoning" in item for item in leaks)


def test_manufacturer_response_status_and_overclaim():
    expected = load_ihi_tech_fixtures()["response_expected"]
    good = ManufacturerResponseAnalysis(
        response_summary="メーカー確認済み情報を質問ごとに整理。PHOTON案はメーカー推奨。",
        matches=[
            {
                "question_id": "mag_cygnus_compatibility",
                "answer_summary": "Cygnus本体は共有でき、機体ごとのIntegration Kitが必要。",
                "suggested_status": "ANSWERED",
                "follow_up_required": False,
            },
            {
                "question_id": "cygnus_elevated_pan_tilt_simultaneous",
                "answer_summary": None,
                "suggested_status": "FOLLOW_UP_REQUIRED",
                "follow_up_required": True,
            },
            {
                "question_id": "underwater_tank_interior_suitability",
                "answer_summary": "メーカーはROVと超音波肉厚計を推奨。MAG適性は追加確認。",
                "suggested_status": "PARTIAL",
                "follow_up_required": True,
            },
            {
                "question_id": "mag_90_degree_surface_transition",
                "answer_summary": "異なる面への連続移動はできない。",
                "suggested_status": "ANSWERED",
                "follow_up_required": False,
            },
            {
                "question_id": "mag_position_awareness",
                "answer_summary": "水深・高度・テザー繰出量による自己位置把握機能はない。",
                "suggested_status": "ANSWERED",
                "follow_up_required": False,
            },
            {
                "question_id": "depth_information",
                "suggested_status": "FOLLOW_UP_REQUIRED",
                "follow_up_required": True,
            },
            {
                "question_id": "tether_payout_or_travel_distance",
                "suggested_status": "FOLLOW_UP_REQUIRED",
                "follow_up_required": True,
            },
            {
                "question_id": "heading_information",
                "suggested_status": "FOLLOW_UP_REQUIRED",
                "follow_up_required": True,
            },
            {
                "question_id": "cygnus_measurement_position_recording",
                "suggested_status": "FOLLOW_UP_REQUIRED",
                "follow_up_required": True,
            },
            {
                "question_id": "manufacturer_recommended_configuration",
                "answer_summary": "メーカー推奨はROV＋超音波肉厚計。候補はPHOTON + Cygnus。",
                "suggested_status": "ANSWERED",
                "follow_up_required": False,
            },
            {
                "question_id": "estimated_lead_time_question",
                "suggested_status": "FOLLOW_UP_REQUIRED",
                "follow_up_required": True,
            },
        ],
        unmatched_information=[
            {"summary": "磁力が強く投入・取り外しが難しい場合がある"},
            {"summary": "1輪あたり50 lb"},
            {"summary": "PHOTONでは水深値・方位・姿勢を確認できる"},
        ],
        overall_follow_up_required=True,
    ).model_dump(mode="json")
    good_report = evaluate_manufacturer_response(good, expected)
    assert all(score.classification in {MATCH, PARTIAL} for score in good_report.scores)
    assert not any(item.item_id == "all_answered" for item in good_report.findings)

    overclaim = {
        "response_summary": "全て回答済み。ATEX必須。納期は3週間。PHOTONはAI_SUGGESTED。保持力は45kgf保証。GPSがない。",
        "matches": [
            {
                "question_id": item["question_topic"],
                "answer_summary": "回答あり",
                "suggested_status": "ANSWERED",
                "follow_up_required": False,
            }
            for item in expected["question_expectations"]
        ],
        "unmatched_information": [],
        "overall_follow_up_required": False,
    }
    bad_report = evaluate_manufacturer_response(overclaim, expected)
    assert any(item.item_id == "all_answered" for item in bad_report.findings)
    assert any(item.item_id == "45kgf_guarantee" for item in bad_report.findings)
    assert any(item.item_id == "photon_ai_suggested" for item in bad_report.findings)
    assert any(item.classification == UNSUPPORTED for item in bad_report.scores + bad_report.findings)
