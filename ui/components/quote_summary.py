import streamlit as st

from ui.quote_format import display_percent, display_yen
from ui.quote_steps import costing_summary


def render_costing_summary(page: dict, draft) -> None:
    workspace = page["workspace"]
    summary = costing_summary(draft)
    first = st.columns(4)
    first[0].metric(workspace["metric_product_cost"], display_yen(summary["product_cost"], page["no_value"]))
    first[1].metric(workspace["metric_shipping_cost"], display_yen(summary["shipping_cost"], page["no_value"]))
    first[2].metric(workspace["metric_total_cost"], display_yen(summary["total_cost"], page["no_value"]))
    first[3].metric(workspace["metric_standard"], display_yen(summary["standard_sales"], page["no_value"]))
    second = st.columns(3)
    second[0].metric(workspace["metric_final"], display_yen(summary["final_sales"], page["no_value"]))
    second[1].metric(workspace["metric_profit"], display_yen(summary["gross_profit"], page["no_value"]))
    second[2].metric(workspace["metric_margin"], display_percent(summary["gross_margin"], page["no_value"]))
