import streamlit as st

from ui.quote_steps import QUOTE_STEP_IDS, normalize_quote_step


def render_quote_action_bar(page: dict, current: int) -> int:
    workspace = page["workspace"]
    selected = normalize_quote_step(current)
    left, _, right = st.columns([1, 2, 1])
    with left:
        if selected > QUOTE_STEP_IDS[0] and st.button(workspace["prev_step"], key="quote_step_prev"):
            selected -= 1
    with right:
        if selected < QUOTE_STEP_IDS[-1] and st.button(workspace["next_step"], key="quote_step_next"):
            selected += 1
    return selected
