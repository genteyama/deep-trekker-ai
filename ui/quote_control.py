from pathlib import Path
from typing import Optional

import streamlit as st
from openpyxl.utils.exceptions import InvalidFileException

from agents.landed_cost import (
    build_ihi_landed_cost_scenario,
    build_shipping_line,
    calculate_landed_cost_scenario,
    compare_quote_economics,
    ihi_historical_sales_totals,
    policy_from_inputs,
    resolve_ihi_dealer_values,
    september_dealer_update_shipping_rate,
    supplier_quote_shipping_rate,
)
from agents.quote_approval import (
    QuoteApprovalError,
    QuoteApprovalStore,
    apply_ihi_photon_human_final_fixture,
    approve_quote,
    create_revision_draft,
    generate_quote_outputs,
    validate_for_approval,
)
from agents.quote_export import (
    QuoteExportError,
    export_internal_calc_excel,
    export_moneyforward_csv,
    export_moneyforward_tsv,
    export_spaceone_quote_excel,
)
from agents.quote_builder import (
    apply_final_price,
    apply_historical_acceptance_preview,
    apply_issue_date,
    apply_lead_time_text,
    apply_presentation_mode,
    apply_selected_remarks,
    apply_shipping_final_price,
    apply_tax_rate,
    apply_valid_until,
    build_ihi_quote_draft,
    customer_preview_rows,
)
from agents.quote_dates import (
    add_one_calendar_month,
    next_valid_until,
    parse_quote_date,
    tokyo_today,
    valid_until_matches_auto_rule,
)
from agents.master_reconciliation import collect_manufacturer_candidates, reconcile_spaceone_master
from agents.quote_control_agent import SkuMasterStore, diff_price_books, import_price_book
from agents.pricing_policy import (
    build_exchange_rate_scenario,
    compare_ihi_historical_prices,
    extract_pricing_policies,
    ihi_historical_comparison_lines,
    simulate_sales_price_candidates,
    summarize_pricing_patterns,
)
from agents.sku_link import build_sku_link_preview, try_manual_link
from agents.supplier_quote_validation import load_official_manufacturer_price_books, validate_supplier_quote
from data.golden_cases.loader import IHI_QUOTE_001, load_quote_golden_case
from models import (
    CustomerPresentationMode,
    DomesticShippingMode,
    ExportPurpose,
    FinalPriceStatus,
    InsuranceMode,
    QuoteDraftStatus,
    RequiredConfigurationItem,
    ShippingType,
    SupplierQuote,
)
from parsers.quote_calc_parser import extract_quote_calc_audit, locate_quote_calc_workbook
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
SESSION_SPACEONE_ITEMS = "spaceone_master_items"
SESSION_SALES_CANDIDATES = "sales_price_candidates"
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
    _render_pricing_policy(page)
    st.divider()
    _render_landed_cost(page)
    st.divider()
    _render_quote_builder(page)
    st.divider()
    _render_quote_approval(page)
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
    st.session_state[SESSION_SPACEONE_ITEMS] = spaceone.items


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


def _render_pricing_policy(page: dict) -> None:
    st.subheader(page["section_pricing_policy"])
    st.write(page["section_pricing_policy_description"])
    st.caption(page["pricing_policy_not_applied"])
    items = st.session_state.get(SESSION_SPACEONE_ITEMS)
    preview = st.session_state.get(SESSION_SKU_LINKS)
    if not items:
        st.text(page["no_pricing_policies"])
        return
    policies = extract_pricing_policies(items)
    patterns = summarize_pricing_patterns(policies)
    st.markdown(f"**{page['pricing_pattern_label']}**")
    st.table(
        [
            {
                page["column_pattern"]: item.formula,
                page["column_basis"]: item.price_basis.value if item.price_basis else page["no_value"],
                page["column_multiplier"]: item.multiplier if item.multiplier is not None else page["no_value"],
                page["sku_link_total"]: item.item_count,
                page["column_formula_example"]: item.formula,
                page["sku_link_review"]: item.review_count,
            }
            for item in patterns
        ]
    )
    detected = next((item.detected_exchange_rate for item in items if item.detected_exchange_rate), None)
    if detected:
        st.caption(page["detected_rate_caption"].format(rate=detected))
    rate_text = st.text_input(page["exchange_rate_label"], key="input_sales_exchange_rate")
    if st.button(page["simulate_sales_button"], key="simulate_sales_prices"):
        try:
            rate = float(rate_text)
        except (TypeError, ValueError):
            st.warning(page["exchange_rate_invalid"])
            return
        if preview is None:
            st.warning(page["no_sku_links"])
            return
        st.session_state[SESSION_SALES_CANDIDATES] = simulate_sales_price_candidates(
            preview, policies, build_exchange_rate_scenario(rate), items
        )
    candidates = st.session_state.get(SESSION_SALES_CANDIDATES)
    if not candidates:
        return
    st.table(
        [
            {
                page["column_sku"]: item.manufacturer_sku or page["no_value"],
                page["column_name_ja"]: item.name_ja or page["no_value"],
                page["column_mfr_msrp"]: _display_number(item.manufacturer_msrp_usd, page),
                page["column_mfr_dealer"]: _display_number(item.manufacturer_dealer_price_usd, page),
                page["exchange_rate_label"]: _display_number(item.exchange_rate, page),
                page["column_policy"]: item.source_formula or page["no_value"],
                page["column_current_sales"]: _display_number(item.current_spaceone_sales_price_jpy, page),
                page["column_sales_candidate"]: _display_number(item.raw_sales_price_jpy, page),
                page["column_sales_delta"]: _display_number(item.difference_jpy, page),
                page["column_ref_margin"]: (
                    f"{item.reference_gross_margin_rate:.1%}" if item.reference_gross_margin_rate is not None else page["no_value"]
                ),
                page["golden_warning"]: item.skipped_reason or "; ".join(item.warnings) or page["no_value"],
            }
            for item in candidates
        ]
    )


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
        _render_ihi_pricing_comparison(page, case)
        _render_ihi_landed_cost_cases(page, case)
        st.markdown(f"**{page['section_quote_builder']}**")
        if st.button(page["ihi_photon_draft_button"], key="golden_ihi_photon_draft"):
            st.session_state["quote_draft"] = _build_ihi_draft_from_ui(page, case, "PHOTON")
        if st.button(page["ihi_mag_draft_button"], key="golden_ihi_mag_draft"):
            st.session_state["quote_draft"] = _build_ihi_draft_from_ui(page, case, "MAG")


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


