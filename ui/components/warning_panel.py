import streamlit as st

from ui.quote_steps import unresolved_required_lines


def render_warning_panel(page: dict, draft) -> None:
    if draft is None:
        return
    workspace = page["workspace"]
    unresolved = unresolved_required_lines(draft)
    if unresolved:
        names = ", ".join(line.manufacturer_sku or line.line_id for line in unresolved)
        st.error(f"{workspace['unresolved_dependency']} ({names})")
    if draft.warnings:
        st.warning("\n".join(draft.warnings))


def render_validation_warnings(page: dict, validation) -> None:
    if validation is None:
        return
    if validation.critical_warnings:
        st.error("\n".join(validation.critical_warnings))
    if validation.regular_warnings:
        st.warning("\n".join(validation.regular_warnings))
