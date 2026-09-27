from agents.update_inbox_agent import UpdateInboxStore, create_manual_candidate, organize_pasted_update
from models import RecordStatus, UpdateCategory, UpdateSourceType


def test_one_source_can_create_shipping_lead_time_and_spec_candidates():
    source, candidates, rules = organize_pasted_update(
        source_type=UpdateSourceType.DEALER_UPDATE_EMAIL,
        source_title="Deep Trekker Dealer Update: September Edition",
        source_sender="Deep Trekker",
        source_text="September Edition shipping and lead times. SPECTRA 3.5 knots.",
        source_reference="dealer-update-2026-09",
    )
    categories = {item.category for item in candidates}
    shipping = [item for item in candidates if item.category == UpdateCategory.SHIPPING]
    lead_times = [item for item in candidates if item.category == UpdateCategory.LEAD_TIME]
    specs = [item for item in candidates if item.category == UpdateCategory.PRODUCT_SPEC]

    assert source.source_text.startswith("September Edition")
    assert source.source_reference == "dealer-update-2026-09"
    assert len(candidates) > 1
    assert {item.update_source_id for item in candidates} == {source.update_source_id}
    assert UpdateCategory.SHIPPING in categories
    assert UpdateCategory.LEAD_TIME in categories
    assert UpdateCategory.PRODUCT_SPEC in categories
    assert all(item.status == RecordStatus.CANDIDATE for item in candidates)
    assert all(item.status != RecordStatus.APPROVED for item in candidates)
    assert all(rule.status == RecordStatus.CANDIDATE for rule in rules)
    assert {item.new_value for item in shipping} == {
        "732.15",
        "1748.15",
        "2922.15",
        "152.00",
        "690.00",
        "1356.00",
        "2244.15",
        "4668.15",
        "8828.15",
    }
    assert {item.product: item.new_value for item in lead_times} == {
        "DTG3": "6",
        "PHOTON": "9",
        "PIVOT": "10",
        "REVOLUTION": "15",
        "A-200": "6",
        "VAC": "20",
    }
    assert all(item.is_time_sensitive is True for item in lead_times)
    assert all(item.unit == "weeks" for item in lead_times)
    assert any(item.product == "SPECTRA" and item.new_value == "3.5" for item in specs)
    assert any(item.product == "SPECTRA" and item.new_value == "2.3" for item in specs)
    assert any(item.new_value == "February 2027" for item in specs)
    assert all(item.target_master == "TechnicalFact" for item in specs)


def test_unmatched_text_does_not_invent_candidates():
    source, candidates, rules = organize_pasted_update(
        source_title="Random note",
        source_text="Please call me tomorrow.",
    )

    assert source.source_text == "Please call me tomorrow."
    assert candidates == []
    assert rules == []


def test_manual_candidate_from_christianne_stays_unapproved():
    store = UpdateInboxStore()
    source, candidate, rule = create_manual_candidate(
        category=UpdateCategory.SHIPPING,
        summary="This part ships at 620 USD for this job",
        product="REVOLUTION Retrieval Kit",
        sku=None,
        new_value="620",
        unit="USD",
        source_sender="Christianne",
        notes="Serena confirmed Non-DG for this shipment",
        source_type=UpdateSourceType.DIRECT_EMAIL,
        store=store,
    )

    assert source.source_sender == "Christianne"
    assert source.source_text == "This part ships at 620 USD for this job"
    assert candidate.status == RecordStatus.CANDIDATE
    assert candidate.confidence.value == "MANUAL_UNVERIFIED"
    assert candidate.target_master == "ShippingRule"
    assert rule is not None
    assert rule.scope_type.value == "CASE_SPECIFIC"
    assert len(store.candidates) == 1
    assert store.candidates[0].status == RecordStatus.CANDIDATE
