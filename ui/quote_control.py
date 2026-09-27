from typing import Optional

import streamlit as st
from openpyxl.utils.exceptions import InvalidFileException

from agents.master_reconciliation import reconcile_spaceone_master
from agents.quote_control_agent import SkuMasterStore, diff_price_books, import_price_book
from agents.sku_link import build_sku_link_preview, try_manual_link
from agents.supplier_quote_validation import load_official_manufacturer_price_books, validate_supplier_quote
from data.golden_cases.loader import IHI_QUOTE_001, load_quote_golden_case
from models import RequiredConfigurationItem, SupplierQuote
from agents.update_inbox_agent import UpdateInboxStore, create_manual_candidate, organize_pasted_update
from models import (
    LinkStatus,
    MatchStatus,
    PriceBookDiff,
    PriceBookDiffType,
    PriceBookImportResult,
    UpdateCategory,
    UpdateSourceType,
)
from parsers.spaceone_master_parser import parse_spaceone_master
from ui.navigation import PAGE_HOME, set_current_page

SESSION_IMPORT = "price_book_import"
SESSION_DIFF = "price_book_diff"
SESSION_OFFICIAL_MASTER = "official_sku_master"
SESSION_UPDATE_INBOX = "dt_update_inbox"
SESSION_RECONCILE = "spaceone_reconciliation"
SESSION_SKU_LINKS = "sku_link_preview"
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
    else:
        _render_import_summary(page, result)
        _render_sku_list(page, result)
        _render_diff(page, st.session_state.get(SESSION_DIFF))

    st.divider()
    _render_spaceone_reconciliation(page)
    st.divider()
    _render_update_inbox(page)
    _render_golden_quote_cases(page)


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
            page["column_source_status"]: item.source_status.value if item.source_status else page["no_value"],
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


def _render_spaceone_reconciliation(page: dict) -> None:
    st.subheader(page["section_spaceone_reconcile"])
    st.write(page["section_spaceone_reconcile_description"])
    st.caption(page["reconcile_not_applied"])

    dt40_file = st.file_uploader(page["upload_dt40_label"], type=["xlsx"], key="input_reconcile_dt40")
    pt30_file = st.file_uploader(page["upload_pt30_label"], type=["xlsx"], key="input_reconcile_pt30")
    spaceone_file = st.file_uploader(page["upload_spaceone_label"], type=["xlsx"], key="input_reconcile_spaceone")

    if st.button(page["reconcile_button"], key="reconcile_spaceone_master"):
        _run_reconciliation(page, dt40_file, pt30_file, spaceone_file)

    report = st.session_state.get(SESSION_RECONCILE)
    if report is None:
        st.text(page["no_reconcile"])
        _render_sku_link_preview(page)
        return

    summary = report.summary
    st.markdown(f"**{page['reconcile_summary_label']}**")
    st.write(f"{page['reconcile_total']}: {summary.total_rows}")
    st.write(f"{page['reconcile_compared']}: {summary.compared_rows}")
    st.write(f"{page['reconcile_exact']}: {summary.exact_match}")
    st.write(f"{page['reconcile_mismatch']}: {summary.price_mismatch}")
    st.write(f"{page['reconcile_missing']}: {summary.price_missing}")
    st.write(f"{page['reconcile_not_found']}: {summary.sku_not_found}")
    st.write(f"{page['reconcile_invalid']}: {summary.part_number_invalid}")
    st.write(f"{page['reconcile_obsolete']}: {summary.obsolete_only}")
    st.write(f"{page['reconcile_review']}: {summary.needs_review}")
    st.write(f"{page['reconcile_duplicate']}: {summary.multiple_spaceone_rows}")

    filter_options = page["reconcile_filters"]
    selected = st.selectbox(
        page["reconcile_filter_label"],
        options=list(filter_options.keys()),
        format_func=lambda key: filter_options[key],
        key="input_reconcile_filter",
    )
    rows = []
    status_labels = page["match_statuses"]
    for item in report.results:
        if not _match_filter(item, selected):
            continue
        spaceone = item.current_spaceone_values
        manufacturer = item.manufacturer_values
        reference = item.old_reference
        reason = "; ".join(issue.message for issue in item.issues) or page["no_value"]
        change_text = page["no_value"]
        if item.recommended_changes:
            change_text = " / ".join(
                f"{change.field}: {change.current_value} → {change.manufacturer_value}"
                for change in item.recommended_changes
            )
        rows.append(
            {
                page["column_spaceone_sku"]: item.spaceone_sku or page["no_value"],
                page["column_name_ja"]: spaceone.name_ja,
                page["column_judgment"]: status_labels.get(item.primary_status.value, item.primary_status.value),
                page["column_spaceone_msrp"]: spaceone.manufacturer_msrp_usd,
                page["column_mfr_msrp"]: manufacturer.msrp_usd if manufacturer else page["no_value"],
                page["column_spaceone_dealer"]: spaceone.manufacturer_dealer_price_usd,
                page["column_mfr_dealer"]: manufacturer.dealer_price_usd if manufacturer else page["no_value"],
                page["column_old_ref"]: (
                    f"{reference.workbook} {reference.sheet}!{reference.cell}"
                    if reference and reference.sheet and reference.cell
                    else page["no_value"]
                ),
                page["column_mfr_sheet"]: ", ".join(manufacturer.source_sheets) if manufacturer else page["no_value"],
                page["column_review_reason"]: reason,
                page["column_recommended"]: change_text,
            }
        )
    st.markdown(f"**{page['reconcile_issues_label']}**")
    if rows:
        st.table(rows)
    else:
        st.text(page["no_reconcile_rows"])
    st.caption(page["recommended_change_caption"])
    _render_sku_link_preview(page)


