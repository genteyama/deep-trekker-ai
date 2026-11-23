"""PORTAL-3B.1.2: line order, purchase prices (Dealer / Gold) and cost / margin rates in the simple builder."""

import pytest
from openpyxl import load_workbook
from pypdf import PdfReader

from agents import simple_quote_builder as sb
from agents.price_master import import_price_master
from agents.quote_approval import all_confirmations, approve_quote, create_revision_draft
from agents.quote_builder import apply_final_price
from agents.quote_export import (
    export_moneyforward_tsv,
    export_spaceone_quote_excel,
    export_spaceone_quote_pdf,
)
from models import FinalPriceStatus, PriceAdjustmentReason, PriceMasterType, ShippingType
from repositories.shipping_rule_repository import ShippingRuleRepository
from repositories.sqlite_quote_repository import SqliteQuoteRepository
from tests.price_book_fixtures import build_workbook
from tests.test_portal3b1_1_product_picker import (  # noqa: F401  (autouse fixture)
    PT_HEADER,
    RATE,
    _draft,
    _line,
    _pick,
    _spectra,
    masters,
)

A = ("DT40", "9680-BASE")
B = ("PT30", "10800S")
C = ("SPECTRA_GOLD", "SPECTRA0001")
NAMES = {A: "PHOTON BASE PACKAGE", B: "A-200S", C: "SPECTRA Base Package"}


def _order(draft):
    return [sb.line_source(line)[:2] for line in draft.configuration_lines]


def _product_names(lines):
    return [line.display_name for line in lines if line.line_kind != "SHIPPING"]


def _priced_abc():
    draft = _draft(_pick(A, B, C))
    # 10800S has no SpaceOne standard price: a manual price, as in normal use.
    apply_final_price(
        draft,
        _line(draft, *B).line_id,
        FinalPriceStatus.MANUAL_OVERRIDE,
        amount_jpy=12000000,
        reason_code=list(PriceAdjustmentReason)[0],
        reason_note="個別",
    )
    sb.select_global_shipping(draft, ShippingRuleRepository().get_active_standard_global(ShippingType.LARGE_BOX))
    sb.set_spectra_shipping(draft, actual_rate_usd=1800.0, reason="SPECTRA メーカー見積")
    return draft


# ---- order --------------------------------------------------------------------------------------


def test_move_line_up_and_down():
    draft = _priced_abc()
    assert _order(draft) == [A, B, C]
    sb.move_line(draft, _line(draft, *C).line_id, -1)
    sb.move_line(draft, _line(draft, *C).line_id, -1)
    assert _order(draft) == [C, A, B]
    sb.move_line(draft, _line(draft, *C).line_id, -1)  # already first: no change
    sb.move_line(draft, _line(draft, *B).line_id, 1)  # already last: no change
    assert _order(draft) == [C, A, B]
    sb.move_line(draft, _line(draft, *A).line_id, 1)
    assert _order(draft) == [C, B, A]
    sb.move_line(draft, _line(draft, *A).line_id, -1)
    # The customer lines follow; shipping stays the last line with the same amount.
    assert _product_names(draft.customer_lines) == [NAMES[C], NAMES[A], NAMES[B]]
    assert draft.customer_lines[-1].line_kind == "SHIPPING"
    assert [line.display_order for line in draft.customer_lines] == [1, 2, 3, 4]
    assert sb.customer_summary(draft)["shipping"] == (
        draft.global_shipping.customer_price_jpy + draft.spectra_shipping.customer_price_jpy
    )


def _position(text, names):
    found = [(text.find(name), name) for name in names]
    assert all(index >= 0 for index, _name in found), found
    return [name for _index, name in sorted(found)]


