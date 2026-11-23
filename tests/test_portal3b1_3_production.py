"""PORTAL-3B.1.3: fast 「見積に追加」, every quotable product in the picker, SPECTRA kinds, several GlobalShipping
rows with 個口数, no official quote number required, no legacy entry on the new quote screen."""

import pytest
from openpyxl import load_workbook
from pypdf import PdfReader

from agents import price_master
from agents import simple_quote_builder as sb
from agents.price_master import active_price_books, import_price_master
from agents.pricing_policy import round_customer_price_jpy
from agents.quote_approval import all_confirmations, approve_quote, create_revision_draft
from agents.quote_builder import apply_final_price
from agents.quote_export import export_moneyforward_tsv, export_spaceone_quote_excel, export_spaceone_quote_pdf
from models import FinalPriceStatus, PriceAdjustmentReason, PriceMasterType, QuoteDraft, QuoteDraftStatus, ShippingType
from repositories.shipping_rule_repository import ShippingRuleRepository
from repositories.sqlite_quote_repository import SqliteQuoteRepository
from tests.price_book_fixtures import build_workbook
from tests.test_portal3b1_1_product_picker import (  # noqa: F401  (autouse fixture)
    ALL,
    HEADER,
    RATE,
    _draft,
    _dt40_book,
    _filter,
    _line,
    _pick,
    _rows,
    _sales,
    masters,
)

PACKAGE = "機体・パッケージ"
OPTION = "オプション"


def _rate(shipping_type):
    return ShippingRuleRepository().get_active_standard_global(shipping_type)


def _usd(shipping_type):
    return float(_rate(shipping_type).rule.rate_usd)


def _customer(usd_total):
    # The existing shipping rule: cost x QUOTE_CALC markup (1.2), rounded with the customer price rule.
    return round_customer_price_jpy(usd_total * RATE * 1.2)


def _manual(draft, book, sku, amount=100000):
    apply_final_price(
        draft,
        _line(draft, book, sku).line_id,
        FinalPriceStatus.MANUAL_OVERRIDE,
        amount_jpy=amount,
        reason_code=list(PriceAdjustmentReason)[0],
        reason_note="個別",
    )


# ---- 「見積に追加」 speed: no workbook parsing after the list is shown -------------------------------


def test_add_reuses_parsed_masters_and_never_reparses_workbooks(monkeypatch):
    from ui.simple_quote_builder import _warm_quote_masters

    rows = _rows()  # the product list: parses the Active masters once
    _warm_quote_masters()  # QUOTE_CALC, parsed while the list is shown

    def forbidden(*_args, **_kwargs):
        raise AssertionError("a price master workbook was parsed again on 「見積に追加」")

    for name in ("parse_manufacturer_price_master", "parse_spaceone_master", "parse_spectra_gold", "extract_quote_calc_audit"):
        monkeypatch.setattr(price_master, name, forbidden)
    monkeypatch.setattr("agents.quote_control_agent.import_price_book", forbidden)

    items = _pick(("DT40", "8459"), ("PT30", "11490"), ("SPECTRA_GOLD", "SPECTRA0001"))
    draft = _draft(items)  # create (sales candidates + general entry per price book)
    sb.add_products(draft, _pick(("DT40", "9757-2")), sales_candidates=_sales())
    assert {sb.line_source(line)[:2] for line in draft.configuration_lines} == {
        ("DT40", "8459"),
        ("PT30", "11490"),
        ("SPECTRA_GOLD", "SPECTRA0001"),
        ("DT40", "9757-2"),
    }
    assert len(rows) == len(ALL)


def test_parse_cache_follows_the_active_master_and_keeps_the_stale_row_check():
    stale = _pick(("DT40", "9757-2"))
    first = {book.record.master_type: book.record.import_id for book in active_price_books()}
    workbook = build_workbook(
        {
            "CONFIG": [["Dealer Retail:", "D_MSRP"], ["Discount Code:", "E_DT-40"]],
            "PHOTON": [HEADER, ["OPTIONS - MISC"], [None, "9757-2", "BRIDGE BOX, ROV", 3400, 2040, None]],
        }
    )
    import_price_master(PriceMasterType.DT40, "DT40-new.xlsx", workbook.getvalue())
    books = {book.record.master_type: book for book in active_price_books()}
    assert books[PriceMasterType.DT40].record.import_id != first[PriceMasterType.DT40]
    assert [item.sku for item in books[PriceMasterType.DT40].book.candidates] == ["9757-2"]
    # A row picked from the list shown before the update is not added (PORTAL-3B.1 safety check).
    draft = _draft(_pick(("PT30", "11490")))
    with pytest.raises(sb.SimpleQuoteError) as error:
        sb.add_products(draft, stale, sales_candidates=_sales())
    assert error.value.code == "SOURCE_CHANGED"
    assert len(draft.configuration_lines) == 1


