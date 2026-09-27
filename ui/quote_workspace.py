from datetime import datetime

import streamlit as st

from agents.quote_approval import (
    QuoteApprovalError,
    apply_ihi_photon_human_final_fixture,
    approve_quote,
    create_revision_draft,
    generate_quote_outputs,
    validate_for_approval,
)
from agents.quote_builder import (
    apply_final_price,
    apply_issue_date,
    apply_lead_time_text,
    apply_presentation_mode,
    apply_selected_remarks,
    apply_shipping_final_price,
    apply_tax_rate,
    apply_valid_until,
    refresh_quote_draft,
)
from agents.quote_dates import date_widget_keys, format_quote_date
from data.golden_cases.loader import IHI_QUOTE_001, load_quote_golden_case
from models import CustomerPresentationMode, FinalPriceStatus, QuoteDraftStatus
from repositories.quote_repository import QuoteRepositoryError
from ui.components.portal import (
    render_portal_section_title,
    render_product_choice_card,
    render_recent_draft_list,
    resume_draft_into_session,
)
from ui.components.quote_action_bar import render_quote_action_bar
from ui.components.quote_cards import (
    render_configuration_card,
    render_price_adjustment,
)
from ui.components.quote_header import render_quote_header
from ui.components.quote_stepper import render_quote_stepper
from ui.components.quote_summary import render_costing_summary, render_summary_cards
from ui.components.warning_panel import render_validation_warnings, render_warning_panel
from ui.quote_format import display_number, display_percent, display_yen
from ui.quote_persistence import (
    PENDING_FORM_KEY,
    SESSION_SAVE_ERROR,
    SESSION_SAVE_STATUS,
    clear_pending_description,
    clear_pending_final_price,
    clear_pending_presentation,
    clear_pending_shipping,
    clear_pending_tax,
    customer_description_widget_key,
    get_quote_repository,
    maybe_autosave,
    reset_pending_form,
    restore_pending_form_widgets,
    save_draft_now,
)
from ui.quote_steps import (
    SESSION_QUOTE_STEP,
    customer_facing_preview,
    normalize_quote_step,
    restore_review_widget_state,
    save_review_widget_state,
    separate_product_lines,
    shipping_customer_lines,
)


def render_quote_workspace(page: dict, helpers: dict) -> None:
    restore_review_widget_state(st.session_state)
    restore_pending_form_widgets(st.session_state, st.session_state.get("quote_draft"))
    draft = st.session_state.get("quote_draft")
    snapshot = st.session_state.get("approved_quote_snapshot")
    validation = st.session_state.get("quote_approval_validation")
    current = normalize_quote_step(st.session_state.get(SESSION_QUOTE_STEP, 1))
    render_quote_header(page, draft, snapshot)
    st.divider()
    selected = render_quote_stepper(page, current, draft, snapshot, validation)
    if selected != current:
        st.session_state[SESSION_QUOTE_STEP] = selected
        st.rerun()
    st.divider()
    if draft is None:
        _render_draft_start(page, helpers)
        if current == 5:
            _render_step_export(page, helpers, None, snapshot)
        elif current != 1:
            st.info(page["workspace"]["no_current_step_detail"])
    else:
        with st.expander(page["workspace"].get("new_quote_label", "新しい見積を作成"), expanded=False):
            _render_new_quote_buttons(page, helpers)
        if current == 1:
            _render_step_configuration(page, draft)
        elif current == 2:
            _render_step_costing(page, draft)
        elif current == 3:
            _render_step_customer(page, draft)
        elif current == 4:
            _render_step_review(page, helpers, draft, snapshot)
        else:
            _render_step_export(page, helpers, draft, snapshot)
    st.divider()
    next_step, save_clicked = render_quote_action_bar(page, current, can_save=draft is not None)
    if save_clicked and draft is not None:
        _save_draft(page, draft, manual=True)
    elif draft is not None:
        _save_draft(page, draft, manual=False)
    if next_step != current:
        st.session_state[SESSION_QUOTE_STEP] = next_step
        st.rerun()


