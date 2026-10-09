import json
import sqlite3

import pytest

from agents.manufacturer_price_source import (
    ManufacturerPriceSourceValidationError,
    check_source_connection,
    list_effective_sources,
    save_source_setting,
)
from agents.online_price_master import OnlinePriceReviewStatus
from agents.online_price_source import FetchedWorkbook, resolve_registered_price_source
from agents.price_master import MANUFACTURER_MASTERS, get_active_master, import_price_master
from agents.quote_builder import apply_exchange_rate
from models import PriceMasterType
from repositories.actor import set_current_actor
from repositories.manufacturer_price_source_repository import (
    ManufacturerPriceSourceConflictError,
    ManufacturerPriceSourceRepository,
    SOURCE_DT40,
    SOURCE_PT30,
    SOURCE_SPECTRA_GOLD,
)
from tests.price_book_fixtures import official_dt40_style_book, official_pt30_style_book
from tests.test_online_price_master import _dt40
from tests.test_quote_builder import _line, _mag_v1, _v1_mag_draft


@pytest.fixture(autouse=True)
def reset_actor():
    set_current_actor(None)
    yield
    set_current_actor(None)


@pytest.mark.parametrize(
    ("source_key", "url", "lifecycle"),
    [
        (SOURCE_DT40, "https://example.test/dt40.xlsx", "ACTIVE"),
        (SOURCE_PT30, "https://example.test/pt30.xlsx", "ACTIVE"),
        (SOURCE_SPECTRA_GOLD, "https://example.test/spectra-gold.xlsx", "FUTURE"),
    ],
)
def test_source_registry_saves_all_supported_sources(source_key, url, lifecycle):
    repo = ManufacturerPriceSourceRepository()

    saved = save_source_setting(source_key, url, True, expected_row_version=0, repository=repo)

    assert saved.source_key == source_key
    assert saved.source_url == url
    assert saved.enabled is True
    assert saved.lifecycle_status == lifecycle
    assert saved.row_version == 1


def test_sqlite_fallback_is_shared_by_repository_instances(tmp_path):
    path = tmp_path / "shared.sqlite3"
    first = ManufacturerPriceSourceRepository(path)
    save_source_setting(SOURCE_DT40, "https://example.test/one.xlsx", True, expected_row_version=0, repository=first)

    second = ManufacturerPriceSourceRepository(path)

    assert second.get(SOURCE_DT40).source_url == "https://example.test/one.xlsx"


def test_postgres_adapter_uses_one_central_registry(monkeypatch, tmp_path):
    raw = sqlite3.connect(tmp_path / "central.sqlite3")
    raw.row_factory = sqlite3.Row
    raw.execute(
        """
        CREATE TABLE manufacturer_price_sources (
            id INTEGER PRIMARY KEY,
            source_key TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            source_url TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 0,
            parser_profile TEXT NOT NULL,
            lifecycle_status TEXT NOT NULL,
            last_checked_at TEXT,
            last_check_status TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by TEXT,
            row_version INTEGER NOT NULL DEFAULT 1
        )
        """
    )

    class CentralConnection:
        is_postgres = True

        def execute(self, sql, params=()):
            return raw.execute(sql, params)

        def commit(self):
            raw.commit()

        def rollback(self):
            raw.rollback()

        def close(self):
            pass

    central = CentralConnection()
    monkeypatch.setattr("repositories.manufacturer_price_source_repository.connect_sqlite", lambda path: central)
    first = ManufacturerPriceSourceRepository()
    second = ManufacturerPriceSourceRepository()

    save_source_setting(
        SOURCE_PT30,
        "https://example.test/central-pt30.xlsx",
        True,
        expected_row_version=0,
        repository=first,
    )

    assert first.is_central is True
    assert second.get(SOURCE_PT30).source_url == "https://example.test/central-pt30.xlsx"


