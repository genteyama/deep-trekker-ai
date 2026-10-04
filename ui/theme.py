from html import escape
from pathlib import Path
import base64

import streamlit as st

from ui.styles import apply_app_styles

ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets" / "branding"
DEEPTREKKER_LOGO = ASSETS_DIR / "deeptrekker_logo.png"
PIPETREKKER_LOGO = ASSETS_DIR / "pipetrekker_logo.png"
SPACEONE_LOGO = ASSETS_DIR / "spaceone_logo.png"
BRAND_LOGOS_LEFT = (
    (DEEPTREKKER_LOGO, "DeepTrekker"),
    (PIPETREKKER_LOGO, "PipeTrekker"),
)
BRAND_LOGOS_RIGHT = (
    (SPACEONE_LOGO, "SpaceOne"),
)
BRAND_LOGOS = BRAND_LOGOS_LEFT + BRAND_LOGOS_RIGHT
BRAND_LOGO_HEIGHT = 36


def apply_light_theme() -> None:
    apply_app_styles()


def _logo_img(path: Path, alt: str) -> str:
    if not path.exists():
        return ""
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return (
        f"<img src='data:image/png;base64,{encoded}' alt='{escape(alt)}' "
        f"height='{BRAND_LOGO_HEIGHT}' style='height:{BRAND_LOGO_HEIGHT}px;width:auto;object-fit:contain;' />"
    )


def render_brand_header() -> None:
    left = "".join(_logo_img(path, alt) for path, alt in BRAND_LOGOS_LEFT)
    right = "".join(_logo_img(path, alt) for path, alt in BRAND_LOGOS_RIGHT)
    st.markdown(
        f"<div class='brand-header'>"
        f"<div class='brand-logos-left'>{left}</div>"
        f"<div class='brand-logos-right'>{right}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
