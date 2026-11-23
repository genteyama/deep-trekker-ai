"""PORTAL-3B.1 one-screen quote builder."""

import io

import pytest
from openpyxl import load_workbook

from agents import simple_quote_builder as sb
from agents.price_master import import_price_master
from agents.pricing_policy import round_customer_price_jpy
from agents.quote_approval import all_confirmations, approve_quote, create_revision_draft
from agents.quote_export import (
    export_internal_calc_excel,
    export_moneyforward_tsv,
    export_spaceone_quote_excel,
    export_spaceone_quote_pdf,
)
from models import FinalPriceStatus, PriceMasterType, QuoteDraftStatus, ShippingType
from repositories.actor import set_current_actor
from repositories.shipping_rule_repository import ShippingRuleRepository
from repositories.sqlite_quote_repository import SqliteQuoteRepository
from tests.price_book_fixtures import (
    official_dt40_style_book,
    official_pt30_style_book,
    quote_calc_formula_book,
    spaceone_master_book,
)
from tests.test_app_pages import _start_app
from tests.test_price_master_ui import _drop_stale_widgets

RATE = 160.0


@pytest.fixture(autouse=True)
def masters():
    set_current_actor("sales@example.com")
    for master_type, book in (
        (PriceMasterType.DT40, official_dt40_style_book()),
        (PriceMasterType.PT30, official_pt30_style_book()),
        (PriceMasterType.QUOTE_CALC, quote_calc_formula_book()),
        (PriceMasterType.SO_MASTER, spaceone_master_book()),
    ):
        import_price_master(master_type, f"{master_type.value}.xlsx", book.getvalue())
    yield
    set_current_actor(None)


def _sales(rate=RATE):
    from ui.quote_control import _sales_candidates_for_rate

    return _sales_candidates_for_rate(rate)


def _draft(items=None, rate=RATE):
    return sb.create_simple_quote_draft(
        customer="テスト顧客",
        title="PHOTON一式",
        items=items or [{"sku": "9680-BASE", "quantity": 1}],
        exchange_rate=rate,
        tax_rate=0.10,
        sales_candidates=_sales(rate),
    )


def _large_box():
    return ShippingRuleRepository().get_active_standard_global(ShippingType.LARGE_BOX)


def _line(draft, sku):
    return next(line for line in draft.configuration_lines if line.manufacturer_sku == sku)


# ---- product picker data --------------------------------------------------------------------------


def _catalog():
    from ui.simple_quote_builder import _catalog_rows, _master_key

    _catalog_rows.clear()
    return _catalog_rows(_master_key(), RATE)


def test_catalog_search_by_name_and_sku_and_filter_by_price_book():
    from ui.simple_quote_builder import filter_product_rows

    rows = _catalog()
    assert {row["Price Book"] for row in rows} == {"DT40", "PT30"}
    by_name = filter_product_rows(rows, keyword="photon base")
    assert [row["SKU"] for row in by_name] == ["9680-BASE"]
    assert by_name[0]["SpaceOne参考売価 JPY"] == 3540000
    assert [row["SKU"] for row in filter_product_rows(rows, keyword="9757")] == ["9757-2"]
    pt30 = filter_product_rows(rows, price_books=["PT30"])
    assert pt30 and all(row["Price Book"] == "PT30" for row in pt30)
    # Only rows the quote engine can price (正式価格) are offered; obsolete / review rows are not.
    assert "7511-SC-BASE" not in {row["SKU"] for row in rows}


# ---- lines ----------------------------------------------------------------------------------------


def test_multiple_products_quantity_merge_and_remove():
    draft = _draft([{"sku": "9680-BASE", "quantity": 1}, {"sku": "9757-2", "quantity": 1}])
    assert draft.builder == sb.SIMPLE_BUILDER
    assert [line.manufacturer_sku for line in draft.configuration_lines] == ["9680-BASE", "9757-2"]
    assert _line(draft, "9680-BASE").final_price_status == FinalPriceStatus.USE_STANDARD_CANDIDATE

    sb.add_products(draft, [{"sku": "9680-BASE", "quantity": 2}, {"sku": "8998", "quantity": 1}], sales_candidates=_sales())
    assert [line.manufacturer_sku for line in draft.configuration_lines] == ["9680-BASE", "9757-2", "8998"]
    base = _line(draft, "9680-BASE")
    assert base.quantity == 3
    assert base.dealer_cost_jpy == pytest.approx(10434.6 * 3 * RATE)

    sb.set_quantity(draft, base.line_id, 2)
    assert _line(draft, "9680-BASE").quantity == 2
    with pytest.raises(sb.SimpleQuoteError):
        sb.set_quantity(draft, base.line_id, 0)

    sb.remove_line(draft, _line(draft, "8998").line_id)
    assert [line.manufacturer_sku for line in draft.configuration_lines] == ["9680-BASE", "9757-2"]
    assert all(item.sku != "8998" for item in draft.pricing_context.manufacturer_price_snapshots)


