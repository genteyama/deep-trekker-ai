from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from html import escape
from typing import Callable, Optional

import streamlit as st

from ui.components.status import render_status_badge, status_badge_html
from ui.work_status import INFO_REVIEW_REQUIRED, INFO_WAITING


@dataclass
class ProcessStepView:
    step: int
    title: str
    status: str
    status_label: str
    review_count: int = 0
    is_current: bool = False
    button_label: Optional[str] = None


def _tone(status: str) -> Optional[str]:
    if status == INFO_REVIEW_REQUIRED:
        return "is-review"
    if status == INFO_WAITING:
        return "is-waiting"
    if status in {"MISSING", "NOT_STARTED", "INCOMPLETE"}:
        return "is-missing"
    return None


def render_process_stepper(
    steps: list[ProcessStepView],
    *,
    selected: int,
    button_key_fn: Callable[[int], str],
    current_label: str = "現在",
    row_sizes: Optional[tuple[int, ...]] = None,
) -> int:
    chosen = selected
    sizes = list(row_sizes or (len(steps),))
    index = 0
    for size in sizes:
        columns = st.columns(size)
        for column in columns:
            if index >= len(steps):
                break
            view = steps[index]
            index += 1
            with column:
                _render_step_card(view, current_label)
                label = view.button_label or f"{view.step} {view.title}"
                if st.button(
                    label,
                    key=button_key_fn(view.step),
                    use_container_width=True,
                    type="primary" if view.step == selected else "secondary",
                ):
                    chosen = view.step
    return chosen


def _render_step_card(view: ProcessStepView, current_label: str) -> None:
    classes = ["dt-step-card"]
    if view.is_current:
        classes.append("is-current")
    current_html = (
        f"<span class='dt-step-current-label'>{escape(current_label)}</span>" if view.is_current else ""
    )
    badge = status_badge_html(view.status_label, tone=_tone(view.status))
    st.markdown(
        f"<div class='{' '.join(classes)}'>"
        f"<div class='dt-step-card-top'>"
        f"<span class='dt-step-num'>{view.step} {escape(view.title)}</span>"
        f"{current_html}"
        f"</div>"
        f"{badge}"
        f"</div>",
        unsafe_allow_html=True,
    )


@contextmanager
def render_work_panel(title: str, badge_label: str, *, status: Optional[str] = None):
    with st.container(border=True):
        heading = st.columns([4, 1])
        heading[0].markdown(f"**{title}**")
        with heading[1]:
            render_status_badge(badge_label, status=status)
        yield
