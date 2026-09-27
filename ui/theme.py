from html import escape
from pathlib import Path
import base64

import streamlit as st

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

THEME_CSS = """
<style>
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"],
    [data-testid="stToolbar"], [data-testid="stMain"], [data-testid="stSidebar"] {
        background-color: #ffffff;
        color: #1a2330;
    }
    .block-container { padding-top: 1.2rem; max-width: 1100px; }
    [data-testid="stExpander"] {
        background: #ffffff;
        border: 1px solid #c9d4dc;
        border-radius: 8px;
    }
    [data-testid="stVerticalBlockBorderWrapper"] {
        background: #ffffff;
        border: 1px solid #c9d4dc;
    }
    .brand-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 24px 40px;
        min-height: 88px;
        padding: 22px 24px;
        border: 1px solid #d5dee4;
        border-radius: 8px;
        background: #ffffff;
        margin-bottom: 8px;
        overflow: visible;
        box-sizing: border-box;
        flex-wrap: wrap;
    }
    .brand-logos-left, .brand-logos-right {
        display: flex;
        align-items: center;
        gap: 28px;
        overflow: visible;
        min-height: 44px;
    }
    .brand-logos-right { margin-left: auto; justify-content: flex-end; }
    .brand-header img {
        height: 36px;
        width: auto;
        max-height: 36px;
        object-fit: contain;
        object-position: center;
        background: transparent;
        display: block;
        overflow: visible;
        flex-shrink: 0;
    }
    [data-testid="stMarkdownContainer"]:has(.brand-header),
    [data-testid="stMarkdownContainer"]:has(.brand-header) p,
    [data-testid="stElementContainer"]:has(.brand-header),
    .stMarkdown:has(.brand-header) {
        overflow: visible !important;
        line-height: normal;
        margin-bottom: 0;
        height: auto !important;
        max-height: none !important;
    }
    [data-testid="stHeading"] h1, h1 { text-align: center; }
    [data-testid="stHeading"] a,
    [data-testid="stHeaderActionElements"] { display: none !important; }
    .app-subtitle {
        text-align: center;
        color: #4a5b67;
        font-size: 15px;
        margin: 0 0 4px 0;
    }
    .portal-hero { text-align: center; padding: 8px 8px 4px 8px; }
    .portal-hero-en {
        text-align: center;
        color: #6b7c86;
        font-size: 13px;
        letter-spacing: 0.04em;
        margin: 0 0 8px 0;
    }
    .portal-hero-products {
        display: flex;
        justify-content: center;
        align-items: center;
        gap: 20px;
        margin-top: 10px;
        min-height: 0;
    }
    .portal-hero-product { height: 48px; width: auto; object-fit: contain; opacity: 0.9; }
    .portal-section-title {
        color: #123a56;
        font-size: 20px;
        font-weight: 700;
        margin: 18px 0 12px 0;
    }
    .portal-card {
        border: 1px solid #c9d4dc;
        border-radius: 8px;
        background: #ffffff;
        padding: 18px 18px 14px 18px;
        min-height: 132px;
        transition: border-color 0.15s ease;
    }
    .portal-card:hover { border-color: #1b6b8a; }
    .portal-card-title { color: #123a56; font-size: 20px; font-weight: 700; line-height: 1.3; }
    .portal-card-en { color: #1b6b8a; font-size: 13px; margin: 4px 0 8px 0; }
    .portal-card-desc { color: #4a5b67; font-size: 14px; line-height: 1.5; }
    .portal-card-thumb { height: 56px; width: auto; max-width: 120px; object-fit: contain; display: block; margin-bottom: 10px; }
    .portal-product-card { min-height: 96px; }
    .product-badge {
        display: inline-block;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.06em;
        color: #123a56;
        border: 1px solid #1b6b8a;
        background: #f3f6f8;
        padding: 2px 8px;
        border-radius: 3px;
        margin: 0 0 6px 0;
    }
    .portal-draft-card {
        border: 1px solid #c9d4dc;
        border-radius: 8px;
        background: #ffffff;
        padding: 14px 16px;
        margin-bottom: 8px;
        transition: border-color 0.15s ease;
    }
    .portal-draft-card:hover { border-color: #1b6b8a; }
    .portal-draft-title { color: #123a56; font-size: 16px; font-weight: 700; }
    .portal-draft-badge-row { margin: 6px 0; }
    .portal-draft-subject { color: #1a2330; font-size: 14px; margin-bottom: 8px; }
    .portal-draft-meta { color: #6b7c86; font-size: 13px; }
    .summary-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin: 8px 0 14px 0; }
    .summary-card {
        background: #ffffff;
        border: 1px solid #c9d4dc;
        border-radius: 8px;
        padding: 10px 12px;
        min-height: 72px;
    }
    .summary-card .label { font-size: 13px; color: #4a5b67; margin-bottom: 4px; }
    .summary-card .value { font-size: 22px; line-height: 1.2; color: #123a56; font-weight: 650; word-break: break-word; }
    .summary-card .unset { font-size: 13px; color: #6b7c86; font-weight: 500; }
    .section-rule { border: 0; border-top: 1px solid #d5dee4; margin: 12px 0; }
    .warning-card {
        border: 1px solid #c9a227;
        background: #fffdf6;
        border-radius: 8px;
        padding: 10px 12px;
        margin: 8px 0 12px 0;
    }
    .warning-card h4 { margin: 0 0 6px 0; font-size: 14px; color: #5c4a10; }
    .warning-card li { font-size: 14px; color: #1a2330; }
    .draft-card {
        border: 1px solid #c9d4dc;
        background: #ffffff;
        border-radius: 8px;
        padding: 10px 12px;
        margin-bottom: 8px;
    }
    .status-badge {
        display: inline-block;
        font-size: 12px;
        padding: 2px 8px;
        border: 1px solid #c9d4dc;
        border-radius: 999px;
        color: #123a56;
        background: #f3f6f8;
    }
    table { border-collapse: collapse; width: 100%; }
    thead tr { border-bottom: 2px solid #123a56; }
    tbody tr { border-bottom: 1px solid #d5dee4; }
    [data-testid="stTable"] table { border: 1px solid #c9d4dc; background: #ffffff; }
    [data-testid="stTable"] th {
        background: #f3f6f8;
        color: #123a56;
        border-bottom: 1px solid #c9d4dc;
        text-align: left;
    }
    [data-testid="stTable"] td { border-bottom: 1px solid #e2e8ec; color: #1a2330; }
    .save-status { font-size: 13px; color: #1b6b8a; }
    .save-error { font-size: 13px; color: #a12626; }
</style>
"""


def apply_light_theme() -> None:
    st.markdown(THEME_CSS, unsafe_allow_html=True)


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
