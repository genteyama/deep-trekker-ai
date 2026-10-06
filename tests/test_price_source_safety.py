from pathlib import Path

from streamlit.testing.v1 import AppTest

from agents.landed_cost import (
    IHI_DEVELOPMENT_DEALER_VALUES,
    build_ihi_landed_cost_scenario,
    calculate_landed_cost_scenario,
    policy_from_inputs,
    resolve_ihi_dealer_values,
)
from agents.quote_approval import (
    QuoteApprovalError,
    all_confirmations,
    apply_ihi_photon_human_final_fixture,
    apply_selected_remarks,
    approve_quote,
    create_revision_draft,
    validate_for_approval,
)
from agents.quote_builder import build_ihi_quote_draft, build_quote_draft
from agents.quote_control_agent import import_price_book
from agents.sku_link import is_official_price_snapshot, price_source_type_of
from models import (
    ApprovedQuoteSnapshot,
    DomesticShippingMode,
    InsuranceMode,
    PriceSourceType,
    QuoteDraftStatus,
    QuotePriceSnapshot,
)
from tests.price_book_fixtures import build_workbook
from tests.test_quote_approval import _approve, _ready_photon
from ui.quote_steps import non_official_price_lines, price_source_display

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
BLOCK_MARKER = "Official manufacturer price book is not set"
WORKSPACE_LABELS = {
    "price_sources": {
        "OFFICIAL_PRICE_BOOK": "{price_book}",
        "DEVELOPMENT_REFERENCE": "開発用参考価格（正式価格表ではありません）",
        "MANUAL_REVIEW": "手入力価格（要確認）",
        "UNKNOWN": "未確認",
    },
    "price_states": {
        "OFFICIAL_PRICE_BOOK": "正式価格表",
        "DEVELOPMENT_REFERENCE": "正式価格表なし / 要確認",
        "MANUAL_REVIEW": "価格確認が必要",
        "UNKNOWN": "価格確認が必要",
    },
}


def _policy():
    return policy_from_inputs(
        import_tax_rate=0.1,
        insurance_mode=InsuranceMode.PERCENTAGE,
        insurance_rate=0.03,
        shipping_markup_multiplier=1.2,
        domestic_shipping_jpy=10000,
        domestic_shipping_mode=DomesticShippingMode.REVIEW_REQUIRED,
    )


def _development_photon_draft():
    # Same inputs as the IHI PHOTON button when no official DT40/PT30 file is available.
    scenario, _ = build_ihi_landed_cost_scenario(
        "PHOTON",
        exchange_rate=170,
        policy=_policy(),
        dealer_values=resolve_ihi_dealer_values([]),
        sales_candidates=[],
        price_book_candidates=[],
    )
    return build_ihi_quote_draft("PHOTON", scenario, [], tax_rate=0.1)


def _pt30_book():
    return import_price_book(
        build_workbook(
            {
                "A-200": [
                    ["Part Number", "Description", "MSRP", "PT30", "Notes:"],
                    ["PT-A200-BASE", "PipeTrekker A-200 base", 40000, 28000, None],
                ],
            }
        ),
        source_price_book="PT30",
        version="official-test",
    )


def _pt30_draft(product_inputs, candidates):
    scenario, _ = calculate_landed_cost_scenario(
        scenario_id="pt30-test",
        case_id="PT30-CASE",
        name="PT30",
        exchange_rate=170,
        policy=_policy(),
        product_inputs=product_inputs,
        shipping_lines=[],
        insurance_mode=InsuranceMode.PERCENTAGE,
        domestic_shipping_jpy=10000,
        price_book_candidates=candidates,
    )
    presentation = {
        "product_presentations": [
            {"sku": item["sku"], "requirement_type": "BASE_PRODUCT", "presentation_mode": "SEPARATE_LINE"}
            for item in product_inputs
        ]
    }
    return build_quote_draft(
        quote_draft_id="pt30-draft",
        case_id="PT30-CASE",
        customer="Test",
        title="PT30",
        configuration_name="PT30",
        landed_scenario=scenario,
        sales_candidates=[],
        presentation=presentation,
        tax_rate=0.1,
    )


