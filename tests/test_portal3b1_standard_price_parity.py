"""PORTAL-3B.1: the builder's standard price is the 価格一覧 standard price (same rule, DT40 and PT30)."""

import io

import pytest
from openpyxl import Workbook

from agents import simple_quote_builder as sb
from agents.price_master import import_price_master
from agents.pricing_policy import round_customer_price_jpy
from agents.quote_builder import apply_final_price
from models import FinalPriceStatus, PriceAdjustmentReason, PriceMasterType, ShippingType
from repositories.actor import set_current_actor
from repositories.shipping_rule_repository import ShippingRuleRepository
from repositories.sqlite_quote_repository import SqliteQuoteRepository
from tests.price_book_fixtures import official_dt40_style_book, official_pt30_style_book, quote_calc_formula_book

RATE = 160.0

# (sheet, sku, msrp usd, multiplier). 9757-2 and 10800S sit on two sheets with the same formula, which
# the price list resolves to one price; 8998 has two different formulas and stays without a price.
SO_ROWS = [
    ("PHOTON", "9680-BASE", 17391, 1.2),
    ("PHOTON", "9757-2", 3280, 1.2),
    ("PIVOT", "9757-2", 3280, 1.2),
    ("PHOTON", "8998", 381, 1.2),
    ("PIVOT", "8998", 381, 1.3),
    ("A-150", "10800S", 52500, 1.2),
    ("A-200", "10800S", 52500, 1.2),
]


def _so_master_book(rows=SO_ROWS) -> io.BytesIO:
    workbook = Workbook()
    workbook.remove(workbook.active)
    sheets = {}
    for sheet_name, sku, msrp, multiplier in rows:
        if sheet_name not in sheets:
            sheet = workbook.create_sheet(sheet_name)
            sheet["E1"] = "レート参考値"
            sheet["E2"] = "1ドル="
            sheet["F2"] = 170
            sheet["B3"] = "Part Number"
            sheet["C3"] = "製品名"
            sheet["E3"] = "価格"
            sheet["R3"] = "スペースワン設定価格"
            sheet["B4"] = "DTマスター\n価格表より"
            sheet["E4"] = "定価"
            sheet["F4"] = "卸値"
            sheets[sheet_name] = [sheet, 5]
        sheet, row = sheets[sheet_name]
        sheet.cell(row, 2, sku)
        sheet.cell(row, 3, sku)
        sheet.cell(row, 5, msrp)
        sheet.cell(row + 1, 5, f"=E{row}*$F$2")
        sheet.cell(row + 1, 18, f"=E{row + 1}*{multiplier}")
        sheets[sheet_name][1] = row + 3
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer


@pytest.fixture(autouse=True)
def masters():
    set_current_actor("sales@example.com")
    for master_type, book in (
        (PriceMasterType.DT40, official_dt40_style_book()),
        (PriceMasterType.PT30, official_pt30_style_book()),
        (PriceMasterType.QUOTE_CALC, quote_calc_formula_book()),
        (PriceMasterType.SO_MASTER, _so_master_book()),
    ):
        import_price_master(master_type, f"{master_type.value}.xlsx", book.getvalue())
    yield
    set_current_actor(None)


def _sales(rate=RATE):
    from ui.quote_control import _sales_candidates_for_rate

    return _sales_candidates_for_rate(rate)


def _price_list(rate=RATE) -> dict:
    """The 価格一覧 screen's own computation (render_price_catalog), keyed by (price book, SKU)."""
    from agents.price_master import active_price_books
    from agents.pricing_policy import is_customer_price_unit
    from ui.price_catalog import _reference_sales_candidates, build_price_catalog_rows, build_reference_sales_map

    books = active_price_books()
    reference = build_reference_sales_map(
        _reference_sales_candidates(books, rate),
        round_customer_price=round_customer_price_jpy,
        is_customer_price_unit=is_customer_price_unit,
    )
    return {(row["Price Book"], row["SKU"]): row["SpaceOne参考売価 JPY"] for row in build_price_catalog_rows(books, reference_sales=reference)}


def _draft(items, rate=RATE):
    return sb.create_simple_quote_draft(
        customer="テスト顧客",
        title=None,
        items=items,
        exchange_rate=rate,
        tax_rate=0.10,
        sales_candidates=_sales(rate),
    )


def _line(draft, sku):
    return next(line for line in draft.configuration_lines if line.manufacturer_sku == sku)


def test_price_list_prices_are_the_builder_standard_prices_for_dt40_and_pt30():
    price_list = _price_list()
    expected = {
        ("DT40", "9680-BASE"): round_customer_price_jpy(17391 * RATE * 1.2),
        ("DT40", "9757-2"): round_customer_price_jpy(3280 * RATE * 1.2),
        ("PT30", "10800S"): round_customer_price_jpy(52500 * RATE * 1.2),
    }
    for key, price in expected.items():
        assert price_list[key] == price

    draft = _draft([{"sku": sku, "quantity": 1} for _book, sku in expected])
    for (_book, sku), price in expected.items():
        line = _line(draft, sku)
        assert line.standard_sales_price_candidate_jpy == price
        assert line.final_sales_price_jpy == price
        assert line.final_price_status == FinalPriceStatus.USE_STANDARD_CANDIDATE
    # Same result when the products are added to an existing quote.
    added = _draft([{"sku": "9680-BASE", "quantity": 1}])
    sb.add_products(added, [{"sku": "9757-2", "quantity": 1}, {"sku": "10800S", "quantity": 1}], sales_candidates=_sales())
    assert _line(added, "9757-2").final_sales_price_jpy == expected[("DT40", "9757-2")]
    assert _line(added, "10800S").final_sales_price_jpy == expected[("PT30", "10800S")]


