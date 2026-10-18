from html import escape

import streamlit as st

from agents.activity_catalog import timeline_event_label
from models import CaseLifecycleStatus, PriceMasterType
from repositories.sqlite_activity_repository import SqliteActivityRepository
from repositories.sqlite_price_master_repository import SqlitePriceMasterRepository
from ui.components.portal import (
    format_portal_datetime,
    render_home_hero,
    render_portal_section_title,
    resume_draft_into_session,
)
from ui.components.lifecycle import render_home_filter
from ui.navigation import PAGE_QUOTE_CONTROL, PAGE_TECHNICAL_CASE, set_current_page
from ui.price_master import format_imported_at
from ui.quote_persistence import get_quote_repository
from ui.technical_case_persistence import get_technical_case_repository, resume_case_into_session
from ui.technical_case_steps import build_technical_workflow
from ui.theme import brand_logos_html
from ui.work_status import KIND_QUOTE, KIND_TECHNICAL, summarize_quote, summarize_technical_case

HOME_LOGO_HEIGHT = 18
NEXT_ACTION_LIMIT = 5


def render_home(texts: dict) -> None:
    portal = texts.get("portal", {})
    quote_page = texts["pages"]["quote_control"]

    tech_open, quote_open = _open_counts()
    in_progress = _recent_work_items("in_progress")
    render_home_hero(
        title=texts["app_title"],
        description=texts["app_description"],
        eyebrow=portal.get("hero_eyebrow", "DEEP TREKKER · PIPETREKKER · SPACEONE"),
        logos_html=brand_logos_html(HOME_LOGO_HEIGHT),
        summary_label=portal.get("work_summary_label", "進行中の業務"),
        summary_items=_hero_summary_items(portal, tech_open, quote_open, in_progress),
    )

    work_column, side_column = st.columns([2, 1], gap="medium")
    with work_column:
        with st.container(border=True, key="home_work_panel"):
            render_portal_section_title(portal.get("recent_work_label", "進行中の案件"))
            view = render_home_filter(texts)
            items = in_progress if view == "in_progress" else _recent_work_items(view)
            if not items:
                st.caption(portal.get("recent_work_empty", "進行中の案件はまだありません。"))
            for item in items:
                _render_recent_work_item(item, portal, quote_page, texts)
    with side_column:
        _render_next_actions(in_progress, portal, quote_page)
        _render_price_master_status(portal, texts)


def _work_summary_items(portal: dict, tech_open: int, quote_open: int) -> list[tuple[str, str]]:
    unit = portal.get("count_unit", "件")

    def count_value(count: int) -> str:
        return f"{count} {unit}".strip()

    return [
        (portal.get("kind_technical", "営業・技術"), count_value(tech_open)),
        (portal.get("kind_quote", "見積"), count_value(quote_open)),
        (portal.get("work_summary_total", "進行中 合計"), count_value(tech_open + quote_open)),
    ]


def _hero_summary_items(portal: dict, tech_open: int, quote_open: int, in_progress: list[dict]) -> list[tuple[str, str, str]]:
    technical, quote, total = _work_summary_items(portal, tech_open, quote_open)
    review_total = sum(_user_progress(item)[2] for item in in_progress)
    review = (
        portal.get("review_label", "要確認"),
        f"{review_total} {portal.get('count_unit', '件')}".strip(),
    )
    return [(*technical, ""), (*quote, ""), (*review, "is-review"), (*total, "is-total")]


def _kind_label(item: dict, portal: dict) -> str:
    if item["kind"] == KIND_TECHNICAL:
        return portal.get("kind_technical", "営業・技術")
    return portal.get("kind_quote", "見積")


def _item_key(item: dict) -> str:
    return item["id"] if item["kind"] == KIND_TECHNICAL else f"{item['id']}_{item['version']}"


def _review_chip_html(review_required: int, portal: dict) -> str:
    if review_required:
        label = f"{portal.get('review_label', '要確認')} {review_required}{portal.get('review_unit', '件')}"
        return f"<span class='home-chip is-review'>{escape(label)}</span>"
    return f"<span class='home-chip is-ok'>{escape(portal.get('review_none', '要確認なし'))}</span>"


def _progress_segments_html(completed: int, total: int) -> str:
    segments = "".join(
        f"<span class='{'is-done' if index < completed else 'is-current' if index == completed else ''}'></span>"
        for index in range(total)
    )
    return f"<div class='home-progress-segs'>{segments}</div>"


