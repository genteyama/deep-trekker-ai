from typing import Optional

import streamlit as st

PAGE_HOME = "home"
PAGE_TECHNICAL_CASE = "technical_case"
PAGE_QUOTE_CONTROL = "quote_control"
PAGE_ACTIVITY_LEDGER = "activity_ledger"
SESSION_CURRENT_PAGE = "current_page"
SESSION_NAVIGATION_STASH = "navigation_state_stash"
SESSION_NAVIGATION_RESTORE_PAGE = "navigation_restore_page"

_TECHNICAL_STASH_KEYS = (
    "input_customer_inquiry",
    "input_case_name",
    "input_customer_name",
    "input_end_user_name",
    "input_manufacturer_response",
    "technical_case_step",
)
_QUOTE_PRE_DRAFT_STASH_KEYS = (
    "quote_new_exchange_rate",
    "quote_new_exchange_rate_changed",
    "spectra_quote_customer",
    "spectra_quote_title",
    "spectra_quote_sku",
    "spectra_quote_quantity",
    "spectra_quote_international_shipping",
    "spectra_quote_domestic_shipping",
)


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
_PAGE_NAV_KEYS = (
    (PAGE_HOME, "home", "HOME", "sidebar_nav_home"),
    (PAGE_TECHNICAL_CASE, "technical_case", "営業・技術問い合わせ", "sidebar_nav_technical"),
    (PAGE_QUOTE_CONTROL, "quote_control", "見積・価格管理", "sidebar_nav_quote"),
    (PAGE_ACTIVITY_LEDGER, "activity_ledger", "履歴・活動台帳", "sidebar_nav_activity"),
)


def stash_navigation_state(session, page: str) -> None:
    keys = _TECHNICAL_STASH_KEYS if page == PAGE_TECHNICAL_CASE else _QUOTE_PRE_DRAFT_STASH_KEYS
    if page not in {PAGE_TECHNICAL_CASE, PAGE_QUOTE_CONTROL}:
        return
    stored = dict(session.get(SESSION_NAVIGATION_STASH) or {})
    page_state = dict(stored.get(page) or {})
    for key in keys:
        if key in session:
            page_state[key] = session[key]
    stored[page] = page_state
    session[SESSION_NAVIGATION_STASH] = stored


def restore_navigation_state(session, page: str) -> None:
    stored = session.get(SESSION_NAVIGATION_STASH) or {}
    restore_requested = session.get(SESSION_NAVIGATION_RESTORE_PAGE) == page
    for key, value in (stored.get(page) or {}).items():
        if restore_requested or key not in session:
            session[key] = value
    if restore_requested:
        session.pop(SESSION_NAVIGATION_RESTORE_PAGE, None)


def quote_navigation_blocked(session) -> bool:
    from ui.quote_persistence import SESSION_SAVE_ERROR

    if session.get(SESSION_SAVE_ERROR):
        return True
    conflict = session.get("edit_conflict")
    return bool(conflict and conflict.get("kind") == "quote")


def current_location_lines(texts: dict, page: Optional[str] = None) -> list[str]:
    location = texts.get("location", {})
    home = location.get("home", "HOME")
    current_page = page or get_current_page()
    page_key = _PAGE_TEXT_KEYS.get(current_page)
    if page_key is None:
        return [home]
    title = location.get("pages", {}).get(page_key) or page_key
    lines = [home, title]
    if current_page == PAGE_QUOTE_CONTROL:
        from ui.quote_steps import SESSION_QUOTE_STEP, STEP_KEYS, normalize_quote_step

        step = normalize_quote_step(st.session_state.get(SESSION_QUOTE_STEP, 1))
        workspace = texts.get("pages", {}).get("quote_control", {}).get("workspace", {})
        label = workspace.get(f"step_{STEP_KEYS[step]}", STEP_KEYS[step])
        lines.append(f"{step}. {label}")
    elif current_page == PAGE_TECHNICAL_CASE:
        from ui.technical_case_steps import SESSION_CASE_STEP, normalize_case_step, step_title

        step = normalize_case_step(st.session_state.get(SESSION_CASE_STEP, 1))
        labels = texts.get("pages", {}).get("technical_case", {}).get("workflow", {})
        lines.append(f"{step}. {step_title(step, labels)}")
    return lines


