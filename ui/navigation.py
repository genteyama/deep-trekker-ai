import streamlit as st

PAGE_HOME = "home"
PAGE_TECHNICAL_CASE = "technical_case"
PAGE_QUOTE_CONTROL = "quote_control"
PAGE_ACTIVITY_LEDGER = "activity_ledger"
SESSION_CURRENT_PAGE = "current_page"


def init_navigation() -> None:
    if SESSION_CURRENT_PAGE not in st.session_state:
        st.session_state[SESSION_CURRENT_PAGE] = PAGE_HOME


def get_current_page() -> str:
    return st.session_state.get(SESSION_CURRENT_PAGE, PAGE_HOME)


def set_current_page(page: str) -> None:
    st.session_state[SESSION_CURRENT_PAGE] = page


_PAGE_TEXT_KEYS = {
    PAGE_TECHNICAL_CASE: "technical_case",
    PAGE_QUOTE_CONTROL: "quote_control",
    PAGE_ACTIVITY_LEDGER: "activity_ledger",
}


def current_location_lines(texts: dict) -> list[str]:
    location = texts.get("location", {})
    home = location.get("home", "HOME")
    page_key = _PAGE_TEXT_KEYS.get(get_current_page())
    if page_key is None:
        return [home]
    title = location.get("pages", {}).get(page_key) or page_key
    return [home, title]


def render_current_location(texts: dict) -> None:
    """Read-only sidebar location. It does not change the current page."""
    location = texts.get("location", {})
    lines = current_location_lines(texts)
    with st.sidebar:
        st.divider()
        st.caption(location.get("label", "現在地"))
        st.markdown(lines[0])
        if len(lines) > 1:
            st.markdown(f"{location.get('separator', '›')} {lines[1]}")
