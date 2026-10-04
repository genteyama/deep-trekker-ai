from __future__ import annotations

from datetime import date
from html import escape
from pathlib import Path

import streamlit as st

from agents.activity_catalog import (
    CATEGORY_LABELS,
    SORT_FIELDS,
    ActivityFilter,
    ActivitySelection,
    ActivitySort,
    apply_activity_filter,
    build_quote_preview,
    display_day,
    load_activity_rows,
    load_related_quotes,
    related_source_label,
    reset_activity_filter,
    reset_activity_sort,
    sort_activity_rows,
    summarize_activity,
    timeline_event_label,
)
from agents.activity_log import get_activity_repository
from agents.activity_report import (
    activity_report_filename,
    customer_csv_filename,
    customer_records_from_rows,
    find_existing_formal_pdf,
    render_activity_report_docx,
    render_activity_report_pdf,
    render_customer_csv,
)
from repositories.sqlite_customer_repository import SqliteCustomerRepository
from ui.components.portal import render_portal_section_title, resume_draft_into_session
from ui.navigation import PAGE_HOME, PAGE_QUOTE_CONTROL, PAGE_TECHNICAL_CASE, set_current_page
from ui.quote_persistence import get_quote_repository
from ui.technical_case_persistence import get_technical_case_repository
from ui.work_status import PROCESS_LABELS

SESSION_FILTER = "activity_filter"
SESSION_SORT = "activity_sort"
SESSION_SELECTED = "activity_selected"
SESSION_DETAIL = "activity_detail_id"
SESSION_PREVIEW = "activity_preview_snapshot_id"
DATE_FIELDS = {"last_activity_at", "date", "updated_at"}
SORT_LABELS = {
    "last_activity_at": "最新活動日時",
    "date": "DATE（発生日）",
    "customer": "顧客名",
    "end_user": "End User",
    "category": "区分",
    "product": "機種",
    "title": "案件名",
    "status": "対応ステータス",
    "updated_at": "最終更新",
}


def render_activity_ledger(texts: dict) -> None:
    page = texts.get("pages", {}).get("activity_ledger", {})
    if st.button(texts.get("back_to_home", "トップへ戻る"), key="back_to_home", type="secondary"):
        set_current_page(PAGE_HOME)
        st.rerun()
    st.title(page.get("title", "履歴・活動台帳"))
    st.caption(page.get("description", "営業技術問い合わせ、見積、派生案件を時系列で確認します。"))
    case_repo = get_technical_case_repository()
    quote_repo = get_quote_repository()
    activity_repo = get_activity_repository(getattr(case_repo, "path", None))
    customer_repo = SqliteCustomerRepository(getattr(case_repo, "path", None))
    rows = load_activity_rows(case_repo, quote_repo, activity_repo)
    filt = _current_filter()
    sort = _current_sort()
    filtered = sort_activity_rows(apply_activity_filter(rows, filt), sort)
    _render_dashboard(page, filtered)
    _render_filters(page, rows, filt)
    _render_sort(page, sort)
    selection = _current_selection()
    _render_selection_bar(page, filtered, selection)
    _render_table(page, filtered, rows, selection)
    detail = _detail_row(filtered, selection)
    if detail is not None:
        _render_detail(page, detail, rows, case_repo, quote_repo, activity_repo)
    _render_exports(page, filtered, selection, filt, customer_repo, rows)


def _current_filter() -> ActivityFilter:
    stored = st.session_state.get(SESSION_FILTER)
    if isinstance(stored, ActivityFilter):
        return stored
    stored = reset_activity_filter()
    st.session_state[SESSION_FILTER] = stored
    return stored


def _current_sort() -> ActivitySort:
    stored = st.session_state.get(SESSION_SORT)
    if isinstance(stored, ActivitySort):
        return stored
    stored = reset_activity_sort()
    st.session_state[SESSION_SORT] = stored
    return stored


def _current_selection() -> ActivitySelection:
    stored = st.session_state.get(SESSION_SELECTED)
    if isinstance(stored, ActivitySelection):
        return stored
    stored = ActivitySelection()
    st.session_state[SESSION_SELECTED] = stored
    return stored


