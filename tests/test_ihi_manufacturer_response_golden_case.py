from data.golden_cases.loader import (
    IHI_TECH_001,
    load_golden_case,
    load_manufacturer_response_golden_case,
)

REQUIRED_QUESTION_TOPICS = {
    "mag_cygnus_compatibility",
    "cygnus_elevated_pan_tilt_simultaneous",
    "underwater_tank_interior_suitability",
    "mag_90_degree_surface_transition",
    "mag_position_awareness",
    "depth_information",
    "tether_payout_or_travel_distance",
    "heading_information",
    "cygnus_measurement_position_recording",
    "manufacturer_recommended_configuration",
    "estimated_lead_time_question",
}

ALLOWED_STATUSES = {"ANSWERED", "PARTIAL", "FOLLOW_UP_REQUIRED"}
RAW_EMAIL_KEYS = ("raw_email", "raw_email_body", "email_body", "manufacturer_email")
EMAIL_MARKERS = ("From:", "Subject:", "Dear ", "Hi Team")


def _load_mr_case():
    return load_manufacturer_response_golden_case()


def _question_map(expected):
    return {item["question_topic"]: item for item in expected["question_expectations"]}


def test_manufacturer_response_golden_case_loads():
    case = _load_mr_case()
    expected = case["expected"]
    notes = case["source_notes"]

    assert expected["case_id"] == "IHI-TECH-001"
    assert expected["response_golden_case_id"] == "IHI-TECH-001-MR-001"
    assert notes["response_golden_case_id"] == "IHI-TECH-001-MR-001"
    assert notes["source_type"] == "HUMAN_VERIFIED_MANUFACTURER_RESPONSE_SUMMARY"


def test_raw_manufacturer_email_was_not_invented():
    case = _load_mr_case()
    notes = case["source_notes"]
    expected = case["expected"]

    assert notes["raw_response_available"] is False
    assert expected["raw_response_available"] is False
    assert notes["is_raw_manufacturer_email"] is False
    assert notes["raw_response_text"] is None
    assert "input.json" not in {path.name for path in case["case_dir"].iterdir()}

    for key in RAW_EMAIL_KEYS:
        assert key not in notes
        assert key not in expected

    combined = str(notes) + str(expected)
    for marker in EMAIL_MARKERS:
        assert marker not in combined


def test_question_expected_statuses_exist_and_are_distinct():
    expected = _load_mr_case()["expected"]
    question_map = _question_map(expected)
    statuses = {item["expected_status"] for item in expected["question_expectations"]}

    assert set(question_map) == REQUIRED_QUESTION_TOPICS
    assert statuses == ALLOWED_STATUSES
    assert all(item["expected_status"] in ALLOWED_STATUSES for item in expected["question_expectations"])


def test_not_all_questions_are_answered():
    expected = _load_mr_case()["expected"]
    statuses = [item["expected_status"] for item in expected["question_expectations"]]

    assert "ANSWERED" in statuses
    assert "PARTIAL" in statuses
    assert "FOLLOW_UP_REQUIRED" in statuses
    assert statuses.count("ANSWERED") < len(statuses)
    assert any(item["follow_up_required"] for item in expected["question_expectations"])


def test_unanswered_questions_remain():
    question_map = _question_map(_load_mr_case()["expected"])

    assert question_map["cygnus_elevated_pan_tilt_simultaneous"]["expected_status"] == "FOLLOW_UP_REQUIRED"
    assert question_map["depth_information"]["expected_status"] == "FOLLOW_UP_REQUIRED"
    assert question_map["tether_payout_or_travel_distance"]["expected_status"] == "FOLLOW_UP_REQUIRED"
    assert question_map["heading_information"]["expected_status"] == "FOLLOW_UP_REQUIRED"
    assert question_map["cygnus_measurement_position_recording"]["expected_status"] == "FOLLOW_UP_REQUIRED"
    assert question_map["estimated_lead_time_question"]["expected_status"] == "FOLLOW_UP_REQUIRED"


