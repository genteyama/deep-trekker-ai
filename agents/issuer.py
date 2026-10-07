from pathlib import Path
from typing import Optional
import json

from pydantic import ValidationError

from models import IssuerSnapshot

ISSUER_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "issuer.json"
REQUIRED_ISSUER_FIELDS = ("company_name", "address", "office_address", "telephone", "source_reference")


class IssuerConfigError(ValueError):
    pass


def load_issuer_snapshot(path: Optional[Path] = None) -> IssuerSnapshot:
    """Load the official issuer source. Fails closed; no defaults are filled in."""
    source = Path(path) if path is not None else ISSUER_CONFIG_PATH
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise IssuerConfigError(f"Issuer config not found: {source}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise IssuerConfigError(f"Issuer config is unreadable: {source}") from exc
    if not isinstance(raw, dict):
        raise IssuerConfigError(f"Issuer config must be a JSON object: {source}")
    missing = [
        key for key in REQUIRED_ISSUER_FIELDS
        if not isinstance(raw.get(key), str) or not raw[key].strip()
    ]
    if missing:
        raise IssuerConfigError(f"Issuer config is missing required fields: {', '.join(missing)}")
    try:
        return IssuerSnapshot.model_validate(raw)
    except ValidationError as exc:
        raise IssuerConfigError(f"Issuer config is invalid: {source}") from exc
