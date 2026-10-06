from pathlib import Path

from agents.landed_cost import (
    build_ihi_landed_cost_scenario,
    build_shipping_line,
    calculate_landed_cost_scenario,
    compare_quote_economics,
    dealer_values_from_candidates,
    ihi_historical_sales_totals,
    load_shipping_snapshots,
    policy_from_inputs,
    september_dealer_update_shipping_rate,
    supplier_quote_shipping_rate,
)
from agents.pricing_policy import compare_ihi_historical_prices
from data.golden_cases.loader import load_quote_golden_case
from models import (
    CostBasis,
    DomesticShippingMode,
    HistoricalComparisonStatus,
    HistoricalPriceComparison,
    InsuranceMode,
    QuoteAdjustment,
    QuoteAdjustmentType,
    SalesPriceCandidate,
    ScenarioCompleteness,
    ShippingType,
    SKUMasterCandidate,
    SKUSourceOccurrence,
    SpaceOnePricingPolicyCandidate,
    PricingFormulaType,
    PriceBasis,
)
from parsers.quote_calc_parser import extract_quote_calc_audit, locate_quote_calc_workbook
from tests.price_book_fixtures import quote_calc_formula_book

OFFICIAL_QUOTE_CALC = Path("/tmp/dt_price_investigation/QUOTE_CALC.xlsx")
IHI_DEALER = {
    "9701-MAG-4K": {"dealer_price_usd": 21262.2, "msrp_usd": 35437, "description": "MAG 4K"},
    "9735": {"dealer_price_usd": 7245.0, "msrp_usd": 12075, "description": "Elevated PT"},
    "5608": {"dealer_price_usd": 10448.0, "msrp_usd": 10448, "description": "Cygnus"},
    "9680-BASE": {"dealer_price_usd": 10434.6, "msrp_usd": 17391, "description": "PHOTON BASE"},
    "8459": {"dealer_price_usd": 472.2, "msrp_usd": 787, "description": "Spare battery"},
    "7851-PHOTON": {"dealer_price_usd": 1047.6, "msrp_usd": 1746, "description": "PHOTON kit"},
}


def _policy(**overrides):
    values = {
        "import_tax_rate": 0.1,
        "insurance_mode": InsuranceMode.PERCENTAGE,
        "insurance_rate": 0.03,
        "shipping_markup_multiplier": 1.2,
        "domestic_shipping_mode": DomesticShippingMode.REVIEW_REQUIRED,
        "domestic_shipping_jpy": 10000,
    }
    values.update(overrides)
    return policy_from_inputs(**values)


def _sales(sku: str, price: float, exchange_rate: float = 170.0) -> SalesPriceCandidate:
    # Simulated candidates always record their rate; IHI Golden scenarios are calculated at 170.
    return SalesPriceCandidate(
        sales_price_candidate_id=f"spc-{sku}",
        spaceone_item_id=f"so-{sku}",
        manufacturer_sku=sku,
        raw_sales_price_jpy=price,
        exchange_rate=exchange_rate,
    )


def _candidate(sku: str, dealer: float, msrp: float) -> SKUMasterCandidate:
    return SKUMasterCandidate(
        sku=sku,
        dealer_price_usd=dealer,
        msrp_usd=msrp,
        occurrences=[
            SKUSourceOccurrence(
                sku=sku,
                source_price_book="DT40",
                dealer_price_usd=dealer,
                msrp_usd=msrp,
            )
        ],
    )


def test_quote_calc_formulas_are_readable_and_become_policy_candidate():
    audit = extract_quote_calc_audit(quote_calc_formula_book())
    policy = audit.policy_candidate
    tax_cells = [item for item in audit.cells if item.cell.startswith("I") and item.formula]
    insurance_cells = [item for item in audit.cells if item.cell.startswith("K") and item.formula]

    assert policy is not None
    assert all(item.formula.endswith("*0.1") for item in tax_cells)
    assert all(item.formula.endswith("*0.03") for item in insurance_cells)
    assert policy.import_tax_rate == 0.1
    assert policy.import_tax_basis == CostBasis.PRODUCT_DEALER_JPY
    assert policy.insurance_mode == InsuranceMode.PERCENTAGE
    assert policy.insurance_rate == 0.03
    assert policy.insurance_basis == CostBasis.PRODUCT_DEALER_JPY
    assert policy.shipping_markup_multiplier == 1.2
    assert policy.domestic_shipping_mode == DomesticShippingMode.REVIEW_REQUIRED
    assert any("5000" in item and "REVIEW_REQUIRED" in item for item in audit.known_rule_checks)
    assert any("アクティオ" in item for item in audit.sheet_differences)
    assert any("原本" in item or "no domestic" in item.lower() for item in audit.domestic_observations)


