from pathlib import Path

from agents.pricing_policy import (
    apply_rounding,
    build_exchange_rate_scenario,
    compare_ihi_historical_prices,
    extract_pricing_policies,
    ihi_historical_comparison_lines,
    simulate_sales_price_candidates,
    summarize_pricing_patterns,
)
from agents.quote_control_agent import import_price_book
from agents.sku_link import build_sku_link_preview
from data.golden_cases.loader import load_quote_golden_case
from models import (
    HistoricalComparisonStatus,
    PriceBasis,
    PricingFormulaType,
    PricingPolicyStatus,
    RoundingMethod,
)
from parsers.spaceone_master_parser import parse_spaceone_master
from tests.price_book_fixtures import pricing_policy_manufacturer_book, pricing_policy_master_book

OFFICIAL_DT40 = Path("/tmp/dt_price_investigation/DT40.xlsx")
OFFICIAL_PT30 = Path("/tmp/dt_price_investigation/PT30.xlsx")
OFFICIAL_SO = Path("/tmp/dt_price_investigation/SO_MASTER.xlsx")


def _load_policy_case():
    spaceone = parse_spaceone_master(pricing_policy_master_book(), source_name="POLICY")
    dt40 = import_price_book(pricing_policy_manufacturer_book(), source_price_book="DT40")
    policies = extract_pricing_policies(spaceone.items)
    preview = build_sku_link_preview(spaceone.items, dt40)
    return spaceone, dt40, policies, preview


def _policy(policies, sku):
    return next(item for item in policies if item.sku == sku)


def test_master_formulas_become_policy_candidates_and_keep_source_formula():
    _, _, policies, _ = _load_policy_case()
    msrp = _policy(policies, "9680-BASE")
    dealer = _policy(policies, "DEALER-P")
    fixed = _policy(policies, "FIXED-P")
    special = _policy(policies, "SPECIAL-P")

    assert msrp.source_formula == "=E6*1.2"
    assert msrp.price_basis == PriceBasis.MANUFACTURER_MSRP
    assert msrp.formula_type == PricingFormulaType.MULTIPLIER
    assert msrp.multiplier == 1.2
    assert dealer.price_basis == PriceBasis.MANUFACTURER_DEALER
    assert dealer.multiplier == 1.1
    assert dealer.source_formula == "=F9*1.1"
    assert fixed.price_basis == PriceBasis.FIXED_PRICE
    assert fixed.fixed_price_jpy == 35000
    assert special.formula_type == PricingFormulaType.SPECIAL
    assert special.multiplier is None
    assert special.source_formula == "=E15*1.2-M15"
    assert special.status == PricingPolicyStatus.REVIEW_REQUIRED


def test_exchange_rate_is_separated_from_policy_and_not_hardcoded():
    spaceone, _, policies, preview = _load_policy_case()
    policy = _policy(policies, "9680-BASE")
    fx160 = build_exchange_rate_scenario(160)
    fx170 = build_exchange_rate_scenario(170)
    sales_160 = simulate_sales_price_candidates(preview, policies, fx160, spaceone.items)
    sales_170 = simulate_sales_price_candidates(preview, policies, fx170, spaceone.items)
    base_160 = next(item for item in sales_160 if item.manufacturer_sku == "9680-BASE")
    base_170 = next(item for item in sales_170 if item.manufacturer_sku == "9680-BASE")

    assert policy.multiplier == 1.2
    assert policy.detected_exchange_rate == 170
    assert "170" not in (policy.source_formula or "")
    assert fx160.source_type == "USER_SPECIFIED"
    assert base_160.raw_sales_price_jpy != base_170.raw_sales_price_jpy
    assert base_160.raw_sales_price_jpy == round(17391 * 160 * 1.2, 4)


def test_sales_candidates_use_current_manufacturer_value_and_skip_unlinked():
    spaceone, dt40, policies, preview = _load_policy_case()
    spaceone.items[0].values.manufacturer_msrp_usd = 1
    spaceone.items[0].values.sales_price = 3540000
    sales_before = [item.values.sales_price for item in spaceone.items]
    result = simulate_sales_price_candidates(
        preview, policies, build_exchange_rate_scenario(160), spaceone.items
    )
    by_sku = {item.manufacturer_sku or item.name_ja: item for item in result}
    linked = next(item for item in result if item.manufacturer_sku == "9680-BASE")
    review = next(item for item in result if "誤記" in (item.name_ja or ""))

    assert linked.manufacturer_msrp_usd == 17391
    assert linked.manufacturer_msrp_usd != 1
    assert linked.current_spaceone_sales_price_jpy == 3540000
    assert "参考粗利率（輸入諸経費除く）" in " ".join(linked.warnings)
    assert "正式粗利" not in " ".join(linked.warnings)
    assert review.skipped_reason == "Manufacturer SKU未確定"
    assert review.raw_sales_price_jpy is None
    assert [item.values.sales_price for item in spaceone.items] == sales_before
    assert dt40.candidates[0].msrp_usd == 17391


