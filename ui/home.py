import streamlit as st

from ui.navigation import PAGE_QUOTE_CONTROL, PAGE_TECHNICAL_CASE, set_current_page


def render_home(texts: dict) -> None:
    technical_case = texts["agents"]["technical_case"]
    quote_control = texts["agents"]["quote_control"]

    st.title(texts["app_title"])
    st.write(texts["app_description"])
    st.divider()
    st.subheader(texts["menu_label"])

    left_column, right_column = st.columns(2)

    with left_column:
        if st.button(
            technical_case["name"],
            key="open_technical_case",
            type="primary",
            use_container_width=True,
        ):
            set_current_page(PAGE_TECHNICAL_CASE)
            st.rerun()
        st.write(technical_case["description"])

    with right_column:
        if st.button(
            quote_control["name"],
            key="open_quote_control",
            use_container_width=True,
        ):
            set_current_page(PAGE_QUOTE_CONTROL)
            st.rerun()
        st.write(quote_control["description"])
        st.caption(texts["pages"]["quote_control"]["internal_name"])
