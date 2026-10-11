from repositories.sqlite_quote_repository import SqliteQuoteRepository
from repositories.sqlite_technical_case_repository import SqliteTechnicalCaseRepository
from tests.test_app_pages import _start_app
from tests.test_quote_approval import _ready_photon
from ui import navigation
from ui.navigation import (
    PAGE_ACTIVITY_LEDGER,
    PAGE_HOME,
    PAGE_QUOTE_CONTROL,
    PAGE_TECHNICAL_CASE,
    SESSION_CURRENT_PAGE,
    SESSION_NAVIGATION_RESTORE_PAGE,
    SESSION_NAVIGATION_STASH,
    restore_navigation_state,
    stash_navigation_state,
)
from ui.quote_persistence import manual_price_widget_key, maybe_autosave
from ui.quote_steps import SESSION_QUOTE_STEP
from ui.technical_case_steps import SESSION_CASE_STEP


def _visible(at) -> str:
    return "\n".join(
        item.value
        for root in (at, at.sidebar)
        for element in ("text", "markdown", "caption", "error")
        for item in getattr(root, element, [])
    )


class _FakeStreamlit:
    def __init__(self, session):
        self.session_state = session
        self.errors = []
        self.reruns = 0

    def error(self, message):
        self.errors.append(message)

    def rerun(self):
        self.reruns += 1


def test_global_sidebar_has_four_items_and_active_home():
    at = _start_app()
    keys = (
        "sidebar_nav_home",
        "sidebar_nav_technical",
        "sidebar_nav_quote",
        "sidebar_nav_activity",
    )
    assert all(at.button(key=key).disabled is False for key in keys)
    assert at.button(key="sidebar_nav_home").proto.type == "primary"
    assert all(at.button(key=key).proto.type == "secondary" for key in keys[1:])


def test_global_sidebar_opens_each_page_and_returns_home():
    destinations = (
        ("sidebar_nav_technical", PAGE_TECHNICAL_CASE),
        ("sidebar_nav_quote", PAGE_QUOTE_CONTROL),
        ("sidebar_nav_activity", PAGE_ACTIVITY_LEDGER),
    )
    for button_key, expected_page in destinations:
        at = _start_app()
        at.button(key=button_key).click().run()
        assert at.session_state[SESSION_CURRENT_PAGE] == expected_page

    at = _start_app()
    at.button(key="sidebar_nav_technical").click().run()
    at.button(key="sidebar_nav_home").click().run()
    assert at.session_state[SESSION_CURRENT_PAGE] == PAGE_HOME


def test_quote_deep_location_and_direct_step_navigation():
    at = _start_app()
    at.button(key="sidebar_nav_quote").click().run()
    at.button(key="sidebar_quote_step_2").click().run()
    assert at.session_state[SESSION_QUOTE_STEP] == 2
    assert "› 2. 原価・標準売価" in _visible(at)

    at = _start_app()
    at.button(key="sidebar_nav_quote").click().run()
    at.button(key="sidebar_quote_step_5").click().run()
    assert at.session_state[SESSION_QUOTE_STEP] == 5


def test_technical_deep_location_and_direct_step_navigation():
    at = _start_app()
    at.button(key="sidebar_nav_technical").click().run()
    at.button(key="sidebar_technical_step_4").click().run()
    assert at.session_state[SESSION_CASE_STEP] == 4
    assert "› 4. メーカー確認" in _visible(at)


def test_technical_navigation_stash_restores_inputs_without_database_write():
    repo = SqliteTechnicalCaseRepository()
    session = {
        "input_customer_inquiry": "管内点検について相談",
        "input_case_name": "未保存案件",
        "input_customer_name": "テスト顧客",
        "input_end_user_name": "エンドユーザー",
        "input_manufacturer_response": "回答途中",
        SESSION_CASE_STEP: 4,
    }

    stash_navigation_state(session, PAGE_TECHNICAL_CASE)
    for key in tuple(session[SESSION_NAVIGATION_STASH][PAGE_TECHNICAL_CASE]):
        session.pop(key, None)
    restore_navigation_state(session, PAGE_TECHNICAL_CASE)

    assert session["input_customer_inquiry"] == "管内点検について相談"
    assert session["input_case_name"] == "未保存案件"
    assert session["input_customer_name"] == "テスト顧客"
    assert session[SESSION_CASE_STEP] == 4
    assert repo.list_recent_cases(limit=20) == []


def test_requested_page_restore_replaces_stale_widget_defaults_once():
    session = {
        SESSION_NAVIGATION_STASH: {
            PAGE_TECHNICAL_CASE: {"input_case_name": "未保存案件"},
        },
        SESSION_NAVIGATION_RESTORE_PAGE: PAGE_TECHNICAL_CASE,
        "input_case_name": "",
    }

    restore_navigation_state(session, PAGE_TECHNICAL_CASE)

    assert session["input_case_name"] == "未保存案件"
    assert SESSION_NAVIGATION_RESTORE_PAGE not in session


def test_quote_pre_draft_navigation_stash_restores_user_input():
    session = {
        "quote_new_exchange_rate": "165",
        "quote_new_exchange_rate_changed": True,
        "spectra_quote_customer": "Customer",
        "spectra_quote_title": "SPECTRA案件",
        "spectra_quote_sku": "SPECTRA0001",
        "spectra_quote_quantity": 2,
        "spectra_quote_international_shipping": "2500",
        "spectra_quote_domestic_shipping": "0",
    }

    stash_navigation_state(session, PAGE_QUOTE_CONTROL)
    for key in tuple(session[SESSION_NAVIGATION_STASH][PAGE_QUOTE_CONTROL]):
        session.pop(key, None)
    restore_navigation_state(session, PAGE_QUOTE_CONTROL)

    assert session["spectra_quote_customer"] == "Customer"
    assert session["spectra_quote_title"] == "SPECTRA案件"
    assert session["spectra_quote_sku"] == "SPECTRA0001"
    assert session["spectra_quote_quantity"] == 2


def test_quote_pending_input_is_autosaved_before_page_navigation(monkeypatch):
    draft = _ready_photon()
    line = draft.configuration_lines[0]
    session = {
        SESSION_CURRENT_PAGE: PAGE_QUOTE_CONTROL,
        SESSION_QUOTE_STEP: 2,
        manual_price_widget_key(line.line_id): "3540001",
    }
    repo = SqliteQuoteRepository()
    maybe_autosave(repo, draft, session)
    fake_st = _FakeStreamlit(session)
    monkeypatch.setattr(navigation, "st", fake_st)

    navigation._request_page_navigation({}, PAGE_QUOTE_CONTROL, PAGE_HOME)

    loaded = repo.get_draft(draft.quote_draft_id, draft.quote_version)
    assert loaded.ui_state["pending_final_prices"][line.line_id] == "3540001"
    assert session[SESSION_CURRENT_PAGE] == PAGE_HOME
    assert fake_st.reruns == 1


def test_quote_save_error_and_conflict_block_navigation(monkeypatch):
    for blocked_state in (
        {"quote_save_error": "save failed"},
        {"edit_conflict": {"kind": "quote", "key": "Q-1", "version": 1}},
    ):
        session = {SESSION_CURRENT_PAGE: PAGE_QUOTE_CONTROL, **blocked_state}
        fake_st = _FakeStreamlit(session)
        monkeypatch.setattr(navigation, "st", fake_st)

        navigation._request_page_navigation({}, PAGE_QUOTE_CONTROL, PAGE_HOME)

        assert session[SESSION_CURRENT_PAGE] == PAGE_QUOTE_CONTROL
        assert fake_st.reruns == 0
        assert fake_st.errors
