from pathlib import Path

from agents.quote_control_agent import SkuMasterStore, import_price_book
from agents.supplier_quote_validation import validate_supplier_quote
from data.golden_cases.loader import IHI_QUOTE_001, load_quote_golden_case
from models import (
    RequiredConfigurationItem,
    SupplierQuote,
    SupplierQuoteInsurance,
    SupplierQuoteLine,
    SupplierQuoteLineKind,
    SupplierQuoteOverallStatus,
    SupplierQuoteShippingLine,
    SupplierQuoteValidationStatus,
    ShippingType,
)
from tests.price_book_fixtures import official_ihi_sku_snapshot_book, supplier_quote_validation_books

OFFICIAL_DT40 = Path("/tmp/dt_price_investigation/DT40.xlsx")
OFFICIAL_PT30 = Path("/tmp/dt_price_investigation/PT30.xlsx")


def _books():
    dt40_file, pt30_file = supplier_quote_validation_books()
    dt40 = import_price_book(dt40_file, source_price_book="DT40", version="test")
    pt30 = import_price_book(pt30_file, source_price_book="PT30", version="test")
    return dt40, pt30


def _quote(*lines, shipping=None, insurance=None, total=None):
    return SupplierQuote(
        supplier_quote_id="SQ-TEST",
        case_id="CASE-TEST",
        quote_reference="TEST-REF",
        total_usd=total,
        lines=list(lines),
        shipping_lines=list(shipping or []),
        insurance=insurance,
    )


def _line(sku, price, description="item", notes=None):
    return SupplierQuoteLine(line_id=sku, sku=sku, description=description, quantity=1, unit_price_usd=price, notes=notes)


def _status(result, sku):
    return next(line.validation_status for line in result.lines if line.sku == sku and line.line_kind.value == "PRODUCT")


def test_dealer_match_and_msrp_match_and_price_mismatch():
    dt40, pt30 = _books()
    quote = _quote(
        _line("DEALER-1", 600),
        _line("MSRP-1", 2000),
        _line("MISMATCH-1", 999),
    )
    result = validate_supplier_quote(quote, dt40, pt30)
    by_sku = {line.sku: line for line in result.lines if line.line_kind == SupplierQuoteLineKind.PRODUCT}

    assert by_sku["DEALER-1"].validation_status == SupplierQuoteValidationStatus.DEALER_MATCH
    assert by_sku["MSRP-1"].validation_status == SupplierQuoteValidationStatus.MSRP_MATCH
    assert by_sku["MISMATCH-1"].validation_status == SupplierQuoteValidationStatus.PRICE_MISMATCH
    assert "supplier_quote_price=999" in by_sku["MISMATCH-1"].warnings[0]
    assert "manufacturer_dealer_price=1800" in by_sku["MISMATCH-1"].warnings[0]
    assert "manufacturer_msrp=3000" in by_sku["MISMATCH-1"].warnings[0]
    assert result.uses_supplier_quote_as_product_cost is False


def test_sku_not_found_conflict_and_obsolete_are_not_price_judged():
    dt40, pt30 = _books()
    quote = _quote(
        _line("UNKNOWN-SKU", 10),
        _line("CONFLICT-1", 60),
        _line("7511-SC-BASE", 600),
    )
    result = validate_supplier_quote(quote, dt40, pt30)

    assert _status(result, "UNKNOWN-SKU") == SupplierQuoteValidationStatus.SKU_NOT_FOUND
    assert _status(result, "CONFLICT-1") == SupplierQuoteValidationStatus.REQUIRES_REVIEW
    assert _status(result, "7511-SC-BASE") == SupplierQuoteValidationStatus.REQUIRES_REVIEW
    assert next(line for line in result.lines if line.sku == "UNKNOWN-SKU").manufacturer_dealer_price_usd is None
    assert next(line for line in result.lines if line.sku == "CONFLICT-1").manufacturer_msrp_usd is None


def test_special_price_is_not_inferred_from_a_price_gap():
    dt40, pt30 = _books()
    quote = _quote(_line("SPECIAL-1", 400))
    result = validate_supplier_quote(quote, dt40, pt30)

    assert _status(result, "SPECIAL-1") == SupplierQuoteValidationStatus.PRICE_MISMATCH
    assert result.summary.special_price_count == 0

    marked = _quote(_line("SPECIAL-1", 400, notes="SPECIAL PRICE approved"))
    declared = validate_supplier_quote(marked, dt40, pt30, special_price_skus=["SPECIAL-1"])
    assert _status(declared, "SPECIAL-1") == SupplierQuoteValidationStatus.SPECIAL_PRICE


def test_no_dealer_discount_requires_manufacturer_notes():
    dt40, pt30 = _books()
    quote = _quote(_line("5608", 10448), _line("NDD-NUM-ONLY", 500))
    result = validate_supplier_quote(quote, dt40, pt30)
    by_sku = {line.sku: line for line in result.lines if line.line_kind == SupplierQuoteLineKind.PRODUCT}

    assert by_sku["5608"].validation_status == SupplierQuoteValidationStatus.NO_DEALER_DISCOUNT
    assert by_sku["NDD-NUM-ONLY"].validation_status == SupplierQuoteValidationStatus.DEALER_MATCH
    assert by_sku["NDD-NUM-ONLY"].validation_status != SupplierQuoteValidationStatus.NO_DEALER_DISCOUNT


