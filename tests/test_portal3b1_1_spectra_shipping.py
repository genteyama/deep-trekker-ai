"""PORTAL-3B.1.1: DT / PT GlobalShipping and SPECTRA GOLD shipping are two separate parts of the quote."""

import pytest

from agents import simple_quote_builder as sb
from agents.price_master import import_price_master
from agents.pricing_policy import round_customer_price_jpy
from agents.quote_approval import all_confirmations, approve_quote, create_revision_draft
from agents.quote_builder import apply_final_price
from agents.quote_export import (
    export_internal_calc_excel,
    export_moneyforward_tsv,
    export_spaceone_quote_excel,
    export_spaceone_quote_pdf,
)
from models import FinalPriceStatus, PriceAdjustmentReason, PriceMasterType, ShippingType
from repositories.shipping_rule_repository import ShippingRuleRepository
from repositories.sqlite_quote_repository import SqliteQuoteRepository
from tests.test_portal3b1_1_product_picker import (  # noqa: F401  (autouse fixture)
    RATE,
    SO_ROWS,
    _draft,
    _line,
    _pick,
    _spectra,
    masters,
)
from tests.test_portal3b1_standard_price_parity import _so_master_book

LARGE_BOX = 2922.15


def _large_box():
    return ShippingRuleRepository().get_active_standard_global(ShippingType.LARGE_BOX)


def _customer(usd):
    return round_customer_price_jpy(usd * RATE * 1.2)


def _mixed():
    draft = _draft(_pick(("DT40", "9680-BASE"), ("SPECTRA_GOLD", "SPECTRA0001")))
    sb.select_global_shipping(draft, _large_box(), selected_by="sales@example.com")
    sb.set_spectra_shipping(draft, actual_rate_usd=1800.0, reason="SPECTRA メーカー見積 Q-123", entered_by="sales@example.com")
    return draft


def test_dt_pt_only_quote_keeps_global_shipping():
    draft = _draft(_pick(("DT40", "9680-BASE")))
    sb.select_global_shipping(draft, _large_box())
    assert draft.spectra_shipping is None
    assert [line.source_type for line in draft.shipping_lines] == [sb.GLOBAL_SHIPPING_SOURCE]
    assert sb.customer_summary(draft)["shipping"] == _customer(LARGE_BOX)
    with pytest.raises(sb.SimpleQuoteError) as error:
        sb.set_spectra_shipping(draft, actual_rate_usd=100.0, reason="x")
    assert error.value.code == "SPECTRA_SHIPPING_NEEDS_SPECTRA"


def test_spectra_only_quote_uses_spectra_shipping_and_never_global_shipping():
    draft = _draft(_pick(("SPECTRA_GOLD", "SPECTRA0001")))
    with pytest.raises(sb.SimpleQuoteError) as error:
        sb.select_global_shipping(draft, _large_box())
    assert error.value.code == "GLOBAL_SHIPPING_NEEDS_DT_PT"
    with pytest.raises(sb.SimpleQuoteError):
        sb.set_spectra_shipping(draft, actual_rate_usd=2500.0, reason=" ")
    with pytest.raises(sb.SimpleQuoteError):
        sb.set_spectra_shipping(draft, actual_rate_usd=0, reason="SPECTRA メーカー見積")

    sb.set_spectra_shipping(draft, actual_rate_usd=2500.0, reason="SPECTRA メーカー見積")
    assert draft.global_shipping is None
    entry = draft.spectra_shipping
    assert (entry.actual_rate_usd, entry.reason) == (2500.0, "SPECTRA メーカー見積")
    assert entry.cost_jpy == pytest.approx(2500 * RATE)
    assert entry.customer_price_jpy == _customer(2500)
    line = draft.shipping_lines[0]
    assert (line.source_type, line.source_reference) == ("HUMAN_INPUT", sb.SPECTRA_SHIPPING_REFERENCE)
    assert sb.customer_summary(draft)["shipping"] == _customer(2500)
    product = draft.configuration_lines[0]
    cost = product.dealer_cost_jpy + product.insurance_jpy + product.import_tax_jpy + 2500 * RATE
    assert sb.revenue_summary(draft)["total_cost"] == pytest.approx(cost)


