"""PORTAL-2A.4: DT40 / PT30 / SPECTRA GOLD online sync with Excel and CSV fallbacks."""

import csv
import io

import pytest
from openpyxl import load_workbook

from agents.manufacturer_price_source import _master_type, check_source_connection, save_source_setting
from agents.online_price_master import (
    OnlinePriceReviewStatus,
    activate_reviewed_online_price,
)
from agents.online_price_source import FetchedWorkbook, OnlinePriceFetchError
from agents.price_master import (
    MANUFACTURER_MASTERS,
    ONLINE_SYNC_MASTERS,
    get_active_master,
    import_price_master,
    parse_manufacturer_price_master,
)
from agents.price_master_csv_fallback import (
    CSV_FALLBACK_SHEETS,
    CsvFallbackError,
    activate_csv_fallback,
    build_csv_fallback_review,
)
from models import PriceMasterImportStatus, PriceMasterSourceType, PriceMasterType
from repositories.actor import set_current_actor
from repositories.manufacturer_price_source_repository import (
    ManufacturerPriceSourceRepository,
    SOURCE_DT40,
    SOURCE_PT30,
    SOURCE_SPECTRA_GOLD,
)
from tests.price_book_fixtures import (
    missing_columns_price_book,
    official_dt40_style_book,
    official_pt30_style_book,
)
from tests.test_price_master_ui import _Upload, _drop_stale_widgets, _open_price_master_page, _texts, uploads  # noqa: F401
from tests.test_spectra_price_master import spectra_workbook
from ui.price_master import active_source_headline, describe_active_source

SPECTRA_URL = "https://docs.google.com/spreadsheets/d/spectra-test/edit"
DT40_URL = "https://docs.google.com/spreadsheets/d/dt40-test/edit"


@pytest.fixture(autouse=True)
def reset_actor():
    set_current_actor(None)
    yield
    set_current_actor(None)


def _fetcher(data: bytes, name: str = "book.xlsx"):
    def fetch(source):
        return FetchedWorkbook(data=data, filename=name, fetch_url=source.fetch_url)

    return fetch


def _failing_fetcher(code: str):
    def fetch(_source):
        raise OnlinePriceFetchError(code)

    return fetch


def _activate(master_type, data, name="book.xlsx"):
    outcome = import_price_master(master_type, name, data)
    assert outcome.status == PriceMasterImportStatus.ACTIVATED
    return outcome.record


def _saved_source(source_key, url, repo=None):
    repo = repo or ManufacturerPriceSourceRepository()
    current = repo.get(source_key)
    return save_source_setting(
        source_key, url, True, expected_row_version=current.row_version if current else 0, repository=repo
    )


def _changed_spectra() -> bytes:
    return spectra_workbook(first_msrp=1100, first_gold=770).getvalue()


# ---- Online -------------------------------------------------------------------------------------


def test_all_three_manufacturer_masters_are_online_sync_targets():
    assert set(ONLINE_SYNC_MASTERS) == {PriceMasterType.DT40, PriceMasterType.PT30, PriceMasterType.SPECTRA_GOLD}
    assert tuple(ONLINE_SYNC_MASTERS) == tuple(MANUFACTURER_MASTERS)


def test_spectra_source_is_active_and_maps_to_its_master_type():
    saved = _saved_source(SOURCE_SPECTRA_GOLD, SPECTRA_URL)
    assert saved.lifecycle_status == "ACTIVE"
    assert saved.parser_profile == "SPECTRA_GOLD"
    assert _master_type(SOURCE_SPECTRA_GOLD) == PriceMasterType.SPECTRA_GOLD
    assert _master_type(SOURCE_DT40) == PriceMasterType.DT40
    assert _master_type(SOURCE_PT30) == PriceMasterType.PT30


