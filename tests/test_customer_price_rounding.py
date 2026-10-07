"""Customer-facing JPY sales prices are quoted in thousands (ROUND_HALF_UP); costs keep full precision."""

import json

import pytest

from agents.formal_quote_document import FormalQuoteDocumentError, build_formal_quote_document
from agents.pricing_policy import round_customer_price_jpy
from agents.quote_approval import create_revision_draft
from agents.quote_builder import apply_exchange_rate, apply_final_price
from agents.quote_export import QuoteExportError, export_spaceone_quote_pdf
from models import ApprovedQuoteSnapshot, FinalPriceStatus, PricingPolicyType
from repositories.sqlite_quote_repository import SqliteQuoteRepository
from tests.test_quote_approval import _approve, _ready_photon
from tests.test_quote_builder import _line, _mag_v1, _v1, _v1_mag_draft
from ui.pricing_display import submit_final_price, validate_final_price_input

LOCALE = json.loads(open("locales/ja.json", encoding="utf-8").read())


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (362737.5, 363000.0),  # A1
        (6431815.5, 6432000.0),  # A2
        (6626719, 6627000.0),  # A3
        (362500, 363000.0),  # exactly half rounds up, not to even
        (361500, 362000.0),
        (362499.9999, 362000.0),
    ],
)
def test_customer_price_rounds_half_up_to_thousands(raw, expected):
    assert round_customer_price_jpy(raw) == expected


def test_msrp_multiplier_standard_is_always_in_thousands_and_costs_are_not_rounded():  # A4
    draft = _v1_mag_draft(_mag_v1())
    apply_exchange_rate(draft, 165, sales_candidates=_mag_v1(165.0))
    mag = _line(draft, "9701-MAG-4K")

    assert mag.standard_sales_price_candidate_jpy == 6432000  # 35437 * 165 * 1.1 = 6,431,815.5
    for line in draft.configuration_lines:
        if line.pricing_policy_type == PricingPolicyType.MSRP_MULTIPLIER:
            assert line.standard_sales_price_candidate_jpy % 1000 == 0
    assert mag.dealer_cost_jpy == round(mag.dealer_price_usd * 165, 4)
    assert mag.landed_cost_jpy % 1000 != 0


def test_fixed_jpy_master_price_in_thousands_is_kept_as_defined():  # A5
    draft = _v1_mag_draft(_mag_v1())
    apply_exchange_rate(draft, 165, sales_candidates=_mag_v1(165.0))

    assert _line(draft, "2604").pricing_policy_type == PricingPolicyType.FIXED_JPY
    assert _line(draft, "2604").standard_sales_price_candidate_jpy == 360000


def test_fixed_jpy_master_price_outside_thousands_goes_to_review_and_is_not_rounded():
    fixed = [item if item.manufacturer_sku != "2604" else _v1("2604", rate=170.0, row=23, fixed=362737.5) for item in _mag_v1()]
    line = _line(_v1_mag_draft(fixed), "2604")

    assert line.pricing_policy_type == PricingPolicyType.FIXED_JPY
    assert line.pricing_fixed_price_jpy == 362737.5
    assert line.standard_sales_price_candidate_jpy is None
    assert line.standard_sales_price_candidate_id is None
    assert any("not in 1,000 JPY units" in item for item in line.warnings)
    assert validate_final_price_input(line, "363,000", None, None)["error"] is None


def test_manual_case_price_in_thousands_is_saved():  # A6
    draft = _v1_mag_draft(_mag_v1())
    line = _line(draft, "9701-MAG-4K")
    values = validate_final_price_input(line, "6,000,000", "COMPETITIVE_RESPONSE", None)

    assert values["error"] is None
    assert submit_final_price(draft, line, values, reason_labels={}) is True
    assert line.final_sales_price_jpy == 6000000
    assert line.final_price_status == FinalPriceStatus.MANUAL_OVERRIDE


@pytest.mark.parametrize("entered", ["6,000,500", "6000000.5", "999"])
def test_manual_case_price_outside_thousands_is_refused_before_saving(entered):  # A7
    draft = _v1_mag_draft(_mag_v1())
    line = _line(draft, "9701-MAG-4K")
    values = validate_final_price_input(line, entered, "COMPETITIVE_RESPONSE", None)

    assert values["error"] == "amount_not_thousand"
    assert values["amount"] is not None
    assert line.final_price_status == FinalPriceStatus.NOT_SET
    assert draft.adjustments == []
    assert "1,000円単位" in LOCALE["pages"]["quote_control"]["workspace"]["adjustment_errors"]["amount_not_thousand"]


