import json

import pytest

from agents.general_quote_entry import GeneralQuoteEntryError, create_general_quote_draft
from agents.price_master import SALES_MASTER_MISSING_WARNING, import_price_master
from agents.quote_approval import validate_for_approval
from agents.quote_builder import inspect_quote_economics
from agents.spectra_quote_entry import create_spectra_quote_draft
from models import (
    CustomerPresentationMode,
    PriceMasterType,
    PriceSourceType,
    PricingPolicyType,
    RequirementType,
    ShippingType,
)
from tests.price_book_fixtures import (
    build_workbook,
    pricing_policy_manufacturer_book,
    pricing_policy_master_book,
    quote_calc_formula_book,
)
from tests.test_quote_builder import _line as _ihi_line
from tests.test_quote_builder import _mag_v1, _v1_mag_draft
from tests.test_spectra_price_master import spectra_workbook
from ui.quote_control import _sales_candidates_for_rate


def _book(master_type, sheets):
    label = master_type.value
    return build_workbook(sheets).getvalue(), label


def _activate(master_type, sheets, name=None):
    data, label = _book(master_type, sheets)
    return import_price_master(
        master_type,
        name or f"{label}.xlsx",
        data,
    ).record


def _priced_sheet(label, rows):
    return [["Part Number", "Description", "MSRP", label, "Notes:"], *rows]


def _activate_dt40(rows=None):
    rows = rows or [["DT-100", "Deep Trekker Camera", 10000, 6000, None]]
    return _activate(PriceMasterType.DT40, {"PHOTON": _priced_sheet("DT40", rows)})


def _activate_pt30(rows=None):
    rows = rows or [["PT-200", "PipeTrekker Reel", 8000, 4800, None]]
    return _activate(PriceMasterType.PT30, {"A-200": _priced_sheet("PT30", rows)})


def _activate_quote_calc():
    return import_price_master(
        PriceMasterType.QUOTE_CALC,
        "QUOTE_CALC.xlsx",
        quote_calc_formula_book().getvalue(),
    ).record


def _create(**overrides):
    values = {
        "customer": "一般顧客",
        "title": "一般案件",
        "lines": [{"sku": "DT-100", "quantity": 1}],
        "exchange_rate": 160,
        "international_shipping_usd": 100,
        "domestic_shipping_jpy": 0,
        "sales_candidates": None,
    }
    values.update(overrides)
    return create_general_quote_draft(**values)


def _ready():
    record = _activate_dt40()
    calc = _activate_quote_calc()
    return record, calc


def test_customer_is_required():
    _ready()
    with pytest.raises(GeneralQuoteEntryError, match="CUSTOMER_REQUIRED"):
        _create(customer="  ")


def test_zero_lines_are_rejected():
    _ready()
    with pytest.raises(GeneralQuoteEntryError, match="NO_LINES"):
        _create(lines=[])


def test_exact_sku_creates_a_draft():
    record, calc = _ready()
    draft = _create()
    line = draft.configuration_lines[0]
    snapshot = line.manufacturer_price_snapshot

    assert line.manufacturer_sku == "DT-100"
    assert line.quantity == 1
    assert line.dealer_price_usd == 6000
    assert snapshot.price_source_type == PriceSourceType.OFFICIAL_PRICE_BOOK
    assert snapshot.price_book == "DT40"
    assert snapshot.price_master_import_id == record.import_id
    assert any(calc.import_id in item for item in draft.source_references)
    assert not any("SO_MASTER" in item for item in draft.source_references)


def test_only_existing_trim_normalization_is_applied():
    _ready()
    draft = _create(lines=[{"sku": "  DT-100  ", "quantity": 1}])
    assert draft.configuration_lines[0].manufacturer_sku == "DT-100"

    with pytest.raises(GeneralQuoteEntryError, match="SKU_NOT_FOUND") as error:
        _create(lines=[{"sku": "dt-100", "quantity": 1}])
    assert error.value.sku == "dt-100"


def test_similar_sku_is_rejected_without_a_draft():
    _ready()
    with pytest.raises(GeneralQuoteEntryError, match="SKU_NOT_FOUND") as error:
        _create(lines=[{"sku": "DT-1000", "quantity": 1}])
    assert error.value.sku == "DT-1000"