def test_legacy_future_spectra_row_reads_as_active_and_is_upgraded_on_save():
    repo = ManufacturerPriceSourceRepository()
    repo._connection.execute(
        """
        INSERT INTO manufacturer_price_sources (source_key, display_name, source_url, enabled, parser_profile,
            lifecycle_status, created_at, updated_at, updated_by, row_version)
        VALUES ('SPECTRA_GOLD', 'SPECTRA GOLD', ?, 1, 'SPECTRA_GOLD_FUTURE', 'FUTURE', 'x', 'x', NULL, 1)
        """,
        (SPECTRA_URL,),
    )
    repo._connection.commit()
    assert repo.get(SOURCE_SPECTRA_GOLD).lifecycle_status == "ACTIVE"
    _saved_source(SOURCE_SPECTRA_GOLD, SPECTRA_URL, repo)
    row = repo._connection.execute(
        "SELECT parser_profile, lifecycle_status FROM manufacturer_price_sources WHERE source_key = 'SPECTRA_GOLD'"
    ).fetchone()
    assert (row["parser_profile"], row["lifecycle_status"]) == ("SPECTRA_GOLD", "ACTIVE")


def test_spectra_connection_check_returns_review_from_spectra_tab_only():
    source = _saved_source(SOURCE_SPECTRA_GOLD, SPECTRA_URL)
    checked, review = check_source_connection(source, fetcher=_fetcher(spectra_workbook().getvalue()))

    assert review.status == OnlinePriceReviewStatus.CHANGES_PENDING
    assert checked.last_check_status == "CHANGES_PENDING"
    skus = {item.sku for item in review.changes}
    assert "SPECTRA0001" in skus
    # Hidden / other product tabs in the SPECTRA workbook are never read.
    assert "ONYX-1" not in skus and "PHOTON-1" not in skus
    assert get_active_master(PriceMasterType.SPECTRA_GOLD) is None


def test_online_no_change_and_changes_pending():
    _activate(PriceMasterType.SPECTRA_GOLD, spectra_workbook().getvalue(), "SPECTRA GOLD.xlsx")
    source = _saved_source(SOURCE_SPECTRA_GOLD, SPECTRA_URL)
    _, same = check_source_connection(source, fetcher=_fetcher(spectra_workbook().getvalue()))
    assert same.status == OnlinePriceReviewStatus.NO_CHANGE

    source = ManufacturerPriceSourceRepository().get(SOURCE_SPECTRA_GOLD)
    _, changed = check_source_connection(source, fetcher=_fetcher(_changed_spectra()))
    assert changed.status == OnlinePriceReviewStatus.CHANGES_PENDING
    assert [item.sku for item in changed.changes] == ["SPECTRA0001"]


@pytest.mark.parametrize(
    "code",
    ["FETCH_FAILED", "GOOGLE_ACCESS_DENIED", "GOOGLE_AUTH_INVALID", "GOOGLE_EXPORT_FAILED", "RESPONSE_TOO_LARGE", "NOT_XLSX"],
)
def test_online_fetch_failure_keeps_active_master(code):
    for master_type, data in (
        (PriceMasterType.DT40, official_dt40_style_book().getvalue()),
        (PriceMasterType.SPECTRA_GOLD, spectra_workbook().getvalue()),
    ):
        active = _activate(master_type, data)
        source = _saved_source(master_type.value, f"https://docs.google.com/spreadsheets/d/{master_type.value}/edit")
        checked, review = check_source_connection(source, fetcher=_failing_fetcher(code))
        assert review.status == OnlinePriceReviewStatus.FETCH_FAILED
        assert checked.last_error == code
        assert get_active_master(master_type).record.import_id == active.import_id


@pytest.mark.parametrize(
    "data",
    [b"", b"not an xlsx", b"PK\x03\x04broken", missing_columns_price_book().getvalue()],
)
def test_online_invalid_workbook_keeps_active_master(data):
    active = _activate(PriceMasterType.DT40, official_dt40_style_book().getvalue())
    source = _saved_source(SOURCE_DT40, DT40_URL)
    _, review = check_source_connection(source, fetcher=_fetcher(data))
    assert review.error_count == 1
    assert activate_reviewed_online_price(review).status == PriceMasterImportStatus.REJECTED
    assert get_active_master(PriceMasterType.DT40).record.import_id == active.import_id


