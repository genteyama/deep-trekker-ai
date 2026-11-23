"""PORTAL-3B.1 one-screen quote builder (見積作成).

Customer → search and pick products → quantities → GlobalShipping → amounts and margin → save / approve /
export, all on one page. Calculation, approval (PORTAL-3A) and export reuse the existing workspace code.
"""

from __future__ import annotations

import logging
from typing import Optional

import streamlit as st

from agents.general_quote_entry import GeneralQuoteEntryError
from agents.simple_quote_builder import (
    GLOBAL_SHIPPING_PRICE_BOOKS,
    SIMPLE_PRICE_BOOKS,
    SPECTRA_PRICE_BOOK,
    SimpleQuoteError,
    add_products,
    adjust_global_shipping,
    clear_global_shipping,
    create_simple_quote_draft,
    clear_spectra_shipping,
    customer_summary,
    move_line,
    price_books_in,
    price_list_sales_candidates,
    purchase_breakdown,
    purchase_price,
    remove_line,
    revenue_summary,
    select_global_shipping,
    set_customer_info,
    set_quantity,
    set_spectra_shipping,
    shipping_breakdown,
    sync_after_rate_change,
)
from agents.quote_builder import apply_tax_rate
from models import FinalPriceStatus, QuoteDraftStatus
from repositories.actor import acting_person
from ui.quote_format import display_number, display_percent, display_yen
from ui.quote_ui_mode import QUOTE_UI_LEGACY, QUOTE_UI_MODE_KEY

logger = logging.getLogger(__name__)

DEFAULT_TAX_RATE = 0.10  # Shown and editable on screen; the quote stores the rate the person kept.
SESSION_PICKER_VERSION = "simple_picker_version"
SESSION_FLASH = "simple_quote_flash"
PRODUCT_COLUMNS = ["選択", "製品名", "SKU", "標準売価 JPY", "Price Book", "Sheet / Category"]

ERRORS = {
    "CUSTOMER_REQUIRED": "顧客名を入力してください。",
    "NO_ITEMS": "見積に追加する商品を選択してください。",
    "QUANTITY_INVALID": "数量は1以上の整数で入力してください。",
    "SHIPPING_RATE_INVALID": "国際輸送費（USD）は0より大きい数値で入力してください。",
    "SHIPPING_REASON_REQUIRED": "国際輸送費を手動調整する場合は理由を入力してください。",
    "CUSTOMER_SHIPPING_INVALID": "顧客向け輸送費は0以上の金額で入力してください。",
    "CUSTOMER_SHIPPING_UNIT": "顧客向け輸送費は千円単位で入力してください。",
    "CUSTOMER_SHIPPING_REASON_REQUIRED": "顧客向け輸送費を手動調整する場合は理由を入力してください。",
    "SHIPPING_NOT_SELECTED": "先に国際輸送費（GlobalShipping）を選択してください。",
    "POLICY_MISSING": "見積計算ポリシー（QUOTE_CALC）がありません。価格マスター管理を確認してください。",
    "SOURCE_CHANGED": "価格マスターが更新されたため追加できませんでした。商品一覧から選び直してください。",
    "PRICE_BOOK_INVALID": "DT40 / PT30 / SPECTRA GOLD の商品を選択してください。",
    "GLOBAL_SHIPPING_NEEDS_DT_PT": "GlobalShipping は Deep Trekker / PipeTrekker の商品がある見積でのみ使います。",
    "SPECTRA_SHIPPING_NEEDS_SPECTRA": "SPECTRA GOLD の商品がある見積でのみ入力できます。",
    "SPECTRA_SHIPPING_REASON_REQUIRED": "SPECTRA GOLD 国際輸送費の理由・根拠を入力してください。",
}


def render_simple_quote_builder(page: dict, helpers: dict) -> None:
    from ui.quote_workspace import _save_draft

    # Every standard price on this page (add, exchange-rate change) follows the 価格一覧 rule.
    base_candidates = helpers["sales_candidates_for_rate"]
    helpers = {**helpers, "sales_candidates_for_rate": lambda rate: price_list_sales_candidates(base_candidates(rate))}
    draft = st.session_state.get("quote_draft")
    snapshot = st.session_state.get("approved_quote_snapshot")
    if draft is not None:
        sync_after_rate_change(draft)
    _render_flash()
    locked = draft is not None and draft.status in {QuoteDraftStatus.APPROVED, QuoteDraftStatus.SUPERSEDED}

    _render_customer(draft, locked)
    _render_exchange_rate(page, helpers, draft, locked)
    if not locked:
        _render_product_picker(page, helpers, draft)
    _render_lines(page, draft, locked)
    if draft is not None and draft.configuration_lines:
        _render_shipping(draft, locked)
        _render_customer_summary(draft, locked)
        _render_revenue_summary(page, draft)
        _render_save_and_approval(page, helpers, draft, snapshot)
    _render_other_quotes()
    draft = st.session_state.get("quote_draft")
    if draft is not None:
        _save_draft(page, draft, manual=False)