def test_price_conflict_is_rejected():
    _activate(
        PriceMasterType.DT40,
        {
            "PHOTON": _priced_sheet("DT40", [["DT-100", "Camera A", 10000, 6000, "a"]]),
            "MISC": _priced_sheet("DT40", [["DT-100", "Camera B", 11000, 7000, "b"]]),
            "KEEP": _priced_sheet("DT40", [["DT-KEEP", "Kept", 100, 60, None]]),
        },
    )
    _activate_quote_calc()
    with pytest.raises(GeneralQuoteEntryError, match="PRICE_CONFLICT"):
        _create()


def test_obsolete_sku_is_rejected():
    _activate(
        PriceMasterType.DT40,
        {
            "PHOTON": _priced_sheet("DT40", [["DT-KEEP", "Kept", 100, 60, None]]),
            "REVOLUTION-OBSOLETE": _priced_sheet("DT40", [["DT-OLD", "Old camera", 500, 300, "obsolete"]]),
        },
    )
    _activate_quote_calc()
    with pytest.raises(GeneralQuoteEntryError, match="OBSOLETE_SKU"):
        _create(lines=[{"sku": "DT-OLD", "quantity": 1}])


def test_missing_dealer_price_is_rejected():
    _activate(
        PriceMasterType.DT40,
        {
            "PHOTON": _priced_sheet(
                "DT40",
                [
                    ["DT-KEEP", "Kept", 100, 60, None],
                    ["DT-NODEALER", "No dealer", 1000, None, None],
                ],
            )
        },
    )
    _activate_quote_calc()
    with pytest.raises(GeneralQuoteEntryError, match="DEALER_PRICE_MISSING"):
        _create(lines=[{"sku": "DT-NODEALER", "quantity": 1}])


@pytest.mark.parametrize("quantity", [0, -1, 1.5, True, "2"])
def test_invalid_quantity_is_rejected(quantity):
    _ready()
    with pytest.raises(GeneralQuoteEntryError, match="QUANTITY_INVALID"):
        _create(lines=[{"sku": "DT-100", "quantity": quantity}])


def test_duplicate_skus_sum_quantities_and_keep_first_position():
    _activate_dt40(
        [
            ["DT-100", "Deep Trekker Camera", 10000, 6000, None],
            ["DT-200", "Deep Trekker Light", 2000, 1200, None],
        ]
    )
    _activate_quote_calc()
    draft = _create(
        lines=[
            {"sku": "DT-100", "quantity": 1},
            {"sku": "DT-200", "quantity": 2},
            {"sku": " DT-100 ", "quantity": 2},
        ]
    )
    assert [(line.manufacturer_sku, line.quantity) for line in draft.configuration_lines] == [
        ("DT-100", 3),
        ("DT-200", 2),
    ]


def test_dt40_and_pt30_lines_share_one_draft():
    dt40 = _activate_dt40()
    pt30 = _activate_pt30()
    _activate_quote_calc()
    draft = _create(
        lines=[
            {"sku": "DT-100", "quantity": 1},
            {"sku": "PT-200", "quantity": 4},
        ]
    )
    assert [line.manufacturer_sku for line in draft.configuration_lines] == ["DT-100", "PT-200"]
    assert draft.configuration_lines[1].quantity == 4
    assert draft.configuration_lines[0].manufacturer_description == "Deep Trekker Camera"
    assert draft.configuration_lines[1].manufacturer_description == "PipeTrekker Reel"
    books = {line.manufacturer_price_snapshot.price_book for line in draft.configuration_lines}
    assert books == {"DT40", "PT30"}
    joined = " ".join(draft.source_references)
    assert dt40.import_id in joined
    assert pt30.import_id in joined


def test_spectra_master_sku_is_not_used():
    import_price_master(
        PriceMasterType.SPECTRA_GOLD,
        "SPECTRA_GOLD.xlsx",
        spectra_workbook().getvalue(),
    )
    _ready()
    with pytest.raises(GeneralQuoteEntryError, match="SKU_NOT_FOUND") as error:
        _create(lines=[{"sku": "SPECTRA0001", "quantity": 1}])
    assert error.value.sku == "SPECTRA0001"

    spectra = create_spectra_quote_draft(
        customer="SPECTRA顧客",
        title="",
        sku="SPECTRA0001",
        quantity=1,
        exchange_rate=160,
        international_shipping_usd=None,
        domestic_shipping_jpy=None,
    )
    assert spectra.configuration_name == "SPECTRA"
    assert spectra.configuration_lines[0].manufacturer_sku == "SPECTRA0001"


