from ui.components.product_badge import product_badge_html, product_badge_label
from ui.product_assets import product_image_html, product_image_path


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
