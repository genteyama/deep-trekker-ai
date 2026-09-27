from datetime import date
import inspect

import pytest

from agents.quote_approval import apply_ihi_photon_human_final_fixture
from agents.quote_builder import apply_issue_date, apply_valid_until
from agents.quote_dates import (
    add_one_calendar_month,
    apply_date_widget_defaults,
    date_widget_keys,
    default_issue_date,
    default_valid_until,
    format_quote_date,
    initial_date_widget_values,
    next_valid_until,
    parse_quote_date,
    sync_auto_valid_until,
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


def test_new_draft_widget_defaults_use_tokyo_today():
    draft = _photon_draft()
    issue, valid, auto = initial_date_widget_values(draft)

    assert issue == tokyo_today()
    assert valid == add_one_calendar_month(issue)
    assert auto is True


def test_historical_ihi_widget_defaults_keep_fixture_dates():
    draft = _photon_draft()
    apply_ihi_photon_human_final_fixture(draft)
    issue, valid, auto = initial_date_widget_values(draft)

    assert issue == date(2026, 9, 26)
    assert valid == date(2026, 10, 31)
    assert auto is False


def test_date_widget_defaults_are_initialized_before_widgets():
    draft = _photon_draft()
    apply_ihi_photon_human_final_fixture(draft)
    keys = date_widget_keys(draft.quote_draft_id)
    session = {}

    apply_date_widget_defaults(session, draft)

    assert session[keys["issue"]] == date(2026, 9, 26)
    assert session[keys["valid"]] == date(2026, 10, 31)
    assert session[keys["auto"]] is False

    session[keys["issue"]] = tokyo_today()
    apply_date_widget_defaults(session, draft, overwrite=False)
    assert session[keys["issue"]] == tokyo_today()

    apply_date_widget_defaults(session, draft, overwrite=True)
    assert session[keys["issue"]] == date(2026, 9, 26)
    assert session[keys["valid"]] == date(2026, 10, 31)


def test_auto_on_syncs_valid_until_one_calendar_month():
    keys = date_widget_keys("ihi-photon-draft")
    session = {
        keys["issue"]: date(2026, 9, 27),
        keys["valid"]: date(2026, 10, 31),
        keys["auto"]: True,
    }

    sync_auto_valid_until(session, "ihi-photon-draft")

    assert session[keys["valid"]] == date(2026, 10, 27)


def test_auto_off_keeps_manual_valid_until():
    keys = date_widget_keys("ihi-photon-draft")
    session = {
        keys["issue"]: date(2026, 11, 1),
        keys["valid"]: date(2026, 10, 31),
        keys["auto"]: False,
    }

    sync_auto_valid_until(session, "ihi-photon-draft")

    assert session[keys["valid"]] == date(2026, 10, 31)


def test_auto_reenabled_resyncs_valid_until():
    keys = date_widget_keys("ihi-photon-draft")
    session = {
        keys["issue"]: date(2026, 11, 1),
        keys["valid"]: date(2026, 10, 31),
        keys["auto"]: True,
    }

    sync_auto_valid_until(session, "ihi-photon-draft")

    assert session[keys["valid"]] == date(2026, 12, 1)


def test_date_widget_keys_are_not_assigned_after_instantiate():
    import ui.quote_control as quote_control

    assert not hasattr(quote_control, "_sync_date_widgets_from_draft")
    source = inspect.getsource(quote_control._render_quote_date_inputs)
    after_first_widget = source.split("st.checkbox", 1)[1]
    assert "st.session_state[keys[\"issue\"]] =" not in after_first_widget
    assert "st.session_state[keys[\"valid\"]] =" not in after_first_widget
    assert "apply_date_widget_defaults" not in after_first_widget
    assert "_init_date_widget_state" not in after_first_widget