def test_saving_url_only_keeps_active_master_and_quote_price_unchanged():
    current = import_price_master(
        PriceMasterType.DT40,
        "active.xlsx",
        official_dt40_style_book().getvalue(),
    ).record
    draft = _v1_mag_draft(_mag_v1())
    apply_exchange_rate(draft, 165, sales_candidates=_mag_v1(165.0))
    before = _line(draft, "9701-MAG-4K").standard_sales_price_candidate_jpy

    save_source_setting(
        SOURCE_DT40,
        "https://example.test/new-source.xlsx",
        True,
        expected_row_version=0,
    )

    assert get_active_master(PriceMasterType.DT40).record.import_id == current.import_id
    assert _line(draft, "9701-MAG-4K").standard_sales_price_candidate_jpy == before == 6432000


def test_update_records_actor_time_and_increments_version():
    repo = ManufacturerPriceSourceRepository()
    set_current_actor("admin@example.com")
    first = save_source_setting(
        SOURCE_DT40,
        "https://example.test/one.xlsx",
        True,
        expected_row_version=0,
        repository=repo,
    )

    second = save_source_setting(
        SOURCE_DT40,
        "https://example.test/two.xlsx",
        True,
        expected_row_version=first.row_version,
        repository=repo,
    )

    assert first.updated_at
    assert second.updated_at
    assert second.updated_by == "admin@example.com"
    assert second.row_version == 2


def test_stale_row_version_is_rejected_without_overwrite():
    repo = ManufacturerPriceSourceRepository()
    first = save_source_setting(
        SOURCE_DT40,
        "https://example.test/one.xlsx",
        True,
        expected_row_version=0,
        repository=repo,
    )
    save_source_setting(
        SOURCE_DT40,
        "https://example.test/two.xlsx",
        True,
        expected_row_version=first.row_version,
        repository=repo,
    )

    with pytest.raises(ManufacturerPriceSourceConflictError):
        save_source_setting(
            SOURCE_DT40,
            "https://example.test/stale.xlsx",
            True,
            expected_row_version=first.row_version,
            repository=repo,
        )

    assert repo.get(SOURCE_DT40).source_url == "https://example.test/two.xlsx"


@pytest.mark.parametrize(
    ("slot", "wrong_factory"),
    [
        (SOURCE_DT40, official_pt30_style_book),
        (SOURCE_PT30, official_dt40_style_book),
    ],
)
def test_wrong_manufacturer_workbook_is_rejected_and_active_is_unchanged(slot, wrong_factory):
    price_repo_current = import_price_master(
        PriceMasterType(slot),
        "active.xlsx",
        (official_dt40_style_book if slot == SOURCE_DT40 else official_pt30_style_book)().getvalue(),
    ).record
    source_repo = ManufacturerPriceSourceRepository()
    source = save_source_setting(
        slot,
        f"https://example.test/{slot}.xlsx",
        True,
        expected_row_version=0,
        repository=source_repo,
    )

    def fetch(_source):
        return FetchedWorkbook(
            data=wrong_factory().getvalue(),
            filename="wrong.xlsx",
            fetch_url=_source.fetch_url,
        )

    checked, review = check_source_connection(source, source_repository=source_repo, fetcher=fetch)

    assert review.status == OnlinePriceReviewStatus.VALIDATION_FAILED
    assert review.reason_code == "MASTER_TYPE_UNCONFIRMED"
    assert checked.last_check_status == "VALIDATION_FAILED"
    assert get_active_master(PriceMasterType(slot)).record.import_id == price_repo_current.import_id


def test_invalid_url_is_rejected_and_active_master_is_unchanged():
    current = import_price_master(
        PriceMasterType.DT40,
        "active.xlsx",
        official_dt40_style_book().getvalue(),
    ).record

    with pytest.raises(ManufacturerPriceSourceValidationError):
        save_source_setting(SOURCE_DT40, "http://not-secure.example.test/book.xlsx", True, expected_row_version=0)

    assert get_active_master(PriceMasterType.DT40).record.import_id == current.import_id
    assert ManufacturerPriceSourceRepository().get(SOURCE_DT40) is None