def test_case_id_stays_empty_unless_supplied():
    _ready()
    draft = _create()
    assert draft.case_id is None
    supplied = _create(case_id="CASE-NEXT")
    assert supplied.case_id == "CASE-NEXT"


def test_customer_title_description_and_presentation_are_kept():
    _ready()
    draft = _create(customer="  港湾株式会社  ", title="  検査案件  ")
    line = draft.configuration_lines[0]
    assert draft.customer == "港湾株式会社"
    assert draft.title == "検査案件"
    assert draft.configuration_name == "CUSTOM"
    assert line.manufacturer_description == "Deep Trekker Camera"
    assert line.customer_display_name == "Deep Trekker Camera"
    assert line.requirement_type == RequirementType.MANUAL_COMPONENT
    assert line.customer_presentation_status == CustomerPresentationMode.SEPARATE_LINE
    assert "IHI_QUOTE_001" not in json.dumps(draft.model_dump(mode="json"))


def test_active_so_master_candidate_is_applied_without_guessing_when_absent():
    import_price_master(
        PriceMasterType.DT40,
        "dt40.xlsx",
        pricing_policy_manufacturer_book().getvalue(),
    )
    _activate_quote_calc()
    missing = _create(lines=[{"sku": "9680-BASE", "quantity": 1}])
    missing_line = missing.configuration_lines[0]
    assert missing_line.standard_sales_price_candidate_jpy is None
    assert missing_line.dealer_price_usd == 10434.6
    assert any(SALES_MASTER_MISSING_WARNING in item for item in missing_line.warnings)
    assert validate_for_approval(missing).can_approve is False

    import_price_master(
        PriceMasterType.SO_MASTER,
        "SpaceOne master.xlsx",
        pricing_policy_master_book().getvalue(),
    )
    sales = _sales_candidates_for_rate(160)
    priced = _create(lines=[{"sku": "9680-BASE", "quantity": 1}], sales_candidates=sales)
    line = priced.configuration_lines[0]
    assert line.standard_sales_price_candidate_jpy == 3339000
    assert line.pricing_policy_type == PricingPolicyType.MSRP_MULTIPLIER
    assert any("SO_MASTER" in item for item in priced.source_references)
    assert not any(SALES_MASTER_MISSING_WARNING in item for item in line.warnings)


def test_blank_shipping_stays_unresolved_and_entered_shipping_is_used():
    _ready()
    pending = _create(international_shipping_usd=None, domestic_shipping_jpy=None)
    pending_line = next(item for item in pending.shipping_lines if item.source_type == "HUMAN_INPUT_PENDING")
    assert pending_line.cost_jpy is None
    assert inspect_quote_economics(pending)["total_landed"] is None
    assert validate_for_approval(pending).can_approve is False

    entered = _create(international_shipping_usd=1234.5, domestic_shipping_jpy=0)
    shipping = entered.shipping_lines[0]
    assert len(entered.shipping_lines) == 1
    assert shipping.shipping_type == ShippingType.CUSTOM
    assert shipping.rate_usd == 1234.5
    assert shipping.cost_jpy == 197520
    assert shipping.source_type == "HUMAN_INPUT"
    assert entered.configuration_lines[0].domestic_shipping_jpy == 0
    assert entered.exchange_rate == 160


def test_missing_master_or_policy_or_rate_fails_closed():
    with pytest.raises(GeneralQuoteEntryError, match="MANUFACTURER_MASTER_MISSING"):
        _create()
    _activate_dt40()
    with pytest.raises(GeneralQuoteEntryError, match="QUOTE_CALC_MISSING"):
        _create()
    _activate_quote_calc()
    with pytest.raises(GeneralQuoteEntryError, match="EXCHANGE_RATE_INVALID"):
        _create(exchange_rate=0)
    with pytest.raises(GeneralQuoteEntryError, match="SKU_REQUIRED"):
        _create(lines=[{"sku": "  ", "quantity": 1}])


def test_known_ihi_standard_candidate_stays_unchanged():
    draft = _v1_mag_draft(_mag_v1())
    assert _ihi_line(draft, "9701-MAG-4K").standard_sales_price_candidate_jpy == 6627000
    assert draft.case_id == "IHI_QUOTE_001"
