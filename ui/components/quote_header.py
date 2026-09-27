import streamlit as st

from ui.quote_format import display_percent, display_yen
from ui.quote_steps import build_header_summary


def render_quote_header(page: dict, draft, snapshot) -> None:
    workspace = page["workspace"]
    summary = build_header_summary(draft, snapshot)
    if draft is None and snapshot is None:
        st.info(workspace["header_empty"])
        return
    status_labels = page["draft_statuses"]
    status = summary["status"]
    status_text = status_labels.get(status.value, status.value) if status is not None else page["no_value"]
    st.markdown(f"**{summary['customer'] or page['no_value']}**")
    title = summary["title"] or summary["configuration_name"] or page["no_value"]
    st.write(title)
    meta = st.columns(3)
    meta[0].write(f"{workspace['header_quote_number']}：{summary['quote_number'] or workspace['header_unnumbered']}")
    meta[1].write(f"{workspace['header_status']}：{status_text}")
    if summary["quote_version"] is not None:
        meta[2].write(f"{page['column_version']}：v{summary['quote_version']}")
    if summary["quote_draft_id"]:
        st.caption(f"{workspace['draft_id_label']}: {summary['quote_draft_id']}")
    metrics = st.columns(4)
    metrics[0].metric(workspace["header_total"], display_yen(summary["total"], page["no_value"]))
    metrics[1].metric(workspace["header_subtotal"], display_yen(summary["subtotal"], page["no_value"]))
    metrics[2].metric(workspace["header_margin"], display_percent(summary["gross_margin"], page["no_value"]))
    metrics[3].metric(
        workspace["header_warnings"],
        f"{summary['warning_count']}{workspace['header_warning_unit']}",
    )
