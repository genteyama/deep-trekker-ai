import hashlib
from types import SimpleNamespace

import openpyxl
import pytest

from ui.price_catalog import (
    REFERENCE_AVAILABLE,
    REFERENCE_REVIEW,
    STATUS_OBSOLETE,
    STATUS_OFFICIAL,
    STATUS_REVIEW,
    build_price_catalog_rows,
    build_reference_sales_map,
    filter_price_catalog_rows,
    _reference_sales_candidates,
    PRIMARY_COLUMN_ORDER,
    PRIMARY_MISSING_REASON_ABSENT,
    PRIMARY_MISSING_REASON_AMBIGUOUS,
    PRIMARY_PACKAGE_SKUS,
    build_primary_package_rows,
    display_primary_package_rows,
    filter_primary_package_rows,
    missing_primary_package_skus,
    JPY_PRICE_COLUMNS,
    SHIPPING_COLUMN_ORDER,
    SHIPPING_JPY_COLUMNS,
    SHIPPING_REASON_ABSENT,
    SHIPPING_REASON_DUPLICATE,
    SHIPPING_REASON_NO_SHEET,
    SHIPPING_STATUS_AVAILABLE,
    SHIPPING_STATUS_REVIEW,
    SHIPPING_USD_COLUMNS,
    USD_PRICE_COLUMNS,
    currency_column_config,
    display_shipping_reference_rows,
    extract_shipping_reference_rows,
    filter_shipping_reference_rows,
    load_shipping_reference_rows,
    shipping_reference_issues,
)


def _candidate(sku, description, msrp, dealer, *, sheet="MAG", status="ACTIVE", duplicate=None):
    return SimpleNamespace(
        sku=sku,
        description=description,
        msrp_usd=msrp,
        dealer_price_usd=dealer,
        source_status=SimpleNamespace(value=status),
        duplicate_class=SimpleNamespace(value=duplicate) if duplicate else None,
        occurrences=[SimpleNamespace(source_sheet=sheet)],
    )


def _book(master_type, candidates):
    return SimpleNamespace(
        record=SimpleNamespace(master_type=SimpleNamespace(value=master_type), imported_at="2026-11-21", import_id=f"{master_type}-1"),
        book=SimpleNamespace(candidates=candidates),
    )


def _sales(sku, raw, *, policy="MSRP_MULTIPLIER", status="CANDIDATE"):
    return SimpleNamespace(
        manufacturer_sku=sku,
        raw_sales_price_jpy=raw,
        pricing_policy_type=SimpleNamespace(value=policy),
        status=SimpleNamespace(value=status),
    )


def test_catalog_combines_three_active_manufacturer_books_and_marks_status():
    rows = build_price_catalog_rows(
        [
            _book("DT40", [_candidate("9701-MAG-4K", "MAG", 100, 60)]),
            _book("PT30", [_candidate("11490", "A-200 item", 200, 140, sheet="A-200")]),
            _book("SPECTRA_GOLD", [_candidate("SP-1", "Spectra", 300, None, sheet="SPECTRA")]),
        ],
        reference_sales={"9701-MAG-4K": 6400000.0},
    )
    assert {row["Price Book"] for row in rows} == {"DT40", "PT30", "SPECTRA_GOLD"}
    mag = next(row for row in rows if row["SKU"] == "9701-MAG-4K")
    assert mag["メーカー価格状態"] == STATUS_OFFICIAL
    assert mag["SpaceOne参考売価 JPY"] == 6400000.0
    assert mag["参考売価状態"] == REFERENCE_AVAILABLE
    spectra = next(row for row in rows if row["SKU"] == "SP-1")
    assert spectra["メーカー価格状態"] == STATUS_REVIEW
    assert spectra["参考売価状態"] == REFERENCE_REVIEW