def _render_ihi_pricing_comparison(page: dict, case: dict) -> None:
    st.markdown(f"**{page['ihi_pricing_comparison_label']}**")
    st.caption(page["ihi_pricing_comparison_hint"])
    rate_text = st.text_input(page["exchange_rate_label"], key="input_ihi_comparison_rate")
    if st.button(page["ihi_compare_button"], key="compare_ihi_pricing"):
        try:
            rate = float(rate_text)
        except (TypeError, ValueError):
            st.warning(page["exchange_rate_invalid"])
            return
        books = load_official_manufacturer_price_books()
        spaceone_path = Path("/tmp/dt_price_investigation/SO_MASTER.xlsx")
        if not books or not spaceone_path.exists():
            st.warning(page["golden_validation_no_books"])
            return
        spaceone = parse_spaceone_master(spaceone_path, source_name="SO_MASTER")
        preview = build_sku_link_preview(spaceone.items, *books)
        policies = extract_pricing_policies(spaceone.items)
        sales = simulate_sales_price_candidates(
            preview, policies, build_exchange_rate_scenario(rate), spaceone.items
        )
        st.session_state["ihi_pricing_comparison"] = compare_ihi_historical_prices(
            sales, policies, historical_lines=ihi_historical_comparison_lines(case)
        )
    rows = st.session_state.get("ihi_pricing_comparison")
    if not rows:
        return
    labels = page["comparison_statuses"]
    st.table(
        [
            {
                page["column_sku"]: item.sku or page["no_value"],
                page["column_name_ja"]: item.item_name or page["no_value"],
                page["column_sales_candidate"]: _display_number(item.policy_sales_price_jpy, page),
                page["column_historical"]: _display_number(item.historical_quote_price_jpy, page),
                page["column_sales_delta"]: _display_number(item.difference_jpy, page),
                page["column_comparison"]: labels.get(item.comparison_status.value, item.comparison_status.value),
            }
            for item in rows
        ]
    )


def _render_landed_cost(page: dict) -> None:
    st.subheader(page["section_landed_cost"])
    st.write(page["section_landed_cost_description"])
    st.caption(page["landed_cost_not_applied"])
    st.caption(page["import_tax_basis_caption"])
    st.caption(page["domestic_shipping_caption"])
    rate_text = st.text_input(page["exchange_rate_label"], key="input_landed_exchange_rate")
    tax_text = st.text_input(page["import_tax_rate_label"], key="input_landed_import_tax")
    insurance_labels = page["insurance_modes"]
    insurance_mode = st.selectbox(
        page["insurance_mode_label"],
        options=list(insurance_labels.keys()),
        format_func=lambda key: insurance_labels[key],
        key="input_landed_insurance_mode",
    )
    insurance_rate_text = st.text_input(page["insurance_rate_label"], key="input_landed_insurance_rate")
    domestic_text = st.text_input(page["domestic_shipping_label"], key="input_landed_domestic")
    snapshot_labels = page["shipping_snapshots"]
    snapshot_key = st.selectbox(
        page["shipping_snapshot_label"],
        options=list(snapshot_labels.keys()),
        format_func=lambda key: snapshot_labels[key],
        key="input_landed_shipping_snapshot",
    )
    large_qty_text = st.text_input(page["large_box_qty_label"], key="input_landed_large_qty")
    small_qty_text = st.text_input(page["small_box_qty_label"], key="input_landed_small_qty")
    if st.button(page["landed_calc_button"], key="estimate_landed_cost"):
        parsed = _parse_landed_inputs(page, rate_text, tax_text, insurance_rate_text, domestic_text, large_qty_text, small_qty_text)
        if parsed is None:
            return
        preview = st.session_state.get(SESSION_SKU_LINKS)
        sales = st.session_state.get(SESSION_SALES_CANDIDATES) or []
        product_inputs = _product_inputs_from_preview(preview)
        if not product_inputs:
            st.warning(page["landed_no_products"])
            return
        extracted_markup = _extracted_shipping_markup()
        policy = policy_from_inputs(
            import_tax_rate=parsed["tax_rate"],
            insurance_mode=InsuranceMode(insurance_mode),
            insurance_rate=parsed["insurance_rate"],
            shipping_markup_multiplier=extracted_markup,
            domestic_shipping_jpy=parsed["domestic"],
            domestic_shipping_mode=DomesticShippingMode.MANUAL if parsed["domestic"] is not None else DomesticShippingMode.REVIEW_REQUIRED,
        )
        shipping_lines = _shipping_lines_from_inputs(snapshot_key, parsed, policy)
        scenario, economics = calculate_landed_cost_scenario(
            scenario_id="ui-landed-cost",
            case_id=None,
            name="UI landed cost",
            exchange_rate=parsed["rate"],
            policy=policy,
            product_inputs=product_inputs,
            shipping_lines=shipping_lines,
            sales_candidates=sales,
            insurance_mode=InsuranceMode(insurance_mode),
            domestic_shipping_jpy=parsed["domestic"],
        )
        st.session_state["landed_cost_result"] = (scenario, economics)
    result = st.session_state.get("landed_cost_result")
    if result:
        _render_landed_cost_result(page, *result)


