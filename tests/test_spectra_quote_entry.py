import pytest

import ui.quote_control as quote_control
from agents.price_master import import_price_master
from agents.quote_approval import validate_for_approval
from agents.quote_builder import inspect_quote_economics
from agents.spectra_quote_entry import (
    SpectraQuoteEntryError,
    create_spectra_quote_draft,
)
from models import (
    CustomerPresentationMode,
    PriceMasterType,
    PriceSourceType,
    QuoteDraftStatus,
    RequirementType,
    ShippingType,
)
from tests.price_book_fixtures import quote_calc_formula_book
from tests.test_price_master_ui import _open_quote_page, _texts
from tests.test_spectra_price_master import spectra_workbook


def _activate_spectra(*, msrp=202500, dealer=141750):
    outcome = import_price_master(
        PriceMasterType.SPECTRA_GOLD,
        "SPECTRA_GOLD.xlsx",
        spectra_workbook(
            first_msrp=msrp,
            first_gold=dealer,
            first_description="SPECTRA Base Package",
        ).getvalue(),
    )
    return outcome.record


def _activate_quote_calc():
    return import_price_master(
        PriceMasterType.QUOTE_CALC,
        "QUOTE_CALC.xlsx",
        quote_calc_formula_book().getvalue(),
    ).record


def _create(**overrides):
    values = {
        "customer": "Example Customer",
        "title": "",
        "sku": "SPECTRA0001",
        "quantity": 1,
        "exchange_rate": 160,
        "international_shipping_usd": 2500,
        "domestic_shipping_jpy": 0,
        "sales_candidates": None,
    }
    values.update(overrides)
    return create_spectra_quote_draft(**values)


def test_active_spectra_exact_sku_creates_draft_with_official_price_and_provenance():
    record = _activate_spectra()
    _activate_quote_calc()

    draft = _create()

    line = draft.configuration_lines[0]
    snapshot = line.manufacturer_price_snapshot
    assert draft.configuration_name == "SPECTRA"
    assert draft.customer == "Example Customer"
    assert draft.title == "SPECTRA SPECTRA0001 御見積"
    assert draft.exchange_rate == 160
    assert line.quantity == 1
    assert line.manufacturer_description == "SPECTRA Base Package"
    assert line.requirement_type == RequirementType.BASE_PRODUCT
    assert line.customer_presentation_status == CustomerPresentationMode.SEPARATE_LINE
    assert line.dealer_price_usd == 141750
    assert snapshot.manufacturer_msrp_usd == 202500
    assert snapshot.manufacturer_dealer_price_usd == 141750
    assert snapshot.price_source_type == PriceSourceType.OFFICIAL_PRICE_BOOK
    assert snapshot.price_book == "SPECTRA_GOLD"
    assert snapshot.price_master_import_id == record.import_id
    assert snapshot.price_master_sha256 == record.sha256
    assert snapshot.price_master_filename == "SPECTRA_GOLD.xlsx"
    assert line.standard_sales_price_candidate_jpy is None
    assert draft.status == QuoteDraftStatus.REVIEW_REQUIRED
    assert validate_for_approval(draft).can_approve is False


@pytest.mark.parametrize("sku", ["spectra0001", "SPECTRA000"])
def test_spectra_entry_requires_exact_active_master_sku(sku):
    _activate_spectra()
    _activate_quote_calc()

    with pytest.raises(SpectraQuoteEntryError, match="SKU_NOT_FOUND"):
        _create(sku=sku)


def test_spectra_entry_trims_outer_whitespace_without_changing_case():
    _activate_spectra()
    _activate_quote_calc()

    draft = _create(sku="  SPECTRA0001  ")

    assert draft.configuration_lines[0].manufacturer_sku == "SPECTRA0001"


