from datetime import date

from agents.quote_approval import apply_ihi_photon_human_final_fixture
from agents.quote_dates import date_widget_keys
from models import QuoteDraftStatus
from tests.test_quote_approval import _approve, _ready_photon
from tests.test_quote_builder import _photon_draft
from ui.quote_steps import (
    QUOTE_STEP_IDS,
    SESSION_QUOTE_STEP,
    STEP_KEYS,
    build_header_summary,
    customer_facing_preview,
    customer_preview_has_internal_cost,
    normalize_quote_step,
    persist_review_key,
    restore_review_widget_state,
    save_review_widget_state,
    step_button_key,
    step_is_complete,
    step_marker,
    warning_count,
)


def test_quote_workspace_has_five_named_steps():
    assert QUOTE_STEP_IDS == (1, 2, 3, 4, 5)
    assert [STEP_KEYS[step] for step in QUOTE_STEP_IDS] == [
        "configuration",
        "costing",
        "customer",
        "review",
        "export",
    ]
    assert [step_button_key(step) for step in QUOTE_STEP_IDS] == [
        "quote_step_1",
        "quote_step_2",
        "quote_step_3",
        "quote_step_4",
        "quote_step_5",
    ]


def test_step_change_does_not_mutate_quote_draft():
    draft = _photon_draft()
    original_id = draft.quote_draft_id
    original_total = draft.total_jpy
    session = {SESSION_QUOTE_STEP: 1, "quote_draft": draft}

    session[SESSION_QUOTE_STEP] = normalize_quote_step(3)

    assert session["quote_draft"] is draft
    assert session["quote_draft"].quote_draft_id == original_id
    assert session["quote_draft"].total_jpy == original_total
    assert session[SESSION_QUOTE_STEP] == 3


def test_human_final_survives_step_change():
    draft = _photon_draft()
    apply_ihi_photon_human_final_fixture(draft)
    session = {"quote_draft": draft, SESSION_QUOTE_STEP: 4}

    session[SESSION_QUOTE_STEP] = 1
    session[SESSION_QUOTE_STEP] = 4

    assert session["quote_draft"].issue_date == "2026-09-26"
    assert session["quote_draft"].valid_until == "2026-10-31"
    assert session["quote_draft"].total_jpy == 7876000
    assert session["quote_draft"].economics_result.gross_margin_rate == draft.economics_result.gross_margin_rate


def test_date_and_confirmation_keys_are_not_cleared_by_step_change():
    draft = _photon_draft()
    keys = date_widget_keys(draft.quote_draft_id)
    session = {
        "quote_draft": draft,
        SESSION_QUOTE_STEP: 4,
        keys["issue"]: date(2026, 9, 26),
        keys["valid"]: date(2026, 10, 31),
        keys["auto"]: False,
        "confirm_configuration": True,
        "confirm_presentation": True,
    }

    save_review_widget_state(session)
    session[SESSION_QUOTE_STEP] = 2
    session.pop("confirm_configuration", None)
    session.pop("confirm_presentation", None)
    restore_review_widget_state(session)

    assert session[keys["issue"]] == date(2026, 9, 26)
    assert session[keys["valid"]] == date(2026, 10, 31)
    assert session[keys["auto"]] is False
    assert session[persist_review_key("confirm_configuration")] is True
    assert session["confirm_configuration"] is True
    assert session["confirm_presentation"] is True


def test_step_navigation_does_not_bypass_approval_validation():
    draft = _photon_draft()
    assert draft.status != QuoteDraftStatus.READY_FOR_APPROVAL
    assert step_is_complete(4, draft, snapshot=None, validation=None) is False
    assert step_is_complete(5, draft, snapshot=None, validation=None) is False
    assert step_marker(4, 4, draft) == "●"
    assert step_marker(5, 4, draft) == "○"


def test_approved_snapshot_and_totals_remain_unchanged():
    draft = _ready_photon()
    _, snapshot = _approve(draft)
    original_id = snapshot.approved_quote_snapshot_id
    original_total = snapshot.total_jpy
    original_margin = snapshot.gross_margin_rate
    original_issue = snapshot.issue_date

    assert step_is_complete(5, draft, snapshot=snapshot) is True
    assert snapshot.approved_quote_snapshot_id == original_id
    assert snapshot.total_jpy == 7876000
    assert original_total == 7876000
    assert snapshot.gross_margin_rate == original_margin
    assert abs(snapshot.gross_margin_rate - 0.29598) < 0.00001
    assert snapshot.issue_date == original_issue == "2026-09-26"
    assert snapshot.valid_until == "2026-10-31"


def test_customer_view_excludes_internal_cost_fields():
    draft = _photon_draft()
    apply_ihi_photon_human_final_fixture(draft)
    rows = customer_facing_preview(draft)

    assert rows
    assert customer_preview_has_internal_cost(rows) is False
    assert all("landed_cost_jpy" not in row for row in rows)
    assert all("dealer_price_usd" not in row for row in rows)
    assert sum(row["amount_jpy"] or 0 for row in rows) == 7160000


def test_header_summary_uses_snapshot_totals():
    draft = _ready_photon()
    _, snapshot = _approve(draft)
    summary = build_header_summary(draft, snapshot)

    assert summary["customer"] == snapshot.customer
    assert summary["total"] == 7876000
    assert summary["subtotal"] == 7160000
    assert abs(summary["gross_margin"] - 0.29598) < 0.00001
    assert warning_count(draft) >= 0