def _render_dashboard(page: dict, rows) -> None:
    summary = summarize_activity(rows)
    cols = st.columns(5)
    labels = (
        ("total", page.get("stat_total", "総件数")),
        ("inquiry", page.get("stat_inquiry", "問い合わせ")),
        ("quote", page.get("stat_quote", "見積")),
        ("completed", page.get("stat_completed", "完了")),
        ("in_progress", page.get("stat_in_progress", "進行中")),
    )
    for column, (key, label) in zip(cols, labels):
        column.metric(label, summary[key])


def _render_filters(page: dict, rows, filt: ActivityFilter) -> None:
    render_portal_section_title(page.get("filter_label", "フィルター"))
    customers = sorted({row.customer for row in rows if row.customer})
    end_users = sorted({row.end_user for row in rows if row.end_user})
    products = sorted({row.product for row in rows if row.product})
    statuses = sorted({row.status for row in rows if row.status})
    categories = list(CATEGORY_LABELS.keys())
    left, right = st.columns(2)
    with left:
        date_from = st.text_input(page.get("date_from", "期間 From"), value=filt.date_from or "", key="activity_date_from")
        date_to = st.text_input(page.get("date_to", "期間 To"), value=filt.date_to or "", key="activity_date_to")
        selected_customers = st.multiselect(page.get("filter_customer", "顧客名"), customers, default=list(filt.customers), key="activity_filter_customers")
        selected_end_users = st.multiselect(page.get("filter_end_user", "End User"), end_users, default=list(filt.end_users), key="activity_filter_end_users")
    with right:
        selected_products = st.multiselect(page.get("filter_product", "機種"), products, default=list(filt.products), key="activity_filter_products")
        selected_categories = st.multiselect(
            page.get("filter_category", "区分"),
            categories,
            default=list(filt.categories),
            format_func=lambda value: CATEGORY_LABELS.get(value, value),
            key="activity_filter_categories",
        )
        selected_statuses = st.multiselect(page.get("filter_status", "対応ステータス"), statuses, default=list(filt.statuses), key="activity_filter_statuses")
        keyword = st.text_input(page.get("filter_keyword", "キーワード"), value=filt.keyword, key="activity_filter_keyword")
        include_archived = st.checkbox(page.get("include_archived", "アーカイブを表示"), value=filt.include_archived, key="activity_include_archived")
    st.session_state[SESSION_FILTER] = ActivityFilter(
        date_from=date_from.strip() or None,
        date_to=date_to.strip() or None,
        customers=tuple(selected_customers),
        end_users=tuple(selected_end_users),
        products=tuple(selected_products),
        categories=tuple(selected_categories),
        statuses=tuple(selected_statuses),
        keyword=keyword or "",
        include_archived=include_archived,
    )
    if st.button(page.get("reset_filters", "フィルターをリセット"), key="activity_reset_filters"):
        st.session_state[SESSION_FILTER] = reset_activity_filter()
        st.session_state[SESSION_SORT] = reset_activity_sort()
        for key in (
            "activity_date_from",
            "activity_date_to",
            "activity_filter_customers",
            "activity_filter_end_users",
            "activity_filter_products",
            "activity_filter_categories",
            "activity_filter_statuses",
            "activity_filter_keyword",
            "activity_include_archived",
            "activity_sort_field",
            "activity_sort_dir",
        ):
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()


def _render_sort(page: dict, sort: ActivitySort) -> None:
    left, right = st.columns(2)
    field = left.selectbox(
        page.get("sort_field", "並び替え"),
        options=list(SORT_FIELDS),
        index=list(SORT_FIELDS).index(sort.field) if sort.field in SORT_FIELDS else 0,
        format_func=lambda value: SORT_LABELS.get(value, value),
        key="activity_sort_field",
    )
    if field in DATE_FIELDS:
        options = (True, False)
        labels = {True: page.get("sort_newest", "新しい順"), False: page.get("sort_oldest", "古い順")}
    else:
        options = (False, True)
        labels = {False: page.get("sort_asc", "昇順"), True: page.get("sort_desc", "降順")}
    descending = right.radio(
        page.get("sort_dir", "順序"),
        options=list(options),
        index=0 if sort.descending == options[0] else 1,
        format_func=lambda value: labels[value],
        horizontal=True,
        key="activity_sort_dir",
    )
    st.session_state[SESSION_SORT] = ActivitySort(field=field, descending=bool(descending))