# ---- A. customer ----------------------------------------------------------------------------------


def _render_customer(draft, locked: bool) -> None:
    with st.container(border=True):
        st.subheader("顧客情報")
        if draft is not None:
            top, new_column = st.columns([4, 1])
            top.caption(f"見積ID：{draft.quote_draft_id} ／ v{draft.quote_version} ／ 状態：{_status_label(draft)}")
            if new_column.button("新しい見積", key="simple_new_quote"):
                for key in ("quote_draft", "approved_quote_snapshot", "quote_approval_validation"):
                    st.session_state[key] = None
                st.session_state.pop("simple_customer", None)
                st.session_state.pop("simple_title", None)
                st.rerun()
        left, right = st.columns(2)
        if draft is None:
            left.text_input("顧客名（必須）", key="simple_customer")
            right.text_input("件名", key="simple_title")
            return
        suffix = f"{draft.quote_draft_id}_{draft.quote_version}"
        customer = left.text_input("顧客名（必須）", value=draft.customer or "", key=f"simple_customer_{suffix}", disabled=locked)
        title = right.text_input("件名", value=draft.title or "", key=f"simple_title_{suffix}", disabled=locked)
        if not locked and ((customer or "").strip() != (draft.customer or "") or ((title or "").strip() or None) != draft.title):
            try:
                set_customer_info(draft, customer, title)
            except SimpleQuoteError as error:
                st.warning(ERRORS.get(error.code, error.code))


# ---- exchange rate ------------------------------------------------------------------------------


def _new_quote_rate() -> float:
    from agents.pricing_policy import parse_exchange_rate
    from ui.quote_steps import SESSION_NEW_QUOTE_FX, ensure_new_quote_exchange_rate

    ensure_new_quote_exchange_rate(st.session_state)
    return parse_exchange_rate(st.session_state[SESSION_NEW_QUOTE_FX])


def _render_exchange_rate(page: dict, helpers: dict, draft, locked: bool) -> None:
    rate = draft.exchange_rate if draft is not None else _safe_new_rate()
    st.caption(f"使用為替：1 USD = ¥{display_number(rate, '-')}")
    if locked:
        return
    with st.expander("為替を変更", expanded=False):
        if draft is None:
            from ui.quote_workspace import _render_new_quote_exchange_rate

            _render_new_quote_exchange_rate(page)
        else:
            from ui.quote_workspace import _render_exchange_rate_editor

            _render_exchange_rate_editor(page, helpers, draft)


def _safe_new_rate() -> Optional[float]:
    try:
        return _new_quote_rate()
    except ValueError:
        return None


# ---- B. product picker ----------------------------------------------------------------------------


@st.cache_data(show_spinner=False, max_entries=8)
def _catalog_rows(master_key: tuple, rate: float) -> list[dict]:
    """Selectable DT40 / PT30 rows with the standard price at `rate`. Keyed by the Active import IDs."""
    from agents.price_master import active_price_books, load_active_spaceone_master
    from agents.pricing_policy import is_customer_price_unit, round_customer_price_jpy
    from ui.price_catalog import STATUS_OFFICIAL, _reference_sales_candidates, build_price_catalog_rows, build_reference_sales_map

    books = [item for item in active_price_books() if item.record.master_type.value in SIMPLE_PRICE_BOOKS]
    reference = {}
    if load_active_spaceone_master() is not None:
        reference = build_reference_sales_map(
            _reference_sales_candidates(books, rate),
            round_customer_price=round_customer_price_jpy,
            is_customer_price_unit=is_customer_price_unit,
        )
    rows = build_price_catalog_rows(books, reference_sales=reference)
    # Only rows the quote engine can price from the Active master are offered for normal selection.
    return [row for row in rows if row["メーカー価格状態"] == STATUS_OFFICIAL]


