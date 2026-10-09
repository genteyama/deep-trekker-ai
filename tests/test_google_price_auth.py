import logging

import pytest

from agents.manufacturer_price_source import check_source_connection, save_source_setting
from agents.online_price_master import (
    OnlinePriceReviewStatus,
    activate_reviewed_online_price,
    review_manufacturer_online_price,
)
from agents.online_price_source import (
    AUTH_MODE_GOOGLE_SERVICE_ACCOUNT,
    AUTH_MODE_PUBLIC,
    GOOGLE_DRIVE_SCOPE,
    GOOGLE_SERVICE_ACCOUNT_SECRET,
    FetchedWorkbook,
    OnlinePriceFetchError,
    OnlinePriceSource,
    fetch_workbook,
    google_spreadsheet_file_id,
)
from agents.price_master import MANUFACTURER_MASTERS, get_active_master, import_price_master
from agents.quote_builder import apply_exchange_rate
from models import PriceMasterImportStatus, PriceMasterType
from repositories.manufacturer_price_source_repository import (
    ManufacturerPriceSourceRepository,
    SOURCE_DT40,
    SOURCE_PT30,
    SOURCE_SPECTRA_GOLD,
)
from repositories.sqlite_price_master_repository import SqlitePriceMasterRepository
from tests.price_book_fixtures import build_workbook, official_dt40_style_book, official_pt30_style_book
from tests.test_quote_builder import _line, _mag_v1, _v1_mag_draft

PRIVATE_KEY_MARKER = "PRIVATE-KEY-MUST-NOT-LEAK"
TOKEN_MARKER = "ACCESS-TOKEN-MUST-NOT-LEAK"
SERVICE_ACCOUNT = {
    "type": "service_account",
    "project_id": "test-project",
    "private_key_id": "placeholder",
    "private_key": PRIVATE_KEY_MARKER,
    "client_email": "price-source@test-project.iam.gserviceaccount.com",
    "client_id": "123",
    "token_uri": "https://oauth2.googleapis.com/token",
}


class _PublicResponse:
    def __init__(self, data: bytes, headers=None):
        self.data = data
        self.headers = headers or {}

    def read(self, _limit):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _DriveResponse:
    def __init__(self, status_code: int, data: bytes = b""):
        self.status_code = status_code
        self.data = data

    def iter_content(self, chunk_size):
        for index in range(0, len(self.data), chunk_size):
            yield self.data[index : index + chunk_size]


class _Credentials:
    token = TOKEN_MARKER

    def refresh(self, _request):
        return None


def _google_source(source_key=SOURCE_SPECTRA_GOLD):
    return OnlinePriceSource(
        master_type=PriceMasterType(source_key) if source_key in {SOURCE_DT40, SOURCE_PT30} else None,
        source_id=source_key,
        source_key=source_key,
        url=f"https://docs.google.com/spreadsheets/d/{source_key}_FILE_ID/edit#gid=0",
        enabled=True,
        registry_row_version=1,
    )


def _set_service_account(monkeypatch, value=SERVICE_ACCOUNT):
    monkeypatch.setattr(
        "repositories.settings._read_st_secret",
        lambda name: value if name == GOOGLE_SERVICE_ACCOUNT_SECRET else None,
    )


def _mock_credentials(monkeypatch):
    from google.oauth2 import service_account

    captured = {}

    def from_info(cls, info, scopes):
        captured["info"] = info
        captured["scopes"] = scopes
        return _Credentials()

    monkeypatch.setattr(
        service_account.Credentials,
        "from_service_account_info",
        classmethod(from_info),
    )
    return captured


def _mock_drive(monkeypatch, status, data=b""):
    captured = {}

    def get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _DriveResponse(status, data)

    monkeypatch.setattr("requests.get", get)
    return captured


@pytest.mark.parametrize(
    ("master_type", "factory", "source_key"),
    [
        (PriceMasterType.DT40, official_dt40_style_book, SOURCE_DT40),
        (PriceMasterType.PT30, official_pt30_style_book, SOURCE_PT30),
    ],
)
def test_public_manufacturer_no_change_workflow_is_unchanged(monkeypatch, master_type, factory, source_key):
    data = factory().getvalue()
    prices = SqlitePriceMasterRepository()
    current = import_price_master(master_type, "active.xlsx", data, repository=prices).record
    source = _google_source(source_key)
    monkeypatch.setattr(
        "agents.online_price_source.urlopen",
        lambda *_args, **_kwargs: _PublicResponse(data),
    )

    review = review_manufacturer_online_price(master_type, repository=prices, source=source)

    assert review.status == OnlinePriceReviewStatus.NO_CHANGE
    assert review.auth_mode == AUTH_MODE_PUBLIC
    assert get_active_master(master_type, prices).record.import_id == current.import_id
    assert len(prices.list_imports(master_type)) == 1