def test_mixed_quote_has_two_shipping_parts_in_cost_and_customer_total():
    draft = _mixed()
    selection, spectra = draft.global_shipping, draft.spectra_shipping
    # A. DT / PT: GlobalShipping with its master provenance.
    assert selection.shipping_rule_id and selection.master_rate_usd == pytest.approx(LARGE_BOX)
    assert selection.cost_jpy == pytest.approx(LARGE_BOX * RATE)
    # B. SPECTRA GOLD: human input, not from GlobalShipping.
    assert spectra.cost_jpy == pytest.approx(1800 * RATE)
    assert [(line.source_type, line.source_reference) for line in draft.shipping_lines] == [
        (sb.GLOBAL_SHIPPING_SOURCE, selection.shipping_rule_id),
        ("HUMAN_INPUT", sb.SPECTRA_SHIPPING_REFERENCE),
    ]
    assert draft.shipping_lines[1].notes == "SPECTRA メーカー見積 Q-123"

    # Customer: each part is rounded by the existing shipping line rule, then added up.
    customer = sb.customer_summary(draft)
    assert (customer["shipping_dt_pt"], customer["shipping_spectra"]) == (_customer(LARGE_BOX), _customer(1800))
    assert customer["shipping"] == _customer(LARGE_BOX) + _customer(1800)
    assert sum(line.sales_price_candidate_jpy for line in draft.shipping_lines) == customer["shipping"]

    revenue = sb.revenue_summary(draft)
    assert revenue["shipping_dt_pt"] == pytest.approx(LARGE_BOX * RATE)
    assert revenue["shipping_spectra"] == pytest.approx(1800 * RATE)
    assert revenue["shipping"] == pytest.approx((LARGE_BOX + 1800) * RATE)
    products = sum(line.dealer_cost_jpy + line.insurance_jpy + line.import_tax_jpy for line in draft.configuration_lines)
    assert revenue["total_cost"] == pytest.approx(products + (LARGE_BOX + 1800) * RATE)
    assert draft.economics_result.total_landed_cost_jpy == pytest.approx(revenue["total_cost"])
    sales = customer["product_subtotal"] + customer["shipping"]
    assert revenue["sales_ex_tax"] == pytest.approx(sales)
    assert revenue["gross_margin_rate"] == pytest.approx((sales - revenue["total_cost"]) / sales, abs=1e-6)


def test_dt_adjustment_and_overrides_do_not_touch_the_spectra_part():
    draft = _mixed()
    sb.adjust_global_shipping(draft, actual_rate_usd=3000.0, rate_reason="DT見積", customer_price_jpy=600000, customer_reason="特別")
    assert draft.spectra_shipping.customer_price_jpy == _customer(1800)
    assert sb.customer_summary(draft)["shipping"] == 600000 + _customer(1800)
    sb.clear_global_shipping(draft)
    assert sb.customer_summary(draft)["shipping"] == _customer(1800)
    assert [line.source_type for line in draft.shipping_lines] == ["HUMAN_INPUT"]
    sb.clear_spectra_shipping(draft)
    assert draft.shipping_lines == []


def test_exchange_rate_change_reprices_both_parts():
    draft = _mixed()
    from ui.quote_control import _sales_candidates_for_rate

    sb.change_exchange_rate(draft, 170.0, sales_candidates=_sales_candidates_for_rate(170.0), reason_note="円安", set_by="x")
    assert draft.global_shipping.cost_jpy == pytest.approx(LARGE_BOX * 170)
    assert draft.spectra_shipping.cost_jpy == pytest.approx(1800 * 170)
    assert draft.spectra_shipping.customer_price_jpy == round_customer_price_jpy(1800 * 170 * 1.2)


def test_removing_the_last_product_of_a_family_drops_its_shipping_part():
    draft = _mixed()
    sb.remove_line(draft, _line(draft, "SPECTRA_GOLD", "SPECTRA0001").line_id)
    assert draft.spectra_shipping is None
    assert sb.customer_summary(draft)["shipping"] == _customer(LARGE_BOX)


def _shipping_state(draft):
    return (
        draft.global_shipping.model_dump(),
        draft.spectra_shipping.model_dump(),
        [line.model_dump() for line in draft.shipping_lines],
        draft.subtotal_ex_tax_jpy,
        draft.total_jpy,
        draft.economics_result.total_landed_cost_jpy,
    )


def test_saved_mixed_quote_keeps_both_parts_after_reload_and_master_updates():
    draft = _mixed()
    SqliteQuoteRepository().save_draft(draft)
    before = _shipping_state(draft)
    loaded = SqliteQuoteRepository().get_draft(draft.quote_draft_id).draft
    assert _shipping_state(loaded) == before
    assert loaded.spectra_shipping.reason == "SPECTRA メーカー見積 Q-123"
    assert loaded.spectra_shipping.entered_by == "sales@example.com"

    ShippingRuleRepository().save_standard_global_rate(ShippingType.LARGE_BOX, rate_usd=9999, effective_from="2027-01-01")
    import_price_master(PriceMasterType.SPECTRA_GOLD, "SPECTRA-new.xlsx", _spectra(250000, 175000))
    import_price_master(
        PriceMasterType.SO_MASTER, "SO-new.xlsx", _so_master_book([(s, k, m, 1.5) for s, k, m, _ in SO_ROWS]).getvalue()
    )
    reloaded = SqliteQuoteRepository().get_draft(draft.quote_draft_id).draft
    assert _shipping_state(reloaded) == before
    sb.sync_after_rate_change(reloaded)
    assert _shipping_state(reloaded)[:3] == before[:3]