def _navigation_error(texts: dict) -> None:
    navigation = texts.get("navigation", {})
    st.error(navigation.get("save_blocked", "保存に問題があるため移動できません。内容を確認してください。"))


def _request_page_navigation(texts: dict, current_page: str, target_page: str) -> None:
    if target_page == current_page:
        return
    if current_page == PAGE_QUOTE_CONTROL and quote_navigation_blocked(st.session_state):
        _navigation_error(texts)
        return
    stash_navigation_state(st.session_state, current_page)
    st.session_state[SESSION_NAVIGATION_RESTORE_PAGE] = target_page
    set_current_page(target_page)
    st.rerun()


def _render_current_location(texts: dict, current_page: str) -> None:
    location = texts.get("location", {})
    lines = current_location_lines(texts, current_page)
    st.caption(location.get("label", "現在地"))
    if current_page == PAGE_HOME:
        st.markdown(lines[0])
    elif st.button(lines[0], key="sidebar_breadcrumb_home", type="secondary", use_container_width=True):
        _request_page_navigation(texts, current_page, PAGE_HOME)
    for line in lines[1:]:
        st.markdown(f"{location.get('separator', '›')} {line}")


def _request_workflow_step(texts: dict, current_page: str, session_key: str, step: int) -> None:
    if current_page == PAGE_QUOTE_CONTROL and quote_navigation_blocked(st.session_state):
        _navigation_error(texts)
        return
    stash_navigation_state(st.session_state, current_page)
    st.session_state[session_key] = step
    st.rerun()


def _render_quote_workflow(texts: dict, current_page: str) -> None:
    from ui.quote_steps import QUOTE_STEP_IDS, SESSION_QUOTE_STEP, STEP_KEYS, normalize_quote_step

    navigation = texts.get("navigation", {})
    workspace = texts.get("pages", {}).get("quote_control", {}).get("workspace", {})
    current = normalize_quote_step(st.session_state.get(SESSION_QUOTE_STEP, 1))
    st.caption(navigation.get("quote_workflow", "見積工程"))
    for step in QUOTE_STEP_IDS:
        label = f"{step}. {workspace.get(f'step_{STEP_KEYS[step]}', STEP_KEYS[step])}"
        if st.button(
            label,
            key=f"sidebar_quote_step_{step}",
            type="primary" if step == current else "secondary",
            use_container_width=True,
        ):
            if step != current:
                _request_workflow_step(texts, current_page, SESSION_QUOTE_STEP, step)


def _render_technical_workflow(texts: dict, current_page: str) -> None:
    from ui.technical_case_steps import (
        SESSION_CASE_STEP,
        TECHNICAL_STEP_IDS,
        normalize_case_step,
        step_title,
    )

    navigation = texts.get("navigation", {})
    labels = texts.get("pages", {}).get("technical_case", {}).get("workflow", {})
    current = normalize_case_step(st.session_state.get(SESSION_CASE_STEP, 1))
    st.caption(navigation.get("technical_workflow", "工程"))
    for step in TECHNICAL_STEP_IDS:
        if st.button(
            f"{step}. {step_title(step, labels)}",
            key=f"sidebar_technical_step_{step}",
            type="primary" if step == current else "secondary",
            use_container_width=True,
        ):
            if step != current:
                _request_workflow_step(texts, current_page, SESSION_CASE_STEP, step)


def render_dashboard_sidebar(texts: dict, current_page: str) -> None:
    navigation = texts.get("navigation", {})
    labels = navigation.get("pages", {})
    with st.sidebar:
        st.markdown(f"### {navigation.get('title', 'Deep Trekker AI')}")
        st.caption(navigation.get("main_menu", "MAIN MENU"))
        for page, label_key, fallback, button_key in _PAGE_NAV_KEYS:
            if st.button(
                labels.get(label_key, fallback),
                key=button_key,
                type="primary" if page == current_page else "secondary",
                use_container_width=True,
            ):
                _request_page_navigation(texts, current_page, page)
        st.divider()
        _render_current_location(texts, current_page)
        if current_page == PAGE_QUOTE_CONTROL:
            st.divider()
            _render_quote_workflow(texts, current_page)
        elif current_page == PAGE_TECHNICAL_CASE:
            st.divider()
            _render_technical_workflow(texts, current_page)
        st.divider()
