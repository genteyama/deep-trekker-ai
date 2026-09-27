from pathlib import Path

from agents.landed_cost import (
    IHI_DEVELOPMENT_DEALER_VALUES,
    IHI_KNOWN_PRODUCTS,
    build_ihi_landed_cost_scenario,
    dealer_values_from_candidates,
    policy_from_inputs,
)
from agents.master_reconciliation import collect_manufacturer_candidates
from agents.pricing_policy import (
    build_exchange_rate_scenario,
    compare_ihi_historical_prices,
    extract_pricing_policies,
    ihi_historical_comparison_lines,
    simulate_sales_price_candidates,
)
from agents.quote_control_agent import import_price_book
from agents.sku_link import build_sku_link_preview
from agents.supplier_quote_validation import (
    manufacturer_package_includes_component,
    validate_supplier_quote,
)
from data.golden_cases.loader import IHI_QUOTE_001, load_quote_golden_case
from models import (
    DomesticShippingMode,
    HistoricalComparisonStatus,
    InsuranceMode,
    RequiredConfigurationItem,
    ScenarioCompleteness,
    SkuMappingSource,
    SupplierQuote,
    SupplierQuoteLineKind,
    SupplierQuoteValidationStatus,
)
from parsers.spaceone_master_parser import parse_spaceone_master
from tests.price_book_fixtures import official_ihi_sku_snapshot_book
from tests.test_landed_cost import IHI_DEALER, _policy, _sales

OFFICIAL_DT40 = Path("/tmp/dt_price_investigation/DT40.xlsx")
OFFICIAL_SO = Path("/tmp/dt_price_investigation/SO_MASTER.xlsx")


def _dt40():
    if OFFICIAL_DT40.exists():
        return import_price_book(OFFICIAL_DT40, source_price_book="DT40", version="official")
    return import_price_book(official_ihi_sku_snapshot_book(), source_price_book="DT40", version="official-snapshot")


def _candidate(book, sku: str):
    return next(item for item in book.candidates if item.sku == sku)


def test_dt40_current_master_has_2604_and_2601_with_dependency_note():
    dt40 = _dt40()
    kit = _candidate(dt40, "2604")
    base = _candidate(dt40, "2601")
    package = _candidate(dt40, "9701-MAG-4K")
    notes = " ".join(item.notes or "" for item in kit.occurrences)

    assert kit.dealer_price_usd == 1024.20
    assert kit.msrp_usd == 1707
    assert kit.description == "INTEGRATION KIT, POWER BRUSH CYGNUS GAUGE"
    assert "REQUIRES 2601" in notes
    assert base.dealer_price_usd == 567
    assert base.msrp_usd == 945
    assert base.description == "KIT, POWER BRUSH BASE"
    assert "2604" not in IHI_DEVELOPMENT_DEALER_VALUES
    assert "2601" not in IHI_DEVELOPMENT_DEALER_VALUES
    assert manufacturer_package_includes_component(
        " ".join(item.notes or "" for item in package.occurrences),
        sku="2601",
        markers=["POWER BRUSH BASE"],
    ) is False


def test_required_configuration_adds_2604_and_dt40_dependency_2601():
    case = load_quote_golden_case(IHI_QUOTE_001)
    items = [RequiredConfigurationItem.model_validate(item) for item in case["required_configuration"]]
    kit = next(item for item in items if item.required_sku == "2604")
    base = next(item for item in items if item.required_sku == "2601")

    assert kit.required_description == "INTEGRATION KIT, POWER BRUSH CYGNUS GAUGE"
    assert kit.requirement_source == "MANUFACTURER_PRICE_BOOK"
    assert kit.requirement_reference == "DT40 / VAC & MAG"
    assert kit.human_verified is True
    assert kit.depends_on_sku == "2601"
    assert "REQUIRES 2601" in (kit.dependency_source or "")
    assert base.required_description == "KIT, POWER BRUSH BASE"
    assert base.requirement_source == "MANUFACTURER_PRICE_BOOK"
    assert base.human_verified is True
    assert "guess" not in (kit.notes or "").lower()


def test_supplier_quote_detects_missing_2604_and_2601_without_adding_lines():
    case = load_quote_golden_case(IHI_QUOTE_001)
    quote = SupplierQuote.model_validate(case["supplier_quote"])
    before_skus = [line.sku for line in quote.lines]
    required = [RequiredConfigurationItem.model_validate(item) for item in case["required_configuration"]]
    result = validate_supplier_quote(quote, _dt40(), required_items=required)
    missing = [line for line in result.lines if line.line_kind == SupplierQuoteLineKind.MISSING_COMPONENT]

    assert "2604" not in before_skus
    assert "2601" not in before_skus
    assert [line.sku for line in quote.lines] == before_skus
    assert {line.sku for line in missing} == {"2604", "2601"}
    assert all(line.validation_status == SupplierQuoteValidationStatus.MISSING_COMPONENT for line in missing)
    assert quote.total_usd == 88600


