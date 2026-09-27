from agents.landed_cost import (
    IHI_DEVELOPMENT_DEALER_VALUES,
    IHI_KNOWN_PRODUCTS,
    build_ihi_landed_cost_scenario,
    dealer_values_from_candidates,
    policy_from_inputs,
)
from agents.quote_builder import (
    HISTORICAL_PRICING_SOURCE,
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
from agents.quote_control_agent import import_price_book
from data.golden_cases.loader import load_quote_golden_case
from models import (
    CustomerPresentationMode,
    DomesticShippingMode,
    FinalPriceStatus,
    InsuranceMode,
    QuoteDraftStatus,
    RequirementType,
    SalesPriceCandidate,
    ScenarioCompleteness,
)
from tests.price_book_fixtures import official_ihi_sku_snapshot_book
from tests.test_landed_cost import IHI_DEALER, _policy, _sales


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