def _master_key() -> tuple:
    from agents.price_master import get_active_master
    from models import PriceMasterType

    keys = []
    for master_type in (PriceMasterType.DT40, PriceMasterType.PT30, PriceMasterType.SPECTRA_GOLD, PriceMasterType.SO_MASTER):
        active = get_active_master(master_type)
        keys.append(active.record.import_id if active else None)
    return tuple(keys)


def filter_product_rows(rows: list[dict], *, keyword: str = "", price_books=None, kind: Optional[str] = None) -> list[dict]:
    """商品種別 → Price Book → 検索語 (製品名 / SKU / Sheet). No Price Book selected means every Price Book."""
    from ui.price_catalog import filter_by_product_kind, filter_price_catalog_rows

    return filter_price_catalog_rows(filter_by_product_kind(rows, kind), keyword=keyword, price_books=price_books or [])


def price_book_label(page: dict, book: Optional[str]) -> str:
    """Price Book display name, the same as 価格マスター管理 (short labels)."""
    labels = (page.get("price_masters") or {}).get("short_labels") or {}
    return labels.get(book or "", book or "-")


def _render_product_picker(page: dict, helpers: dict, draft) -> None:
    with st.container(border=True):
        st.subheader("商品を選ぶ")
        rate = draft.exchange_rate if draft is not None else _safe_new_rate()
        if not rate:
            st.warning("見積用為替が不正です。「為替を変更」で確認してください。")
            return
        try:
            rows = _catalog_rows(_master_key(), float(rate))
        except Exception:
            logger.exception("simple_quote_catalog_failed")
            st.error("価格マスターを読み込めませんでした。価格マスター管理を確認してください。")
            return
        if not rows:
            st.warning("選択できる商品がありません。Active DT40 / PT30 価格マスターを確認してください。")
            return
        from ui.price_catalog import PRODUCT_KIND_ALL, PRODUCT_KINDS

        kind = st.radio("商品種別", list(PRODUCT_KINDS), horizontal=True, key="simple_product_kind") or PRODUCT_KIND_ALL
        search_column, book_column = st.columns([3, 2])
        keyword = search_column.text_input(
            "製品名・SKUで検索", placeholder="例：PHOTON / REVOLUTION / GRABBER / 70250", key="simple_search"
        )
        available = [book for book in SIMPLE_PRICE_BOOKS if any(row["Price Book"] == book for row in rows)]
        books = book_column.segmented_control(
            "Price Book",
            available,
            selection_mode="multi",
            format_func=lambda book: price_book_label(page, book),
            key="simple_price_books",
        )
        books = list(books or [])
        filtered = filter_product_rows(rows, keyword=keyword, price_books=books, kind=kind)
        scope = "全Price Book" if not books else " + ".join(price_book_label(page, book) for book in books)
        st.caption(f"{len(filtered)} / {len(rows)} 件 ・ {kind} ・ {scope} ・ チェックして「見積に追加」")
        if kind != PRODUCT_KIND_ALL:
            st.caption("商品種別で絞り込むと、種別を判定できない商品（補修部品など）は表示されません。「すべて」で全商品を表示します。")
        version = st.session_state.get(SESSION_PICKER_VERSION, 0)
        edited = st.data_editor(
            [
                {
                    "選択": False,
                    "製品名": row["製品名"],
                    "SKU": row["SKU"],
                    "標準売価 JPY": row["SpaceOne参考売価 JPY"],
                    "Price Book": price_book_label(page, row["Price Book"]),
                    "Sheet / Category": row["Source Sheet"],
                }
                for row in filtered
            ],
            key=f"simple_picker_{version}_{hash((kind, keyword, tuple(books)))}",
            hide_index=True,
            use_container_width=True,
            height=320,
            disabled=PRODUCT_COLUMNS[1:],
            column_order=PRODUCT_COLUMNS,
            column_config={
                "選択": st.column_config.CheckboxColumn("選択"),
                "標準売価 JPY": st.column_config.NumberColumn("標準売価 JPY", format="yen"),
            },
        )
        chosen = picked_items(filtered, _editor_rows(edited))
        if st.button(f"見積に追加（{len(chosen)}件）", key="simple_add_products", type="primary", disabled=not chosen):
            _add_products(page, helpers, draft, chosen)


