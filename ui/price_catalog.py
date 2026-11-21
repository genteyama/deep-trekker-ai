"""Read-only manufacturer price catalog for DT40 / PT30 / SPECTRA GOLD."""

from __future__ import annotations

from typing import Iterable


STATUS_OFFICIAL = "正式価格"
STATUS_REVIEW = "要確認"
STATUS_OBSOLETE = "廃番"
REFERENCE_AVAILABLE = "算出可"
REFERENCE_REVIEW = "要確認"


def _value(value):
    return getattr(value, "value", value)


def _source_sheets(candidate) -> str:
    sheets = []
    for occurrence in getattr(candidate, "occurrences", []) or []:
        sheet = getattr(occurrence, "source_sheet", None)
        if sheet and sheet not in sheets:
            sheets.append(str(sheet))
    return " / ".join(sheets) if sheets else "-"


def _price_status(candidate) -> str:
    source_status = _value(getattr(candidate, "source_status", None))
    duplicate_class = _value(getattr(candidate, "duplicate_class", None))
    if source_status == "OBSOLETE":
        return STATUS_OBSOLETE
    if duplicate_class == "PRICE_CONFLICT":
        return STATUS_REVIEW
    if getattr(candidate, "msrp_usd", None) is None or getattr(candidate, "dealer_price_usd", None) is None:
        return STATUS_REVIEW
    return STATUS_OFFICIAL


def build_reference_sales_map(candidates: Iterable, *, round_customer_price, is_customer_price_unit) -> dict[str, float | None]:
    """Return only unambiguous v1 standard prices. Ambiguous/review SKUs stay None."""
    grouped: dict[str, list[float | None]] = {}
    for candidate in candidates or []:
        sku = str(getattr(candidate, "manufacturer_sku", None) or "").strip()
        if not sku:
            continue
        status = _value(getattr(candidate, "status", None))
        policy = _value(getattr(candidate, "pricing_policy_type", None))
        price = None
        if status != "REVIEW_REQUIRED":
            raw = getattr(candidate, "raw_sales_price_jpy", None)
            if policy == "MSRP_MULTIPLIER" and raw is not None:
                price = round_customer_price(raw)
            elif policy == "FIXED_JPY" and raw is not None and is_customer_price_unit(raw):
                price = float(raw)
        grouped.setdefault(sku, []).append(price)

    result: dict[str, float | None] = {}
    for sku, prices in grouped.items():
        usable = {float(price) for price in prices if price is not None}
        # More than one valid result for the same manufacturer SKU is not auto-resolved.
        result[sku] = next(iter(usable)) if len(usable) == 1 and all(price is not None for price in prices) else None
    return result


def build_price_catalog_rows(active_books: Iterable, *, reference_sales: dict[str, float | None] | None = None) -> list[dict]:
    reference_sales = reference_sales or {}
    rows = []
    for active in active_books:
        record = active.record
        book = active.book
        price_book = _value(getattr(record, "master_type", None)) or getattr(book, "source_price_book", None) or "-"
        imported_at = getattr(record, "imported_at", None) or "-"
        import_id = getattr(record, "import_id", None) or "-"
        for candidate in getattr(book, "candidates", []) or []:
            sku = str(getattr(candidate, "sku", None) or "").strip()
            description = str(getattr(candidate, "description", None) or "").strip()
            source_sheet = _source_sheets(candidate)
            status = _price_status(candidate)
            reference_price = reference_sales.get(sku)
            reference_status = REFERENCE_AVAILABLE if reference_price is not None else REFERENCE_REVIEW
            rows.append(
                {
                    "Price Book": str(price_book),
                    "Source Sheet": source_sheet,
                    "SKU": sku,
                    "製品名": description,
                    "MSRP USD": getattr(candidate, "msrp_usd", None),
                    "Dealer USD": getattr(candidate, "dealer_price_usd", None),
                    "メーカー価格状態": status,
                    "SpaceOne参考売価 JPY": reference_price,
                    "参考売価状態": reference_status,
                    "Master更新": imported_at,
                    "Import ID": import_id,
                    "_search": " ".join((str(price_book), source_sheet, sku, description, status, reference_status)).casefold(),
                }
            )
    return sorted(rows, key=lambda row: (row["Price Book"], row["Source Sheet"], row["SKU"]))