def test_order_is_kept_through_save_reload_approval_exports_and_revision(tmp_path):
    draft = _priced_abc()
    before_total = draft.total_jpy
    for _ in range(2):
        sb.move_line(draft, _line(draft, *C).line_id, -1)
    expected = [NAMES[C], NAMES[A], NAMES[B]]
    assert draft.total_jpy == before_total

    repo = SqliteQuoteRepository()
    repo.save_draft(draft)
    loaded = repo.get_draft(draft.quote_draft_id).draft
    assert _order(loaded) == [C, A, B]
    assert _product_names(loaded.customer_lines) == expected

    candidate = loaded.model_copy(deep=True)
    _, snapshot = approve_quote(
        candidate, approved_by="sales@example.com", confirmations=all_confirmations(), official_quote_number="ORD-001"
    )
    repo.record_approval(candidate, snapshot)
    assert [sb.line_source(line)[:2] for line in snapshot.configuration_snapshot] == [C, A, B]
    assert _product_names(snapshot.customer_lines_snapshot) == expected

    _bundle, pdf_path = export_spaceone_quote_pdf(snapshot, output_dir=tmp_path)
    pdf_text = "".join(page.extract_text() for page in PdfReader(str(pdf_path)).pages)
    assert _position(pdf_text, expected) == expected

    _bundle, excel_path = export_spaceone_quote_excel(snapshot, output_dir=tmp_path)
    cells = " ".join(
        str(value) for sheet in load_workbook(excel_path).worksheets for row in sheet.iter_rows(values_only=True) for value in row if value
    )
    assert _position(cells, expected) == expected

    _bundle, tsv_path = export_moneyforward_tsv(snapshot, output_dir=tmp_path)
    assert _position(tsv_path.read_text(encoding="utf-8-sig"), expected) == expected

    revision = create_revision_draft(snapshot)
    assert _order(revision) == [C, A, B]
    assert _product_names(revision.customer_lines) == expected


# ---- purchase price -----------------------------------------------------------------------------


def test_purchase_price_is_dealer_for_dt_pt_and_gold_for_spectra():
    draft = _draft(_pick(A, B, C))
    assert {key: (sb.purchase_price(_line(draft, *key))["label"], sb.purchase_price(_line(draft, *key))["unit_usd"]) for key in (A, B, C)} == {
        A: ("Dealer", 10434.6),
        B: ("Dealer", 36750),
        C: ("Gold", 141750),
    }
    sb.set_quantity(draft, _line(draft, *A).line_id, 2)
    price = sb.purchase_price(_line(draft, *A))
    assert price["total_usd"] == pytest.approx(10434.6 * 2)
    assert price["jpy"] == pytest.approx(_line(draft, *A).dealer_cost_jpy)
    assert price["jpy"] == pytest.approx(10434.6 * 2 * RATE)


def test_same_sku_in_two_price_books_shows_each_dealer_price():
    pt30 = build_workbook(
        {
            "CONFIG": [["Dealer Retail:", "D_MSRP"], ["Discount Code:", "E_PT-30"]],
            "A-200": [PT_HEADER, [None, "PACKAGES"], [None, "10800S", "A-200S", 52500, 36750, None], [None, "9757-2", "BRIDGE BOX, ROV", 3280, 2100, None]],
        }
    )
    import_price_master(PriceMasterType.PT30, "PT30-dup.xlsx", pt30.getvalue())
    draft = _draft(_pick(("DT40", "9757-2"), ("PT30", "9757-2")))
    assert sb.purchase_price(_line(draft, "DT40", "9757-2"))["unit_usd"] == 1968
    assert sb.purchase_price(_line(draft, "PT30", "9757-2"))["unit_usd"] == 2100


def test_saved_purchase_prices_do_not_follow_a_master_update():
    draft = _draft(_pick(A, C))
    SqliteQuoteRepository().save_draft(draft)
    import_price_master(PriceMasterType.SPECTRA_GOLD, "SPECTRA-new.xlsx", _spectra(250000, 175000))
    loaded = SqliteQuoteRepository().get_draft(draft.quote_draft_id).draft
    assert sb.purchase_price(_line(loaded, *C))["unit_usd"] == 141750
    assert [group["total_usd"] for group in sb.purchase_breakdown(loaded)] == [10434.6, 141750]


