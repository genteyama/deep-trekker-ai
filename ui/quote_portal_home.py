"""Simplified HOME for the quote and price focused portal."""

HOME_LOGO_HEIGHT = 18


def render_quote_portal_home(texts: dict) -> None:
    import streamlit as st

    from ui.components.portal import render_home_hero
    from ui.navigation import PAGE_PRICE_CATALOG, PAGE_QUOTE_CONTROL, PAGE_QUOTE_LIST, set_current_page
    from ui.theme import brand_logos_html

    render_home_hero(
        title="Deep Trekker / PipeTrekker Quote Portal",
        description="価格確認と見積作成を、迷わず最短で進めるための業務ポータル",
        eyebrow="DEEP TREKKER · PIPETREKKER · SPACEONE",
        logos_html=brand_logos_html(HOME_LOGO_HEIGHT),
        summary_label="メーカー価格のSource of Truth",
        summary_items=[
            ("DT40", "Active Master", ""),
            ("PT30", "Active Master", ""),
            ("SPECTRA GOLD", "Active Master", "is-total"),
        ],
    )

    st.subheader("何をしますか？")
    left, center, right = st.columns(3)
    with left:
        with st.container(border=True):
            st.markdown("### 価格一覧")
            st.write("全商品のメーカー価格を一覧・検索します。")
            if st.button("価格一覧を見る", key="home_open_price_catalog", type="primary", use_container_width=True):
                set_current_page(PAGE_PRICE_CATALOG)
                st.rerun()
    with center:
        with st.container(border=True):
            st.markdown("### 見積作成")
            st.write("SKUを指定して原価・売価・粗利を計算します。")
            if st.button("見積作成を開く", key="home_open_quote", type="primary", use_container_width=True):
                set_current_page(PAGE_QUOTE_CONTROL)
                st.rerun()
    with right:
        with st.container(border=True):
            st.markdown("### 見積一覧")
            st.write("保存済み見積を検索・閲覧します。")
            if st.button("見積一覧を見る", key="home_open_quote_list", type="primary", use_container_width=True):
                set_current_page(PAGE_QUOTE_LIST)
                st.rerun()

    st.divider()
    with st.container(border=True):
        st.markdown("### Deep Trekker見積PDFから作成")
        st.write("メーカー見積PDFからSKU・数量・価格・送料等を取り込み、自動試算する機能は次の開発Stepで追加します。")
        st.button("準備中", disabled=True, key="home_supplier_pdf_pending")
