from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class TokenUsageRecord:
    provider: str
    model: Optional[str]
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    timestamp: str
    case_id: Optional[str]
    operation: str
    success: bool
    http_status: Optional[int]
    duration_ms: Optional[int]
    fallbacks_enabled: bool

    def as_dict(self) -> dict:
        return asdict(self)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def tokens_from_response(response) -> tuple[Optional[int], Optional[int]]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None, None
    return getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None)