def test_cached_parse_is_a_copy_callers_cannot_change():
    book = active_price_books()[0].book
    book.candidates.clear()
    assert active_price_books()[0].book.candidates


# ---- 商品網羅 ---------------------------------------------------------------------------------------


def test_sku_8459_is_listed_and_added_without_a_standard_price():
    row = next(row for row in _rows() if (row["Price Book"], row["SKU"]) == ("DT40", "8459"))
    assert row["SpaceOne参考売価 JPY"] is None  # no SO_MASTER policy
    assert ("DT40", "8459") in _filter(kind="すべて")
    assert ("DT40", "8459") in _filter(keyword="8459")
    draft = _draft(_pick(("DT40", "8459")))
    line = _line(draft, "DT40", "8459")
    assert line.final_price_status == FinalPriceStatus.NOT_SET
    assert line.manufacturer_price_snapshot.manufacturer_dealer_price_usd == 472.2
    _manual(draft, "DT40", "8459", 120000)  # 売価を調整
    assert _line(draft, "DT40", "8459").final_sales_price_jpy == 120000


def test_all_lists_every_quotable_row_of_the_active_masters():
    from ui.simple_quote_builder import is_quotable_row

    quotable = set()
    for active in active_price_books():
        for candidate in active.book.candidates:
            if (
                candidate.source_status.value != "OBSOLETE"
                and candidate.dealer_price_usd is not None
                and (candidate.duplicate_class is None or candidate.duplicate_class.value != "PRICE_CONFLICT")
            ):
                quotable.add((active.record.master_type.value, candidate.sku))
    assert _filter(kind="すべて") == quotable == ALL
    # The SKU-only row (no prices) is not quotable and so not offered; nothing else is left out.
    assert ("DT40", "9511") not in quotable
    assert all(is_quotable_row(row) for row in _rows())
    # Standard price, kind and spare-parts headings never hide a row.
    assert {key for key in ALL if key[0] == "DT40"} >= {("DT40", "8998"), ("DT40", "7000"), ("DT40", "7100")}


def test_package_and_option_filters_for_dt40_and_pt30():
    assert _filter(kind=PACKAGE, price_books=["DT40"]) == {("DT40", "9680-BASE")}
    assert _filter(kind=PACKAGE, price_books=["PT30"]) == {("PT30", "10800S")}
    assert _filter(kind=OPTION, price_books=["DT40"]) == {("DT40", "9757-2"), ("DT40", "2535"), ("DT40", "8459")}
    assert _filter(kind=OPTION, price_books=["PT30"]) == {("PT30", "11490")}
    unclassified = ALL - _filter(kind=PACKAGE) - _filter(kind=OPTION)
    assert unclassified == {("DT40", "9680-OLD"), ("DT40", "8998"), ("DT40", "7000"), ("DT40", "7100")}
    assert unclassified <= _filter(kind="すべて")


def test_parser_headings_follow_the_manufacturer_layout(tmp_path):
    from parsers.price_book_parser import parse_price_book

    path = tmp_path / "dt40.xlsx"
    path.write_bytes(_dt40_book().getvalue())
    kinds = {}
    for occurrence in parse_price_book(path).occurrences:
        kinds.setdefault(occurrence.sku, []).append(occurrence.section_kind)
    assert kinds["9757-2"] == ["OPTIONS"]
    assert kinds["2535"] == ["OPTIONS"]  # the SKU-only row 9511 above it does not end the section
    assert kinds["8459"] == ["OPTIONS", "SPARE_PARTS"]  # heading next to the product, then a spare part
    assert kinds["7000"] == ["SPARE_PARTS"]  # under the BRIDGE BOX sub-heading
    assert kinds["7100"] == [None]  # after the "--" separator
    assert "PACKAGES" not in kinds and "BRIDGE BOX" not in kinds