def picked_items(rows: list[dict], edited_rows: list[dict]) -> list[dict]:
    """The checked catalog rows as add items. The row itself (price book, master import, prices, sheet)
    is what gets added, not just its SKU. The editor rows are in the same order as `rows`."""
    return [
        {
            "sku": row["SKU"],
            "quantity": 1,
            "price_book": row["Price Book"],
            "import_id": row.get("Import ID"),
            "msrp_usd": row.get("MSRP USD"),
            "dealer_price_usd": row.get("Dealer USD"),
            "source_sheet": row.get("Source Sheet"),
        }
        for row, edited in zip(rows, edited_rows)
        if edited.get("選択")
    ]


def _editor_rows(edited) -> list[dict]:
    if edited is None:
        return []
    if hasattr(edited, "to_dict"):
        return edited.to_dict("records")
    return list(edited)


def _add_products(page: dict, helpers: dict, draft, items: list[dict]) -> None:
    from ui.quote_persistence import reset_pending_form
    from ui.quote_steps import new_quote_exchange_rate_source
    from ui.quote_workspace import _save_draft

    try:
        if draft is None:
            customer = (st.session_state.get("simple_customer") or "").strip()
            if not customer:
                raise SimpleQuoteError("CUSTOMER_REQUIRED")
            rate = _new_quote_rate()
            draft = create_simple_quote_draft(
                customer=customer,
                title=st.session_state.get("simple_title"),
                items=items,
                exchange_rate=rate,
                exchange_rate_source=new_quote_exchange_rate_source(st.session_state),
                tax_rate=DEFAULT_TAX_RATE,
                sales_candidates=helpers["sales_candidates_for_rate"](rate),
            )
            st.session_state["quote_draft"] = draft
            st.session_state["approved_quote_snapshot"] = None
            st.session_state["quote_approval_validation"] = None
            helpers["init_date_widgets"](draft, overwrite=True)
            reset_pending_form(st.session_state, 1)
        else:
            add_products(draft, items, sales_candidates=helpers["sales_candidates_for_rate"](draft.exchange_rate))
            st.session_state["quote_draft"] = draft
    except SimpleQuoteError as error:
        st.error(ERRORS.get(error.code, error.code))
        return
    except GeneralQuoteEntryError as error:
        message = page["workspace"]["general_errors"].get(error.code, page["workspace"]["general_errors"]["UNEXPECTED"])
        st.error(message.format(sku=error.sku) if error.sku and "{sku}" in message else message)
        return
    except Exception:
        logger.exception("simple_quote_add_failed")
        st.error(page["workspace"]["general_errors"]["UNEXPECTED"])
        return
    _save_draft(page, draft, manual=True, from_widgets=False)
    st.session_state[SESSION_PICKER_VERSION] = st.session_state.get(SESSION_PICKER_VERSION, 0) + 1
    st.rerun()


# ---- C. lines -------------------------------------------------------------------------------------


LINE_COLUMNS = [0.7, 3.0, 1.7, 1.5, 1.3, 1.0, 1.4, 0.8]


def _render_lines(page: dict, draft, locked: bool) -> None:
    with st.container(border=True):
        st.subheader("見積明細")
        if draft is None or not draft.configuration_lines:
            st.caption("商品を選んで「見積に追加」すると、ここに表示されます。")
            return
        header = st.columns(LINE_COLUMNS)
        titles = ("順番", "製品名", "SKU / Price Book", "仕入価格 USD", "売価 JPY", "数量", "小計", "")
        for column, text in zip(header, titles):
            column.markdown(f"**{text}**")
        lines = list(draft.configuration_lines)
        for index, line in enumerate(lines):
            order, name, sku, purchase, unit, quantity, subtotal, remove = st.columns(LINE_COLUMNS)
            if locked:
                order.write(str(index + 1))
            else:
                if order.button("↑", key=f"simple_up_{line.line_id}", help="上へ", disabled=index == 0):
                    move_line(draft, line.line_id, -1)
                    st.rerun()
                if order.button("↓", key=f"simple_down_{line.line_id}", help="下へ", disabled=index == len(lines) - 1):
                    move_line(draft, line.line_id, 1)
                    st.rerun()
            name.write(line.customer_display_name or line.manufacturer_description or "-")
            book = line.manufacturer_price_snapshot.price_book if line.manufacturer_price_snapshot else None
            book = price_book_label(page, book) if book else None
            sku.write(line.manufacturer_sku or "-")
            if book:
                sku.caption(book)
            price = purchase_price(line)
            purchase.write(f"{price['label']} {_usd(price['unit_usd'])}")
            unit.write(display_yen(line.final_sales_price_jpy, "未設定"))
            value = quantity.number_input(
                "数量",
                min_value=1,
                step=1,
                value=int(line.quantity),
                key=f"simple_qty_{line.line_id}_{line.quantity}",
                label_visibility="collapsed",
                disabled=locked,
            )
            amount = None if line.final_sales_price_jpy is None else line.final_sales_price_jpy * line.quantity
            subtotal.write(display_yen(amount, "-"))
            if not locked and remove.button("削除", key=f"simple_remove_{line.line_id}"):
                remove_line(draft, line.line_id)
                st.rerun()
            if not locked and int(value) != line.quantity:
                set_quantity(draft, line.line_id, int(value))
                st.rerun()
            if line.final_price_status == FinalPriceStatus.NOT_SET:
                st.caption(f"⚠ {line.manufacturer_sku}: 標準売価がありません。「売価を調整」で売価を設定してください。")
            elif line.final_price_status == FinalPriceStatus.MANUAL_OVERRIDE:
                st.caption(
                    f"{line.manufacturer_sku}: 売価調整済み（標準売価 {display_yen(line.standard_sales_price_candidate_jpy, '-')}）"
                )
            if not locked:
                with st.expander(f"売価を調整：{line.manufacturer_sku}" + (f"（{book}）" if book else ""), expanded=False):
                    from ui.quote_workspace import _render_final_price_editor

                    st.caption(_purchase_caption(draft, line))
                    _render_final_price_editor(page, draft, line)


