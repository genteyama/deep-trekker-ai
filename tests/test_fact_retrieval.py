from agents.fact_retrieval import (
    build_fact_grounded_questions,
    detect_requested_products,
    facts_as_provider_payload,
    load_human_approved_catalog,
    merge_manufacturer_questions,
    retrieve_approved_facts_for_products,
)
from agents.technical_case_agent import load_system_prompt, run_technical_case_analysis
from data.golden_cases.ihi_tech_eval import load_ihi_tech_fixtures
from llm.mock_provider import DEFAULT_MOCK_PAYLOAD, MockTechnicalCaseProvider
from llm.provider import attach_approved_facts


def test_catalog_contains_only_human_approved_mag_facts():
    catalog = load_human_approved_catalog()
    assert {item["fact_id"] for item in catalog} == {
        "FACT-MAG-SURFACE-TRANSITION",
        "FACT-MAG-SELF-POSITION",
        "FACT-MAG-CYGNUS",
        "FACT-MAG-UNDERWATER-TANK-RECOMMENDATION",
    }
    blob = "\n".join(item["fact"] for item in catalog)
    assert "ATEX" not in blob
    assert "45kgf" not in blob
    assert "GPSがない" not in blob
    assert all(item["status"] == "HUMAN_REGISTERED" for item in catalog)
    assert all(item["scope"] == "PRODUCT_REUSABLE" for item in catalog)
    assert all(item["confidence"] == "MANUFACTURER_CONFIRMED" for item in catalog)


def test_detects_mag_and_retrieves_four_facts():
    inquiry = load_ihi_tech_fixtures()["input"]["customer_inquiry"]
    products = detect_requested_products(inquiry)
    facts = retrieve_approved_facts_for_products(products)
    assert products == ["MAG Utility Crawler"]
    assert [item["topic"] for item in facts] == [
        "surface_transition_constraint",
        "structure_self_position",
        "cygnus_compatibility",
        "underwater_tank_manufacturer_recommendation",
    ]


def test_pipetrekker_inquiry_does_not_retrieve_mag_facts():
    facts = retrieve_approved_facts_for_products(detect_requested_products("PipeTrekkerで管内点検したい"))
    assert facts == []


def test_unapproved_or_case_only_facts_are_not_retrieved():
    catalog = [
        {
            "fact_id": "SKIP-UNAPPROVED",
            "product": "MAG Utility Crawler",
            "topic": "x",
            "fact": "should not retrieve",
            "scope": "PRODUCT_REUSABLE",
            "status": "AI_EXTRACTED_UNVERIFIED",
            "confidence": "MANUFACTURER_CONFIRMED",
        },
        {
            "fact_id": "SKIP-CASE",
            "product": "MAG Utility Crawler",
            "topic": "x",
            "fact": "should not retrieve",
            "scope": "CASE_ONLY",
            "status": "HUMAN_REGISTERED",
            "confidence": "MANUFACTURER_CONFIRMED",
        },
    ]
    assert retrieve_approved_facts_for_products(["MAG Utility Crawler"], catalog=catalog) == []


def test_provider_payload_has_evidence_and_no_customer_email():
    facts = retrieve_approved_facts_for_products(["MAG Utility Crawler"])
    payload = attach_approved_facts({"inquiry_text": "MAG Utility Crawler"}, facts_as_provider_payload(facts))
    assert len(payload["approved_technical_facts"]) == 4
    assert payload["approved_technical_facts"][0]["source_reference"].startswith("IHI-TECH-001-MR-001")
    assert "customer_inquiry" not in str(payload["approved_technical_facts"])
    assert "AIza" not in str(payload)


def test_grounded_questions_are_marked_technical_fact_and_need_human_review():
    inquiry = load_ihi_tech_fixtures()["input"]["customer_inquiry"]
    facts = retrieve_approved_facts_for_products(["MAG Utility Crawler"])
    questions = build_fact_grounded_questions(inquiry, facts)
    assert len(questions) == 4
    assert {item["source"] for item in questions} == {"TECHNICAL_FACT"}
    assert {item["grounding"] for item in questions} == {item["fact_id"] for item in facts}
    merged = merge_manufacturer_questions(
        [{"question": "MAGは90度の面移動ができるか確認してください。"}],
        questions,
    )
    assert any("自己位置" in (item.get("question") or "") for item in merged)
    assert sum("面移動" in (item.get("question") or "") or "連続して移動" in (item.get("question") or "") for item in merged) == 1


def test_agent_passes_facts_to_provider_and_merges_grounded_questions():
    captured = {}

    class CaptureProvider(MockTechnicalCaseProvider):
        name = "capture"

        def analyze_technical_case(self, **kwargs):
            captured.update(kwargs)
            return dict(DEFAULT_MOCK_PAYLOAD)

    inquiry = load_ihi_tech_fixtures()["input"]["customer_inquiry"]
    run = run_technical_case_analysis("案件", "顧客", None, inquiry, provider=CaptureProvider())
    assert run.success is True
    assert [fact.fact_id for fact in run.retrieved_facts] == [
        "FACT-MAG-SURFACE-TRANSITION",
        "FACT-MAG-SELF-POSITION",
        "FACT-MAG-CYGNUS",
        "FACT-MAG-UNDERWATER-TANK-RECOMMENDATION",
    ]
    assert len(captured["approved_technical_facts"]) == 4
    assert captured["system_prompt"] == load_system_prompt()
    sources = [item.source for item in run.manufacturer_questions]
    assert "TECHNICAL_FACT" in sources
    assert all(item.status.value == "DRAFT" for item in run.manufacturer_questions)


def test_mock_without_mag_stays_unchanged():
    run = run_technical_case_analysis("案件", "顧客", None, "管内点検の相談です。")
    assert run.retrieved_facts == []
    assert [item.question for item in run.manufacturer_questions] == [
        item["question"] for item in DEFAULT_MOCK_PAYLOAD["manufacturer_questions"]
    ]
    assert run.case_summary == DEFAULT_MOCK_PAYLOAD["case_summary"]


def test_common_prompt_is_not_specialized_for_mag_facts():
    prompt = load_system_prompt()
    assert "TECHNICAL_FACT" in prompt
    assert "異なる面へ連続して移動できない" not in prompt
    assert "PHOTON + Cygnus" not in prompt
    assert "Integration Kit" not in prompt