def test_shipping_and_insurance_are_not_sku_validated():
    dt40, pt30 = _books()
    quote = _quote(
        _line("DEALER-1", 600),
        shipping=[
            SupplierQuoteShippingLine(
                shipping_type=ShippingType.LARGE_BOX,
                description="Large Box Shipping Globally",
                quantity=3,
                unit_price_usd=2922,
                line_total_usd=8766,
            )
        ],
        insurance=SupplierQuoteInsurance(description="Shipping Insurance", quantity=1, amount_usd=1950),
        total=88600,
    )
    result = validate_supplier_quote(quote, dt40, pt30)
    non_product = [line for line in result.lines if line.validation_status == SupplierQuoteValidationStatus.NON_PRODUCT_COST]

    assert result.summary.shipping_line_count == 1
    assert result.summary.insurance_line_count == 1
    assert all(line.manufacturer_dealer_price_usd is None for line in non_product)
    assert result.supplier_quote_total_usd == 88600


def test_unverified_requirement_is_ignored_and_verified_missing_component_is_detected():
    dt40, pt30 = _books()
    quote = _quote(_line("DEALER-1", 600, description="MAG CRAWLER"))
    unverified = RequiredConfigurationItem(
        configuration_id="ai-guess",
        required_description="Imaginary extra battery",
        human_verified=False,
        match_markers=["BATTERY"],
    )
    verified = RequiredConfigurationItem(
        configuration_id="mag-kit",
        required_description="MAG Cygnus Integration Kit",
        human_verified=True,
        match_markers=["INTEGRATION"],
        exclude_skus=["7851-PHOTON"],
        exclude_markers=["PHOTON"],
    )
    ignored = validate_supplier_quote(quote, dt40, pt30, required_items=[unverified])
    detected = validate_supplier_quote(quote, dt40, pt30, required_items=[verified])

    assert ignored.summary.missing_component_count == 0
    assert detected.summary.missing_component_count == 1
    assert detected.known_configuration_issues[0].code == "MISSING_COMPONENT"


def test_ihi_supplier_quote_validates_against_dt40_without_changing_master_or_total():
    case = load_quote_golden_case(IHI_QUOTE_001)
    quote = SupplierQuote.model_validate(case["supplier_quote"])
    required = [RequiredConfigurationItem.model_validate(item) for item in case["required_configuration"]]
    if OFFICIAL_DT40.exists() and OFFICIAL_PT30.exists():
        dt40 = import_price_book(OFFICIAL_DT40, source_price_book="DT40", version="official")
        pt30 = import_price_book(OFFICIAL_PT30, source_price_book="PT30", version="official")
        books = (dt40, pt30)
    else:
        books = (import_price_book(official_ihi_sku_snapshot_book(), source_price_book="DT40", version="official-snapshot"),)
    store = SkuMasterStore(items=list(books[0].items))
    before_items = store.snapshot()
    before_candidates = [item.model_dump() for item in books[0].candidates]
    before_total = quote.total_usd
    result = validate_supplier_quote(quote, *books, required_items=required)
    product = {line.sku: line for line in result.lines if line.line_kind == SupplierQuoteLineKind.PRODUCT}

    assert quote.total_usd == before_total == 88600
    assert result.supplier_quote_total_usd == 88600
    assert result.uses_supplier_quote_as_product_cost is False
    assert result.status == SupplierQuoteOverallStatus.REVIEW_REQUIRED
    assert product["9701-MAG-4K"].validation_status == SupplierQuoteValidationStatus.MSRP_MATCH
    assert product["9735"].validation_status == SupplierQuoteValidationStatus.MSRP_MATCH
    assert product["9680-BASE"].validation_status == SupplierQuoteValidationStatus.MSRP_MATCH
    assert product["7851-PHOTON"].validation_status == SupplierQuoteValidationStatus.MSRP_MATCH
    assert product["8459"].validation_status == SupplierQuoteValidationStatus.MSRP_MATCH
    assert product["5608"].validation_status == SupplierQuoteValidationStatus.NO_DEALER_DISCOUNT
    assert product["7851-PHOTON"].description and "PHOTON" in product["7851-PHOTON"].description
    assert result.summary.msrp_match_count == 5
    assert result.summary.no_dealer_discount_count == 1
    assert result.summary.missing_component_count == 1
    assert result.summary.shipping_line_count == 1
    assert result.summary.insurance_line_count == 1
    assert result.summary.shipping_line_count + result.summary.insurance_line_count == 2
    assert all(
        line.validation_status == SupplierQuoteValidationStatus.NON_PRODUCT_COST
        for line in result.lines
        if line.line_kind in {SupplierQuoteLineKind.SHIPPING, SupplierQuoteLineKind.INSURANCE}
    )
    assert store.snapshot() == before_items
    assert [item.model_dump() for item in books[0].candidates] == before_candidates
    assert result.status != SupplierQuoteOverallStatus.VALID