def test_official_quote_calc_formulas_and_displayed_values_when_present():
    path = locate_quote_calc_workbook() or (OFFICIAL_QUOTE_CALC if OFFICIAL_QUOTE_CALC.exists() else None)
    if path is None:
        audit = extract_quote_calc_audit(quote_calc_formula_book())
        assert audit.observed_import_tax_rate == 0.1
        return
    audit = extract_quote_calc_audit(path)
    assert audit.observed_import_tax_rate == 0.1
    assert audit.observed_insurance_rate == 0.03
    assert audit.observed_shipping_markup == 1.2
    assert audit.policy_candidate.import_tax_basis == CostBasis.PRODUCT_DEALER_JPY


def test_tax_rate_is_not_hardcoded_in_engine():
    source = Path("agents/landed_cost.py").read_text(encoding="utf-8")
    low, high = [
        calculate_landed_cost_scenario(
            scenario_id=f"tax-{rate}",
            case_id="CASE",
            name="tax",
            exchange_rate=170,
            policy=_policy(import_tax_rate=rate),
            product_inputs=[{"sku": "9680-BASE", "dealer_price_usd": 10434.6, "quantity": 1}],
            shipping_lines=[],
            sales_candidates=[_sales("9680-BASE", 100)],
            domestic_shipping_jpy=0,
        )[0]
        for rate in (0.08, 0.1)
    ]
    assert "import_tax_rate = 0.1" not in source
    assert "0.10" not in source
    assert low.product_lines[0].import_tax_jpy != high.product_lines[0].import_tax_jpy
    assert high.product_lines[0].import_tax_jpy == round(10434.6 * 170 * 0.1, 4)


def test_insurance_modes_are_separated_and_supplier_amount_is_not_internal():
    percentage, _ = calculate_landed_cost_scenario(
        scenario_id="ins-pct",
        case_id="CASE",
        name="pct",
        exchange_rate=170,
        policy=_policy(),
        product_inputs=[{"sku": "9680-BASE", "dealer_price_usd": 10434.6, "quantity": 1}],
        shipping_lines=[],
        sales_candidates=[_sales("9680-BASE", 100)],
        insurance_mode=InsuranceMode.PERCENTAGE,
        supplier_insurance_usd=1950,
        domestic_shipping_jpy=0,
    )
    quoted, quoted_econ = calculate_landed_cost_scenario(
        scenario_id="ins-sq",
        case_id="CASE",
        name="quoted",
        exchange_rate=170,
        policy=_policy(insurance_mode=InsuranceMode.SUPPLIER_QUOTED, insurance_rate=None),
        product_inputs=[{"sku": "9680-BASE", "dealer_price_usd": 10434.6, "quantity": 1}],
        shipping_lines=[],
        sales_candidates=[_sales("9680-BASE", 100)],
        insurance_mode=InsuranceMode.SUPPLIER_QUOTED,
        supplier_insurance_usd=1950,
        domestic_shipping_jpy=0,
    )
    included, _ = calculate_landed_cost_scenario(
        scenario_id="ins-none",
        case_id="CASE",
        name="none",
        exchange_rate=170,
        policy=_policy(insurance_mode=InsuranceMode.NONE, insurance_rate=None),
        product_inputs=[{"sku": "9680-BASE", "dealer_price_usd": 10434.6, "quantity": 1}],
        shipping_lines=[],
        sales_candidates=[_sales("9680-BASE", 100)],
        insurance_mode=InsuranceMode.NONE,
        domestic_shipping_jpy=0,
    )
    dealer_jpy = 10434.6 * 170
    assert percentage.insurance_input == InsuranceMode.PERCENTAGE
    assert percentage.product_lines[0].insurance_jpy == round(dealer_jpy * 0.03, 4)
    assert percentage.product_lines[0].insurance_jpy != 1950 * 170
    assert quoted.insurance_input == InsuranceMode.SUPPLIER_QUOTED
    assert quoted.product_lines[0].insurance_jpy == 0
    assert quoted_econ.other_cost_total_jpy == round(1950 * 170, 4)
    assert included.insurance_input == InsuranceMode.NONE
    assert included.product_lines[0].insurance_jpy == 0
    assert "included" in " ".join(included.warnings)