def test_private_google_sheet_authenticated_export_succeeds(monkeypatch):
    data = build_workbook({"FUTURE": [["SKU"], ["S-1"]]}).getvalue()
    _set_service_account(monkeypatch)
    credentials = _mock_credentials(monkeypatch)
    request = _mock_drive(monkeypatch, 200, data)

    fetched = fetch_workbook(_google_source())

    assert fetched.data == data
    assert fetched.auth_mode == AUTH_MODE_GOOGLE_SERVICE_ACCOUNT
    assert credentials["scopes"] == [GOOGLE_DRIVE_SCOPE]
    assert request["params"]["mimeType"].endswith("spreadsheetml.sheet")
    assert request["headers"]["Authorization"] == f"Bearer {TOKEN_MARKER}"


def test_service_account_not_configured_private_sheet_fails_closed(monkeypatch):
    monkeypatch.setattr(
        "agents.online_price_source.urlopen",
        lambda *_args, **_kwargs: _PublicResponse(b"<html>Google sign in</html>"),
    )

    with pytest.raises(OnlinePriceFetchError) as error:
        fetch_workbook(_google_source())

    assert error.value.reason_code == "GOOGLE_AUTH_NOT_CONFIGURED"


def test_malformed_service_account_fails_closed(monkeypatch):
    _set_service_account(monkeypatch, {"type": "service_account", "private_key": "bad"})

    with pytest.raises(OnlinePriceFetchError) as error:
        fetch_workbook(_google_source())

    assert error.value.reason_code == "GOOGLE_AUTH_INVALID"