def _render_selection_bar(page: dict, rows, selection: ActivitySelection) -> None:
    st.caption(f"{page.get('selected_count', '選択中')}：{len(selection.selected_rows(rows))}{page.get('count_unit', '件')}")
    cols = st.columns(4)
    if cols[0].button(page.get("select_all", "全選択"), key="activity_select_all", type="primary"):
        selection.select_all(rows)
        st.rerun()
    if cols[1].button(page.get("deselect_all", "全解除"), key="activity_deselect_all"):
        selection.deselect_all()
        st.rerun()


def _status_label(status: str) -> str:
    return PROCESS_LABELS.get(status or "", status or "-")


def _cell(text: str, *, kind: str = "td", extra: str = "") -> str:
    css = f"activity-{kind}"
    if extra:
        css = f"{css} {extra}"
    return f"<div class='{css}'>{escape(text)}</div>"


TABLE_WEIGHTS = [0.35, 0.35, 0.75, 1.0, 0.8, 0.75, 0.95, 1.7, 1.25, 0.75, 0.85, 0.55]


def _render_table(page: dict, rows, all_rows, selection: ActivitySelection) -> None:
    render_portal_section_title(page.get("list_label", "履歴一覧"))
    labels = (
        page.get("col_select", "選択"),
        page.get("col_no", "No."),
        page.get("col_date", "DATE"),
        page.get("col_customer", "顧客"),
        page.get("col_end_user", "End User"),
        page.get("col_category", "区分"),
        page.get("col_product", "機種"),
        page.get("col_title", "案件名"),
        page.get("col_status", "対応ステータス"),
        page.get("col_updated", "最終更新"),
        page.get("col_related", "関連元"),
        page.get("open_row", "開く"),
    )
    header = st.columns(TABLE_WEIGHTS)
    for column, label in zip(header, labels):
        column.markdown(_cell(label, kind="th"), unsafe_allow_html=True)
    if not rows:
        st.caption(page.get("empty", "該当する履歴はありません。"))
        return
    for index, row in enumerate(rows, start=1):
        cols = st.columns(TABLE_WEIGHTS)
        checked = cols[0].checkbox(" ", value=row.row_id in selection.selected, key=f"activity_select_{row.row_id}", label_visibility="collapsed")
        if checked:
            selection.select_one(row.row_id)
        elif row.row_id in selection.selected:
            selection.selected.discard(row.row_id)
        cols[1].markdown(_cell(str(index)), unsafe_allow_html=True)
        cols[2].markdown(_cell(display_day(row.date) or "-"), unsafe_allow_html=True)
        cols[3].markdown(_cell(row.customer or "-"), unsafe_allow_html=True)
        cols[4].markdown(_cell(row.end_user or "-"), unsafe_allow_html=True)
        cols[5].markdown(_cell(row.category_label()), unsafe_allow_html=True)
        cols[6].markdown(_cell(row.product or "-", extra="activity-td-product"), unsafe_allow_html=True)
        cols[7].markdown(_cell(row.title or "-", extra="activity-td-title"), unsafe_allow_html=True)
        cols[8].markdown(_cell(_status_label(row.status), extra="activity-td-status"), unsafe_allow_html=True)
        cols[9].markdown(_cell(display_day(row.updated_at) or "-"), unsafe_allow_html=True)
        cols[10].markdown(_cell(related_source_label(row, all_rows) or "-"), unsafe_allow_html=True)
        if cols[11].button(page.get("open_row", "開く"), key=f"activity_open_{row.row_id}", type="primary"):
            st.session_state[SESSION_DETAIL] = row.row_id
            _open_row(row)


def _detail_row(rows, selection: ActivitySelection):
    detail_id = st.session_state.get(SESSION_DETAIL)
    if detail_id:
        for row in rows:
            if row.row_id == detail_id:
                return row
    selected = selection.selected_rows(rows)
    return selected[0] if selected else None