def _run_reconciliation(page: dict, dt40_file, pt30_file, spaceone_file) -> None:
    if spaceone_file is None or (dt40_file is None and pt30_file is None):
        st.error(page["reconcile_missing_files"])
        return
    try:
        spaceone = parse_spaceone_master(spaceone_file, source_name="SpaceOne")
        dt40 = import_price_book(dt40_file, source_price_book="DT40") if dt40_file is not None else None
        pt30 = import_price_book(pt30_file, source_price_book="PT30") if pt30_file is not None else None
    except (InvalidFileException, ValueError, OSError, KeyError):
        st.error(page["reconcile_error"])
        return
    st.session_state[SESSION_RECONCILE] = reconcile_spaceone_master(spaceone.items, dt40, pt30)
    st.session_state[SESSION_SKU_LINKS] = build_sku_link_preview(spaceone.items, dt40, pt30)


def _render_sku_link_preview(page: dict) -> None:
    preview = st.session_state.get(SESSION_SKU_LINKS)
    st.markdown(f"**{page['sku_link_preview_label']}**")
    flash = st.session_state.pop("sku_link_flash", None)
    if flash:
        accepted, message = flash
        if accepted:
            st.success(message)
        else:
            st.warning(message)
    if preview is None:
        st.text(page["no_sku_links"])
        return
    st.write(f"{page['sku_link_total']}: {preview.total_items}")
    st.write(f"{page['sku_link_auto']}: {preview.auto_linked}")
    st.write(f"{page['sku_link_review']}: {preview.review_required}")
    st.write(f"{page['sku_link_manual']}: {preview.manually_linked}")
    st.write(f"{page['sku_link_none']}: {preview.no_link_required}")
    link_labels = page["link_statuses"]
    rows = []
    for item in preview.items:
        current = item.current_values
        legacy = item.legacy
        reference = legacy.legacy_reference
        delta = item.price_difference.dealer_price_delta if item.price_difference else None
        rows.append(
            {
                page["column_spaceone_sku"]: item.spaceone_sku or page["no_value"],
                page["column_name_ja"]: item.name_ja or page["no_value"],
                page["column_link_status"]: link_labels.get(item.link.link_status.value, item.link.link_status.value),
                page["column_manufacturer_sku"]: item.link.manufacturer_sku or page["no_value"],
                page["column_legacy_dealer"]: _display_number(legacy.legacy_manufacturer_dealer_price, page),
                page["column_current_dealer"]: _display_number(current.dealer_price_usd if current else None, page),
                page["column_legacy_msrp"]: _display_number(legacy.legacy_manufacturer_msrp, page),
                page["column_current_msrp"]: _display_number(current.msrp_usd if current else None, page),
                page["column_dealer_delta"]: _display_number(delta, page),
                page["column_old_ref"]: (
                    f"{reference.workbook} {reference.sheet}!{reference.cell}"
                    if reference and reference.sheet and reference.cell
                    else page["no_value"]
                ),
                page["column_review_reason"]: item.review_reason or page["no_value"],
            }
        )
    st.table(rows)

    review_items = [item for item in preview.items if item.link.link_status == LinkStatus.REVIEW_REQUIRED]
    if not review_items:
        return
    st.markdown(f"**{page['manual_sku_link_label']}**")
    st.caption(page["manual_sku_link_hint"])
    for item in review_items:
        st.write(f"{item.spaceone_sku or page['no_value']} / {item.name_ja or page['no_value']}")
        entered = st.text_input(
            page["manual_manufacturer_sku_label"],
            key=f"manual_manufacturer_sku_{item.spaceone_item_id}",
        )
        if st.button(page["manual_link_button"], key=f"manual_link_button_{item.spaceone_item_id}"):
            result = try_manual_link(preview, item.spaceone_item_id, entered)
            st.session_state[SESSION_SKU_LINKS] = result.preview
            st.session_state["sku_link_flash"] = (result.accepted, result.message)
            st.rerun()


