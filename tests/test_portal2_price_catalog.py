from types import SimpleNamespace

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