def test_product_subtotal_is_unit_price_times_quantity():
    draft = _draft([{"sku": "9680-BASE", "quantity": 2}])
    summary = sb.customer_summary(draft)
    assert summary["product_subtotal"] == pytest.approx(3540000 * 2)


def test_manual_price_keeps_standard_price_and_reason():
    from agents.quote_builder import apply_final_price
    from models import PriceAdjustmentReason

    draft = _draft()
    line = draft.configuration_lines[0]
    apply_final_price(
        draft,
        line.line_id,
        FinalPriceStatus.MANUAL_OVERRIDE,
        amount_jpy=3300000,
        reason_code=list(PriceAdjustmentReason)[0],
        reason_note="値引き",
    )
    adjustment = draft.adjustments[-1]
    assert (adjustment.original_price_jpy, adjustment.final_price_jpy, adjustment.reason_note) == (3540000, 3300000, "値引き")


# ---- GlobalShipping -------------------------------------------------------------------------------


def test_global_shipping_cost_is_actual_and_customer_is_times_markup():
    draft = _draft()
    sb.select_global_shipping(draft, _large_box(), selected_by="sales@example.com")
    selection = draft.global_shipping
    cost = 2922.15 * RATE
    assert selection.master_rate_usd == pytest.approx(2922.15)
    assert selection.actual_rate_usd == pytest.approx(2922.15)
    assert selection.markup_multiplier == pytest.approx(1.2)
    assert draft.shipping_lines[0].cost_jpy == pytest.approx(cost)
    assert selection.customer_price_jpy == round_customer_price_jpy(cost * 1.2)
    assert sb.customer_summary(draft)["shipping"] == round_customer_price_jpy(cost * 1.2)
    assert selection.selected_by == "sales@example.com"


def test_manual_shipping_adjustment_keeps_master_value_and_reason():
    draft = _draft()
    sb.select_global_shipping(draft, _large_box())
    with pytest.raises(sb.SimpleQuoteError):
        sb.adjust_global_shipping(draft, actual_rate_usd=3000.0, rate_reason="")

    sb.adjust_global_shipping(draft, actual_rate_usd=3000.0, rate_reason="DT見積 2026-11 による")
    selection = draft.global_shipping
    assert selection.master_rate_usd == pytest.approx(2922.15)
    assert (selection.actual_rate_usd, selection.rate_adjusted) == (3000.0, True)
    assert selection.rate_adjustment_reason == "DT見積 2026-11 による"
    assert draft.shipping_lines[0].cost_jpy == pytest.approx(3000 * RATE)
    assert selection.customer_price_jpy == round_customer_price_jpy(3000 * RATE * 1.2)

    with pytest.raises(sb.SimpleQuoteError):
        sb.adjust_global_shipping(draft, actual_rate_usd=3000.0, rate_reason="x", customer_price_jpy=600500, customer_reason="y")
    sb.adjust_global_shipping(
        draft, actual_rate_usd=3000.0, rate_reason="DT見積", customer_price_jpy=600000, customer_reason="特別条件"
    )
    assert selection.customer_price_overridden is True
    assert selection.customer_price_jpy == 600000
    assert selection.auto_customer_price_jpy == round_customer_price_jpy(3000 * RATE * 1.2)
    assert sb.customer_summary(draft)["shipping"] == 600000

    sb.adjust_global_shipping(draft, actual_rate_usd=None)
    assert (selection.actual_rate_usd, selection.rate_adjusted, selection.customer_price_overridden) == (2922.15, False, False)


def test_cost_and_margin_use_four_cost_items_and_tax_exclusive_sales():
    draft = _draft([{"sku": "9680-BASE", "quantity": 1}])
    sb.select_global_shipping(draft, _large_box())
    revenue = sb.revenue_summary(draft)
    line = draft.configuration_lines[0]
    assert line.domestic_shipping_jpy == 0
    expected_cost = line.dealer_cost_jpy + line.insurance_jpy + line.import_tax_jpy + 2922.15 * RATE
    sales = 3540000 + round_customer_price_jpy(2922.15 * RATE * 1.2)
    assert revenue["total_cost"] == pytest.approx(expected_cost)
    assert revenue["sales_ex_tax"] == pytest.approx(sales)
    assert revenue["gross_profit"] == pytest.approx(sales - expected_cost)
    assert revenue["gross_margin_rate"] == pytest.approx((sales - expected_cost) / sales, abs=1e-6)
    assert draft.total_jpy == pytest.approx(sales * 1.1)
    # The approval engine sees the same numbers.
    assert draft.status == QuoteDraftStatus.READY_FOR_APPROVAL
    assert draft.economics_result.gross_margin_rate == pytest.approx(revenue["gross_margin_rate"], abs=1e-6)


