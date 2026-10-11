from pathlib import Path
import json
import os

from dotenv import load_dotenv
import streamlit as st

from ui.activity_ledger import render_activity_ledger
from ui.auth import render_identity, require_login
from ui.conflict import render_conflict_banner
from ui.home import render_home
from ui.navigation import (
    PAGE_ACTIVITY_LEDGER,
    PAGE_PRICE_MASTER,
    PAGE_QUOTE_CONTROL,
    PAGE_TECHNICAL_CASE,
    get_current_page,
    init_navigation,
    render_dashboard_sidebar,
    restore_navigation_state,
)
from ui.quote_control import render_price_master_admin, render_quote_control
from ui.technical_case import render_technical_case
from ui.styles import page_icon_value
from ui.theme import apply_light_theme, render_brand_header

load_dotenv()

LOCALES_DIR = Path(__file__).parent / "locales"
DEFAULT_LANGUAGE = "ja"


def load_texts(language: str) -> dict:
    locale_path = LOCALES_DIR / f"{language}.json"
    if not locale_path.exists():
        locale_path = LOCALES_DIR / f"{DEFAULT_LANGUAGE}.json"

    with locale_path.open(encoding="utf-8") as file:
        return json.load(file)


def main() -> None:
    language = os.getenv("APP_LANGUAGE", DEFAULT_LANGUAGE)
    texts = load_texts(language)

    st.set_page_config(
        page_title=texts["app_title"],
        page_icon=page_icon_value(),
        layout="wide",
        initial_sidebar_state="expanded",
    )
    apply_light_theme()
    if not require_login():
        return
    init_navigation()
    current_page = get_current_page()
    restore_navigation_state(st.session_state, current_page)
    render_brand_header()
    render_conflict_banner()

    if current_page == PAGE_TECHNICAL_CASE:
        render_technical_case(texts)
    elif current_page == PAGE_QUOTE_CONTROL:
        render_quote_control(texts)
    elif current_page == PAGE_PRICE_MASTER:
        render_price_master_admin(texts)
    elif current_page == PAGE_ACTIVITY_LEDGER:
        render_activity_ledger(texts)
    else:
        render_home(texts)
    render_dashboard_sidebar(texts, current_page)
    render_identity()


if __name__ == "__main__":
    main()
