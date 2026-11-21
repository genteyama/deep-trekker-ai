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