def test_manual_review_line_also_requires_thousands():  # A7 (no standard price)
    draft = _v1_mag_draft(_mag_v1())
    line = _line(draft, "2601")
    assert line.standard_sales_price_candidate_jpy is None

    assert validate_final_price_input(line, "12,345", None, None)["error"] == "amount_not_thousand"
    assert validate_final_price_input(line, "12,000", None, None)["error"] is None


def _formal_from_standard_prices():
    draft = _ready_photon()
    base = next(line for line in draft.configuration_lines if line.manufacturer_sku == "9680-BASE")
    apply_final_price(draft, base.line_id, FinalPriceStatus.USE_STANDARD_CANDIDATE)
    _approval, snapshot = _approve(draft)
    return snapshot, build_formal_quote_document(snapshot, official_quote_number="T-0001")


def _shown(value) -> int:
    from agents.formal_quote_document import format_document_amount

    return int(format_document_amount(value).replace(",", ""))


def test_formal_document_lines_add_up_to_subtotal():  # A8
    snapshot, document = _formal_from_standard_prices()

    assert any(line.amount == 3548000 for line in document.customer_lines)
    assert sum(_shown(line.amount) for line in document.customer_lines) == _shown(document.subtotal)
    assert document.subtotal == snapshot.subtotal_ex_tax_jpy


def test_formal_document_subtotal_plus_tax_is_total():  # A9
    _snapshot, document = _formal_from_standard_prices()

    assert _shown(document.subtotal) + _shown(document.tax_amount) == _shown(document.total)


def _legacy_fractional(snapshot: ApprovedQuoteSnapshot) -> ApprovedQuoteSnapshot:
    # Acceptance reproduction: 2604 at 1707 * 170 * 1.25 = 362,737.5 left the printed yen inconsistent.
    amounts = [6000000.0, 2258025.0, 2220200.0, 362737.5, 200000.0]
    lines = [
        line.model_copy(update={"unit_price_jpy": amount, "amount_jpy": amount})
        for line, amount in zip(snapshot.customer_lines_snapshot, amounts)
    ]
    configuration = [line.model_copy(deep=True) for line in snapshot.configuration_snapshot]
    configuration[0].standard_sales_price_candidate_jpy = 3547764.0
    return snapshot.model_copy(
        update={
            "customer_lines_snapshot": lines,
            "configuration_snapshot": configuration,
            "subtotal_ex_tax_jpy": 11040962.5,
            "tax_jpy": 1104096.25,
            "total_jpy": 12145058.75,
        }
    )


def test_formal_document_refuses_printed_amounts_that_do_not_add_up(tmp_path):  # A8 / A9 fail closed
    snapshot, _document = _formal_from_standard_prices()
    legacy = _legacy_fractional(snapshot)

    with pytest.raises(FormalQuoteDocumentError, match="do not add up"):
        build_formal_quote_document(legacy, official_quote_number="T-0002")
    with pytest.raises(QuoteExportError, match="do not add up"):
        export_spaceone_quote_pdf(legacy, output_dir=tmp_path, official_quote_number="T-0002")
    assert list(tmp_path.glob("*.pdf")) == []


def test_legacy_snapshot_with_fractional_prices_still_loads():  # A10
    snapshot, _document = _formal_from_standard_prices()
    legacy = _legacy_fractional(snapshot)

    loaded = ApprovedQuoteSnapshot.model_validate(json.loads(legacy.model_dump_json()))
    assert loaded.subtotal_ex_tax_jpy == 11040962.5
    assert loaded.configuration_snapshot[0].standard_sales_price_candidate_jpy == 3547764.0

    repository = SqliteQuoteRepository()
    repository.save_snapshot(legacy)
    stored = repository.get_snapshot(legacy.approved_quote_snapshot_id)
    assert stored.model_dump_json() == legacy.model_dump_json()

    revision = create_revision_draft(stored)
    assert revision.configuration_lines[0].standard_sales_price_candidate_jpy == 3547764.0


def _shipping_policy(markup=1.2):
    from agents.landed_cost import policy_from_inputs
    from models import InsuranceMode

    return policy_from_inputs(
        import_tax_rate=0.1, insurance_mode=InsuranceMode.PERCENTAGE, insurance_rate=0.03, shipping_markup_multiplier=markup
    )


def _shipping(cost_jpy, markup=1.2):
    from agents.landed_cost import build_shipping_line
    from models import ShippingType

    return build_shipping_line(ShippingType.LARGE_BOX, 1, cost_jpy, 1.0, _shipping_policy(markup), source_type="TEST")


def test_customer_shipping_price_is_cost_times_markup_in_thousands():  # shipping 1 / 3 / 4
    line = _shipping(935088)

    assert line.cost_jpy == 935088  # internal cost is not rounded
    assert line.sales_price_candidate_jpy == 1122000  # 935,088 x 1.2 = 1,122,105.6
    assert line.sales_price_candidate_jpy % 1000 == 0