def test_online_review_changes_active_only_after_human_activation():
    active = _activate(PriceMasterType.SPECTRA_GOLD, spectra_workbook().getvalue())
    source = _saved_source(SOURCE_SPECTRA_GOLD, SPECTRA_URL)
    _, review = check_source_connection(source, fetcher=_fetcher(_changed_spectra(), "SPECTRA.xlsx"))
    assert get_active_master(PriceMasterType.SPECTRA_GOLD).record.import_id == active.import_id

    outcome = activate_reviewed_online_price(review)

    assert outcome.status == PriceMasterImportStatus.ACTIVATED
    record = get_active_master(PriceMasterType.SPECTRA_GOLD).record
    assert record.import_id != active.import_id
    assert record.source_type == PriceMasterSourceType.MANUFACTURER_ONLINE
    assert record.validation_summary["online_source"]["source_key"] == SOURCE_SPECTRA_GOLD
    assert record.validation_summary["online_source"]["sha256"] == record.sha256


# ---- URL change ---------------------------------------------------------------------------------


def test_url_change_records_audit_and_does_not_touch_active_master():
    active = _activate(PriceMasterType.DT40, official_dt40_style_book().getvalue())
    repo = ManufacturerPriceSourceRepository()
    set_current_actor("first@example.com")
    first = _saved_source(SOURCE_DT40, DT40_URL, repo)
    set_current_actor("second@example.com")
    changed = save_source_setting(
        SOURCE_DT40,
        "https://docs.google.com/spreadsheets/d/dt40-moved/edit",
        True,
        expected_row_version=first.row_version,
        repository=repo,
    )

    assert changed.source_url.endswith("dt40-moved/edit")
    assert changed.row_version == first.row_version + 1
    assert changed.updated_at >= first.updated_at
    assert changed.updated_by == "second@example.com"
    assert get_active_master(PriceMasterType.DT40).record.import_id == active.import_id

    _, review = check_source_connection(changed, source_repository=repo, fetcher=_fetcher(official_dt40_style_book().getvalue()))
    assert review.status == OnlinePriceReviewStatus.NO_CHANGE
    assert review.source_url == "https://docs.google.com/spreadsheets/d/dt40-moved/export?format=xlsx"


def test_url_change_after_review_makes_review_stale():
    _activate(PriceMasterType.SPECTRA_GOLD, spectra_workbook().getvalue())
    repo = ManufacturerPriceSourceRepository()
    source = _saved_source(SOURCE_SPECTRA_GOLD, SPECTRA_URL, repo)
    checked, review = check_source_connection(source, source_repository=repo, fetcher=_fetcher(_changed_spectra()))
    save_source_setting(
        SOURCE_SPECTRA_GOLD,
        "https://docs.google.com/spreadsheets/d/other/edit",
        True,
        expected_row_version=checked.row_version,
        repository=repo,
    )
    before = get_active_master(PriceMasterType.SPECTRA_GOLD).record.import_id

    outcome = activate_reviewed_online_price(review, source_repository=repo)

    assert outcome.reason_code == "ONLINE_REVIEW_STALE"
    assert get_active_master(PriceMasterType.SPECTRA_GOLD).record.import_id == before


def test_url_change_then_check_then_review_then_activate():
    _activate(PriceMasterType.SPECTRA_GOLD, spectra_workbook().getvalue())
    repo = ManufacturerPriceSourceRepository()
    _saved_source(SOURCE_SPECTRA_GOLD, SPECTRA_URL, repo)
    moved = _saved_source(SOURCE_SPECTRA_GOLD, "https://docs.google.com/spreadsheets/d/spectra-moved/edit", repo)
    _, review = check_source_connection(moved, source_repository=repo, fetcher=_fetcher(_changed_spectra()))

    outcome = activate_reviewed_online_price(review, source_repository=repo)

    assert outcome.status == PriceMasterImportStatus.ACTIVATED
    online = get_active_master(PriceMasterType.SPECTRA_GOLD).record.validation_summary["online_source"]
    assert online["source_url"] == "https://docs.google.com/spreadsheets/d/spectra-moved/export?format=xlsx"