def test_development_dealer_values_are_never_labelled_as_an_official_price_book():
    for values in IHI_DEVELOPMENT_DEALER_VALUES.values():
        assert "price_book" not in values
        assert values["price_source_type"] == PriceSourceType.DEVELOPMENT_REFERENCE.value


def test_without_official_dt40_development_prices_are_not_treated_as_official():
    draft = _development_photon_draft()

    assert draft.configuration_lines
    for line in draft.configuration_lines:
        snapshot = line.manufacturer_price_snapshot
        assert snapshot.price_source_type == PriceSourceType.DEVELOPMENT_REFERENCE
        assert snapshot.price_book != "DT40"
        assert not is_official_price_snapshot(snapshot)
    assert draft.status == QuoteDraftStatus.REVIEW_REQUIRED
    assert len(non_official_price_lines(draft)) == len(draft.configuration_lines)


def test_development_prices_block_approval_even_after_final_prices_are_entered():
    draft = _development_photon_draft()
    apply_ihi_photon_human_final_fixture(draft)
    apply_selected_remarks(draft, [item.text for item in draft.remark_candidates])

    assert draft.status == QuoteDraftStatus.REVIEW_REQUIRED
    result = validate_for_approval(draft)
    assert result.can_approve is False
    assert any(BLOCK_MARKER in item and "DEVELOPMENT_REFERENCE" in item for item in result.critical_warnings)
    try:
        approve_quote(draft, approved_by="test", confirmations=all_confirmations())
    except QuoteApprovalError:
        pass
    else:
        raise AssertionError("Development reference prices must not be approvable.")

    draft.status = QuoteDraftStatus.READY_FOR_APPROVAL
    forced = validate_for_approval(draft)
    assert forced.can_approve is False
    assert forced.blocking_reason == "Critical warnings block approval."


def test_unknown_price_source_blocks_approval():
    draft = _pt30_draft([{"sku": "PT-UNVERIFIED", "dealer_price_usd": 1000, "quantity": 1}], candidates=[])
    snapshot = draft.configuration_lines[0].manufacturer_price_snapshot

    assert snapshot.price_source_type == PriceSourceType.UNKNOWN
    assert draft.status == QuoteDraftStatus.REVIEW_REQUIRED
    result = validate_for_approval(draft)
    assert result.can_approve is False
    assert any(BLOCK_MARKER in item and "UNKNOWN" in item for item in result.critical_warnings)


def test_official_dt40_snapshot_remains_approvable():
    draft = _ready_photon()

    assert all(
        line.manufacturer_price_snapshot.price_source_type == PriceSourceType.OFFICIAL_PRICE_BOOK
        and line.manufacturer_price_snapshot.price_book == "DT40"
        for line in draft.configuration_lines
    )
    assert draft.status == QuoteDraftStatus.READY_FOR_APPROVAL
    assert validate_for_approval(draft).can_approve is True
    _, snapshot = _approve(draft)
    assert all(is_official_price_snapshot(item) for item in snapshot.manufacturer_price_snapshots)


def test_pt30_official_price_book_is_recognised_and_missing_pt30_is_not():
    book = _pt30_book()
    official = _pt30_draft([{"sku": "PT-A200-BASE", "quantity": 1}], candidates=book.candidates)
    official_snapshot = official.configuration_lines[0].manufacturer_price_snapshot
    assert official_snapshot.price_book == "PT30"
    assert official_snapshot.price_source_type == PriceSourceType.OFFICIAL_PRICE_BOOK
    assert not any(BLOCK_MARKER in item for item in official.warnings)

    missing = _pt30_draft(
        [{"sku": "PT-NOT-IN-BOOK", "dealer_price_usd": 500, "quantity": 1, "price_source_type": "DEVELOPMENT_REFERENCE"}],
        candidates=book.candidates,
    )
    missing_snapshot = missing.configuration_lines[0].manufacturer_price_snapshot
    assert missing_snapshot.price_source_type == PriceSourceType.DEVELOPMENT_REFERENCE
    assert missing_snapshot.price_book is None
    assert validate_for_approval(missing).can_approve is False