def test_confirmed_topics_keep_separate_statuses():
    question_map = _question_map(_load_mr_case()["expected"])

    assert question_map["mag_position_awareness"]["expected_status"] == "ANSWERED"
    assert question_map["mag_90_degree_surface_transition"]["expected_status"] == "ANSWERED"
    assert question_map["depth_information"]["expected_status"] != "ANSWERED"
    assert question_map["tether_payout_or_travel_distance"]["expected_status"] != "ANSWERED"
    assert question_map["heading_information"]["expected_status"] != "ANSWERED"


def test_product_origins_are_not_confused():
    case = _load_mr_case()
    expected_origins = case["expected"]["product_origins"]
    notes_origins = case["source_notes"]["product_origins"]

    assert expected_origins["MAG Utility Crawler"] == "CUSTOMER_REQUESTED"
    assert notes_origins["MAG Utility Crawler"] == "CUSTOMER_REQUESTED"
    assert expected_origins["PHOTON"] == "MANUFACTURER_RECOMMENDED"
    assert notes_origins["PHOTON"] == "MANUFACTURER_RECOMMENDED"
    assert expected_origins["PHOTON + Cygnus Thickness Gauge"] == "MANUFACTURER_RECOMMENDED"
    assert "AI_SUGGESTED" not in expected_origins.values()
    assert "AI_SUGGESTED" not in notes_origins.values()

    photon = next(
        item
        for item in case["source_notes"]["verified_statements"]
        if item["statement_id"] == "photon_plus_cygnus_proposed"
    )
    assert photon["recommendation_origin"] == "MANUFACTURER_RECOMMENDED"
    assert "AI_SUGGESTED" in photon["must_not_use_origin"]


def test_surface_transition_and_position_facts_exist():
    notes = _load_mr_case()["source_notes"]
    statement_ids = {item["statement_id"] for item in notes["verified_statements"]}

    assert "mag_cannot_transition_surfaces" in statement_ids
    assert "mag_no_structure_self_position" in statement_ids

    position = next(
        item for item in notes["verified_statements"] if item["statement_id"] == "mag_no_structure_self_position"
    )
    assert "GPSがない" in position["must_not_reinterpret_as"]


def test_wheel_force_values_are_not_mixed():
    case = _load_mr_case()
    wheel = next(
        item
        for item in case["source_notes"]["verified_statements"]
        if item["statement_id"] == "mag_wheel_50lb"
    )
    reference = case["source_notes"]["spaceone_derived_values"][0]
    expected_reference = case["expected"]["spaceone_derived_values"][0]

    assert wheel["manufacturer_stated_value"] == "50 lb per wheel"
    assert reference["value"] == "約45kgf"
    assert reference["origin"] == "SPACEONE_SIMPLE_SUM"
    assert reference["must_not_become_manufacturer_guaranteed_total"] is True
    assert reference["must_not_become_technical_fact"] is True
    assert expected_reference["must_not_become_manufacturer_guaranteed_total"] is True


def test_cygnus_share_and_integration_kit_both_exist():
    case = _load_mr_case()
    statement_ids = {item["statement_id"] for item in case["source_notes"]["verified_statements"]}
    compatibility = _question_map(case["expected"])["mag_cygnus_compatibility"]

    assert "cygnus_body_shareable" in statement_ids
    assert "integration_kit_required_per_vehicle" in statement_ids
    assert "cygnus_body_shareable" in compatibility["expected_answer_topics"]
    assert "integration_kit_required_per_vehicle" in compatibility["expected_answer_topics"]


def test_initial_golden_case_was_not_mixed_with_response_stage():
    initial = load_golden_case(IHI_TECH_001)

    assert initial["expected"]["stage"] == "INITIAL_CUSTOMER_INQUIRY"
    assert "PHOTON" not in initial["input"]["customer_inquiry"]
    assert _load_mr_case()["expected"]["stage"] == "AFTER_MANUFACTURER_RESPONSE"
