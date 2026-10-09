from agents.manufacturer_price_source import save_source_setting
from agents.online_price_master import (
    OnlinePriceReviewStatus,
    activate_reviewed_online_price,
    inspect_online_workbook,
)
from agents.online_price_source import OnlinePriceSource
from agents.price_master import get_active_master, import_price_master
from agents.quote_builder import apply_exchange_rate
from models import PriceMasterImportOutcome, PriceMasterImportStatus, PriceMasterType
from repositories.manufacturer_price_source_repository import (
    ManufacturerPriceSourceRepository,
    SOURCE_DT40,
)
from repositories.sqlite_price_master_repository import SqlitePriceMasterRepository
from tests.test_online_price_master import _dt40
from tests.test_quote_builder import _line, _mag_v1, _v1_mag_draft
from ui.price_master import outcome_message

MASTER_A = {
    "PHOTON": [
        ["9680-BASE", "PHOTON BASE", 100, 60, None],
        ["2535", "GAME PAD", 10, 10, None],
    ]
}
ONLINE_B = {
    "PHOTON": [
        ["9680-BASE", "PHOTON BASE", 110, 66, None],
        ["2535", "GAME PAD", 10, 10, None],
    ]
}
MASTER_C = {
    "PHOTON": [
        ["9680-BASE", "PHOTON BASE", 120, 72, None],
        ["2535", "GAME PAD", 10, 10, None],
    ]
}


def _source(repository: ManufacturerPriceSourceRepository):
    record = save_source_setting(
        SOURCE_DT40,
        "https://example.test/dt40.xlsx",
        True,
        expected_row_version=0,
        repository=repository,
    )
    return record


def _review(source_record, price_repository):
    source = OnlinePriceSource(
        master_type=PriceMasterType.DT40,
        source_id=source_record.source_key,
        source_key=source_record.source_key,
        url=source_record.source_url,
        enabled=source_record.enabled,
        registry_row_version=source_record.row_version,
    )
    review = inspect_online_workbook(
        PriceMasterType.DT40,
        _dt40(ONLINE_B),
        filename="online-b.xlsx",
        source=source,
        repository=price_repository,
    )
    assert review.status == OnlinePriceReviewStatus.CHANGES_PENDING
    return review


def test_review_of_master_a_is_rejected_after_master_c_is_activated():
    prices = SqlitePriceMasterRepository()
    sources = ManufacturerPriceSourceRepository()
    source = _source(sources)
    master_a = import_price_master(PriceMasterType.DT40, "a.xlsx", _dt40(MASTER_A), repository=prices).record
    review_b = _review(source, prices)
    master_c = import_price_master(PriceMasterType.DT40, "c.xlsx", _dt40(MASTER_C), repository=prices).record

    outcome = activate_reviewed_online_price(review_b, repository=prices, source_repository=sources)

    assert review_b.active_import_id == master_a.import_id
    assert outcome.status == PriceMasterImportStatus.REJECTED
    assert outcome.reason_code == "ONLINE_REVIEW_STALE"
    assert get_active_master(PriceMasterType.DT40, prices).record.import_id == master_c.import_id
    assert len(prices.list_imports(PriceMasterType.DT40)) == 2


def test_review_with_no_active_master_is_rejected_after_another_master_is_activated():
    prices = SqlitePriceMasterRepository()
    sources = ManufacturerPriceSourceRepository()
    review_b = _review(_source(sources), prices)
    assert review_b.active_import_id is None
    master_c = import_price_master(PriceMasterType.DT40, "c.xlsx", _dt40(MASTER_C), repository=prices).record

    outcome = activate_reviewed_online_price(review_b, repository=prices, source_repository=sources)

    assert outcome.reason_code == "ONLINE_REVIEW_STALE"
    assert get_active_master(PriceMasterType.DT40, prices).record.import_id == master_c.import_id
    assert len(prices.list_imports(PriceMasterType.DT40)) == 1


def test_review_is_rejected_when_active_master_is_removed_after_review():
    prices = SqlitePriceMasterRepository()
    sources = ManufacturerPriceSourceRepository()
    master_a = import_price_master(PriceMasterType.DT40, "a.xlsx", _dt40(MASTER_A), repository=prices).record
    review_b = _review(_source(sources), prices)
    prices._connection.execute("UPDATE price_master_imports SET active = 0 WHERE import_id = ?", (master_a.import_id,))
    prices._connection.commit()

    outcome = activate_reviewed_online_price(review_b, repository=prices, source_repository=sources)

    assert outcome.reason_code == "ONLINE_REVIEW_STALE"
    assert get_active_master(PriceMasterType.DT40, prices) is None
    assert len(prices.list_imports(PriceMasterType.DT40)) == 1