def test_spectra_gold_connection_check_does_not_enter_quote_price_books():
    repo = ManufacturerPriceSourceRepository()
    source = save_source_setting(
        SOURCE_SPECTRA_GOLD,
        "https://example.test/spectra.xlsx",
        True,
        expected_row_version=0,
        repository=repo,
    )

    def fetch(_source):
        return FetchedWorkbook(
            data=_dt40({"NEW SHEET NAME": [["S-1", "Future", 100, 60, None]]}),
            filename="spectra.xlsx",
            fetch_url=_source.fetch_url,
        )

    checked, review = check_source_connection(source, source_repository=repo, fetcher=fetch)

    assert checked.last_check_status == "CONNECTED_FUTURE"
    assert review is None
    assert SOURCE_SPECTRA_GOLD not in {item.value for item in MANUFACTURER_MASTERS}
    assert SOURCE_SPECTRA_GOLD not in {item.value for item in PriceMasterType}
    assert get_active_master(PriceMasterType.DT40) is None
    assert get_active_master(PriceMasterType.PT30) is None


def test_db_registry_precedes_environment_and_bootstrap_fallback(monkeypatch, tmp_path):
    repo = ManufacturerPriceSourceRepository(tmp_path / "registry.sqlite3")
    monkeypatch.setenv("DT40_ONLINE_PRICE_SOURCE_URL", "https://example.test/env.xlsx")
    config = tmp_path / "sources.json"
    config.write_text(
        json.dumps({"DT40": {"source_id": "bootstrap", "url": "https://example.test/config.xlsx"}}),
        encoding="utf-8",
    )

    fallback = resolve_registered_price_source(
        SOURCE_DT40,
        master_type=PriceMasterType.DT40,
        config_path=config,
        source_repository=repo,
    )
    stored = save_source_setting(
        SOURCE_DT40,
        "https://example.test/db.xlsx",
        True,
        expected_row_version=0,
        repository=repo,
    )
    authoritative = resolve_registered_price_source(
        SOURCE_DT40,
        master_type=PriceMasterType.DT40,
        config_path=config,
        source_repository=repo,
    )

    assert fallback.url == "https://example.test/env.xlsx"
    assert stored.source_url == "https://example.test/db.xlsx"
    assert authoritative.url == "https://example.test/db.xlsx"


def test_json_bootstrap_is_used_when_db_and_environment_are_empty(monkeypatch, tmp_path):
    monkeypatch.delenv("PT30_ONLINE_PRICE_SOURCE_URL", raising=False)
    repo = ManufacturerPriceSourceRepository(tmp_path / "registry.sqlite3")
    config = tmp_path / "sources.json"
    config.write_text(
        json.dumps({"PT30": {"source_id": "PT30-bootstrap", "url": "https://example.test/config-pt30.xlsx"}}),
        encoding="utf-8",
    )

    source = resolve_registered_price_source(
        SOURCE_PT30,
        master_type=PriceMasterType.PT30,
        config_path=config,
        source_repository=repo,
    )

    assert source.source_id == "PT30-bootstrap"
    assert source.url == "https://example.test/config-pt30.xlsx"
    assert source.configured is True


def test_effective_source_list_includes_future_source_without_persisting_it():
    repo = ManufacturerPriceSourceRepository()

    sources = {item.source_key: item for item in list_effective_sources(repo)}

    assert sources[SOURCE_SPECTRA_GOLD].lifecycle_status == "FUTURE"
    assert repo.list_sources() == []


def test_admin_ui_can_save_url_and_labels_spectra_as_future():
    from tests.test_price_master_ui import _open_quote_page, _texts

    at = _open_quote_page()
    assert "オンライン価格表設定" in _texts(at)
    assert "将来利用予定。現在の見積価格には使用されません。" in _texts(at)

    at.text_input(key="manufacturer_source_url_DT40").set_value("https://example.test/ui-dt40.xlsx")
    at.button(key="manufacturer_source_save_DT40").click().run()

    assert not at.exception
    assert "オンライン価格表URLを保存しました" in _texts(at)
    assert ManufacturerPriceSourceRepository().get(SOURCE_DT40).source_url == "https://example.test/ui-dt40.xlsx"
    assert get_active_master(PriceMasterType.DT40) is None