# ---- SPECTRA 分類 -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sku", "kind"),
    [("SPECTRA0001", PACKAGE), ("SPECTRA0002", PACKAGE), ("SPECTRA001", OPTION), ("SPECTRA0003", OPTION), ("GOLD-TETHER", OPTION)],
)
def test_spectra_kind_rule(sku, kind):
    from ui.price_catalog import product_kind

    assert product_kind({"Price Book": "SPECTRA_GOLD", "SKU": sku, "_section_kinds": (None,)}) == kind


def test_spectra_rows_in_the_picker_by_kind():
    assert _filter(kind=PACKAGE, price_books=["SPECTRA_GOLD"]) == {("SPECTRA_GOLD", "SPECTRA0001")}
    assert _filter(kind=OPTION, price_books=["SPECTRA_GOLD"]) == {("SPECTRA_GOLD", "SPECTRA001")}


# ---- 複数GlobalShipping -------------------------------------------------------------------------------


def _dt_draft():
    draft = _draft(_pick(("DT40", "9680-BASE")))
    return draft


def test_large_two_and_small_one_rows_cost_customer_and_total():
    large, small = _usd(ShippingType.LARGE_BOX), _usd(ShippingType.SMALL_BOX)
    draft = _dt_draft()
    sb.add_global_shipping(draft, _rate(ShippingType.LARGE_BOX), quantity=2, selected_by="sales@example.com")
    sb.add_global_shipping(draft, _rate(ShippingType.SMALL_BOX), quantity=1)
    rows = draft.global_shipping_lines
    assert [(row.shipping_type, row.quantity) for row in rows] == [("LARGE_BOX", 2), ("SMALL_BOX", 1)]
    # Cost per row: unit USD x 個口数 x rate.
    assert rows[0].cost_jpy == pytest.approx(large * 2 * RATE)
    assert rows[1].cost_jpy == pytest.approx(small * RATE)
    # Customer per row: the existing markup and rounding on the row total (rounded once per row).
    assert rows[0].customer_price_jpy == _customer(large * 2)
    assert rows[1].customer_price_jpy == _customer(small)
    # Totals: one customer 国際輸送費 line = sum of the rows; cost = sum of the row costs.
    assert sb.customer_summary(draft)["shipping"] == _customer(large * 2) + _customer(small)
    assert sb.revenue_summary(draft)["shipping"] == pytest.approx((large * 2 + small) * RATE)
    assert [line.quantity for line in draft.shipping_lines] == [2, 1]
    shipping = [line for line in draft.customer_lines if line.line_kind == "SHIPPING"]
    assert len(shipping) == 1 and shipping[0].amount_jpy == _customer(large * 2) + _customer(small)
    assert draft.customer_lines[-1].line_kind == "SHIPPING"


def test_adding_the_same_kind_adds_packages_and_quantity_and_remove_work():
    large = _usd(ShippingType.LARGE_BOX)
    draft = _dt_draft()
    sb.add_global_shipping(draft, _rate(ShippingType.LARGE_BOX))
    sb.add_global_shipping(draft, _rate(ShippingType.LARGE_BOX))
    assert [(row.shipping_type, row.quantity) for row in draft.global_shipping_lines] == [("LARGE_BOX", 2)]
    rule_id = draft.global_shipping_lines[0].shipping_rule_id
    sb.set_global_shipping_quantity(draft, rule_id, 3)
    assert draft.global_shipping_lines[0].cost_jpy == pytest.approx(large * 3 * RATE)
    for bad in (0, -1, 1.5, True):
        with pytest.raises(sb.SimpleQuoteError) as error:
            sb.set_global_shipping_quantity(draft, rule_id, bad)
        assert error.value.code == "SHIPPING_QUANTITY_INVALID"
    sb.remove_global_shipping(draft, rule_id)
    assert draft.global_shipping_lines == [] and draft.shipping_lines == []
    assert sb.customer_summary(draft)["shipping"] is None