def _render_draft_start(page: dict, helpers) -> None:
    workspace = page["workspace"]
    render_portal_section_title(workspace.get("recent_drafts_label", "最近の下書き"))
    items = get_quote_repository().list_recent_drafts(limit=8)
    render_recent_draft_list(
        page,
        items,
        resume_key_prefix="resume_draft_",
        on_resume=lambda draft_id, version: _resume_draft(page, helpers, draft_id, version),
    )
    st.markdown("<hr class='section-rule' />", unsafe_allow_html=True)
    st.subheader(page["section_quote_builder"])
    st.caption(workspace.get("new_quote_label", "新しい見積を作成"))
    _render_new_quote_buttons(page, helpers)
    if st.session_state.get("quote_draft") is None and not items:
        st.text(page["no_quote_draft"])


def _render_new_quote_buttons(page: dict, helpers) -> None:
    st.write(page["section_quote_builder_description"])
    st.caption(page["quote_builder_hint"])
    case = load_quote_golden_case(IHI_QUOTE_001)
    left, right = st.columns(2)
    with left:
        render_product_choice_card("PHOTON", page["ihi_photon_draft_button"])
        if st.button(page["ihi_photon_draft_button"], key="ihi_photon_draft"):
            _create_draft(page, helpers, case, "PHOTON")
    with right:
        render_product_choice_card("MAG", page["ihi_mag_draft_button"])
        if st.button(page["ihi_mag_draft_button"], key="ihi_mag_draft"):
            _create_draft(page, helpers, case, "MAG")


def _create_draft(page: dict, helpers, case: dict, configuration: str) -> None:
    draft = helpers["create_ihi_draft"](page, case, configuration)
    st.session_state["quote_draft"] = draft
    if draft is not None:
        helpers["init_date_widgets"](draft, overwrite=True)
        st.session_state[SESSION_QUOTE_STEP] = 1
        reset_pending_form(st.session_state, 1)
        _save_draft(page, draft, manual=True, from_widgets=False)
        st.rerun()


def _render_step_configuration(page: dict, draft) -> None:
    workspace = page["workspace"]
    st.subheader(workspace["step_configuration"])
    render_warning_panel(page, draft)
    empty = workspace.get("unset_label", "未設定")
    presentation_labels = page["presentation_modes"]
    st.table(
        [
            {
                page["column_sku"]: line.manufacturer_sku or empty,
                page["column_name_ja"]: line.manufacturer_description or empty,
                page["column_qty"]: line.quantity,
                page["column_presentation"]: presentation_labels.get(
                    line.customer_presentation_status.value,
                    line.customer_presentation_status.value,
                ),
                workspace.get("column_status", "状態"): _line_status_label(workspace, line),
            }
            for line in draft.configuration_lines
        ]
    )
    for line in draft.configuration_lines:
        render_configuration_card(page, line)
    _render_2601_choice(page, draft)


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
        clear_pending_presentation(st.session_state)
        st.session_state["quote_draft"] = draft
        st.rerun()