def _display_number(value, page: dict) -> str:
    if value is None:
        return page["no_value"]
    return f"{value:,}"


def _match_filter(item, selected: str) -> bool:
    if selected == "ALL":
        return True
    if selected == "REVIEW":
        return item.primary_status != MatchStatus.EXACT_MATCH
    return item.primary_status.value == selected


def _render_update_inbox(page: dict) -> None:
    inbox = _ensure_update_inbox()
    st.subheader(page["section_update_inbox"])
    st.write(page["section_update_inbox_description"])
    st.warning(page["update_inbox_mock_warning"])

    st.markdown(f"**{page['paste_update_label']}**")
    source_type_labels = page["source_types"]
    source_type_key = st.selectbox(
        page["source_type_label"],
        options=list(source_type_labels.keys()),
        format_func=lambda key: source_type_labels[key],
        key="input_update_source_type",
    )
    source_title = st.text_input(page["source_title_label"], key="input_update_source_title")
    source_sender = st.text_input(page["source_sender_label"], key="input_update_source_sender")
    source_date = st.text_input(page["source_date_label"], key="input_update_source_date")
    source_text = st.text_area(page["source_text_label"], key="input_update_source_text")

    if st.button(page["organize_update_button"], key="organize_update"):
        organize_pasted_update(
            source_type=UpdateSourceType(source_type_key),
            source_title=source_title or None,
            source_sender=source_sender or None,
            source_text=source_text or None,
            source_reference=source_date or None,
            store=inbox,
        )

    st.markdown(f"**{page['manual_update_label']}**")
    category_labels = page["update_categories"]
    manual_category = st.selectbox(
        page["manual_category_label"],
        options=list(category_labels.keys()),
        format_func=lambda key: category_labels[key],
        key="input_manual_category",
    )
    manual_product = st.text_input(page["manual_product_label"], key="input_manual_product")
    manual_sku = st.text_input(page["manual_sku_label"], key="input_manual_sku")
    manual_summary = st.text_input(page["manual_summary_label"], key="input_manual_summary")
    manual_value = st.text_input(page["manual_value_label"], key="input_manual_value")
    manual_unit = st.text_input(page["manual_unit_label"], key="input_manual_unit")
    manual_date = st.text_input(page["manual_date_label"], key="input_manual_date")
    manual_person = st.text_input(page["manual_person_label"], key="input_manual_person")
    manual_notes = st.text_area(page["manual_notes_label"], key="input_manual_notes")

    if st.button(page["manual_register_button"], key="register_manual_update"):
        create_manual_candidate(
            category=UpdateCategory(manual_category),
            summary=manual_summary or None,
            product=manual_product or None,
            sku=manual_sku or None,
            new_value=manual_value or None,
            unit=manual_unit or None,
            source_sender=manual_person or None,
            notes=manual_notes or None,
            source_reference=manual_date or None,
            store=inbox,
        )

    st.markdown(f"**{page['candidate_list_label']}**")
    if not inbox.candidates:
        st.text(page["no_update_candidates"])
        return

    rows = []
    sources = {item.update_source_id: item for item in inbox.sources}
    status_labels = page["candidate_statuses"]
    time_labels = page["time_sensitive"]
    for candidate in inbox.candidates:
        source = sources.get(candidate.update_source_id)
        rows.append(
            {
                page["column_category"]: category_labels.get(
                    candidate.category.value if candidate.category else "",
                    candidate.category.value if candidate.category else page["no_value"],
                ),
                page["column_target"]: candidate.product or candidate.sku or page["no_value"],
                page["column_summary"]: candidate.summary or candidate.title,
                page["column_new_value"]: candidate.new_value,
                page["column_unit"]: candidate.unit,
                page["column_time_sensitive"]: time_labels["yes"] if candidate.is_time_sensitive else time_labels["no"],
                page["column_source"]: (source.source_title or source.source_sender) if source else page["no_value"],
                page["column_status"]: status_labels.get(
                    candidate.status.value,
                    candidate.status.value,
                ),
            }
        )
    st.table(rows)


