from tests.test_app_pages import _start_app
from ui.navigation import PAGE_PRICE_CATALOG, PAGE_QUOTE_LIST, SESSION_CURRENT_PAGE


def test_price_catalog_and_quote_list_are_primary_routes():
    at = _start_app()
    at.button(key="sidebar_nav_price_catalog").click().run()
    assert at.session_state[SESSION_CURRENT_PAGE] == PAGE_PRICE_CATALOG
    assert at.title[0].value == "価格一覧"
    assert not at.exception

    at = _start_app()
    at.button(key="sidebar_nav_quote_list").click().run()
    assert at.session_state[SESSION_CURRENT_PAGE] == PAGE_QUOTE_LIST
    assert at.title[0].value == "見積一覧"
    assert not at.exception


def test_technical_and_activity_are_not_removed():
    at = _start_app()
    assert at.button(key="sidebar_nav_technical").disabled is False
    assert at.button(key="sidebar_nav_activity").disabled is False