def test_permission_denied_private_sheet_fails_closed(monkeypatch):
    _set_service_account(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_drive(monkeypatch, 403)
    monkeypatch.setattr(
        "agents.online_price_source.urlopen",
        lambda *_args, **_kwargs: _PublicResponse(b"<html>Google sign in</html>"),
    )

    with pytest.raises(OnlinePriceFetchError) as error:
        fetch_workbook(_google_source())

    assert error.value.reason_code == "GOOGLE_ACCESS_DENIED"


def test_permission_denied_public_sheet_falls_back_to_public_export(monkeypatch):
    data = official_dt40_style_book().getvalue()
    _set_service_account(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_drive(monkeypatch, 403)
    monkeypatch.setattr(
        "agents.online_price_source.urlopen",
        lambda *_args, **_kwargs: _PublicResponse(data),
    )

    fetched = fetch_workbook(_google_source(SOURCE_DT40))

    assert fetched.data == data
    assert fetched.auth_mode == AUTH_MODE_PUBLIC


def test_non_google_url_never_uses_google_auth(monkeypatch):
    data = official_dt40_style_book().getvalue()
    _set_service_account(monkeypatch)
    monkeypatch.setattr(
        "agents.online_price_source._fetch_google_authenticated",
        lambda *_args, **_kwargs: pytest.fail("Google auth must not run"),
    )
    monkeypatch.setattr(
        "agents.online_price_source.urlopen",
        lambda *_args, **_kwargs: _PublicResponse(data),
    )
    source = OnlinePriceSource(
        master_type=PriceMasterType.DT40,
        source_id=SOURCE_DT40,
        url="https://prices.example.test/dt40.xlsx",
    )

    fetched = fetch_workbook(source)

    assert fetched.auth_mode == AUTH_MODE_PUBLIC


@pytest.mark.parametrize(
    "url",
    [
        "https://docs.google.com/spreadsheets/d/",
        "https://docs.google.com/document/d/not-a-sheet/edit",
        "https://evil.example.test/spreadsheets/d/FAKE/edit",
        "http://docs.google.com/spreadsheets/d/FILE/edit",
    ],
)
def test_invalid_google_spreadsheet_url_is_not_accepted(url):
    assert google_spreadsheet_file_id(url) is None
    source = OnlinePriceSource(master_type=None, source_id="INVALID", url=url)
    if url.startswith("https://docs.google.com"):
        with pytest.raises(OnlinePriceFetchError) as error:
            fetch_workbook(source)
        assert error.value.reason_code == "INVALID_GOOGLE_URL"


def test_returned_html_is_rejected(monkeypatch):
    monkeypatch.setattr(
        "agents.online_price_source.urlopen",
        lambda *_args, **_kwargs: _PublicResponse(b"<html>not xlsx</html>"),
    )
    source = OnlinePriceSource(
        master_type=None,
        source_id="HTML",
        url="https://prices.example.test/book.xlsx",
    )

    with pytest.raises(OnlinePriceFetchError) as error:
        fetch_workbook(source)

    assert error.value.reason_code == "NOT_XLSX"


def test_authenticated_auth_mode_is_kept_in_snapshot_provenance_without_secrets(monkeypatch):
    current = official_dt40_style_book().getvalue()
    changed = build_workbook(
        {
            "CONFIG": [["Discount Code:", "E_DT-40"]],
            "PHOTON": [
                ["Part Number", "Description", "MSRP", "DT40", "Notes:"],
                ["9680-BASE", "PHOTON BASE", 18000, 10800, None],
            ],
        }
    ).getvalue()
    prices = SqlitePriceMasterRepository()
    sources = ManufacturerPriceSourceRepository()
    import_price_master(PriceMasterType.DT40, "active.xlsx", current, repository=prices)
    source_record = save_source_setting(
        SOURCE_DT40,
        _google_source(SOURCE_DT40).url,
        True,
        expected_row_version=0,
        repository=sources,
    )
    source = _google_source(SOURCE_DT40)
    source = OnlinePriceSource(
        **{
            **source.__dict__,
            "registry_row_version": source_record.row_version,
        }
    )
    _set_service_account(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_drive(monkeypatch, 200, changed)

    review = review_manufacturer_online_price(PriceMasterType.DT40, repository=prices, source=source)
    outcome = activate_reviewed_online_price(review, repository=prices, source_repository=sources)

    assert review.auth_mode == AUTH_MODE_GOOGLE_SERVICE_ACCOUNT
    assert outcome.status == PriceMasterImportStatus.ACTIVATED
    provenance = outcome.record.validation_summary["online_source"]
    assert provenance["auth_mode"] == AUTH_MODE_GOOGLE_SERVICE_ACCOUNT
    serialized = str(provenance)
    assert PRIVATE_KEY_MARKER not in serialized
    assert TOKEN_MARKER not in serialized
    assert "Authorization" not in serialized


def test_credentials_and_token_are_not_logged_on_access_denied(monkeypatch, caplog):
    _set_service_account(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_drive(monkeypatch, 403)
    monkeypatch.setattr(
        "agents.online_price_source.urlopen",
        lambda *_args, **_kwargs: _PublicResponse(b"<html>denied</html>"),
    )
    caplog.set_level(logging.WARNING)

    review = review_manufacturer_online_price(
        PriceMasterType.DT40,
        source=_google_source(SOURCE_DT40),
    )

    assert review.status == OnlinePriceReviewStatus.FETCH_FAILED
    assert review.reason_code == "GOOGLE_ACCESS_DENIED"
    assert PRIVATE_KEY_MARKER not in caplog.text
    assert TOKEN_MARKER not in caplog.text
    assert "Authorization" not in caplog.text


def test_spectra_gold_authenticated_connectivity_succeeds_without_pricing(monkeypatch):
    data = build_workbook({"ANY FUTURE SHEET": [["SKU"], ["S-1"]]}).getvalue()
    sources = ManufacturerPriceSourceRepository()
    source = save_source_setting(
        SOURCE_SPECTRA_GOLD,
        _google_source().url,
        True,
        expected_row_version=0,
        repository=sources,
    )
    _set_service_account(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_drive(monkeypatch, 200, data)

    checked, review = check_source_connection(source, source_repository=sources)

    assert checked.last_check_status == "CONNECTED_FUTURE"
    assert review is None
    assert SOURCE_SPECTRA_GOLD not in {item.value for item in MANUFACTURER_MASTERS}
    assert SOURCE_SPECTRA_GOLD not in {item.value for item in PriceMasterType}
    assert get_active_master(PriceMasterType.DT40) is None
    assert get_active_master(PriceMasterType.PT30) is None


def test_google_export_too_large_fails_closed(monkeypatch):
    _set_service_account(monkeypatch)
    _mock_credentials(monkeypatch)

    class LargeResponse:
        status_code = 200

        def iter_content(self, chunk_size):
            from agents.online_price_source import MAX_BYTES

            yield b"x" * (MAX_BYTES // 2 + 1)
            yield b"x" * (MAX_BYTES // 2 + 1)

    monkeypatch.setattr("requests.get", lambda *_args, **_kwargs: LargeResponse())

    with pytest.raises(OnlinePriceFetchError) as error:
        fetch_workbook(_google_source())

    assert error.value.reason_code == "GOOGLE_EXPORT_TOO_LARGE"


def test_quote_regression_remains_unchanged():
    draft = _v1_mag_draft(_mag_v1())
    apply_exchange_rate(draft, 165, sales_candidates=_mag_v1(165.0))

    assert _line(draft, "9701-MAG-4K").standard_sales_price_candidate_jpy == 6432000