def filter_price_catalog_rows(
    rows: Iterable[dict],
    *,
    keyword: str = "",
    price_books: Iterable[str] | None = None,
    source_sheets: Iterable[str] | None = None,
    statuses: Iterable[str] | None = None,
) -> list[dict]:
    keyword = (keyword or "").strip().casefold()
    book_set = set(price_books or [])
    sheet_set = set(source_sheets or [])
    status_set = set(statuses or [])
    filtered = []
    for row in rows:
        if keyword and keyword not in row.get("_search", ""):
            continue
        if book_set and row.get("Price Book") not in book_set:
            continue
        if sheet_set:
            row_sheets = {part.strip() for part in str(row.get("Source Sheet") or "").split("/")}
            if not row_sheets.intersection(sheet_set):
                continue
        if status_set and row.get("メーカー価格状態") not in status_set:
            continue
        filtered.append(row)
    return filtered


def display_price_catalog_rows(rows: Iterable[dict]) -> list[dict]:
    return [{key: value for key, value in row.items() if not key.startswith("_") and key != "Import ID"} for row in rows]


def _reference_sales_candidates(books, exchange_rate: float):
    from agents.master_reconciliation import build_sku_link_preview
    from agents.price_master import load_active_spaceone_master
    from agents.pricing_policy import build_exchange_rate_scenario, extract_pricing_policies, simulate_sales_price_candidates

    active_spaceone = load_active_spaceone_master()
    if active_spaceone is None:
        return []
    master = active_spaceone[0]
    preview = build_sku_link_preview(master.items, *[item.book for item in books])
    policies = extract_pricing_policies(master.items)
    return simulate_sales_price_candidates(preview, policies, build_exchange_rate_scenario(exchange_rate), master.items)


def render_price_catalog(texts: dict) -> None:
    import streamlit as st

    from agents.price_master import active_price_books
    from agents.pricing_policy import DEFAULT_QUOTE_EXCHANGE_RATE, is_customer_price_unit, round_customer_price_jpy

    st.title("価格一覧")
    st.caption("DT40 / PT30 / SPECTRA GOLD の現在有効な価格マスターを一覧・検索します。")
    st.info("メーカー価格の根拠は Active DT40 / PT30 / SPECTRA GOLD。SpaceOne参考売価は既存Pricing Policyからの算出値です。")

    books = active_price_books()
    if not books:
        st.warning("有効なメーカー価格マスターがありません。価格マスター管理を確認してください。")
        return

    exchange_rate = st.number_input(
        "参考売価の為替（JPY/USD）",
        min_value=1.0,
        value=float(DEFAULT_QUOTE_EXCHANGE_RATE),
        step=1.0,
        help="価格一覧上の参考売価計算だけに使用します。見積案件の採用為替は別途決定します。",
    )
    sales_candidates = _reference_sales_candidates(books, float(exchange_rate))
    reference_sales = build_reference_sales_map(
        sales_candidates,
        round_customer_price=round_customer_price_jpy,
        is_customer_price_unit=is_customer_price_unit,
    )
    rows = build_price_catalog_rows(books, reference_sales=reference_sales)

    keyword = st.text_input("SKU・製品名を検索", placeholder="例：9701 / MAG / A-200 / C550d")
    filter_columns = st.columns(3)
    book_options = sorted({row["Price Book"] for row in rows})
    sheet_options = sorted({part.strip() for row in rows for part in str(row["Source Sheet"]).split("/") if part.strip() and part.strip() != "-"})
    status_options = [status for status in (STATUS_OFFICIAL, STATUS_REVIEW, STATUS_OBSOLETE) if any(row["メーカー価格状態"] == status for row in rows)]
    with filter_columns[0]:
        selected_books = st.multiselect("価格表", book_options)
    with filter_columns[1]:
        selected_sheets = st.multiselect("製品カテゴリ / Sheet", sheet_options)
    with filter_columns[2]:
        selected_statuses = st.multiselect("メーカー価格状態", status_options)

    filtered = filter_price_catalog_rows(
        rows,
        keyword=keyword,
        price_books=selected_books,
        source_sheets=selected_sheets,
        statuses=selected_statuses,
    )
    st.caption(f"{len(filtered)} / {len(rows)} 件")
    st.dataframe(
        display_price_catalog_rows(filtered),
        use_container_width=True,
        hide_index=True,
        column_order=[
            "Price Book",
            "Source Sheet",
            "SKU",
            "製品名",
            "MSRP USD",
            "Dealer USD",
            "メーカー価格状態",
            "SpaceOne参考売価 JPY",
            "参考売価状態",
            "Master更新",
        ],
    )