def _render_ihi_landed_cost_cases(page: dict, case: dict) -> None:
    st.markdown(f"**{page['ihi_mag_landed_label']} / {page['ihi_photon_landed_label']}**")
    st.caption(page["ihi_landed_hint"])
    rate_text = st.text_input(page["exchange_rate_label"], key="input_ihi_landed_rate")
    if st.button(page["ihi_mag_landed_button"], key="estimate_ihi_mag_landed"):
        st.session_state["ihi_mag_landed"] = _run_ihi_landed(page, case, "MAG", rate_text)
    if st.button(page["ihi_photon_landed_button"], key="estimate_ihi_photon_landed"):
        st.session_state["ihi_photon_landed"] = _run_ihi_landed(page, case, "PHOTON", rate_text)
    for key, label in (("ihi_mag_landed", page["ihi_mag_landed_label"]), ("ihi_photon_landed", page["ihi_photon_landed_label"])):
        result = st.session_state.get(key)
        if not result:
            continue
        st.markdown(f"**{label}**")
        scenario, economics = result
        _render_landed_cost_result(page, scenario, economics)
        comparison = economics.economics_comparison
        if comparison is None:
            continue
        st.markdown(f"**{page['ihi_economics_label']}**")
        st.table(
            [
                {
                    page["column_comparison"]: "Product",
                    page["column_calculated"]: _display_number(comparison.product_sales_calculated_jpy, page),
                    page["column_historical"]: _display_number(comparison.product_sales_historical_jpy, page),
                    page["column_sales_delta"]: _display_number(comparison.product_sales_difference_jpy, page),
                },
                {
                    page["column_comparison"]: "Shipping",
                    page["column_calculated"]: _display_number(comparison.shipping_sales_calculated_jpy, page),
                    page["column_historical"]: _display_number(comparison.shipping_sales_historical_jpy, page),
                    page["column_sales_delta"]: _display_number(comparison.shipping_sales_difference_jpy, page),
                },
                {
                    page["column_comparison"]: "Total",
                    page["column_calculated"]: _display_number(comparison.total_sales_calculated_jpy, page),
                    page["column_historical"]: _display_number(comparison.total_sales_historical_jpy, page),
                    page["column_sales_delta"]: _display_number(comparison.total_sales_difference_jpy, page),
                },
            ]
        )


def _render_landed_cost_result(page: dict, scenario, economics) -> None:
    labels = page["completeness"]
    st.write(f"{page['summary_completeness']}: {labels.get(scenario.status.value, scenario.status.value)}")
    st.write(f"{page['summary_sales']}: {_display_number(economics.total_sales_ex_tax_jpy, page)}")
    st.write(f"{page['summary_landed']}: {_display_number(economics.total_landed_cost_jpy, page)}")
    st.write(f"{page['summary_gross_profit']}: {_display_number(economics.gross_profit_jpy, page)}")
    st.write(
        f"{page['summary_gross_margin']}: "
        f"{f'{economics.gross_margin_rate:.1%}' if economics.gross_margin_rate is not None else page['no_value']}"
    )
    st.table(
        [
            {
                page["column_sku"]: line.sku or page["no_value"],
                page["column_dealer_usd"]: _display_number(line.dealer_price_usd, page),
                page["column_fx"]: _display_number(line.exchange_rate, page),
                page["column_dealer_jpy"]: _display_number(line.dealer_cost_jpy, page),
                page["column_import_tax"]: _display_number(line.import_tax_jpy, page),
                page["column_insurance"]: _display_number(line.insurance_jpy, page),
                page["column_domestic"]: _display_number(line.domestic_shipping_jpy, page),
                page["column_landed"]: _display_number(line.landed_cost_jpy, page),
                page["column_sales_candidate"]: _display_number(line.standard_sales_price_jpy, page),
                page["column_line_profit"]: _display_number(
                    None
                    if line.standard_sales_price_jpy is None or line.landed_cost_jpy is None
                    else line.standard_sales_price_jpy - line.landed_cost_jpy,
                    page,
                ),
                page["golden_warning"]: "; ".join(line.warnings) or page["no_value"],
            }
            for line in scenario.product_lines
        ]
    )
    if scenario.shipping_lines:
        st.table(
            [
                {
                    page["column_shipping_type"]: line.shipping_type.value if line.shipping_type else page["no_value"],
                    page["column_qty"]: line.quantity,
                    page["column_usd_rate"]: _display_number(line.rate_usd, page),
                    page["column_cost_jpy"]: _display_number(line.cost_jpy, page),
                    page["column_sales_candidate"]: _display_number(line.sales_price_candidate_jpy, page),
                }
                for line in scenario.shipping_lines
            ]
        )
    if scenario.unresolved_components:
        st.write(f"{page['golden_missing_label']}: {', '.join(scenario.unresolved_components)}")
    if economics.warnings:
        st.caption("; ".join(economics.warnings))


