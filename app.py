from pathlib import Path
import json
import os

from dotenv import load_dotenv
import streamlit as st

from ui.home import render_home
from ui.navigation import PAGE_QUOTE_CONTROL, PAGE_TECHNICAL_CASE, get_current_page, init_navigation
from ui.quote_control import render_quote_control
from ui.technical_case import render_technical_case
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
        layout="wide",
    )
    apply_light_theme()
    render_brand_header()
    init_navigation()

    current_page = get_current_page()
    if current_page == PAGE_TECHNICAL_CASE:
        render_technical_case(texts)
    elif current_page == PAGE_QUOTE_CONTROL:
        render_quote_control(texts)
    else:
        render_home(texts)


if __name__ == "__main__":
    main()
