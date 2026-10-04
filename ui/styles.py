from __future__ import annotations

from pathlib import Path
from typing import Optional

import streamlit as st

ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
FAVICON_PATH = ASSETS_DIR / "deep_trekker_favicon.png"

APP_CSS = """
<style>
    :root {
        --dt-navy: #123a56;
        --dt-navy-hover: #1b5578;
        --dt-border: #c9d4dc;
        --dt-bg-soft: #f3f6f8;
        --dt-text: #1a2330;
        --dt-muted: #4a5b67;
        --dt-accent: #1b6b8a;
        --dt-warn: #8a6a12;
        --dt-warn-bg: #fffdf6;
        --dt-danger: #a12626;
        --dt-white: #ffffff;
    }
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"],
    [data-testid="stToolbar"], [data-testid="stMain"], [data-testid="stSidebar"] {
        background-color: var(--dt-white);
        color: var(--dt-text);
    }
    .block-container { padding-top: 1.2rem; max-width: 1100px; }
    [data-testid="stExpander"] {
        background: var(--dt-white);
        border: 1px solid var(--dt-border);
        border-radius: 10px;
    }
    [data-testid="stVerticalBlockBorderWrapper"] {
        background: var(--dt-white);
        border: 1px solid var(--dt-border);
    }
    div.stButton > button,
    button[data-testid="baseButton-primary"],
    button[data-testid="baseButton-secondary"],
    button[kind="primary"],
    button[kind="secondary"] {
        border-radius: 8px;
        font-weight: 650;
        cursor: pointer;
        min-height: 40px;
    }
    button[data-testid="baseButton-primary"],
    button[kind="primary"] {
        background: var(--dt-navy) !important;
        color: var(--dt-white) !important;
        border: 1px solid var(--dt-navy) !important;
    }
    button[data-testid="baseButton-primary"]:hover,
    button[kind="primary"]:hover {
        background: var(--dt-navy-hover) !important;
        border-color: var(--dt-navy-hover) !important;
        color: var(--dt-white) !important;
    }
    button[data-testid="baseButton-secondary"],
    button[kind="secondary"] {
        background: var(--dt-white) !important;
        color: var(--dt-navy) !important;
        border: 1px solid var(--dt-navy) !important;
    }
    button[data-testid="baseButton-secondary"]:hover,
    button[kind="secondary"]:hover {
        background: var(--dt-bg-soft) !important;
        color: var(--dt-navy) !important;
    }
    button:disabled,
    button[disabled] {
        opacity: 0.45 !important;
        cursor: not-allowed !important;
        color: var(--dt-muted) !important;
    }
    .dt-complete-wrap button {
        background: var(--dt-bg-soft) !important;
        color: var(--dt-navy) !important;
        border: 1px solid var(--dt-border) !important;
    }
    .dt-danger-wrap button {
        background: var(--dt-white) !important;
        color: var(--dt-danger) !important;
        border: 1px solid var(--dt-danger) !important;
    }
    .brand-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 24px 40px;
        min-height: 88px;
        padding: 22px 24px;
        border: 1px solid var(--dt-border);
        border-radius: 8px;
        background: var(--dt-white);
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
        display: block;
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
        color: var(--dt-muted);
        font-size: 15px;
        margin: 0 0 4px 0;
    }
    .portal-hero { text-align: center; padding: 8px 8px 4px 8px; }
    .portal-hero-en {
        text-align: center;
        color: var(--dt-muted);
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
    }
    .portal-hero-product { height: 48px; width: auto; object-fit: contain; opacity: 0.9; }
    .portal-section-title {
        color: var(--dt-navy);
        font-size: 20px;
        font-weight: 700;
        margin: 18px 0 12px 0;
    }
    .portal-card, .dt-card, .portal-draft-card, .summary-card, .draft-card {
        border: 1px solid var(--dt-border);
        border-radius: 10px;
        background: var(--dt-white);
        padding: 16px 18px;
    }
    .portal-card { min-height: 132px; }
    .portal-card:hover, .portal-draft-card:hover { border-color: var(--dt-accent); }
    .portal-card-title, .dt-card-title, .portal-draft-title { color: var(--dt-navy); font-size: 20px; font-weight: 700; line-height: 1.3; }
    .portal-card-en { color: var(--dt-accent); font-size: 13px; margin: 4px 0 8px 0; }
    .portal-card-desc, .dt-card-meta { color: var(--dt-muted); font-size: 14px; line-height: 1.5; }
    .portal-card-thumb { height: 56px; width: auto; max-width: 120px; object-fit: contain; display: block; margin-bottom: 10px; }
    .portal-product-card { min-height: 96px; }
    .product-badge, .dt-status-badge, .status-badge {
        display: inline-block;
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0.02em;
        color: var(--dt-navy);
        border: 1px solid var(--dt-accent);
        background: var(--dt-bg-soft);
        padding: 2px 8px;
        border-radius: 999px;
        margin: 0 4px 6px 0;
    }
    .dt-status-badge.is-review, .dt-status-badge.is-waiting {
        border-color: var(--dt-warn);
        color: var(--dt-warn);
        background: var(--dt-warn-bg);
    }
    .dt-status-badge.is-missing { border-color: var(--dt-border); color: var(--dt-muted); }
    .dt-kind-badge {
        display: inline-block;
        font-size: 12px;
        font-weight: 700;
        color: var(--dt-white);
        background: var(--dt-navy);
        padding: 2px 8px;
        border-radius: 4px;
        margin-bottom: 6px;
    }
    .portal-draft-card { padding: 14px 16px; margin-bottom: 8px; }
    .portal-draft-title { font-size: 16px; }
    .portal-draft-subject { color: var(--dt-text); font-size: 14px; margin-bottom: 8px; }
    .portal-draft-meta { color: var(--dt-muted); font-size: 13px; }
    .summary-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin: 8px 0 14px 0; }
    .summary-card { min-height: 72px; padding: 10px 12px; }
    .summary-card .label { font-size: 13px; color: var(--dt-muted); margin-bottom: 4px; }
    .summary-card .value { font-size: 22px; line-height: 1.2; color: var(--dt-navy); font-weight: 650; word-break: break-word; }
    .summary-card .unset { font-size: 13px; color: var(--dt-muted); font-weight: 500; }
    .dt-progress { color: var(--dt-navy); font-size: 14px; font-weight: 650; }
    .section-rule { border: 0; border-top: 1px solid var(--dt-border); margin: 12px 0; }
    .warning-card {
        border: 1px solid #c9a227;
        background: var(--dt-warn-bg);
        border-radius: 8px;
        padding: 10px 12px;
        margin: 8px 0 12px 0;
    }
    .warning-card h4 { margin: 0 0 6px 0; font-size: 14px; color: #5c4a10; }
    table { border-collapse: collapse; width: 100%; }
    thead tr { border-bottom: 2px solid var(--dt-navy); }
    tbody tr { border-bottom: 1px solid var(--dt-border); }
    [data-testid="stTable"] th { background: var(--dt-bg-soft); color: var(--dt-navy); }
    .save-status { font-size: 13px; color: var(--dt-accent); }
    .save-error { font-size: 13px; color: var(--dt-danger); }
</style>
"""


def favicon_path() -> Optional[Path]:
    return FAVICON_PATH if FAVICON_PATH.exists() else None


def page_icon_value():
    path = favicon_path()
    return str(path) if path is not None else "🌊"


def apply_app_styles() -> None:
    st.markdown(APP_CSS, unsafe_allow_html=True)
