import hashlib
import shutil
import sqlite3
from pathlib import Path, PurePosixPath

import pytest

from agents.price_master import (
    get_active_master,
    import_price_master,
    resolve_stored_path,
    safe_display_filename,
)
from models import PriceMasterImportStatus, PriceMasterSourceType, PriceMasterType
from repositories.sqlite import default_sqlite_path
from repositories.sqlite_price_master_repository import SqlitePriceMasterRepository
from tests.price_book_fixtures import (
    missing_columns_price_book,
    official_dt40_style_book,
    official_ihi_sku_snapshot_book,
    official_pt30_style_book,
    pricing_policy_master_book,
    quote_calc_formula_book,
    valid_price_book,
)

VALID_UPLOADS = {
    PriceMasterType.DT40: official_ihi_sku_snapshot_book,
    PriceMasterType.PT30: official_pt30_style_book,
    PriceMasterType.SO_MASTER: pricing_policy_master_book,
    PriceMasterType.QUOTE_CALC: quote_calc_formula_book,
}


def _upload(master_type, factory, name="upload.xlsx", repo=None):
    return import_price_master(master_type, name, factory().getvalue(), repository=repo)


@pytest.mark.parametrize("master_type", list(VALID_UPLOADS))
def test_valid_upload_is_stored_and_activated(master_type):
    outcome = _upload(master_type, VALID_UPLOADS[master_type], name=f"{master_type.value} 2026年10月.xlsx")

    assert outcome.status == PriceMasterImportStatus.ACTIVATED
    record = outcome.record
    assert record.active is True
    assert record.source_type == PriceMasterSourceType.FILE_UPLOAD
    assert record.original_filename == f"{master_type.value} 2026年10月.xlsx"
    assert record.stored_path == f"{master_type.value}/{record.import_id}.xlsx"
    assert len(record.sha256) == 64
    assert record.validation_summary
    active = get_active_master(master_type)
    assert active.record.import_id == record.import_id
    assert active.path.is_file()
    assert active.path.parent == default_sqlite_path().parent / "price_masters" / master_type.value


def test_validation_summaries_come_from_the_existing_parsers():
    assert _upload(PriceMasterType.DT40, official_ihi_sku_snapshot_book).record.validation_summary["sku_count"] > 0
    assert _upload(PriceMasterType.SO_MASTER, pricing_policy_master_book).record.validation_summary["policy_count"] > 0
    calc = _upload(PriceMasterType.QUOTE_CALC, quote_calc_formula_book).record.validation_summary
    assert calc["import_tax_rate"] == 0.1


@pytest.mark.parametrize(
    "master_type, name, data",
    [
        (PriceMasterType.DT40, "dt40.xlsx", missing_columns_price_book().getvalue()),
        (PriceMasterType.DT40, "dt40.xlsx", b"PK\x03\x04 not really a workbook"),
        (PriceMasterType.DT40, "dt40.csv", b"sku,price\n1,2\n"),
        (PriceMasterType.DT40, "dt40.xlsx", b""),
        (PriceMasterType.SO_MASTER, "so.xlsx", valid_price_book().getvalue()),
        (PriceMasterType.QUOTE_CALC, "calc.xlsx", valid_price_book().getvalue()),
        (PriceMasterType.PT30, "pt30.xlsx", pricing_policy_master_book().getvalue()),
    ],
)
def test_invalid_upload_keeps_the_active_master(master_type, name, data):
    good = _upload(master_type, VALID_UPLOADS[master_type]).record

    outcome = import_price_master(master_type, name, data)

    assert outcome.status == PriceMasterImportStatus.REJECTED
    assert outcome.record is None
    assert get_active_master(master_type).record.import_id == good.import_id
    repo = SqlitePriceMasterRepository()
    assert [item.import_id for item in repo.list_imports(master_type)] == [good.import_id]
    assert not any((repo.storage_root / ".staging").glob("*"))


def test_invalid_first_upload_leaves_master_unset():
    outcome = import_price_master(PriceMasterType.DT40, "x.xlsx", missing_columns_price_book().getvalue())

    assert outcome.status == PriceMasterImportStatus.REJECTED
    assert get_active_master(PriceMasterType.DT40) is None


def test_new_version_deactivates_old_and_keeps_its_file():
    first = _upload(PriceMasterType.DT40, official_ihi_sku_snapshot_book, name="dt40-sep.xlsx").record
    second = _upload(PriceMasterType.DT40, official_dt40_style_book, name="dt40-oct.xlsx").record

    repo = SqlitePriceMasterRepository()
    records = {item.import_id: item for item in repo.list_imports(PriceMasterType.DT40)}
    assert records[second.import_id].active is True
    assert records[first.import_id].active is False
    assert records[first.import_id].deactivated_at is not None
    assert resolve_stored_path(repo, records[first.import_id]).is_file()
    assert get_active_master(PriceMasterType.DT40).record.import_id == second.import_id
    assert sum(1 for item in records.values() if item.active) == 1


def _write_once(tmp_path, factory):
    # The workbook is generated exactly once; every later upload reads these same bytes from disk.
    original = tmp_path / "original.xlsx"
    original.write_bytes(factory().getvalue())
    copy = tmp_path / "copied" / "別名でコピー.xlsx"
    copy.parent.mkdir()
    shutil.copyfile(original, copy)
    assert original.read_bytes() == copy.read_bytes()
    return original, copy


