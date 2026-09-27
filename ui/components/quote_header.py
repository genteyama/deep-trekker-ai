import streamlit as st

from ui.components.quote_summary import render_summary_cards
from ui.quote_format import display_percent, display_yen
from ui.quote_persistence import SESSION_SAVE_AT, SESSION_SAVE_ERROR, SESSION_SAVE_STATUS, format_saved_at
from ui.quote_steps import build_header_summary


def render_quote_header(page: dict, draft, snapshot) -> None:
    workspace = page["workspace"]
    summary = build_header_summary(draft, snapshot)
    if draft is None and snapshot is None:
        st.info(workspace["header_empty"])
        return
    status_labels = page["draft_statuses"]
    status = summary["status"]
    status_text = status_labels.get(status.value, status.value) if status is not None else workspace.get("unset_label", "未設定")
    with st.container(border=True):
        st.markdown(f"**{summary['customer'] or workspace.get('unset_label', '未設定')}**")
        title = summary["title"] or summary["configuration_name"] or workspace.get("unset_label", "未設定")
        st.write(title)
        meta = st.columns(3)
        meta[0].write(f"{workspace['header_quote_number']}：{summary['quote_number'] or workspace['header_unnumbered']}")
        meta[1].markdown(f"{workspace['header_status']}：<span class='status-badge'>{status_text}</span>", unsafe_allow_html=True)
        if summary["quote_version"] is not None:
            meta[2].write(f"{page['column_version']}：v{summary['quote_version']}")
        if summary["quote_draft_id"]:
            st.caption(f"{workspace['draft_id_label']}: {summary['quote_draft_id']}")
        render_summary_cards(
            [
                (workspace["header_total"], display_yen(summary["total"], None)),
                (workspace["header_subtotal"], display_yen(summary["subtotal"], None)),
                (workspace["header_margin"], display_percent(summary["gross_margin"], None)),
                (
                    workspace["header_warnings"],
                    f"{summary['warning_count']}{workspace['header_warning_unit']}",
                ),
            ],
            unset_label=workspace.get("unset_label", "未設定"),
        )
        _render_save_status(workspace)


def _render_save_status(workspace: dict) -> None:
    error = st.session_state.get(SESSION_SAVE_ERROR)
    if error:
        st.markdown(f"<div class='save-error'>⚠ {workspace.get('save_failed', error)}</div>", unsafe_allow_html=True)
        return
    status = st.session_state.get(SESSION_SAVE_STATUS)
    saved_at = format_saved_at(st.session_state.get(SESSION_SAVE_AT))
    if status == "saving":
        st.caption(workspace.get("saving_label", "保存中..."))
    elif saved_at:
        st.markdown(
            f"<div class='save-status'>✓ {workspace.get('saved_label', '保存済み')} {saved_at}</div>",
            unsafe_allow_html=True,
        )