def test_unpriced_spectra_sku_creates_review_draft_without_zero_cost():
    _activate_spectra()
    _activate_quote_calc()

    draft = _create(sku="ZERO-BOTH")
    line = draft.configuration_lines[0]

    assert line.manufacturer_price_snapshot.price_source_type == PriceSourceType.UNKNOWN
    assert line.dealer_price_usd is None
    assert line.dealer_cost_jpy is None
    assert line.landed_cost_jpy is None
    assert draft.status == QuoteDraftStatus.REVIEW_REQUIRED
    assert validate_for_approval(draft).can_approve is False


@pytest.mark.parametrize(
    "international, domestic",
    [
        (None, None),
        (None, 0),
        (100, None),
    ],
)
def test_pending_shipping_keeps_total_landed_unresolved_and_blocks_approval(
    international, domestic
):
    _activate_spectra()
    _activate_quote_calc()

    draft = _create(
        international_shipping_usd=international,
        domestic_shipping_jpy=domestic,
    )
    economics = inspect_quote_economics(draft)

    pending = next(item for item in draft.shipping_lines if item.source_type == "HUMAN_INPUT_PENDING")
    assert pending.cost_jpy is None
    assert economics["total_landed"] is None
    assert draft.status == QuoteDraftStatus.REVIEW_REQUIRED
    assert validate_for_approval(draft).can_approve is False


def test_explicit_shipping_inputs_are_used_without_inference():
    _activate_spectra()
    _activate_quote_calc()

    draft = _create(international_shipping_usd=1234.5, domestic_shipping_jpy=0)
    shipping = draft.shipping_lines[0]

    assert len(draft.shipping_lines) == 1
    assert shipping.shipping_type == ShippingType.CUSTOM
    assert shipping.rate_usd == 1234.5
    assert shipping.exchange_rate == 160
    assert shipping.cost_jpy == 197520
    assert shipping.source_type == "HUMAN_INPUT"
    assert draft.configuration_lines[0].domestic_shipping_jpy == 0


@pytest.mark.parametrize(
    "overrides, code",
    [
        ({"customer": ""}, "CUSTOMER_REQUIRED"),
        ({"quantity": 0}, "QUANTITY_INVALID"),
        ({"international_shipping_usd": -1}, "INTERNATIONAL_SHIPPING_INVALID"),
        ({"domestic_shipping_jpy": -1}, "DOMESTIC_SHIPPING_INVALID"),
    ],
)
def test_invalid_spectra_inputs_fail_closed(overrides, code):
    _activate_spectra()
    _activate_quote_calc()

    with pytest.raises(SpectraQuoteEntryError, match=code):
        _create(**overrides)


def test_missing_active_master_or_quote_calc_fails_closed():
    with pytest.raises(SpectraQuoteEntryError, match="SPECTRA_MASTER_MISSING"):
        _create()

    _activate_spectra()
    with pytest.raises(SpectraQuoteEntryError, match="QUOTE_CALC_MISSING"):
        _create()


def test_spectra_quote_entry_ui_does_not_load_dt40_or_pt30(monkeypatch):
    _activate_spectra()
    _activate_quote_calc()

    def fail_if_all_manufacturer_books_are_loaded():
        raise AssertionError("SPECTRA entry must not load DT40/PT30")

    monkeypatch.setattr(
        quote_control,
        "active_price_books",
        fail_if_all_manufacturer_books_are_loaded,
    )
    at = _open_quote_page()

    assert "SPECTRA 見積下書き" in _texts(at)
    at.text_input(key="spectra_quote_customer").set_value("UI Customer")
    at.text_input(key="spectra_quote_sku").set_value("SPECTRA0001")
    at.text_input(key="spectra_quote_international_shipping").set_value("2500")
    at.text_input(key="spectra_quote_domestic_shipping").set_value("0")
    at.button(key="spectra_quote_create").click().run()

    assert not at.exception
    draft = at.session_state["quote_draft"]
    assert draft.customer == "UI Customer"
    assert draft.configuration_name == "SPECTRA"
    assert draft.configuration_lines[0].manufacturer_sku == "SPECTRA0001"
    assert draft.configuration_lines[0].dealer_price_usd == 141750
    assert (
        draft.configuration_lines[0].manufacturer_price_snapshot.manufacturer_msrp_usd
        == 202500
    )