def _render_golden_quote_cases(page: dict) -> None:
    with st.expander(page["golden_quote_cases_label"]):
        st.caption(page["golden_quote_cases_hint"])
        case = load_quote_golden_case(IHI_QUOTE_001)
        supplier = case["supplier_quote"]
        mag = case["mag_customer_quote"]
        photon = case["photon_customer_quote"]
        expected = case["expected_validation"]
        st.markdown(f"**{expected['case_id']}**")
        st.write(expected["display_name"])
        st.write(
            f"{page['golden_sot_label']}: {', '.join(expected['manufacturer_source_of_truth'])}"
        )
        st.write(
            f"{page['golden_supplier_role_label']}: {page['golden_supplier_not_sot']}"
        )
        st.markdown(f"**{page['golden_known_issues_label']}**")
        for issue in supplier.get("known_issues") or []:
            st.write(f"{issue['code']}: {issue['message']}")
        st.markdown(f"**{page['golden_supplier_label']}**")
        st.write(f"{page['golden_reference']}: {supplier.get('quote_reference')}")
        st.write(f"{page['golden_supplier_total']}: {supplier.get('total_usd'):,} USD")
        st.table(
            [
                {
                    page["column_sku"]: line.get("sku") or page["no_value"],
                    page["column_description"]: line.get("description"),
                    page["golden_qty"]: line.get("quantity"),
                    page["golden_unit_usd"]: line.get("unit_price_usd"),
                }
                for line in supplier.get("lines") or []
            ]
        )
        st.markdown(f"**{page['golden_mag_label']}**")
        st.write(f"{page['golden_quote_number']}: {mag.get('quote_number')}")
        st.write(f"{page['golden_subtotal']}: {mag.get('subtotal_ex_tax_jpy'):,} JPY")
        st.write(f"{page['golden_total']}: {mag.get('total_jpy'):,} JPY")
        st.write(f"{page['golden_shipping']}: {mag.get('shipping', {}).get('description')}")
        st.write(f"{page['golden_insurance']}: {mag.get('insurance_note')}")
        st.write(f"{page['golden_lead_time']}: {mag.get('lead_time_note')}")
        st.markdown(f"**{page['golden_photon_label']}**")
        st.write(f"{page['golden_quote_number']}: {photon.get('quote_number')}")
        st.write(f"{page['golden_subtotal']}: {photon.get('subtotal_ex_tax_jpy'):,} JPY")
        st.write(f"{page['golden_total']}: {photon.get('total_jpy'):,} JPY")
        st.write(f"{page['golden_shipping']}: {photon.get('shipping', {}).get('description')}")
        st.write(f"{page['golden_insurance']}: {photon.get('insurance_note')}")
        st.write(f"{page['golden_lead_time']}: {photon.get('lead_time_note')}")
        _render_supplier_quote_validation(page, case)


