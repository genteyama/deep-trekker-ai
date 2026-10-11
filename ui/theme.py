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
COMPACT_BRAND_LOGO_HEIGHT = 26


def apply_light_theme() -> None:
    apply_app_styles()


def _logo_img(path: Path, alt: str, height: int = BRAND_LOGO_HEIGHT) -> str:
    if not path.exists():
        return ""
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return (
        f"<img src='data:image/png;base64,{encoded}' alt='{escape(alt)}' "
        f"height='{height}' style='height:{height}px;width:auto;object-fit:contain;' />"
    )


def render_brand_header(compact: bool = False) -> None:
    height = COMPACT_BRAND_LOGO_HEIGHT if compact else BRAND_LOGO_HEIGHT
    left = "".join(_logo_img(path, alt, height) for path, alt in BRAND_LOGOS_LEFT)
    right = "".join(_logo_img(path, alt, height) for path, alt in BRAND_LOGOS_RIGHT)
    css = "brand-header is-compact" if compact else "brand-header"
    st.markdown(
        f"<div class='{css}'>"
        f"<div class='brand-logos-left'>{left}</div>"
        f"<div class='brand-logos-right'>{right}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
