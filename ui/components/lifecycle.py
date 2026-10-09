from __future__ import annotations

from typing import Optional

import streamlit as st

from agents.work_lifecycle import (
    archive_quote,
    archive_record,
    derive_quote,
    derive_technical_case,
    duplicate_quote,
    duplicate_technical_case,
    restore_quote,
    restore_record,
    soft_delete_quote,
    soft_delete_record,
)
from models import CaseLineageType, QuoteLineageType


CASE_RELATION_OPTIONS = (
    CaseLineageType.ADDITIONAL_REQUEST.value,
    CaseLineageType.ALTERNATIVE_CONFIGURATION.value,
    CaseLineageType.FOLLOW_UP.value,
    CaseLineageType.OTHER.value,
)
QUOTE_RELATION_OPTIONS = (
    QuoteLineageType.ADDITIONAL.value,
    QuoteLineageType.ALTERNATIVE.value,
    QuoteLineageType.REVISION.value,
    QuoteLineageType.CONFIGURATION_CHANGE.value,
    QuoteLineageType.OTHER.value,
)

HOME_FILTERS = (
    ("in_progress", "進行中"),
    ("completed", "完了"),
    ("closed", "終了案件"),
    ("archived", "アーカイブ"),
    ("trash", "ゴミ箱"),
)


def lifecycle_texts(texts: dict) -> dict:
    return texts.get("lifecycle", {})


def relation_label(kind: str, relation_type: Optional[str], texts: dict) -> str:
    labels = lifecycle_texts(texts).get("case_relations" if kind == "case" else "quote_relations", {})
    return labels.get(relation_type or "", relation_type or "-")


def render_home_filter(texts: dict) -> str:
    portal = texts.get("portal", {})
    labels = lifecycle_texts(texts)
    options = [key for key, _ in HOME_FILTERS]
    display = {
        "in_progress": portal.get("filter_in_progress", labels.get("filter_in_progress", "進行中")),
        "completed": portal.get("filter_completed", labels.get("filter_completed", "完了")),
        "closed": portal.get("filter_closed", labels.get("filter_closed", "終了案件")),
        "archived": portal.get("filter_archived", labels.get("filter_archived", "アーカイブ")),
        "trash": portal.get("filter_trash", labels.get("filter_trash", "ゴミ箱")),
    }
    current = st.session_state.get("home_work_filter", "in_progress")
    if current not in options:
        current = "in_progress"
    selected = st.radio(
        portal.get("work_filter_label", "表示"),
        options=options,
        index=options.index(current),
        format_func=lambda key: display[key],
        horizontal=True,
        key="home_work_filter",
    )
    return selected


def render_lineage_card(
    *,
    texts: dict,
    parent=None,
    children=None,
    kind: str,
    parent_open=None,
    child_open=None,
) -> None:
    labels = lifecycle_texts(texts)
    if parent is None and not children:
        return
    with st.container(border=True):
        st.markdown(f"**{labels.get('lineage_label', '関連案件・見積')}**")
        if parent is not None:
            title = getattr(parent, "case_title", None) or getattr(parent, "title", None) or getattr(parent, "subject", None) or parent
            st.caption(f"{labels.get('parent_label', '元')}: {title}")
            if parent_open is not None and st.button(labels.get("open_parent", "元を開く"), key=f"open_parent_{kind}", type="secondary"):
                parent_open()
        if children:
            st.caption(labels.get("children_label", "派生先"))
            for index, child in enumerate(children):
                title = getattr(child, "case_title", None) or getattr(child, "subject", None) or getattr(child, "title", None) or child
                relation = relation_label(kind, getattr(child, "relation_type", None), texts)
                st.write(f"- {title}（{relation}）")
                if child_open is not None and st.button(
                    labels.get("open_child", "開く"),
                    key=f"open_child_{kind}_{index}",
                    type="secondary",
                ):
                    child_open(child)


def render_confirm_bar(texts: dict, action: str, *, confirm_key: str, cancel_key: str) -> Optional[str]:
    labels = lifecycle_texts(texts)
    if action == "archive":
        st.warning(labels.get("confirm_archive", "このデータをアーカイブします。通常一覧から非表示になります。"))
        confirm_label = labels.get("confirm_ok_archive", "アーカイブする")
    else:
        st.warning(labels.get("confirm_trash", "ゴミ箱へ移動します。物理削除はしません。"))
        confirm_label = labels.get("confirm_ok_trash", "ゴミ箱へ移動する")
    left, right = st.columns(2)
    if left.button(confirm_label, key=confirm_key, type="secondary"):
        return "confirm"
    if right.button(labels.get("cancel", "キャンセル"), key=cancel_key, type="secondary"):
        return "cancel"
    return None


def apply_case_lifecycle(record, repo, action: str, *, relation_type: Optional[str] = None):
    if action == "duplicate":
        return duplicate_technical_case(record)
    if action == "derive":
        return derive_technical_case(record, relation_type=relation_type or CaseLineageType.OTHER.value)
    if action == "archive":
        return archive_record(record)
    if action == "trash":
        return soft_delete_record(record)
    if action == "restore":
        return restore_record(record)
    return record


