from data.golden_cases.loader import IHI_QUOTE_001, load_quote_golden_case
from models import (
    CustomerQuote,
    ShippingType,
    SkuMappingSource,
    SupplierQuote,
    SupplierQuoteValidationStatus,
)


def _load():
    return load_quote_golden_case(IHI_QUOTE_001)


def _models():
    case = _load()
    return (
        SupplierQuote.model_validate(case["supplier_quote"]),
        CustomerQuote.model_validate(case["mag_customer_quote"]),
        CustomerQuote.model_validate(case["photon_customer_quote"]),
        case["expected_validation"],
    )


def _box_qty(shipping, shipping_type: ShippingType) -> int:
    return sum(
        box.quantity or 0
        for box in (shipping.boxes if shipping else [])
        if box.shipping_type == shipping_type
    )


def test_ihi_supplier_quote_fixture_loads():
    supplier, _, _, expected = _models()

    assert supplier.case_id == "IHI_QUOTE_001"
    assert supplier.quote_reference == "20260925-142434902"
    assert supplier.supplier == "Deep Trekker"
    assert supplier.currency == "USD"
    assert expected["case_id"] == "IHI_QUOTE_001"
    assert expected["display_name"] == "IHI検査計測 MAG / PHOTON 肉厚測定提案"


def test_supplier_quote_total_is_88600():
    supplier, _, _, expected = _models()
    line_total = sum(line.line_total_usd or 0 for line in supplier.lines)
    shipping_total = sum(line.line_total_usd or 0 for line in supplier.shipping_lines)
    insurance = supplier.insurance.amount_usd if supplier.insurance else 0

    assert supplier.total_usd == 88600
    assert expected["supplier_quote_expectations"]["total_usd"] == 88600
    assert line_total + shipping_total + insurance == 88600


def test_mag_and_photon_customer_quote_totals():
    _, mag, photon, expected = _models()
    mag_expected = expected["mag_customer_quote_expectations"]
    photon_expected = expected["photon_customer_quote_expectations"]

    assert mag.subtotal_ex_tax_jpy == 12648000
    assert mag.tax_jpy == 1264800
    assert mag.total_jpy == 13912800
    assert mag.subtotal_ex_tax_jpy + mag.tax_jpy == mag.total_jpy
    assert mag_expected["subtotal_ex_tax_jpy"] == 12648000
    assert mag_expected["total_jpy"] == 13912800

    assert photon.subtotal_ex_tax_jpy == 7160000
    assert photon.tax_jpy == 716000
    assert photon.total_jpy == 7876000
    assert photon.subtotal_ex_tax_jpy + photon.tax_jpy == photon.total_jpy
    assert photon_expected["subtotal_ex_tax_jpy"] == 7160000
    assert photon_expected["total_jpy"] == 7876000


def test_mag_integration_kit_is_missing_from_supplier_quote():
    supplier, mag, _, expected = _models()
    missing = expected["missing_components"][0]
    mag_kit = next(line for line in mag.lines if "INTEGRATION KIT" in (line.description or ""))

    assert missing["code"] == "MISSING_COMPONENT"
    assert missing["present_in_supplier_quote"] is False
    assert missing["present_in_mag_customer_quote"] is True
    assert missing["expected_manufacturer_sku"] is None
    assert all(line.sku != "7851-PHOTON" or "PHOTON" in (line.description or "") for line in supplier.lines)
    assert not any("POWER BRUSH" in (line.description or "") for line in supplier.lines)
    assert mag_kit.manufacturer_sku is None
    assert mag_kit.sku_source == SkuMappingSource.UNMAPPED
    assert any(issue.code == "MISSING_COMPONENT" for issue in supplier.known_issues)


def test_photon_integration_kit_is_on_supplier_quote():
    supplier, _, _, expected = _models()
    photon_kit = next(line for line in supplier.lines if line.sku == "7851-PHOTON")

    assert expected["supplier_quote_expectations"]["photon_integration_kit_present"] is True
    assert expected["supplier_quote_expectations"]["photon_integration_kit_sku"] == "7851-PHOTON"
    assert photon_kit.description
    assert "PHOTON" in photon_kit.description
    assert photon_kit.unit_price_usd == 1746


