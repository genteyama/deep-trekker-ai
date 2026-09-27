from agents.quote_control_agent import SkuMasterStore, diff_price_books, import_price_book
from models import PriceBookDiffType
from parsers.price_book_parser import (
    CODE_DEALER_GT_MSRP,
    CODE_DUPLICATE_CONTEXT_DIFFERENT,
    CODE_DUPLICATE_SAME,
    CODE_EMPTY_SKU,
    CODE_INVALID_DEALER_PRICE,
    CODE_INVALID_MSRP,
    CODE_MISSING_COLUMNS,
    CODE_MSRP_EQUALS_DEALER,
    CODE_NO_DEALER_DISCOUNT,
    CODE_PART_NUMBER_INVALID,
    CODE_PRICE_CONFLICT,
    calculate_dealer_rate,
)
from tests.price_book_fixtures import (
    FIXTURE_DIR,
    datetime_sku_book,
    duplicate_same_price_book,
    missing_columns_price_book,
    official_dt40_style_book,
    official_pt30_style_book,
    previous_master_book,
    price_conflict_book,
    shifted_columns_price_book,
    valid_price_book,
    validation_price_book,
    write_fixture_files,
)


def _by_sku(result):
    return {item.sku: item for item in result.items}


def _codes(issues):
    return [issue.code for issue in issues]


def test_excel_file_can_be_read_from_path(tmp_path):
    paths = write_fixture_files(tmp_path)
    result = import_price_book(
        paths["valid_dt40.xlsx"],
        source_price_book="DT40",
        version="2026-09",
    )

    committed = FIXTURE_DIR / "valid_dt40.xlsx"
    if committed.exists():
        committed_result = import_price_book(committed, source_price_book="DT40")
        assert "9701-MAG-4K" in {item.sku for item in committed_result.items}

    assert result.source_price_book == "DT40"
    assert result.version == "2026-09"
    assert {item.sku for item in result.items} == {
        "9701-MAG-4K",
        "9735",
        "7851-PHOTON",
        "9680-BASE",
        "5608",
        "8459",
    }


def test_sku_is_primary_key_and_not_cell_position():
    left = import_price_book(valid_price_book(), source_price_book="DT40")
    right = import_price_book(shifted_columns_price_book(), source_price_book="DT40")
    left_mag = {item.sku: (item.description, item.msrp_usd, item.dealer_price_usd) for item in left.items if item.source_sheet == "MAG"}
    right_mag = {item.sku: (item.description, item.msrp_usd, item.dealer_price_usd) for item in right.items}

    assert left_mag["9701-MAG-4K"] == right_mag["9701-MAG-4K"]
    assert left_mag["9735"] == right_mag["9735"]
    assert "B27" not in left_mag
    assert all(item.sku not in {"B27", "D42"} for item in left.items)


def test_multiple_sheets_keep_source_sheet_and_unknown_family():
    result = import_price_book(valid_price_book(), source_price_book="DT40")
    items = _by_sku(result)

    assert items["9701-MAG-4K"].source_sheet == "MAG"
    assert items["9701-MAG-4K"].product_family == "Utility Crawler"
    assert items["7851-PHOTON"].source_sheet == "PHOTON"
    assert items["7851-PHOTON"].product_family == "ROV"
    assert items["9680-BASE"].source_sheet == "PipeTrekker"
    assert items["9680-BASE"].product_family == "PipeTrekker"
    assert items["8459"].source_sheet == "Bundle Pack"
    assert items["8459"].product_family is None
    assert items["8459"].model is None
    assert len(result.sheets) == 5


def test_empty_and_duplicate_sku_are_detected():
    result = import_price_book(validation_price_book(), source_price_book="DT40")

    assert CODE_EMPTY_SKU in _codes(result.errors)
    assert CODE_DUPLICATE_CONTEXT_DIFFERENT in _codes(result.infos)
    assert CODE_DUPLICATE_CONTEXT_DIFFERENT not in _codes(result.errors)
    assert [item.sku for item in result.items].count("9701-MAG-4K") == 2
    assert len([item for item in result.occurrences if item.sku == "9701-MAG-4K"]) == 2


