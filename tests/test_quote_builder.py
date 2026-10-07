from agents.landed_cost import (
    IHI_DEVELOPMENT_DEALER_VALUES,
    IHI_KNOWN_PRODUCTS,
    build_ihi_landed_cost_scenario,
    dealer_values_from_candidates,
    policy_from_inputs,
)
from agents.quote_builder import (
    CANDIDATE_NOT_APPLIED_MARKER,
    HISTORICAL_PRICING_SOURCE,
    apply_exchange_rate,
    apply_final_price,
    apply_historical_acceptance_preview,
    apply_minimum_margin_reference,
    apply_presentation_mode,
    apply_shipping_final_price,
    apply_tax_rate,
    build_ihi_quote_draft,
    customer_line_landed_cost,
    customer_preview_rows,
    internal_configuration_rows,
)
from agents.pricing_policy import standard_sales_price_jpy
from agents.quote_control_agent import import_price_book
from data.golden_cases.loader import load_quote_golden_case
from models import (
    CustomerPresentationMode,
    DomesticShippingMode,
    FinalPriceStatus,
    InsuranceMode,
    PricingPolicyType,
    QuoteDraft,
    QuoteDraftStatus,
    RequirementType,
    SalesPriceCandidate,
    ScenarioCompleteness,
)
from tests.price_book_fixtures import official_ihi_sku_snapshot_book
from tests.test_landed_cost import FIXTURE_MSRP, IHI_DEALER, _policy, _sales


def _sales_list(*skus_and_prices):
    return [_sales(sku, price) for sku, price in skus_and_prices]


def _photon_sales():
    return _sales_list(
        ("9680-BASE", 3547764),
        ("8459", 160548),
        ("5608", 2309008),
        ("7851-PHOTON", 371025),
    )


def _mag_sales():
    return _sales_list(
        ("9701-MAG-4K", 6626719),
        ("9735", 2258025),
        ("5608", 2220200),
        ("2604", 360000),
    )


def _landed(configuration, sales, *, tax=0.1, insurance=0.03):
    dt40 = import_price_book(official_ihi_sku_snapshot_book(), source_price_book="DT40", version="snapshot")
    values = dealer_values_from_candidates(dt40.candidates, IHI_KNOWN_PRODUCTS[configuration])
    values.update({sku: dict(item) for sku, item in IHI_DEALER.items() if sku not in values})
    return build_ihi_landed_cost_scenario(
        configuration,
        exchange_rate=170,
        policy=policy_from_inputs(
            import_tax_rate=tax,
            insurance_mode=InsuranceMode.PERCENTAGE,
            insurance_rate=insurance,
            shipping_markup_multiplier=1.2,
            domestic_shipping_jpy=10000,
            domestic_shipping_mode=DomesticShippingMode.REVIEW_REQUIRED,
        ),
        dealer_values=values,
        sales_candidates=sales,
        price_book_candidates=dt40.candidates,
    )


def _photon_draft(**kwargs):
    sales = _photon_sales()
    scenario, _ = _landed("PHOTON", sales)
    return build_ihi_quote_draft("PHOTON", scenario, sales, **kwargs)


def _mag_draft(**kwargs):
    sales = _mag_sales()
    scenario, _ = _landed("MAG", sales)
    return build_ihi_quote_draft("MAG", scenario, sales, **kwargs)


def test_quote_draft_separates_internal_bom_from_customer_lines():
    draft = _mag_draft()
    customer_skus = []
    for line in draft.customer_lines:
        for config in draft.configuration_lines:
            if config.line_id in line.source_configuration_line_ids:
                customer_skus.append(config.manufacturer_sku)

    assert [line.manufacturer_sku for line in draft.configuration_lines] == list(IHI_KNOWN_PRODUCTS["MAG"])
    assert "2601" in [line.manufacturer_sku for line in draft.configuration_lines]
    assert "2601" not in customer_skus
    assert [line.display_name for line in draft.customer_lines if line.line_kind == "PRODUCT"] == [
        "MAG UTILITY CRAWLER PACKAGE 4K",
        "ELEVATED PT CAMERA KIT",
        "THICKNESS GUAGE - CYGNUS",
        "INTEGRATION KIT, POWER BRUSH CYGNUS GAUGE",
    ]


