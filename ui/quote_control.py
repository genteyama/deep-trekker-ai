from typing import Optional

import streamlit as st
from openpyxl.utils.exceptions import InvalidFileException

from agents.quote_control_agent import SkuMasterStore, diff_price_books, import_price_book
from models import PriceBookDiff, PriceBookDiffType, PriceBookImportResult
from ui.navigation import PAGE_HOME, set_current_page

SESSION_IMPORT = "price_book_import"
SESSION_DIFF = "price_book_diff"
SESSION_OFFICIAL_MASTER = "official_sku_master"
DIFF_ORDER = (
    PriceBookDiffType.NEW_SKU,
    PriceBookDiffType.PRICE_CHANGED,
    PriceBookDiffType.DESCRIPTION_CHANGED,
    PriceBookDiffType.NOTES_CHANGED,
    PriceBookDiffType.REMOVED_SKU,
    PriceBookDiffType.UNCHANGED,
)


def render_quote_control(texts: dict) -> None:
    page = texts["pages"]["quote_control"]
    _ensure_official_master()

    if st.button(texts["back_to_home"], key="back_to_home"):
        set_current_page(PAGE_HOME)
        st.rerun()

    st.title(page["title"])
    st.caption(page["internal_name"])
    st.write(page["description"])
    st.divider()

    st.subheader(page["section_sku_master"])
    st.write(page["section_sku_master_description"])
    st.caption(page["diff_not_applied"])

    uploaded = st.file_uploader(page["upload_label"], type=["xlsx"], key="input_price_book")
    previous = st.file_uploader(
        page["previous_master_label"],
        type=["xlsx"],
        key="input_previous_master",
    )
    st.caption(page["previous_master_hint"])
    source_price_book = st.text_input(page["price_book_name_label"], key="input_price_book_name")
    version = st.text_input(page["version_label"], key="input_price_book_version")

    if st.button(page["import_button"], key="import_price_book"):
        _run_import(page, uploaded, previous, source_price_book, version)

    result = st.session_state.get(SESSION_IMPORT)
    if result is None:
        st.text(page["no_import"])
        return

    _render_import_summary(page, result)
    _render_sku_list(page, result)
    _render_diff(page, st.session_state.get(SESSION_DIFF))


def _run_import(page: dict, uploaded, previous, source_price_book: str, version: str) -> None:
    if uploaded is None:
        st.error(page["import_no_file"])
        return
    official_master = st.session_state[SESSION_OFFICIAL_MASTER]
    before = official_master.snapshot()
    try:
        result = import_price_book(
            uploaded,
            source_price_book=source_price_book or None,
            version=version or None,
            official_master=official_master,
        )
    except (InvalidFileException, ValueError, OSError, KeyError):
        st.error(page["import_error"])
        return
    st.session_state[SESSION_IMPORT] = result
    if previous is not None:
        previous_result = import_price_book(
            previous,
            source_price_book="previous_master",
            official_master=official_master,
        )
        st.session_state[SESSION_DIFF] = diff_price_books(previous_result.items, result.items)
    else:
        st.session_state[SESSION_DIFF] = None
    if official_master.snapshot() != before:
        official_master.items = before


def _render_import_summary(page: dict, result: PriceBookImportResult) -> None:
    st.markdown(f"**{page['summary_label']}**")
    st.write(f"{page['summary_price_book']}: {result.source_price_book or page['no_value']}")
    st.write(f"{page['summary_version']}: {result.version or page['no_value']}")
    st.write(f"{page['summary_sheets']}: {len(result.sheets)}")
    st.write(f"{page['summary_skus']}: {len(result.items)}")
    st.write(f"{page['summary_warnings']}: {len(result.warnings)}")
    st.write(f"{page['summary_errors']}: {len(result.errors)}")


def _render_sku_list(page: dict, result: PriceBookImportResult) -> None:
    st.markdown(f"**{page['sku_list_label']}**")
    rows = [
        {
            page["column_sku"]: item.sku,
            page["column_description"]: item.description,
            page["column_msrp"]: item.msrp_usd,
            page["column_dealer_price"]: item.dealer_price_usd,
            page["column_dealer_rate"]: item.dealer_rate,
            page["column_source_sheet"]: item.source_sheet,
            page["column_notes"]: item.notes,
        }
        for item in result.items
    ]
    if rows:
        st.table(rows)
    else:
        st.text(page["no_skus"])


def _render_diff(page: dict, diff: Optional[PriceBookDiff]) -> None:
    st.markdown(f"**{page['diff_label']}**")
    if diff is None:
        st.text(page["no_previous_master"])
        return
    labels = page["diff_types"]
    for change_type in DIFF_ORDER:
        st.write(f"{labels[change_type.value]}: {diff.count(change_type)}")


def _ensure_official_master() -> None:
    if SESSION_OFFICIAL_MASTER not in st.session_state:
        st.session_state[SESSION_OFFICIAL_MASTER] = SkuMasterStore()