def test_catalog_marks_obsolete_and_conflict_without_guessing_price():
    rows = build_price_catalog_rows(
        [
            _book("DT40", [_candidate("OLD", "old", 100, 60, status="OBSOLETE")]),
            _book("DT40", [_candidate("CONFLICT", "conflict", 100, 60, duplicate="PRICE_CONFLICT")]),
        ]
    )
    assert next(row for row in rows if row["SKU"] == "OLD")["メーカー価格状態"] == STATUS_OBSOLETE
    assert next(row for row in rows if row["SKU"] == "CONFLICT")["メーカー価格状態"] == STATUS_REVIEW


def test_catalog_filters_by_keyword_book_sheet_and_status():
    rows = build_price_catalog_rows(
        [
            _book("DT40", [_candidate("9701-MAG-4K", "MAG Utility Crawler", 100, 60, sheet="VAC & MAG")]),
            _book("PT30", [_candidate("11490", "Rear camera", 200, 140, sheet="A-200")]),
        ]
    )
    assert [row["SKU"] for row in filter_price_catalog_rows(rows, keyword="utility")] == ["9701-MAG-4K"]
    assert [row["SKU"] for row in filter_price_catalog_rows(rows, price_books=["PT30"])] == ["11490"]
    assert [row["SKU"] for row in filter_price_catalog_rows(rows, source_sheets=["A-200"])] == ["11490"]
    assert len(filter_price_catalog_rows(rows, statuses=[STATUS_OFFICIAL])) == 2


def test_reference_sales_map_rounds_msrp_policy_and_fails_closed_on_ambiguity():
    rounded = lambda value: round(value / 1000) * 1000
    thousand = lambda value: value % 1000 == 0
    mapping = build_reference_sales_map(
        [_sales("SKU-1", 6431815.5), _sales("SKU-2", 5000000, policy="FIXED_JPY")],
        round_customer_price=rounded,
        is_customer_price_unit=thousand,
    )
    assert mapping == {"SKU-1": 6432000.0, "SKU-2": 5000000.0}

    ambiguous = build_reference_sales_map(
        [_sales("SKU-X", 1000000), _sales("SKU-X", 1100000)],
        round_customer_price=rounded,
        is_customer_price_unit=thousand,
    )
    assert ambiguous["SKU-X"] is None


def test_reference_sales_candidates_runtime_imports_resolve(monkeypatch):
    import agents.price_master

    monkeypatch.setattr(agents.price_master, "load_active_spaceone_master", lambda *args, **kwargs: None)

    assert _reference_sales_candidates([], 160) == []


def _full_primary_rows(*, extra_dt40=(), extra_pt30=(), skip=()):
    dt40 = [
        _candidate(sku, f"{sku} desc", 1000, 600)
        for _group, book, sku in PRIMARY_PACKAGE_SKUS
        if book == "DT40" and sku not in skip
    ]
    pt30 = [
        _candidate(sku, f"{sku} desc", 2000, 1200, sheet="A-200")
        for _group, book, sku in PRIMARY_PACKAGE_SKUS
        if book == "PT30" and sku not in skip
    ]
    return build_price_catalog_rows(
        [
            _book("DT40", dt40 + list(extra_dt40)),
            _book("PT30", pt30 + list(extra_pt30)),
            _book("SPECTRA_GOLD", [_candidate("SP-1", "Spectra", 300, 200, sheet="SPECTRA")]),
        ],
        reference_sales={"9680-EXPERT": 4_500_000.0},
    )


def test_primary_allowlist_has_21_skus_in_business_order():
    assert len(PRIMARY_PACKAGE_SKUS) == 21
    assert len({(book, sku) for _group, book, sku in PRIMARY_PACKAGE_SKUS}) == 21
    groups = []
    for group, _book, _sku in PRIMARY_PACKAGE_SKUS:
        if group not in groups:
            groups.append(group)
    assert groups == ["DTG3", "PHOTON", "PIVOT", "REVOLUTION", "Utility Crawler", "A-150", "A-200"]
    assert {book for _group, book, _sku in PRIMARY_PACKAGE_SKUS} == {"DT40", "PT30"}