def _render_step_costing(page: dict, draft) -> None:
    st.subheader(page["workspace"]["step_costing"])
    render_warning_panel(page, draft)
    _render_pending_price_key_reviews(page)
    render_costing_summary(page, draft)
    empty = page["workspace"].get("unset_label", "未設定")
    st.table(
        [
            {
                page["column_sku"]: line.manufacturer_sku or empty,
                page["column_name_ja"]: line.manufacturer_description or empty,
                page["column_landed"]: display_yen(line.landed_cost_jpy, empty),
                page["column_sales_candidate"]: display_yen(line.standard_sales_price_candidate_jpy, empty),
                page["column_final_price"]: display_yen(line.final_sales_price_jpy, empty),
            }
            for line in draft.configuration_lines
        ]
    )
    for line in separate_product_lines(draft):
        render_price_adjustment(page, line)
        if st.button(page["use_standard_button"], key=f"use_standard_{line.line_id}"):
            apply_final_price(draft, line.line_id, FinalPriceStatus.USE_STANDARD_CANDIDATE)
            clear_pending_final_price(st.session_state, line)
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
                clear_pending_final_price(st.session_state, line)
                st.session_state["quote_draft"] = draft
                st.rerun()
            except (TypeError, ValueError):
                st.warning(page["exchange_rate_invalid"])
    st.markdown(f"**{page['workspace']['shipping_section']}**")
    shipping_rows = shipping_customer_lines(draft)
    if shipping_rows:
        st.table(
            [
                {
                    page["column_item"]: line.display_name,
                    page["column_item_detail"]: line.description,
                    page["column_amount"]: display_yen(line.amount_jpy, empty),
                }
                for line in shipping_rows
            ]
        )
    shipping_text = st.text_input(page["shipping_price_label"], key="input_draft_shipping_price")
    if shipping_text and st.button(page["apply_shipping_price_button"], key="apply_draft_shipping"):
        try:
            apply_shipping_final_price(draft, float(shipping_text))
            clear_pending_shipping(st.session_state)
            st.session_state["quote_draft"] = draft
            st.rerun()
        except (TypeError, ValueError):
            st.warning(page["exchange_rate_invalid"])
    with st.expander(page["workspace"]["see_details"], expanded=False):
        st.table(
            [
                {
                    page["column_sku"]: line.manufacturer_sku or empty,
                    page["column_dealer_usd"]: display_number(line.dealer_price_usd, empty),
                    page["column_dealer_jpy"]: display_yen(line.dealer_cost_jpy, empty),
                    page["column_landed"]: display_yen(line.landed_cost_jpy, empty),
                }
                for line in draft.configuration_lines
            ]
        )


def _render_step_customer(page: dict, draft) -> None:
    st.subheader(page["workspace"]["step_customer"])
    empty = page["workspace"].get("unset_label", "未設定")
    rows = customer_facing_preview(draft)
    st.table(
        [
            {
                page["column_item"]: row.get("display_name") or empty,
                page["column_item_detail"]: row.get("description") or empty,
                page["column_qty"]: row.get("quantity") or 1,
                page["column_unit_price"]: display_yen(row.get("unit_price_jpy"), empty),
                page["column_amount"]: display_yen(row.get("amount_jpy"), empty),
            }
            for row in rows
        ]
    )
    for row in rows:
        line_id = row.get("customer_quote_line_id") or row.get("display_name")
        if not line_id:
            continue
        key = customer_description_widget_key(str(line_id))
        st.text_area(
            f"{page['column_item_detail']}：{row.get('display_name') or empty}",
            key=key,
        )
        if row.get("line_kind") == "SHIPPING":
            continue
        if st.button(page.get("apply_description_button", "説明を反映"), key=f"apply_description_{line_id}"):
            _apply_pending_description(draft, row, st.session_state.get(key) or "")
            clear_pending_description(st.session_state, str(line_id))
            st.session_state["quote_draft"] = draft
            st.rerun()
    st.markdown("<hr class='section-rule' />", unsafe_allow_html=True)
    render_summary_cards(
        [
            (page["golden_subtotal"], display_yen(draft.subtotal_ex_tax_jpy, None)),
            (page["column_import_tax"], display_yen(draft.tax_jpy, None)),
            (page["golden_total"], display_yen(draft.total_jpy, None)),
        ],
        unset_label=empty,
    )
    tax_text = st.text_input(page["tax_rate_label"], key="input_draft_tax_rate")
    if tax_text and st.button(page["apply_manual_price_button"], key="apply_draft_tax"):
        try:
            apply_tax_rate(draft, float(tax_text))
            clear_pending_tax(st.session_state)
            st.session_state["quote_draft"] = draft
            st.rerun()
        except (TypeError, ValueError):
            st.warning(page["exchange_rate_invalid"])