def _render_detail(page: dict, row, all_rows, case_repo, quote_repo, activity_repo) -> None:
    render_portal_section_title(page.get("detail_label", "履歴詳細"))
    with st.container(border=True):
        st.markdown(f"**{row.title or row.entity_id}**")
        st.caption(f"{row.category_label()} / {row.customer or '-'} / {_status_label(row.status)}")
        actions = st.columns(4)
        if row.entity_kind == "case":
            if actions[0].button(page.get("open_case", "案件を開く"), key=f"activity_open_case_{row.entity_id}", type="primary"):
                _open_row(row)
            related = load_related_quotes(quote_repo, row.entity_id)
            if related:
                if actions[1].button(page.get("open_linked_quote", "見積を開く"), key=f"activity_open_linked_quote_{row.entity_id}"):
                    st.session_state[SESSION_DETAIL] = row.row_id
                snapshots = []
                for draft in related:
                    snapshot = quote_repo.get_snapshot_for_draft(draft.quote_draft_id, draft.quote_version)
                    if snapshot is not None:
                        snapshots.append(snapshot)
                if snapshots and actions[2].button(page.get("preview_quote", "見積プレビュー"), key=f"activity_preview_from_case_{row.entity_id}"):
                    st.session_state[SESSION_PREVIEW] = snapshots[0].approved_quote_snapshot_id
                st.markdown(f"**{page.get('related_quotes', '関連見積')}**")
                for draft in related:
                    label = draft.title or draft.configuration_name or draft.quote_draft_id
                    number = ""
                    snapshot = quote_repo.get_snapshot_for_draft(draft.quote_draft_id, draft.quote_version)
                    if snapshot is not None:
                        number = snapshot.official_quote_number or snapshot.quote_number_candidate or ""
                    caption = f"{number} {label}".strip()
                    cols = st.columns([3, 1, 1])
                    cols[0].write(caption)
                    if cols[1].button(page.get("open_quote", "見積を開く"), key=f"activity_open_quote_{draft.quote_draft_id}_{draft.quote_version}", type="primary"):
                        _open_quote(draft.quote_draft_id, draft.quote_version)
                    if snapshot is not None and cols[2].button(page.get("preview_quote", "見積プレビュー"), key=f"activity_preview_{snapshot.approved_quote_snapshot_id}"):
                        st.session_state[SESSION_PREVIEW] = snapshot.approved_quote_snapshot_id
                        st.rerun()
        else:
            if actions[0].button(page.get("open_quote", "見積を開く"), key=f"activity_open_quote_detail_{row.entity_id}", type="primary"):
                _open_row(row)
            snapshot = quote_repo.get_snapshot_for_draft(row.entity_id, row.quote_version or 1)
            if snapshot is not None and actions[1].button(page.get("preview_quote", "見積プレビュー"), key=f"activity_preview_quote_{row.entity_id}"):
                st.session_state[SESSION_PREVIEW] = snapshot.approved_quote_snapshot_id
                st.rerun()
        children = [item for item in all_rows if item.parent_id == row.entity_id]
        if row.parent_id or children:
            if actions[3].button(page.get("related_work", "関連案件・見積"), key=f"activity_related_{row.row_id}"):
                st.session_state[SESSION_DETAIL] = row.row_id
            st.markdown(f"**{page.get('related_work', '関連案件・見積')}**")
            if row.parent_id:
                st.caption(f"{page.get('related_source', '関連元')}: {related_source_label(row, all_rows)}")
            for child in children:
                if st.button(f"{child.category_label()} {child.title or child.entity_id}", key=f"activity_child_{child.row_id}"):
                    _open_row(child)
        events = activity_repo.list_events(entity_kind=row.entity_kind, entity_id=row.entity_id, limit=30)
        if row.entity_kind == "case":
            for draft in load_related_quotes(quote_repo, row.entity_id):
                events.extend(activity_repo.list_events(entity_kind="quote", entity_id=draft.quote_draft_id, limit=20))
        events = sorted(events, key=lambda item: item.occurred_at or "", reverse=True)
        if events:
            st.markdown(f"**{page.get('timeline_label', '活動タイムライン')}**")
            for event in events:
                label = timeline_event_label(event.event_type)
                st.write(f"{display_day(event.occurred_at)}　{label}")
        preview_id = st.session_state.get(SESSION_PREVIEW)
        if preview_id:
            snapshot = quote_repo.get_snapshot(preview_id)
            if snapshot is not None:
                _render_preview(page, snapshot)