def test_shipping_differs_across_the_three_sources():
    supplier, mag, photon, expected = _models()
    supplier_ship = supplier.shipping_lines[0]
    mag_ship = expected["mag_customer_quote_expectations"]["shipping"]
    photon_ship = expected["photon_customer_quote_expectations"]["shipping"]

    assert supplier_ship.shipping_type == ShippingType.LARGE_BOX
    assert supplier_ship.quantity == 3
    assert supplier_ship.unit_price_usd == 2922
    assert supplier_ship.line_total_usd == 8766
    assert _box_qty(mag.shipping, ShippingType.LARGE_BOX) == 2
    assert _box_qty(mag.shipping, ShippingType.SMALL_BOX) == 0
    assert mag.shipping.price_jpy == 1190000
    assert mag_ship["large_box"] == 2
    assert _box_qty(photon.shipping, ShippingType.LARGE_BOX) == 1
    assert _box_qty(photon.shipping, ShippingType.SMALL_BOX) == 1
    assert photon.shipping.price_jpy == 870000
    assert photon_ship["large_box"] == 1
    assert photon_ship["small_box"] == 1


def test_insurance_is_separate_on_supplier_and_included_on_customer_quotes():
    supplier, mag, photon, expected = _models()

    assert supplier.insurance is not None
    assert supplier.insurance.amount_usd == 1950
    assert supplier.insurance.is_separate_line is True
    assert expected["supplier_quote_expectations"]["insurance"]["amount_usd"] == 1950
    assert mag.insurance.included_in_sales_price is True
    assert mag.insurance.separate_line is False
    assert photon.insurance.included_in_sales_price is True
    assert photon.insurance.separate_line is False
    assert expected["mag_customer_quote_expectations"]["insurance_included_in_sales_price"] is True
    assert expected["photon_customer_quote_expectations"]["insurance_included_in_sales_price"] is True


def test_supplier_quote_is_not_manufacturer_source_of_truth():
    supplier, _, _, expected = _models()

    assert supplier.is_manufacturer_source_of_truth is False
    assert expected["supplier_quote_is_manufacturer_source_of_truth"] is False
    assert expected["supplier_quote_role"] == "VALIDATION_TARGET"
    assert expected["manufacturer_source_of_truth"] == ["DT40", "PT30"]
    assert expected["customer_quotes_role"] == "EXPECTED_BUSINESS_OUTPUT"
    assert {issue.code for issue in supplier.known_issues} >= {
        "SUPPLIER_PRICE_REQUIRES_VALIDATION",
        "MISSING_COMPONENT",
        "SHIPPING_REQUIRES_CONFIGURATION_REVIEW",
    }
    assert all(
        line.expected_validation_status == SupplierQuoteValidationStatus.REQUIRES_REVIEW
        for line in supplier.lines
    )


def test_customer_quote_lines_do_not_invent_source_skus():
    _, mag, photon, expected = _models()

    assert all(line.manufacturer_sku is None for line in mag.lines)
    assert all(line.manufacturer_sku is None for line in photon.lines)
    assert all(line.sku_source == SkuMappingSource.UNMAPPED for line in mag.lines + photon.lines)
    mag_kit_mapping = next(
        item
        for item in expected["human_verified_sku_mappings"]
        if item["customer_line_description"] == "INTEGRATION KIT, POWER BRUSH CYGNUS GAUGE"
    )
    photon_kit_mapping = next(
        item
        for item in expected["human_verified_sku_mappings"]
        if item["expected_manufacturer_sku"] == "7851-PHOTON"
    )
    assert mag_kit_mapping["expected_manufacturer_sku"] is None
    assert mag_kit_mapping["expected_status"] == "MISSING_COMPONENT"
    assert photon_kit_mapping["sku_source"] == "HUMAN_VERIFIED"


def test_lead_time_is_quote_snapshot_not_technical_fact():
    _, mag, photon, expected = _models()

    assert mag.lead_time.kind == "QUOTE_SNAPSHOT"
    assert mag.lead_time.is_technical_fact is False
    assert mag.lead_time.is_lead_time_master is False
    assert mag.lead_time.text == "発注より5か月程度"
    assert mag.lead_time.as_of == "2026-09-26"
    assert photon.lead_time.kind == "QUOTE_SNAPSHOT"
    assert photon.lead_time.is_technical_fact is False
    assert photon.lead_time.text == "発注より3か月程度"
    assert expected["mag_customer_quote_expectations"]["lead_time"]["is_technical_fact"] is False
    assert expected["photon_customer_quote_expectations"]["lead_time"]["is_lead_time_master"] is False
