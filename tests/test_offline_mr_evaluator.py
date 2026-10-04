from agents.technical_case_agent import run_manufacturer_response_analysis
from data.golden_cases.ihi_tech_eval import (
    evaluate_manufacturer_response,
    load_ihi_tech_fixtures,
    manufacturer_questions_from_golden,
    manufacturer_response_fixture_text,
)
from llm.evaluation_report import build_provider_evaluation_report
from llm.mock_provider import MockTechnicalCaseProvider
from models import QuestionStatus, QuestionTarget, TechnicalQuestion


def _question(question_id: str, text: str) -> TechnicalQuestion:
    return TechnicalQuestion(
        question_id=question_id,
        case_id="CASE-OFFLINE",
        target=QuestionTarget.MANUFACTURER,
        question=text,
        status=QuestionStatus.DRAFT,
    )


def _run(questions, response, matches):
    provider = MockTechnicalCaseProvider(
        response_payload={
            "response_summary": "offline fixture",
            "matches": matches,
            "unmatched_information": [],
            "overall_follow_up_required": True,
        }
    )
    return run_manufacturer_response_analysis(questions, response, provider=provider)


def test_offline_wrong_product_answered_is_blocked():
    response = "PHOTONでは水深値を確認できます"
    run = _run(
        [_question("depth_information", "MAG Utility Crawlerに水深情報はあるか")],
        response,
        [
            {
                "question_id": "depth_information",
                "suggested_status": "ANSWERED",
                "evidence_text": response,
                "answer_summary": response,
            }
        ],
    )
    assert run.success is True
    assert run.matches[0].candidate.suggested_status.value == "FOLLOW_UP_REQUIRED"
    assert run.matches[0].validation.reason == "PRODUCT_SCOPE_MISMATCH"


def test_offline_self_position_cannot_answer_depth_tether_heading():
    response = "自己位置を把握する機能はない。"
    questions = [
        _question("depth_information", "水深情報はあるか"),
        _question("tether_payout_or_travel_distance", "テザー繰出長はあるか"),
        _question("heading_information", "方位情報はあるか"),
    ]
    matches = [
        {
            "question_id": item.question_id,
            "suggested_status": "ANSWERED",
            "evidence_text": response,
            "answer_summary": response,
        }
        for item in questions
    ]
    run = _run(questions, response, matches)
    assert all(view.candidate.suggested_status.value == "FOLLOW_UP_REQUIRED" for view in run.matches)
    assert all(view.validation.reason == "TOPIC_SCOPE_MISMATCH" for view in run.matches)


def test_offline_correct_evidence_and_missing_row():
    response = "PIVOTでは水深値を確認できます"
    questions = [
        _question("depth_information", "PIVOTに水深情報はあるか"),
        _question("heading_information", "PIVOTに方位はあるか"),
    ]
    run = _run(
        questions,
        response,
        [
            {
                "question_id": "depth_information",
                "suggested_status": "ANSWERED",
                "evidence_text": response,
                "answer_summary": response,
            }
        ],
    )
    assert run.matches[0].candidate.suggested_status.value == "ANSWERED"
    assert run.matches[1].candidate.suggested_status.value == "FOLLOW_UP_REQUIRED"
    assert run.matches[1].validation.reason == "NO_MODEL_MATCH"
    assert [view.question.question_id for view in run.matches] == [
        "depth_information",
        "heading_information",
    ]


def test_offline_shared_accessory_evidence_keeps_product_scope():
    response = "Cygnus本体はMAGとPHOTONで共用可能。各機体専用Integration Kitが必要。"
    run = _run(
        [_question("vehicle_gauge_compatibility", "MAG + Cygnus の互換性")],
        response,
        [
            {
                "question_id": "vehicle_gauge_compatibility",
                "suggested_status": "ANSWERED",
                "evidence_text": response,
                "answer_summary": response,
            }
        ],
    )
    assert run.matches[0].validation.product_scope_valid is True
    assert run.matches[0].candidate.suggested_status.value == "ANSWERED"


