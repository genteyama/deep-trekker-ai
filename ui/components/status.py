from __future__ import annotations

from html import escape
from typing import Optional

import streamlit as st

from ui.components.portal import format_portal_datetime
from ui.work_status import INFO_LABELS, INFO_REVIEW_REQUIRED, INFO_WAITING, WorkSummary


def status_badge_html(label: str, *, tone: Optional[str] = None) -> str:
    css = "dt-status-badge"
    if tone:
        css = f"{css} {tone}"
    return f"<span class='{css}'>{escape(label)}</span>"


def render_status_badge(label: str, *, status: Optional[str] = None) -> None:
    tone = None
    if status in {INFO_REVIEW_REQUIRED, INFO_WAITING}:
        tone = "is-review" if status == INFO_REVIEW_REQUIRED else "is-waiting"
    elif status in {"MISSING", "NOT_STARTED"}:
        tone = "is-missing"
    st.markdown(status_badge_html(label, tone=tone), unsafe_allow_html=True)


def progress_text(summary: WorkSummary, labels: Optional[dict] = None) -> str:
    texts = labels or {}
    return (
        f"{texts.get('progress_label', '進捗')}：{summary.completed} / {summary.total}  "
        f"{texts.get('review_label', '要確認')}：{summary.review_required}{texts.get('review_unit', '件')}"
    )


def render_progress_summary(summary: WorkSummary, labels: Optional[dict] = None) -> None:
    st.markdown(f"<div class='dt-progress'>{escape(progress_text(summary, labels))}</div>", unsafe_allow_html=True)
    if summary.total:
        percent = int(round(100 * summary.completed / summary.total))
        st.markdown(
            f"<div class='dt-progress-bar' role='progressbar' aria-valuenow='{summary.completed}' "
            f"aria-valuemin='0' aria-valuemax='{summary.total}'>"
            f"<div class='dt-progress-bar-fill' style='width:{percent}%'></div></div>",
            unsafe_allow_html=True,
        )


def render_workflow_progress(workflow, labels: Optional[dict] = None) -> None:
    texts = labels or {}
    current_title = getattr(workflow, "current", None)
    current_name = getattr(current_title, "title", "") if current_title is not None else ""
    review = getattr(workflow, "review_required", 0)
    st.markdown(
        f"<div class='dt-progress'>"
        f"{escape(texts.get('current_label', '現在'))}：{escape(current_name)}　"
        f"{escape(texts.get('progress_label', '進捗'))}：{workflow.completed} / {workflow.total}　"
        f"{escape(texts.get('review_label', '要確認'))}：{review}{escape(texts.get('review_unit', '件'))}"
        f"</div>",
        unsafe_allow_html=True,
    )
    percent = int(round(100 * workflow.completed / workflow.total)) if workflow.total else 0
    st.markdown(
        f"<div class='dt-progress-bar' role='progressbar' aria-valuenow='{workflow.completed}' "
        f"aria-valuemin='0' aria-valuemax='{workflow.total}'>"
        f"<div class='dt-progress-bar-fill' style='width:{percent}%'></div></div>",
        unsafe_allow_html=True,
    )


def render_work_card(title: str, badge_label: str, *, expanded: bool, key: Optional[str] = None):
    label = f"{title}　[{badge_label}]"
    return st.expander(label, expanded=expanded)


def render_recent_case_card(
    *,
    kind_label: str,
    customer: str,
    title: str,
    process_label: str,
    progress: str,
    review_label: str,
    updated_at: Optional[str],
    updated_prefix: str,
) -> None:
    updated = format_portal_datetime(updated_at) if updated_at else "-"
    st.markdown(
        f"<div class='portal-draft-card'>"
        f"<div class='dt-kind-badge'>{escape(kind_label)}</div>"
        f"<div class='portal-draft-title'>{escape(customer)}</div>"
        f"<div class='portal-draft-subject'>{escape(title)}</div>"
        f"<div class='portal-draft-meta'>{escape(process_label)}</div>"
        f"<div class='portal-draft-meta'>{escape(progress)}</div>"
        f"<div class='portal-draft-meta'>{escape(review_label)}</div>"
        f"<div class='portal-draft-meta'>{escape(updated_prefix)} {escape(updated)}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def info_label(status: str, labels: Optional[dict] = None) -> str:
    return (labels or INFO_LABELS).get(status, status)


def item_badge_label(summary: WorkSummary, key: str, labels: Optional[dict] = None) -> str:
    item = summary.item(key)
    if item is None:
        return info_label("NOT_STARTED", labels)
    label = info_label(item.status, labels)
    if item.review_count:
        return f"{label} {item.review_count}"
    return label
