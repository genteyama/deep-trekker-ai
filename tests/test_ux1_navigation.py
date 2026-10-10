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


def test_quick_view_toggle_labels_and_independent_case_state():
    _save_case("CASE-A", "Alpha Case")
    _save_case("CASE-B", "Beta Case")
    at = _start_app()

    button_a = at.button(key="home_quick_technical_CASE-A")
    button_b = at.button(key="home_quick_technical_CASE-B")
    assert button_a.label == "ステータスを確認 ▼"
    assert button_b.label == "ステータスを確認 ▼"
    assert "案件ステータス" not in _visible(at)

    button_a.click().run()
    assert at.button(key="home_quick_technical_CASE-A").label == "ステータスを閉じる ▲"
    assert at.button(key="home_quick_technical_CASE-B").label == "ステータスを確認 ▼"
    visible = _visible(at)
    assert "案件ステータス" in visible
    assert "Alpha Case" in visible
    assert "Beta Case" in visible
    assert at.session_state["home_quick_technical_CASE-A_open"] is True
    assert "home_quick_technical_CASE-B_open" not in at.session_state

    at.button(key="home_quick_technical_CASE-A").click().run()
    assert at.button(key="home_quick_technical_CASE-A").label == "ステータスを確認 ▼"
    assert "案件ステータス" not in _visible(at)
    assert at.session_state["home_quick_technical_CASE-A_open"] is False


def test_sidebar_current_location_is_read_only():
    at = _start_app()
    home = _visible(at)
    assert "現在地" in home
    assert "HOME" in home
    assert "› 営業・技術問い合わせAI" not in home
    assert at.session_state["current_page"] == PAGE_HOME

    at.button(key="open_technical_case").click().run()
    technical = _visible(at)
    assert "現在地" in technical
    assert "HOME" in technical
    assert "› 営業・技術問い合わせAI" in technical
    assert at.session_state["current_page"] == PAGE_TECHNICAL_CASE

    at.button(key="back_to_home").click().run()
    # AppTest can keep the previous sidebar node until the settled rerun.
    at.run()
    assert at.session_state["current_page"] == PAGE_HOME
    assert "› 営業・技術問い合わせAI" not in _visible(at)

    at.button(key="open_quote_control").click().run()
    assert "› 見積・価格管理AI" in _visible(at)
    assert at.session_state["current_page"] == PAGE_QUOTE_CONTROL

    at.button(key="back_to_home").click().run()
    at.button(key="open_activity_ledger").click().run()
    assert "› 履歴・活動台帳" in _visible(at)
    assert at.session_state["current_page"] == PAGE_ACTIVITY_LEDGER
