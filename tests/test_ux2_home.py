from tests.test_app_pages import _start_app


def _visible(at) -> str:
    return " ".join(
        [item.value for item in at.text]
        + [item.value for item in at.markdown]
        + [item.value for item in at.caption]
    )


def test_home_is_price_and_quote_focused():
    at = _start_app()
    visible = _visible(at)

    assert "Deep Trekker / PipeTrekker Quote Portal" in visible
    assert "メーカー価格のSource of Truth" in visible
    assert "DT40" in visible
    assert "PT30" in visible
    assert "SPECTRA GOLD" in visible
    assert at.button(key="home_open_price_catalog").disabled is False
    assert at.button(key="home_open_quote").disabled is False
    assert at.button(key="home_open_quote_list").disabled is False
    assert at.button(key="home_supplier_pdf_pending").disabled is True
    assert "進行中の案件" not in visible
    assert "次にやること" not in visible


def test_primary_sidebar_is_price_quote_focused_and_legacy_tools_remain_available():
    at = _start_app()

    for key in (
        "sidebar_nav_home",
        "sidebar_nav_price_catalog",
        "sidebar_nav_quote",
        "sidebar_nav_quote_list",
        "sidebar_admin_price_master",
    ):
        assert at.button(key=key).disabled is False

    # Existing capabilities are retained behind the secondary section, not deleted.
    assert at.button(key="sidebar_nav_technical").disabled is False
    assert at.button(key="sidebar_nav_activity").disabled is False
    assert any(expander.label == "詳細機能" for expander in at.expander)


def test_home_keeps_brand_logos():
    at = _start_app()
    html = " ".join(item.value for item in at.markdown)
    assert "class='home-hero-logos'" in html
    for alt in ("DeepTrekker", "PipeTrekker", "SpaceOne"):
        assert f"alt='{alt}' height='18'" in html
