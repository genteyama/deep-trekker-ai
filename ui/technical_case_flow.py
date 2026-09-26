from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from models import Case

SESSION_CASE = "technical_case_record"
SESSION_INQUIRY = "customer_inquiry_text"
SESSION_NOTICE = "technical_case_notice"
SESSION_ANALYSIS = "technical_case_analysis"

RESULT_KEYS = (
    "case_summary",
    "requirements",
    "customer_confirmations",
    "manufacturer_confirmations",
    "technical_questions",
    "unconfirmed_items",
)


def normalize_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = value.strip()
    return text if text else None


def generate_case_id() -> str:
    return f"CASE-{uuid4().hex[:12].upper()}"


def build_case_from_inputs(
    case_name: Optional[str],
    customer_name: Optional[str],
    end_user_name: Optional[str],
    case_id: Optional[str] = None,
    created_at: Optional[datetime] = None,
) -> Case:
    timestamp = created_at or datetime.now(timezone.utc)
    return Case(
        case_id=case_id or generate_case_id(),
        case_name=normalize_optional_text(case_name),
        customer_name=normalize_optional_text(customer_name),
        end_user_name=normalize_optional_text(end_user_name),
        created_at=timestamp,
        updated_at=timestamp,
    )


def empty_analysis_result() -> dict:
    return {
        "case_summary": None,
        "requirements": [],
        "customer_confirmations": [],
        "manufacturer_confirmations": [],
        "technical_questions": [],
        "unconfirmed_items": [],
    }


def has_analysis_results(result: Optional[dict]) -> bool:
    if not result:
        return False
    return any(result.get(key) for key in RESULT_KEYS)


def start_inquiry_analysis(
    case_name: Optional[str],
    customer_name: Optional[str],
    end_user_name: Optional[str],
    inquiry_text: Optional[str],
    case_id: Optional[str] = None,
    created_at: Optional[datetime] = None,
) -> tuple[Case, Optional[str], dict]:
    case = build_case_from_inputs(
        case_name,
        customer_name,
        end_user_name,
        case_id=case_id,
        created_at=created_at,
    )
    inquiry = normalize_optional_text(inquiry_text)
    return case, inquiry, empty_analysis_result()
