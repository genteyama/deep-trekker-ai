"""Manufacturer online price books are reviewed before any snapshot is activated."""

import hashlib

import pytest

from agents.online_price_master import (
    OnlinePriceReviewStatus,
    activate_reviewed_online_price,
    inspect_online_workbook,
    review_manufacturer_online_price,
)
from agents.online_price_source import OnlinePriceFetchError, OnlinePriceSource, xlsx_export_url
from agents.price_master import get_active_master, import_price_master
from agents.quote_builder import apply_exchange_rate
from models import PriceMasterImportStatus, PriceMasterSourceType, PriceMasterType, PriceMasterValidationStatus
from repositories.sqlite_price_master_repository import SqlitePriceMasterRepository
from tests.price_book_fixtures import build_workbook, missing_columns_price_book, official_pt30_style_book
from tests.test_quote_builder import _line, _mag_v1, _v1_mag_draft

SOURCE = OnlinePriceSource(
    master_type=PriceMasterType.DT40,
    source_id="DT40-manufacturer",
    url="https://docs.google.com/spreadsheets/d/abc123_sheet/edit#gid=0",
)


def _dt40(rows_by_sheet) -> bytes:
    sheets = {"CONFIG": [["Discount Code:", "E_DT-40"]]}
    for name, rows in rows_by_sheet.items():
        sheets[name] = [["Part Number", "Description", "MSRP", "DT40", "Notes:"], *rows]
    return build_workbook(sheets).getvalue()


BASE = {
    "PHOTON": [
        ["9680-BASE", "PHOTON BASE", 100, 60, None],
        ["2535", "GAME PAD", 10, 10, None],
    ]
}


def _activate_base():
    outcome = import_price_master(PriceMasterType.DT40, "dt40.xlsx", _dt40(BASE))
    assert outcome.status == PriceMasterImportStatus.ACTIVATED
    return outcome.record


def _review(data: bytes):
    return inspect_online_workbook(PriceMasterType.DT40, data, filename="DT40-online.xlsx", source=SOURCE)


def _fetcher(data: bytes):
    def fetch(source):
        assert source.fetch_url == "https://docs.google.com/spreadsheets/d/abc123_sheet/export?format=xlsx"
        from agents.online_price_source import FetchedWorkbook

        return FetchedWorkbook(data=data, filename="DT40-online.xlsx", fetch_url=source.fetch_url)

    return fetch


def test_google_sheet_url_becomes_xlsx_export_without_inventing_an_id():
    assert xlsx_export_url(SOURCE.url) == "https://docs.google.com/spreadsheets/d/abc123_sheet/export?format=xlsx"
    direct = "https://files.example.test/DT40.xlsx"
    assert xlsx_export_url(direct) == direct
    assert xlsx_export_url("") == ""


def test_online_fetch_success_does_not_activate():
    review = review_manufacturer_online_price(PriceMasterType.DT40, source=SOURCE, fetcher=_fetcher(_dt40(BASE)))

    assert review.status == OnlinePriceReviewStatus.CHANGES_PENDING
    assert review.sha256 == hashlib.sha256(_dt40(BASE)).hexdigest()
    assert review.fetched_at
    assert review.source_url.endswith("/export?format=xlsx")
    assert get_active_master(PriceMasterType.DT40) is None
    assert SqlitePriceMasterRepository().list_imports(PriceMasterType.DT40) == []


def test_online_fetch_failure_keeps_the_active_master():
    current = _activate_base()

    def fetch(source):
        raise OnlinePriceFetchError("HTTPError")

    review = review_manufacturer_online_price(PriceMasterType.DT40, source=SOURCE, fetcher=fetch)

    assert review.status == OnlinePriceReviewStatus.FETCH_FAILED
    assert review.error_count == 1
    assert get_active_master(PriceMasterType.DT40).record.import_id == current.import_id
    assert activate_reviewed_online_price(review).status == PriceMasterImportStatus.REJECTED
    assert get_active_master(PriceMasterType.DT40).record.import_id == current.import_id


