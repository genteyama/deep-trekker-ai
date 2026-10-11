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
    .block-container { padding-top: 1.2rem; max-width: 1240px; }
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
    .brand-header.is-compact {
        gap: 12px 16px;
        min-height: 52px;
        padding: 10px 16px;
        /* Streamlit's toolbar is 60px and covers content that starts near 35px. */
        margin-top: 28px;
        margin-bottom: 6px;
    }
    .brand-header.is-compact .brand-logos-left,
    .brand-header.is-compact .brand-logos-right {
        gap: 14px;
        min-height: 26px;
    }
    .brand-header.is-compact img {
        height: 26px;
        max-height: 26px;
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
    .portal-card {
        min-height: 228px;
        display: flex;
        flex-direction: column;
        box-sizing: border-box;
    }
    .portal-card.is-compact { min-height: 176px; padding: 12px 14px; }
    .portal-card.is-compact .portal-card-thumb,
    .portal-card.is-compact .portal-card-thumb-spacer { height: 42px; margin-bottom: 7px; }
    .portal-card.is-compact .portal-card-title { font-size: 17px; }
    .portal-card.is-compact .portal-card-en { margin: 2px 0 5px 0; }
    .portal-card:hover, .portal-draft-card:hover { border-color: var(--dt-accent); }
    .portal-card-title, .dt-card-title, .portal-draft-title {
        color: var(--dt-navy);
        font-size: 20px;
        font-weight: 700;
        line-height: 1.35;
        display: flex;
        flex-wrap: wrap;
        align-items: baseline;
        gap: 2px 4px;
    }
    .portal-card-count {
        font-size: 13px;
        font-weight: 650;
        color: var(--dt-accent);
        white-space: nowrap;
    }
    .portal-card-en { color: var(--dt-accent); font-size: 13px; margin: 4px 0 8px 0; }
    .portal-card-desc, .dt-card-meta { color: var(--dt-muted); font-size: 14px; line-height: 1.5; flex: 1; }
    .portal-card-thumb, .portal-card-thumb-spacer {
        height: 56px;
        width: auto;
        max-width: 120px;
        object-fit: contain;
        display: block;
        margin-bottom: 10px;
        flex-shrink: 0;
    }
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
    .home-summary-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px;
        margin: 6px 0 12px 0;
    }
    .home-summary-card {
        border: 1px solid var(--dt-border);
        border-radius: 8px;
        background: var(--dt-white);
        padding: 9px 12px;
    }
    .home-summary-label { color: var(--dt-muted); font-size: 12px; margin-bottom: 2px; }
    .home-summary-value { color: var(--dt-navy); font-size: 19px; font-weight: 700; line-height: 1.25; }
    @media (max-width: 700px) {
        .home-summary-grid { grid-template-columns: 1fr; }
    }
    .summary-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin: 8px 0 14px 0; }
    .summary-card { min-height: 72px; padding: 10px 12px; }
    .summary-card .label { font-size: 13px; color: var(--dt-muted); margin-bottom: 4px; }
    .summary-card .value { font-size: 22px; line-height: 1.2; color: var(--dt-navy); font-weight: 650; word-break: break-word; }
    .summary-card .unset { font-size: 13px; color: var(--dt-muted); font-weight: 500; }
    .dt-progress { color: var(--dt-navy); font-size: 14px; font-weight: 650; }
    .dt-progress-bar {
        height: 6px;
        background: var(--dt-border);
        border-radius: 999px;
        overflow: hidden;
        margin: 6px 0 10px 0;
    }
    .dt-progress-bar-fill {
        height: 100%;
        background: var(--dt-navy);
        border-radius: 999px;
    }
    .dt-step-card {
        border: 1px solid var(--dt-border);
        border-radius: 10px;
        background: var(--dt-white);
        padding: 10px 12px;
        min-height: 88px;
        margin-bottom: 8px;
        box-sizing: border-box;
    }
    .dt-step-card.is-current {
        border: 2px solid var(--dt-navy);
        background: var(--dt-bg-soft);
    }
    .dt-step-card.is-compact {
        min-height: 68px;
        padding: 6px 10px;
        margin-bottom: 4px;
    }
    .dt-step-card.is-compact .dt-step-card-top {
        margin-bottom: 4px;
    }
    .record-header {
        display: flex;
        flex-wrap: wrap;
        justify-content: space-between;
        gap: 8px 24px;
        padding: 12px 16px;
        border: 1px solid var(--dt-border);
        border-radius: 8px;
        background: var(--dt-white);
        margin-bottom: 8px;
    }
    .record-header-identity { min-width: 0; }
    .record-customer { color: var(--dt-muted); font-size: 13px; }
    .record-title { color: var(--dt-navy); font-size: 20px; font-weight: 700; line-height: 1.3; }
    .record-header-status { text-align: right; }
    .record-status { color: var(--dt-navy); font-weight: 700; }
    .record-header-meta {
        flex-basis: 100%;
        display: flex;
        flex-wrap: wrap;
        gap: 8px 20px;
        color: var(--dt-muted);
        font-size: 13px;
    }
    .record-meta-row {
        display: flex;
        justify-content: space-between;
        gap: 12px;
        color: var(--dt-text);
        font-size: 13px;
        line-height: 1.45;
    }
    .record-flag {
        display: inline-block;
        margin-left: 6px;
        padding: 1px 6px;
        border-radius: 999px;
        background: var(--dt-bg-soft);
        color: var(--dt-navy);
        font-size: 12px;
    }
    .record-side-card {
        padding: 10px 12px;
        margin-bottom: 8px;
        border-radius: 8px;
        background: var(--dt-bg-soft);
    }
    .record-side-title {
        color: var(--dt-navy);
        font-size: 13px;
        font-weight: 700;
        margin-bottom: 6px;
    }
    .record-related-item {
        padding: 4px 0;
        border-top: 1px solid var(--dt-border);
        color: var(--dt-text);
        font-size: 13px;
    }
    .dt-step-card-top {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 6px;
        margin-bottom: 8px;
    }
    .dt-step-num {
        color: var(--dt-navy);
        font-size: 14px;
        font-weight: 700;
        line-height: 1.35;
    }
    .dt-step-current-label {
        display: inline-block;
        font-size: 11px;
        font-weight: 700;
        color: var(--dt-white);
        background: var(--dt-navy);
        padding: 1px 6px;
        border-radius: 4px;
        white-space: nowrap;
    }
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
    [data-testid="stHorizontalBlock"]:has(.activity-th) {
        background: var(--dt-navy);
        border: 1px solid var(--dt-navy);
        margin-bottom: 0;
    }
    [data-testid="stHorizontalBlock"]:has(.activity-td) {
        background: var(--dt-white);
        border: 1px solid var(--dt-border);
        border-top: none;
        margin-bottom: 0;
    }
    [data-testid="stHorizontalBlock"]:has(.activity-td):nth-of-type(even) {
        background: var(--dt-bg-soft);
    }
    [data-testid="stHorizontalBlock"]:has(.activity-th) [data-testid="column"],
    [data-testid="stHorizontalBlock"]:has(.activity-td) [data-testid="column"] {
        border-right: 1px solid rgba(255,255,255,0.18);
        padding: 6px 6px !important;
    }
    [data-testid="stHorizontalBlock"]:has(.activity-td) [data-testid="column"] {
        border-right: 1px solid var(--dt-border);
    }
    [data-testid="stHorizontalBlock"]:has(.activity-th) [data-testid="column"]:last-child,
    [data-testid="stHorizontalBlock"]:has(.activity-td) [data-testid="column"]:last-child {
        border-right: none;
    }
    .activity-th {
        color: var(--dt-white);
        font-size: 12px;
        font-weight: 700;
        line-height: 1.3;
        padding: 8px 4px;
    }
    .activity-td {
        color: var(--dt-text);
        font-size: 13px;
        line-height: 1.35;
        padding: 7px 4px;
        overflow-wrap: anywhere;
        word-break: break-word;
    }
    .activity-td-product, .activity-td-title, .activity-td-status {
        min-width: 0;
    }
    .activity-td-title { font-weight: 650; }
    .activity-td-status { color: var(--dt-navy); font-weight: 650; }
    .save-status { font-size: 13px; color: var(--dt-accent); }
    .save-error { font-size: 13px; color: var(--dt-danger); }
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
        gap: 0.42rem !important;
    }
    [data-testid="stSidebar"] .st-key-sidebar_main_menu,
    [data-testid="stSidebar"] .st-key-sidebar_admin_menu,
    [data-testid="stSidebar"] .st-key-sidebar_quote_workflow,
    [data-testid="stSidebar"] .st-key-sidebar_technical_workflow,
    [data-testid="stSidebar"] .st-key-sidebar_location_row,
    [data-testid="stSidebar"] .st-key-sidebar_admin_menu [data-testid="stVerticalBlock"],
    [data-testid="stSidebar"] .st-key-sidebar_main_menu [data-testid="stVerticalBlock"],
    [data-testid="stSidebar"] .st-key-sidebar_quote_workflow [data-testid="stVerticalBlock"],
    [data-testid="stSidebar"] .st-key-sidebar_technical_workflow [data-testid="stVerticalBlock"],
    [data-testid="stSidebar"] .st-key-sidebar_location_row [data-testid="stVerticalBlock"] {
        gap: 0.2rem !important;
    }
    [data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.sidebar-brand) {
        height: auto !important;
        min-height: 1.45rem !important;
    }
    [data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.sidebar-location-line) {
        height: auto !important;
        min-height: 1.35rem !important;
    }
    [data-testid="stSidebar"] .sidebar-brand,
    [data-testid="stSidebar"] .sidebar-location-line {
        margin: 0;
        line-height: 1.3;
    }
    [data-testid="stSidebar"] .sidebar-brand {
        color: var(--dt-navy);
        font-size: 1.02rem;
        font-weight: 700;
        margin-bottom: 0.15rem;
    }
    [data-testid="stSidebar"] .sidebar-location-line {
        color: var(--dt-text);
        font-size: 0.84rem;
    }
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
        margin: 0;
    }
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {
        margin: 0;
        font-size: 0.78rem;
        line-height: 1.25;
    }
    [data-testid="stSidebar"] hr {
        margin: 0.2rem 0 !important;
    }
    [data-testid="stSidebar"] [class*="st-key-sidebar_admin_"] button[kind] {
        min-height: 38px !important;
        padding: 0.22rem 0.7rem !important;
        font-size: 0.9rem !important;
        line-height: 1.2 !important;
    }
    [data-testid="stSidebar"] [class*="st-key-sidebar_nav_"] button[kind] {
        min-height: 38px !important;
        padding: 0.22rem 0.7rem !important;
        font-size: 0.9rem !important;
        line-height: 1.2 !important;
    }
    [data-testid="stSidebar"] [class*="st-key-sidebar_breadcrumb_home"] {
        width: auto !important;
        flex: 0 0 auto !important;
    }
    [data-testid="stSidebar"] [class*="st-key-sidebar_breadcrumb_home"] button[kind] {
        width: auto !important;
        min-height: 32px !important;
        height: 32px !important;
        white-space: nowrap !important;
        padding: 0.1rem 0.55rem !important;
        font-size: 0.84rem !important;
        line-height: 1.2 !important;
    }
    [data-testid="stSidebar"] [class*="st-key-sidebar_quote_step_"] button[kind],
    [data-testid="stSidebar"] [class*="st-key-sidebar_technical_step_"] button[kind],
    [data-testid="stSidebar"] [class*="st-key-auth_logout"] button[kind] {
        min-height: 34px !important;
        padding: 0.14rem 0.65rem !important;
        font-size: 0.84rem !important;
        line-height: 1.2 !important;
    }
</style>
"""


def favicon_path() -> Optional[Path]:
    return FAVICON_PATH if FAVICON_PATH.exists() else None


def page_icon_value():
    path = favicon_path()
    return str(path) if path is not None else "🌊"


def apply_app_styles() -> None:
    st.markdown(APP_CSS, unsafe_allow_html=True)
