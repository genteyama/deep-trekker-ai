"""PORTAL-3B.1: the picked price book row is the source of a builder line (same SKU in DT40 and PT30)."""

import pytest

from agents import simple_quote_builder as sb
from agents.general_quote_entry import GeneralQuoteEntryError
from agents.price_master import import_price_master
from agents.quote_approval import all_confirmations, approve_quote
from agents.quote_builder import apply_final_price
from agents.quote_export import export_spaceone_quote_excel, export_spaceone_quote_pdf
from models import FinalPriceStatus, PriceAdjustmentReason, PriceMasterType, ShippingType
from repositories.actor import set_current_actor
from repositories.shipping_rule_repository import ShippingRuleRepository
from repositories.sqlite_quote_repository import SqliteQuoteRepository
from tests.price_book_fixtures import build_workbook, official_dt40_style_book, quote_calc_formula_book, spaceone_master_book

RATE = 160.0
# 8998 is DT40 PIVOT 381 / 228.6 (fixture) and PT30 A-150 381 / 280.0 here: same SKU, different price.
PT30_8998_DEALER = 280.0


def _pt30_book(dealer_8998=PT30_8998_DEALER):
    return build_workbook(
        {
            "CONFIG": [["Dealer Retail:", "D_MSRP"], ["Discount Code:", "E_PT-30"]],
            "A-150": [
                [None, "Part Number", "Description", "MSRP", "PT30", "Notes:"],
                [None, "11000S", "A-150 S", 47500, 33250, "Base system"],
                [None, "8998", "CONTROLLER CABLE SUPPORT", 381, dealer_8998, None],
            ],
            "A-200": [
                [None, "Part Number", "Description", "MSRP", "PT30", "Notes:"],
                [None, "10800S", "A-200S", 52500, 36750, None],
            ],
        }
    )


@pytest.fixture(autouse=True)
def masters():
    set_current_actor("sales@example.com")
    for master_type, book in (
        (PriceMasterType.DT40, official_dt40_style_book()),
        (PriceMasterType.PT30, _pt30_book()),
        (PriceMasterType.QUOTE_CALC, quote_calc_formula_book()),
        (PriceMasterType.SO_MASTER, spaceone_master_book()),
    ):
        import_price_master(master_type, f"{master_type.value}.xlsx", book.getvalue())
    yield
    set_current_actor(None)


def _sales(rate=RATE):
    from ui.quote_control import _sales_candidates_for_rate

    return _sales_candidates_for_rate(rate)


def _rows():
    from ui.simple_quote_builder import _catalog_rows, _master_key

    _catalog_rows.clear()
    return _catalog_rows(_master_key(), RATE)


def _pick(*keys):
    """Catalog rows for (price book, SKU) keys, turned into add items exactly as the picker does."""
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


def test_both_rows_of_a_same_sku_different_price_product_are_listed_and_addable():
    listed = {(row["Price Book"], row["Dealer USD"]) for row in _rows() if row["SKU"] == "8998"}
    assert listed == {("DT40", 228.6), ("PT30", PT30_8998_DEALER)}
    # Looking the SKU up in every book is still a conflict (the legacy SKU-only entry is unchanged) ...
    with pytest.raises(GeneralQuoteEntryError):
        _draft([{"sku": "8998", "quantity": 1}])

    # ... but a picked row is used as it is.
    draft = _draft(_pick(("DT40", "8998"), ("PT30", "8998")))
    dt40, pt30 = _line(draft, "DT40", "8998"), _line(draft, "PT30", "8998")
    assert dt40.line_id != pt30.line_id
    assert dt40.manufacturer_price_snapshot.manufacturer_dealer_price_usd == pytest.approx(228.6)
    assert dt40.dealer_cost_jpy == pytest.approx(228.6 * RATE)
    assert pt30.manufacturer_price_snapshot.manufacturer_dealer_price_usd == pytest.approx(PT30_8998_DEALER)
    assert pt30.dealer_cost_jpy == pytest.approx(PT30_8998_DEALER * RATE)
    # The catalog row's Sheet / Category (DT40 lists 8998 on two sheets at the same price).
    assert dt40.manufacturer_price_snapshot.source_sheet == "PIVOT / REVOLUTION-OBSOLETE"
    assert pt30.manufacturer_price_snapshot.source_sheet == "A-150"
    assert dt40.manufacturer_price_snapshot.price_master_import_id.startswith("DT40-")
    assert pt30.manufacturer_price_snapshot.price_master_import_id.startswith("PT30-")
    assert pt30.manufacturer_price_snapshot.price_master_sha256


def test_only_the_picked_book_is_added():
    draft = _draft(_pick(("PT30", "8998")))
    assert [sb.line_source(line)[:2] for line in draft.configuration_lines] == [("PT30", "8998")]
    sb.add_products(draft, _pick(("DT40", "8998")), sales_candidates=_sales())
    assert [sb.line_source(line)[:2] for line in draft.configuration_lines] == [("PT30", "8998"), ("DT40", "8998")]


def test_re_adding_the_same_source_adds_quantity_and_other_sources_are_not_merged():
    draft = _draft(_pick(("DT40", "8998"), ("PT30", "8998")))
    sb.add_products(draft, _pick(("DT40", "8998")), sales_candidates=_sales())
    assert len(draft.configuration_lines) == 2
    assert _line(draft, "DT40", "8998").quantity == 2
    assert _line(draft, "DT40", "8998").dealer_cost_jpy == pytest.approx(228.6 * RATE * 2)
    assert _line(draft, "PT30", "8998").quantity == 1
    # The same row twice in one add is one line.
    single = _draft(_pick(("PT30", "8998")) * 2)
    assert [(sb.line_source(line)[:2], line.quantity) for line in single.configuration_lines] == [(("PT30", "8998"), 2)]