def test_identical_bytes_uploaded_twice_are_one_import(tmp_path):
    original, copy = _write_once(tmp_path, official_ihi_sku_snapshot_book)
    expected_sha = hashlib.sha256(original.read_bytes()).hexdigest()

    first = import_price_master(PriceMasterType.DT40, original.name, original.read_bytes())
    same_path = import_price_master(PriceMasterType.DT40, original.name, original.read_bytes())
    other_path = import_price_master(PriceMasterType.DT40, copy.name, copy.read_bytes())

    assert first.status == PriceMasterImportStatus.ACTIVATED
    assert first.record.sha256 == expected_sha
    for outcome in (same_path, other_path):
        assert outcome.status == PriceMasterImportStatus.ALREADY_ACTIVE
        assert outcome.record.import_id == first.record.import_id
        assert outcome.record.sha256 == expected_sha
    repo = SqlitePriceMasterRepository()
    assert len(repo.list_imports(PriceMasterType.DT40)) == 1
    assert len(list((repo.storage_root / "DT40").glob("*.xlsx"))) == 1


def test_identical_bytes_of_a_previous_version_are_revalidated_and_reactivated_without_a_copy(tmp_path, monkeypatch):
    from agents import price_master

    original, copy = _write_once(tmp_path, official_ihi_sku_snapshot_book)
    first = import_price_master(PriceMasterType.DT40, original.name, original.read_bytes()).record
    second = _upload(PriceMasterType.DT40, official_dt40_style_book).record
    assert get_active_master(PriceMasterType.DT40).record.import_id == second.import_id

    validated = []
    real_validate = price_master.validate_price_master
    monkeypatch.setattr(
        price_master,
        "validate_price_master",
        lambda master_type, path: validated.append(Path(path)) or real_validate(master_type, path),
    )
    back = import_price_master(PriceMasterType.DT40, copy.name, copy.read_bytes())

    repo = SqlitePriceMasterRepository()
    assert back.status == PriceMasterImportStatus.REACTIVATED
    assert back.record.import_id == first.import_id
    assert validated == [resolve_stored_path(repo, first)]
    assert get_active_master(PriceMasterType.DT40).record.import_id == first.import_id
    assert repo.get(second.import_id).active is False
    assert len(repo.list_imports(PriceMasterType.DT40)) == 2
    assert len(list((repo.storage_root / "DT40").glob("*.xlsx"))) == 2


def test_same_file_for_another_master_type_never_reuses_the_other_import():
    data = official_ihi_sku_snapshot_book().getvalue()
    dt40 = import_price_master(PriceMasterType.DT40, "dt40.xlsx", data).record

    # Same bytes in the PT30 slot: dedupe is keyed by (master_type, sha256), so the DT40 import is not
    # reused, and the workbook is validated as PT30 — which it is not.
    outcome = import_price_master(PriceMasterType.PT30, "x.xlsx", data)

    assert outcome.status == PriceMasterImportStatus.REJECTED
    assert outcome.record is None
    repo = SqlitePriceMasterRepository()
    assert repo.find_by_sha(PriceMasterType.PT30, dt40.sha256) is None
    assert repo.find_by_sha(PriceMasterType.DT40, dt40.sha256).import_id == dt40.import_id
    assert get_active_master(PriceMasterType.PT30) is None
    assert get_active_master(PriceMasterType.DT40).record.import_id == dt40.import_id


@pytest.mark.parametrize(
    "name",
    ["../../etc/evil.xlsx", "..\\..\\Windows\\evil.xlsx", "/Users/someone/Downloads/DT40.xlsx", "C:\\Users\\x\\DT40.xlsx"],
)
def test_uploaded_filename_never_controls_the_storage_path(name):
    outcome = import_price_master(PriceMasterType.DT40, name, official_ihi_sku_snapshot_book().getvalue())

    record = outcome.record
    assert outcome.status == PriceMasterImportStatus.ACTIVATED
    assert record.stored_path == f"DT40/{record.import_id}.xlsx"
    assert "/" not in record.original_filename and "\\" not in record.original_filename
    root = SqlitePriceMasterRepository().storage_root.resolve()
    assert root in get_active_master(PriceMasterType.DT40).path.resolve().parents


def test_safe_display_filename_strips_directories():
    assert safe_display_filename("../../a/b/DT40.xlsx") == "DT40.xlsx"
    assert safe_display_filename("C:\\Users\\x\\PT30 価格表.xlsx") == "PT30 価格表.xlsx"
    assert safe_display_filename(None) == "upload.xlsx"


def test_stored_path_is_relative_and_resolves_on_any_os():
    record = _upload(PriceMasterType.DT40, official_ihi_sku_snapshot_book).record
    repo = SqlitePriceMasterRepository()

    assert not PurePosixPath(record.stored_path).is_absolute()
    assert "\\" not in record.stored_path
    assert resolve_stored_path(repo, record) == repo.storage_root / "DT40" / f"{record.import_id}.xlsx"
    tampered = record.model_copy(update={"stored_path": "../outside.xlsx"})
    with pytest.raises(ValueError):
        resolve_stored_path(repo, tampered)


def test_registry_table_is_added_to_an_existing_database_without_touching_other_tables(tmp_path):
    from repositories.sqlite_quote_repository import SqliteQuoteRepository
    from tests.test_quote_approval import _ready_photon

    db = tmp_path / "existing.sqlite3"
    quotes = SqliteQuoteRepository(db)
    draft = _ready_photon()
    quotes.save_draft(draft)
    before = sqlite3.connect(db).execute("SELECT payload_json FROM quote_drafts").fetchall()

    SqlitePriceMasterRepository(db)
    SqlitePriceMasterRepository(db)

    connection = sqlite3.connect(db)
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"quote_drafts", "approved_quote_snapshots", "price_master_imports"} <= tables
    assert connection.execute("SELECT payload_json FROM quote_drafts").fetchall() == before
    assert SqliteQuoteRepository(db).get_draft(draft.quote_draft_id).draft.total_jpy == draft.total_jpy
