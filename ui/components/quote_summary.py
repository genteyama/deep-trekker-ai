import streamlit as st

from ui.quote_format import display_percent, display_yen
from ui.quote_steps import costing_summary


def render_summary_cards(items: list[tuple[str, object]], unset_label: str = "未設定") -> None:
    cards = []
    for label, value in items:
        if value is None:
            body = f"<div class='unset'>{unset_label}</div>"
        else:
            body = f"<div class='value'>{value}</div>"
        cards.append(f"<div class='summary-card'><div class='label'>{label}</div>{body}</div>")
    st.markdown(f"<div class='summary-grid'>{''.join(cards)}</div>", unsafe_allow_html=True)


def render_costing_summary(page: dict, draft) -> None:
    workspace = page["workspace"]
    summary = costing_summary(draft)
    unset = workspace.get("unset_label", "未設定")
    render_summary_cards(
        [
            (workspace["metric_product_cost"], display_yen(summary["product_cost"], None)),
            (workspace["metric_shipping_cost"], display_yen(summary["shipping_cost"], None)),
            (workspace["metric_total_cost"], display_yen(summary["total_cost"], None)),
            (workspace["metric_standard"], display_yen(summary["standard_sales"], None)),
            (workspace["metric_final"], display_yen(summary["final_sales"], None)),
            (workspace["metric_profit"], display_yen(summary["gross_profit"], None)),
            (workspace["metric_margin"], display_percent(summary["gross_margin"], None)),
        ],
        unset_label=unset,
    )