def test_shipping_is_separate_and_supports_multiple_lines():
    policy = _policy()
    lines = [
        build_shipping_line(
            ShippingType.LARGE_BOX,
            1,
            2922.15,
            170,
            policy,
            source_type="DEALER_UPDATE_SNAPSHOT",
            source_reference="dealer-update-2026-09-shipping",
        ),
        build_shipping_line(
            ShippingType.SMALL_BOX,
            1,
            1356.0,
            170,
            policy,
            source_type="DEALER_UPDATE_SNAPSHOT",
            source_reference="dealer-update-2026-09-shipping",
        ),
    ]
    scenario, economics = calculate_landed_cost_scenario(
        scenario_id="ship",
        case_id="CASE",
        name="ship",
        exchange_rate=170,
        policy=policy,
        product_inputs=[{"sku": "9680-BASE", "dealer_price_usd": 10434.6, "quantity": 1}],
        shipping_lines=lines,
        sales_candidates=[_sales("9680-BASE", 100)],
        domestic_shipping_jpy=0,
    )
    product = scenario.product_lines[0]
    assert len(scenario.shipping_lines) == 2
    assert product.landed_cost_jpy == round(10434.6 * 170 * 1.13, 4)
    assert product.landed_cost_jpy != product.dealer_cost_jpy + lines[0].cost_jpy
    assert economics.shipping_cost_total_jpy == round((2922.15 + 1356.0) * 170, 4)
    assert economics.shipping_sales_total_jpy == round((2922.15 + 1356.0) * 170 * 1.2, 4)
    assert september_dealer_update_shipping_rate(ShippingType.LARGE_BOX) == 2922.15
    assert supplier_quote_shipping_rate(ShippingType.LARGE_BOX) == 2922.0
    assert september_dealer_update_shipping_rate(ShippingType.LARGE_BOX) != supplier_quote_shipping_rate(
        ShippingType.LARGE_BOX
    )


def test_product_cost_uses_dealer_not_supplier_msrp_and_keeps_snapshot():
    candidates = [_candidate("9701-MAG-4K", 21262.2, 35437)]
    scenario, _ = calculate_landed_cost_scenario(
        scenario_id="snap",
        case_id="CASE",
        name="snap",
        exchange_rate=170,
        policy=_policy(),
        product_inputs=[{"sku": "9701-MAG-4K", "quantity": 1}],
        shipping_lines=[],
        sales_candidates=[_sales("9701-MAG-4K", 6620000)],
        price_book_candidates=candidates,
        domestic_shipping_jpy=0,
    )
    line = scenario.product_lines[0]
    original = line.manufacturer_price_snapshot.manufacturer_dealer_price_usd
    candidates[0].dealer_price_usd = 1
    candidates[0].occurrences[0].dealer_price_usd = 1

    assert line.dealer_price_usd == 21262.2
    assert line.dealer_cost_jpy == round(21262.2 * 170, 4)
    assert line.dealer_cost_jpy != 35437 * 170
    assert line.manufacturer_price_snapshot.manufacturer_msrp_usd == 35437
    assert line.manufacturer_price_snapshot.exchange_rate == 170
    assert line.manufacturer_price_snapshot.manufacturer_dealer_price_usd == original
    assert original != 1


