from __future__ import annotations

from datetime import datetime
from typing import Optional

import streamlit as st

from agents.price_master import get_active_master, import_price_master
from agents.quote_dates import TOKYO
from models import PriceMasterImport, PriceMasterImportOutcome, PriceMasterImportStatus, PriceMasterType
from repositories.sqlite_price_master_repository import SqlitePriceMasterRepository

SESSION_PRICE_MASTER_FLASH = "price_master_flash"


def render_price_master_summary(page: dict) -> None:
    labels = page["price_masters"]
    with st.container(border=True):
        st.markdown(f"**{labels['summary_title']}**")
        columns = st.columns(len(PriceMasterType))
        for column, master_type in zip(columns, PriceMasterType):
            active = get_active_master(master_type)
            name = labels["short_labels"][master_type.value]
            if active is None:
                column.write(f"{name}：{labels['summary_unset']}")
            else:
                date = format_imported_at(active.record.imported_at, date_only=True)
                column.write(f"{name}：{labels['status_active']} / {labels['summary_active'].format(date=date)}")


def render_price_master_management(page: dict) -> None:
    labels = page["price_masters"]
    with st.expander(labels["management_title"], expanded=False):
        st.caption(labels["management_description"])
        flash = st.session_state.pop(SESSION_PRICE_MASTER_FLASH, None)
        if flash:
            level, text = flash
            (st.success if level == "success" else st.info if level == "info" else st.error)(text)
        repository = SqlitePriceMasterRepository()
        for master_type in PriceMasterType:
            _render_master_section(labels, master_type, repository)


def _render_master_section(labels: dict, master_type: PriceMasterType, repository: SqlitePriceMasterRepository) -> None:
    st.markdown(f"#### {labels['labels'][master_type.value]}")
    active = repository.get_active(master_type)
    if active is None:
        st.write(f"{labels['current_label']}：{labels['status_unset']}")
    else:
        st.write(f"{labels['current_label']}：{labels['status_active']}")
        st.write(
            f"{labels['imported_at_label']}：{format_imported_at(active.imported_at)} ／ "
            f"{labels['file_label']}：{active.original_filename or '-'} ／ "
            f"{labels['hash_label']}：{active.sha256[:12]}…"
        )
        st.caption(f"{labels['validation_label']}：{format_validation(labels, active)}")
    uploaded = st.file_uploader(labels["upload_label"], type=["xlsx"], key=f"price_master_upload_{master_type.value}")
    if st.button(labels["import_button"], key=f"price_master_import_{master_type.value}"):
        if uploaded is None:
            st.warning(labels["no_file"])
        else:
            outcome = import_price_master(master_type, uploaded.name, uploaded.getvalue(), repository=repository)
            st.session_state[SESSION_PRICE_MASTER_FLASH] = outcome_message(labels, outcome)
            st.rerun()
    history = repository.list_imports(master_type)
    with st.expander(labels["history_label"], expanded=False):
        if not history:
            st.text(labels["no_history"])
        else:
            st.table(
                [
                    {
                        labels["imported_at_label"]: format_imported_at(item.imported_at),
                        labels["file_label"]: item.original_filename or "-",
                        labels["hash_label"]: f"{item.sha256[:12]}…",
                        labels["current_label"]: labels["status_active"] if item.active else labels["status_inactive"],
                        labels["validation_label"]: format_validation(labels, item),
                    }
                    for item in history
                ]
            )


def outcome_message(labels: dict, outcome: PriceMasterImportOutcome) -> tuple[str, str]:
    label = labels["labels"][outcome.master_type.value]
    templates = labels["outcomes"]
    record = outcome.record
    if outcome.status == PriceMasterImportStatus.REJECTED:
        return "error", templates[outcome.reason_code or "VALIDATION_FAILED"].format(label=label)
    text = templates[outcome.status.value].format(
        label=label,
        file=record.original_filename if record else "-",
        date=format_imported_at(record.imported_at, date_only=True) if record else "-",
    )
    return ("success" if outcome.status == PriceMasterImportStatus.ACTIVATED else "info"), text


def format_validation(labels: dict, record: PriceMasterImport) -> str:
    summary = dict(record.validation_summary or {})
    for key in ("import_tax_rate", "insurance_rate"):
        if key in summary:
            summary[key] = f"{summary[key]:.0%}" if isinstance(summary[key], (int, float)) else "-"
    if "shipping_markup" in summary and summary["shipping_markup"] is None:
        summary["shipping_markup"] = "-"
    try:
        return labels["validation_formats"][record.master_type.value].format(**summary)
    except (KeyError, ValueError):
        return "-"


def format_imported_at(value: Optional[str], *, date_only: bool = False) -> str:
    if not value:
        return "-"
    try:
        moment = datetime.fromisoformat(value).astimezone(TOKYO)
    except ValueError:
        return value
    return moment.strftime("%Y-%m-%d" if date_only else "%Y-%m-%d %H:%M")