def test_required_dependency_stays_undecided_and_is_not_auto_hidden():
    draft = _mag_draft()
    brush = next(line for line in draft.configuration_lines if line.manufacturer_sku == "2601")

    assert brush.requirement_type == RequirementType.REQUIRED_DEPENDENCY
    assert brush.required_by_sku == "2604"
    assert "REQUIRES 2601" in (brush.dependency_source or "")
    assert brush.customer_presentation_status == CustomerPresentationMode.UNDECIDED
    assert brush.final_price_status == FinalPriceStatus.NOT_SET
    assert brush.final_sales_price_jpy is None
    assert draft.status == QuoteDraftStatus.REVIEW_REQUIRED
    assert brush.customer_presentation_status != CustomerPresentationMode.INTERNAL_ONLY


def test_bundle_keeps_component_landed_cost():
    draft = _mag_draft()
    parent = next(line for line in draft.configuration_lines if line.manufacturer_sku == "2604")
    child = next(line for line in draft.configuration_lines if line.manufacturer_sku == "2601")
    apply_presentation_mode(
        draft,
        child.line_id,
        CustomerPresentationMode.BUNDLED_WITH_PARENT,
        bundled_into_line_id=parent.line_id,
    )
    customer = next(item for item in draft.customer_lines if parent.line_id in item.source_configuration_line_ids)
    bundled_cost = customer_line_landed_cost(draft, customer)

    assert child.customer_presentation_status == CustomerPresentationMode.BUNDLED_WITH_PARENT
    assert child.landed_cost_jpy not in (None, 0)
    assert bundled_cost == round(parent.landed_cost_jpy + child.landed_cost_jpy, 4)
    assert "2601" not in [item["display_name"] for item in customer_preview_rows(draft)]
    assert child.line_id in customer.source_configuration_line_ids


def test_standard_and_final_prices_are_separated_and_override_is_tracked():
    draft = _photon_draft()
    base = next(line for line in draft.configuration_lines if line.manufacturer_sku == "9680-BASE")
    before_adjustments = list(draft.adjustments)
    apply_final_price(draft, base.line_id, FinalPriceStatus.USE_STANDARD_CANDIDATE)
    apply_final_price(
        draft,
        base.line_id,
        FinalPriceStatus.MANUAL_OVERRIDE,
        amount_jpy=3540000,
        reason="Human commercial adjustment",
        entered_by="弦",
    )
    updated = next(line for line in draft.configuration_lines if line.manufacturer_sku == "9680-BASE")

    assert base.standard_sales_price_candidate_jpy == 3547764
    assert updated.final_sales_price_jpy == 3540000
    assert updated.final_price_status == FinalPriceStatus.MANUAL_OVERRIDE
    assert updated.standard_sales_price_candidate_jpy == 3547764
    assert len(draft.adjustments) == len(before_adjustments) + 1
    assert draft.adjustments[-1].original_price_jpy == 3547764
    assert draft.adjustments[-1].final_price_jpy == 3540000
    assert draft.adjustments[-1].amount_jpy == -7764


def test_historical_difference_does_not_create_adjustments_or_set_finals():
    case = load_quote_golden_case()
    draft = _photon_draft()
    apply_historical_acceptance_preview(draft, case["photon_customer_quote"])
    base = next(line for line in draft.configuration_lines if line.manufacturer_sku == "9680-BASE")
    preview = next(item for item in draft.customer_lines if base.line_id in item.source_configuration_line_ids)

    assert draft.adjustments == []
    assert base.final_price_status == FinalPriceStatus.NOT_SET
    assert base.final_sales_price_jpy is None
    assert preview.historical_preview_unit_price_jpy == 3540000
    assert preview.unit_price_jpy is None
    assert HISTORICAL_PRICING_SOURCE not in (preview.pricing_source or "")
    assert "acceptance preview" in " ".join(draft.warnings).lower()
    assert "pricing source" in " ".join(draft.warnings).lower()