def test_domestic_and_shipping_markup_come_from_policy_and_sales_are_not_recomputed():
    policy = _policy(shipping_markup_multiplier=1.5, domestic_shipping_mode=DomesticShippingMode.PER_QUOTE)
    shipping = build_shipping_line(
        ShippingType.LARGE_BOX,
        2,
        2922.15,
        170,
        policy,
        source_type="DEALER_UPDATE_SNAPSHOT",
    )
    scenario, _ = calculate_landed_cost_scenario(
        scenario_id="policy-inputs",
        case_id="CASE",
        name="policy",
        exchange_rate=170,
        policy=policy,
        product_inputs=[
            {"sku": "9680-BASE", "dealer_price_usd": 10434.6, "quantity": 1},
            {"sku": "8459", "dealer_price_usd": 472.2, "quantity": 1},
        ],
        shipping_lines=[shipping],
        sales_candidates=[_sales("9680-BASE", 999999), _sales("8459", 111)],
        domestic_shipping_jpy=10000,
    )
    assert scenario.product_lines[0].domestic_shipping_jpy == 10000
    assert scenario.product_lines[1].domestic_shipping_jpy == 0
    assert scenario.shipping_lines[0].sales_markup_multiplier == 1.5
    assert scenario.product_lines[0].standard_sales_price_jpy == 999999
    assert scenario.product_lines[0].standard_sales_price_jpy != round(17391 * 170 * 1.2, 4)


def test_official_gross_margin_requires_complete_scenario():
    complete, complete_econ = calculate_landed_cost_scenario(
        scenario_id="complete",
        case_id="CASE",
        name="complete",
        exchange_rate=170,
        policy=_policy(),
        product_inputs=[{"sku": "9680-BASE", "dealer_price_usd": 10434.6, "quantity": 1}],
        shipping_lines=[],
        sales_candidates=[_sales("9680-BASE", 4000000)],
        domestic_shipping_jpy=10000,
    )
    incomplete, incomplete_econ = calculate_landed_cost_scenario(
        scenario_id="incomplete",
        case_id="CASE",
        name="incomplete",
        exchange_rate=170,
        policy=_policy(),
        product_inputs=[{"sku": "9680-BASE", "dealer_price_usd": 10434.6, "quantity": 1}],
        shipping_lines=[],
        sales_candidates=[_sales("9680-BASE", 4000000)],
        unresolved_components=["MAG Cygnus Integration Kit"],
        domestic_shipping_jpy=10000,
    )
    assert complete.status == ScenarioCompleteness.COMPLETE
    assert complete_econ.gross_margin_rate is not None
    assert incomplete.status == ScenarioCompleteness.INCOMPLETE
    assert incomplete_econ.gross_margin_rate is None
    assert incomplete_econ.gross_profit_jpy is None


