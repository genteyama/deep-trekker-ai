"""Where the DT40 / PT30 manufacturer workbooks are fetched from.

URLs are not hardcoded. A person sets them in config/manufacturer_price_sources.json
or in the environment / Streamlit secrets. A Google Spreadsheet link is read through
that spreadsheet's xlsx export. No Google API client is used.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from models import PriceMasterType
from repositories.manufacturer_price_source_repository import (
    ManufacturerPriceSourceRepository,
    SOURCE_DT40,
    SOURCE_PT30,
    SOURCE_SPECTRA_GOLD,
)
from repositories.settings import get_secret_mapping, get_setting

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "manufacturer_price_sources.json"
FETCH_TIMEOUT_SECONDS = 30
MAX_BYTES = 25 * 1024 * 1024
XLSX_SIGNATURE = b"PK\x03\x04"
AUTH_MODE_PUBLIC = "PUBLIC"
AUTH_MODE_GOOGLE_SERVICE_ACCOUNT = "GOOGLE_SERVICE_ACCOUNT"
GOOGLE_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
GOOGLE_EXPORT_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
GOOGLE_SERVICE_ACCOUNT_SECRET = "google_price_source_service_account"
_GOOGLE_HOST = "docs.google.com"
_FILE_ID = re.compile(r"^[a-zA-Z0-9_-]+$")
_URL_ENV = {
    SOURCE_DT40: "DT40_ONLINE_PRICE_SOURCE_URL",
    SOURCE_PT30: "PT30_ONLINE_PRICE_SOURCE_URL",
    SOURCE_SPECTRA_GOLD: "SPECTRA_GOLD_ONLINE_PRICE_SOURCE_URL",
}
_AUTH_ENV = {
    SOURCE_DT40: "DT40_ONLINE_PRICE_SOURCE_AUTHORIZATION",
    SOURCE_PT30: "PT30_ONLINE_PRICE_SOURCE_AUTHORIZATION",
    SOURCE_SPECTRA_GOLD: "SPECTRA_GOLD_ONLINE_PRICE_SOURCE_AUTHORIZATION",
}


class OnlinePriceFetchError(RuntimeError):
    def __init__(self, reason_code: str):
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class OnlinePriceSource:
    master_type: Optional[PriceMasterType]
    source_id: str
    url: str
    enabled: bool = True
    source_key: Optional[str] = None
    registry_row_version: Optional[int] = None
    authorization: Optional[str] = None
    config_error: Optional[str] = None

    @property
    def configured(self) -> bool:
        return self.enabled and not self.config_error and self.url.lower().startswith("https://")

    @property
    def fetch_url(self) -> str:
        return xlsx_export_url(self.url)


@dataclass(frozen=True)
class FetchedWorkbook:
    data: bytes
    filename: Optional[str]
    fetch_url: str
    auth_mode: str = AUTH_MODE_PUBLIC


def xlsx_export_url(url: str) -> str:
    """Use a Google Spreadsheet's xlsx export when the configured URL is a spreadsheet link."""
    text = (url or "").strip()
    if "/export" in text and "format=xlsx" in text:
        return text
    file_id = google_spreadsheet_file_id(text)
    if not file_id:
        return text
    return f"https://docs.google.com/spreadsheets/d/{file_id}/export?format=xlsx"


def google_spreadsheet_file_id(url: str) -> Optional[str]:
    """Extract an ID only from the documented HTTPS Google Spreadsheet URL shape."""
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return None
    if parsed.scheme.lower() != "https" or (parsed.hostname or "").lower() != _GOOGLE_HOST:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 3 or parts[0:2] != ["spreadsheets", "d"]:
        return None
    file_id = parts[2]
    return file_id if _FILE_ID.fullmatch(file_id) else None


def resolve_online_price_source(
    master_type: PriceMasterType,
    *,
    config_path: Optional[Path] = None,
    source_repository: Optional[ManufacturerPriceSourceRepository] = None,
) -> OnlinePriceSource:
    master_type = PriceMasterType(master_type)
    return resolve_registered_price_source(
        master_type.value,
        master_type=master_type,
        config_path=config_path,
        source_repository=source_repository,
    )


def resolve_registered_price_source(
    source_key: str,
    *,
    master_type: Optional[PriceMasterType] = None,
    config_path: Optional[Path] = None,
    source_repository: Optional[ManufacturerPriceSourceRepository] = None,
) -> OnlinePriceSource:
    """DB is authoritative. Environment/secrets and JSON are bootstrap-only fallbacks."""
    repository = source_repository or ManufacturerPriceSourceRepository()
    try:
        registered = repository.get(source_key)
    except Exception as error:
        logger.warning("online_price_source_registry_unavailable type=%s error=%s", source_key, type(error).__name__)
        registered = None
    if registered is not None:
        return OnlinePriceSource(
            master_type=master_type,
            source_id=registered.source_key,
            url=registered.source_url,
            enabled=registered.enabled,
            source_key=registered.source_key,
            registry_row_version=registered.row_version,
            authorization=(get_setting(_AUTH_ENV.get(source_key, "")) or "").strip() or None,
        )

    file_entry, config_error = _file_entry(source_key, config_path or CONFIG_PATH)
    source_id = str(file_entry.get("source_id") or source_key)
    configured_url = (get_setting(_URL_ENV.get(source_key, "")) or "").strip()
    if not configured_url:
        configured_url = str(file_entry.get("url") or "").strip()
    authorization = (get_setting(_AUTH_ENV.get(source_key, "")) or "").strip() or None
    return OnlinePriceSource(
        master_type=master_type,
        source_id=source_id,
        url=configured_url,
        enabled=bool(configured_url),
        source_key=source_key,
        registry_row_version=0,
        authorization=authorization,
        config_error=config_error,
    )