def test_row_adjustment_keeps_the_master_value_and_reason():
    large, small = _usd(ShippingType.LARGE_BOX), _usd(ShippingType.SMALL_BOX)
    draft = _dt_draft()
    sb.add_global_shipping(draft, _rate(ShippingType.LARGE_BOX), quantity=2)
    sb.add_global_shipping(draft, _rate(ShippingType.SMALL_BOX))
    small_id = draft.global_shipping_lines[1].shipping_rule_id
    with pytest.raises(sb.SimpleQuoteError):
        sb.adjust_global_shipping(draft, small_id, actual_rate_usd=500.0, rate_reason="")
    sb.adjust_global_shipping(draft, small_id, actual_rate_usd=500.0, rate_reason="DT見積 2026-11")
    large_row, small_row = draft.global_shipping_lines
    assert (small_row.master_rate_usd, small_row.actual_rate_usd, small_row.rate_adjusted) == (pytest.approx(small), 500.0, True)
    assert small_row.rate_adjustment_reason == "DT見積 2026-11"
    assert small_row.cost_jpy == pytest.approx(500.0 * RATE)
    assert not large_row.rate_adjusted and large_row.cost_jpy == pytest.approx(large * 2 * RATE)
    with pytest.raises(sb.SimpleQuoteError) as error:
        sb.adjust_global_shipping(draft, actual_rate_usd=500.0, rate_reason="x")  # two rows: which one?
    assert error.value.code == "SHIPPING_NOT_SELECTED"


def test_rows_are_frozen_through_save_reload_and_a_master_update():
    draft = _dt_draft()
    sb.add_global_shipping(draft, _rate(ShippingType.LARGE_BOX), quantity=2, selected_by="sales@example.com")
    sb.add_global_shipping(draft, _rate(ShippingType.SMALL_BOX))
    SqliteQuoteRepository().save_draft(draft)
    before = [row.model_dump() for row in draft.global_shipping_lines]
    for row in draft.global_shipping_lines:
        # snapshot / provenance of each row
        assert row.shipping_rule_id and row.label and row.master_effective_from and row.selected_at
        assert row.master_rate_usd == row.actual_rate_usd and row.quantity >= 1
    assert draft.global_shipping_lines[0].selected_by == "sales@example.com"

    ShippingRuleRepository().save_standard_global_rate(ShippingType.LARGE_BOX, rate_usd=9999, effective_from="2027-01-01")
    loaded = SqliteQuoteRepository().get_draft(draft.quote_draft_id).draft
    assert [row.model_dump() for row in loaded.global_shipping_lines] == before
    assert sb.customer_summary(loaded)["shipping"] == sb.customer_summary(draft)["shipping"]
    # Rows are matched by shipping master ID. The updated master is a new ID, so adding Large now is a new
    # row at the new value; the frozen row (and the packages already quoted) keep the value they had.
    updated = _rate(ShippingType.LARGE_BOX)
    assert updated.rule.shipping_rule_id != before[0]["shipping_rule_id"]
    sb.add_global_shipping(loaded, updated)
    assert [(row.shipping_rule_id, row.quantity, row.master_rate_usd) for row in loaded.global_shipping_lines] == [
        (before[0]["shipping_rule_id"], 2, before[0]["master_rate_usd"]),
        (before[1]["shipping_rule_id"], 1, before[1]["master_rate_usd"]),
        (updated.rule.shipping_rule_id, 1, 9999),
    ]


def test_quote_saved_with_the_single_shipping_choice_reads_as_one_row():
    draft = _dt_draft()
    sb.select_global_shipping(draft, _rate(ShippingType.LARGE_BOX))
    payload = draft.model_dump(mode="json")
    payload["global_shipping"] = payload.pop("global_shipping_lines")[0]
    payload["global_shipping"].pop("quantity")
    old = QuoteDraft.model_validate(payload)
    assert old.global_shipping is None
    assert [(row.shipping_type, row.quantity) for row in old.global_shipping_lines] == [("LARGE_BOX", 1)]
    assert sb.customer_summary(old)["shipping"] == sb.customer_summary(draft)["shipping"]


def test_approved_snapshot_with_the_single_shipping_choice_still_loads_and_revises():
    from models import ApprovedQuoteSnapshot

    draft = _dt_draft()
    sb.select_global_shipping(draft, _rate(ShippingType.LARGE_BOX))
    candidate = draft.model_copy(deep=True)
    _, snapshot = approve_quote(
        candidate, approved_by="sales@example.com", confirmations=all_confirmations(), official_quote_number="OLD-1"
    )
    payload = snapshot.model_dump(mode="json")
    payload["global_shipping"] = payload.pop("global_shipping_lines")[0]
    payload["global_shipping"].pop("quantity")
    old = ApprovedQuoteSnapshot.model_validate(payload)  # frozen model, saved before PORTAL-3B.1.3
    assert old.global_shipping is None
    assert [(row.shipping_type, row.quantity) for row in old.global_shipping_lines] == [("LARGE_BOX", 1)]
    assert old.official_quote_number == "OLD-1"
    revision = create_revision_draft(old)
    assert revision.global_shipping_lines[0].cost_jpy == draft.global_shipping_lines[0].cost_jpy