def test_shipping_and_insurance_customer_separation():
    draft = _photon_draft()
    shipping_customer = [item for item in draft.customer_lines if item.line_kind == "SHIPPING"]
    preview_text = " ".join(
        f"{item['display_name']} {item['description']}" for item in customer_preview_rows(draft)
    )

    assert len(draft.shipping_lines) == 2
    assert len(shipping_customer) == 1
    assert shipping_customer[0].display_name == "国際輸送費"
    assert "大型梱包×1" in (shipping_customer[0].description or "")
    assert "小型梱包×1" in (shipping_customer[0].description or "")
    assert all(item.line_kind != "INSURANCE" for item in draft.customer_lines)
    assert "1024.20" not in preview_text
    assert "Landed" not in preview_text
    assert "Dealer" not in preview_text
    keys = set(customer_preview_rows(draft)[0])
    assert "dealer_price_usd" not in keys
    assert "landed_cost_jpy" not in keys
    assert "gross_margin_rate" not in keys


def test_tax_rate_is_not_hardcoded_and_incomplete_has_no_gross_margin():
    draft = _photon_draft(tax_rate=0.08)
    other = _photon_draft(tax_rate=0.1)
    apply_shipping_final_price(draft, 870000)
    apply_shipping_final_price(other, 870000)

    assert _photon_draft().tax_rate is None
    assert draft.tax_rate == 0.08
    assert other.tax_rate == 0.1
    assert draft.status == QuoteDraftStatus.REVIEW_REQUIRED
    assert draft.economics_result.gross_margin_rate is None
    assert draft.completeness == ScenarioCompleteness.INCOMPLETE


def test_complete_draft_uses_final_prices_for_margin_and_margin_warning_does_not_change_price():
    draft = _photon_draft(tax_rate=0.1)
    for line in draft.configuration_lines:
        apply_final_price(draft, line.line_id, FinalPriceStatus.USE_STANDARD_CANDIDATE)
    apply_shipping_final_price(draft, 872742.6)
    apply_minimum_margin_reference(draft, 0.99)
    sales = draft.economics_result.total_sales_ex_tax_jpy
    landed = draft.economics_result.total_landed_cost_jpy
    base = next(line for line in draft.configuration_lines if line.manufacturer_sku == "9680-BASE")

    assert draft.status == QuoteDraftStatus.READY_FOR_APPROVAL
    assert draft.economics_result.gross_margin_rate == round((sales - landed) / sales, 6)
    assert draft.economics_result.product_sales_total_jpy == 3547764 + 160548 + 2309008 + 371025
    assert "below the entered reference" in " ".join(draft.warnings)
    assert base.final_sales_price_jpy == 3547764


def test_ihi_photon_and_mag_drafts_follow_golden_rules():
    case = load_quote_golden_case()
    photon = _photon_draft()
    mag = _mag_draft()
    apply_historical_acceptance_preview(photon, case["photon_customer_quote"])
    apply_historical_acceptance_preview(mag, case["mag_customer_quote"])
    internals = internal_configuration_rows(mag)
    photon_names = [item.display_name for item in photon.customer_lines]

    assert photon_names[:4] == [
        "DeepTrekker PHOTON BASE Package",
        "POWER PACK ASY, PHOTON",
        "THICKNESS GUAGE - CYGNUS",
        "THICKNESS GAUGE - CYGNUS INTEGRATION KIT",
    ]
    assert photon_names[-1] == "国際輸送費"
    assert mag.status == QuoteDraftStatus.REVIEW_REQUIRED
    assert next(item for item in internals if item["sku"] == "2601")["presentation"] == "UNDECIDED"
    assert case["mag_customer_quote"]["subtotal_ex_tax_jpy"] == 12648000
    assert "2601" not in IHI_DEVELOPMENT_DEALER_VALUES
    assert photon.pricing_context.manufacturer_price_snapshots
    snapshot = photon.pricing_context.manufacturer_price_snapshots[0]
    original = snapshot.manufacturer_dealer_price_usd
    snapshot.manufacturer_dealer_price_usd = 1
    assert photon.configuration_lines[0].manufacturer_price_snapshot.manufacturer_dealer_price_usd == original
    assert original != 1


