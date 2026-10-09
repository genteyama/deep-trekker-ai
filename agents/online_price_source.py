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
from urllib.request import Request, urlopen

from models import PriceMasterType
from repositories.manufacturer_price_source_repository import (
    ManufacturerPriceSourceRepository,
    SOURCE_DT40,
    SOURCE_PT30,
    SOURCE_SPECTRA_GOLD,
)
from repositories.settings import get_setting

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "manufacturer_price_sources.json"
FETCH_TIMEOUT_SECONDS = 30
MAX_BYTES = 25 * 1024 * 1024
_SPREADSHEET_ID = re.compile(r"https://docs\.google\.com/spreadsheets/d/([a-zA-Z0-9-_]+)")
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
    pass


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


def xlsx_export_url(url: str) -> str:
    """Use a Google Spreadsheet's xlsx export when the configured URL is a spreadsheet link."""
    text = (url or "").strip()
    if "/export" in text and "format=xlsx" in text:
        return text
    match = _SPREADSHEET_ID.search(text)
    if not match:
        return text
    return f"https://docs.google.com/spreadsheets/d/{match.group(1)}/export?format=xlsx"


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
        raise OnlinePriceFetchError("Online price source is not configured.")
    request = Request(source.fetch_url, headers={"User-Agent": "DeepTrekkerAI-PriceMasterSync/1.2"})
    if source.authorization:
        request.add_header("Authorization", source.authorization)
    try:
        with urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            data = response.read(MAX_BYTES + 1)
            filename = _filename_from_headers(response.headers)
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise OnlinePriceFetchError(type(error).__name__) from error
    if len(data) > MAX_BYTES:
        raise OnlinePriceFetchError("RESPONSE_TOO_LARGE")
    return FetchedWorkbook(data=data, filename=filename, fetch_url=source.fetch_url)


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