def test_every_priced_price_list_row_gets_the_same_builder_price():
    price_list = _price_list()
    priced = {sku: price for (book, sku), price in price_list.items() if book in sb.SIMPLE_PRICE_BOOKS and price is not None}
    draft = _draft([{"sku": sku, "quantity": 1} for sku in priced])
    assert {line.manufacturer_sku: line.standard_sales_price_candidate_jpy for line in draft.configuration_lines} == priced


def test_quantity_shipping_total_and_margin_with_price_list_prices():
    draft = _draft([{"sku": "9757-2", "quantity": 1}, {"sku": "10800S", "quantity": 1}])
    sb.set_quantity(draft, _line(draft, "9757-2").line_id, 3)
    unit_dt, unit_pt = round_customer_price_jpy(3280 * RATE * 1.2), round_customer_price_jpy(52500 * RATE * 1.2)
    assert sb.customer_summary(draft)["product_subtotal"] == pytest.approx(unit_dt * 3 + unit_pt)

    sb.select_global_shipping(draft, ShippingRuleRepository().get_active_standard_global(ShippingType.LARGE_BOX))
    shipping = round_customer_price_jpy(2922.15 * RATE * 1.2)
    sales = unit_dt * 3 + unit_pt + shipping
    cost = sum(line.dealer_cost_jpy + line.insurance_jpy + line.import_tax_jpy for line in draft.configuration_lines)
    cost += 2922.15 * RATE
    revenue = sb.revenue_summary(draft)
    assert sb.customer_summary(draft)["shipping"] == shipping
    assert revenue["sales_ex_tax"] == pytest.approx(sales)
    assert revenue["total_cost"] == pytest.approx(cost)
    assert revenue["gross_margin_rate"] == pytest.approx((sales - cost) / sales, abs=1e-6)


def test_products_without_a_price_list_price_still_need_a_manual_price():
    price_list = _price_list()
    # 8998 has two different SpaceOne formulas; 2535 is not in the SpaceOne master at all.
    assert price_list[("DT40", "8998")] is None and price_list[("DT40", "2535")] is None
    draft = _draft([{"sku": "8998", "quantity": 1}, {"sku": "2535", "quantity": 1}])
    for sku in ("8998", "2535"):
        line = _line(draft, sku)
        assert line.standard_sales_price_candidate_jpy is None
        assert line.final_price_status != FinalPriceStatus.USE_STANDARD_CANDIDATE
        apply_final_price(
            draft,
            line.line_id,
            FinalPriceStatus.MANUAL_OVERRIDE,
            amount_jpy=90000,
            reason_code=list(PriceAdjustmentReason)[0],
            reason_note="個別見積",
        )
        assert _line(draft, sku).final_sales_price_jpy == 90000


def test_exchange_rate_change_keeps_price_list_prices():
    draft = _draft([{"sku": "9757-2", "quantity": 1}])
    sb.change_exchange_rate(draft, 150.0, sales_candidates=_sales(150.0), reason_note="円高", set_by="x")
    assert _line(draft, "9757-2").final_sales_price_jpy == _price_list(150.0)[("DT40", "9757-2")]


def test_saved_amounts_do_not_follow_a_later_so_master_change():
    draft = _draft([{"sku": "9757-2", "quantity": 2}, {"sku": "10800S", "quantity": 1}])
    sb.select_global_shipping(draft, ShippingRuleRepository().get_active_standard_global(ShippingType.LARGE_BOX))
    SqliteQuoteRepository().save_draft(draft)
    before = (draft.subtotal_ex_tax_jpy, draft.total_jpy, draft.economics_result.total_landed_cost_jpy)

    # The SpaceOne multiplier for 9757-2 is raised; the price list now shows a new price.
    changed = _so_master_book([(sheet, sku, msrp, 1.5 if sku == "9757-2" else mult) for sheet, sku, msrp, mult in SO_ROWS])
    import_price_master(PriceMasterType.SO_MASTER, "SO_MASTER-new.xlsx", changed.getvalue())

    assert _price_list()[("DT40", "9757-2")] == round_customer_price_jpy(3280 * RATE * 1.5)

    loaded = SqliteQuoteRepository().get_draft(draft.quote_draft_id).draft
    assert (loaded.subtotal_ex_tax_jpy, loaded.total_jpy, loaded.economics_result.total_landed_cost_jpy) == before
    assert _line(loaded, "9757-2").final_sales_price_jpy == round_customer_price_jpy(3280 * RATE * 1.2)