def test_review_is_rejected_after_source_url_changes():
    prices = SqlitePriceMasterRepository()
    sources = ManufacturerPriceSourceRepository()
    import_price_master(PriceMasterType.DT40, "a.xlsx", _dt40(MASTER_A), repository=prices)
    source = _source(sources)
    review_b = _review(source, prices)
    save_source_setting(
        SOURCE_DT40,
        "https://example.test/new-dt40.xlsx",
        True,
        expected_row_version=source.row_version,
        repository=sources,
    )

    outcome = activate_reviewed_online_price(review_b, repository=prices, source_repository=sources)

    assert outcome.reason_code == "ONLINE_REVIEW_STALE"
    assert len(prices.list_imports(PriceMasterType.DT40)) == 1


def test_review_is_rejected_after_source_is_disabled():
    prices = SqlitePriceMasterRepository()
    sources = ManufacturerPriceSourceRepository()
    import_price_master(PriceMasterType.DT40, "a.xlsx", _dt40(MASTER_A), repository=prices)
    source = _source(sources)
    review_b = _review(source, prices)
    save_source_setting(
        SOURCE_DT40,
        source.source_url,
        False,
        expected_row_version=source.row_version,
        repository=sources,
    )

    outcome = activate_reviewed_online_price(review_b, repository=prices, source_repository=sources)

    assert outcome.reason_code == "ONLINE_REVIEW_STALE"
    assert len(prices.list_imports(PriceMasterType.DT40)) == 1


def test_review_is_rejected_after_source_row_version_only_changes():
    prices = SqlitePriceMasterRepository()
    sources = ManufacturerPriceSourceRepository()
    import_price_master(PriceMasterType.DT40, "a.xlsx", _dt40(MASTER_A), repository=prices)
    source = _source(sources)
    review_b = _review(source, prices)
    sources.record_check(
        SOURCE_DT40,
        status="NO_CHANGE",
        error=None,
        expected_row_version=source.row_version,
    )

    outcome = activate_reviewed_online_price(review_b, repository=prices, source_repository=sources)

    assert outcome.reason_code == "ONLINE_REVIEW_STALE"
    assert len(prices.list_imports(PriceMasterType.DT40)) == 1


def test_review_activates_when_active_master_and_source_are_unchanged():
    prices = SqlitePriceMasterRepository()
    sources = ManufacturerPriceSourceRepository()
    master_a = import_price_master(PriceMasterType.DT40, "a.xlsx", _dt40(MASTER_A), repository=prices).record
    review_b = _review(_source(sources), prices)

    outcome = activate_reviewed_online_price(review_b, repository=prices, source_repository=sources)

    assert outcome.status == PriceMasterImportStatus.ACTIVATED
    assert outcome.record.import_id != master_a.import_id
    assert get_active_master(PriceMasterType.DT40, prices).record.import_id == outcome.record.import_id
    assert len(prices.list_imports(PriceMasterType.DT40)) == 2


def test_review_without_source_registry_identity_fails_closed():
    prices = SqlitePriceMasterRepository()
    import_price_master(PriceMasterType.DT40, "a.xlsx", _dt40(MASTER_A), repository=prices)
    source = OnlinePriceSource(
        master_type=PriceMasterType.DT40,
        source_id=SOURCE_DT40,
        url="https://example.test/dt40.xlsx",
    )
    review = inspect_online_workbook(
        PriceMasterType.DT40,
        _dt40(ONLINE_B),
        source=source,
        repository=prices,
    )

    outcome = activate_reviewed_online_price(review, repository=prices)

    assert outcome.reason_code == "ONLINE_REVIEW_STALE"
    assert len(prices.list_imports(PriceMasterType.DT40)) == 1


def test_stale_message_is_plain_japanese_and_quote_regression_is_unchanged():
    labels = {
        "labels": {"DT40": "DT40"},
        "outcomes": {
            "ONLINE_REVIEW_STALE": (
                "確認後に価格表またはオンライン価格表設定が更新されています。"
                "最新版を再確認してください。現在使用中の価格マスターは変更されていません。"
            )
        },
    }
    rejected = PriceMasterImportOutcome(
        status=PriceMasterImportStatus.REJECTED,
        master_type=PriceMasterType.DT40,
        reason_code="ONLINE_REVIEW_STALE",
    )
    draft = _v1_mag_draft(_mag_v1())
    apply_exchange_rate(draft, 165, sales_candidates=_mag_v1(165.0))

    assert rejected.reason_code == "ONLINE_REVIEW_STALE"
    assert "最新版を再確認してください" in outcome_message(labels, rejected)[1]
    assert _line(draft, "9701-MAG-4K").standard_sales_price_candidate_jpy == 6432000