def _render_supplier_quote_validation(page: dict, case: dict) -> None:
    st.markdown(f"**{page['golden_validation_label']}**")
    if st.button(page["golden_validate_button"], key="validate_ihi_supplier_quote"):
        books = load_official_manufacturer_price_books()
        if not books:
            st.session_state["ihi_supplier_validation"] = None
            st.warning(page["golden_validation_no_books"])
        else:
            quote = SupplierQuote.model_validate(case["supplier_quote"])
            required = [
                RequiredConfigurationItem.model_validate(item) for item in case["required_configuration"]
            ]
            st.session_state["ihi_supplier_validation"] = validate_supplier_quote(
                quote, *books, required_items=required
            )
    result = st.session_state.get("ihi_supplier_validation")
    if result is None:
        st.caption(page["golden_validation_hint"])
        return
    status_labels = page["golden_validation_statuses"]
    st.write(f"{page['golden_overall_status']}: {status_labels.get(result.status.value, result.status.value)}")
    st.write(f"{page['golden_supplier_total']}: {result.supplier_quote_total_usd:,} USD")
    rows = []
    for line in result.lines:
        if line.line_kind.value != "PRODUCT":
            continue
        rows.append(
            {
                page["column_sku"]: line.sku or page["no_value"],
                page["golden_supplier_price"]: _display_number(line.supplier_unit_price_usd, page),
                page["golden_current_dealer"]: _display_number(line.manufacturer_dealer_price_usd, page),
                page["golden_current_msrp"]: _display_number(line.manufacturer_msrp_usd, page),
                page["column_status"]: status_labels.get(line.validation_status.value, line.validation_status.value),
                page["golden_difference"]: _display_number(line.price_difference_vs_dealer, page),
                page["golden_warning"]: "; ".join(line.warnings) or page["no_value"],
            }
        )
    st.table(rows)
    st.markdown(f"**{page['golden_missing_label']}**")
    if result.known_configuration_issues:
        for issue in result.known_configuration_issues:
            st.write(f"{issue.code}: {issue.message}")
    else:
        st.text(page["no_value"])
    st.markdown(f"**{page['golden_shipping']}**")
    for line in result.lines:
        if line.line_kind.value == "SHIPPING":
            st.write(f"{line.description}: {line.quantity} x {_display_number(line.supplier_unit_price_usd, page)} USD")
    st.markdown(f"**{page['golden_insurance']}**")
    for line in result.lines:
        if line.line_kind.value == "INSURANCE":
            st.write(f"{line.description}: {_display_number(line.supplier_unit_price_usd, page)} USD")
    st.caption(page["golden_validation_caption"])


def _ensure_official_master() -> None:
    if SESSION_OFFICIAL_MASTER not in st.session_state:
        st.session_state[SESSION_OFFICIAL_MASTER] = SkuMasterStore()


def _ensure_update_inbox() -> UpdateInboxStore:
    if SESSION_UPDATE_INBOX not in st.session_state:
        st.session_state[SESSION_UPDATE_INBOX] = UpdateInboxStore()
    return st.session_state[SESSION_UPDATE_INBOX]
