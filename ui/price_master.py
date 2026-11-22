from __future__ import annotations

from datetime import datetime
from typing import Optional

import streamlit as st

from agents.manufacturer_price_source import (
    CHECK_OK,
    ManufacturerPriceSourceValidationError,
    check_source_connection,
    list_effective_sources,
    save_source_setting,
)
from agents.online_price_master import (
    OnlinePriceReview,
    OnlinePriceReviewStatus,
    activate_reviewed_online_price,
)
from agents.price_master import ONLINE_SYNC_MASTERS, get_active_master, import_price_master
from agents.price_master_csv_fallback import (
    CSV_FALLBACK_SHEETS,
    CsvFallbackError,
    CsvFallbackReview,
    activate_csv_fallback,
    build_csv_fallback_review,
)
from agents.quote_dates import TOKYO
from models import (
    PriceMasterImport,
    PriceMasterImportOutcome,
    PriceMasterImportStatus,
    PriceMasterSourceType,
    PriceMasterType,
)
from repositories.manufacturer_price_source_repository import (
    ManufacturerPriceSourceConflictError,
    ManufacturerPriceSourceRepositoryError,
    ManufacturerPriceSourceRepository,
)
from repositories.sqlite_price_master_repository import SqlitePriceMasterRepository

SESSION_PRICE_MASTER_FLASH = "price_master_flash"
SESSION_SHIPPING_FLASH = "shipping_reference_flash"
ONLINE_SECTION_TITLE = "オンライン価格表（通常はこちら）"
FALLBACK_SECTION_TITLE = "Fallback（オンライン取得できない場合）"
FALLBACK_SECTION_NOTE = (
    "通常はオンライン価格表を利用します。オンライン取得できない場合だけ、Excel（.xlsx）またはCSVを使用してください。"
    "Fallbackを使ってもOnline Source設定は消えません。"
)
EXCEL_FALLBACK_TITLE = "Excel（.xlsx）— 完全Fallback"
CSV_FALLBACK_TITLE = "CSV — 単一Sheet Fallback"
CSV_FALLBACK_NOTE = (
    "CSVは1Sheet分だけです。現在のActive Masterをコピーし、選択したSheetだけをCSV内容で置き換えて、"
    "Workbook全体を検証します。登録・有効化は確認後の明示操作でのみ行います。"
)
ONLINE_FALLBACK_NOTICE = (
    "オンライン価格表を取得できません。現在のActive Masterを継続使用しています。"
    "必要に応じてExcel / CSVのFallbackを使用してください。"
)
SOURCE_UPDATED_AT_LABEL = "最終更新日時（URL保存・最新価格表を確認）"
SOURCE_UPDATED_BY_LABEL = "更新者"
SOURCE_TYPE_LABELS = {
    "MANUFACTURER_ONLINE": "Online",
    "FILE_UPLOAD": "Excel Upload",
    "CSV_UPLOAD": "CSV Upload",
}
CSV_OUTCOME_TEMPLATES = {
    "CSV_REVIEW_REQUIRED": "{label}は、CSVの確認結果に変更がある場合だけ登録できます。現在の価格マスターは変更していません。",
    "CSV_REVIEW_STALE": "確認後に{label}のActive Masterが更新されています。CSVをもう一度検証してください。現在の価格マスターは変更していません。",
}
CSV_ERROR_MESSAGES = {
    "PRICE_BOOK_REQUIRED": "Price Bookを選択してください。",
    "PRICE_BOOK_NOT_ALLOWED": "このPrice BookはCSV Fallbackの対象外です。",
    "SHEET_REQUIRED": "対象Sheetを選択してください。",
    "SHEET_NOT_ALLOWED": "このSheetはCSV Fallbackの対象外です。",
    "SHEET_NOT_IN_ACTIVE_MASTER": "選択したSheetが現在のActive Masterにありません。",
    "NOT_CSV": "CSV（.csv）ファイルを選択してください。",
    "CSV_EMPTY": "CSVが空です。",
    "CSV_TOO_LARGE": "CSVが大きすぎます。",
    "CSV_UNREADABLE": "CSVを読み込めませんでした（UTF-8のCSVを使用してください）。",
    "ACTIVE_MASTER_REQUIRED": "CSV Fallbackには現在のActive Masterが必要です。初回登録はExcel（.xlsx）を使用してください。",
    "ACTIVE_MASTER_UNREADABLE": "現在のActive Masterを読み込めませんでした。",
    "CSV_MISSING_COLUMNS": "CSVに必須列（Part Number / Description / MSRP / Dealer・Gold price）がありません。",
    "CSV_NO_SKUS": "CSVから価格のあるSKUを読み取れませんでした。",
    "PARSER_FAILED": "CSVを反映したWorkbookを読み込めませんでした。",
    "CSV_REVIEW_STALE": "確認中にActive Masterが更新されました。もう一度検証してください。",
    "DEFAULT": "CSVを検証できませんでした。",
}
SHIPPING_ADMIN_TITLE = "国際輸送費（参考）管理"
SHIPPING_SAVE_BUTTON = "国際輸送費を更新"
SHIPPING_UNCHANGED = "変更はありません"
SHIPPING_HISTORY_LABEL = "更新履歴"
SHIPPING_STATUS_LABELS = {"APPROVED": "有効（APPROVED）", "SUPERSEDED": "旧版（SUPERSEDED）"}


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
        source_repository = ManufacturerPriceSourceRepository()
        st.markdown(f"### {labels['online']['settings_title']}")
        st.caption(labels["online"]["settings_safety"])
        sources ={source.source_key: source for source in list_effective_sources(source_repository)}
        for master_type in PriceMasterType:
            if master_type in ONLINE_SYNC_MASTERS:
                _render_manufacturer_book(labels, master_type, sources.get(master_type.value), repository, source_repository)
            else:
                _render_master_section(labels, master_type, repository, source_repository)
    render_shipping_reference_management()


