from agents.update_inbox_agent import (
    UpdateInboxStore,
    create_manual_candidate,
    create_shipping_rule,
    organize_pasted_update,
)
from models import (
    DestinationRegion,
    RecordStatus,
    SHIPPING_RULE_PRIORITY,
    ShippingScopeType,
    ShippingType,
    UpdateCategory,
    UpdateSourceType,
    YesNoUnknown,
)


def test_standard_shipping_rule_stays_candidate_with_unknown_flags():
    rule = create_shipping_rule(
        "ship-std-001",
        shipping_type=ShippingType.SMALL_BOX,
        destination_region=DestinationRegion.GLOBAL,
        rate_usd=1356.00,
        source_type=UpdateSourceType.DEALER_UPDATE_EMAIL.value,
        source_reference="dealer-update-2026-09",
    )

    assert rule.status == RecordStatus.CANDIDATE
    assert rule.status != RecordStatus.APPROVED
    assert rule.dangerous_goods == YesNoUnknown.UNKNOWN
    assert rule.battery_included == YesNoUnknown.UNKNOWN
    assert rule.scope_type == ShippingScopeType.STANDARD
    assert rule.rate_usd == 1356.00


def test_case_specific_shipping_does_not_replace_standard_rule():
    store = UpdateInboxStore()
    source, candidates, standard_rules = organize_pasted_update(
        source_title="Deep Trekker Dealer Update: September Edition",
        source_text="Large Box Shipping Globally 2,922.15",
        store=store,
    )
    _, manual, case_rule = create_manual_candidate(
        category=UpdateCategory.SHIPPING,
        summary="REVOLUTION Retrieval Kit shipping is 620 USD this time",
        product="REVOLUTION Retrieval Kit",
        new_value="620",
        unit="USD",
        source_sender="Christianne",
        notes="Non-DG for this case",
        case_id="IHI-20260926",
        source_type=UpdateSourceType.DIRECT_EMAIL,
        store=store,
    )

    assert source.update_source_id
    assert candidates
    assert all(rule.scope_type == ShippingScopeType.STANDARD for rule in standard_rules)
    assert case_rule is not None
    assert case_rule.scope_type == ShippingScopeType.CASE_SPECIFIC
    assert case_rule.rate_usd == 620
    assert case_rule.product_scope == "REVOLUTION Retrieval Kit"
    assert case_rule.dangerous_goods == YesNoUnknown.UNKNOWN
    assert case_rule.status == RecordStatus.CANDIDATE
    assert manual.status == RecordStatus.CANDIDATE
    assert all(rule.shipping_rule_id != case_rule.shipping_rule_id for rule in standard_rules)
    assert any(rule.rate_usd == 1356.00 for rule in standard_rules)
    assert any(rule.rate_usd == 1356.00 for rule in store.shipping_rules)
    assert sum(1 for rule in store.shipping_rules if rule.shipping_rule_id == case_rule.shipping_rule_id) == 1
    assert SHIPPING_RULE_PRIORITY[0] == "SUPPLIER_QUOTE_CASE_SPECIFIC"
