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