def _run_ihi_landed(page: dict, case: dict, configuration: str, rate_text: str):
    try:
        rate = float(rate_text)
    except (TypeError, ValueError):
        st.warning(page["exchange_rate_invalid"])
        return None
    books = load_official_manufacturer_price_books()
    candidates = collect_manufacturer_candidates(*books) if books else []
    dealer_values = resolve_ihi_dealer_values(candidates)
    sales = st.session_state.get(SESSION_SALES_CANDIDATES) or []
    spaceone_path = Path("/tmp/dt_price_investigation/SO_MASTER.xlsx")
    if spaceone_path.exists() and books:
        spaceone = parse_spaceone_master(spaceone_path, source_name="SO_MASTER")
        preview = build_sku_link_preview(spaceone.items, *books)
        policies = extract_pricing_policies(spaceone.items)
        sales = simulate_sales_price_candidates(
            preview, policies, build_exchange_rate_scenario(rate), spaceone.items
        )
    policy = _extracted_landed_policy()
    if policy is None or policy.import_tax_rate is None:
        tax_rate = _optional_float(st.session_state.get("input_landed_import_tax"))
        insurance_rate = _optional_float(st.session_state.get("input_landed_insurance_rate"))
        if tax_rate is None:
            st.warning(page["exchange_rate_invalid"])
            return None
        policy = policy_from_inputs(
            import_tax_rate=tax_rate,
            insurance_mode=InsuranceMode.PERCENTAGE,
            insurance_rate=insurance_rate,
            shipping_markup_multiplier=None,
            domestic_shipping_jpy=10000,
            domestic_shipping_mode=DomesticShippingMode.REVIEW_REQUIRED,
        )
    scenario, economics = build_ihi_landed_cost_scenario(
        configuration,
        exchange_rate=rate,
        policy=policy,
        dealer_values=dealer_values,
        sales_candidates=sales,
        price_book_candidates=candidates,
    )
    quote = case["mag_customer_quote"] if configuration == "MAG" else case["photon_customer_quote"]
    historical = ihi_historical_sales_totals(quote)
    comparisons = []
    if sales:
        comparisons = compare_ihi_historical_prices(
            sales,
            extract_pricing_policies(parse_spaceone_master(spaceone_path, source_name="SO_MASTER").items)
            if spaceone_path.exists()
            else [],
            historical_lines=[
                line for line in ihi_historical_comparison_lines(case) if line.get("quote") == configuration
            ],
        )
    economics = compare_quote_economics(
        economics,
        configuration_name=configuration,
        quote_number=historical["quote_number"],
        historical_product_sales_jpy=historical["product_sales_jpy"],
        historical_shipping_sales_jpy=historical["shipping_sales_jpy"],
        historical_total_sales_jpy=historical["total_sales_jpy"],
        product_comparisons=comparisons,
    )
    return scenario, economics


def _product_inputs_from_preview(preview) -> list[dict]:
    if preview is None:
        return []
    inputs = []
    for item in preview.items:
        if item.link.link_status.value not in {"AUTO_LINKED", "MANUALLY_LINKED"}:
            continue
        current = item.current_values
        if current is None or current.dealer_price_usd is None:
            continue
        inputs.append(
            {
                "sku": item.link.manufacturer_sku,
                "quantity": 1,
                "dealer_price_usd": current.dealer_price_usd,
                "msrp_usd": current.msrp_usd,
                "description": item.name_ja,
                "price_book": current.price_book,
                "price_book_version": current.price_book_version,
            }
        )
    return inputs


def _shipping_lines_from_inputs(snapshot_key: str, parsed: dict, policy) -> list:
    lines = []
    for shipping_type, qty in (
        (ShippingType.LARGE_BOX, parsed["large_qty"]),
        (ShippingType.SMALL_BOX, parsed["small_qty"]),
    ):
        if not qty:
            continue
        if snapshot_key == "SUPPLIER_QUOTE":
            rate = supplier_quote_shipping_rate(shipping_type)
        else:
            rate = september_dealer_update_shipping_rate(shipping_type)
        if rate is None:
            continue
        lines.append(
            build_shipping_line(
                shipping_type,
                qty,
                rate,
                parsed["rate"],
                policy,
                source_type=snapshot_key,
                source_reference=snapshot_key,
                rule_status="SNAPSHOT",
            )
        )
    return lines


def _extracted_landed_policy():
    cached = st.session_state.get("quote_calc_policy")
    if "quote_calc_policy" in st.session_state:
        return cached
    path = locate_quote_calc_workbook()
    policy = extract_quote_calc_audit(path).policy_candidate if path else None
    st.session_state["quote_calc_policy"] = policy
    return policy


def _extracted_shipping_markup():
    policy = _extracted_landed_policy()
    return policy.shipping_markup_multiplier if policy else None


def _optional_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_landed_inputs(page, rate_text, tax_text, insurance_rate_text, domestic_text, large_qty_text, small_qty_text):
    try:
        rate = float(rate_text)
        tax_rate = float(tax_text)
    except (TypeError, ValueError):
        st.warning(page["exchange_rate_invalid"])
        return None
    insurance_rate = None
    if insurance_rate_text:
        try:
            insurance_rate = float(insurance_rate_text)
        except (TypeError, ValueError):
            st.warning(page["exchange_rate_invalid"])
            return None
    domestic = None
    if domestic_text:
        try:
            domestic = float(domestic_text)
        except (TypeError, ValueError):
            st.warning(page["exchange_rate_invalid"])
            return None
    large_qty = int(large_qty_text) if large_qty_text else 0
    small_qty = int(small_qty_text) if small_qty_text else 0
    return {
        "rate": rate,
        "tax_rate": tax_rate,
        "insurance_rate": insurance_rate,
        "domestic": domestic,
        "large_qty": large_qty,
        "small_qty": small_qty,
    }


