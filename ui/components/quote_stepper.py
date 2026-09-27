import streamlit as st

from ui.quote_steps import (
    QUOTE_STEP_IDS,
    STEP_KEYS,
    normalize_quote_step,
    step_button_key,
    step_marker,
)


def render_quote_stepper(page: dict, current: int, draft, snapshot, validation) -> int:
    workspace = page["workspace"]
    selected = normalize_quote_step(current)
    columns = st.columns(len(QUOTE_STEP_IDS))
    for step, column in zip(QUOTE_STEP_IDS, columns):
        marker = step_marker(step, selected, draft, snapshot, validation)
        label = workspace[f"step_{STEP_KEYS[step]}"]
        button_label = f"{marker} {step} {label}"
        with column:
            if st.button(
                button_label,
                key=step_button_key(step),
                use_container_width=True,
                type="primary" if step == selected else "secondary",
            ):
                selected = step
    return selected