def test_rounding_is_deterministic_and_unknown_rounding_is_not_invented():
    rounded = apply_rounding(153600, RoundingMethod.ROUND, 1000)
    unknown = apply_rounding(3547764, RoundingMethod.NONE, None)
    _, _, policies, preview = _load_policy_case()
    spaceone = parse_spaceone_master(pricing_policy_master_book(), source_name="POLICY")
    result = simulate_sales_price_candidates(
        preview, policies, build_exchange_rate_scenario(160), spaceone.items
    )
    round_item = next(item for item in result if item.manufacturer_sku == "ROUND-P")
    base = next(item for item in result if item.manufacturer_sku == "9680-BASE")

    assert rounded == 154000
    assert unknown == 3547764
    assert _policy(policies, "9680-BASE").rounding_method == RoundingMethod.NONE
    assert round_item.rounded_sales_price_jpy == apply_rounding(800 * 160 * 1.2, RoundingMethod.ROUND, 1000)
    assert base.rounded_sales_price_jpy == base.raw_sales_price_jpy


def test_sales_candidate_excludes_shipping_insurance_and_tax():
    spaceone, _, policies, preview = _load_policy_case()
    result = simulate_sales_price_candidates(
        preview, policies, build_exchange_rate_scenario(160), spaceone.items
    )
    linked = next(item for item in result if item.manufacturer_sku == "9680-BASE")

    assert linked.raw_sales_price_jpy == round(17391 * 160 * 1.2, 4)
    assert linked.raw_sales_price_jpy != round(17391 * 160 * 1.2, 4) + 10000
    assert "輸入諸経費除く" in " ".join(linked.warnings)


def test_ihi_historical_quote_is_comparison_not_policy_source():
    if not (OFFICIAL_SO.exists() and OFFICIAL_DT40.exists() and OFFICIAL_PT30.exists()):
        spaceone, _, policies, preview = _load_policy_case()
        case = load_quote_golden_case()
        sales = simulate_sales_price_candidates(
            preview, policies, build_exchange_rate_scenario(170), spaceone.items
        )
        comparisons = compare_ihi_historical_prices(
            sales, policies, historical_lines=ihi_historical_comparison_lines(case)
        )
        assert all("historical output" in (item.notes or "") for item in comparisons if item.sku == "9680-BASE")
        assert not any(policy.source_formula and "6620000" in policy.source_formula for policy in policies)
        return

    spaceone = parse_spaceone_master(OFFICIAL_SO, source_name="SO_MASTER")
    dt40 = import_price_book(OFFICIAL_DT40, source_price_book="DT40", version="official")
    pt30 = import_price_book(OFFICIAL_PT30, source_price_book="PT30", version="official")
    policies = extract_pricing_policies(spaceone.items)
    preview = build_sku_link_preview(spaceone.items, dt40, pt30)
    sales = simulate_sales_price_candidates(
        preview, policies, build_exchange_rate_scenario(170), spaceone.items
    )
    case = load_quote_golden_case()
    comparisons = compare_ihi_historical_prices(
        sales, policies, historical_lines=ihi_historical_comparison_lines(case)
    )
    patterns = summarize_pricing_patterns(policies)
    mag_kit = next(item for item in comparisons if "INTEGRATION KIT, POWER BRUSH" in (item.item_name or ""))
    photon_base = next(item for item in comparisons if item.sku == "9680-BASE" and item.configuration_name == "PHOTON")
    multipliers = {item.multiplier for item in policies if item.formula_type == PricingFormulaType.MULTIPLIER}

    assert {1.1, 1.2, 1.25, 1.3}.issubset(multipliers)
    assert any(item.formula_type == PricingFormulaType.SPECIAL for item in policies)
    assert any(item.formula_type == PricingFormulaType.FIXED for item in policies)
    assert all(item.source_formula for item in policies)
    mag_brush = next(item for item in comparisons if item.sku == "2601")
    assert mag_kit.sku == "2604"
    assert mag_kit.historical_quote_price_jpy == 360000
    assert mag_kit.comparison_status in {
        HistoricalComparisonStatus.NOT_COMPARABLE,
        HistoricalComparisonStatus.DIFFERENCE,
        HistoricalComparisonStatus.MATCH,
    }
    assert mag_brush.comparison_status == HistoricalComparisonStatus.MISSING_IN_HISTORICAL_QUOTE
    assert mag_brush.historical_quote_price_jpy is None
    assert photon_base.historical_quote_price_jpy == 3540000
    assert photon_base.policy_sales_price_jpy == round(17391 * 170 * 1.2, 4)
    assert photon_base.comparison_status == HistoricalComparisonStatus.DIFFERENCE
    assert "historical output" in (photon_base.notes or "")
    assert not any("8194" in (item.source_formula or "") for item in policies)
    assert patterns
    sales_prices = [item.values.sales_price for item in spaceone.items]
    simulate_sales_price_candidates(preview, policies, build_exchange_rate_scenario(160), spaceone.items)
    assert [item.values.sales_price for item in spaceone.items] == sales_prices