def _render_quote_builder(page: dict) -> None:
    st.subheader(page["section_quote_builder"])
    st.write(page["section_quote_builder_description"])
    st.caption(page["quote_builder_hint"])
    case = load_quote_golden_case(IHI_QUOTE_001)
    if st.button(page["ihi_photon_draft_button"], key="ihi_photon_draft"):
        st.session_state["quote_draft"] = _build_ihi_draft_from_ui(page, case, "PHOTON")
    if st.button(page["ihi_mag_draft_button"], key="ihi_mag_draft"):
        st.session_state["quote_draft"] = _build_ihi_draft_from_ui(page, case, "MAG")
    draft = st.session_state.get("quote_draft")
    if draft is None:
        st.text(page["no_quote_draft"])
        return
    status_labels = page["draft_statuses"]
    st.write(f"{page['column_version']}: v{draft.quote_version}")
    st.write(f"{page['draft_status_label']}: {status_labels.get(draft.status.value, draft.status.value)}")
    st.write(f"{page['summary_completeness']}: {page['completeness'].get(draft.completeness.value, draft.completeness.value)}")
    _render_internal_bom(page, draft)
    _render_2601_choice(page, draft)
    _render_customer_preview(page, draft)


def _render_internal_bom(page: dict, draft) -> None:
    st.markdown(f"**{page['internal_bom_label']}**")
    presentation_labels = page["presentation_modes"]
    st.table(
        [
            {
                page["column_sku"]: line.manufacturer_sku or page["no_value"],
                page["column_name_ja"]: line.manufacturer_description or page["no_value"],
                page["column_requirement"]: line.requirement_type.value,
                page["column_dealer_usd"]: _display_number(line.dealer_price_usd, page),
                page["column_landed"]: _display_number(line.landed_cost_jpy, page),
                page["column_sales_candidate"]: _display_number(line.standard_sales_price_candidate_jpy, page),
                page["column_final_price"]: _display_number(line.final_sales_price_jpy, page),
                page["column_presentation"]: presentation_labels.get(
                    line.customer_presentation_status.value, line.customer_presentation_status.value
                ),
                page["golden_warning"]: "; ".join(line.warnings) or page["no_value"],
            }
            for line in draft.configuration_lines
        ]
    )
    for line in draft.configuration_lines:
        if line.customer_presentation_status != CustomerPresentationMode.SEPARATE_LINE:
            continue
        if st.button(page["use_standard_button"], key=f"use_standard_{line.line_id}"):
            apply_final_price(draft, line.line_id, FinalPriceStatus.USE_STANDARD_CANDIDATE)
            st.session_state["quote_draft"] = draft
            st.rerun()
        entered = st.text_input(page["manual_price_label"], key=f"manual_price_{line.line_id}")
        if st.button(page["apply_manual_price_button"], key=f"apply_manual_{line.line_id}"):
            try:
                apply_final_price(
                    draft,
                    line.line_id,
                    FinalPriceStatus.MANUAL_OVERRIDE,
                    amount_jpy=float(entered),
                    reason="UI manual override",
                )
                st.session_state["quote_draft"] = draft
                st.rerun()
            except (TypeError, ValueError):
                st.warning(page["exchange_rate_invalid"])


def _render_2601_choice(page: dict, draft) -> None:
    target = next((line for line in draft.configuration_lines if line.manufacturer_sku == "2601"), None)
    if target is None:
        return
    parent = next((line for line in draft.configuration_lines if line.manufacturer_sku == "2604"), None)
    choice = st.radio(
        page["dependency_choice_label"],
        options=["UNDECIDED", "SEPARATE_LINE", "BUNDLED_WITH_PARENT"],
        format_func=lambda key: {
            "UNDECIDED": page["dependency_undecided"],
            "SEPARATE_LINE": page["dependency_separate"],
            "BUNDLED_WITH_PARENT": page["dependency_bundle"],
        }[key],
        key="input_2601_presentation",
    )
    if st.button(page["apply_2601_button"], key="apply_2601_presentation"):
        apply_presentation_mode(
            draft,
            target.line_id,
            CustomerPresentationMode(choice),
            bundled_into_line_id=parent.line_id if choice == "BUNDLED_WITH_PARENT" and parent else None,
        )
        st.session_state["quote_draft"] = draft
        st.rerun()