def test_customer_shipping_price_rounds_half_up_at_500():  # shipping 2
    line = _shipping(778750)  # 778,750 x 1.2 = 934,500 exactly

    assert line.sales_price_candidate_jpy == 935000
    assert round(934.5) * 1000 == 934000  # Python round() would have gone to even


def test_repriced_shipping_keeps_exact_cost_and_thousand_customer_price():  # shipping 3 / 4
    from agents.landed_cost import build_shipping_line, reprice_shipping_line
    from models import ShippingType

    line = build_shipping_line(ShippingType.LARGE_BOX, 2, 2922.15, 170.0, _shipping_policy(), source_type="TEST")
    repriced = reprice_shipping_line(line, exchange_rate=165.0, policy=_shipping_policy())

    assert line.cost_jpy == round(2 * 2922.15 * 170, 4) == 993531.0
    assert repriced.cost_jpy == round(2 * 2922.15 * 165, 4)
    assert line.sales_price_candidate_jpy == 1192000  # 1,192,237.2
    assert repriced.sales_price_candidate_jpy % 1000 == 0


def _formal_with_calculated_shipping():
    draft = _ready_photon()
    from agents.quote_builder import apply_shipping_final_price

    shipping_sales = sum(line.sales_price_candidate_jpy for line in draft.shipping_lines)
    shipping_costs = [line.cost_jpy for line in draft.shipping_lines]
    apply_shipping_final_price(draft, shipping_sales)
    _approval, snapshot = _approve(draft)
    return snapshot, build_formal_quote_document(snapshot, official_quote_number="T-0003"), shipping_sales, shipping_costs


def test_formal_document_with_products_and_shipping_adds_up():  # shipping 5 / 6
    snapshot, document, shipping_sales, shipping_costs = _formal_with_calculated_shipping()

    shipping = document.customer_lines[-1]
    assert shipping.amount == shipping_sales and shipping_sales % 1000 == 0
    assert [line.cost_jpy for line in snapshot.shipping_snapshot] == shipping_costs
    assert any(cost % 1000 for cost in shipping_costs)  # costs stay at full precision
    assert sum(_shown(line.amount) for line in document.customer_lines) == _shown(document.subtotal)
    assert _shown(document.subtotal) + _shown(document.tax_amount) == _shown(document.total)


def test_photon_2535_fixed_jpy_stays_35000_at_any_rate():  # shipping 7
    from agents.quote_builder import _apply_standard_candidate
    from models import QuoteConfigurationLine
    from ui.pricing_display import standard_price_basis

    candidate = _v1("2535", rate=165.0, sheet="PHOTON", row=53, msrp=105.0, fixed=35000.0)
    for rate in (160.0, 165.0, 170.0):
        line = QuoteConfigurationLine(line_id="cfg-2535", manufacturer_sku="2535")
        _apply_standard_candidate(line, candidate.model_copy(update={"exchange_rate": rate}), rate)
        assert line.standard_sales_price_candidate_jpy == 35000
        assert line.pricing_policy_type == PricingPolicyType.FIXED_JPY
        assert not line.warnings
    workspace = LOCALE["pages"]["quote_control"]["workspace"]
    assert standard_price_basis(workspace, line)["text"] == "固定標準価格"


def test_legacy_decimal_snapshot_is_readable_revisable_unchanged_and_refused_for_formal_output(tmp_path):  # shipping 8
    snapshot, _document = _formal_from_standard_prices()
    lines = [line.model_copy(deep=True) for line in snapshot.customer_lines_snapshot]
    lines[-1] = lines[-1].model_copy(update={"unit_price_jpy": 1122105.6, "amount_jpy": 1122105.6})
    subtotal = round(sum(line.amount_jpy for line in lines), 4)
    legacy = snapshot.model_copy(
        update={
            "customer_lines_snapshot": lines,
            "subtotal_ex_tax_jpy": subtotal,
            "tax_jpy": round(subtotal * 0.1, 4),
            "total_jpy": round(subtotal * 1.1, 4),
        }
    )
    before = legacy.model_dump_json()

    loaded = ApprovedQuoteSnapshot.model_validate(json.loads(before))
    revision = create_revision_draft(loaded)
    with pytest.raises(QuoteExportError, match="do not add up"):
        export_spaceone_quote_pdf(loaded, output_dir=tmp_path, official_quote_number="T-0004")

    assert revision.customer_lines[-1].amount_jpy == 1122105.6  # not converted to the new rule
    assert loaded.model_dump_json() == before
    assert list(tmp_path.glob("*.pdf")) == []