def _v1(sku, multiplier=None, *, rate=170.0, sheet="MAG", row=13, msrp=None, fixed=None):
    # A simulated Pricing Policy v1 candidate: MSRP_MULTIPLIER unless a fixed JPY price is given.
    policy_type = PricingPolicyType.FIXED_JPY if fixed is not None else PricingPolicyType.MSRP_MULTIPLIER
    msrp = FIXTURE_MSRP[sku] if msrp is None else msrp
    return SalesPriceCandidate(
        sales_price_candidate_id=f"spc-{sheet}-{row}",
        spaceone_item_id=f"so-{sheet}-{row}",
        pricing_policy_candidate_id=f"ppc-{sheet}-{row}",
        manufacturer_sku=sku,
        manufacturer_msrp_usd=msrp,
        exchange_rate=rate,
        raw_sales_price_jpy=standard_sales_price_jpy(
            policy_type, msrp_usd=msrp, exchange_rate=rate, multiplier=multiplier, fixed_price_jpy=fixed
        ),
        pricing_policy_type=policy_type,
        multiplier=multiplier if fixed is None else None,
        fixed_price_jpy=fixed,
        source_formula=str(fixed) if fixed is not None else f"=E{row}*{multiplier}",
        source_reference=sheet,
        source_row=row,
    )


def _mag_v1(rate=170.0, *extra):
    return [
        _v1("9701-MAG-4K", 1.1, rate=rate, row=13),
        _v1("9735", 1.1, rate=rate, row=19),
        _v1("5608", 1.25, rate=rate, row=21),
        _v1("2604", rate=rate, row=23, fixed=360000),
        *extra,
    ]


def _v1_mag_draft(sales):
    scenario, _ = _landed("MAG", sales)
    return build_ihi_quote_draft("MAG", scenario, sales)


def _line(draft, sku):
    return next(line for line in draft.configuration_lines if line.manufacturer_sku == sku)


def test_v1_msrp_multiplier_line_uses_snapshot_msrp_quote_rate_and_keeps_provenance():
    draft = _v1_mag_draft(_mag_v1())
    mag = _line(draft, "9701-MAG-4K")

    assert mag.standard_sales_price_candidate_jpy == 6626719
    assert mag.pricing_policy_type == PricingPolicyType.MSRP_MULTIPLIER
    assert mag.pricing_multiplier == 1.1
    assert mag.pricing_fixed_price_jpy is None
    assert (mag.pricing_source_sheet, mag.pricing_source_row) == ("MAG", 13)
    assert mag.pricing_source_formula == "=E13*1.1"
    assert mag.pricing_policy_candidate_id == "ppc-MAG-13"
    assert mag.standard_sales_price_candidate_id == "spc-MAG-13"

    apply_exchange_rate(draft, 160, sales_candidates=_mag_v1(160.0))
    mag = _line(draft, "9701-MAG-4K")

    assert mag.manufacturer_price_snapshot.manufacturer_msrp_usd == 35437
    assert mag.standard_sales_price_candidate_jpy == 6236912
    assert mag.pricing_multiplier == 1.1


def test_v1_fixed_jpy_line_is_unchanged_by_exchange_rate():
    draft = _v1_mag_draft(_mag_v1())
    assert _line(draft, "2604").standard_sales_price_candidate_jpy == 360000
    assert _line(draft, "2604").pricing_policy_type == PricingPolicyType.FIXED_JPY

    apply_exchange_rate(draft, 160, sales_candidates=_mag_v1(160.0))
    assert _line(draft, "2604").standard_sales_price_candidate_jpy == 360000
    apply_exchange_rate(draft, 150)

    assert _line(draft, "2604").standard_sales_price_candidate_jpy == 360000
    assert _line(draft, "2604").pricing_fixed_price_jpy == 360000
    assert _line(draft, "9701-MAG-4K").standard_sales_price_candidate_jpy is None


def test_v1_cross_sheet_sku_uses_only_the_configuration_sheet():
    sales = _mag_v1(170.0)
    sales.insert(0, _v1("5608", 1.3, sheet="PHOTON", row=45))
    draft = _v1_mag_draft(sales)
    cygnus = _line(draft, "5608")

    assert cygnus.pricing_source_sheet == "MAG"
    assert cygnus.pricing_multiplier == 1.25
    assert cygnus.standard_sales_price_candidate_jpy == round(10448 * 170 * 1.25, 4)