def _render_manufacturer_book(
    labels: dict,
    master_type: PriceMasterType,
    source,
    repository: SqlitePriceMasterRepository,
    source_repository: ManufacturerPriceSourceRepository,
) -> None:
    """One manufacturer Price Book: current source, online (primary), then file fallbacks."""
    st.markdown(f"#### {labels['labels'][master_type.value]}")
    active = repository.get_active(master_type)
    _render_active_source(labels, active)
    st.markdown(f"##### {ONLINE_SECTION_TITLE}")
    if source is not None:
        _render_source_settings(labels, source, source_repository, repository)
    _render_online_review(labels, master_type, repository, source_repository)
    st.markdown(f"##### {FALLBACK_SECTION_TITLE}")
    st.caption(FALLBACK_SECTION_NOTE)
    st.markdown(f"**{EXCEL_FALLBACK_TITLE}**")
    _render_excel_upload(labels, master_type, repository)
    st.markdown(f"**{CSV_FALLBACK_TITLE}**")
    _render_csv_fallback(labels, master_type, repository)
    _render_import_history(labels, master_type, repository)


def describe_active_source(record: Optional[PriceMasterImport]) -> list[tuple[str, str]]:
    """Where the Active master came from, as (label, value) rows. Empty when nothing is active."""
    if record is None:
        return []
    summary = record.validation_summary or {}
    source_type = record.source_type.value
    rows = [("Source Type", SOURCE_TYPE_LABELS.get(source_type, source_type))]
    if source_type == PriceMasterSourceType.MANUFACTURER_ONLINE.value:
        online = summary.get("online_source") or {}
        rows.append(("取得元URL", online.get("source_url") or "-"))
        rows.append(("ファイル名", record.original_filename or "-"))
    elif source_type == PriceMasterSourceType.CSV_UPLOAD.value:
        csv_source = summary.get("csv_source") or {}
        rows.append(("CSVファイル", csv_source.get("csv_filename") or "-"))
        rows.append(("置換Sheet", csv_source.get("replaced_sheet") or "-"))
        rows.append(("Base Master", csv_source.get("base_import_id") or "-"))
    else:
        rows.append(("ファイル名", record.original_filename or "-"))
    rows.append(("取込日時", format_imported_at(record.imported_at)))
    rows.append(("状態", "Active" if record.active else "Inactive"))
    rows.append(("Import ID", record.import_id))
    rows.append(("sha256", f"{record.sha256[:12]}…"))
    if summary.get("imported_by"):
        rows.append(("登録者", summary["imported_by"]))
    return rows