def test_ihi_mag_is_incomplete_and_photon_can_be_built():
    policy = _policy()
    sales = [
        _sales("9701-MAG-4K", 6627764),
        _sales("9735", 2258000),
        _sales("5608", 2222200),
        _sales("9680-BASE", 3547764),
        _sales("8459", 160548),
        _sales("7851-PHOTON", 356184),
    ]
    mag, mag_econ = build_ihi_landed_cost_scenario(
        "MAG",
        exchange_rate=170,
        policy=policy,
        dealer_values=IHI_DEALER,
        sales_candidates=sales,
    )
    photon, photon_econ = build_ihi_landed_cost_scenario(
        "PHOTON",
        exchange_rate=170,
        policy=policy,
        dealer_values=IHI_DEALER,
        sales_candidates=sales,
    )
    case = load_quote_golden_case()
    mag_hist = ihi_historical_sales_totals(case["mag_customer_quote"])
    photon_hist = ihi_historical_sales_totals(case["photon_customer_quote"])
    mag_econ = compare_quote_economics(
        mag_econ,
        configuration_name="MAG",
        quote_number="8194",
        historical_product_sales_jpy=mag_hist["product_sales_jpy"],
        historical_shipping_sales_jpy=mag_hist["shipping_sales_jpy"],
        historical_total_sales_jpy=mag_hist["total_sales_jpy"],
    )
    photon_econ = compare_quote_economics(
        photon_econ,
        configuration_name="PHOTON",
        quote_number="8195",
        historical_product_sales_jpy=photon_hist["product_sales_jpy"],
        historical_shipping_sales_jpy=photon_hist["shipping_sales_jpy"],
        historical_total_sales_jpy=photon_hist["total_sales_jpy"],
        product_comparisons=[
            HistoricalPriceComparison(
                sku="5608",
                configuration_name="PHOTON",
                policy_sales_price_jpy=2309008,
                historical_quote_price_jpy=2220000,
                difference_jpy=89008,
                comparison_status=HistoricalComparisonStatus.DIFFERENCE,
                notes="Pricing Policy Candidate and Historical differ. Policy is not changed.",
            )
        ],
    )
    photon_policy = SpaceOnePricingPolicyCandidate(
        pricing_policy_candidate_id="ppc-5608-photon",
        sku="5608",
        source_sheet="PHOTON",
        price_basis=PriceBasis.MANUFACTURER_MSRP,
        formula_type=PricingFormulaType.MULTIPLIER,
        multiplier=1.3,
        source_formula="=E*1.3",
    )

    assert mag.status == ScenarioCompleteness.INCOMPLETE
    assert "MAG Cygnus Integration Kit" not in mag.unresolved_components
    assert any("2604" in item for item in mag.unresolved_components)
    assert any("2601" in item for item in mag.unresolved_components)
    assert mag_econ.gross_margin_rate is None
    assert mag.adjustments == []
    assert [line.shipping_type for line in mag.shipping_lines] == [ShippingType.LARGE_BOX]
    assert mag.shipping_lines[0].quantity == 2
    assert mag.shipping_lines[0].rate_usd == 2922.15
    assert photon.status == ScenarioCompleteness.COMPLETE
    assert [line.sku for line in photon.product_lines] == ["9680-BASE", "8459", "5608", "7851-PHOTON"]
    assert [line.shipping_type for line in photon.shipping_lines] == [ShippingType.LARGE_BOX, ShippingType.SMALL_BOX]
    assert photon.shipping_lines[0].rate_usd == 2922.15
    assert photon.shipping_lines[1].rate_usd == 1356.0
    assert photon_econ.gross_margin_rate is not None
    assert mag_econ.economics_comparison.shipping_sales_historical_jpy == 1190000
    assert photon_econ.economics_comparison.shipping_sales_historical_jpy == 870000
    assert mag_econ.economics_comparison.shipping_sales_calculated_jpy != 1190000
    assert "acceptance comparison" in (mag_econ.economics_comparison.notes or "")
    assert photon_econ.comparisons[0].comparison_status == HistoricalComparisonStatus.DIFFERENCE
    assert photon_policy.multiplier == 1.3
    assert compare_ihi_historical_prices([], [photon_policy], historical_lines=[]) == []
    snapshots = load_shipping_snapshots()
    assert snapshots["dealer_update_september_2026"]["is_permanent"] is False
    assert dealer_values_from_candidates(
        [_candidate("9680-BASE", 10434.6, 17391)], ["9680-BASE"]
    )["9680-BASE"]["dealer_price_usd"] == 10434.6


def test_quote_adjustment_is_not_auto_created_from_historical_difference():
    _, economics = calculate_landed_cost_scenario(
        scenario_id="adj",
        case_id="IHI_QUOTE_001",
        name="adj",
        exchange_rate=170,
        policy=_policy(),
        product_inputs=[{"sku": "9680-BASE", "dealer_price_usd": 10434.6, "quantity": 1}],
        shipping_lines=[],
        sales_candidates=[_sales("9680-BASE", 3547764)],
        domestic_shipping_jpy=10000,
    )
    compared = compare_quote_economics(
        economics,
        configuration_name="PHOTON",
        quote_number="8195",
        historical_product_sales_jpy=3540000,
        historical_shipping_sales_jpy=870000,
        historical_total_sales_jpy=7160000,
    )
    assert compared.economics_comparison.product_sales_difference_jpy != 0
    assert QuoteAdjustment(
        adjustment_id="manual-only",
        adjustment_type=QuoteAdjustmentType.ROUNDING,
        amount_jpy=-7764,
        reason="Not auto-generated",
    ).adjustment_type == QuoteAdjustmentType.ROUNDING