# ---- Excel fallback -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("master_type", "factory"),
    [
        (PriceMasterType.DT40, lambda: official_dt40_style_book().getvalue()),
        (PriceMasterType.PT30, lambda: official_pt30_style_book().getvalue()),
        (PriceMasterType.SPECTRA_GOLD, lambda: spectra_workbook().getvalue()),
    ],
)
def test_excel_fallback_upload_for_each_manufacturer_book(master_type, factory):
    set_current_actor("ops@example.com")
    record = _activate(master_type, factory(), f"{master_type.value}_2026-11-22.xlsx")
    assert record.source_type == PriceMasterSourceType.FILE_UPLOAD
    assert record.validation_summary["imported_by"] == "ops@example.com"
    assert active_source_headline(record) == f"現在使用中：Excel Upload / {master_type.value}_2026-11-22.xlsx"


def test_invalid_excel_is_rejected_and_active_master_kept():
    active = _activate(PriceMasterType.PT30, official_pt30_style_book().getvalue())
    for name, data in (("bad.xlsx", missing_columns_price_book().getvalue()), ("bad.xlsx", b"junk"), ("dt40.xlsx", official_dt40_style_book().getvalue())):
        outcome = import_price_master(PriceMasterType.PT30, name, data)
        assert outcome.status == PriceMasterImportStatus.REJECTED
    assert get_active_master(PriceMasterType.PT30).record.import_id == active.import_id


def test_excel_upload_keeps_online_source_and_online_diff_still_works():
    repo = ManufacturerPriceSourceRepository()
    source = _saved_source(SOURCE_SPECTRA_GOLD, SPECTRA_URL, repo)
    _activate(PriceMasterType.SPECTRA_GOLD, spectra_workbook().getvalue(), "SPECTRA manual.xlsx")

    kept = repo.get(SOURCE_SPECTRA_GOLD)
    assert (kept.source_url, kept.enabled, kept.row_version) == (source.source_url, True, source.row_version)

    # Online recovered: the latest online workbook is compared with the uploaded Active master.
    _, review = check_source_connection(kept, source_repository=repo, fetcher=_fetcher(_changed_spectra()))
    assert review.status == OnlinePriceReviewStatus.CHANGES_PENDING
    assert review.active_import_id == get_active_master(PriceMasterType.SPECTRA_GOLD).record.import_id


# ---- CSV fallback -------------------------------------------------------------------------------


def _sheet_csv(data: bytes, sheet_name: str, replace=None) -> bytes:
    workbook = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    try:
        rows = [["" if value is None else value for value in row] for row in workbook[sheet_name].iter_rows(values_only=True)]
    finally:
        workbook.close()
    if replace:
        rows = [[replace.get(value, value) for value in row] for row in rows]
    buffer = io.StringIO()
    csv.writer(buffer).writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _dt40_active():
    data = official_dt40_style_book().getvalue()
    return data, _activate(PriceMasterType.DT40, data, "DT40.xlsx")


def test_csv_target_sheets_are_fixed_allowlists():
    assert CSV_FALLBACK_SHEETS[PriceMasterType.DT40] == (
        "DTG3", "PHOTON", "PIVOT", "REVOLUTION-DC", "VAC & MAG", "REVOLUTION-OBSOLETE"
    )
    assert CSV_FALLBACK_SHEETS[PriceMasterType.PT30] == ("A-150", "A-200", "PT-VAN")
    assert CSV_FALLBACK_SHEETS[PriceMasterType.SPECTRA_GOLD] == ("SPECTRA",)


