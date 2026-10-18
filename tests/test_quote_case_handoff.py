from models import CaseLifecycleStatus, TechnicalCaseRecord, TechnicalCaseStatus
from repositories.sqlite_quote_repository import SqliteQuoteRepository
from repositories.sqlite_technical_case_repository import SqliteTechnicalCaseRepository
from tests.test_app_pages import _start_app
from tests.test_price_master_ui import _drop_stale_widgets, _open_quote_page
from tests.test_quote_general_ui import _activate, _line_id
from ui.navigation import PAGE_QUOTE_CONTROL, restore_navigation_state, stash_navigation_state
from ui.quote_handoff import (
    SESSION_QUOTE_HANDOFF_CASE_ID,
    SESSION_QUOTE_HANDOFF_CUSTOMER,
    SESSION_QUOTE_HANDOFF_PENDING,
    SESSION_QUOTE_HANDOFF_PRODUCTS,
    SESSION_QUOTE_HANDOFF_TITLE,
    SOURCE_CASE_ID,
    SOURCE_PRODUCTS,
    apply_pending_quote_handoff,
    clear_quote_handoff_source,
    handoff_allowed,
    stage_quote_handoff,
)

_STAGED_HANDOFF_KEYS = (
    SESSION_QUOTE_HANDOFF_PENDING,
    SESSION_QUOTE_HANDOFF_CASE_ID,
    SESSION_QUOTE_HANDOFF_CUSTOMER,
    SESSION_QUOTE_HANDOFF_TITLE,
    SESSION_QUOTE_HANDOFF_PRODUCTS,
)


def _visible(at) -> str:
    return " ".join(
        [item.value for item in at.text]
        + [item.value for item in at.markdown]
        + [item.value for item in at.caption]
        + [item.label for item in at.button]
        + [item.value for item in at.error]
    )


def _keep_latest_widgets(at) -> None:
    """AppTest keeps widgets from the run before st.rerun(). Keep the latest copy."""

    def walk(block) -> None:
        children = getattr(block, "children", None)
        if not children:
            return
        positions = {}
        for idx, child in list(children.items()):
            key = getattr(child, "key", None)
            if key:
                positions.setdefault(key, []).append(idx)
            walk(child)
        for indexes in positions.values():
            for idx in indexes[:-1]:
                del children[idx]

    walk(at._tree)


def _has_button(at, key: str) -> bool:
    return any(getattr(item, "key", None) == key for item in at.button)


def _save_case(case_id="CASE-100", **overrides):
    payload = dict(
        case_id=case_id,
        customer_name="株式会社ABC",
        case_title="設備調査",
        requested_products=["MAG", "PipeTrekker"],
        created_at="2026-10-11T06:00:00+00:00",
        updated_at="2026-10-11T06:00:00+00:00",
        status=TechnicalCaseStatus.DRAFT.value,
    )
    payload.update(overrides)
    record = TechnicalCaseRecord(**payload)
    SqliteTechnicalCaseRepository().save_case(record)
    return record


def _open_case(case_id: str):
    at = _start_app()
    at.button(key="sidebar_nav_technical").click().run()
    at.session_state["technical_case_saved_id"] = case_id
    _drop_stale_widgets(at)
    at.run()
    assert not at.exception
    return at


def _handoff(at):
    at.button(key="create_quote_from_technical_case").click().run()
    _drop_stale_widgets(at)
    assert not at.exception
    return at


def test_saved_active_case_shows_handoff_button():
    _save_case()
    at = _open_case("CASE-100")

    assert _has_button(at, "create_quote_from_technical_case")
    assert "この案件から見積を作成" in _visible(at)
    assert "保存済みの案件情報を見積へ引き継ぎます。" in _visible(at)
    assert "関連見積" in _visible(at)


def test_unsaved_case_has_caption_without_button():
    at = _start_app()
    at.button(key="sidebar_nav_technical").click().run()

    assert not _has_button(at, "create_quote_from_technical_case")
    assert "案件を保存すると見積を作成できます" in _visible(at)
    assert len(SqliteTechnicalCaseRepository().list_recent_cases(limit=50)) == 0


def test_closed_archived_and_trash_cases_hide_the_button():
    _save_case("CASE-CLOSED", case_lifecycle_status=CaseLifecycleStatus.CLOSED)
    _save_case("CASE-ARCHIVED", archived_at="2026-10-11T00:00:00+00:00")
    _save_case("CASE-TRASH", deleted_at="2026-10-11T00:00:00+00:00")

    for case_id in ("CASE-CLOSED", "CASE-ARCHIVED", "CASE-TRASH"):
        at = _open_case(case_id)
        assert not _has_button(at, "create_quote_from_technical_case")
        assert "案件を保存すると見積を作成できます" not in _visible(at)