def test_primary_rows_follow_fixed_order_across_groups():
    rows = _full_primary_rows()
    primary = build_primary_package_rows(rows)
    assert [(row["製品"], row["Price Book"], row["SKU"]) for row in primary] == list(PRIMARY_PACKAGE_SKUS)
    expert = next(row for row in primary if row["SKU"] == "9680-EXPERT")
    assert expert["SpaceOne参考売価 JPY"] == 4_500_000.0
    assert expert["参考売価状態"] == REFERENCE_AVAILABLE
    base = next(row for row in primary if row["SKU"] == "9680-BASE")
    assert base["SpaceOne参考売価 JPY"] is None
    assert base["参考売価状態"] == REFERENCE_REVIEW
    assert missing_primary_package_skus(rows) == []
    displayed = display_primary_package_rows(primary)
    assert list(displayed[0].keys()) == PRIMARY_COLUMN_ORDER
    assert displayed[0]["製品"] == "DTG3"


def test_primary_rows_exclude_accessories_and_spectra():
    rows = _full_primary_rows(
        extra_dt40=[_candidate("9680-TETHER-100", "PHOTON Tether 100m", 500, 300), _candidate("9701", "Crawler body", 9, 5)],
        extra_pt30=[_candidate("11490", "A-200 accessory", 200, 140, sheet="A-200")],
    )
    primary_skus = [row["SKU"] for row in build_primary_package_rows(rows)]
    assert "9680-TETHER-100" not in primary_skus
    assert "9701" not in primary_skus
    assert "11490" not in primary_skus
    assert "SP-1" not in primary_skus
    assert len(primary_skus) == 21


def test_missing_primary_sku_is_reported_not_hidden():
    rows = _full_primary_rows(skip=("8530-NAV", "10800PRO"))
    primary_skus = [row["SKU"] for row in build_primary_package_rows(rows)]
    assert "8530-NAV" not in primary_skus
    assert "10800PRO" not in primary_skus
    assert missing_primary_package_skus(rows) == [
        {"製品": "PIVOT", "Price Book": "DT40", "SKU": "8530-NAV", "理由": PRIMARY_MISSING_REASON_ABSENT},
        {"製品": "A-200", "Price Book": "PT30", "SKU": "10800PRO", "理由": PRIMARY_MISSING_REASON_ABSENT},
    ]


def test_primary_sku_under_wrong_price_book_is_not_adopted():
    # 10800S exists only under DT40 here; the allowlist requires PT30.
    rows = _full_primary_rows(skip=("10800S",), extra_dt40=[_candidate("10800S", "Wrong book", 1, 1)])
    primary = build_primary_package_rows(rows)
    assert not any(row["SKU"] == "10800S" for row in primary)
    assert {"製品": "A-200", "Price Book": "PT30", "SKU": "10800S", "理由": PRIMARY_MISSING_REASON_ABSENT} in missing_primary_package_skus(rows)


def test_duplicate_primary_rows_are_not_auto_adopted():
    rows = _full_primary_rows(extra_dt40=[_candidate("9680-SAR", "PHOTON SAR duplicate", 99999, 1)])
    primary = build_primary_package_rows(rows)
    assert not any(row["SKU"] == "9680-SAR" for row in primary)
    assert missing_primary_package_skus(rows) == [
        {"製品": "PHOTON", "Price Book": "DT40", "SKU": "9680-SAR", "理由": PRIMARY_MISSING_REASON_AMBIGUOUS}
    ]


def test_primary_keyword_and_group_filter():
    primary = build_primary_package_rows(_full_primary_rows())

    def skus(**kwargs):
        return [row["SKU"] for row in filter_primary_package_rows(primary, **kwargs)]

    assert skus(keyword="PHOTON") == ["9680-BASE", "9680-EXPERT", "9680-SAR"]
    assert skus(keyword="nav") == ["8530-NAV", "7511-DC-NAV"]
    assert skus(keyword="A-200") == ["10800S", "10800X", "10800PRO"]
    assert skus(keyword="9680") == ["9680-BASE", "9680-EXPERT", "9680-SAR"]
    assert skus(groups=["A-150", "DTG3"]) == ["7340-BASE-4K", "11000S", "11000X"]
    assert skus(keyword="SAR", groups=["PIVOT"]) == ["8530-SAR"]
    assert len(skus()) == 21


