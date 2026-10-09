import streamlit as st

from ui.quote_steps import non_official_price_lines
from ui.warning_summary import (
    format_warning_details,
    format_warning_lines,
    summarize_draft_warnings,
)


def render_price_source_notice(page: dict, draft) -> None:
    blocked = non_official_price_lines(draft)
    if not blocked:
        return
    template = page["workspace"].get("price_source_blocked", "{count}")
    st.error(template.format(count=len(blocked)))


def render_warning_panel(page: dict, draft) -> None:
    if draft is None:
        return
    render_price_source_notice(page, draft)
    workspace = page["workspace"]
    summary = summarize_draft_warnings(draft)
    if not summary["lines"] and not summary["raw"]:
        return
    labels = workspace.get("warning_kinds", {})
    lines = format_warning_lines(summary, labels)
    items = "".join(f"<li>{line}</li>" for line in lines)
    st.markdown(
        f"<div class='warning-card'><h4>{workspace.get('warning_title', '要確認があります')}</h4><ul>{items}</ul></div>",
        unsafe_allow_html=True,
    )
    if summary["raw"]:
        with st.expander(workspace.get("warning_details", "警告の詳細"), expanded=False):
            for item in format_warning_details(
                summary,
                labels,
                workspace.get("warning_detail_other", labels.get("other", "{count}")).format(count=1),
            ):
                st.caption(item)


def render_validation_warnings(page: dict, validation) -> None:
    if validation is None:
        return
    workspace = page["workspace"]
    raw = list(validation.critical_warnings) + list(validation.regular_warnings)
    if not raw:
        return
    if validation.critical_warnings:
        st.error(workspace.get("warning_title", "要確認があります"))
    elif validation.regular_warnings:
        st.warning(workspace.get("warning_title", "要確認があります"))
    with st.expander(workspace.get("warning_details", "警告の詳細"), expanded=False):
        summary = {"raw": list(dict.fromkeys(raw))}
        for item in format_warning_details(
            summary,
            workspace.get("warning_kinds", {}),
            workspace.get("warning_detail_other", "Review is required."),
        ):
            st.caption(item)