@pytest.mark.parametrize(
    ("price_book", "sheet", "code"),
    [
        (None, "PHOTON", "PRICE_BOOK_REQUIRED"),
        ("", "PHOTON", "PRICE_BOOK_REQUIRED"),
        (PriceMasterType.DT40, None, "SHEET_REQUIRED"),
        (PriceMasterType.DT40, "CONFIG", "SHEET_NOT_ALLOWED"),
        (PriceMasterType.DT40, "A-200", "SHEET_NOT_ALLOWED"),
        (PriceMasterType.SPECTRA_GOLD, "ONYX", "SHEET_NOT_ALLOWED"),
        ("SO_MASTER", "PHOTON", "PRICE_BOOK_NOT_ALLOWED"),
    ],
)
def test_csv_requires_explicit_price_book_and_allowed_sheet(price_book, sheet, code):
    data, _ = _dt40_active()
    with pytest.raises(CsvFallbackError) as error:
        build_csv_fallback_review(price_book, sheet, "PHOTON.csv", _sheet_csv(data, "PHOTON"))
    assert error.value.code == code


def test_csv_without_active_master_is_rejected():
    with pytest.raises(CsvFallbackError) as error:
        build_csv_fallback_review(PriceMasterType.PT30, "A-150", "A-150.csv", b"Part Number,Description,MSRP,PT30\n1,a,1,1\n")
    assert error.value.code == "ACTIVE_MASTER_REQUIRED"


@pytest.mark.parametrize("payload", [b"", b"   \n", b",,,\n,,\n"])
def test_empty_csv_is_rejected(payload):
    _dt40_active()
    with pytest.raises(CsvFallbackError) as error:
        build_csv_fallback_review(PriceMasterType.DT40, "PHOTON", "PHOTON.csv", payload)
    assert error.value.code == "CSV_EMPTY"


def test_csv_missing_required_columns_is_rejected():
    _, active = _dt40_active()
    with pytest.raises(CsvFallbackError) as error:
        build_csv_fallback_review(PriceMasterType.DT40, "PHOTON", "PHOTON.csv", b"Part Number,Description\n9680-BASE,PHOTON BASE\n")
    assert error.value.code == "CSV_MISSING_COLUMNS"
    assert get_active_master(PriceMasterType.DT40).record.import_id == active.import_id


def test_csv_replaces_only_selected_sheet_and_validates_whole_workbook():
    data, active = _dt40_active()
    payload = _sheet_csv(data, "PHOTON", replace={17391: "17500", 10434.6: "$10,500.00"})

    fallback = build_csv_fallback_review(PriceMasterType.DT40, "PHOTON", "PHOTON.csv", payload)

    review = fallback.review
    assert review.status == OnlinePriceReviewStatus.CHANGES_PENDING
    assert [(item.sku, item.kind) for item in review.changes] == [("9680-BASE", "DEALER_AND_MSRP")]
    assert review.validation_summary["sheet_count"] == 3
    assert get_active_master(PriceMasterType.DT40).record.import_id == active.import_id

    rebuilt = load_workbook(io.BytesIO(review.data), data_only=True)
    try:
        assert rebuilt.sheetnames == load_workbook(io.BytesIO(data)).sheetnames
        assert [row[1] for row in rebuilt["PIVOT"].iter_rows(min_row=2, values_only=True)] == ["2535", "8998"]
        assert rebuilt["REVOLUTION-OBSOLETE"]["B2"].value == "7511-SC-BASE"
    finally:
        rebuilt.close()


def test_unchanged_csv_is_no_change_and_cannot_be_activated():
    data, active = _dt40_active()
    fallback = build_csv_fallback_review(PriceMasterType.DT40, "PIVOT", "PIVOT.csv", _sheet_csv(data, "PIVOT"))
    assert fallback.review.status == OnlinePriceReviewStatus.NO_CHANGE
    assert activate_csv_fallback(fallback).reason_code == "CSV_REVIEW_REQUIRED"
    assert get_active_master(PriceMasterType.DT40).record.import_id == active.import_id