def active_source_headline(record: Optional[PriceMasterImport]) -> str:
    if record is None:
        return "現在使用中：未設定"
    summary = record.validation_summary or {}
    source_type = record.source_type.value
    label = SOURCE_TYPE_LABELS.get(source_type, source_type)
    if source_type == PriceMasterSourceType.MANUFACTURER_ONLINE.value:
        detail = record.master_type.value
    elif source_type == PriceMasterSourceType.CSV_UPLOAD.value:
        detail = (summary.get("csv_source") or {}).get("csv_filename") or "-"
    else:
        detail = record.original_filename or "-"
    return f"現在使用中：{label} / {detail}"


def _render_active_source(labels: dict, active: Optional[PriceMasterImport]) -> None:
    with st.container(border=True):
        st.markdown(f"**{active_source_headline(active)}**")
        rows = describe_active_source(active)
        if rows:
            st.table([{"項目": key, "内容": value} for key, value in rows])
            st.caption(f"{labels['validation_label']}：{format_validation(labels, active)}")


def _render_source_settings(labels: dict, source, source_repository, price_master_repository) -> None:
    online = labels["online"]
    version_key = f"manufacturer_source_version_{source.source_key}"
    if version_key not in st.session_state:
        st.session_state[version_key] = source.row_version
    state = online["enabled"] if source.enabled else online["disabled"]
    st.write(f"{online['state_label']}：{state}")
    st.write(
        f"{online['checked_at_label']}：{format_imported_at(source.last_checked_at)} ／ "
        f"{online['check_status_label']}：{source.last_check_status or online['not_checked']}"
    )
    st.caption(
        f"{SOURCE_UPDATED_AT_LABEL}：{format_imported_at(source.updated_at)} ／ "
        f"{SOURCE_UPDATED_BY_LABEL}：{source.updated_by or '-'}"
    )
    url = st.text_input(
        online["url_label"],
        value=source.source_url,
        key=f"manufacturer_source_url_{source.source_key}",
    )
    enabled = st.checkbox(
        online["enabled_label"],
        value=source.enabled,
        key=f"manufacturer_source_enabled_{source.source_key}",
    )
    save_column, check_column = st.columns(2)
    if save_column.button(online["save_url_button"], key=f"manufacturer_source_save_{source.source_key}"):
        try:
            save_source_setting(
                source.source_key,
                url,
                enabled,
                expected_row_version=st.session_state[version_key],
                repository=source_repository,
            )
        except ManufacturerPriceSourceValidationError:
            st.session_state[SESSION_PRICE_MASTER_FLASH] = ("error", online["invalid_url"])
        except ManufacturerPriceSourceConflictError:
            st.session_state.pop(version_key, None)
            st.session_state[SESSION_PRICE_MASTER_FLASH] = ("error", online["conflict"])
        except ManufacturerPriceSourceRepositoryError:
            st.session_state[SESSION_PRICE_MASTER_FLASH] = ("error", online["registry_unavailable"])
        else:
            st.session_state.pop(version_key, None)
            st.session_state.pop(_review_key_for_source(source.source_key), None)
            st.session_state[SESSION_PRICE_MASTER_FLASH] = ("success", online["saved"])
        st.rerun()
    if check_column.button(online["connection_button"], key=f"manufacturer_source_check_{source.source_key}"):
        try:
            updated, review = check_source_connection(
                source.model_copy(update={"row_version": st.session_state[version_key]}),
                source_repository=source_repository,
                price_master_repository=price_master_repository,
            )
        except ManufacturerPriceSourceValidationError:
            st.session_state[SESSION_PRICE_MASTER_FLASH] = ("error", online["save_before_check"])
        except ManufacturerPriceSourceConflictError:
            st.session_state.pop(version_key, None)
            st.session_state[SESSION_PRICE_MASTER_FLASH] = ("error", online["conflict"])
        except ManufacturerPriceSourceRepositoryError:
            st.session_state[SESSION_PRICE_MASTER_FLASH] = ("error", online["registry_unavailable"])
        else:
            st.session_state.pop(version_key, None)
            if review is not None:
                st.session_state[_review_key_for_source(source.source_key)] = review
            ok = updated.last_check_status in CHECK_OK
            message = online["connection_ok"] if ok else f"{online['connection_failed']} {ONLINE_FALLBACK_NOTICE}"
            st.session_state[SESSION_PRICE_MASTER_FLASH] = ("success" if ok else "error", message)
        st.rerun()


def _review_key_for_source(source_key: str) -> str:
    return f"online_price_review_{source_key}"


def _render_master_section(
    labels: dict,
    master_type: PriceMasterType,
    repository: SqlitePriceMasterRepository,
    source_repository: ManufacturerPriceSourceRepository,
) -> None:
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
    _render_excel_upload(labels, master_type, repository)
    _render_import_history(labels, master_type, repository)