# ---- 混在 ---------------------------------------------------------------------------------------------


def test_mixed_quote_with_two_rows_and_spectra_shipping():
    large, small = _usd(ShippingType.LARGE_BOX), _usd(ShippingType.SMALL_BOX)
    draft = _draft(_pick(("DT40", "9680-BASE"), ("SPECTRA_GOLD", "SPECTRA0001")))
    sb.add_global_shipping(draft, _rate(ShippingType.LARGE_BOX), quantity=2)
    sb.add_global_shipping(draft, _rate(ShippingType.SMALL_BOX))
    sb.set_spectra_shipping(draft, actual_rate_usd=1800.0, reason="SPECTRA メーカー見積")
    parts = sb.shipping_breakdown(draft)
    assert parts["dt_pt_cost"] == pytest.approx((large * 2 + small) * RATE)
    assert parts["spectra_cost"] == pytest.approx(1800.0 * RATE)
    assert parts["dt_pt_customer"] == _customer(large * 2) + _customer(small)
    assert parts["spectra_customer"] == _customer(1800.0)
    revenue = sb.revenue_summary(draft)
    assert revenue["shipping"] == pytest.approx(parts["dt_pt_cost"] + parts["spectra_cost"])
    assert revenue["total_cost"] == pytest.approx(
        revenue["purchase"] + revenue["insurance"] + revenue["import_tax"] + revenue["shipping"]
    )
    assert sb.customer_summary(draft)["shipping"] == parts["dt_pt_customer"] + parts["spectra_customer"]
    assert [line.source_type for line in draft.shipping_lines] == [
        sb.GLOBAL_SHIPPING_SOURCE,
        sb.GLOBAL_SHIPPING_SOURCE,
        sb.SPECTRA_SHIPPING_SOURCE,
    ]
    # Removing the last DT / PT product drops its GlobalShipping rows, SPECTRA shipping stays.
    sb.remove_line(draft, _line(draft, "DT40", "9680-BASE").line_id)
    assert draft.global_shipping_lines == [] and draft.spectra_shipping is not None


# ---- 正式見積番号 ---------------------------------------------------------------------------------------


def _approved(number=None):
    draft = _dt_draft()
    sb.add_global_shipping(draft, _rate(ShippingType.LARGE_BOX), quantity=2)
    sb.add_global_shipping(draft, _rate(ShippingType.SMALL_BOX))
    repo = SqliteQuoteRepository()
    repo.save_draft(draft)  # 21: saved without a number
    assert repo.get_draft(draft.quote_draft_id).draft.official_quote_number is None
    candidate = repo.get_draft(draft.quote_draft_id).draft.model_copy(deep=True)
    _, snapshot = approve_quote(
        candidate, approved_by="sales@example.com", confirmations=all_confirmations(), official_quote_number=number
    )
    repo.record_approval(candidate, snapshot)
    return candidate, snapshot


def _excel_cells(path):
    return [cell for sheet in load_workbook(path).worksheets for row in sheet.iter_rows(values_only=True) for cell in row]


def test_approve_and_export_without_an_official_number(tmp_path):
    draft, snapshot = _approved()
    stored = SqliteQuoteRepository().get_snapshot_for_draft(draft.quote_draft_id, draft.quote_version)
    assert snapshot.status == QuoteDraftStatus.APPROVED and stored.official_quote_number is None
    assert stored.approved_by == "sales@example.com" and stored.approved_at is not None
    assert [(row.shipping_type, row.quantity) for row in stored.global_shipping_lines] == [("LARGE_BOX", 2), ("SMALL_BOX", 1)]

    pdf_bundle, pdf_path = export_spaceone_quote_pdf(snapshot, output_dir=tmp_path)
    excel_bundle, excel_path = export_spaceone_quote_excel(snapshot, output_dir=tmp_path)
    _tsv_bundle, tsv_path = export_moneyforward_tsv(snapshot, output_dir=tmp_path)
    assert pdf_bundle.official_quote_number is None and excel_bundle.official_quote_number is None
    sheet = load_workbook(excel_path)["見積書"]
    assert sheet["B8"].value in (None, "")  # 見積番号: blank
    # The internal ID is never printed as the quote number.
    internal = snapshot.quote_number_candidate
    assert internal and draft.quote_draft_id in internal
    pdf_text = "".join(page.extract_text() for page in PdfReader(str(pdf_path)).pages)
    assert internal not in pdf_text and draft.quote_draft_id not in pdf_text
    assert not any(isinstance(cell, str) and draft.quote_draft_id in cell for cell in _excel_cells(excel_path))
    assert tsv_path.exists()