def test_historical_mag_maps_2604_and_does_not_invent_2601_sales():
    case = load_quote_golden_case(IHI_QUOTE_001)
    mag = case["mag_customer_quote"]
    kit_line = next(line for line in mag["lines"] if line["description"] == "INTEGRATION KIT, POWER BRUSH CYGNUS GAUGE")
    comparisons = compare_ihi_historical_prices(
        [],
        [],
        historical_lines=ihi_historical_comparison_lines(case),
    )
    mapped_2604 = next(item for item in comparisons if item.sku == "2604")
    mapped_2601 = next(item for item in comparisons if item.sku == "2601")

    assert kit_line["unit_price_jpy"] == 360000
    assert kit_line["manufacturer_sku"] is None
    assert kit_line["sku_source"] == SkuMappingSource.UNMAPPED.value
    assert mag["subtotal_ex_tax_jpy"] == 12648000
    assert not any("2601" in (line.get("description") or "") for line in mag["lines"])
    assert mapped_2604.historical_quote_price_jpy == 360000
    assert mapped_2601.historical_quote_price_jpy is None
    assert mapped_2601.comparison_status == HistoricalComparisonStatus.MISSING_IN_HISTORICAL_QUOTE
    assert "360,000" in (mapped_2601.notes or "")
    assert "not a verdict" in (mapped_2601.notes or "")


def test_mag_landed_cost_uses_current_dealer_and_stays_incomplete_without_2601_sales():
    dt40 = _dt40()
    values = dealer_values_from_candidates(dt40.candidates, IHI_KNOWN_PRODUCTS["MAG"])
    sales = [
        _sales("9701-MAG-4K", 6626719),
        _sales("9735", 2258025),
        _sales("5608", 2220200),
        _sales("2604", 360000),
    ]
    scenario, economics = build_ihi_landed_cost_scenario(
        "MAG",
        exchange_rate=170,
        policy=_policy(),
        dealer_values=IHI_DEALER,
        sales_candidates=sales,
        price_book_candidates=dt40.candidates,
    )
    by_sku = {line.sku: line for line in scenario.product_lines}

    assert [line.sku for line in scenario.product_lines] == ["9701-MAG-4K", "9735", "5608", "2604", "2601"]
    assert by_sku["2604"].dealer_price_usd == 1024.20
    assert by_sku["2601"].dealer_price_usd == 567
    assert by_sku["2604"].dealer_cost_jpy == round(1024.20 * 170, 4)
    assert by_sku["2601"].dealer_cost_jpy == round(567 * 170, 4)
    assert by_sku["2604"].standard_sales_price_jpy == 360000
    assert by_sku["2601"].standard_sales_price_jpy is None
    assert values["2604"]["dealer_price_usd"] == 1024.20
    assert scenario.status == ScenarioCompleteness.INCOMPLETE
    assert economics.gross_margin_rate is None
    assert any("sales" in item.lower() for item in scenario.unresolved_components)


def test_finding_2604_does_not_force_complete_when_other_costs_are_open():
    dt40 = _dt40()
    scenario, economics = build_ihi_landed_cost_scenario(
        "MAG",
        exchange_rate=170,
        policy=policy_from_inputs(
            import_tax_rate=None,
            insurance_mode=InsuranceMode.PERCENTAGE,
            insurance_rate=None,
            shipping_markup_multiplier=1.2,
            domestic_shipping_mode=DomesticShippingMode.REVIEW_REQUIRED,
        ),
        dealer_values={},
        sales_candidates=[
            _sales("9701-MAG-4K", 1),
            _sales("9735", 1),
            _sales("5608", 1),
            _sales("2604", 1),
            _sales("2601", 1),
        ],
        price_book_candidates=dt40.candidates,
    )

    assert "2604" in [line.sku for line in scenario.product_lines]
    assert scenario.status == ScenarioCompleteness.INCOMPLETE
    assert economics.gross_margin_rate is None
    assert any("Import tax" in item or "insurance" in item.lower() for item in scenario.unresolved_components)


def test_historical_customer_quote_is_not_rewritten_by_configuration_audit():
    case = load_quote_golden_case(IHI_QUOTE_001)
    mag = case["mag_customer_quote"]

    assert [line["unit_price_jpy"] for line in mag["lines"]] == [6620000, 2258000, 2220000, 360000]
    assert mag["shipping"]["price_jpy"] == 1190000
    assert mag["subtotal_ex_tax_jpy"] == 12648000
    if OFFICIAL_SO.exists():
        spaceone = parse_spaceone_master(OFFICIAL_SO, source_name="SO_MASTER")
        dt40 = _dt40()
        preview = build_sku_link_preview(spaceone.items, dt40)
        policies = extract_pricing_policies(spaceone.items)
        simulate_sales_price_candidates(
            preview, policies, build_exchange_rate_scenario(170), spaceone.items
        )
        assert [line["unit_price_jpy"] for line in mag["lines"]] == [6620000, 2258000, 2220000, 360000]
        assert not any(policy.sku == "2601" and policy.fixed_price_jpy == 360000 for policy in policies)