def test_csv_whole_workbook_validation_failure_keeps_active_master():
    data, active = _dt40_active()
    # Same SKU twice with different prices in the replaced sheet: rejected by the existing parser rules.
    payload = _sheet_csv(data, "PHOTON") + b",9757-2,BRIDGE BOX ROV,9999,5000,\n"
    fallback = build_csv_fallback_review(PriceMasterType.DT40, "PHOTON", "PHOTON.csv", payload)
    assert fallback.review.error_count == 1
    assert activate_csv_fallback(fallback).status == PriceMasterImportStatus.REJECTED
    assert get_active_master(PriceMasterType.DT40).record.import_id == active.import_id


def test_csv_activation_only_after_human_action_with_provenance():
    data, active = _dt40_active()
    set_current_actor("ops@example.com")
    fallback = build_csv_fallback_review(
        PriceMasterType.DT40, "PHOTON", "PHOTON.csv", _sheet_csv(data, "PHOTON", replace={17391: "17500"})
    )
    assert get_active_master(PriceMasterType.DT40).record.import_id == active.import_id

    outcome = activate_csv_fallback(fallback)

    assert outcome.status == PriceMasterImportStatus.ACTIVATED
    record = get_active_master(PriceMasterType.DT40).record
    assert record.source_type == PriceMasterSourceType.CSV_UPLOAD
    provenance = record.validation_summary["csv_source"]
    assert provenance["csv_filename"] == "PHOTON.csv"
    assert provenance["replaced_sheet"] == "PHOTON"
    assert provenance["base_import_id"] == active.import_id
    assert provenance["price_book"] == "DT40"
    assert provenance["approved_by"] == "ops@example.com"
    assert active_source_headline(record) == "現在使用中：CSV Upload / PHOTON.csv"
    rows = dict(describe_active_source(record))
    assert rows["置換Sheet"] == "PHOTON" and rows["Base Master"] == active.import_id
    book = parse_manufacturer_price_master(PriceMasterType.DT40, get_active_master(PriceMasterType.DT40).path)
    prices = {item.sku: item.msrp_usd for item in book.candidates}
    assert prices["9680-BASE"] == 17500
    assert prices["8998"] == 381


def test_csv_review_goes_stale_when_active_master_changes():
    data, _ = _dt40_active()
    fallback = build_csv_fallback_review(
        PriceMasterType.DT40, "PHOTON", "PHOTON.csv", _sheet_csv(data, "PHOTON", replace={17391: "17500"})
    )
    newer = official_dt40_style_book()
    workbook = load_workbook(newer)
    workbook["PIVOT"]["D3"] = 400
    buffer = io.BytesIO()
    workbook.save(buffer)
    _activate(PriceMasterType.DT40, buffer.getvalue(), "newer.xlsx")
    newer_id = get_active_master(PriceMasterType.DT40).record.import_id

    assert activate_csv_fallback(fallback).reason_code == "CSV_REVIEW_STALE"
    assert get_active_master(PriceMasterType.DT40).record.import_id == newer_id


def test_spectra_csv_replaces_spectra_tab_only():
    data = spectra_workbook().getvalue()
    _activate(PriceMasterType.SPECTRA_GOLD, data)
    fallback = build_csv_fallback_review(
        PriceMasterType.SPECTRA_GOLD, "SPECTRA", "SPECTRA.csv", _sheet_csv(data, "SPECTRA", replace={1000: "1100"})
    )
    assert fallback.review.status == OnlinePriceReviewStatus.CHANGES_PENDING
    assert {item.sku for item in fallback.review.changes} == {"SPECTRA0001"}


