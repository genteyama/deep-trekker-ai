from datetime import date, datetime
from typing import Optional, Union
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

TOKYO = ZoneInfo("Asia/Tokyo")
DATE_DISPLAY_FORMAT = "%Y/%m/%d"


def tokyo_today() -> date:
    return datetime.now(TOKYO).date()


def add_one_calendar_month(value: date) -> date:
    return value + relativedelta(months=1)


def default_issue_date() -> date:
    return tokyo_today()


def default_valid_until(issue: Optional[date] = None) -> date:
    return add_one_calendar_month(issue or default_issue_date())


def parse_quote_date(value: Union[date, datetime, str, None]) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def to_iso_date(value: Union[date, datetime, str, None]) -> Optional[str]:
    parsed = parse_quote_date(value)
    return parsed.isoformat() if parsed else None


def format_quote_date(value: Union[date, datetime, str, None]) -> str:
    parsed = parse_quote_date(value)
    return parsed.strftime(DATE_DISPLAY_FORMAT) if parsed else ""


def next_valid_until(issue: date, *, auto: bool, current: Optional[date] = None) -> date:
    if auto:
        return add_one_calendar_month(issue)
    return current or add_one_calendar_month(issue)


def valid_until_matches_auto_rule(issue: Optional[date], valid_until: Optional[date]) -> bool:
    if issue is None or valid_until is None:
        return False
    return valid_until == add_one_calendar_month(issue)