def _render_preview(page: dict, snapshot) -> None:
    preview = build_quote_preview(snapshot)
    st.markdown(f"**{page.get('preview_label', '見積プレビュー')}**")
    st.caption(page.get("preview_note", "承認時の保存内容を表示します。現在の価格マスタでは再計算しません。"))
    st.write(f"{page.get('preview_number', '見積番号')}: {preview['quote_number'] or '-'}")
    st.write(f"{page.get('col_customer', '顧客')}: {preview['customer'] or '-'}")
    st.write(f"{page.get('col_title', '案件名')}: {preview['title'] or '-'}")
    st.write(f"{page.get('preview_issue', '見積日')}: {preview['issue_date'] or '-'}")
    st.write(f"{page.get('preview_valid', '有効期限')}: {preview['valid_until'] or '-'}")
    st.write(f"{page.get('preview_status', '承認状態')}: {preview['status'] or '-'}")
    for line in preview["lines"]:
        st.write(
            f"- {line['name']} / {line['quantity']} / {line['unit_price'] or '-'} / {line['amount'] or '-'}"
        )
    for line in preview["shipping"]:
        st.write(f"- {line['name']}: {line['amount'] or '-'}")
    st.write(f"{page.get('preview_total', '合計')}: {preview['total'] or '-'}")
    if preview["remarks"]:
        st.caption(" / ".join(preview["remarks"]))
    pdf_path = find_existing_formal_pdf(snapshot)
    if pdf_path is not None and pdf_path.exists():
        st.download_button(
            page.get("open_formal_pdf", "正式PDFを確認"),
            data=pdf_path.read_bytes(),
            file_name=pdf_path.name,
            mime="application/pdf",
            key=f"activity_formal_pdf_{snapshot.approved_quote_snapshot_id}",
        )


def _render_exports(page: dict, rows, selection: ActivitySelection, filt: ActivityFilter, customer_repo, all_rows) -> None:
    render_portal_section_title(page.get("export_label", "レポート出力"))
    selected = selection.selected_rows(rows)
    target = selected or rows
    stamp = date.today().strftime("%Y%m%d")
    export_dir = Path("runtime") / "exports"
    cols = st.columns(4)
    if cols[0].button(page.get("export_word", "Word出力"), key="activity_export_word", type="primary"):
        path = export_dir / activity_report_filename(".docx", now=stamp)
        render_activity_report_docx(target, path, filt=filt)
        st.session_state["activity_export_word_path"] = str(path)
    if cols[1].button(page.get("export_pdf", "PDF出力"), key="activity_export_pdf", type="primary"):
        path = export_dir / activity_report_filename(".pdf", now=stamp)
        render_activity_report_pdf(target, path, filt=filt)
        st.session_state["activity_export_pdf_path"] = str(path)
    if cols[2].button(page.get("export_csv_selected", "選択顧客CSV"), key="activity_export_csv_selected"):
        records = customer_records_from_rows(selected or rows, customer_repo)
        path = export_dir / customer_csv_filename(now=stamp)
        render_customer_csv(records, path)
        st.session_state["activity_export_csv_path"] = str(path)
    if cols[3].button(page.get("export_csv_all", "全顧客CSV"), key="activity_export_csv_all"):
        records = customer_records_from_rows(all_rows, customer_repo, include_master=True)
        path = export_dir / customer_csv_filename(now=stamp)
        render_customer_csv(records, path)
        st.session_state["activity_export_csv_path"] = str(path)
    word_path = st.session_state.get("activity_export_word_path")
    if word_path and Path(word_path).exists():
        st.download_button(
            page.get("download_word", "Wordをダウンロード"),
            data=Path(word_path).read_bytes(),
            file_name=Path(word_path).name,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key="activity_download_word",
        )
    pdf_path = st.session_state.get("activity_export_pdf_path")
    if pdf_path and Path(pdf_path).exists():
        st.download_button(
            page.get("download_pdf", "PDFをダウンロード"),
            data=Path(pdf_path).read_bytes(),
            file_name=Path(pdf_path).name,
            mime="application/pdf",
            key="activity_download_pdf",
        )
    csv_path = st.session_state.get("activity_export_csv_path")
    if csv_path and Path(csv_path).exists():
        st.download_button(
            page.get("download_csv", "CSVをダウンロード"),
            data=Path(csv_path).read_bytes(),
            file_name=Path(csv_path).name,
            mime="text/csv",
            key="activity_download_csv",
        )


def _open_row(row) -> None:
    if row.entity_kind == "case":
        st.session_state["pending_resume_case_id"] = row.entity_id
        set_current_page(PAGE_TECHNICAL_CASE)
        st.rerun()
    _open_quote(row.entity_id, row.quote_version or 1)


def _open_quote(quote_draft_id: str, version: int) -> None:
    if resume_draft_into_session(quote_draft_id, version):
        set_current_page(PAGE_QUOTE_CONTROL)
        st.rerun()