def fetch_workbook(source: OnlinePriceSource) -> FetchedWorkbook:
    if not source.configured:
        raise OnlinePriceFetchError("NOT_CONFIGURED")
    parsed = urlparse(source.url)
    is_google = (parsed.hostname or "").lower() == _GOOGLE_HOST
    if not is_google:
        return _fetch_public(source)

    file_id = google_spreadsheet_file_id(source.url)
    if not file_id:
        raise OnlinePriceFetchError("INVALID_GOOGLE_URL")
    service_account_info = get_secret_mapping(GOOGLE_SERVICE_ACCOUNT_SECRET)
    if service_account_info is None:
        try:
            return _fetch_public(source)
        except OnlinePriceFetchError as error:
            if error.reason_code in {"GOOGLE_EXPORT_TOO_LARGE", "RESPONSE_TOO_LARGE"}:
                raise OnlinePriceFetchError("GOOGLE_EXPORT_TOO_LARGE") from None
            raise OnlinePriceFetchError("GOOGLE_AUTH_NOT_CONFIGURED") from None

    try:
        return _fetch_google_authenticated(source, file_id, service_account_info)
    except OnlinePriceFetchError as auth_error:
        if auth_error.reason_code not in {"GOOGLE_ACCESS_DENIED", "GOOGLE_EXPORT_FAILED"}:
            raise
        try:
            return _fetch_public(source)
        except OnlinePriceFetchError:
            raise OnlinePriceFetchError(auth_error.reason_code) from None


def _fetch_public(source: OnlinePriceSource) -> FetchedWorkbook:
    request = Request(source.fetch_url, headers={"User-Agent": "DeepTrekkerAI-PriceMasterSync/1.2"})
    if source.authorization:
        request.add_header("Authorization", source.authorization)
    try:
        with urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            data = response.read(MAX_BYTES + 1)
            filename = _filename_from_headers(response.headers)
    except (HTTPError, URLError, TimeoutError, OSError):
        raise OnlinePriceFetchError("FETCH_FAILED") from None
    if len(data) > MAX_BYTES:
        raise OnlinePriceFetchError("RESPONSE_TOO_LARGE")
    if not data.startswith(XLSX_SIGNATURE):
        raise OnlinePriceFetchError("NOT_XLSX")
    return FetchedWorkbook(
        data=data,
        filename=filename,
        fetch_url=source.fetch_url,
        auth_mode=AUTH_MODE_PUBLIC,
    )


def _fetch_google_authenticated(
    source: OnlinePriceSource,
    file_id: str,
    service_account_info: dict,
) -> FetchedWorkbook:
    try:
        from google.auth.transport.requests import Request as GoogleAuthRequest
        from google.oauth2 import service_account

        credentials = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=[GOOGLE_DRIVE_SCOPE],
        )
        credentials.refresh(GoogleAuthRequest())
    except Exception:
        raise OnlinePriceFetchError("GOOGLE_AUTH_INVALID") from None

    endpoint = f"https://www.googleapis.com/drive/v3/files/{file_id}/export"
    try:
        import requests

        response = requests.get(
            endpoint,
            params={"mimeType": GOOGLE_EXPORT_MIME_TYPE},
            headers={"Authorization": f"Bearer {credentials.token}"},
            timeout=FETCH_TIMEOUT_SECONDS,
            stream=True,
        )
    except Exception:
        raise OnlinePriceFetchError("GOOGLE_EXPORT_FAILED") from None
    if response.status_code in {401, 403}:
        raise OnlinePriceFetchError("GOOGLE_ACCESS_DENIED")
    if response.status_code != 200:
        raise OnlinePriceFetchError("GOOGLE_EXPORT_FAILED")
    data = _read_limited_response(response)
    if not data.startswith(XLSX_SIGNATURE):
        raise OnlinePriceFetchError("NOT_XLSX")
    return FetchedWorkbook(
        data=data,
        filename=f"{source.source_key or source.source_id}.xlsx",
        fetch_url=source.fetch_url,
        auth_mode=AUTH_MODE_GOOGLE_SERVICE_ACCOUNT,
    )


def _read_limited_response(response) -> bytes:
    chunks = []
    size = 0
    try:
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            size += len(chunk)
            if size > MAX_BYTES:
                raise OnlinePriceFetchError("GOOGLE_EXPORT_TOO_LARGE")
            chunks.append(chunk)
    except OnlinePriceFetchError:
        raise
    except Exception:
        raise OnlinePriceFetchError("GOOGLE_EXPORT_FAILED") from None
    return b"".join(chunks)


def _file_entry(source_key: str, path: Path) -> tuple[dict, Optional[str]]:
    if not path.is_file():
        return {}, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("online_price_source_config_unreadable type=%s", source_key)
        return {}, "CONFIG_UNREADABLE"
    entry = payload.get(source_key) if isinstance(payload, dict) else None
    if not isinstance(entry, dict):
        return {}, None
    return entry, None


def _filename_from_headers(headers) -> Optional[str]:
    disposition = headers.get("Content-Disposition") if headers is not None else None
    if not disposition:
        return None
    match = re.search(r'filename="?([^";]+)"?', disposition)
    if not match:
        return None
    name = match.group(1).strip()
    return name or None