def test_handoff_click_navigates_without_a_database_write():
    _save_case()
    cases_before = len(SqliteTechnicalCaseRepository().list_recent_cases(limit=50))
    quotes_before = len(SqliteQuoteRepository().list_recent_drafts())
    at = _handoff(_open_case("CASE-100"))

    assert at.session_state["current_page"] == PAGE_QUOTE_CONTROL
    assert "一般見積を作成" in _visible(at)
    assert len(SqliteTechnicalCaseRepository().list_recent_cases(limit=50)) == cases_before
    assert len(SqliteQuoteRepository().list_recent_drafts()) == quotes_before
    assert "quote_draft" not in at.session_state or at.session_state["quote_draft"] is None


def test_pending_handoff_overwrites_an_older_quote_pre_draft():
    _save_case()
    at = _start_app()
    at.button(key="sidebar_nav_quote").click().run()
    line_id = _line_id(at)
    at.text_input(key="generic_quote_customer").set_value("古い顧客")
    at.text_input(key="generic_quote_title").set_value("古い案件")
    at.text_input(key=f"generic_quote_sku_{line_id}").set_value("DT-100")
    at.button(key="sidebar_nav_home").click().run()
    _drop_stale_widgets(at)
    at.button(key="sidebar_nav_technical").click().run()
    at.session_state["technical_case_saved_id"] = "CASE-100"
    _drop_stale_widgets(at)
    at.run()
    _handoff(at)

    assert at.text_input(key="generic_quote_customer").value == "株式会社ABC"
    assert at.text_input(key="generic_quote_title").value == "設備調査"
    assert at.session_state[SOURCE_CASE_ID] == "CASE-100"
    assert at.session_state[SOURCE_PRODUCTS] == ["MAG", "PipeTrekker"]
    assert [line["sku"] for line in at.session_state["generic_quote_lines"]] == [""]
    sku_key = f"generic_quote_sku_{_line_id(at)}"
    assert at.text_input(key=sku_key).value == ""
    visible = _visible(at)
    assert "営業・技術案件から引き継ぎ" in visible
    assert "CASE-100" in visible
    assert "MAG" in visible
    assert "PipeTrekker" in visible
    assert "対象製品は営業・技術案件から引き継いだ参考情報です。" in visible


def test_apply_pending_handoff_runs_after_navigation_restore():
    session = {
        "generic_quote_customer": "古い顧客",
        "generic_quote_title": "古い案件",
        "generic_quote_lines": [{"id": "old", "sku": "DT-100", "quantity": 2}],
        "generic_quote_sku_old": "DT-100",
        "quote_draft": object(),
    }
    stash_navigation_state(session, PAGE_QUOTE_CONTROL)
    session.pop("generic_quote_customer")
    session.pop("generic_quote_title")
    session.pop("generic_quote_lines")
    record = _save_case("CASE-UNIT")
    stage_quote_handoff(session, record)
    restore_navigation_state(session, PAGE_QUOTE_CONTROL)
    assert session["generic_quote_customer"] == "古い顧客"

    apply_pending_quote_handoff(session)

    assert session["generic_quote_customer"] == "株式会社ABC"
    assert session["generic_quote_title"] == "設備調査"
    assert session[SOURCE_CASE_ID] == "CASE-UNIT"
    assert session[SOURCE_PRODUCTS] == ["MAG", "PipeTrekker"]
    assert session["generic_quote_lines"][0]["sku"] == ""
    assert "quote_draft" not in session
    assert all(key not in session for key in _STAGED_HANDOFF_KEYS)


def test_clearing_the_source_also_drops_staged_handoff_keys():
    session = {
        "generic_quote_customer": "株式会社ABC",
        "generic_quote_title": "設備調査",
        SOURCE_CASE_ID: "CASE-UNIT",
        SOURCE_PRODUCTS: ["MAG"],
        SESSION_QUOTE_HANDOFF_PENDING: True,
        SESSION_QUOTE_HANDOFF_CASE_ID: "CASE-UNIT",
        SESSION_QUOTE_HANDOFF_CUSTOMER: "株式会社ABC",
        SESSION_QUOTE_HANDOFF_TITLE: "設備調査",
        SESSION_QUOTE_HANDOFF_PRODUCTS: ["MAG"],
    }

    clear_quote_handoff_source(session)

    assert SOURCE_CASE_ID not in session
    assert SOURCE_PRODUCTS not in session
    assert all(key not in session for key in _STAGED_HANDOFF_KEYS)
    assert session["generic_quote_customer"] == "株式会社ABC"
    assert session["generic_quote_title"] == "設備調査"