def test_online_provenance_headline():
    _activate(PriceMasterType.SPECTRA_GOLD, spectra_workbook().getvalue())
    source = _saved_source(SOURCE_SPECTRA_GOLD, SPECTRA_URL)
    _, review = check_source_connection(source, fetcher=_fetcher(_changed_spectra(), "SPECTRA.xlsx"))
    activate_reviewed_online_price(review)
    record = get_active_master(PriceMasterType.SPECTRA_GOLD).record
    assert active_source_headline(record) == "現在使用中：Online / SPECTRA_GOLD"
    assert dict(describe_active_source(record))["取得元URL"].endswith("spectra-test/export?format=xlsx")


# ---- Admin UI -----------------------------------------------------------------------------------


def test_admin_ui_shows_online_first_then_fallbacks_for_each_book():
    _dt40_active()
    at = _open_price_master_page()
    texts = _texts(at)
    for label in ("#### DT40", "#### PT30", "#### SPECTRA GOLD"):
        assert any(label in item.value for item in at.markdown)
    assert texts.count("オンライン価格表（通常はこちら）") == 3
    assert texts.count("Fallback（オンライン取得できない場合）") == 3
    assert "現在使用中：Excel Upload / DT40.xlsx" in texts
    assert "現在使用中：未設定" in texts
    for key in ("DT40", "PT30", "SPECTRA_GOLD"):
        assert any(item.key == f"price_master_import_{key}" for item in at.button)
    assert any(item.key == "csv_validate_DT40" for item in at.button)
    # No Active PT30 yet: CSV fallback explains that Excel is needed first.
    assert not any(item.key == "csv_validate_PT30" for item in at.button)
    assert "CSV Fallbackには現在のActive Masterが必要です。" in texts


def test_admin_ui_online_failure_shows_fallback_notice_and_keeps_active(monkeypatch):
    import agents.online_price_master as online_module

    _, active = _dt40_active()
    _saved_source(SOURCE_DT40, DT40_URL)

    def fail(_source):
        raise OnlinePriceFetchError("GOOGLE_EXPORT_FAILED")

    monkeypatch.setattr(online_module, "_default_fetcher", fail)
    at = _open_price_master_page()
    at.button(key="manufacturer_source_check_DT40").click().run()
    _drop_stale_widgets(at)

    assert not at.exception
    assert "オンライン価格表を取得できません。現在のActive Masterを継続使用しています。" in _texts(at)
    assert get_active_master(PriceMasterType.DT40).record.import_id == active.import_id


def test_admin_ui_csv_requires_price_book_selection(uploads):
    data, active = _dt40_active()
    uploads["csv_upload_DT40"] = _Upload("PHOTON.csv", _sheet_csv(data, "PHOTON", replace={17391: "17500"}))
    at = _open_price_master_page()
    at.selectbox(key="csv_sheet_DT40").select("PHOTON").run()
    at.button(key="csv_validate_DT40").click().run()

    assert "Price Bookを選択してください。" in _texts(at)
    assert not any(item.key == "csv_activate_DT40" for item in at.button)
    assert get_active_master(PriceMasterType.DT40).record.import_id == active.import_id


def test_admin_ui_csv_validate_then_explicit_activate(uploads):
    data, active = _dt40_active()
    uploads["csv_upload_DT40"] = _Upload("PHOTON.csv", _sheet_csv(data, "PHOTON", replace={17391: "17500"}))
    at = _open_price_master_page()
    at.selectbox(key="csv_price_book_DT40").select("DT40").run()
    at.selectbox(key="csv_sheet_DT40").select("PHOTON").run()
    at.button(key="csv_validate_DT40").click().run()
    _drop_stale_widgets(at)

    assert not at.exception
    assert "検証済みCSV：PHOTON.csv ／ 置換Sheet：PHOTON" in _texts(at)
    assert get_active_master(PriceMasterType.DT40).record.import_id == active.import_id

    at.button(key="csv_activate_DT40").click().run()
    _drop_stale_widgets(at)

    assert not at.exception
    record = get_active_master(PriceMasterType.DT40).record
    assert record.import_id != active.import_id
    assert record.source_type == PriceMasterSourceType.CSV_UPLOAD
    assert "現在使用中：CSV Upload / PHOTON.csv" in _texts(at)