# ---- profitability ------------------------------------------------------------------------------


def test_cost_rate_and_margin_rate_share_the_tax_exclusive_base():
    draft = _priced_abc()
    revenue = sb.revenue_summary(draft)
    sales, cost = revenue["sales_ex_tax"], revenue["total_cost"]
    assert revenue["cost_rate"] == pytest.approx(cost / sales, abs=1e-6)
    assert revenue["gross_margin_rate"] == pytest.approx((sales - cost) / sales, abs=1e-6)
    assert revenue["cost_rate"] + revenue["gross_margin_rate"] == pytest.approx(1.0, abs=1e-5)
    # The cost rule itself is unchanged: purchase + insurance + import tax + shipping.
    assert cost == pytest.approx(revenue["purchase"] + revenue["insurance"] + revenue["import_tax"] + revenue["shipping"])


def test_cost_rate_is_empty_without_sales():
    draft = _draft(_pick(B))
    revenue = sb.revenue_summary(draft)
    assert revenue["sales_ex_tax"] is None
    assert revenue["cost_rate"] is None and revenue["gross_margin_rate"] is None


def test_purchase_breakdown_keeps_dealer_and_gold_apart_and_matches_snapshots():
    draft = _priced_abc()
    sb.set_quantity(draft, _line(draft, *A).line_id, 2)
    groups = {group["label"]: group for group in sb.purchase_breakdown(draft)}
    assert set(groups) == {"Dealer", "Gold"}
    dealer_usd = sum(
        line.manufacturer_price_snapshot.manufacturer_dealer_price_usd * line.quantity
        for line in draft.configuration_lines
        if sb.line_source(line)[0] != "SPECTRA_GOLD"
    )
    assert groups["Dealer"]["total_usd"] == pytest.approx(dealer_usd)
    assert groups["Dealer"]["total_usd"] == pytest.approx(10434.6 * 2 + 36750)
    assert groups["Gold"]["total_usd"] == pytest.approx(141750)
    assert groups["Dealer"]["jpy"] == pytest.approx(_line(draft, *A).dealer_cost_jpy + _line(draft, *B).dealer_cost_jpy)
    assert groups["Gold"]["jpy"] == pytest.approx(_line(draft, *C).dealer_cost_jpy)
    assert groups["Dealer"]["jpy"] + groups["Gold"]["jpy"] == pytest.approx(sb.revenue_summary(draft)["purchase"])


# ---- UI -------------------------------------------------------------------------------------------


def _open(draft):
    from tests.test_portal3b1_1_product_picker import _open_builder

    return _open_builder(draft)


def test_ui_order_buttons_purchase_column_and_rates():
    from tests.test_price_master_ui import _drop_stale_widgets

    draft = _priced_abc()
    at = _open(draft)
    texts = [item.value for item in at.markdown]
    for title in ("**順番**", "**SKU / Price Book**", "**仕入価格 USD**", "**売価 JPY**"):
        assert title in texts
    assert "Dealer $10,434.60" in texts and "Gold $141,750.00" in texts
    assert any(text.startswith("**原価率 ") for text in texts) and any(text.startswith("**粗利率 ") for text in texts)
    assert any(item.value.startswith("Gold価格：$141,750.00 ／ Gold $141,750.00 × ¥160 = ¥22,680,000") for item in at.caption)
    assert at.button(key=f"simple_up_{_line(draft, *A).line_id}").disabled
    assert at.button(key=f"simple_down_{_line(draft, *C).line_id}").disabled

    at.button(key=f"simple_up_{_line(draft, *C).line_id}").click().run()
    _drop_stale_widgets(at)
    assert not at.exception
    assert _order(at.session_state["quote_draft"]) == [A, C, B]
    stored = SqliteQuoteRepository().get_draft(draft.quote_draft_id).draft
    assert _order(stored) == [A, C, B]