def test_lines_without_a_standard_price_take_a_manual_price_each():
    draft = _draft(_pick(("DT40", "8998"), ("PT30", "8998")))
    for book, amount in (("DT40", 60000), ("PT30", 70000)):
        line = _line(draft, book, "8998")
        assert line.standard_sales_price_candidate_jpy is None
        assert line.final_price_status == FinalPriceStatus.NOT_SET
        apply_final_price(
            draft,
            line.line_id,
            FinalPriceStatus.MANUAL_OVERRIDE,
            amount_jpy=amount,
            reason_code=list(PriceAdjustmentReason)[0],
            reason_note="個別見積",
        )
    assert _line(draft, "DT40", "8998").final_sales_price_jpy == 60000
    assert _line(draft, "PT30", "8998").final_sales_price_jpy == 70000
    assert sb.customer_summary(draft)["product_subtotal"] == pytest.approx(130000)


def _priced_draft():
    draft = _draft(_pick(("DT40", "8998"), ("PT30", "8998")))
    for book, amount in (("DT40", 60000), ("PT30", 70000)):
        apply_final_price(
            draft,
            _line(draft, book, "8998").line_id,
            FinalPriceStatus.MANUAL_OVERRIDE,
            amount_jpy=amount,
            reason_code=list(PriceAdjustmentReason)[0],
            reason_note="個別見積",
        )
    sb.select_global_shipping(draft, ShippingRuleRepository().get_active_standard_global(ShippingType.SMALL_BOX))
    return draft


def _state(draft):
    return sorted(
        (
            sb.line_source(line),
            line.manufacturer_price_snapshot.source_sheet,
            line.manufacturer_price_snapshot.manufacturer_msrp_usd,
            line.manufacturer_price_snapshot.manufacturer_dealer_price_usd,
            line.dealer_cost_jpy,
            line.landed_cost_jpy,
            line.final_sales_price_jpy,
        )
        for line in draft.configuration_lines
    )


def test_saved_lines_keep_source_and_amounts_after_reload_and_master_update(tmp_path):
    draft = _priced_draft()
    SqliteQuoteRepository().save_draft(draft)
    before = (_state(draft), draft.subtotal_ex_tax_jpy, draft.total_jpy, draft.economics_result.total_landed_cost_jpy)

    loaded = SqliteQuoteRepository().get_draft(draft.quote_draft_id).draft
    assert (_state(loaded), loaded.subtotal_ex_tax_jpy, loaded.total_jpy, loaded.economics_result.total_landed_cost_jpy) == before

    stale_pick = _pick(("PT30", "11000S"))
    same_source_pick = _pick(("PT30", "8998"))
    import_price_master(PriceMasterType.PT30, "PT30-new.xlsx", _pt30_book(dealer_8998=300.0).getvalue())
    reloaded = SqliteQuoteRepository().get_draft(draft.quote_draft_id).draft
    assert (_state(reloaded), reloaded.subtotal_ex_tax_jpy, reloaded.total_jpy, reloaded.economics_result.total_landed_cost_jpy) == before
    # Editing a kept line still uses its own snapshot.
    sb.set_quantity(reloaded, _line(reloaded, "PT30", "8998").line_id, 2)
    assert _line(reloaded, "PT30", "8998").dealer_cost_jpy == pytest.approx(PT30_8998_DEALER * RATE * 2)

    # Re-adding the exact source of a kept line adds to that line, at its own snapshot price.
    sb.add_products(reloaded, same_source_pick, sales_candidates=_sales())
    assert _line(reloaded, "PT30", "8998").quantity == 3
    assert _line(reloaded, "PT30", "8998").dealer_cost_jpy == pytest.approx(PT30_8998_DEALER * RATE * 3)

    # A new row picked from the old master is not silently re-priced from the new one.
    with pytest.raises(sb.SimpleQuoteError) as error:
        sb.add_products(reloaded, stale_pick, sales_candidates=_sales())
    assert error.value.code == "SOURCE_CHANGED"
    # Picking again from the new list adds the new import as its own line (not merged into the old one).
    sb.add_products(reloaded, _pick(("PT30", "8998")), sales_candidates=_sales())
    pt30_lines = [line for line in reloaded.configuration_lines if sb.line_source(line)[:2] == ("PT30", "8998")]
    assert sorted(line.manufacturer_price_snapshot.manufacturer_dealer_price_usd for line in pt30_lines) == [PT30_8998_DEALER, 300.0]


def test_same_sku_lines_approve_and_export(tmp_path):
    draft = _priced_draft()
    repo = SqliteQuoteRepository()
    repo.save_draft(draft)
    candidate = draft.model_copy(deep=True)
    _, snapshot = approve_quote(
        candidate, approved_by="sales@example.com", confirmations=all_confirmations(), official_quote_number="SB-DUP"
    )
    repo.record_approval(candidate, snapshot)
    assert sorted(line.final_sales_price_jpy for line in snapshot.configuration_snapshot) == [60000, 70000]
    assert {sb.line_source(line)[0] for line in snapshot.configuration_snapshot} == {"DT40", "PT30"}
    for exporter in (export_spaceone_quote_pdf, export_spaceone_quote_excel):
        _bundle, path = exporter(snapshot, output_dir=tmp_path)
        assert path.is_file()


def test_standard_prices_still_apply_to_picked_rows():
    draft = _draft(_pick(("DT40", "9680-BASE")))
    line = _line(draft, "DT40", "9680-BASE")
    assert line.final_sales_price_jpy == 3540000
    assert line.final_price_status == FinalPriceStatus.USE_STANDARD_CANDIDATE
