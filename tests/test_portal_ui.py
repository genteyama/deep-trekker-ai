from ui.components.product_badge import product_badge_html, product_badge_label
from ui.product_assets import product_image_html, product_image_path
from ui.styles import APP_CSS, page_icon_value


def test_product_badge_shows_text_not_color_only():
    html = product_badge_html("photon")
    assert "PHOTON" in html
    assert "product-badge" in html
    assert product_badge_label("") == ""
    assert product_badge_html(None) == ""


def test_product_images_are_local_only_and_optional():
    remote = product_image_path("https://example.com/photon.png")
    assert remote is None
    path = product_image_path("PHOTON")
    html = product_image_html("PHOTON")
    if path is None:
        assert html == ""
    else:
        assert path.is_file()
        assert "assets/products" in path.as_posix()
        assert html.startswith("<img")
        assert "http://" not in html and "https://" not in html


def test_shared_css_uses_brand_tokens_and_button_states():
    assert "--dt-navy" in APP_CSS
    assert "--dt-navy-hover" in APP_CSS
    assert "--dt-border" in APP_CSS
    assert ".activity-th" in APP_CSS
    assert ".dt-step-card" in APP_CSS
    assert ".dt-progress-bar" in APP_CSS
    assert ".dt-step-current-label" in APP_CSS
    assert "background: var(--dt-navy) !important" in APP_CSS
    assert "cursor: pointer" in APP_CSS
    assert "cursor: not-allowed" in APP_CSS
    assert "opacity: 0.45" in APP_CSS
    assert page_icon_value() in {str(__import__("ui.styles", fromlist=["FAVICON_PATH"]).FAVICON_PATH), "🌊"}
