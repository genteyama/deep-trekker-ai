from models import TechnicalCaseRecord, TechnicalCaseStatus
from repositories.sqlite_technical_case_repository import SqliteTechnicalCaseRepository
from tests.test_app_pages import _start_app
from ui.navigation import PAGE_ACTIVITY_LEDGER, PAGE_HOME, PAGE_QUOTE_CONTROL, PAGE_TECHNICAL_CASE


def _visible(at) -> str:
    roots = [at]
    sidebar = getattr(at, "sidebar", None)
    if sidebar is not None:
        roots.append(sidebar)
    parts = []
    for root in roots:
        for name in ("text", "markdown", "caption"):
            for item in getattr(root, name, []):
                parts.append(item.value)
    return "\n".join(parts)


def _save_case(case_id: str, title: str) -> None:
    SqliteTechnicalCaseRepository().save_case(
        TechnicalCaseRecord(
            case_id=case_id,
            customer_name=f"{title} Customer",
            case_title=title,
            status=TechnicalCaseStatus.DRAFT.value,
            original_inquiry="Question",
        )
    )


def test_technical_case_resumes_multiple_saved_cases_independently():
    _save_case("CASE-A", "Alpha Case")
    _save_case("CASE-B", "Beta Case")
    at = _start_app()

    at.button(key="sidebar_nav_technical").click().run()
    assert any(item.key == "resume_technical_case_CASE-A" for item in at.button)
    assert any(item.key == "resume_technical_case_CASE-B" for item in at.button)

    at.button(key="resume_technical_case_CASE-A").click().run()
    assert at.session_state["technical_case_saved_id"] == "CASE-A"

    at.button(key="resume_technical_case_CASE-B").click().run()
    assert at.session_state["technical_case_saved_id"] == "CASE-B"


def test_sidebar_current_location_remains_visible_and_home_is_clickable():
    at = _start_app()
    home = _visible(at)
    assert "現在地" in home
    assert "HOME" in home
    assert "› 営業・技術問い合わせAI" not in home
    assert at.session_state["current_page"] == PAGE_HOME

    at.button(key="sidebar_nav_technical").click().run()
    technical = _visible(at)
    assert "現在地" in technical
    assert at.button(key="sidebar_breadcrumb_home").label == "HOME"
    assert "› 営業・技術問い合わせAI" in technical
    assert "› 1. 受付" in technical
    assert at.session_state["current_page"] == PAGE_TECHNICAL_CASE

    at.button(key="sidebar_breadcrumb_home").click().run()
    assert at.session_state["current_page"] == PAGE_HOME


def test_sidebar_location_for_quote_and_activity():
    at = _start_app()
    at.button(key="sidebar_nav_quote").click().run()
    assert "› 見積・価格管理AI" in _visible(at)
    assert "› 1. 構成確認" in _visible(at)
    assert at.session_state["current_page"] == PAGE_QUOTE_CONTROL

    at = _start_app()
    at.button(key="sidebar_nav_activity").click().run()
    assert "› 履歴・活動台帳" in _visible(at)
    assert at.session_state["current_page"] == PAGE_ACTIVITY_LEDGER