def test_user_can_edit_customer_and_title_while_case_id_stays():
    _activate()
    _save_case()
    at = _handoff(_open_case("CASE-100"))
    at.text_input(key="generic_quote_customer").set_value("変更顧客")
    at.text_input(key="generic_quote_title").set_value("変更案件")
    at.text_input(key=f"generic_quote_sku_{_line_id(at)}").set_value("DT-100")
    at.button(key="generic_quote_create").click().run()
    assert not at.exception

    draft = at.session_state["quote_draft"]
    assert draft.customer == "変更顧客"
    assert draft.title == "変更案件"
    assert draft.case_id == "CASE-100"
    assert draft.configuration_lines[0].manufacturer_sku == "DT-100"
    stored = at.session_state["quote_repository"].get_draft(draft.quote_draft_id)
    assert stored.draft.case_id == "CASE-100"
    assert SOURCE_CASE_ID not in at.session_state
    assert all(key not in at.session_state for key in _STAGED_HANDOFF_KEYS)

    from agents.activity_catalog import load_related_quotes

    related = load_related_quotes(at.session_state["quote_repository"], "CASE-100")
    assert [item.case_id for item in related] == ["CASE-100"]
    _drop_stale_widgets(at)
    at.button(key="sidebar_nav_technical").click().run()
    assert "関連見積：1件" in _visible(at)


def test_navigation_before_create_keeps_handoff_and_writes_nothing():
    _save_case()
    at = _handoff(_open_case("CASE-100"))
    line_id = _line_id(at)
    at.text_input(key="generic_quote_customer").set_value("編集顧客")
    at.text_input(key=f"generic_quote_sku_{line_id}").set_value("DT-KEEP")
    at.text_input(key="generic_quote_international_shipping").set_value("12")
    at.button(key="sidebar_nav_home").click().run()
    _drop_stale_widgets(at)

    assert SqliteQuoteRepository().list_recent_drafts() == []
    at.button(key="sidebar_nav_quote").click().run()
    assert at.text_input(key="generic_quote_customer").value == "編集顧客"
    assert at.text_input(key="generic_quote_title").value == "設備調査"
    assert at.session_state[SOURCE_CASE_ID] == "CASE-100"
    assert at.session_state[SOURCE_PRODUCTS] == ["MAG", "PipeTrekker"]
    assert at.text_input(key=f"generic_quote_sku_{line_id}").value == "DT-KEEP"
    assert at.text_input(key="generic_quote_international_shipping").value == "12"
    assert "CASE-100" in _visible(at)


def test_failed_create_keeps_the_handoff():
    _activate()
    _save_case()
    at = _handoff(_open_case("CASE-100"))
    at.text_input(key=f"generic_quote_sku_{_line_id(at)}").set_value("NOT-A-SKU")
    at.button(key="generic_quote_create").click().run()

    assert "NOT-A-SKU" in _visible(at)
    assert at.session_state[SOURCE_CASE_ID] == "CASE-100"
    assert at.session_state[SOURCE_PRODUCTS] == ["MAG", "PipeTrekker"]
    assert at.text_input(key="generic_quote_customer").value == "株式会社ABC"
    assert "quote_draft" not in at.session_state or at.session_state["quote_draft"] is None
    assert SqliteQuoteRepository().list_recent_drafts() == []


def test_clearing_handoff_drops_case_id_and_keeps_the_inputs():
    _activate()
    _save_case()
    at = _handoff(_open_case("CASE-100"))
    at.button(key="clear_technical_case_quote_handoff").click().run()
    _keep_latest_widgets(at)

    assert SOURCE_CASE_ID not in at.session_state
    assert SOURCE_PRODUCTS not in at.session_state
    assert all(key not in at.session_state for key in _STAGED_HANDOFF_KEYS)
    assert "営業・技術案件から引き継ぎ" not in _visible(at)
    assert at.text_input(key="generic_quote_customer").value == "株式会社ABC"
    assert at.text_input(key="generic_quote_title").value == "設備調査"
    for item in at.text_input:
        if (item.key or "").startswith("generic_quote_sku_"):
            item.set_value("DT-100")
    at.button(key="generic_quote_create").click().run()
    errors = " ".join(item.value for item in at.error)
    assert not at.exception
    assert "quote_draft" in at.session_state, errors
    assert at.session_state["quote_draft"].case_id is None


def test_standalone_general_quote_has_no_case_handoff():
    at = _open_quote_page()

    assert "営業・技術案件から引き継ぎ" not in _visible(at)
    assert not _has_button(at, "clear_technical_case_quote_handoff")
    assert SOURCE_CASE_ID not in at.session_state
    assert _has_button(at, "spectra_quote_create")
    assert _has_button(at, "ihi_photon_draft")
    assert _has_button(at, "ihi_mag_draft")


def test_spectra_product_name_stays_on_the_general_form():
    _save_case(requested_products=["SPECTRA", "MAG"])
    at = _handoff(_open_case("CASE-100"))

    assert "一般見積を作成" in _visible(at)
    assert "SPECTRA" in _visible(at)
    assert "spectra_quote_sku" not in at.session_state or at.session_state["spectra_quote_sku"] == ""
    assert [line["sku"] for line in at.session_state["generic_quote_lines"]] == [""]
    assert _has_button(at, "spectra_quote_create")
    assert _has_button(at, "ihi_photon_draft")
    assert handoff_allowed(_save_case("CASE-ACTIVE-CHECK")) is True
    closed = _save_case("CASE-CLOSED-CHECK", case_lifecycle_status=CaseLifecycleStatus.CLOSED)
    assert handoff_allowed(closed) is False