def test_exchange_rate_change_reprices_standard_lines_and_shipping():
    draft = _draft()
    sb.select_global_shipping(draft, _large_box())
    sb.change_exchange_rate(draft, 170.0, sales_candidates=_sales(170.0), reason_note="円安", set_by="x")
    line = draft.configuration_lines[0]
    assert draft.exchange_rate == 170.0
    assert line.final_sales_price_jpy == line.standard_sales_price_candidate_jpy
    assert draft.shipping_lines[0].cost_jpy == pytest.approx(2922.15 * 170)
    assert draft.global_shipping.customer_price_jpy == round_customer_price_jpy(2922.15 * 170 * 1.2)


# ---- snapshot -------------------------------------------------------------------------------------


def test_saved_quote_does_not_follow_master_or_shipping_updates():
    draft = _draft()
    sb.select_global_shipping(draft, _large_box())
    repo = SqliteQuoteRepository()
    repo.save_draft(draft)
    before = (draft.subtotal_ex_tax_jpy, draft.economics_result.total_landed_cost_jpy, draft.global_shipping.cost_jpy)

    changed = official_dt40_style_book()
    workbook = load_workbook(changed)
    workbook["PHOTON"]["E6"] = 20000
    buffer = io.BytesIO()
    workbook.save(buffer)
    import_price_master(PriceMasterType.DT40, "DT40-new.xlsx", buffer.getvalue())
    ShippingRuleRepository().save_standard_global_rate(ShippingType.LARGE_BOX, rate_usd=9999, effective_from="2027-01-01")

    loaded = SqliteQuoteRepository().get_draft(draft.quote_draft_id).draft
    after = (loaded.subtotal_ex_tax_jpy, loaded.economics_result.total_landed_cost_jpy, loaded.global_shipping.cost_jpy)
    assert after == before
    assert loaded.global_shipping.master_rate_usd == pytest.approx(2922.15)
    # Editing a kept line still uses its own frozen price, not the new master.
    sb.set_quantity(loaded, loaded.configuration_lines[0].line_id, 1)
    assert loaded.configuration_lines[0].dealer_price_usd == pytest.approx(10434.6)
    sb.sync_after_rate_change(loaded)
    assert loaded.global_shipping.cost_jpy == pytest.approx(2922.15 * RATE)


# ---- approval / revision / exports -------------------------------------------------------------


def _approved(draft, number="SB-001"):
    repo = SqliteQuoteRepository()
    repo.save_draft(draft)
    candidate = draft.model_copy(deep=True)
    _, snapshot = approve_quote(
        candidate, approved_by="sales@example.com", confirmations=all_confirmations(), official_quote_number=number
    )
    repo.record_approval(candidate, snapshot)
    return candidate, snapshot


def test_builder_quote_approves_exports_and_revises_with_frozen_shipping(tmp_path):
    draft = _draft()
    sb.select_global_shipping(draft, _large_box())
    approved, snapshot = _approved(draft)

    assert snapshot.builder == sb.SIMPLE_BUILDER
    assert snapshot.global_shipping.actual_rate_usd == pytest.approx(2922.15)
    with pytest.raises(ValueError):
        sb.set_quantity(approved, approved.configuration_lines[0].line_id, 2)
    for exporter in (export_spaceone_quote_pdf, export_spaceone_quote_excel, export_internal_calc_excel, export_moneyforward_tsv):
        bundle, path = exporter(snapshot, output_dir=tmp_path)
        assert bundle.official_quote_number == "SB-001"
        assert path.is_file()
    assert snapshot.total_jpy == pytest.approx(approved.total_jpy)

    revision = create_revision_draft(snapshot)
    assert revision.builder == sb.SIMPLE_BUILDER
    assert revision.global_shipping.shipping_rule_id == snapshot.global_shipping.shipping_rule_id
    sb.set_quantity(revision, revision.configuration_lines[0].line_id, 2)
    assert revision.global_shipping.customer_price_jpy == snapshot.global_shipping.customer_price_jpy
    _approved(revision, number="SB-001")
    repo = SqliteQuoteRepository()
    assert repo.get_draft(approved.quote_draft_id, 1).draft.status == QuoteDraftStatus.SUPERSEDED
    assert repo.get_draft(revision.quote_draft_id, 2).draft.status == QuoteDraftStatus.APPROVED