def test_identical_online_workbook_is_no_change_and_creates_no_snapshot():
    current = _activate_base()

    review = _review(_dt40(BASE))

    assert review.status == OnlinePriceReviewStatus.NO_CHANGE
    assert review.changes == []
    assert review.error_count == 0
    assert len(SqlitePriceMasterRepository().list_imports(PriceMasterType.DT40)) == 1
    assert activate_reviewed_online_price(review).reason_code == "ONLINE_REVIEW_REQUIRED"
    assert get_active_master(PriceMasterType.DT40).record.import_id == current.import_id


def test_dealer_price_change_is_reported_and_not_activated_until_approval():
    current = _activate_base()
    changed = {"PHOTON": [["9680-BASE", "PHOTON BASE", 100, 70, None], ["2535", "GAME PAD", 10, 10, None]]}

    review = _review(_dt40(changed))

    assert review.status == OnlinePriceReviewStatus.CHANGES_PENDING
    assert review.dealer_change_count == 1
    assert review.msrp_change_count == 0
    assert review.price_change_count == 1
    assert review.changes[0].sku == "9680-BASE"
    assert review.changes[0].old_dealer == 60
    assert review.changes[0].new_dealer == 70
    assert get_active_master(PriceMasterType.DT40).record.import_id == current.import_id


def test_msrp_change_is_reported_separately_from_dealer_price():
    _activate_base()
    changed = {"PHOTON": [["9680-BASE", "PHOTON BASE", 120, 60, None], ["2535", "GAME PAD", 10, 10, None]]}

    review = _review(_dt40(changed))

    assert review.msrp_change_count == 1
    assert review.dealer_change_count == 0
    assert review.changes[0].old_msrp == 100
    assert review.changes[0].new_msrp == 120


def test_added_sku_is_not_a_price_change():
    _activate_base()
    changed = {
        "PHOTON": [
            ["9680-BASE", "PHOTON BASE", 100, 60, None],
            ["2535", "GAME PAD", 10, 10, None],
            ["9757-2", "BRIDGE BOX", 50, 30, None],
        ]
    }

    review = _review(_dt40(changed))

    assert review.added_count == 1
    assert review.removed_count == 0
    assert review.price_change_count == 0
    assert review.changes[0].sku == "9757-2"
    assert review.changes[0].kind == "ADDED"


def test_removed_sku_is_detected_by_normalized_sku():
    _activate_base()
    changed = {"PHOTON": [["9680-BASE", "PHOTON BASE", 100, 60, None]]}

    review = _review(_dt40(changed))

    assert review.removed_count == 1
    assert review.added_count == 0
    assert review.changes[0].sku == "2535"
    assert review.changes[0].kind == "REMOVED"


def test_row_order_change_is_not_a_price_change():
    current = _activate_base()
    reordered = {
        "PHOTON": [
            ["2535", "GAME PAD", 10, 10, None],
            ["  9680-BASE  ", "PHOTON BASE renamed", 100, 60, "note moved"],
        ]
    }

    review = _review(_dt40(reordered))

    assert hashlib.sha256(_dt40(reordered)).hexdigest() != current.sha256
    assert review.status == OnlinePriceReviewStatus.NO_CHANGE
    assert len(SqlitePriceMasterRepository().list_imports(PriceMasterType.DT40)) == 1


def test_duplicate_sku_with_conflicting_prices_is_rejected():
    current = _activate_base()
    duplicate = {
        "PHOTON": [["9680-BASE", "PHOTON BASE", 100, 60, None]],
        "PIVOT": [["9680-BASE", "PHOTON BASE", 100, 80, None]],
    }

    review = _review(_dt40(duplicate))

    assert review.status == OnlinePriceReviewStatus.DUPLICATE_SKU
    assert get_active_master(PriceMasterType.DT40).record.import_id == current.import_id
    assert len(SqlitePriceMasterRepository().list_imports(PriceMasterType.DT40)) == 1


def test_malformed_workbook_is_rejected():
    current = _activate_base()

    review = _review(b"PK\x03\x04this is not a workbook")

    assert review.status == OnlinePriceReviewStatus.PARSER_FAILED
    assert get_active_master(PriceMasterType.DT40).record.import_id == current.import_id


