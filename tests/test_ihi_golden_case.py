from data.golden_cases.loader import IHI_TECH_001, load_golden_case

REQUIRED_REQUIREMENT_TOPIC_IDS = {
    "usage_thickness_measurement",
    "method_ultrasonic_thickness_gauge",
    "target_steel_cylindrical_tank",
    "area_side_wall",
    "area_bottom",
    "environment_underwater",
    "tank_inner_diameter_about_10m",
    "tank_height_about_15m",
    "plate_thickness_about_12_to_25mm",
    "coating_about_0_5mm",
    "water_temperature_ambient",
    "visibility_relatively_good",
    "need_to_know_measurement_location",
    "existing_chasing_rov",
    "existing_rov_used_for_visual_inspection",
}

REQUIRED_MANUFACTURER_TOPIC_IDS = {
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

PRICE_MARKERS = ("価格", "USD", "$", "万円", "送料")
SKU_MARKERS = ("SKU",)
LEAD_TIME_MARKERS = ("納期", "週間", "営業日")


def _load_ihi_case():
    return load_golden_case(IHI_TECH_001)


def _topic_ids(topics):
    return {item["topic_id"] for item in topics}


def _input_text(payload):
    return " ".join(
        [
            payload["case_name"],
            payload["customer_name"],
            payload.get("customer_inquiry") or "",
            " ".join(payload.get("requested_products") or []),
        ]
    )


def test_input_json_loads():
    case = _load_ihi_case()
    payload = case["input"]

    assert payload["case_id"] == "IHI-TECH-001"
    assert payload["customer_name"] == "株式会社IHI検査計測"
    assert "MAG Utility Crawler" in payload["customer_inquiry"]


def test_expected_json_loads():
    case = _load_ihi_case()
    expected = case["expected"]

    assert expected["case_id"] == "IHI-TECH-001"
    assert expected["requested_product"] == "MAG Utility Crawler"
    assert expected["evaluation_policy"]["forbidden_assertion_present"] == "FAIL"
    assert expected["evaluation_policy"]["missing_optional_customer_question_topic"] == "WARNING"


def test_requested_product_is_customer_requested_not_recommended():
    case = _load_ihi_case()
    payload = case["input"]
    expected = case["expected"]

    assert payload["requested_products"] == ["MAG Utility Crawler"]
    assert payload["requested_product_origin"] == "CUSTOMER_REQUESTED"
    assert "recommended_products" not in payload
    assert expected["recommendation_must_not_be_confirmed"] is True
    assert expected["extracted_requirements_must_be_unconfirmed"] is True


def test_required_requirement_topics_exist():
    expected = _load_ihi_case()["expected"]
    topic_ids = _topic_ids(expected["required_requirement_topics"])

    assert REQUIRED_REQUIREMENT_TOPIC_IDS.issubset(topic_ids)
    assert all(item.get("aliases") for item in expected["required_requirement_topics"])


def test_required_manufacturer_question_topics_exist():
    expected = _load_ihi_case()["expected"]
    topic_ids = _topic_ids(expected["required_manufacturer_question_topics"])

    assert REQUIRED_MANUFACTURER_TOPIC_IDS.issubset(topic_ids)
    assert all(item.get("aliases") for item in expected["required_manufacturer_question_topics"])


def test_forbidden_assertions_exist():
    expected = _load_ihi_case()["expected"]
    assertion_ids = {item["assertion_id"] for item in expected["forbidden_assertions"]}

    assert "mag_is_optimal_product" in assertion_ids
    assert "photon_is_officially_recommended" in assertion_ids
    assert "price_generated" in assertion_ids
    assert "sku_generated" in assertion_ids
    assert all(item.get("severity") == "FAIL" for item in expected["forbidden_assertions"])


def test_later_manufacturer_facts_are_not_in_input():
    case = _load_ihi_case()
    text = _input_text(case["input"])

    for fact in case["expected"]["later_facts_must_not_appear_in_input"]:
        assert fact not in text


def test_input_has_no_price_sku_or_specific_lead_time():
    text = _input_text(_load_ihi_case()["input"])

    for marker in PRICE_MARKERS + SKU_MARKERS + LEAD_TIME_MARKERS:
        assert marker not in text