def _render_excel_upload(labels: dict, master_type: PriceMasterType, repository: SqlitePriceMasterRepository) -> None:
    uploaded = st.file_uploader(labels["upload_label"], type=["xlsx"], key=f"price_master_upload_{master_type.value}")
    if st.button(labels["import_button"], key=f"price_master_import_{master_type.value}"):
        if uploaded is None:
            st.warning(labels["no_file"])
        else:
            outcome = import_price_master(master_type, uploaded.name, uploaded.getvalue(), repository=repository)
            st.session_state[SESSION_PRICE_MASTER_FLASH] = outcome_message(labels, outcome)
            st.rerun()


def _render_import_history(labels: dict, master_type: PriceMasterType, repository: SqlitePriceMasterRepository) -> None:
    history = repository.list_imports(master_type)
    with st.expander(labels["history_label"], expanded=False):
        if not history:
            st.text(labels["no_history"])
        else:
            st.table(
                [
                    {
                        labels["imported_at_label"]: format_imported_at(item.imported_at),
                        "Source": SOURCE_TYPE_LABELS.get(item.source_type.value, item.source_type.value),
                        labels["file_label"]: item.original_filename or "-",
                        labels["hash_label"]: f"{item.sha256[:12]}…",
                        labels["current_label"]: labels["status_active"] if item.active else labels["status_inactive"],
                        labels["validation_label"]: format_validation(labels, item),
                    }
                    for item in history
                ]
            )


def _csv_review_key(master_type: PriceMasterType) -> str:
    return f"csv_fallback_review_{master_type.value}"


def _render_csv_fallback(labels: dict, master_type: PriceMasterType, repository: SqlitePriceMasterRepository) -> None:
    st.caption(CSV_FALLBACK_NOTE)
    if repository.get_active(master_type) is None:
        st.info(CSV_ERROR_MESSAGES["ACTIVE_MASTER_REQUIRED"])
        return
    book_column, sheet_column = st.columns(2)
    selected_book = book_column.selectbox(
        "Price Book",
        [master_type.value],
        index=None,
        placeholder="選択してください",
        key=f"csv_price_book_{master_type.value}",
    )
    selected_sheet = sheet_column.selectbox(
        "対象Sheet",
        list(CSV_FALLBACK_SHEETS[master_type]),
        index=None,
        placeholder="選択してください",
        key=f"csv_sheet_{master_type.value}",
    )
    uploaded = st.file_uploader("CSVファイル", type=["csv"], key=f"csv_upload_{master_type.value}")
    if st.button("CSVを検証して差分を確認", key=f"csv_validate_{master_type.value}"):
        st.session_state.pop(_csv_review_key(master_type), None)
        if uploaded is None:
            st.session_state[SESSION_PRICE_MASTER_FLASH] = ("error", "CSVファイルを選択してください。現在の価格マスターは変更していません。")
        else:
            try:
                fallback = build_csv_fallback_review(
                    selected_book,
                    selected_sheet,
                    uploaded.name,
                    uploaded.getvalue(),
                    repository=repository,
                )
            except CsvFallbackError as error:
                message = CSV_ERROR_MESSAGES.get(error.code, CSV_ERROR_MESSAGES["DEFAULT"])
                st.session_state[SESSION_PRICE_MASTER_FLASH] = ("error", f"{message} 現在の価格マスターは変更していません。")
            else:
                st.session_state[_csv_review_key(master_type)] = fallback
        st.rerun()
    fallback = st.session_state.get(_csv_review_key(master_type))
    if not isinstance(fallback, CsvFallbackReview):
        return
    review = fallback.review
    st.caption(f"検証済みCSV：{fallback.csv_filename} ／ 置換Sheet：{fallback.sheet_name} ／ Base Master：{fallback.base_import_id}")
    if review.error_count:
        status_text = labels["online"]["statuses"].get(review.status.value, labels["online"]["statuses"]["VALIDATION_FAILED"])
        st.error(status_text.format(label=labels["labels"][master_type.value]))
        return
    _render_review_summary(labels, review)
    if review.status == OnlinePriceReviewStatus.NO_CHANGE:
        st.info(labels["online"]["no_change"])
        return
    if st.button("CSV反映版を新しいPrice Masterとして登録・有効化", key=f"csv_activate_{master_type.value}"):
        outcome = activate_csv_fallback(fallback, repository=repository)
        st.session_state.pop(_csv_review_key(master_type), None)
        st.session_state[SESSION_PRICE_MASTER_FLASH] = outcome_message(labels, outcome)
        st.rerun()