def test_offline_heading_accepts_heading_and_rejects_self_position():
    heading = "方位・姿勢情報を確認できる"
    position = "構造物上の自己位置を把握する機能はない"
    accepted = _run(
        [_question("heading_information", "方位情報を取得できるか")],
        heading,
        [
            {
                "question_id": "heading_information",
                "suggested_status": "ANSWERED",
                "evidence_text": heading,
                "answer_summary": heading,
            }
        ],
    )
    assert accepted.matches[0].candidate.suggested_status.value == "ANSWERED"

    rejected = _run(
        [_question("heading_information", "方位情報を取得できるか")],
        position,
        [
            {
                "question_id": "heading_information",
                "suggested_status": "ANSWERED",
                "evidence_text": position,
                "answer_summary": position,
            }
        ],
    )
    assert rejected.matches[0].candidate.suggested_status.value == "FOLLOW_UP_REQUIRED"
    assert rejected.matches[0].validation.reason == "TOPIC_SCOPE_MISMATCH"


def test_offline_depth_rejects_heading_evidence():
    response = "方位・姿勢情報を確認できる"
    run = _run(
        [_question("depth_information", "水深値を取得できるか")],
        response,
        [
            {
                "question_id": "depth_information",
                "suggested_status": "ANSWERED",
                "evidence_text": response,
                "answer_summary": response,
            }
        ],
    )
    assert run.matches[0].candidate.suggested_status.value == "FOLLOW_UP_REQUIRED"
    assert run.matches[0].validation.reason == "TOPIC_SCOPE_MISMATCH"


def test_offline_subset_rule_is_generic_for_pivot_revolution_sonar():
    other = "REVOLUTION + Sonar が利用可能"
    blocked = _run(
        [_question("pivot_sonar_compatibility", "PIVOT + Sonar の互換性")],
        other,
        [
            {
                "question_id": "pivot_sonar_compatibility",
                "suggested_status": "ANSWERED",
                "evidence_text": other,
                "answer_summary": other,
            }
        ],
    )
    assert blocked.matches[0].validation.reason == "PRODUCT_SCOPE_MISMATCH"

    shared = "Sonar本体はPIVOTとREVOLUTIONで共用可能。"
    accepted = _run(
        [_question("pivot_sonar_compatibility", "PIVOT + Sonar の互換性")],
        shared,
        [
            {
                "question_id": "pivot_sonar_compatibility",
                "suggested_status": "ANSWERED",
                "evidence_text": shared,
                "answer_summary": shared,
            }
        ],
    )
    assert accepted.matches[0].validation.product_scope_valid is True


def test_offline_ihi_fixture_photon_as_mag_cygnus_is_blocked():
    fixtures = load_ihi_tech_fixtures()
    questions = manufacturer_questions_from_golden()
    response = manufacturer_response_fixture_text()
    photon = "その候補として PHOTON + Cygnus Thickness Gauge が提案された。"
    run = _run(
        questions,
        response,
        [
            {
                "question_id": "mag_cygnus_compatibility",
                "suggested_status": "ANSWERED",
                "evidence_text": photon,
                "answer_summary": photon,
            }
        ],
    )
    match = next(view for view in run.matches if view.question.question_id == "mag_cygnus_compatibility")
    assert match.candidate.suggested_status.value == "FOLLOW_UP_REQUIRED"
    assert match.validation.reason == "PRODUCT_SCOPE_MISMATCH"
    evaluation = evaluate_manufacturer_response(run.analysis_json, fixtures["response_expected"])
    report = build_provider_evaluation_report(
        provider="offline",
        model="fixture",
        case_id="IHI-TECH-001",
        analysis_type="manufacturer_response",
        evaluation=evaluation,
        validation_results=[view.validation for view in run.matches],
        payload=run.analysis_json,
    )
    assert report.product_scope_errors >= 1
    assert report.thinking_leak is False
