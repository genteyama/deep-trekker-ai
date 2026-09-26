from pathlib import Path
import json
import os

from dotenv import load_dotenv
import streamlit as st

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
    technical_case = texts["agents"]["technical_case"]
    quote_control = texts["agents"]["quote_control"]

    st.set_page_config(
        page_title=texts["app_title"],
        layout="centered",
    )

    st.title(texts["app_title"])
    st.write(texts["app_description"])
    st.divider()
    st.subheader(texts["menu_label"])

    left_column, right_column = st.columns(2)

    with left_column:
        st.markdown(f"### {technical_case['name']}")
        st.write(technical_case["description"])

    with right_column:
        st.markdown(f"### {quote_control['name']}")
        st.write(quote_control["description"])


if __name__ == "__main__":
    main()
