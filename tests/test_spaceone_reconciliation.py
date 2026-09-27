from datetime import datetime

from agents.master_reconciliation import get_manufacturer_price_by_sku, reconcile_spaceone_master
from agents.quote_control_agent import import_price_book
from models import MatchStatus, SpaceOneValues
from parsers.spaceone_master_parser import classify_spaceone_sku, parse_cell_reference, parse_spaceone_master
from tests.price_book_fixtures import manufacturer_books_for_reconciliation, spaceone_master_book


def _by_sku(items):
    return {item.normalized_sku or item.spaceone_sku: item for item in items}


def _result_by_sku(report):
    return {item.normalized_sku or item.spaceone_sku: item for item in report.results}


def _load_books():
    dt40_file, pt30_file = manufacturer_books_for_reconciliation()
    dt40 = import_price_book(dt40_file, source_price_book="DT40")
    pt30 = import_price_book(pt30_file, source_price_book="PT30")
    spaceone = parse_spaceone_master(spaceone_master_book(), source_name="SO_MASTER")
    return dt40, pt30, spaceone


def test_spaceone_master_can_be_read_and_keeps_cell_reference():
    spaceone = parse_spaceone_master(spaceone_master_book(), source_name="SO_MASTER")
    items = _by_sku(spaceone.items)
    base = items["9680-BASE"]

    assert spaceone.items
    assert base.spaceone_sku == "9680-BASE"
    assert isinstance(base.normalized_sku, str)
    assert base.old_reference is not None
    assert base.old_reference.workbook == "DT40"
    assert base.old_reference.sheet == "PHOTON"
    assert base.old_reference.cell == "D10"
    assert "IMPORTRANGE" in (base.old_reference.formula or "")


def test_sku_stays_string_and_datetime_is_not_restored():
    spaceone = parse_spaceone_master(spaceone_master_book())
    items = {item.spaceone_item_id: item for item in spaceone.items}
    pack = next(item for item in spaceone.items if item.normalized_sku == "8459")
    broken = next(item for item in spaceone.items if item.part_number_invalid)

    assert pack.normalized_sku == "8459"
    assert isinstance(pack.normalized_sku, str)
    assert pack.sku_cell_type in {"float", "int"}
    assert broken.sku_cell_type == "datetime"
    assert broken.normalized_sku is None
    assert "9757-2" not in (broken.spaceone_sku or "")
    assert "9757-2" not in (broken.sku_raw or "")
    sku, invalid, cell_type, raw = classify_spaceone_sku(datetime(9757, 2, 1))
    assert sku is None
    assert invalid == "PART_NUMBER_INVALID"
    assert cell_type == "datetime"
    assert raw


def test_reconciliation_statuses_and_old_new_prices():
    dt40, pt30, spaceone = _load_books()
    report = reconcile_spaceone_master(spaceone.items, dt40, pt30)
    by_sku = _result_by_sku(report)

    assert by_sku["9680-BASE"].primary_status == MatchStatus.EXACT_MATCH
    assert by_sku["11490"].primary_status == MatchStatus.PRICE_MISMATCH
    assert by_sku["11490"].old_msrp == 77000
    assert by_sku["11490"].new_msrp == 1945
    assert by_sku["11490"].old_dealer_price == 68701.1
    assert by_sku["11490"].new_dealer_price == 1361.5
    assert by_sku["7851-PHOTON"].primary_status == MatchStatus.PRICE_MISSING
    assert by_sku["MISSING-SKU"].primary_status == MatchStatus.SKU_NOT_FOUND
    assert by_sku["7511-SC-BASE"].primary_status == MatchStatus.OBSOLETE_ONLY
    assert by_sku["CONFLICT-1"].primary_status == MatchStatus.SOURCE_PRICE_CONFLICT
    assert by_sku["CONFLICT-1"].recommended_changes == []
    assert any(item.primary_status == MatchStatus.PART_NUMBER_INVALID for item in report.results)
    assert report.summary.multiple_spaceone_rows == 2
    assert {item.primary_status for item in report.results if item.normalized_sku == "5608"} == {MatchStatus.EXACT_MATCH}
    assert all(
        issue.code == "MULTIPLE_SPACEONE_ROWS"
        for item in report.results
        if item.normalized_sku == "5608"
        for issue in item.issues
        if issue.code == "MULTIPLE_SPACEONE_ROWS"
    )


def test_spaceone_unique_fields_are_not_changed():
    dt40, pt30, spaceone = _load_books()
    before = spaceone.items[0].values.model_copy(deep=True)
    report = reconcile_spaceone_master(spaceone.items, dt40, pt30)
    after = spaceone.items[0].values
    matched = next(item for item in report.results if item.normalized_sku == "9680-BASE")

    assert after.name_ja == before.name_ja == "PHOTON 基本構成"
    assert after.sales_price == before.sales_price == 3540000
    assert matched.current_spaceone_values.name_ja == "PHOTON 基本構成"
    assert matched.current_spaceone_values.sales_price == 3540000
    assert SpaceOneValues(
        name_ja=before.name_ja,
        description=before.description,
        manufacturer_msrp_usd=before.manufacturer_msrp_usd,
        manufacturer_dealer_price_usd=before.manufacturer_dealer_price_usd,
        sales_price=before.sales_price,
        notes=before.notes,
        category=before.category,
    ) == after


def test_manufacturer_price_is_looked_up_by_sku_not_cell():
    dt40, pt30, spaceone = _load_books()
    candidate = get_manufacturer_price_by_sku("11490", list(dt40.candidates) + list(pt30.candidates))
    missing = get_manufacturer_price_by_sku("PHOTON!D40", list(dt40.candidates))
    unknown = get_manufacturer_price_by_sku("9680-EXPEET", list(dt40.candidates))
    report = reconcile_spaceone_master(spaceone.items, dt40, pt30)
    wheels = next(item for item in report.results if item.normalized_sku == "11490")

    assert candidate is not None
    assert candidate.msrp_usd == 1945
    assert missing is None
    assert unknown is None
    assert wheels.old_reference is not None
    assert wheels.old_reference.cell == "D40"
    assert wheels.new_msrp == 1945
    assert wheels.old_msrp != wheels.new_msrp


def test_shipping_row_is_not_treated_as_manufacturer_sku():
    dt40, pt30, spaceone = _load_books()
    report = reconcile_spaceone_master(spaceone.items, dt40, pt30)
    shipping = next(item for item in report.results if item.current_spaceone_values.name_ja and "輸送費" in item.current_spaceone_values.name_ja)

    assert shipping.primary_status == MatchStatus.MANUAL_REVIEW_REQUIRED
    assert any(issue.code == "LEGACY_SHIPPING_VALUE" for issue in shipping.issues)
    assert shipping.manufacturer_candidate is None
    assert shipping.recommended_changes == []


def test_reconciliation_does_not_apply():
    dt40, pt30, spaceone = _load_books()
    before = [item.model_dump() for item in spaceone.items]
    reconcile_spaceone_master(spaceone.items, dt40, pt30)
    after = [item.model_dump() for item in spaceone.items]
    assert before == after


def test_cell_reference_parser_reads_importrange():
    ref = parse_cell_reference(
        '=IFERROR(__xludf.DUMMYFUNCTION("IMPORTRANGE(""https://docs.google.com/spreadsheets/d/'
        '1VoWnPU8KRnRM7ddNGQJIEN2I_zAborsBfBmOxsNMXl4/edit"", ""A-200!D54"")"),77000)'
    )
    assert ref.workbook == "PT30"
    assert ref.sheet == "A-200"
    assert ref.cell == "D54"