def _usd(value) -> str:
    return "-" if value is None else f"${value:,.2f}"


def _purchase_caption(draft, line) -> str:
    """Purchase price of one unit from the line snapshot, and its JPY at the quote rate (existing result)."""
    price = purchase_price(line)
    text = f"{price['label']}価格：{_usd(price['unit_usd'])}"
    if price["jpy"] is not None and line.quantity:
        text += (
            f" ／ {price['label']} {_usd(price['unit_usd'])} × ¥{display_number(draft.exchange_rate, '-')}"
            f" = {display_yen(price['jpy'] / line.quantity, '-')}（1台あたり）"
        )
    return text


# ---- D. GlobalShipping ----------------------------------------------------------------------------


def _render_shipping(draft, locked: bool) -> None:
    books = price_books_in(draft)
    has_dt_pt = bool(books & set(GLOBAL_SHIPPING_PRICE_BOOKS))
    has_spectra = SPECTRA_PRICE_BOOK in books
    with st.container(border=True):
        st.subheader("国際輸送費")
        if has_dt_pt or draft.global_shipping is not None:
            if has_spectra:
                st.markdown("##### Deep Trekker / PipeTrekker 国際輸送費")
            _render_global_shipping(draft, locked)
        if has_spectra or draft.spectra_shipping is not None:
            st.markdown("##### SPECTRA GOLD 国際輸送費")
            _render_spectra_shipping(draft, locked)
        if has_dt_pt and has_spectra:
            parts = shipping_breakdown(draft)
            st.markdown("##### 顧客向け国際輸送費 合計")
            st.metric(
                "顧客向け国際輸送費 合計",
                display_yen(customer_summary(draft)["shipping"], "未確定"),
                label_visibility="collapsed",
            )
            st.caption(
                f"DT / PT {display_yen(parts['dt_pt_customer'], '未選択')} ＋ "
                f"SPECTRA GOLD {display_yen(parts['spectra_customer'], '未入力')}"
            )


