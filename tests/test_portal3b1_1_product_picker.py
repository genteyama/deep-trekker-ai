"""PORTAL-3B.1.1: 商品種別 / Price Book (DT40, PT30, SPECTRA GOLD) / search in the simple quote builder."""

import pytest

from agents import simple_quote_builder as sb
from agents.price_master import import_price_master
from agents.pricing_policy import is_customer_price_unit, round_customer_price_jpy
from models import FinalPriceStatus, PriceMasterType, ShippingType
from repositories.actor import set_current_actor
from repositories.shipping_rule_repository import ShippingRuleRepository
from repositories.sqlite_quote_repository import SqliteQuoteRepository
from tests.price_book_fixtures import build_workbook, quote_calc_formula_book
from tests.test_portal3b1_standard_price_parity import _so_master_book
from tests.test_spectra_price_master import spectra_workbook

RATE = 160.0
HEADER = [None, "Part Number", "Description", "MSRP", "DT40", "Notes:"]
PT_HEADER = [None, "Part Number", "Description", "MSRP", "PT30", "Notes:"]


def _dt40_book():
    return build_workbook(
        {
            "CONFIG": [["Dealer Retail:", "D_MSRP"], ["Discount Code:", "E_DT-40"]],
            "PHOTON": [
                HEADER,
                [None, "PACKAGES"],
                [None, "9680-BASE", "PHOTON BASE PACKAGE", 17391, 10434.6, None],
                [None, "9680-OLD", "PHOTON OLD PACKAGE", 15000, 9000, None],
                [None, "OPTIONS - MISC"],
                [None, "9757-2", "BRIDGE BOX, ROV", 3280, 1968, None],
                [None, "2535", "GAME PAD", 105, 105, None],
                [None, "SPARE PARTS - MAJOR ASSEMBLIES"],
                [None, "8998", "CONTROLLER CABLE SUPPORT", 381, 228.6, None],
                [None, "BRIDGE BOX"],
                [None, "7000", "UNKNOWN SECTION ITEM", 50, 30, None],
            ],
        }
    )


def _pt30_book():
    return build_workbook(
        {
            "CONFIG": [["Dealer Retail:", "D_MSRP"], ["Discount Code:", "E_PT-30"]],
            "A-200": [
                PT_HEADER,
                [None, "PACKAGES"],
                [None, "10800S", "A-200S", 52500, 36750, None],
                [None, "ADD ON - WHEEL KITS"],
                [None, "11490", "ALL TERRAIN WHEELS", 1945, 1361.5, None],
            ],
        }
    )


SO_ROWS = [
    ("PHOTON", "9680-BASE", 17391, 1.2),
    ("SPECTRA", "SPECTRA0001", 202500, 1.2),
]


@pytest.fixture(autouse=True)
def masters():
    set_current_actor("sales@example.com")
    for master_type, data in (
        (PriceMasterType.DT40, _dt40_book().getvalue()),
        (PriceMasterType.PT30, _pt30_book().getvalue()),
        (PriceMasterType.SPECTRA_GOLD, _spectra(202500, 141750)),
        (PriceMasterType.QUOTE_CALC, quote_calc_formula_book().getvalue()),
        (PriceMasterType.SO_MASTER, _so_master_book(SO_ROWS).getvalue()),
    ):
        import_price_master(master_type, f"{master_type.value}.xlsx", data)
    yield
    set_current_actor(None)


def _spectra(msrp, gold):
    return spectra_workbook(first_msrp=msrp, first_gold=gold, first_description="SPECTRA Base Package").getvalue()


def _rows():
    from ui.simple_quote_builder import _catalog_rows, _master_key

    _catalog_rows.clear()
    return _catalog_rows(_master_key(), RATE)


def _skus(rows):
    return {(row["Price Book"], row["SKU"]) for row in rows}


def _filter(**kwargs):
    from ui.simple_quote_builder import filter_product_rows

    return _skus(filter_product_rows(_rows(), **kwargs))


def _sales(rate=RATE):
    from ui.quote_control import _sales_candidates_for_rate

    return _sales_candidates_for_rate(rate)


def _pick(*keys):
    from ui.simple_quote_builder import picked_items

    rows = [row for row in _rows() if (row["Price Book"], row["SKU"]) in keys]
    assert len(rows) == len(keys)
    return picked_items(rows, [{"選択": True}] * len(rows))


def _draft(items):
    return sb.create_simple_quote_draft(
        customer="テスト顧客", title=None, items=items, exchange_rate=RATE, tax_rate=0.10, sales_candidates=_sales()
    )


def _line(draft, book, sku):
    return next(line for line in draft.configuration_lines if sb.line_source(line)[:2] == (book, sku))