def _render_customer_preview(page: dict, draft) -> None:
    st.markdown(f"**{page['customer_preview_label']}**")
    st.table(
        [
            {
                page["column_item"]: row["display_name"],
                page["column_item_detail"]: row["description"],
                page["column_unit_price"]: _display_number(row["unit_price_jpy"], page),
                page["column_qty"]: row["quantity"],
                page["column_amount"]: _display_number(row["amount_jpy"], page),
            }
            for row in customer_preview_rows(draft)
        ]
    )
    st.write(f"{page['golden_subtotal']}: {_display_number(draft.subtotal_ex_tax_jpy, page)}")
    st.write(f"{page['column_import_tax']}: {_display_number(draft.tax_jpy, page)}")
    st.write(f"{page['golden_total']}: {_display_number(draft.total_jpy, page)}")
    st.markdown(f"**{page['remarks_label']}**")
    st.caption(page["remarks_caption"])
    for remark in draft.remark_candidates:
        st.write(f"[{remark.source.value}] {remark.text}")
    tax_text = st.text_input(page["tax_rate_label"], key="input_draft_tax_rate")
    if tax_text and st.button(page["apply_manual_price_button"], key="apply_draft_tax"):
        try:
            apply_tax_rate(draft, float(tax_text))
            st.session_state["quote_draft"] = draft
            st.rerun()
        except (TypeError, ValueError):
            st.warning(page["exchange_rate_invalid"])
    shipping_text = st.text_input(page["shipping_price_label"], key="input_draft_shipping_price")
    if shipping_text and st.button(page["apply_shipping_price_button"], key="apply_draft_shipping"):
        try:
            apply_shipping_final_price(draft, float(shipping_text))
            st.session_state["quote_draft"] = draft
            st.rerun()
        except (TypeError, ValueError):
            st.warning(page["exchange_rate_invalid"])


def _render_quote_approval(page: dict) -> None:
    st.subheader(page["section_quote_approval"])
    st.write(page["section_quote_approval_description"])
    store = _ensure_quote_approval_store()
    draft = st.session_state.get("quote_draft")
    snapshot = st.session_state.get("approved_quote_snapshot")
    if draft is None:
        st.text(page["no_quote_draft"])
        if snapshot is None:
            _render_file_export(page, None)
            return
    else:
        status_labels = page["draft_statuses"]
        economics = draft.economics_result
        st.write(f"{page['column_version']}: v{draft.quote_version}")
        st.write(f"{page['draft_status_label']}: {status_labels.get(draft.status.value, draft.status.value)}")
        st.write(f"{page['column_customer']}: {draft.customer or page['no_value']}")
        st.write(f"{page['column_title']}: {draft.title or page['no_value']}")
        st.write(f"{page['golden_subtotal']}: {_display_number(draft.subtotal_ex_tax_jpy, page)}")
        st.write(f"{page['column_import_tax']}: {_display_number(draft.tax_jpy, page)}")
        st.write(f"{page['golden_total']}: {_display_number(draft.total_jpy, page)}")
        st.write(f"{page['column_landed_total']}: {_display_number(economics.total_landed_cost_jpy if economics else None, page)}")
        st.write(f"{page['column_gross_profit']}: {_display_number(economics.gross_profit_jpy if economics else None, page)}")
        st.write(f"{page['column_gross_margin']}: {_display_percent(economics.gross_margin_rate if economics else None, page)}")
        if draft.warnings:
            st.warning("\n".join(draft.warnings))
        selected_remarks = st.multiselect(
            page["select_remarks_label"],
            options=[item.text for item in draft.remark_candidates],
            default=[item.text for item in draft.remark_candidates if item.selected],
            key="input_selected_remarks",
        )
        lead_time = st.text_input(page["lead_time_label"], value=draft.lead_time_text or "", key="input_lead_time")
        issue_date, valid_until = _render_quote_date_inputs(page, draft)
        confirm_configuration = st.checkbox(page["confirm_configuration"], key="confirm_configuration")
        confirm_presentation = st.checkbox(page["confirm_presentation"], key="confirm_presentation")
        confirm_sales_price = st.checkbox(page["confirm_sales_price"], key="confirm_sales_price")
        confirm_remarks = st.checkbox(page["confirm_remarks"], key="confirm_remarks")
        if draft.configuration_name == "PHOTON" and draft.status != QuoteDraftStatus.APPROVED:
            if st.button(page["photon_human_final_button"], key="photon_human_final"):
                try:
                    apply_ihi_photon_human_final_fixture(draft)
                    _sync_date_widgets_from_draft(draft, auto=False)
                    st.session_state["quote_draft"] = draft
                    st.rerun()
                except ValueError:
                    st.warning(page["approved_draft_locked"])
        if st.button(page["confirm_ready_button"], key="check_quote_approval"):
            try:
                apply_selected_remarks(draft, selected_remarks)
                apply_lead_time_text(draft, lead_time or None)
                apply_issue_date(draft, issue_date or None)
                apply_valid_until(draft, valid_until or None)
            except ValueError:
                st.warning(page["approved_draft_locked"])
            st.session_state["quote_approval_validation"] = validate_for_approval(draft)
            st.session_state["quote_draft"] = draft
        validation = st.session_state.get("quote_approval_validation")
        if validation is not None:
            if validation.can_approve:
                st.success(page["approval_ready"])
            else:
                st.error(validation.blocking_reason or page["approval_blocked"])
            if validation.critical_warnings:
                st.error("\n".join(validation.critical_warnings))
            if validation.regular_warnings:
                st.warning("\n".join(validation.regular_warnings))
        ready_to_approve = (
            draft.status == QuoteDraftStatus.READY_FOR_APPROVAL
            and validation is not None
            and validation.can_approve
            and confirm_configuration
            and confirm_presentation
            and confirm_sales_price
            and confirm_remarks
        )
        if ready_to_approve and st.button(page["approve_snapshot_button"], key="approve_quote_snapshot"):
            try:
                apply_selected_remarks(draft, selected_remarks)
                apply_lead_time_text(draft, lead_time or None)
                apply_issue_date(draft, issue_date or None)
                apply_valid_until(draft, valid_until or None)
                approval, snapshot = approve_quote(
                    draft,
                    approved_by="弦",
                    confirmations={
                        "configuration": confirm_configuration,
                        "presentation": confirm_presentation,
                        "sales_price": confirm_sales_price,
                        "remarks": confirm_remarks,
                    },
                    warnings_acknowledged=list(validation.regular_warnings),
                    store=store,
                )
                st.session_state["quote_draft"] = draft
                st.session_state["quote_approval"] = approval
                st.session_state["approved_quote_snapshot"] = snapshot
                st.session_state["quote_outputs"] = generate_quote_outputs(snapshot)
                st.rerun()
            except (QuoteApprovalError, ValueError) as error:
                st.error(str(error))
        if snapshot is not None and st.button(page["create_revision_button"], key="create_quote_revision"):
            revision = create_revision_draft(snapshot, store=store)
            st.session_state["quote_draft"] = revision
            st.session_state["quote_approval_validation"] = None
            st.rerun()
    snapshot = st.session_state.get("approved_quote_snapshot")
    if snapshot is None:
        st.text(page["no_approved_snapshot"])
        _render_file_export(page, None)
        return
    st.markdown(f"**{page['output_preview_label']}**")
    st.write(f"{page['quote_number_candidate_label']}: {snapshot.quote_number_candidate or page['no_value']}")
    outputs = st.session_state.get("quote_outputs") or generate_quote_outputs(snapshot)
    internal_tab, spaceone_tab, moneyforward_tab = st.tabs(
        [page["tab_internal_transfer"], page["tab_spaceone_quote"], page["tab_moneyforward"]]
    )
    with internal_tab:
        st.table(
            [
                {
                    "Part Number": row.part_number,
                    page["column_name_ja"]: row.item_name,
                    page["column_qty"]: row.quantity,
                    "DT USD": _display_number(row.dealer_unit_price_usd, page),
                    page["column_landed"]: _display_number(row.landed_subtotal_jpy, page),
                    page["column_final_price"]: _display_number(row.adjusted_unit_price_jpy, page),
                    page["column_gross_margin"]: _display_percent(row.gross_margin_rate, page),
                }
                for row in outputs.internal_transfer.rows
            ]
        )
        st.write(f"{page['golden_total']}: {_display_number(outputs.internal_transfer.customer_total_jpy, page)}")
    with spaceone_tab:
        st.write(f"{page['column_customer']}: {outputs.spaceone_quote.customer or page['no_value']}")
        st.write(f"{page['column_title']}: {outputs.spaceone_quote.title or page['no_value']}")
        st.table(
            [
                {
                    page["column_item"]: line.item_name,
                    page["column_item_detail"]: line.item_detail,
                    page["column_unit_price"]: _display_number(line.unit_price_jpy, page),
                    page["column_qty"]: line.quantity,
                    page["column_amount"]: _display_number(line.amount_jpy, page),
                }
                for line in outputs.spaceone_quote.lines
            ]
        )
        st.write(f"{page['golden_subtotal']}: {_display_number(outputs.spaceone_quote.subtotal, page)}")
        st.write(f"{page['column_import_tax']}: {_display_number(outputs.spaceone_quote.tax, page)}")
        st.write(f"{page['golden_total']}: {_display_number(outputs.spaceone_quote.total, page)}")
        if outputs.spaceone_quote.remarks:
            st.markdown(f"**{page['remarks_label']}**")
            for remark in outputs.spaceone_quote.remarks:
                st.write(remark)
    with moneyforward_tab:
        st.table(
            [
                {
                    page["column_item"]: row.item_name,
                    page["column_item_detail"]: row.item_detail,
                    page["column_unit_price"]: _display_number(row.unit_price_jpy, page),
                    page["column_qty"]: row.quantity,
                    page["column_amount"]: _display_number(row.amount_jpy, page),
                    page["column_notes"]: row.notes or page["no_value"],
                }
                for row in outputs.moneyforward.rows
            ]
        )
        st.text_area(page["mf_tsv_label"], value=outputs.moneyforward.tsv_preview, height=180)
        st.write(f"{page['golden_total']}: {_display_number(outputs.moneyforward.total_jpy, page)}")
    _render_file_export(page, snapshot)


