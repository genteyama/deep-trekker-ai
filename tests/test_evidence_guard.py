from llm.evidence_guard import (
    REASON_EVIDENCE_MISSING,
    REASON_EVIDENCE_NOT_IN_RESPONSE,
    REASON_PRODUCT_SCOPE_MISMATCH,
    REASON_TOPIC_SCOPE_MISMATCH,
    apply_evidence_guard,
    extract_product_entities,
    product_scope_covers,
    required_question_entities,
)
from models import QuestionStatus, QuestionTarget, ResponseMatchCandidate, SuggestedQuestionStatus, TechnicalQuestion


def _question(question_id: str, text: str, products=None) -> TechnicalQuestion:
    return TechnicalQuestion(
        question_id=question_id,
        case_id="CASE-GUARD",
        target=QuestionTarget.MANUFACTURER,
        question=text,
        status=QuestionStatus.DRAFT,
        related_products=products or [],
    )


def _answered(question_id: str, evidence: str) -> ResponseMatchCandidate:
    return ResponseMatchCandidate(
        question_id=question_id,
        suggested_status=SuggestedQuestionStatus.ANSWERED,
        evidence_text=evidence,
        answer_summary=evidence,
    )


def test_cross_product_evidence_is_rejected():
    question = _question("depth_information", "PIVOTに水深情報はあるか", ["PIVOT"])
    evidence = "REVOLUTIONでは水深値を確認できます"
    updated, check = apply_evidence_guard(question, _answered("depth_information", evidence), evidence)
    assert check.product_scope_valid is False
    assert check.reason == REASON_PRODUCT_SCOPE_MISMATCH
    assert updated.suggested_status == SuggestedQuestionStatus.FOLLOW_UP_REQUIRED


def test_same_product_evidence_is_accepted():
    question = _question("depth_information", "PIVOTに水深情報はあるか", ["PIVOT"])
    evidence = "PIVOTでは水深値を確認できます"
    updated, check = apply_evidence_guard(question, _answered("depth_information", evidence), evidence)
    assert check.product_scope_valid is True
    assert check.topic_scope_valid is True
    assert check.evidence_valid is True
    assert updated.suggested_status == SuggestedQuestionStatus.ANSWERED
    assert extract_product_entities(question.question) == ["PIVOT"]


def test_mag_plus_accessory_rejects_other_vehicle_plus_same_accessory():
    question = _question("vehicle_gauge_compatibility", "MAG + Cygnus の互換性")
    evidence = "PHOTON + Cygnus が利用可能"
    updated, check = apply_evidence_guard(question, _answered(question.question_id, evidence), evidence)
    assert set(check.question_products) >= {"MAG Utility Crawler", "Cygnus Thickness Gauge"}
    assert "MAG Utility Crawler" not in check.evidence_products
    assert check.product_scope_valid is False
    assert check.reason == REASON_PRODUCT_SCOPE_MISMATCH
    assert updated.suggested_status == SuggestedQuestionStatus.FOLLOW_UP_REQUIRED


def test_shared_accessory_evidence_covers_required_product_subset():
    question = _question("vehicle_gauge_compatibility", "MAG + Cygnus の互換性")
    evidence = "Cygnus本体はMAGとPHOTONで共用可能。各機体専用Integration Kitが必要。"
    updated, check = apply_evidence_guard(question, _answered(question.question_id, evidence), evidence)
    assert product_scope_covers(check.question_products, check.evidence_products) is True
    assert check.product_scope_valid is True
    assert check.evidence_valid is True
    assert updated.suggested_status == SuggestedQuestionStatus.ANSWERED


def test_product_scope_ok_does_not_force_answered_when_topic_differs():
    question = _question("depth_information", "PIVOTに水深情報はあるか", ["PIVOT"])
    evidence = "PIVOTでは方位・姿勢情報を確認できる"
    updated, check = apply_evidence_guard(question, _answered("depth_information", evidence), evidence)
    assert check.product_scope_valid is True
    assert check.topic_scope_valid is False
    assert check.reason == REASON_TOPIC_SCOPE_MISMATCH
    assert updated.suggested_status == SuggestedQuestionStatus.FOLLOW_UP_REQUIRED


def test_generic_question_does_not_require_product_entities():
    question = _question("heading_information", "方位情報を取得できるか")
    assert required_question_entities(question) == []
    evidence = "方位情報を確認できます"
    updated, check = apply_evidence_guard(question, _answered("heading_information", evidence), evidence)
    assert check.product_scope_valid is True
    assert updated.suggested_status == SuggestedQuestionStatus.ANSWERED


def test_topic_mismatch_is_downgraded():
    question = _question("depth_information", "水深情報を取得できるか")
    evidence = "自己位置を把握する機能はない。"
    updated, check = apply_evidence_guard(question, _answered("depth_information", evidence), evidence)
    assert check.topic_scope_valid is False
    assert check.reason == REASON_TOPIC_SCOPE_MISMATCH
    assert updated.suggested_status == SuggestedQuestionStatus.FOLLOW_UP_REQUIRED


