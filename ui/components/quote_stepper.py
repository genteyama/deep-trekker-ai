from ui.components.process_stepper import ProcessStepView, render_process_stepper
from ui.quote_steps import (
    QUOTE_STEP_IDS,
    STEP_KEYS,
    normalize_quote_step,
    step_button_key,
    step_is_complete,
    step_marker,
    warning_count,
)
from ui.work_status import INFO_COMPLETE, INFO_IN_PROGRESS, INFO_NOT_STARTED, INFO_REVIEW_REQUIRED


def render_quote_stepper(page: dict, current: int, draft, snapshot, validation) -> int:
    workspace = page["workspace"]
    selected = normalize_quote_step(current)
    views = []
    for step in QUOTE_STEP_IDS:
        complete = step_is_complete(step, draft, snapshot, validation)
        marker = step_marker(step, selected, draft, snapshot, validation)
        title = workspace[f"step_{STEP_KEYS[step]}"]
        if step == selected and not complete:
            status = INFO_IN_PROGRESS
            status_label = workspace.get("step_current", "現在")
        elif complete:
            status = INFO_COMPLETE
            status_label = workspace.get("status_complete", "完了")
        else:
            status = INFO_NOT_STARTED
            status_label = workspace.get("step_todo", "未完了")
        if step == selected and workspace.get("status_review") and not complete:
            if warning_count(draft):
                status = INFO_REVIEW_REQUIRED
                status_label = workspace.get("status_review", "要確認")
        views.append(
            ProcessStepView(
                step=step,
                title=title,
                status=status,
                status_label=status_label,
                is_current=step == selected,
                button_label=f"{marker} {step} {title}",
            )
        )
    return render_process_stepper(
        views,
        selected=selected,
        button_key_fn=step_button_key,
        current_label=workspace.get("step_current", "現在"),
    )