def test_a_numbered_past_quote_keeps_its_number_in_exports_and_revision(tmp_path):
    draft, snapshot = _approved("MF-2026-001")
    _bundle, pdf_path = export_spaceone_quote_pdf(snapshot, output_dir=tmp_path)
    _bundle, excel_path = export_spaceone_quote_excel(snapshot, output_dir=tmp_path)
    assert "MF-2026-001" in "".join(page.extract_text() for page in PdfReader(str(pdf_path)).pages)
    assert load_workbook(excel_path)["見積書"]["B8"].value == "MF-2026-001"
    stored = SqliteQuoteRepository().get_snapshot_for_draft(draft.quote_draft_id, draft.quote_version)
    assert stored.official_quote_number == "MF-2026-001"
    revision = create_revision_draft(stored)
    assert revision.official_quote_number == "MF-2026-001"
    assert [(row.shipping_type, row.quantity) for row in revision.global_shipping_lines] == [("LARGE_BOX", 2), ("SMALL_BOX", 1)]


# ---- UI -----------------------------------------------------------------------------------------------


def _open(draft=None):
    from tests.test_portal3b1_1_product_picker import _open_builder

    return _open_builder(draft)


def test_ui_has_no_legacy_entry_on_the_new_quote_screen():
    at = _open()
    assert not any(item.key == "simple_open_legacy" for item in at.button)
    assert not any("従来の詳細画面" in (item.label or "") for item in at.expander)
    assert not any("SPECTRA見積" in (item.label or "") for item in at.expander)


def test_ui_legacy_draft_still_opens():
    from tests.test_app_pages import _start_app
    from tests.test_quote_builder import _photon_draft

    at = _start_app()
    at.session_state["quote_draft"] = _photon_draft()
    at.button(key="sidebar_nav_quote").click().run()
    assert not at.exception
    assert any((item.key or "").startswith("sidebar_quote_step_") for item in at.sidebar.button)


def test_ui_adds_shipping_rows_with_packages_changes_and_removes_them():
    from tests.test_price_master_ui import _drop_stale_widgets

    draft = _dt_draft()
    at = _open(draft)
    suffix = f"{draft.quote_draft_id}_{draft.quote_version}"
    large, small = _rate(ShippingType.LARGE_BOX).rule.shipping_rule_id, _rate(ShippingType.SMALL_BOX).rule.shipping_rule_id

    at.selectbox(key=f"simple_shipping_{suffix}").set_value(large).run()
    at.number_input(key=f"simple_ship_add_qty_{suffix}").set_value(2).run()
    at.button(key=f"simple_ship_add_{suffix}").click().run()
    _drop_stale_widgets(at)
    at.selectbox(key=f"simple_shipping_{suffix}").set_value(small).run()
    at.number_input(key=f"simple_ship_add_qty_{suffix}").set_value(1).run()
    at.button(key=f"simple_ship_add_{suffix}").click().run()
    _drop_stale_widgets(at)
    assert not at.exception
    rows = at.session_state["quote_draft"].global_shipping_lines
    assert [(row.shipping_rule_id, row.quantity) for row in rows] == [(large, 2), (small, 1)]
    texts = [item.value for item in at.markdown]
    for title in ("**種類**", "**単価 USD**", "**個口数**", "**実送料 USD**"):
        assert title in texts

    at.number_input(key=f"simple_ship_qty_{large}_{suffix}_2").set_value(3).run()
    _drop_stale_widgets(at)
    assert at.session_state["quote_draft"].global_shipping_lines[0].quantity == 3
    at.button(key=f"simple_ship_remove_{small}_{suffix}").click().run()
    _drop_stale_widgets(at)
    assert [(row.shipping_rule_id, row.quantity) for row in at.session_state["quote_draft"].global_shipping_lines] == [(large, 3)]
    stored = SqliteQuoteRepository().get_draft(draft.quote_draft_id).draft
    assert [(row.shipping_rule_id, row.quantity) for row in stored.global_shipping_lines] == [(large, 3)]
