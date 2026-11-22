from types import SimpleNamespace

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
    SHIPPING_STATUS_AVAILABLE,
    SHIPPING_STATUS_REVIEW,
    SHIPPING_USD_COLUMNS,
    USD_PRICE_COLUMNS,
    build_shipping_reference_rows,
    currency_column_config,
    display_shipping_reference_rows,
    format_tokyo_datetime,
    load_shipping_reference_rows,
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
    assert set(SHIPPING_USD_COLUMNS) == {"輸送費 USD"}
    for column in USD_PRICE_COLUMNS + SHIPPING_USD_COLUMNS:
        assert _format(config, column) == "dollar"


def test_jpy_price_columns_use_yen_format():
    config = currency_column_config((), JPY_PRICE_COLUMNS + SHIPPING_JPY_COLUMNS)
    assert set(JPY_PRICE_COLUMNS) == {"SpaceOne参考売価 JPY"}
    assert set(SHIPPING_JPY_COLUMNS) == {"参考換算 JPY"}
    for column in JPY_PRICE_COLUMNS + SHIPPING_JPY_COLUMNS:
        assert _format(config, column) == "yen"


def _shipping_repo(tmp_path):
    from repositories.shipping_rule_repository import ShippingRuleRepository

    return ShippingRuleRepository(tmp_path / "shipping.sqlite3")


def _rows_by_type(rows):
    return {row["_shipping_type"]: row for row in rows}


def test_shipping_tab_shows_three_standard_types_with_basis_and_jpy(tmp_path):
    rows = load_shipping_reference_rows(160, repository=_shipping_repo(tmp_path))
    assert [row["区分"] for row in rows] == [
        "Large Box Shipping Globally",
        "Small Box Shipping Globally",
        "Pipe Trekker Shipping Globally",
    ]
    by_type = _rows_by_type(rows)
    large, small, pipe = by_type["LARGE_BOX"], by_type["SMALL_BOX"], by_type["PIPE_TREKKER"]
    assert large["輸送費 USD"] == pytest.approx(2922.15)
    assert small["輸送費 USD"] == pytest.approx(1356.00)
    assert pipe["輸送費 USD"] == pytest.approx(8828.15)
    assert large["課金単位"] == "1個口あたり"
    assert small["課金単位"] == "1個口あたり"
    assert pipe["課金単位"] == "PT本体発注時の基本一式"
    assert large["適用目安"] == "Large Box適用のROV本体・オプション等"
    assert pipe["適用目安"] == "Pipe Trekker本体注文時"
    assert large["参考換算 JPY"] == pytest.approx(2922.15 * 160)
    assert round(large["参考換算 JPY"]) == 467544
    assert all(row["基準日"] == "2026-10-23" for row in rows)
    assert all(row["状態"] == SHIPPING_STATUS_AVAILABLE for row in rows)
    assert list(display_shipping_reference_rows(rows)[0].keys()) == SHIPPING_COLUMN_ORDER
    # No insurance column: insurance is never inferred or added to shipping.
    assert not any("保険" in column for column in SHIPPING_COLUMN_ORDER)


def test_shipping_tab_currency_formats():
    config = currency_column_config(SHIPPING_USD_COLUMNS, SHIPPING_JPY_COLUMNS)
    assert _format(config, "輸送費 USD") == "dollar"
    assert _format(config, "参考換算 JPY") == "yen"


def test_shipping_tab_missing_rule_is_review_without_amounts():
    from datetime import datetime

    from models import RecordStatus, ShippingChargeBasis, ShippingRule, ShippingType

    large = SimpleNamespace(
        rule=ShippingRule(
            shipping_rule_id="x",
            shipping_type=ShippingType.LARGE_BOX,
            rate_usd=2922.15,
            charge_basis=ShippingChargeBasis.PER_PARCEL,
            effective_from=datetime(2026, 10, 23),
            status=RecordStatus.APPROVED,
        ),
        registered_at="2026-11-22T05:00:00+00:00",
        last_updated_at="2026-11-22T05:00:00+00:00",
    )
    by_type = _rows_by_type(build_shipping_reference_rows([large], 160))
    assert by_type["LARGE_BOX"]["状態"] == SHIPPING_STATUS_AVAILABLE
    for missing in ("SMALL_BOX", "PIPE_TREKKER"):
        row = by_type[missing]
        assert row["状態"] == SHIPPING_STATUS_REVIEW
        assert row["輸送費 USD"] is None
        assert row["参考換算 JPY"] is None
        assert row["基準日"] is None and row["登録日時"] is None and row["最終更新日時"] is None
    assert by_type["PIPE_TREKKER"]["課金単位"] == "PT本体発注時の基本一式"
    assert by_type["LARGE_BOX"]["登録日時"] == "2026-11-22 14:00"


def test_shipping_tab_display_is_tokyo_time():
    assert format_tokyo_datetime("2026-11-22T05:34:00+00:00") == "2026-11-22 14:34"
    assert format_tokyo_datetime("2026-11-22T20:10:00Z") == "2026-11-23 05:10"
    assert format_tokyo_datetime(None) is None


def test_shipping_tab_viewing_does_not_write_db(tmp_path, monkeypatch):
    from repositories.shipping_rule_repository import ShippingRuleRepository

    repository = _shipping_repo(tmp_path)
    before = repository._connection.total_changes

    def forbidden(*args, **kwargs):
        raise AssertionError("viewing the shipping reference must not write")

    monkeypatch.setattr(ShippingRuleRepository, "save_standard_global_rate", forbidden)
    load_shipping_reference_rows(160, repository=repository)
    load_shipping_reference_rows(150, repository=repository)
    assert repository._connection.total_changes == before
    assert len(repository.list_history()) == 3


def test_shipping_tab_does_not_depend_on_so_master(tmp_path, monkeypatch):
    import ui.price_catalog as price_catalog
    from agents import price_master

    def forbidden(*args, **kwargs):
        raise AssertionError("shipping reference must not read SO_MASTER")

    monkeypatch.setattr(price_master, "get_active_master", forbidden)
    monkeypatch.setattr(price_master, "load_active_spaceone_master", forbidden)
    rows = load_shipping_reference_rows(160, repository=_shipping_repo(tmp_path))
    assert len(rows) == 3
    for removed in ("extract_shipping_reference_rows", "SHIPPING_SHEET_BY_GROUP", "_read_shipping_sheets"):
        assert not hasattr(price_catalog, removed)


def test_price_catalog_page_shows_shipping_tab_without_so_master(monkeypatch):
    from streamlit.testing.v1 import AppTest

    import agents.price_master as price_master

    monkeypatch.setattr(price_master, "active_price_books", lambda *args, **kwargs: [_book("DT40", [])])
    monkeypatch.setattr(price_master, "load_active_spaceone_master", lambda *args, **kwargs: None)

    def page():
        from ui.price_catalog import render_price_catalog

        render_price_catalog({})

    at = AppTest.from_function(page, default_timeout=60).run()
    assert not at.exception
    assert [tab.label for tab in at.tabs] == ["主要機体・パッケージ", "全商品・オプション", "国際輸送費（参考）"]
    texts = " ".join([item.value for item in at.info] + [item.value for item in at.caption])
    assert "国際輸送費は手動登録されたDeep Trekkerの標準参考値です。" in texts
    assert "Pipe Trekkerは本体発注時の基本輸送費一式です。" in texts