def test_mixed_quote_approves_exports_and_revises(tmp_path):
    draft = _mixed()
    repo = SqliteQuoteRepository()
    repo.save_draft(draft)
    candidate = draft.model_copy(deep=True)
    _, snapshot = approve_quote(
        candidate, approved_by="sales@example.com", confirmations=all_confirmations(), official_quote_number="MX-001"
    )
    repo.record_approval(candidate, snapshot)
    assert snapshot.global_shipping.shipping_rule_id == draft.global_shipping.shipping_rule_id
    assert snapshot.spectra_shipping.reason == "SPECTRA メーカー見積 Q-123"
    assert snapshot.total_jpy == pytest.approx(draft.total_jpy)
    for exporter in (export_spaceone_quote_pdf, export_spaceone_quote_excel, export_internal_calc_excel, export_moneyforward_tsv):
        bundle, path = exporter(snapshot, output_dir=tmp_path)
        assert bundle.official_quote_number == "MX-001"
        assert path.is_file()
    revision = create_revision_draft(snapshot)
    assert revision.spectra_shipping.actual_rate_usd == 1800.0
    assert revision.global_shipping.master_rate_usd == pytest.approx(LARGE_BOX)


def test_mixed_quote_with_a_manual_price_product_approves_and_exports_pdf(tmp_path):
    draft = _draft(_pick(("SPECTRA_GOLD", "SPECTRA0001"), ("DT40", "9757-2")))
    apply_final_price(
        draft,
        _line(draft, "DT40", "9757-2").line_id,
        FinalPriceStatus.MANUAL_OVERRIDE,
        amount_jpy=650000,
        reason_code=list(PriceAdjustmentReason)[0],
        reason_note="個別",
    )
    sb.select_global_shipping(draft, _large_box())
    sb.set_spectra_shipping(draft, actual_rate_usd=3000.0, reason="SPECTRA メーカー見積")
    candidate = draft.model_copy(deep=True)
    _, snapshot = approve_quote(
        candidate, approved_by="sales@example.com", confirmations=all_confirmations(), official_quote_number="SP-001"
    )
    _bundle, path = export_spaceone_quote_pdf(snapshot, output_dir=tmp_path)
    assert path.is_file()


# ---- UI -------------------------------------------------------------------------------------------


def _open(draft):
    from tests.test_portal3b1_1_product_picker import _open_builder

    return _open_builder(draft)


def _markdown(at):
    return [item.value for item in at.markdown]


def test_ui_sections_follow_the_price_books_in_the_quote():
    spectra_only = _draft(_pick(("SPECTRA_GOLD", "SPECTRA0001")))
    at = _open(spectra_only)
    suffix = f"{spectra_only.quote_draft_id}_{spectra_only.quote_version}"
    assert "##### SPECTRA GOLD 国際輸送費" in _markdown(at)
    assert not [item for item in at.selectbox if item.key == f"simple_shipping_{suffix}"]
    assert "##### 顧客向け国際輸送費 合計" not in _markdown(at)

    dt_only = _draft(_pick(("DT40", "9680-BASE")))
    at = _open(dt_only)
    suffix = f"{dt_only.quote_draft_id}_{dt_only.quote_version}"
    assert len(at.selectbox(key=f"simple_shipping_{suffix}").options) == 4
    assert "##### SPECTRA GOLD 国際輸送費" not in _markdown(at)

    mixed = _mixed()
    at = _open(mixed)
    markdown = _markdown(at)
    for heading in ("##### Deep Trekker / PipeTrekker 国際輸送費", "##### SPECTRA GOLD 国際輸送費", "##### 顧客向け国際輸送費 合計"):
        assert heading in markdown
    assert not at.exception


def test_ui_spectra_shipping_entry():
    draft = _draft(_pick(("DT40", "9680-BASE"), ("SPECTRA_GOLD", "SPECTRA0001")))
    at = _open(draft)
    suffix = f"{draft.quote_draft_id}_{draft.quote_version}"
    at.number_input(key=f"simple_spectra_ship_usd_{suffix}").set_value(1500.0)
    at.button(key=f"simple_spectra_ship_apply_{suffix}").click().run()
    assert any("理由・根拠を入力してください" in item.value for item in at.error)
    at.text_input(key=f"simple_spectra_ship_reason_{suffix}").set_value("SPECTRA メーカー見積")
    at.button(key=f"simple_spectra_ship_apply_{suffix}").click().run()
    assert not at.exception
    saved = at.session_state["quote_draft"]
    assert saved.spectra_shipping.actual_rate_usd == 1500.0
    assert saved.spectra_shipping.customer_price_jpy == _customer(1500)