# ---- UI -------------------------------------------------------------------------------------------


def _open_builder(draft=None):
    at = _start_app()
    if draft is not None:
        SqliteQuoteRepository().save_draft(draft)
        at.session_state["quote_draft"] = draft
    at.button(key="sidebar_nav_quote").click().run()
    assert not at.exception
    return at


def test_ui_builder_is_the_default_one_screen_page_without_steps():
    at = _open_builder()
    assert any(item.key == "simple_customer" for item in at.text_input)
    assert any(item.key == "simple_search" for item in at.text_input)
    assert not any((item.key or "").startswith("sidebar_quote_step_") for item in at.sidebar.button)
    assert any(item.key == "simple_open_legacy" for item in at.button)


def test_ui_quantity_delete_shipping_and_summary():
    draft = _draft([{"sku": "9680-BASE", "quantity": 1}, {"sku": "8998", "quantity": 1}])
    at = _open_builder(draft)
    base = _line(draft, "9680-BASE")
    at.number_input(key=f"simple_qty_{base.line_id}_1").set_value(3).run()
    _drop_stale_widgets(at)
    assert _line(at.session_state["quote_draft"], "9680-BASE").quantity == 3

    other = _line(at.session_state["quote_draft"], "8998")
    at.button(key=f"simple_remove_{other.line_id}").click().run()
    _drop_stale_widgets(at)
    assert [line.manufacturer_sku for line in at.session_state["quote_draft"].configuration_lines] == ["9680-BASE"]

    current = at.session_state["quote_draft"]
    key = f"simple_shipping_{current.quote_draft_id}_{current.quote_version}"
    rule_id = _large_box().rule.shipping_rule_id
    at.selectbox(key=key).set_value(rule_id).run()
    _drop_stale_widgets(at)
    assert not at.exception
    updated = at.session_state["quote_draft"]
    assert updated.global_shipping.shipping_rule_id == rule_id
    labels = [item.label for item in at.metric]
    assert {"見積額（税抜）", "税抜見積額", "原価合計", "粗利"} <= set(labels)
    # PORTAL-3B.1.2: 原価率 / 粗利率 sit under 原価合計 / 粗利.
    texts = [item.value for item in at.markdown]
    assert any(text.startswith("**原価率 ") for text in texts) and any(text.startswith("**粗利率 ") for text in texts)
    stored = SqliteQuoteRepository().get_draft(updated.quote_draft_id).draft
    assert stored.global_shipping.shipping_rule_id == rule_id


def test_ui_approve_and_export_on_the_same_page():
    from ui.quote_workspace import official_number_widget_key

    draft = _draft()
    sb.select_global_shipping(draft, _large_box())
    at = _open_builder(draft)
    for key in ("confirm_configuration", "confirm_presentation", "confirm_sales_price", "confirm_remarks"):
        at.checkbox(key=key).set_value(True).run()
    at.button(key="check_quote_approval").click().run()
    at.text_input(key=official_number_widget_key(draft)).set_value("UI-SB-1").run()
    at.button(key="approve_quote_snapshot").click().run()
    _drop_stale_widgets(at)

    assert not at.exception
    approved = at.session_state["quote_draft"]
    assert approved.status == QuoteDraftStatus.APPROVED
    assert approved.builder == sb.SIMPLE_BUILDER
    assert any(item.key == "export_spaceone_pdf" for item in at.button)
    assert not any((item.key or "").startswith("sidebar_quote_step_") for item in at.sidebar.button)


def test_ui_legacy_drafts_and_spectra_stay_on_the_legacy_screen():
    from tests.test_quote_builder import _photon_draft

    at = _start_app()
    at.session_state["quote_draft"] = _photon_draft()
    at.button(key="sidebar_nav_quote").click().run()
    assert any((item.key or "").startswith("sidebar_quote_step_") for item in at.sidebar.button)
    assert any(item.key == "quote_back_to_simple" for item in at.button)

    at = _open_builder()
    at.button(key="simple_open_legacy").click().run()
    _drop_stale_widgets(at)
    assert any((item.key or "").startswith("spectra_quote") for item in list(at.button) + list(at.text_input))
    assert any(item.key == "generic_quote_create" for item in at.button)
    at.button(key="quote_back_to_simple").click().run()
    _drop_stale_widgets(at)
    assert any(item.key == "simple_customer" for item in at.text_input)