def _format(config, column):
    return config[column]["type_config"]["format"]


def test_usd_price_columns_use_dollar_format():
    config = currency_column_config(USD_PRICE_COLUMNS + SHIPPING_USD_COLUMNS, ())
    assert set(USD_PRICE_COLUMNS) == {"MSRP USD", "Dealer USD"}
    for column in USD_PRICE_COLUMNS + SHIPPING_USD_COLUMNS:
        assert _format(config, column) == "dollar"


def test_jpy_price_columns_use_yen_format():
    config = currency_column_config((), JPY_PRICE_COLUMNS + SHIPPING_JPY_COLUMNS)
    assert set(JPY_PRICE_COLUMNS) == {"SpaceOne参考売価 JPY"}
    assert set(SHIPPING_JPY_COLUMNS) == {"参考換算 JPY"}
    for column in JPY_PRICE_COLUMNS + SHIPPING_JPY_COLUMNS:
        assert _format(config, column) == "yen"


def _so_row(sku, name, insurance, shipping):
    row = [None] * 14
    row[1], row[2], row[11], row[12] = sku, name, insurance, shipping
    return row


def _so_master(tmp_path, sheets):
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for sheet_name, rows in sheets.items():
        sheet = workbook.create_sheet(sheet_name)
        sheet.append(_so_row("Part Number", "製品名", "保険（3%）④", "送料\n（単体の目安）"))
        for row in rows:
            sheet.append(row)
            # JPY cache row under each SKU row: column B empty, must never be used.
            sheet.append([None, None, None, None, 2956470, 1773882, None, None, None, None, None, 53216, 235790, 10000])
    path = tmp_path / "so_master.xlsx"
    workbook.save(path)
    return path


def _by_sku(rows):
    return {row["SKU"]: row for row in rows}


def test_shipping_reference_extracts_insurance_and_shipping(tmp_path):
    path = _so_master(
        tmp_path,
        {
            "PHOTON": [
                _so_row("9680-BASE", "PHOTON \nBASE PACKAGE", 313.04, 1387.00),
                _so_row(" 9680-EXPERT\n", "PHOTON EXPERT PACKAGE", 478.44, 2756),
            ]
        },
    )
    rows = _by_sku(extract_shipping_reference_rows(path, 160))
    base = rows["9680-BASE"]
    assert base["製品"] == "PHOTON"
    assert base["製品名"] == "PHOTON BASE PACKAGE"
    assert base["保険 USD"] == pytest.approx(313.04)
    assert base["国際送料 USD"] == pytest.approx(1387.00)
    assert base["送料・保険合計 USD"] == pytest.approx(1700.04)
    assert base["状態"] == SHIPPING_STATUS_AVAILABLE
    # Whitespace / newlines in the SKU cell are normalized like classify_spaceone_sku().
    assert rows["9680-EXPERT"]["送料・保険合計 USD"] == pytest.approx(3234.44)


def test_shipping_reference_jpy_uses_screen_exchange_rate(tmp_path):
    path = _so_master(tmp_path, {"PHOTON": [_so_row("9680-BASE", "PHOTON BASE", 313.04, 1387.00)]})
    base = _by_sku(extract_shipping_reference_rows(path, 160))["9680-BASE"]
    assert base["参考換算 JPY"] == pytest.approx(1700.04 * 160)
    assert round(base["参考換算 JPY"]) == 272006
    other_rate = _by_sku(extract_shipping_reference_rows(path, 150))["9680-BASE"]
    assert other_rate["参考換算 JPY"] == pytest.approx(1700.04 * 150)
    assert list(display_shipping_reference_rows([base])[0].keys()) == SHIPPING_COLUMN_ORDER