def _render_global_shipping(draft, locked: bool) -> None:
    from repositories.shipping_rule_repository import CHARGE_BASIS_LABELS, ShippingRuleRepository

    selection = draft.global_shipping
    try:
        rates = ShippingRuleRepository().list_active_standard_global()
    except Exception:
        logger.exception("simple_quote_shipping_load_failed")
        rates = []
        st.warning("GlobalShippingを読み込めませんでした。価格マスター管理の国際輸送費を確認してください。")
    by_id = {item.rule.shipping_rule_id: item for item in rates}
    options = ["__none__"] + list(by_id)
    labels = {"__none__": "選択してください"}
    for item in rates:
        basis = CHARGE_BASIS_LABELS.get(item.rule.charge_basis, "-")
        labels[item.rule.shipping_rule_id] = f"{_rule_label(item.rule)} / ${item.rule.rate_usd:,.2f}（{basis}）"
    if selection is not None and selection.shipping_rule_id not in by_id:
        # The frozen choice stays selectable even after the reference master changed.
        options.append(selection.shipping_rule_id)
        labels[selection.shipping_rule_id] = f"{selection.label} / ${selection.master_rate_usd:,.2f}（保存時の値）"
    current = selection.shipping_rule_id if selection is not None else "__none__"
    chosen = st.selectbox(
        "GlobalShippingを選択",
        options,
        index=options.index(current),
        format_func=lambda key: labels.get(key, key),
        key=f"simple_shipping_{draft.quote_draft_id}_{draft.quote_version}",
        disabled=locked,
    )
    if not locked and chosen != current:
        try:
            if chosen == "__none__":
                clear_global_shipping(draft)
            else:
                select_global_shipping(draft, by_id[chosen], selected_by=acting_person())
        except SimpleQuoteError as error:
            st.error(ERRORS.get(error.code, error.code))
        else:
            st.rerun()
    if selection is None:
        st.caption("国際輸送費を選択すると、原価と顧客向け輸送費が自動計算されます。")
        return
    markup = selection.markup_multiplier
    st.write(
        f"DT実輸送費：${selection.actual_rate_usd:,.2f} → 原価 {display_yen(selection.cost_jpy, '-')} ／ "
        f"顧客向け（×{display_number(markup, '-')}）：{display_yen(selection.customer_price_jpy, '-')}"
    )
    if selection.rate_adjusted:
        st.caption(
            f"手動調整：マスター値 ${selection.master_rate_usd:,.2f} → ${selection.actual_rate_usd:,.2f}"
            f"（理由：{selection.rate_adjustment_reason}）"
        )
    if selection.customer_price_overridden:
        st.caption(
            f"顧客向け輸送費を手動設定：自動計算 {display_yen(selection.auto_customer_price_jpy, '-')} → "
            f"{display_yen(selection.customer_price_jpy, '-')}（理由：{selection.customer_price_reason}）"
        )
    if locked:
        return
    _render_shipping_adjustments(draft, selection)


def _render_spectra_shipping(draft, locked: bool) -> None:
    entry = draft.spectra_shipping
    if entry is not None:
        st.write(
            f"SPECTRA実輸送費：${entry.actual_rate_usd:,.2f} → 原価 {display_yen(entry.cost_jpy, '-')} ／ "
            f"顧客向け（×{display_number(entry.markup_multiplier, '-')}）：{display_yen(entry.customer_price_jpy, '-')}"
        )
        st.caption(f"根拠・理由：{entry.reason}")
    else:
        st.caption("GlobalShipping は SPECTRA に使いません。メーカー見積などの送料（USD）と根拠を入力してください。")
    if locked:
        return
    suffix = f"{draft.quote_draft_id}_{draft.quote_version}"
    left, right = st.columns([1, 2])
    amount = left.number_input(
        "USD",
        min_value=0.0,
        value=float(entry.actual_rate_usd) if entry else 0.0,
        step=0.01,
        format="%.2f",
        key=f"simple_spectra_ship_usd_{suffix}",
    )
    reason = right.text_input(
        "理由・根拠（必須）",
        value=entry.reason if entry else "",
        placeholder="例：SPECTRA メーカー見積 2026-11",
        key=f"simple_spectra_ship_reason_{suffix}",
    )
    apply_column, clear_column = st.columns(2)
    if apply_column.button("SPECTRA送料を反映", key=f"simple_spectra_ship_apply_{suffix}"):
        try:
            set_spectra_shipping(draft, actual_rate_usd=float(amount), reason=reason, entered_by=acting_person())
        except SimpleQuoteError as error:
            st.error(ERRORS.get(error.code, error.code))
            return
        st.rerun()
    if entry is not None and clear_column.button("SPECTRA送料をクリア", key=f"simple_spectra_ship_clear_{suffix}"):
        clear_spectra_shipping(draft)
        st.rerun()