def apply_quote_lifecycle(draft, action: str, *, relation_type: Optional[str] = None):
    if action == "duplicate":
        return duplicate_quote(draft)
    if action == "derive":
        return derive_quote(draft, relation_type=relation_type or QuoteLineageType.OTHER.value)
    if action == "archive":
        return archive_quote(draft)
    if action == "trash":
        return soft_delete_quote(draft)
    if action == "restore":
        return restore_quote(draft)
    return draft


def render_case_actions_menu(page: dict, texts: dict, record) -> Optional[str]:
    labels = lifecycle_texts(texts)
    if record is None:
        st.caption(labels.get("save_first", "保存済み案件に対して複製・アーカイブできます。"))
        return None
    pending = st.session_state.get("case_lifecycle_confirm")
    if pending:
        result = render_confirm_bar(
            texts,
            pending,
            confirm_key="confirm_case_lifecycle",
            cancel_key="cancel_case_lifecycle",
        )
        if result == "confirm":
            st.session_state["case_lifecycle_confirm"] = None
            return pending
        if result == "cancel":
            st.session_state["case_lifecycle_confirm"] = None
            return None
    cols = st.columns(4)
    if cols[0].button(labels.get("duplicate", "複製"), key="duplicate_technical_case", type="secondary"):
        return "duplicate"
    if cols[1].button(labels.get("derive_case", "派生案件を作成"), key="derive_technical_case", type="secondary"):
        st.session_state["case_lifecycle_derive"] = True
    if cols[2].button(labels.get("archive", "アーカイブ"), key="archive_technical_case", type="secondary"):
        st.session_state["case_lifecycle_confirm"] = "archive"
        st.rerun()
    if cols[3].button(labels.get("trash", "ゴミ箱へ移動"), key="trash_technical_case", type="secondary"):
        st.session_state["case_lifecycle_confirm"] = "trash"
        st.rerun()
    if record.archived_at or record.deleted_at:
        restore_label = labels.get("restore_trash", "ゴミ箱から戻す") if record.deleted_at else labels.get("restore_archive", "アーカイブから戻す")
        if st.button(restore_label, key="restore_technical_case", type="secondary"):
            return "restore"
    if st.session_state.get("case_lifecycle_derive"):
        options = CASE_RELATION_OPTIONS
        mapping = labels.get("case_relations", {})
        selected = st.selectbox(
            labels.get("relation_label", "関係"),
            options=options,
            format_func=lambda value: mapping.get(value, value),
            key="derive_case_relation",
        )
        if st.button(labels.get("create_derived", "派生を作成"), key="confirm_derive_technical_case", type="primary"):
            st.session_state["case_lifecycle_derive"] = False
            st.session_state["case_derive_relation"] = selected
            return "derive"
    return None


def render_quote_actions_menu(texts: dict, draft) -> Optional[str]:
    labels = lifecycle_texts(texts)
    if draft is None:
        return None
    pending = st.session_state.get("quote_lifecycle_confirm")
    if pending:
        result = render_confirm_bar(
            texts,
            pending,
            confirm_key="confirm_quote_lifecycle",
            cancel_key="cancel_quote_lifecycle",
        )
        if result == "confirm":
            st.session_state["quote_lifecycle_confirm"] = None
            return pending
        if result == "cancel":
            st.session_state["quote_lifecycle_confirm"] = None
            return None
    cols = st.columns(4)
    if cols[0].button(labels.get("duplicate", "複製"), key="duplicate_quote_draft", type="secondary"):
        return "duplicate"
    if cols[1].button(labels.get("derive_quote", "追加・派生見積を作成"), key="derive_quote_draft", type="secondary"):
        st.session_state["quote_lifecycle_derive"] = True
    if cols[2].button(labels.get("archive", "アーカイブ"), key="archive_quote_draft", type="secondary"):
        st.session_state["quote_lifecycle_confirm"] = "archive"
        st.rerun()
    if cols[3].button(labels.get("trash", "ゴミ箱へ移動"), key="trash_quote_draft", type="secondary"):
        st.session_state["quote_lifecycle_confirm"] = "trash"
        st.rerun()
    if draft.archived_at or draft.deleted_at:
        restore_label = labels.get("restore_trash", "ゴミ箱から戻す") if draft.deleted_at else labels.get("restore_archive", "アーカイブから戻す")
        if st.button(restore_label, key="restore_quote_draft", type="secondary"):
            return "restore"
    if st.session_state.get("quote_lifecycle_derive"):
        options = QUOTE_RELATION_OPTIONS
        mapping = labels.get("quote_relations", {})
        selected = st.selectbox(
            labels.get("relation_label", "関係"),
            options=options,
            format_func=lambda value: mapping.get(value, value),
            key="derive_quote_relation",
        )
        if st.button(labels.get("create_derived", "派生を作成"), key="confirm_derive_quote_draft", type="primary"):
            st.session_state["quote_lifecycle_derive"] = False
            st.session_state["quote_derive_relation"] = selected
            return "derive"
    return None
