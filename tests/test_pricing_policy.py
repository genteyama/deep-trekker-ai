from pathlib import Path

from agents.pricing_policy import (
    apply_rounding,
    build_exchange_rate_scenario,
    compare_ihi_historical_prices,
    extract_pricing_policies,
    ihi_historical_comparison_lines,
    simulate_sales_price_candidates,
    standard_sales_price_jpy,
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
    PricingPolicyType,
    RoundingMethod,
    SpaceOneMasterItem,
    SpaceOneValues,
)
from parsers.spaceone_master_parser import parse_spaceone_master
from tests.price_book_fixtures import (
    official_ihi_sku_snapshot_book,
    pricing_policy_manufacturer_book,
    pricing_policy_master_book,
)

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
    # The real master has no rounding formula, so Pricing Policy v1 does not calculate one automatically.
    assert _policy(policies, "ROUND-P").rounding_method == RoundingMethod.ROUND
    assert _policy(policies, "ROUND-P").policy_type == PricingPolicyType.MANUAL_REVIEW
    assert round_item.raw_sales_price_jpy is None
    assert round_item.rounded_sales_price_jpy is None
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


def _so_item(sku, formula, *, sheet="MAG", usd_row=12, jpy_formula=None, msrp=None, sales=None, invalid=False):
    # Same shape the parser produces for the real master: USD row, then a JPY row "=E{usd}*$F$2" with R.
    return SpaceOneMasterItem(
        spaceone_item_id=f"so-{sheet}-{usd_row}",
        source_sheet=sheet,
        source_row=usd_row,
        spaceone_sku=sku,
        normalized_sku=None if invalid else sku,
        part_number_invalid=invalid,
        sales_price_formula=formula,
        sales_price_formula_row=usd_row + 1,
        jpy_msrp_formula=jpy_formula if jpy_formula is not None else f"=E{usd_row}*$F$2",
        detected_exchange_rate=170.0,
        exchange_rate_source_cell=f"{sheet}!F2",
        values=SpaceOneValues(name_ja=sku, manufacturer_msrp_usd=msrp, sales_price=sales),
    )


def _v1_candidates(items, rate=160):
    dt40 = import_price_book(official_ihi_sku_snapshot_book(), source_price_book="DT40", version="snapshot")
    policies = extract_pricing_policies(items)
    preview = build_sku_link_preview(items, dt40)
    sales = simulate_sales_price_candidates(preview, policies, build_exchange_rate_scenario(rate), items)
    return {item.spaceone_item_id: item for item in policies}, {item.spaceone_item_id: item for item in sales}


def test_v1_msrp_multiplier_uses_official_msrp_quote_rate_and_master_multiplier():
    item = _so_item("9701-MAG-4K", "=E13*1.1", msrp=35437, sales=6626719)
    policies, sales = _v1_candidates([item])
    candidate = sales[item.spaceone_item_id]

    assert policies[item.spaceone_item_id].policy_type == PricingPolicyType.MSRP_MULTIPLIER
    assert candidate.pricing_policy_type == PricingPolicyType.MSRP_MULTIPLIER
    assert candidate.multiplier == 1.1
    # source_row is the master row holding the R formula (the JPY row).
    assert (candidate.source_reference, candidate.source_row) == ("MAG", 13)
    assert candidate.raw_sales_price_jpy == 6236912
    assert candidate.raw_sales_price_jpy == standard_sales_price_jpy(
        PricingPolicyType.MSRP_MULTIPLIER, msrp_usd=35437, exchange_rate=160, multiplier=1.1, fixed_price_jpy=None
    )


def test_v1_missing_cached_master_msrp_still_uses_official_msrp():
    # IMPORTRANGE left the SpaceOne USD cell empty and R cached as 0; the formula structure is still safe.
    item = _so_item("9701-MAG-4K", "=E13*1.1", msrp=None, sales=0)
    policies, sales = _v1_candidates([item])

    assert policies[item.spaceone_item_id].policy_type == PricingPolicyType.MSRP_MULTIPLIER
    assert sales[item.spaceone_item_id].raw_sales_price_jpy == 6236912


def test_v1_fixed_jpy_policy_does_not_depend_on_exchange_rate():
    item = _so_item("2604", "35000", sheet="PHOTON", usd_row=52)
    _, sales_160 = _v1_candidates([item], rate=160)
    policies, sales_170 = _v1_candidates([item], rate=170)

    assert policies[item.spaceone_item_id].policy_type == PricingPolicyType.FIXED_JPY
    assert sales_160[item.spaceone_item_id].raw_sales_price_jpy == 35000
    assert sales_170[item.spaceone_item_id].raw_sales_price_jpy == 35000
    assert sales_160[item.spaceone_item_id].fixed_price_jpy == 35000


def test_v1_special_dealer_and_unverified_reference_are_manual_review_without_price():
    special = _so_item("9701-MAG-4K", "=E17*1.2-M17", usd_row=16)
    dealer = _so_item("9735", "=F15*1.1", usd_row=14, jpy_formula="=F14*$F$2")
    usd_row_ref = _so_item("5608", "=E18*1.25", usd_row=18)
    broken_chain = _so_item("2601", "=E21*1.2", usd_row=20, jpy_formula="=E20*165")
    items = [special, dealer, usd_row_ref, broken_chain]
    policies, sales = _v1_candidates(items)

    for item in items:
        assert policies[item.spaceone_item_id].policy_type == PricingPolicyType.MANUAL_REVIEW
        assert policies[item.spaceone_item_id].source_formula == item.sales_price_formula
        assert sales[item.spaceone_item_id].raw_sales_price_jpy is None
        assert sales[item.spaceone_item_id].status == PricingPolicyStatus.REVIEW_REQUIRED
    assert policies[special.spaceone_item_id].multiplier is None
    assert policies[dealer.spaceone_item_id].price_basis == PriceBasis.MANUFACTURER_DEALER


def test_v1_no_exact_manufacturer_match_has_no_candidate():
    item = _so_item("9263-100", "=E25*1.25", sheet="PIVOT", usd_row=24)
    policies, sales = _v1_candidates([item])

    assert policies[item.spaceone_item_id].policy_type == PricingPolicyType.MSRP_MULTIPLIER
    assert sales[item.spaceone_item_id].raw_sales_price_jpy is None
    assert sales[item.spaceone_item_id].status == PricingPolicyStatus.REVIEW_REQUIRED


def test_v1_date_converted_part_number_is_not_a_policy():
    valid = _so_item("9701-MAG-4K", "=E13*1.1")
    date_like = _so_item("9757-02-01 00:00:00", "=E51*1.2", usd_row=50, invalid=True)

    policies = extract_pricing_policies([valid, date_like])

    assert [policy.spaceone_item_id for policy in policies] == [valid.spaceone_item_id]
