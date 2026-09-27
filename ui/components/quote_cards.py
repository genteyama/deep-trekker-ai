import streamlit as st

from models import RequirementType
from ui.quote_format import display_number, display_yen
from ui.quote_steps import prices_adjusted


def render_configuration_card(page: dict, line) -> None:
    workspace = page["workspace"]
    presentation_labels = page["presentation_modes"]
    requirement_labels = workspace["requirement_types"]
    empty = page["no_value"]
    with st.container(border=True):
        st.markdown(f"**{line.customer_display_name or line.manufacturer_description or empty}**")
        st.caption(f"{page['column_sku']}: {line.manufacturer_sku or empty}")
        cols = st.columns(3)
        cols[0].write(f"{page['column_qty']}：{line.quantity}")
        required = line.requirement_type in {RequirementType.BASE_PRODUCT, RequirementType.REQUIRED_DEPENDENCY}
        cols[1].write(workspace["required_yes"] if required else workspace["required_no"])
        cols[2].write(workspace["snapshot_ready"] if line.manufacturer_price_snapshot else workspace["snapshot_missing"])
        st.write(
            f"{workspace['customer_display']}：{line.customer_display_name or empty} / "
            f"{presentation_labels.get(line.customer_presentation_status.value, line.customer_presentation_status.value)}"
        )
        if line.warnings:
            with st.expander(workspace.get("warning_details", "警告の詳細"), expanded=False):
                for item in line.warnings:
                    st.caption(item)
        with st.expander(workspace["see_details"], expanded=False):
            st.write(
                f"{page['column_requirement']}："
                f"{requirement_labels.get(line.requirement_type.value, line.requirement_type.value)}"
            )
            if line.required_by_sku:
                st.write(f"{page['column_sku']} dependency: {line.required_by_sku}")
            if line.dependency_source:
                st.write(line.dependency_source)
            st.write(f"{page['column_name_ja']}：{line.manufacturer_description or empty}")
        snapshot = line.manufacturer_price_snapshot
        with st.expander(workspace["manufacturer_price_details"], expanded=False):
            if snapshot is None:
                st.text(empty)
            else:
                st.write(f"SKU: {snapshot.sku}")
                st.write(f"MSRP USD: {display_number(snapshot.manufacturer_msrp_usd, empty)}")
                st.write(f"Dealer USD: {display_number(snapshot.manufacturer_dealer_price_usd, empty)}")
                st.write(f"{page['column_fx']}: {display_number(snapshot.exchange_rate, empty)}")
                if snapshot.source_reference:
                    st.caption(snapshot.source_reference)


def render_customer_line_card(page: dict, row: dict) -> None:
    empty = page["no_value"]
    with st.container(border=True):
        st.markdown(f"**{row.get('display_name') or empty}**")
        st.markdown(f"**{display_yen(row.get('unit_price_jpy'), empty)}**")
        if row.get("description"):
            st.write(row["description"])
        st.caption(f"{page['column_qty']}：{row.get('quantity') or 1}")


def render_price_adjustment(page: dict, line) -> None:
    if not prices_adjusted(line):
        return
    workspace = page["workspace"]
    st.caption(
        workspace["price_adjusted"].format(
            standard=display_yen(line.standard_sales_price_candidate_jpy, page["no_value"]),
            final=display_yen(line.final_sales_price_jpy, page["no_value"]),
        )
    )