def _render_step_review(page: dict, helpers, draft, snapshot) -> None:
    workspace = page["workspace"]
    st.subheader(page["section_quote_approval"])
    st.write(page["section_quote_approval_description"])
    render_warning_panel(page, draft)
    store = helpers["ensure_store"]()
    st.markdown(f"**{workspace['review_heading']}**")
    selected_remarks = st.multiselect(
        page["select_remarks_label"],
        options=[item.text for item in draft.remark_candidates],
        default=[item.text for item in draft.remark_candidates if item.selected],
        key="input_selected_remarks",
    )
    lead_time = st.text_input(page["lead_time_label"], value=draft.lead_time_text or "", key="input_lead_time")
    issue_date, valid_until = helpers["render_dates"](page, draft)
    confirm_configuration = st.checkbox(page["confirm_configuration"], key="confirm_configuration")
    confirm_presentation = st.checkbox(page["confirm_presentation"], key="confirm_presentation")
    confirm_sales_price = st.checkbox(page["confirm_sales_price"], key="confirm_sales_price")
    confirm_remarks = st.checkbox(page["confirm_remarks"], key="confirm_remarks")
    save_review_widget_state(st.session_state)
    _render_confirmation_table(
        page,
        {
            page["confirm_configuration"]: confirm_configuration,
            page["confirm_presentation"]: confirm_presentation,
            page["confirm_sales_price"]: confirm_sales_price,
            page["confirm_remarks"]: confirm_remarks,
        },
    )
    if draft.configuration_name == "PHOTON" and draft.status != QuoteDraftStatus.APPROVED:
        if st.button(page["photon_human_final_button"], key="photon_human_final"):
            try:
                apply_ihi_photon_human_final_fixture(draft)
                st.session_state["quote_draft"] = draft
                st.session_state[date_widget_keys(draft.quote_draft_id)["pending"]] = True
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
    _render_approval_state(page, draft, validation)
    render_validation_warnings(page, validation)
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
            st.session_state[SESSION_QUOTE_STEP] = 5
            try:
                get_quote_repository().save_snapshot(snapshot)
                _save_draft(page, draft, manual=True)
            except QuoteRepositoryError as error:
                st.session_state[SESSION_SAVE_ERROR] = str(error)
                st.error(page["workspace"].get("save_failed", str(error)))
            st.rerun()
        except (QuoteApprovalError, ValueError) as error:
            st.error(str(error))
    if snapshot is not None and st.button(page["create_revision_button"], key="create_quote_revision"):
        revision = create_revision_draft(snapshot, store=store)
        helpers["init_date_widgets"](revision, overwrite=True)
        st.session_state["quote_draft"] = revision
        st.session_state["quote_approval_validation"] = None
        st.session_state[SESSION_QUOTE_STEP] = 1
        _save_draft(page, revision, manual=True)
        st.rerun()


def _render_approval_state(page: dict, draft, validation) -> None:
    workspace = page["workspace"]
    status_labels = page["draft_statuses"]
    st.markdown(f"**{workspace['approval_state']}**")
    st.write(f"{page['draft_status_label']}：{status_labels.get(draft.status.value, draft.status.value)}")
    if validation is None:
        st.info(workspace["approval_not_checked"])
        return
    if validation.can_approve:
        st.success(page["approval_ready"])
    else:
        st.error(validation.blocking_reason or page["approval_blocked"])
        st.write(workspace["approval_needs"])