def _price_list_reference(book, sku):
    """The 価格一覧 screen's standard price (render_price_catalog's own computation, all Active books)."""
    from agents.price_master import active_price_books
    from ui.price_catalog import _reference_sales_candidates, build_price_catalog_rows, build_reference_sales_map

    books = active_price_books()
    reference = build_reference_sales_map(
        _reference_sales_candidates(books, RATE),
        round_customer_price=round_customer_price_jpy,
        is_customer_price_unit=is_customer_price_unit,
    )
    rows = build_price_catalog_rows(books, reference_sales=reference)
    return next(row["SpaceOne参考売価 JPY"] for row in rows if (row["Price Book"], row["SKU"]) == (book, sku))


ALL = {
    ("DT40", "9680-BASE"),
    ("DT40", "9680-OLD"),
    ("DT40", "9757-2"),
    ("DT40", "2535"),
    ("DT40", "8998"),
    ("DT40", "7000"),
    ("PT30", "10800S"),
    ("PT30", "11490"),
    ("SPECTRA_GOLD", "SPECTRA0001"),
    ("SPECTRA_GOLD", "SPECTRA001"),
}


# ---- 商品種別 -------------------------------------------------------------------------------------


def test_product_kind_all_packages_and_options():
    assert _filter(kind="すべて") == ALL
    assert _filter() == ALL
    # 機体・パッケージ is the price list's 主要機体・パッケージ allowlist (9680-OLD sits under PACKAGES but
    # is not on it, so it is not guessed into a kind).
    assert _filter(kind="機体・パッケージ") == {("DT40", "9680-BASE"), ("PT30", "10800S")}
    # オプション: rows under OPTIONS / ADD ON headings only. Spare parts, unknown headings and SPECTRA
    # are unclassified and only listed under すべて.
    assert _filter(kind="オプション") == {("DT40", "9757-2"), ("DT40", "2535"), ("PT30", "11490")}


def test_product_kind_matches_the_price_list_package_allowlist():
    from ui.price_catalog import build_primary_package_rows, product_kind

    rows = _rows()
    primary = _skus(build_primary_package_rows(rows))
    assert {key for key, row in ((( row["Price Book"], row["SKU"]), row) for row in rows) if product_kind(row) == "機体・パッケージ"} == primary


def test_product_kind_with_keyword_and_price_book():
    assert _filter(kind="オプション", keyword="wheel") == {("PT30", "11490")}
    assert _filter(kind="オプション", keyword="PHOTON") == {("DT40", "9757-2"), ("DT40", "2535")}  # Sheet name
    assert _filter(kind="オプション", price_books=["DT40"]) == {("DT40", "9757-2"), ("DT40", "2535")}
    assert _filter(kind="機体・パッケージ", price_books=["PT30"], keyword="a-200") == {("PT30", "10800S")}


# ---- Price Book -----------------------------------------------------------------------------------


def test_price_book_filter_single_multiple_and_none():
    assert {book for book, _sku in _filter(price_books=["DT40"])} == {"DT40"}
    assert {book for book, _sku in _filter(price_books=["PT30"])} == {"PT30"}
    assert _filter(price_books=["SPECTRA_GOLD"]) == {("SPECTRA_GOLD", "SPECTRA0001"), ("SPECTRA_GOLD", "SPECTRA001")}
    assert {book for book, _sku in _filter(price_books=["DT40", "SPECTRA_GOLD"])} == {"DT40", "SPECTRA_GOLD"}
    assert _filter(price_books=[]) == ALL


# ---- SPECTRA --------------------------------------------------------------------------------------


def test_spectra_search_shows_price_list_standard_price():
    rows = {(row["Price Book"], row["SKU"]): row for row in _rows()}
    assert _filter(keyword="spectra base") == {("SPECTRA_GOLD", "SPECTRA0001")}
    row = rows[("SPECTRA_GOLD", "SPECTRA0001")]
    assert row["SpaceOne参考売価 JPY"] == _price_list_reference("SPECTRA_GOLD", "SPECTRA0001")
    assert row["SpaceOne参考売価 JPY"] == round_customer_price_jpy(202500 * RATE * 1.2)
    # A SPECTRA SKU without a SpaceOne policy has no standard price, as in the price list.
    assert rows[("SPECTRA_GOLD", "SPECTRA001")]["SpaceOne参考売価 JPY"] is None