def _render_recent_work_item(item: dict, portal: dict, quote_page: dict, texts: dict) -> None:
    completed, total, review_required = _user_progress(item)
    kind_class = "is-technical" if item["kind"] == KIND_TECHNICAL else "is-quote"
    updated = format_portal_datetime(item["updated_at"]) if item["updated_at"] else "-"
    updated_prefix = quote_page["workspace"].get("updated_at_label", "最終更新")
    with st.container(key=f"home_row_{item['kind']}_{_item_key(item)}"):
        identity, status, actions = st.columns([4, 4, 3.4], vertical_alignment="center")
        identity.markdown(
            f"<div class='home-row-identity'>"
            f"<span class='home-kind-badge {kind_class}'>{escape(_kind_label(item, portal))}</span>"
            f"<div class='home-row-customer'>{escape(item['customer'])}</div>"
            f"<div class='home-row-title'>{escape(item['title'])}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        status.markdown(
            f"<div class='home-row-status'>"
            f"<div class='home-row-stage'><span>{escape(item['process'])}</span>"
            f"<span class='home-row-progress'>{portal.get('progress_label', '進捗')} {completed} / {total}</span></div>"
            f"{_progress_segments_html(completed, total)}"
            f"<div class='home-row-meta'>{_review_chip_html(review_required, portal)}"
            f"<span>{escape(updated_prefix)} {escape(updated)}</span></div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        with actions:
            if item["kind"] == KIND_TECHNICAL:
                if st.button(
                    portal.get("open_case_label", "案件を開く"),
                    key=f"home_resume_technical_{item['id']}",
                    type="primary",
                    use_container_width=True,
                ):
                    _open_technical_case(item["id"])
                quick_key = f"home_quick_technical_{item['id']}"
                quick_open = bool(st.session_state.get(f"{quick_key}_open", False))
                quick_label = (
                    portal.get("quick_view_button_close", "ステータスを閉じる ▲")
                    if quick_open
                    else portal.get("quick_view_button_open", "ステータスを確認 ▼")
                )
                if st.button(quick_label, key=quick_key, type="secondary", use_container_width=True):
                    st.session_state[f"{quick_key}_open"] = not quick_open
                    st.rerun()
            elif st.button(
                quote_page["workspace"].get("resume_draft_button", "作業を再開"),
                key=f"home_resume_draft_{item['id']}_{item['version']}",
                type="primary",
                use_container_width=True,
            ):
                _resume_quote_from_home(quote_page, item["id"], item["version"])
        if item["kind"] == KIND_TECHNICAL and st.session_state.get(f"home_quick_technical_{item['id']}_open"):
            _render_technical_quick_view(item, portal, texts["pages"]["technical_case"])


def _render_next_actions(in_progress: list[dict], portal: dict, quote_page: dict) -> None:
    pending = [item for item in in_progress if _user_progress(item)[2]][:NEXT_ACTION_LIMIT]
    with st.container(border=True, key="home_next_actions"):
        render_portal_section_title(portal.get("next_actions_label", "次にやること"))
        if not pending:
            st.caption(portal.get("next_actions_empty", "要確認の案件はありません。"))
        for item in pending:
            st.markdown(
                f"<div class='home-next-item'>"
                f"<div class='home-next-meta'>{escape(_kind_label(item, portal))} · {escape(item['customer'])}</div>"
                f"<div class='home-next-title'>{escape(item['title'])}</div>"
                f"<div class='home-next-reason'>{escape(item['process'])} · {_review_chip_html(_user_progress(item)[2], portal)}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
            if st.button(
                portal.get("open_short_label", "開く"),
                key=f"home_next_open_{item['kind']}_{_item_key(item)}",
                type="secondary",
            ):
                if item["kind"] == KIND_TECHNICAL:
                    _open_technical_case(item["id"])
                else:
                    _resume_quote_from_home(quote_page, item["id"], item["version"])


def _render_price_master_status(portal: dict, texts: dict) -> None:
    labels = texts["pages"]["quote_control"]["price_masters"]
    repository = SqlitePriceMasterRepository()
    rows = []
    for master_type in PriceMasterType:
        record = repository.get_active(master_type)
        name = labels["short_labels"].get(master_type.value, master_type.value)
        if record is None:
            state, tone = labels.get("summary_unset", "未設定"), "is-unset"
        else:
            state, tone = f"{labels.get('status_active', '有効')} · {format_imported_at(record.imported_at, date_only=True)}", "is-active"
        rows.append(
            f"<div class='home-master-row'><span class='home-master-name'>{escape(name)}</span>"
            f"<span class='home-master-state {tone}'>{escape(state)}</span></div>"
        )
    with st.container(border=True, key="home_price_masters"):
        render_portal_section_title(portal.get("price_master_label", "価格マスター"))
        st.markdown(f"<div class='home-master-list'>{''.join(rows)}</div>", unsafe_allow_html=True)


def _open_technical_case(case_id: str) -> None:
    loaded = get_technical_case_repository().get_case(case_id)
    if loaded is not None:
        resume_case_into_session(loaded, st.session_state)
        set_current_page(PAGE_TECHNICAL_CASE)
        st.rerun()


def _open_counts() -> tuple[int, int]:
    technical = get_technical_case_repository().list_recent_cases(limit=20, view="in_progress")
    quotes = get_quote_repository().list_recent_drafts(limit=20, view="in_progress")
    return len(technical), len(quotes)


def _recent_work_items(view: str = "in_progress") -> list[dict]:
    items = []
    tech_repo = get_technical_case_repository()
    for item in tech_repo.list_recent_cases(limit=8, view=view):
        record = tech_repo.get_case(item.case_id)
        summary = summarize_technical_case(record=record)
        items.append(
            {
                "kind": KIND_TECHNICAL,
                "id": item.case_id,
                "version": None,
                "customer": item.customer_name or "-",
                "title": item.case_title or "-",
                "process": summary.process_label(),
                "updated_at": item.updated_at,
                "summary": summary,
                "workflow": build_technical_workflow(summary),
                "record": record,
            }
        )
    if view == "closed":
        return sorted(items, key=lambda row: row["updated_at"] or "", reverse=True)[:8]
    quote_repo = get_quote_repository()
    for item in quote_repo.list_recent_drafts(limit=8, view=view):
        loaded = quote_repo.get_draft(item.quote_draft_id, item.version)
        draft = loaded.draft if loaded is not None else None
        snapshot = quote_repo.get_snapshot_for_draft(item.quote_draft_id, item.version)
        summary = summarize_quote(draft, snapshot, updated_at=item.updated_at)
        items.append(
            {
                "kind": KIND_QUOTE,
                "id": item.quote_draft_id,
                "version": item.version,
                "customer": item.customer_name or "-",
                "title": item.subject or item.configuration_name or "-",
                "process": summary.process_label(),
                "updated_at": item.updated_at,
                "summary": summary,
            }
        )
    items.sort(key=lambda row: row["updated_at"] or "", reverse=True)
    return items[:8]


def _user_progress(item: dict) -> tuple[int, int, int]:
    source = item["workflow"] if item["kind"] == KIND_TECHNICAL else item["summary"]
    return source.completed, source.total, source.review_required


def _render_technical_quick_view(item: dict, portal: dict, technical_page: dict) -> None:
    record = item["record"]
    completed, total, review_required = _user_progress(item)
    labels = portal.get("quick_view", {})
    closed = record.case_lifecycle_status == CaseLifecycleStatus.CLOSED
    status = record.status or "DRAFT"
    latest = SqliteActivityRepository(getattr(get_technical_case_repository(), "path", None)).list_events(
        entity_kind="case",
        entity_id=record.case_id,
        limit=1,
    )
    latest_label = (
        timeline_event_label(latest[0].event_type)
        if latest
        else labels.get("activity_fallback", "案件情報を更新")
    )
    situation = labels.get("closed_situation") if closed else labels.get("situations", {}).get(status)
    next_action = labels.get("closed_next") if closed else labels.get("next_actions", {}).get(status)
    phase_labels = technical_page.get("case_status", {})
    with st.container(border=True):
        st.markdown(f"**{labels.get('title', 'ステータス Quick View')}**")
        st.write(f"{labels.get('case_name', '案件名')}：{record.case_title or '-'}")
        st.write(f"{labels.get('customer', '顧客名')}：{record.customer_name or '-'}")
        st.write(
            f"{labels.get('business_status', '業務状態')}："
            f"{labels.get('closed', '終了') if closed else labels.get('active', '進行中')}"
        )
        st.write(f"{labels.get('phase', '現在Phase')}：{phase_labels.get(status, status)}")
        st.write(f"{labels.get('progress', '進捗')}：{completed} / {total}")
        st.write(f"{labels.get('review', '要確認')}：{review_required}{labels.get('review_unit', '件')}")
        st.write(f"{labels.get('situation', '現在の状況')}：{situation or phase_labels.get(status, status)}")
        updated_at = format_portal_datetime(record.updated_at) if record.updated_at else "-"
        st.write(f"{labels.get('updated_at', '最終更新日時')}：{updated_at}")
        st.write(f"{labels.get('latest_activity', '最新更新内容')}：{latest_label}")
        st.write(f"{labels.get('next_action', '次にやること')}：{next_action or '-'}")
        if st.button(
            labels.get("open_case", "案件を開く"),
            key=f"quick_open_technical_{record.case_id}",
            type="primary",
        ):
            resume_case_into_session(record, st.session_state)
            set_current_page(PAGE_TECHNICAL_CASE)
            st.rerun()


def _resume_quote_from_home(page: dict, quote_draft_id: str, version: int) -> None:
    if resume_draft_into_session(quote_draft_id, version):
        set_current_page(PAGE_QUOTE_CONTROL)
        st.rerun()
    st.error(page["workspace"].get("resume_failed", "下書きを開けませんでした。"))