def _render_step_export(page: dict, helpers, draft, snapshot) -> None:
    workspace = page["workspace"]
    st.subheader(page["section_file_export"])
    if snapshot is None:
        st.warning(workspace["export_needs_approval"])
        helpers["render_export"](page, None)
        return
    st.success(workspace["approved_heading"])
    st.write(f"{page['column_version']}: v{snapshot.quote_version}")
    st.write(f"{workspace['approved_by']}: {snapshot.approved_by or page['no_value']}")
    approved_at = snapshot.approved_at
    if isinstance(approved_at, datetime):
        st.write(format_quote_date(approved_at.date()) + approved_at.strftime(" %H:%M"))
    st.caption(f"{workspace['formal_output']} / {workspace['development_output']}")
    outputs = st.session_state.get("quote_outputs") or generate_quote_outputs(snapshot)
    st.markdown(f"**{page['output_preview_label']}**")
    st.write(f"{page['quote_number_candidate_label']}: {snapshot.quote_number_candidate or page['no_value']}")
    internal_tab, spaceone_tab, moneyforward_tab = st.tabs(
        [page["tab_internal_transfer"], page["tab_spaceone_quote"], page["tab_moneyforward"]]
    )
    empty = page["no_value"]
    with internal_tab:
        st.table(
            [
                {
                    "Part Number": row.part_number,
                    page["column_name_ja"]: row.item_name,
                    page["column_qty"]: row.quantity,
                    "DT USD": display_number(row.dealer_unit_price_usd, empty),
                    page["column_landed"]: display_number(row.landed_subtotal_jpy, empty),
                    page["column_final_price"]: display_number(row.adjusted_unit_price_jpy, empty),
                    page["column_gross_margin"]: display_percent(row.gross_margin_rate, empty),
                }
                for row in outputs.internal_transfer.rows
            ]
        )
        st.write(f"{page['golden_total']}: {display_number(outputs.internal_transfer.customer_total_jpy, empty)}")
    with spaceone_tab:
        st.write(f"{page['column_customer']}: {outputs.spaceone_quote.customer or empty}")
        st.write(f"{page['column_title']}: {outputs.spaceone_quote.title or empty}")
        st.table(
            [
                {
                    page["column_item"]: line.item_name,
                    page["column_item_detail"]: line.item_detail,
                    page["column_unit_price"]: display_number(line.unit_price_jpy, empty),
                    page["column_qty"]: line.quantity,
                    page["column_amount"]: display_number(line.amount_jpy, empty),
                }
                for line in outputs.spaceone_quote.lines
            ]
        )
        st.write(f"{page['golden_subtotal']}: {display_number(outputs.spaceone_quote.subtotal, empty)}")
        st.write(f"{page['column_import_tax']}: {display_number(outputs.spaceone_quote.tax, empty)}")
        st.write(f"{page['golden_total']}: {display_number(outputs.spaceone_quote.total, empty)}")
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
                    page["column_unit_price"]: display_number(row.unit_price_jpy, empty),
                    page["column_qty"]: row.quantity,
                    page["column_amount"]: display_number(row.amount_jpy, empty),
                    page["column_notes"]: row.notes or empty,
                }
                for row in outputs.moneyforward.rows
            ]
        )
        st.text_area(page["mf_tsv_label"], value=outputs.moneyforward.tsv_preview, height=180)
        st.write(f"{page['golden_total']}: {display_number(outputs.moneyforward.total_jpy, empty)}")
    helpers["render_export"](page, snapshot)