def test_spectra_line_uses_gold_cost_and_price_list_price_and_mixes_with_dt_pt():
    draft = _draft(_pick(("SPECTRA_GOLD", "SPECTRA0001"), ("DT40", "9680-BASE"), ("PT30", "11490")))
    spectra = _line(draft, "SPECTRA_GOLD", "SPECTRA0001")
    snapshot = spectra.manufacturer_price_snapshot
    assert (snapshot.price_book, snapshot.manufacturer_msrp_usd, snapshot.manufacturer_dealer_price_usd) == ("SPECTRA_GOLD", 202500, 141750)
    assert snapshot.price_master_import_id.startswith("SPECTRA_GOLD-") and snapshot.price_master_sha256
    assert snapshot.source_sheet == "SPECTRA"
    assert spectra.manufacturer_description == "SPECTRA Base Package"
    assert spectra.dealer_cost_jpy == pytest.approx(141750 * RATE)
    # Same QUOTE_CALC landed cost rule as the existing SPECTRA quote entry: insurance and import tax on dealer JPY.
    assert spectra.insurance_jpy == pytest.approx(141750 * RATE * 0.03)
    assert spectra.import_tax_jpy == pytest.approx(141750 * RATE * 0.10)
    assert spectra.final_sales_price_jpy == _price_list_reference("SPECTRA_GOLD", "SPECTRA0001")
    assert spectra.final_price_status == FinalPriceStatus.USE_STANDARD_CANDIDATE
    assert _line(draft, "DT40", "9680-BASE").final_sales_price_jpy == round_customer_price_jpy(17391 * RATE * 1.2)
    assert sb.price_books_in(draft) == {"DT40", "PT30", "SPECTRA_GOLD"}

    sb.set_quantity(draft, spectra.line_id, 2)
    assert _line(draft, "SPECTRA_GOLD", "SPECTRA0001").dealer_cost_jpy == pytest.approx(141750 * RATE * 2)
    sb.add_products(draft, _pick(("SPECTRA_GOLD", "SPECTRA0001")), sales_candidates=_sales())
    assert _line(draft, "SPECTRA_GOLD", "SPECTRA0001").quantity == 3
    assert len(draft.configuration_lines) == 3


def _state(draft):
    return (
        sorted(
            (sb.line_source(line), line.dealer_cost_jpy, line.landed_cost_jpy, line.final_sales_price_jpy)
            for line in draft.configuration_lines
        ),
        draft.subtotal_ex_tax_jpy,
        draft.total_jpy,
        draft.economics_result.total_landed_cost_jpy,
    )


def test_saved_spectra_quote_keeps_amounts_after_reload_and_master_update():
    draft = _draft(_pick(("SPECTRA_GOLD", "SPECTRA0001"), ("DT40", "9680-BASE")))
    sb.select_global_shipping(draft, ShippingRuleRepository().get_active_standard_global(ShippingType.LARGE_BOX))
    SqliteQuoteRepository().save_draft(draft)
    before = _state(draft)
    assert _state(SqliteQuoteRepository().get_draft(draft.quote_draft_id).draft) == before

    import_price_master(PriceMasterType.SPECTRA_GOLD, "SPECTRA_GOLD-new.xlsx", _spectra(250000, 175000))
    import_price_master(
        PriceMasterType.SO_MASTER, "SO-new.xlsx", _so_master_book([(s, k, m, 1.5) for s, k, m, _ in SO_ROWS]).getvalue()
    )
    assert _price_list_reference("SPECTRA_GOLD", "SPECTRA0001") == round_customer_price_jpy(250000 * RATE * 1.5)
    loaded = SqliteQuoteRepository().get_draft(draft.quote_draft_id).draft
    assert _state(loaded) == before
    assert _line(loaded, "SPECTRA_GOLD", "SPECTRA0001").manufacturer_price_snapshot.manufacturer_dealer_price_usd == 141750


# ---- UI -------------------------------------------------------------------------------------------


def _open_builder(draft=None):
    from tests.test_app_pages import _start_app

    at = _start_app()
    if draft is not None:
        SqliteQuoteRepository().save_draft(draft)
        at.session_state["quote_draft"] = draft
    at.button(key="sidebar_nav_quote").click().run()
    assert not at.exception
    return at


def _count_caption(at):
    return next(item.value for item in at.caption if " 件 ・ " in item.value)


def test_ui_product_kind_and_price_book_controls():
    at = _open_builder()
    assert list(at.radio(key="simple_product_kind").options) == ["すべて", "機体・パッケージ", "オプション"]
    assert _count_caption(at).startswith("10 / 10 件 ・ すべて ・ 全Price Book")
    group = at.button_group(key="simple_price_books")
    assert [option.content for option in group.options] == ["DT40", "PT30", "SPECTRA GOLD"]

    at.radio(key="simple_product_kind").set_value("オプション").run()
    assert _count_caption(at).startswith("3 / 10 件 ・ オプション")
    at.button_group(key="simple_price_books").set_value(["PT30"]).run()
    assert _count_caption(at).startswith("1 / 10 件 ・ オプション ・ PT30")
    at.radio(key="simple_product_kind").set_value("すべて").run()
    at.button_group(key="simple_price_books").set_value(["DT40", "SPECTRA_GOLD"]).run()
    assert _count_caption(at).startswith("8 / 10 件 ・ すべて ・ DT40 + SPECTRA GOLD")
    assert not at.exception