def test_v1_cross_sheet_sku_without_configuration_sheet_is_not_chosen():
    sales = [item for item in _mag_v1() if item.manufacturer_sku != "5608"]
    sales += [_v1("5608", 1.3, sheet="PHOTON", row=45), _v1("5608", 1.3, sheet="PIVOT", row=45)]
    draft = _v1_mag_draft(sales)
    cygnus = _line(draft, "5608")

    assert cygnus.standard_sales_price_candidate_jpy is None
    assert cygnus.standard_sales_price_candidate_id is None
    assert any(CANDIDATE_NOT_APPLIED_MARKER in item and "ambiguous" in item for item in cygnus.warnings)


def test_v1_same_sheet_duplicate_sku_is_not_chosen_even_with_same_multiplier():
    draft = _v1_mag_draft(_mag_v1(170.0, _v1("9701-MAG-4K", 1.1, row=15)))
    mag = _line(draft, "9701-MAG-4K")

    assert mag.standard_sales_price_candidate_jpy is None
    assert mag.pricing_policy_type is None
    assert any("MAG:13" in item and "MAG:15" in item for item in mag.warnings)

    apply_exchange_rate(draft, 160, sales_candidates=_mag_v1(160.0, _v1("9701-MAG-4K", 1.1, rate=160.0, row=15)))
    assert _line(draft, "9701-MAG-4K").standard_sales_price_candidate_jpy is None


def test_v1_candidate_msrp_must_match_quote_snapshot_msrp():
    sales = [item for item in _mag_v1() if item.manufacturer_sku != "9701-MAG-4K"]
    sales.append(_v1("9701-MAG-4K", 1.1, msrp=35000))
    draft = _v1_mag_draft(sales)
    mag = _line(draft, "9701-MAG-4K")

    assert mag.standard_sales_price_candidate_jpy is None
    assert mag.standard_sales_price_candidate_id is None
    assert mag.final_sales_price_jpy is None
    assert any(CANDIDATE_NOT_APPLIED_MARKER in item and "35000" in item for item in mag.warnings)


def test_v1_manual_review_and_unclassified_candidates_set_no_standard_price():
    review = _v1("9701-MAG-4K", 1.1).model_copy(
        update={"pricing_policy_type": PricingPolicyType.MANUAL_REVIEW, "multiplier": None, "raw_sales_price_jpy": None}
    )
    legacy = _v1("9735", 1.1).model_copy(update={"pricing_policy_type": None})
    sales = [item for item in _mag_v1() if item.manufacturer_sku not in {"9701-MAG-4K", "9735"}] + [review, legacy]
    draft = _v1_mag_draft(sales)

    for sku in ("9701-MAG-4K", "9735"):
        assert _line(draft, sku).standard_sales_price_candidate_jpy is None
        assert any(CANDIDATE_NOT_APPLIED_MARKER in item for item in _line(draft, sku).warnings)
    assert _line(draft, "9701-MAG-4K").pricing_policy_type == PricingPolicyType.MANUAL_REVIEW


def test_v1_rate_change_never_changes_final_sales_price():
    draft = _v1_mag_draft(_mag_v1())
    line = _line(draft, "9701-MAG-4K")
    apply_final_price(draft, line.line_id, FinalPriceStatus.USE_STANDARD_CANDIDATE)

    apply_exchange_rate(draft, 160, sales_candidates=_mag_v1(160.0))
    line = _line(draft, "9701-MAG-4K")

    assert line.standard_sales_price_candidate_jpy == 6236912
    assert line.final_sales_price_jpy == 6626719


def test_v1_legacy_draft_without_policy_fields_still_loads():
    data = _v1_mag_draft(_mag_v1()).model_dump(mode="json")
    new_fields = [name for name in data["configuration_lines"][0] if name.startswith("pricing_")]
    for line in data["configuration_lines"]:
        for name in new_fields:
            line.pop(name)

    loaded = QuoteDraft.model_validate(data)

    assert len(new_fields) == 7
    assert all(line.pricing_policy_type is None for line in loaded.configuration_lines)
    assert _line(loaded, "9701-MAG-4K").standard_sales_price_candidate_jpy == 6626719