def render_quote_debug_details(page: dict) -> None:
    draft = st.session_state.get("quote_draft")
    snapshot = st.session_state.get("approved_quote_snapshot")
    if draft is None and snapshot is None:
        st.text(page["no_quote_draft"])
        return
    if draft is not None:
        st.write(f"{page['workspace']['draft_id_label']}: {draft.quote_draft_id}")
        st.write(f"{page['column_version']}: v{draft.quote_version}")
        st.write(f"status: {draft.status.value}")
        if draft.source_references:
            st.write("Source Reference")
            for item in draft.source_references:
                st.caption(item)
        if draft.warnings:
            st.write("Raw Warning")
            for item in draft.warnings:
                st.caption(item)
        if draft.pricing_context.manufacturer_price_snapshots:
            st.write("Manufacturer Price Snapshot")
            for item in draft.pricing_context.manufacturer_price_snapshots:
                st.caption(f"{item.sku} / {item.price_book or ''} / {item.source_reference or ''}")
        if draft.pricing_context.pricing_policy_candidate_ids:
            st.write("Pricing Policy Reference")
            st.caption(", ".join(draft.pricing_context.pricing_policy_candidate_ids))
        if draft.pricing_context.landed_cost_policy_snapshot:
            st.write("Landed Cost Policy")
            st.caption(draft.pricing_context.landed_cost_policy_snapshot.landed_cost_policy_candidate_id or "")
    if snapshot is not None:
        st.write(f"Approved Snapshot: {snapshot.approved_quote_snapshot_id}")
        st.write(f"{page['quote_number_candidate_label']}: {snapshot.quote_number_candidate or page['no_value']}")
        for item in snapshot.source_references:
            st.caption(item)


def _save_draft(page: dict, draft, *, manual: bool, from_widgets: bool = True) -> None:
    workspace = page["workspace"]
    st.session_state[SESSION_SAVE_STATUS] = "saving"
    try:
        if manual:
            save_draft_now(get_quote_repository(), draft, st.session_state, from_widgets=from_widgets)
        else:
            maybe_autosave(get_quote_repository(), draft, st.session_state, from_widgets=from_widgets)
    except QuoteRepositoryError as error:
        st.session_state[SESSION_SAVE_ERROR] = str(error)
        st.error(workspace.get("save_failed", str(error)))


def _render_pending_price_key_reviews(page: dict) -> None:
    stored = st.session_state[PENDING_FORM_KEY] if PENDING_FORM_KEY in st.session_state else {}
    reviews = (stored or {}).get("pending_final_price_reviews") or []
    if not reviews:
        return
    template = page["workspace"].get(
        "pending_price_key_ambiguous",
        "SKU {sku} の入力途中売価は、同一見積に複数行があるため復元しません。行ごとに入力してください。",
    )
    for review in reviews:
        if review.get("reason") != "ambiguous_sku":
            continue
        st.warning(template.format(sku=review.get("sku") or ""))


def _resume_draft(page: dict, helpers, quote_draft_id: str, version: int) -> None:
    if resume_draft_into_session(
        quote_draft_id,
        version,
        init_dates=helpers["init_date_widgets"],
    ):
        st.rerun()
    st.error(page["workspace"].get("resume_failed", "下書きを開けませんでした。"))


def _apply_pending_description(draft, row: dict, text: str) -> None:
    source_ids = row.get("source_configuration_line_ids") or []
    line_id = row.get("customer_quote_line_id")
    customer = next(
        (item for item in draft.customer_lines if item.customer_quote_line_id == line_id),
        None,
    )
    if customer is not None:
        source_ids = customer.source_configuration_line_ids or source_ids
        customer.description = text or None
    for config in draft.configuration_lines:
        if config.line_id in source_ids or (
            customer is not None and config.line_id in (customer.source_configuration_line_ids or [])
        ):
            config.customer_description = text or None
    refresh_quote_draft(draft)


def _line_status_label(workspace: dict, line) -> str:
    if line.customer_presentation_status.value == "UNDECIDED" or line.final_sales_price_jpy is None:
        return workspace.get("unset_label", "未設定")
    if line.warnings:
        return workspace.get("status_review", "要確認")
    return workspace.get("status_complete", "完了")


def _render_confirmation_table(page: dict, checks: dict) -> None:
    workspace = page["workspace"]
    st.table(
        [
            {
                workspace.get("check_item_label", "確認項目"): label,
                workspace.get("column_status", "状態"): (
                    workspace.get("check_ok", "OK") if checked else workspace.get("check_pending", "未確認")
                ),
            }
            for label, checked in checks.items()
        ]
    )