def _render_review_summary(labels: dict, review: OnlinePriceReview) -> None:
    online = labels["online"]
    st.markdown(f"**{online['summary_title']}**")
    st.write(online["price_changes"].format(count=review.price_change_count))
    st.write(online["dealer_changes"].format(count=review.dealer_change_count))
    st.write(online["msrp_changes"].format(count=review.msrp_change_count))
    st.write(online["sku_added"].format(count=review.added_count))
    st.write(online["sku_removed"].format(count=review.removed_count))
    st.write(online["errors"].format(count=review.error_count))
    if review.changes:
        kind_labels = online["change_kinds"]
        with st.expander(online["details"], expanded=False):
            st.table(
                [
                    {
                        online["column_sku"]: item.sku,
                        online["column_change"]: kind_labels[item.kind],
                        online["column_dealer"]: _price_pair(item.old_dealer, item.new_dealer),
                        online["column_msrp"]: _price_pair(item.old_msrp, item.new_msrp),
                    }
                    for item in review.changes
                ]
            )


def _review_key(master_type: PriceMasterType) -> str:
    return _review_key_for_source(master_type.value)


def _render_online_review(labels: dict, master_type: PriceMasterType, repository, source_repository) -> None:
    """Show the review stored by 最新価格表を確認 (check_source_connection). Nothing when there is none."""
    online = labels["online"]
    review = st.session_state.get(_review_key(master_type))
    if not isinstance(review, OnlinePriceReview):
        return
    if review.error_count:
        st.error(online["statuses"][review.status.value].format(label=labels["labels"][master_type.value]))
        st.warning(ONLINE_FALLBACK_NOTICE)
        return
    _render_review_summary(labels, review)
    if review.status == OnlinePriceReviewStatus.NO_CHANGE:
        st.info(online["no_change"])
        return
    if st.button(online["activate_button"], key=f"online_price_activate_{master_type.value}"):
        outcome = activate_reviewed_online_price(
            review,
            repository=repository,
            source_repository=source_repository,
        )
        if outcome.status == PriceMasterImportStatus.REJECTED:
            if outcome.reason_code == "ONLINE_REVIEW_STALE":
                st.session_state.pop(_review_key(master_type), None)
            st.session_state[SESSION_PRICE_MASTER_FLASH] = outcome_message(labels, outcome)
        else:
            st.session_state.pop(_review_key(master_type), None)
            st.session_state[SESSION_PRICE_MASTER_FLASH] = outcome_message(labels, outcome)
        st.rerun()


def _price_pair(old, new) -> str:
    if old is None and new is None:
        return "-"
    left = "-" if old is None else f"{old:g}"
    right = "-" if new is None else f"{new:g}"
    if old is None:
        return right
    if new is None:
        return left
    if old == new:
        return left
    return f"{left} → {right}"


def outcome_message(labels: dict, outcome: PriceMasterImportOutcome) -> tuple[str, str]:
    label = labels["labels"][outcome.master_type.value]
    templates = labels["outcomes"]
    record = outcome.record
    if outcome.status == PriceMasterImportStatus.REJECTED:
        template = (
            templates.get(outcome.reason_code or "")
            or CSV_OUTCOME_TEMPLATES.get(outcome.reason_code or "")
            or templates.get("VALIDATION_FAILED")
            or "{label}: validation failed"
        )
        return "error", template.format(label=label)
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