def test_shipping_reference_absent_sku_is_review(tmp_path):
    path = _so_master(tmp_path, {"PHOTON": [_so_row("9680-BASE", "PHOTON BASE", 313.04, 1387.00)]})
    rows = extract_shipping_reference_rows(path, 160)
    sar = _by_sku(rows)["9680-SAR"]
    assert sar["状態"] == SHIPPING_STATUS_REVIEW
    assert sar["保険 USD"] is None and sar["国際送料 USD"] is None
    assert sar["送料・保険合計 USD"] is None and sar["参考換算 JPY"] is None
    assert {"製品": "PHOTON", "SKU": "9680-SAR", "理由": SHIPPING_REASON_ABSENT} in shipping_reference_issues(rows)


def test_shipping_reference_duplicate_sku_is_review(tmp_path):
    path = _so_master(
        tmp_path,
        {
            "PHOTON": [
                _so_row("9680-BASE", "PHOTON BASE", 313.04, 1387.00),
                _so_row("9680-BASE", "PHOTON BASE (dup)", 999.0, 9999.0),
            ]
        },
    )
    rows = extract_shipping_reference_rows(path, 160)
    base = _by_sku(rows)["9680-BASE"]
    assert base["状態"] == SHIPPING_STATUS_REVIEW
    assert base["保険 USD"] is None and base["送料・保険合計 USD"] is None
    assert {"製品": "PHOTON", "SKU": "9680-BASE", "理由": SHIPPING_REASON_DUPLICATE} in shipping_reference_issues(rows)


def test_shipping_reference_dtg3_without_sheet_does_not_break_catalog(tmp_path):
    path = _so_master(tmp_path, {"MAG": [_so_row("9701-MAG-4K", "MAG", 637.866, 4134)]})
    rows = extract_shipping_reference_rows(path, 160)
    assert len(rows) == 21
    dtg3 = _by_sku(rows)["7340-BASE-4K"]
    assert dtg3["状態"] == SHIPPING_STATUS_REVIEW
    assert dtg3["保険 USD"] is None and dtg3["国際送料 USD"] is None and dtg3["参考換算 JPY"] is None
    assert {"製品": "DTG3", "SKU": "7340-BASE-4K", "理由": SHIPPING_REASON_NO_SHEET} in shipping_reference_issues(rows)
    assert _by_sku(rows)["9701-MAG-4K"]["状態"] == SHIPPING_STATUS_AVAILABLE
    assert [row["SKU"] for row in filter_shipping_reference_rows(rows, keyword="mag")] == ["9701-MAG-4K"]
    assert [row["SKU"] for row in filter_shipping_reference_rows(rows, keyword="A-200")] == ["10800S", "10800X", "10800PRO"]


def test_shipping_reference_display_is_read_only(tmp_path):
    from models import PriceMasterType

    path = _so_master(tmp_path, {"PHOTON": [_so_row("9680-BASE", "PHOTON BASE", 313.04, 1387.00)]})
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    calls = []

    def fake_get_active(master_type):
        calls.append(master_type)
        return SimpleNamespace(record=SimpleNamespace(import_id="SO_MASTER-test"), path=path)

    rows = load_shipping_reference_rows(160, get_active=fake_get_active)
    assert calls == [PriceMasterType.SO_MASTER]
    assert _by_sku(rows)["9680-BASE"]["状態"] == SHIPPING_STATUS_AVAILABLE
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert load_shipping_reference_rows(160, get_active=lambda master_type: None) is None


def test_shipping_reference_load_does_not_write_price_master_db(tmp_path, monkeypatch):
    from agents import price_master
    from repositories.sqlite_price_master_repository import SqlitePriceMasterRepository

    path = _so_master(tmp_path, {"PHOTON": [_so_row("9680-BASE", "PHOTON BASE", 313.04, 1387.00)]})

    def forbidden(*args, **kwargs):
        raise AssertionError("price master DB must not be written while displaying shipping reference")

    for name in ("add", "activate"):
        monkeypatch.setattr(SqlitePriceMasterRepository, name, forbidden)
    monkeypatch.setattr(
        price_master,
        "get_active_master",
        lambda master_type, repository=None: SimpleNamespace(record=SimpleNamespace(import_id="SO_MASTER-test"), path=path),
    )
    rows = load_shipping_reference_rows(160)
    assert len(rows) == 21