def test_validation_error_leaves_the_active_master_unchanged():
    current = _activate_base()

    missing = inspect_online_workbook(PriceMasterType.DT40, missing_columns_price_book().getvalue(), source=SOURCE)
    wrong_type = inspect_online_workbook(PriceMasterType.DT40, official_pt30_style_book().getvalue(), source=SOURCE)
    empty = inspect_online_workbook(PriceMasterType.DT40, b"", source=SOURCE)
    not_xlsx = inspect_online_workbook(PriceMasterType.DT40, b"not-an-xlsx", source=SOURCE)

    assert missing.status == OnlinePriceReviewStatus.MISSING_COLUMNS
    assert wrong_type.status == OnlinePriceReviewStatus.VALIDATION_FAILED
    assert wrong_type.reason_code == "MASTER_TYPE_UNCONFIRMED"
    assert empty.status == OnlinePriceReviewStatus.EMPTY
    assert not_xlsx.status == OnlinePriceReviewStatus.NOT_XLSX
    assert get_active_master(PriceMasterType.DT40).record.import_id == current.import_id
    assert len(SqlitePriceMasterRepository().list_imports(PriceMasterType.DT40)) == 1


def test_activation_keeps_the_previous_master_in_history():
    current = _activate_base()
    changed = {"PHOTON": [["9680-BASE", "PHOTON BASE", 100, 70, None], ["2535", "GAME PAD", 10, 10, None]]}
    review = _review(_dt40(changed))

    outcome = activate_reviewed_online_price(review)

    assert outcome.status == PriceMasterImportStatus.ACTIVATED
    assert outcome.record.import_id != current.import_id
    assert outcome.record.active is True
    history = SqlitePriceMasterRepository().list_imports(PriceMasterType.DT40)
    assert len(history) == 2
    previous = next(item for item in history if item.import_id == current.import_id)
    assert previous.active is False
    assert get_active_master(PriceMasterType.DT40).record.import_id == outcome.record.import_id


def test_activated_snapshot_keeps_sha_and_online_provenance():
    _activate_base()
    changed = {"PHOTON": [["9680-BASE", "PHOTON BASE", 110, 66, None], ["2535", "GAME PAD", 10, 10, None]]}
    data = _dt40(changed)
    review = _review(data)

    record = activate_reviewed_online_price(review).record

    assert record.sha256 == hashlib.sha256(data).hexdigest()
    assert record.sha256 == review.sha256
    assert record.source_type == PriceMasterSourceType.MANUFACTURER_ONLINE
    assert record.original_filename == "DT40-online.xlsx"
    assert record.validation_status == PriceMasterValidationStatus.VALID
    assert record.validation_summary["sku_count"] == 2
    source = record.validation_summary["online_source"]
    assert source["source_id"] == "DT40-manufacturer"
    assert source["source_url"] == SOURCE.fetch_url
    assert source["fetched_at"] == review.fetched_at
    assert source["filename"] == "DT40-online.xlsx"
    assert source["sha256"] == record.sha256
    assert record.import_id


def test_quote_price_regression_is_unchanged():
    draft = _v1_mag_draft(_mag_v1())
    apply_exchange_rate(draft, 165, sales_candidates=_mag_v1(165.0))

    assert _line(draft, "9701-MAG-4K").standard_sales_price_candidate_jpy == 6432000


def test_unconfigured_source_is_not_fetched(monkeypatch):
    monkeypatch.delenv("DT40_ONLINE_PRICE_SOURCE_URL", raising=False)
    called = {"count": 0}

    def fetch(source):
        called["count"] += 1
        raise AssertionError("fetch should not run")

    review = review_manufacturer_online_price(PriceMasterType.DT40, fetcher=fetch)

    assert review.status == OnlinePriceReviewStatus.NOT_CONFIGURED
    assert called["count"] == 0


def test_price_master_screen_can_check_and_shows_unconfigured_source(monkeypatch):
    monkeypatch.delenv("DT40_ONLINE_PRICE_SOURCE_URL", raising=False)
    monkeypatch.delenv("PT30_ONLINE_PRICE_SOURCE_URL", raising=False)
    from tests.test_price_master_ui import _open_quote_page, _texts

    at = _open_quote_page()
    assert any(item.label == "メーカー価格表を確認" for item in at.button)
    at.button(key="online_price_check_DT40").click().run()

    assert not at.exception
    assert "DT40（Deep Trekker 価格表）のOnline Sourceが未設定です" in _texts(at)
    assert "現在の価格マスターは変更していません" in _texts(at)