def test_numeric_errors_are_detected():
    result = import_price_book(validation_price_book(), source_price_book="DT40")
    codes = _codes(result.errors)

    assert CODE_INVALID_MSRP in codes
    assert CODE_INVALID_DEALER_PRICE in codes


def test_missing_required_columns_are_errors():
    result = import_price_book(missing_columns_price_book(), source_price_book="DT40")

    assert result.items == []
    assert CODE_MISSING_COLUMNS in _codes(result.errors)


def test_dealer_price_equal_to_msrp_is_allowed_and_keeps_no_dealer_discount():
    result = import_price_book(valid_price_book(), source_price_book="DT40")
    cygnus = _by_sku(result)["5608"]

    assert cygnus.msrp_usd == cygnus.dealer_price_usd
    assert cygnus.notes == "NO DEALER DISCOUNT"
    assert cygnus.dealer_equals_msrp is True
    assert cygnus.no_dealer_discount_note is True
    assert CODE_MSRP_EQUALS_DEALER in _codes(result.infos)
    assert CODE_NO_DEALER_DISCOUNT in _codes(result.infos)
    assert CODE_MSRP_EQUALS_DEALER not in _codes(result.errors)


def test_dealer_rate_is_calculated_only_from_listed_prices():
    result = import_price_book(valid_price_book(), source_price_book="DT40")
    items = _by_sku(result)

    assert items["9701-MAG-4K"].dealer_rate == 0.6
    assert items["9680-BASE"].dealer_rate == 0.7
    assert items["5608"].dealer_rate == 1.0
    assert items["8459"].dealer_price_usd == 90
    assert items["8459"].dealer_equals_msrp is False
    assert items["8459"].no_dealer_discount_note is False
    assert items["8459"].dealer_price_usd != items["8459"].msrp_usd * 0.6
    assert items["8459"].dealer_price_usd != items["8459"].msrp_usd * 0.7
    assert calculate_dealer_rate(None, 100) is None
    assert calculate_dealer_rate(0, 100) is None


def test_dealer_price_greater_than_msrp_is_warning_not_generated_price():
    result = import_price_book(validation_price_book(), source_price_book="DT40")
    item = _by_sku(result)["HIGH-DEALER"]

    assert item.dealer_price_usd == 150
    assert item.msrp_usd == 100
    assert CODE_DEALER_GT_MSRP in _codes(result.warnings)


def test_diff_detects_new_price_description_notes_removed_and_unchanged():
    current = import_price_book(previous_master_book(), source_price_book="DT40")
    incoming = import_price_book(valid_price_book(), source_price_book="DT40")
    diff = diff_price_books(current.items, incoming.items)
    by_sku = {item.sku: item for item in diff.items}

    assert PriceBookDiffType.NEW_SKU in by_sku["9680-BASE"].change_types
    assert PriceBookDiffType.PRICE_CHANGED in by_sku["9701-MAG-4K"].change_types
    assert by_sku["9701-MAG-4K"].old_msrp == 24000
    assert by_sku["9701-MAG-4K"].new_msrp == 25000
    assert by_sku["9701-MAG-4K"].old_dealer_price == 14400
    assert by_sku["9701-MAG-4K"].new_dealer_price == 15000
    assert PriceBookDiffType.DESCRIPTION_CHANGED in by_sku["9701-MAG-4K"].change_types
    assert PriceBookDiffType.NOTES_CHANGED in by_sku["9701-MAG-4K"].change_types
    assert PriceBookDiffType.UNCHANGED in by_sku["7851-PHOTON"].change_types
    assert PriceBookDiffType.UNCHANGED in by_sku["9735"].change_types
    assert PriceBookDiffType.REMOVED_SKU in by_sku["RETIRED-1"].change_types
    assert by_sku["RETIRED-1"].change_types == [PriceBookDiffType.REMOVED_SKU]


