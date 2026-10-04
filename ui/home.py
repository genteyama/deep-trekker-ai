import streamlit as st

from ui.components.portal import (
    render_home_hero,
    render_menu_card,
    render_portal_section_title,
    resume_draft_into_session,
)
from ui.components.lifecycle import render_home_filter
from ui.components.status import render_recent_case_card
from ui.navigation import PAGE_ACTIVITY_LEDGER, PAGE_QUOTE_CONTROL, PAGE_TECHNICAL_CASE, set_current_page
from ui.quote_persistence import get_quote_repository
from ui.technical_case_persistence import get_technical_case_repository, resume_case_into_session
from ui.work_status import KIND_QUOTE, KIND_TECHNICAL, summarize_quote, summarize_technical_case


def render_home(texts: dict) -> None:
    technical_case = texts["agents"]["technical_case"]
    quote_control = texts["agents"]["quote_control"]
    portal = texts.get("portal", {})
    quote_page = texts["pages"]["quote_control"]

    render_home_hero(
        texts["app_title"],
        texts["app_description"],
        texts.get("hero_english", ""),
    )
    render_portal_section_title(texts["menu_label"])

    tech_open, quote_open = _open_counts()
    count_label = portal.get("open_cases_label", "進行中")
    count_unit = portal.get("count_unit", "件")
    left_column, middle_column, right_column = st.columns(3)
    with left_column:
        render_menu_card(
            technical_case["name"],
            technical_case.get("english", "Technical Support"),
            technical_case["description"],
            product_key="PIPETREKKER",
            count=tech_open,
            count_label=count_label,
            count_unit=count_unit,
        )
        if st.button(
            texts.get("open_label", "開く"),
            key="open_technical_case",
            use_container_width=True,
            type="primary",
        ):
            set_current_page(PAGE_TECHNICAL_CASE)
            st.rerun()

    with middle_column:
        render_menu_card(
            quote_control["name"],
            quote_control.get("english", "Quote & Price Control"),
            quote_control["description"],
            product_key="PHOTON",
            count=quote_open,
            count_label=count_label,
            count_unit=count_unit,
        )
        if st.button(
            texts.get("open_label", "開く"),
            key="open_quote_control",
            use_container_width=True,
            type="primary",
        ):
            set_current_page(PAGE_QUOTE_CONTROL)
            st.rerun()

    with right_column:
        activity = texts.get("agents", {}).get("activity_ledger", {})
        render_menu_card(
            activity.get("name", "履歴・活動台帳"),
            activity.get("english", "Activity Ledger"),
            activity.get("description", "営業技術問い合わせ、見積、派生案件を時系列で確認"),
        )
        if st.button(
            texts.get("open_label", "開く"),
            key="open_activity_ledger",
            use_container_width=True,
            type="primary",
        ):
            set_current_page(PAGE_ACTIVITY_LEDGER)
            st.rerun()

    render_portal_section_title(portal.get("recent_work_label", "進行中の案件"))
    view = render_home_filter(texts)
    items = _recent_work_items(view)
    if not items:
        st.caption(portal.get("recent_work_empty", "進行中の案件はまだありません。"))
        return
    for item in items:
        kind_label = portal.get("kind_technical", "営業・技術") if item["kind"] == KIND_TECHNICAL else portal.get("kind_quote", "見積")
        render_recent_case_card(
            kind_label=kind_label,
            customer=item["customer"],
            title=item["title"],
            process_label=item["process"],
            progress=f"{portal.get('progress_label', '進捗')}：{item['summary'].completed} / {item['summary'].total}",
            review_label=f"{portal.get('review_label', '要確認')}：{item['summary'].review_required}{portal.get('review_unit', '件')}",
            updated_at=item["updated_at"],
            updated_prefix=quote_page["workspace"].get("updated_at_label", "最終更新"),
        )
        if item["kind"] == KIND_TECHNICAL:
            if st.button(
                portal.get("resume_label", "再開"),
                key=f"home_resume_technical_{item['id']}",
                type="primary",
            ):
                loaded = get_technical_case_repository().get_case(item["id"])
                if loaded is not None:
                    resume_case_into_session(loaded, st.session_state)
                    set_current_page(PAGE_TECHNICAL_CASE)
                    st.rerun()
        else:
            if st.button(
                quote_page["workspace"].get("resume_draft_button", "作業を再開"),
                key=f"home_resume_draft_{item['id']}_{item['version']}",
                type="primary",
            ):
                _resume_quote_from_home(quote_page, item["id"], item["version"])


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
            }
        )
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


def _resume_quote_from_home(page: dict, quote_draft_id: str, version: int) -> None:
    if resume_draft_into_session(quote_draft_id, version):
        set_current_page(PAGE_QUOTE_CONTROL)
        st.rerun()
    st.error(page["workspace"].get("resume_failed", "下書きを開けませんでした。"))