def test_heading_cannot_reuse_self_position():
    question = _question("heading_information", "方位情報を取得できるか")
    evidence = "構造物上の自己位置を把握する機能はない"
    updated, check = apply_evidence_guard(question, _answered("heading_information", evidence), evidence)
    assert check.topic_scope_valid is False
    assert check.reason == REASON_TOPIC_SCOPE_MISMATCH
    assert updated.suggested_status == SuggestedQuestionStatus.FOLLOW_UP_REQUIRED


def test_heading_evidence_is_accepted_for_heading_question():
    question = _question("heading_information", "方位情報を取得できるか")
    evidence = "方位・姿勢情報を確認できる"
    updated, check = apply_evidence_guard(question, _answered("heading_information", evidence), evidence)
    assert check.topic_scope_valid is True
    assert check.evidence_valid is True
    assert updated.suggested_status == SuggestedQuestionStatus.ANSWERED


def test_mixed_sensor_evidence_does_not_answer_a_single_sensor_question():
    evidence = "PIVOTでは水深値・方位・姿勢情報を確認できる"
    for question_id, text in (
        ("depth_information", "水深値を取得できるか"),
        ("heading_information", "方位情報を取得できるか"),
    ):
        question = _question(question_id, text)
        updated, check = apply_evidence_guard(question, _answered(question_id, evidence), evidence)
        assert check.topic_scope_valid is False
        assert check.reason == REASON_TOPIC_SCOPE_MISMATCH
        assert updated.suggested_status == SuggestedQuestionStatus.FOLLOW_UP_REQUIRED


def test_depth_cannot_reuse_heading_evidence():
    question = _question("depth_information", "水深値を取得できるか")
    evidence = "方位・姿勢情報を確認できる"
    updated, check = apply_evidence_guard(question, _answered("depth_information", evidence), evidence)
    assert check.topic_scope_valid is False
    assert check.reason == REASON_TOPIC_SCOPE_MISMATCH
    assert updated.suggested_status == SuggestedQuestionStatus.FOLLOW_UP_REQUIRED


def test_tether_and_heading_cannot_reuse_self_position():
    evidence = "水深・高度・テザー繰出量などを利用した自己位置把握機能はない。"
    for question_id, text in (
        ("tether_payout_or_travel_distance", "テザー繰出長は分かるか"),
        ("heading_information", "方位情報はあるか"),
        ("depth_information", "水深情報はあるか"),
        ("altitude_information", "高度情報はあるか"),
    ):
        question = _question(question_id, text)
        updated, check = apply_evidence_guard(question, _answered(question_id, evidence), evidence)
        assert check.reason == REASON_TOPIC_SCOPE_MISMATCH
        assert updated.suggested_status == SuggestedQuestionStatus.FOLLOW_UP_REQUIRED


def test_subset_rule_works_for_unrelated_vehicle_and_sonar():
    question = _question("pivot_sonar_compatibility", "PIVOT + Sonar の互換性")
    other_vehicle = "REVOLUTION + Sonar が利用可能"
    updated, check = apply_evidence_guard(question, _answered(question.question_id, other_vehicle), other_vehicle)
    assert check.product_scope_valid is False
    assert check.reason == REASON_PRODUCT_SCOPE_MISMATCH
    assert updated.suggested_status == SuggestedQuestionStatus.FOLLOW_UP_REQUIRED

    shared = "Sonar本体はPIVOTとREVOLUTIONで共用可能。"
    updated, check = apply_evidence_guard(question, _answered(question.question_id, shared), shared)
    assert product_scope_covers(check.question_products, check.evidence_products) is True
    assert check.product_scope_valid is True


def test_missing_evidence_is_rejected():
    question = _question("compatibility", "組み合わせは可能か")
    candidate = ResponseMatchCandidate(
        question_id="compatibility",
        suggested_status=SuggestedQuestionStatus.ANSWERED,
        evidence_text=None,
    )
    updated, check = apply_evidence_guard(question, candidate, "組み合わせは可能です")
    assert check.evidence_valid is False
    assert check.reason == REASON_EVIDENCE_MISSING
    assert updated.suggested_status == SuggestedQuestionStatus.FOLLOW_UP_REQUIRED


def test_evidence_not_in_response_is_rejected():
    question = _question("compatibility", "組み合わせは可能か")
    candidate = ResponseMatchCandidate(
        question_id="compatibility",
        suggested_status=SuggestedQuestionStatus.PARTIAL,
        evidence_text="本文にない根拠",
    )
    updated, check = apply_evidence_guard(question, candidate, "組み合わせは可能です")
    assert check.reason == REASON_EVIDENCE_NOT_IN_RESPONSE
    assert updated.suggested_status == SuggestedQuestionStatus.FOLLOW_UP_REQUIRED