def _render_file_export(page: dict, snapshot) -> None:
    st.markdown(f"**{page['section_file_export']}**")
    st.write(page["section_file_export_description"])
    st.caption(f"{page['export_development_label']} / {page['export_formal_label']}")
    if snapshot is None:
        st.text(page["export_requires_snapshot"])
        return
    official = st.text_input(page["official_quote_number_label"], key="input_official_quote_number")
    st.caption(page["official_quote_number_caption"])
    generated_by = st.text_input(page["generated_by_label"], value="弦", key="input_export_generated_by")
    columns = st.columns(2)
    with columns[0]:
        if st.button(page["export_mf_tsv_button"], key="export_mf_tsv"):
            _run_export(page, snapshot, export_moneyforward_tsv, official, generated_by, ExportPurpose.DEVELOPMENT)
        if st.button(page["export_internal_button"], key="export_internal_xlsx"):
            _run_export(page, snapshot, export_internal_calc_excel, official, generated_by, ExportPurpose.DEVELOPMENT)
    with columns[1]:
        if st.button(page["export_mf_csv_button"], key="export_mf_csv"):
            _run_export(page, snapshot, export_moneyforward_csv, official, generated_by, ExportPurpose.DEVELOPMENT)
        if st.button(page["export_spaceone_button"], key="export_spaceone_xlsx"):
            _run_export(page, snapshot, export_spaceone_quote_excel, official, generated_by, ExportPurpose.FORMAL)
    saved = st.session_state.get("quote_export_files") or []
    if not saved:
        st.text(page["no_export_yet"])
        return
    for item in saved:
        st.write(f"{page['export_saved']}: {item}")