# ---- Single "最新価格表を確認" button --------------------------------------------------------


def _edited(data: bytes, sheet: str, cell: str, value) -> bytes:
    workbook = load_workbook(io.BytesIO(data))
    workbook[sheet][cell] = value
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


BOOK_CASES = [
    (PriceMasterType.DT40, lambda: official_dt40_style_book().getvalue(), lambda data: _edited(data, "PHOTON", "D6", 17500)),
    (PriceMasterType.PT30, lambda: official_pt30_style_book().getvalue(), lambda data: _edited(data, "A-150", "D2", 99999)),
    (PriceMasterType.SPECTRA_GOLD, lambda: spectra_workbook().getvalue(), lambda _data: _changed_spectra()),
]


@pytest.mark.parametrize(("master_type", "base", "change"), BOOK_CASES)
def test_single_latest_check_button_runs_check_source_connection_and_allows_activation(
    monkeypatch, master_type, base, change
):
    import agents.online_price_master as online_module
    import ui.price_master as price_master_ui

    key = master_type.value
    base_data = base()
    active = _activate(master_type, base_data)
    _saved_source(key, f"https://docs.google.com/spreadsheets/d/{key}-latest/edit")
    monkeypatch.setattr(
        online_module,
        "_default_fetcher",
        lambda source: FetchedWorkbook(data=change(base_data), filename=f"{key}.xlsx", fetch_url=source.fetch_url),
    )
    calls = []
    original = price_master_ui.check_source_connection

    def spy(source, **kwargs):
        calls.append(source.source_key)
        return original(source, **kwargs)

    monkeypatch.setattr(price_master_ui, "check_source_connection", spy)

    at = _open_price_master_page()
    for book in ("DT40", "PT30", "SPECTRA_GOLD"):
        online_buttons = [
            item for item in at.button if item.key in {f"manufacturer_source_check_{book}", f"online_price_check_{book}"}
        ]
        assert [item.label for item in online_buttons] == ["最新価格表を確認"]
    assert not any(item.key == f"online_price_activate_{key}" for item in at.button)

    at.button(key=f"manufacturer_source_check_{key}").click().run()
    _drop_stale_widgets(at)

    assert not at.exception
    assert calls == [key]
    checked = ManufacturerPriceSourceRepository().get(key)
    assert checked.last_checked_at is not None
    assert checked.last_check_status == "CHANGES_PENDING"
    review = at.session_state[f"online_price_review_{key}"]
    assert review.status == OnlinePriceReviewStatus.CHANGES_PENDING
    assert get_active_master(master_type).record.import_id == active.import_id

    at.button(key=f"online_price_activate_{key}").click().run()
    _drop_stale_widgets(at)

    assert not at.exception
    record = get_active_master(master_type).record
    assert record.import_id != active.import_id
    assert record.source_type == PriceMasterSourceType.MANUFACTURER_ONLINE


@pytest.mark.parametrize(("master_type", "base", "_change"), BOOK_CASES)
def test_saving_url_alone_never_changes_active_master(master_type, base, _change):
    key = master_type.value
    active = _activate(master_type, base())
    _saved_source(key, f"https://docs.google.com/spreadsheets/d/{key}-old/edit")

    at = _open_price_master_page()
    at.text_input(key=f"manufacturer_source_url_{key}").set_value(f"https://docs.google.com/spreadsheets/d/{key}-new/edit")
    at.button(key=f"manufacturer_source_save_{key}").click().run()
    _drop_stale_widgets(at)

    assert not at.exception
    assert ManufacturerPriceSourceRepository().get(key).source_url.endswith(f"{key}-new/edit")
    assert ManufacturerPriceSourceRepository().get(key).last_checked_at is None
    assert get_active_master(master_type).record.import_id == active.import_id
    assert not any(item.key == f"online_price_activate_{key}" for item in at.button)
