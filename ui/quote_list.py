"""Quote-only finder kept separate from the broader Activity Ledger."""

from __future__ import annotations

from typing import Callable, Iterable, Optional


STATUS_LABELS = {
    "DRAFT": "下書き",
    "REVIEW_REQUIRED": "要確認",
    "READY_FOR_APPROVAL": "承認待ち",
    "APPROVED": "承認済み",
    "SUPERSEDED": "改訂済み",
}


def _yen(value) -> str:
    if value is None:
        return "-"
    return f"¥{float(value):,.0f}"


def _percent(value) -> str:
    if value is None:
        return "-"
    return f"{float(value) * 100:.1f}%"


def quote_list_rows(items: Iterable, *, load_draft: Optional[Callable] = None) -> list[dict]:
    rows = []
    for item in items:
        draft = None
        if load_draft is not None:
            loaded = load_draft(item.quote_draft_id, item.version)
            draft = loaded.draft if loaded is not None else None
        economics = getattr(draft, "economics_result", None) if draft is not None else None
        raw_status = item.status or "-"
        status = STATUS_LABELS.get(raw_status, raw_status)
        official = (getattr(draft, "official_quote_number", None) or "") if draft is not None else ""
        rows.append(
            {
                "正式見積番号": official or "-",
                "見積ID": item.quote_draft_id,
                "Version": item.version,
                "顧客": item.customer_name or "-",
                "件名": item.subject or "-",
                "構成": item.configuration_name or "-",
                "売上(税抜)": _yen(getattr(draft, "subtotal_ex_tax_jpy", None)),
                "粗利": _yen(getattr(economics, "gross_profit_jpy", None)),
                "粗利率": _percent(getattr(economics, "gross_margin_rate", None)),
                "状態": status,
                "最終更新": item.updated_at or "-",
                "_raw_status": raw_status,
                "_search": " ".join(
                    str(value or "")
                    for value in (
                        official,
                        item.quote_draft_id,
                        item.customer_name,
                        item.subject,
                        item.configuration_name,
                        raw_status,
                        status,
                    )
                ).casefold(),
            }
        )
    return rows


def filter_quote_list_rows(rows: Iterable[dict], *, keyword: str = "", statuses: Iterable[str] | None = None) -> list[dict]:
    keyword = (keyword or "").strip().casefold()
    status_set = set(statuses or [])
    result = []
    for row in rows:
        if keyword and keyword not in row.get("_search", ""):
            continue
        if status_set and row.get("状態") not in status_set:
            continue
        result.append(row)
    return result


def display_quote_list_rows(rows: Iterable[dict]) -> list[dict]:
    return [{key: value for key, value in row.items() if not key.startswith("_")} for row in rows]


def render_quote_list(texts: dict) -> None:
    import streamlit as st

    from ui.components.portal import resume_draft_into_session
    from ui.navigation import PAGE_QUOTE_CONTROL, set_current_page
    from ui.quote_persistence import get_quote_repository

    st.title("見積一覧")
    st.caption("作成済みの見積を顧客名・件名・見積ID・構成から検索して開きます。")

    repo = get_quote_repository()
    items = repo.list_recent_drafts(limit=500, view="active")
    rows = quote_list_rows(items, load_draft=repo.get_draft)
    if not rows:
        st.info("保存済みの見積はありません。")
        return

    columns = st.columns([2, 1])
    with columns[0]:
        keyword = st.text_input("見積を検索", placeholder="顧客名 / 件名 / 正式見積番号 / 見積ID / 製品・構成")
    with columns[1]:
        status_options = sorted({row["状態"] for row in rows})
        selected_statuses = st.multiselect("状態", status_options)

    filtered = filter_quote_list_rows(rows, keyword=keyword, statuses=selected_statuses)
    st.caption(f"{len(filtered)} / {len(rows)} 件")
    st.dataframe(
        display_quote_list_rows(filtered),
        use_container_width=True,
        hide_index=True,
        column_order=["正式見積番号", "見積ID", "Version", "顧客", "件名", "構成", "売上(税抜)", "粗利", "粗利率", "状態", "最終更新"],
    )

    if not filtered:
        return
    selected_index = st.selectbox(
        "開く見積",
        options=list(range(len(filtered))),
        format_func=lambda index: (
            f"{filtered[index]['顧客']}｜{filtered[index]['件名']}｜"
            f"{filtered[index]['見積ID']} v{filtered[index]['Version']}"
        ),
    )
    selected = filtered[int(selected_index)]
    if st.button("この見積を開く", type="primary"):
        if resume_draft_into_session(selected["見積ID"], int(selected["Version"])):
            set_current_page(PAGE_QUOTE_CONTROL)
            st.rerun()
        else:
            st.error("見積を開けませんでした。再読み込みして確認してください。")