def test_removed_sku_is_candidate_only_and_official_master_is_not_updated():
    store = SkuMasterStore()
    before = store.snapshot()
    incoming = import_price_book(
        valid_price_book(),
        source_price_book="DT40",
        official_master=store,
    )
    current = import_price_book(previous_master_book(), source_price_book="DT40")
    diff = diff_price_books(current.items, incoming.items)
    removed = [item for item in diff.items if PriceBookDiffType.REMOVED_SKU in item.change_types]

    assert store.snapshot() == before
    assert store.items == []
    assert incoming.items
    assert removed
    assert all(item.change_types != ["DELETED"] for item in removed)


def test_official_dt40_headers_and_config_skip():
    result = import_price_book(official_dt40_style_book(), source_price_book="DT40")
    items = _by_sku(result)
    sheets = {sheet.sheet_name: sheet for sheet in result.sheets}

    assert sheets["CONFIG"].skipped is True
    assert sheets["CONFIG"].item_count == 0
    assert items["9680-BASE"].dealer_price_usd == 10434.6
    assert items["9680-BASE"].msrp_usd == 17391
    assert items["2535"].dealer_price_usd == 105
    assert items["2535"].dealer_price_usd != items["2535"].msrp_usd * 0.6
    assert items["2535"].notes == "*** NO DEALER DISCOUNT - Requires Bridge Box"
    assert items["2535"].no_dealer_discount_note is True
    assert items["2535"].dealer_equals_msrp is True
    assert items["9757-2"].sku == "9757-2"
    assert items["00123"].sku == "00123"
    assert isinstance(items["00123"].sku, str)
    assert items["7511-SC-BASE"].source_status.value == "OBSOLETE"
    assert items["7511-SC-BASE"].source_sheet == "REVOLUTION-OBSOLETE"
    candidate = next(item for item in result.candidates if item.sku == "7511-SC-BASE")
    assert candidate.source_status.value == "OBSOLETE"
    assert any(item.source_sheet == "PHOTON" for item in result.occurrences if item.sku == "2535")
    assert any(item.source_sheet == "PIVOT" for item in result.occurrences if item.sku == "2535")


def test_official_pt30_headers_are_read_as_dealer_price():
    result = import_price_book(official_pt30_style_book(), source_price_book="PT30")
    items = _by_sku(result)

    assert items["11000S"].dealer_price_usd == 33250
    assert items["11000S"].msrp_usd == 47500
    assert items["10800S"].dealer_price_usd == 36750
    assert items["11000S"].dealer_rate == 0.7
    config = next(sheet for sheet in result.sheets if sheet.sheet_name == "CONFIG")
    assert config.skipped is True


def test_duplicate_same_and_price_conflict_are_classified():
    same = import_price_book(duplicate_same_price_book(), source_price_book="DT40")
    conflict = import_price_book(price_conflict_book(), source_price_book="MIXED")
    same_candidate = next(item for item in same.candidates if item.sku == "2535")
    conflict_candidate = next(item for item in conflict.candidates if item.sku == "11490")

    assert CODE_DUPLICATE_SAME in _codes(same.infos)
    assert same_candidate.duplicate_class.value == "DUPLICATE_SAME"
    assert same_candidate.msrp_usd == 105
    assert CODE_PRICE_CONFLICT in _codes(conflict.warnings)
    assert CODE_PRICE_CONFLICT not in _codes(conflict.errors)
    assert conflict_candidate.duplicate_class.value == "PRICE_CONFLICT"
    assert conflict_candidate.msrp_usd is None
    assert conflict_candidate.dealer_price_usd is None
    assert len(conflict_candidate.occurrences) == 2


def test_datetime_sku_is_not_restored():
    result = import_price_book(datetime_sku_book(), source_price_book="DT40")
    skus = {item.sku for item in result.items}

    assert "2500-1" in skus
    assert "9757-2" not in skus
    assert "9757-02" not in skus
    assert CODE_PART_NUMBER_INVALID in _codes(result.warnings)
    assert all(isinstance(item.sku, str) for item in result.items)


def test_parser_uses_cached_values_by_default():
    result = import_price_book(official_dt40_style_book(), source_price_book="DT40")
    assert _by_sku(result)["9680-BASE"].msrp_usd == 17391