def render_shipping_reference_management() -> None:
    """Manual International Shipping Reference Master: view, explicit update, history. No deletion."""
    from repositories.actor import current_actor
    from repositories.shipping_rule_repository import (
        CHARGE_BASIS_BY_TYPE,
        CHARGE_BASIS_LABELS,
        SHIPPING_TYPE_LABELS,
        STANDARD_GLOBAL_TYPES,
        ShippingRuleRepository,
        ShippingRuleRepositoryError,
        ShippingRuleValidationError,
    )
    from ui.price_catalog import SHIPPING_BASIS_NOTE, SHIPPING_INFO, currency_column_config

    st.header(SHIPPING_ADMIN_TITLE)
    st.caption(SHIPPING_INFO)
    st.caption(SHIPPING_BASIS_NOTE)
    flash = st.session_state.pop(SESSION_SHIPPING_FLASH, None)
    if flash:
        level, text = flash
        (st.success if level == "success" else st.info if level == "info" else st.error)(text)
    try:
        repository = ShippingRuleRepository()
        current = {shipping_type: repository.get_active_standard_global(shipping_type) for shipping_type in STANDARD_GLOBAL_TYPES}
        history = repository.list_history()
    except ShippingRuleRepositoryError:
        st.warning("国際輸送費マスターを読み込めませんでした。DB migrationの適用状況を確認してください。")
        return

    for shipping_type in STANDARD_GLOBAL_TYPES:
        active = current[shipping_type]
        basis = CHARGE_BASIS_BY_TYPE[shipping_type]
        version = active.rule.shipping_rule_id if active is not None else "new"
        with st.container(border=True):
            st.markdown(f"**{SHIPPING_TYPE_LABELS[shipping_type]}**")
            if active is None:
                st.warning("未登録（要確認）")
            info = {
                "区分": SHIPPING_TYPE_LABELS[shipping_type],
                "現在金額 USD": f"${active.rule.rate_usd:,.2f}" if active is not None else "-",
                "課金単位": CHARGE_BASIS_LABELS[basis],
                "基準日": active.rule.effective_from.date().isoformat() if active is not None and active.rule.effective_from else "-",
                "登録日時": format_imported_at(active.registered_at) if active is not None else "-",
                "最終更新日時": format_imported_at(active.last_updated_at) if active is not None else "-",
                "メモ": (active.rule.notes or "-") if active is not None else "-",
            }
            st.table([info])
            rate_column, date_column = st.columns(2)
            rate = rate_column.number_input(
                "USD金額",
                min_value=0.0,
                value=float(active.rule.rate_usd) if active is not None else None,
                step=0.01,
                format="%.2f",
                key=f"shipping_rate_{shipping_type.value}_{version}",
            )
            effective = date_column.date_input(
                "基準日",
                value=active.rule.effective_from.date() if active is not None and active.rule.effective_from else None,
                key=f"shipping_effective_{shipping_type.value}_{version}",
            )
            notes = st.text_area(
                "メモ",
                value=(active.rule.notes or "") if active is not None else "",
                key=f"shipping_notes_{shipping_type.value}_{version}",
            )
            if st.button(SHIPPING_SAVE_BUTTON, key=f"shipping_save_{shipping_type.value}"):
                try:
                    saved = repository.save_standard_global_rate(
                        shipping_type,
                        rate_usd=rate,
                        effective_from=effective,
                        notes=notes,
                        created_by=current_actor(),
                    )
                except ShippingRuleValidationError as error:
                    st.session_state[SESSION_SHIPPING_FLASH] = ("error", str(error))
                except ShippingRuleRepositoryError:
                    st.session_state[SESSION_SHIPPING_FLASH] = ("error", "国際輸送費を保存できませんでした。再読み込みして確認してください。")
                else:
                    if saved is None:
                        st.session_state[SESSION_SHIPPING_FLASH] = ("info", SHIPPING_UNCHANGED)
                    else:
                        st.session_state[SESSION_SHIPPING_FLASH] = (
                            "success",
                            f"{SHIPPING_TYPE_LABELS[shipping_type]} を ${saved.rule.rate_usd:,.2f} に更新しました。",
                        )
                st.rerun()

    with st.expander(SHIPPING_HISTORY_LABEL, expanded=False):
        if not history:
            st.text("履歴はありません。")
        else:
            st.dataframe(
                [
                    {
                        "Shipping Type": SHIPPING_TYPE_LABELS.get(item.rule.shipping_type, item.rule.shipping_type.value),
                        "USD": item.rule.rate_usd,
                        "課金単位": CHARGE_BASIS_LABELS.get(item.rule.charge_basis, "-"),
                        "基準日": item.rule.effective_from.date().isoformat() if item.rule.effective_from else "-",
                        "状態": SHIPPING_STATUS_LABELS.get(item.rule.status.value, item.rule.status.value),
                        "登録日時": format_imported_at(item.created_at),
                        "登録者": item.created_by or "-",
                        "メモ": item.rule.notes or "-",
                    }
                    for item in history
                ],
                use_container_width=True,
                hide_index=True,
                column_config=currency_column_config(("USD",), ()),
            )