def _render_shipping_adjustments(draft, selection) -> None:
    suffix = f"{draft.quote_draft_id}_{draft.quote_version}"
    override = (selection.customer_price_jpy, selection.customer_price_reason) if selection.customer_price_overridden else (None, None)
    if st.toggle("国際輸送費を手動調整", key=f"simple_ship_adjust_{suffix}", value=selection.rate_adjusted):
        left, right = st.columns([1, 2])
        actual = left.number_input(
            "DT実輸送費（USD）",
            min_value=0.0,
            value=float(selection.actual_rate_usd),
            step=0.01,
            format="%.2f",
            key=f"simple_ship_usd_{suffix}",
        )
        reason = right.text_input("調整理由（必須）", value=selection.rate_adjustment_reason or "", key=f"simple_ship_reason_{suffix}")
        apply_column, reset_column = st.columns(2)
        if apply_column.button("国際輸送費を反映", key=f"simple_ship_apply_{suffix}"):
            _adjust(draft, actual_rate_usd=float(actual), rate_reason=reason, customer=override)
        if selection.rate_adjusted and reset_column.button("マスター値に戻す", key=f"simple_ship_reset_{suffix}"):
            _adjust(draft, actual_rate_usd=None, rate_reason=None, customer=override)
    keep_rate = (selection.actual_rate_usd if selection.rate_adjusted else None, selection.rate_adjustment_reason)
    if st.toggle("顧客向け輸送費も手動調整", key=f"simple_ship_customer_{suffix}", value=selection.customer_price_overridden):
        st.caption(f"通常は DT実輸送費 × {display_number(selection.markup_multiplier, '-')} の自動計算値（{display_yen(selection.auto_customer_price_jpy, '-')}）を使います。")
        left, right = st.columns([1, 2])
        amount = left.number_input(
            "顧客向け輸送費（円・千円単位）",
            min_value=0,
            step=1000,
            value=int(selection.customer_price_jpy or 0),
            key=f"simple_ship_customer_jpy_{suffix}",
        )
        reason = right.text_input("理由（必須）", value=selection.customer_price_reason or "", key=f"simple_ship_customer_reason_{suffix}")
        apply_column, reset_column = st.columns(2)
        if apply_column.button("顧客向け輸送費を反映", key=f"simple_ship_customer_apply_{suffix}"):
            _adjust(draft, actual_rate_usd=keep_rate[0], rate_reason=keep_rate[1], customer=(float(amount), reason))
        if selection.customer_price_overridden and reset_column.button("自動計算に戻す", key=f"simple_ship_customer_reset_{suffix}"):
            _adjust(draft, actual_rate_usd=keep_rate[0], rate_reason=keep_rate[1], customer=(None, None))


def _adjust(draft, *, actual_rate_usd, rate_reason, customer) -> None:
    try:
        adjust_global_shipping(
            draft,
            actual_rate_usd=actual_rate_usd,
            rate_reason=rate_reason,
            customer_price_jpy=customer[0],
            customer_reason=customer[1],
        )
    except SimpleQuoteError as error:
        st.error(ERRORS.get(error.code, error.code))
        return
    st.rerun()


# ---- E/F. summaries -------------------------------------------------------------------------------


def _render_customer_summary(draft, locked: bool) -> None:
    summary = customer_summary(draft)
    with st.container(border=True):
        st.subheader("見積金額（顧客向け）")
        st.metric("見積額（税抜）", display_yen(summary["subtotal_ex_tax"], "未確定"))
        first, second, third = st.columns(3)
        first.metric("商品小計", display_yen(summary["product_subtotal"], "-"))
        second.metric("国際輸送費", display_yen(summary["shipping"], "未選択"))
        third.metric("合計（税込）", display_yen(summary["total"], "未確定"))
        rate_column, tax_column = st.columns([1, 2])
        percent = rate_column.number_input(
            "消費税率（%）",
            min_value=0.0,
            max_value=100.0,
            step=1.0,
            value=float((draft.tax_rate if draft.tax_rate is not None else DEFAULT_TAX_RATE) * 100),
            key=f"simple_tax_{draft.quote_draft_id}_{draft.quote_version}",
            disabled=locked,
        )
        tax_column.metric("消費税", display_yen(summary["tax"], "-"))
        rate = round(float(percent) / 100, 6)
        if not locked and rate != draft.tax_rate:
            apply_tax_rate(draft, rate)
            st.rerun()
        if summary["subtotal_ex_tax"] is None:
            st.caption("売価未設定の商品または国際輸送費の未選択があるため、見積額は未確定です。")