def _run_export(page: dict, snapshot, exporter, official: str, generated_by: str, purpose) -> None:
    try:
        _bundle, path = exporter(
            snapshot,
            official_quote_number=official or None,
            generated_by=generated_by or None,
            purpose=purpose,
        )
        saved = list(st.session_state.get("quote_export_files") or [])
        saved.append(str(path))
        st.session_state["quote_export_files"] = saved
        st.success(f"{page['export_saved']}: {path.name}")
    except QuoteExportError as error:
        st.error(str(error))


def _ensure_quote_approval_store() -> QuoteApprovalStore:
    if "quote_approval_store" not in st.session_state:
        st.session_state["quote_approval_store"] = QuoteApprovalStore()
    return st.session_state["quote_approval_store"]


def _render_quote_date_inputs(page: dict, draft):
    auto_key = f"input_auto_valid_{draft.quote_draft_id}"
    issue_key = f"input_issue_date_{draft.quote_draft_id}"
    valid_key = f"input_valid_until_{draft.quote_draft_id}"
    issue_default = parse_quote_date(draft.issue_date) or tokyo_today()
    valid_default = parse_quote_date(draft.valid_until) or add_one_calendar_month(issue_default)
    if auto_key not in st.session_state:
        st.session_state[auto_key] = valid_until_matches_auto_rule(issue_default, valid_default)
    if issue_key not in st.session_state:
        st.session_state[issue_key] = issue_default
    if valid_key not in st.session_state:
        st.session_state[valid_key] = valid_default
    auto = st.checkbox(page["auto_valid_until_label"], key=auto_key)
    issue_date = st.date_input(page["issue_date_label"], key=issue_key, format="YYYY/MM/DD")
    if auto:
        computed = next_valid_until(issue_date, auto=True)
        if st.session_state.get(valid_key) != computed:
            st.session_state[valid_key] = computed
    valid_until = st.date_input(
        page["valid_until_label"],
        key=valid_key,
        format="YYYY/MM/DD",
        disabled=auto,
    )
    if draft.status not in {QuoteDraftStatus.APPROVED, QuoteDraftStatus.SUPERSEDED}:
        apply_issue_date(draft, issue_date)
        apply_valid_until(draft, valid_until if not auto else next_valid_until(issue_date, auto=True))
    return issue_date, valid_until


def _sync_date_widgets_from_draft(draft, *, auto: Optional[bool] = None) -> None:
    issue = parse_quote_date(draft.issue_date) or tokyo_today()
    valid = parse_quote_date(draft.valid_until) or add_one_calendar_month(issue)
    st.session_state[f"input_issue_date_{draft.quote_draft_id}"] = issue
    st.session_state[f"input_valid_until_{draft.quote_draft_id}"] = valid
    if auto is None:
        auto = valid_until_matches_auto_rule(issue, valid)
    st.session_state[f"input_auto_valid_{draft.quote_draft_id}"] = auto


def _display_percent(value, page: dict) -> str:
    if value is None:
        return page["no_value"]
    return f"{value:.2%}"


def _build_ihi_draft_from_ui(page: dict, case: dict, configuration: str):
    rate_text = st.session_state.get("input_landed_exchange_rate") or st.session_state.get("input_ihi_landed_rate") or "170"
    try:
        rate = float(rate_text)
    except (TypeError, ValueError):
        st.warning(page["exchange_rate_invalid"])
        return None
    books = load_official_manufacturer_price_books()
    candidates = collect_manufacturer_candidates(*books) if books else []
    dealer_values = resolve_ihi_dealer_values(candidates)
    sales = st.session_state.get(SESSION_SALES_CANDIDATES) or []
    policy = _extracted_landed_policy()
    if policy is None or policy.import_tax_rate is None:
        policy = policy_from_inputs(
            import_tax_rate=_optional_float(st.session_state.get("input_landed_import_tax")),
            insurance_mode=InsuranceMode.PERCENTAGE,
            insurance_rate=_optional_float(st.session_state.get("input_landed_insurance_rate")),
            shipping_markup_multiplier=_extracted_shipping_markup(),
            domestic_shipping_mode=DomesticShippingMode.REVIEW_REQUIRED,
        )
    scenario, _economics = build_ihi_landed_cost_scenario(
        configuration,
        exchange_rate=rate,
        policy=policy,
        dealer_values=dealer_values,
        sales_candidates=sales,
        price_book_candidates=candidates,
    )
    quote = case["photon_customer_quote"] if configuration == "PHOTON" else case["mag_customer_quote"]
    draft = build_ihi_quote_draft(
        configuration,
        scenario,
        sales,
        tax_rate=_optional_float(st.session_state.get("input_draft_tax_rate")),
    )
    apply_historical_acceptance_preview(draft, quote)
    return draft


def _ensure_official_master() -> None:
    if SESSION_OFFICIAL_MASTER not in st.session_state:
        st.session_state[SESSION_OFFICIAL_MASTER] = SkuMasterStore()


def _ensure_update_inbox() -> UpdateInboxStore:
    if SESSION_UPDATE_INBOX not in st.session_state:
        st.session_state[SESSION_UPDATE_INBOX] = UpdateInboxStore()
    return st.session_state[SESSION_UPDATE_INBOX]
