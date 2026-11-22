import json

from tests.test_app_pages import _start_app
from ui.navigation import PAGE_QUOTE_CONTROL, PAGE_QUOTE_LIST


def _sidebar_keys(at):
    return [item.key for item in at.sidebar.button if item.key and item.key.startswith("sidebar_nav_")]


def test_sidebar_main_menu_shows_quote_create_right_below_price_catalog():
    at = _start_app()
    keys = _sidebar_keys(at)
    main = [key for key in keys if key in {"sidebar_nav_home", "sidebar_nav_price_catalog", "sidebar_nav_quote", "sidebar_nav_quote_list"}]
    assert main == ["sidebar_nav_home", "sidebar_nav_price_catalog", "sidebar_nav_quote", "sidebar_nav_quote_list"]
    assert at.button(key="sidebar_nav_quote").label == "見積作成"
    assert not any(item.label == "見積・価格管理" for item in at.sidebar.button)
    # Price master management stays in the admin section.
    assert any(item.key == "sidebar_admin_price_master" for item in at.sidebar.button)


def test_sidebar_quote_create_opens_the_same_workspace_as_home_card():
    at = _start_app()
    at.button(key="sidebar_nav_quote").click().run()
    assert not at.exception
    assert at.session_state["current_page"] == PAGE_QUOTE_CONTROL
    from_sidebar = at.title[0].value

    at = _start_app()
    at.button(key="home_open_quote").click().run()
    assert not at.exception
    assert at.session_state["current_page"] == PAGE_QUOTE_CONTROL
    assert at.title[0].value == from_sidebar

    at.button(key="sidebar_nav_quote_list").click().run()
    assert not at.exception
    assert at.session_state["current_page"] == PAGE_QUOTE_LIST


def test_quote_create_menu_label_in_both_locales():
    with open("locales/ja.json", encoding="utf-8") as file:
        ja = json.load(file)
    with open("locales/en.json", encoding="utf-8") as file:
        en = json.load(file)
    assert ja["navigation"]["pages"]["quote_control"] == "見積作成"
    assert en["navigation"]["pages"]["quote_control"] == "Create quote"
    assert set(ja["navigation"]["pages"]) == set(en["navigation"]["pages"])