def _render_revenue_summary(page: dict, draft) -> None:
    from ui.components.warning_panel import render_warning_panel

    revenue = revenue_summary(draft)
    with st.container(border=True):
        st.subheader("社内用収益サマリー")
        sales, cost, gross = st.columns(3)
        sales.metric("税抜見積額", display_yen(revenue["sales_ex_tax"], "未確定"))
        cost.metric("原価合計", display_yen(revenue["total_cost"], "未確定"))
        cost.markdown(f"**原価率 {display_percent(revenue['cost_rate'], '-')}**")
        gross.metric("粗利", display_yen(revenue["gross_profit"], "未確定"))
        gross.markdown(f"**粗利率 {display_percent(revenue['gross_margin_rate'], '-')}**")
        with st.expander("原価内訳", expanded=False):
            rows = [{"項目": "商品仕入原価", "金額": display_yen(revenue["purchase"], "-"), "根拠": ""}]
            for group in purchase_breakdown(draft):
                origin = "DT / PT Dealer価格" if group["label"] == "Dealer" else "SPECTRA GOLD Gold価格"
                basis = (
                    f"{group['label']}合計 {_usd(group['total_usd'])} × 使用為替 ¥{display_number(draft.exchange_rate, '-')}"
                    if group["total_usd"] is not None
                    else "-"
                )
                rows.append({"項目": f"　うち {origin}", "金額": display_yen(group["jpy"], "-"), "根拠": basis})
            rows += [
                {"項目": "輸送保険料", "金額": display_yen(revenue["insurance"], "-"), "根拠": "見積試算ポリシー"},
                {"項目": "輸入税", "金額": display_yen(revenue["import_tax"], "-"), "根拠": "見積試算ポリシー"},
                {"項目": "国際輸送費", "金額": display_yen(revenue["shipping"], "未選択"), "根拠": ""},
            ]
            if draft.spectra_shipping is not None or SPECTRA_PRICE_BOOK in price_books_in(draft):
                rows += [
                    {"項目": "　うち DT / PT 国際輸送費", "金額": display_yen(revenue["shipping_dt_pt"], "未選択"), "根拠": "GlobalShipping"},
                    {"項目": "　うち SPECTRA GOLD 国際輸送費", "金額": display_yen(revenue["shipping_spectra"], "未入力"), "根拠": "手入力"},
                ]
            rows.append({"項目": "原価合計", "金額": display_yen(revenue["total_cost"], "-"), "根拠": ""})
            st.table(rows)
            st.caption("原価率 = 原価合計 ÷ 税抜見積額、粗利率 = 粗利 ÷ 税抜見積額。国内送料は含みません。")
        render_warning_panel(page, draft)


# ---- G. save / approve / export -------------------------------------------------------------------


def _render_save_and_approval(page: dict, helpers: dict, draft, snapshot) -> None:
    from ui.quote_workspace import _render_step_export, _render_step_review, _save_draft

    with st.container(border=True):
        st.subheader("保存・承認")
        if draft.status not in {QuoteDraftStatus.APPROVED, QuoteDraftStatus.SUPERSEDED}:
            if st.button("下書き保存", key="simple_save_draft"):
                _save_draft(page, draft, manual=True)
                st.session_state[SESSION_FLASH] = "下書きを保存しました。"
                st.rerun()
        with st.expander("確認・承認", expanded=draft.status == QuoteDraftStatus.READY_FOR_APPROVAL or snapshot is not None):
            _render_step_review(page, helpers, draft, snapshot)
    if snapshot is not None:
        with st.container(border=True):
            _render_step_export(page, helpers, draft, snapshot)


def _render_other_quotes() -> None:
    with st.expander("SPECTRA見積・従来の詳細画面", expanded=False):
        st.caption("SPECTRA GOLD の見積や、従来の5ステップ画面で作成した見積はこちらから操作します。")
        if st.button("従来の詳細画面を開く", key="simple_open_legacy"):
            st.session_state[QUOTE_UI_MODE_KEY] = QUOTE_UI_LEGACY
            for key in ("quote_draft", "approved_quote_snapshot", "quote_approval_validation"):
                st.session_state[key] = None
            st.rerun()


# ---- helpers --------------------------------------------------------------------------------------


def _render_flash() -> None:
    message = st.session_state.pop(SESSION_FLASH, None)
    if message:
        st.success(message)


def _status_label(draft) -> str:
    return {
        "DRAFT": "下書き",
        "REVIEW_REQUIRED": "要確認",
        "READY_FOR_APPROVAL": "承認可能",
        "APPROVED": "承認済み",
        "SUPERSEDED": "改訂済み",
    }.get(draft.status.value, draft.status.value)


def _rule_label(rule) -> str:
    from repositories.shipping_rule_repository import SHIPPING_TYPE_LABELS

    return SHIPPING_TYPE_LABELS.get(rule.shipping_type, rule.shipping_type.value if rule.shipping_type else "-")
