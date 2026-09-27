from datetime import date

import pytest

from agents.quote_approval import apply_ihi_photon_human_final_fixture
from agents.quote_builder import apply_issue_date, apply_valid_until
from agents.quote_dates import (
    add_one_calendar_month,
    default_issue_date,
    default_valid_until,
    format_quote_date,
    next_valid_until,
    parse_quote_date,
    tokyo_today,
    valid_until_matches_auto_rule,
)
from tests.test_quote_approval import _approve, _ready_photon
from tests.test_quote_builder import _photon_draft


def test_new_draft_uses_tokyo_today_and_one_calendar_month():
    draft = _photon_draft()
    issue = parse_quote_date(draft.issue_date)
    valid = parse_quote_date(draft.valid_until)

    assert issue == tokyo_today()
    assert issue == default_issue_date()
    assert valid == add_one_calendar_month(issue)
    assert valid == default_valid_until(issue)
    assert format_quote_date(issue) == issue.strftime("%Y/%m/%d")
    assert format_quote_date(valid) == valid.strftime("%Y/%m/%d")


def test_valid_until_uses_calendar_month_not_30_days():
    assert add_one_calendar_month(date(2026, 9, 27)) == date(2026, 10, 27)
    assert add_one_calendar_month(date(2026, 11, 30)) == date(2026, 12, 30)
    assert add_one_calendar_month(date(2026, 1, 31)) == date(2026, 2, 28)
    assert add_one_calendar_month(date(2026, 1, 31)) != date(2026, 1, 31).replace() 
    from datetime import timedelta

    assert add_one_calendar_month(date(2026, 1, 31)) != date(2026, 1, 31) + timedelta(days=30)


def test_auto_valid_until_follows_issue_date_only_when_enabled():
    issue = date(2026, 9, 27)
    current = date(2026, 10, 31)

    assert next_valid_until(issue, auto=True, current=current) == date(2026, 10, 27)
    assert next_valid_until(issue, auto=False, current=current) == date(2026, 10, 31)
    assert valid_until_matches_auto_rule(issue, date(2026, 10, 27)) is True
    assert valid_until_matches_auto_rule(issue, current) is False


def test_historical_fixture_dates_are_not_replaced_with_today():
    draft = _photon_draft()
    apply_ihi_photon_human_final_fixture(draft)

    assert draft.issue_date == "2026-09-26"
    assert draft.valid_until == "2026-10-31"


def test_approved_dates_are_immutable():
    draft = _ready_photon()
    _, snapshot = _approve(draft)

    assert snapshot.issue_date == "2026-09-26"
    assert snapshot.valid_until == "2026-10-31"
    with pytest.raises(ValueError, match="Approved drafts cannot be edited"):
        apply_issue_date(draft, tokyo_today())
    with pytest.raises(ValueError, match="Approved drafts cannot be edited"):
        apply_valid_until(draft, tokyo_today())
    assert snapshot.issue_date == "2026-09-26"
    assert snapshot.valid_until == "2026-10-31"