def test_scenario_input_cannot_claim_official_price_book():
    draft = _pt30_draft(
        [{"sku": "PT-A200-BASE", "dealer_price_usd": 28000, "price_book": "PT30", "price_source_type": "OFFICIAL_PRICE_BOOK"}],
        candidates=[],
    )
    snapshot = draft.configuration_lines[0].manufacturer_price_snapshot

    assert snapshot.price_source_type == PriceSourceType.UNKNOWN
    assert validate_for_approval(draft).can_approve is False


def test_legacy_snapshots_without_source_type_keep_their_meaning():
    legacy_official = QuotePriceSnapshot(
        snapshot_id="s1", sku="9680-BASE", price_book="DT40", manufacturer_dealer_price_usd=10434.6, source_reference="DT40"
    )
    legacy_scenario = QuotePriceSnapshot(
        snapshot_id="s2", sku="9680-BASE", price_book="DT40", manufacturer_dealer_price_usd=10434.6, source_reference="scenario-input"
    )

    assert price_source_type_of(legacy_official) == PriceSourceType.OFFICIAL_PRICE_BOOK
    assert price_source_type_of(legacy_scenario) == PriceSourceType.UNKNOWN
    assert price_source_type_of(None) == PriceSourceType.UNKNOWN


def test_existing_approved_snapshot_loads_and_revises_without_source_type():
    _, snapshot = _approve(_ready_photon())
    payload = snapshot.model_dump(mode="json")
    for item in payload["manufacturer_price_snapshots"]:
        item.pop("price_source_type")
    for line in payload["configuration_snapshot"]:
        line["manufacturer_price_snapshot"].pop("price_source_type")
    legacy = ApprovedQuoteSnapshot.model_validate(payload)

    assert legacy.total_jpy == snapshot.total_jpy
    revision = create_revision_draft(legacy)
    assert all(is_official_price_snapshot(line.manufacturer_price_snapshot) for line in revision.configuration_lines)
    assert not any(BLOCK_MARKER in item for item in revision.warnings)


def test_price_source_display_labels():
    official = _ready_photon().configuration_lines[0]
    development = _development_photon_draft().configuration_lines[0]

    assert price_source_display(WORKSPACE_LABELS, official) == ("DT40", "正式価格表")
    assert price_source_display(WORKSPACE_LABELS, development) == (
        "開発用参考価格（正式価格表ではありません）",
        "正式価格表なし / 要確認",
    )


def test_ihi_button_without_official_price_books_shows_reference_only(tmp_path, monkeypatch):
    from agents.price_master import get_active_master
    from models import PriceMasterType

    # The per-test database starts with no active price masters, so no official file can be used.
    assert all(get_active_master(master_type) is None for master_type in PriceMasterType)

    at = AppTest.from_file(str(APP_PATH)).run()
    at.button(key="open_quote_control").click().run()
    at.button(key="ihi_photon_draft").click().run()

    assert not at.exception
    draft = at.session_state["quote_draft"]
    assert draft.status == QuoteDraftStatus.REVIEW_REQUIRED
    assert all(
        line.manufacturer_price_snapshot.price_source_type == PriceSourceType.DEVELOPMENT_REFERENCE
        for line in draft.configuration_lines
    )
    errors = " ".join(item.value for item in at.error)
    assert "正式価格表が未設定です" in errors
    visible = " ".join(item.value for item in at.markdown)
    assert "開発用参考価格（正式価格表ではありません）" in visible
    assert not any(getattr(item, "key", None) == "approve_quote_snapshot" for item in at.button)
