import streamlit as st

from ui.quote_steps import QUOTE_STEP_IDS, normalize_quote_step


def render_quote_action_bar(page: dict, current: int, *, can_save: bool = False) -> tuple[int, bool]:
    workspace = page["workspace"]
    selected = normalize_quote_step(current)
    save_clicked = False
    left, middle, right = st.columns([1, 1, 1])
    with left:
        if selected > QUOTE_STEP_IDS[0] and st.button(workspace["prev_step"], key="quote_step_prev", type="secondary"):
            selected -= 1
    with middle:
        if can_save and st.button(workspace.get("save_draft_button", "下書き保存"), key="save_quote_draft", type="primary"):
            save_clicked = True
    with right:
        if selected < QUOTE_STEP_IDS[-1] and st.button(workspace["next_step"], key="quote_step_next", type="secondary"):
            selected += 1
    return selected, save_clicked
