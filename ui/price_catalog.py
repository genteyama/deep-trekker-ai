"""Read-only manufacturer price catalog for DT40 / PT30 / SPECTRA GOLD."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable, Optional


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


PRIMARY_TAB_LABEL = "主要機体・パッケージ"
ALL_PRODUCTS_TAB_LABEL = "全商品・オプション"
PRIMARY_MISSING_WARNING = "主要機体・パッケージの一部が現在のActive Masterに見つかりません。価格マスターを確認してください。"
PRIMARY_MISSING_REASON_ABSENT = "Active Masterに無し"
PRIMARY_MISSING_REASON_AMBIGUOUS = "複数行一致（一意に特定不可）"

# Explicit sales allowlist: (製品 Group, Price Book, SKU) in fixed business order.
# Matching is exact on Price Book + SKU only; nothing is inferred from prefixes or descriptions.
PRIMARY_PACKAGE_GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("DTG3", "DT40", ("7340-BASE-4K",)),
    ("PHOTON", "DT40", ("9680-BASE", "9680-EXPERT", "9680-SAR")),
    ("PIVOT", "DT40", ("8530-SMART", "8530-EXPERT", "8530-NAV", "8530-RECON", "8530-SAR")),
    ("REVOLUTION", "DT40", ("7511-DC-BASE", "7511-DC-NAV", "7511-DC-RECON", "7511-DC-SAR")),
    ("Utility Crawler", "DT40", ("9701-MAG-4K", "9701-VAC-4K", "9701-MAX-4K")),
    ("A-150", "PT30", ("11000S", "11000X")),
    ("A-200", "PT30", ("10800S", "10800X", "10800PRO")),
)
PRIMARY_PACKAGE_SKUS: tuple[tuple[str, str, str], ...] = tuple(
    (group, price_book, sku) for group, price_book, skus in PRIMARY_PACKAGE_GROUPS for sku in skus
)
PRIMARY_GROUP_ORDER: tuple[str, ...] = tuple(group for group, _book, _skus in PRIMARY_PACKAGE_GROUPS)
PRIMARY_COLUMN_ORDER = [
    "製品",
    "SKU",
    "製品名",
    "Price Book",
    "MSRP USD",
    "Dealer USD",
    "SpaceOne参考売価 JPY",
    "メーカー価格状態",
    "参考売価状態",
]


def _primary_matches(rows: Iterable[dict]) -> dict[tuple[str, str], list[dict]]:
    wanted = {(price_book, sku) for _group, price_book, sku in PRIMARY_PACKAGE_SKUS}
    matches: dict[tuple[str, str], list[dict]] = {key: [] for key in wanted}
    for row in rows:
        key = (row.get("Price Book"), row.get("SKU"))
        if key in matches:
            matches[key].append(row)
    return matches


def build_primary_package_rows(rows: Iterable[dict]) -> list[dict]:
    """Return allowlisted rows in fixed order. Only exactly one matching row is adopted."""
    matches = _primary_matches(rows)
    result = []
    for group, price_book, sku in PRIMARY_PACKAGE_SKUS:
        found = matches[(price_book, sku)]
        if len(found) != 1:
            continue
        row = dict(found[0])
        row["製品"] = group
        row["_primary_search"] = " ".join((group, sku, str(row.get("製品名") or ""))).casefold()
        result.append(row)
    return result


def missing_primary_package_skus(rows: Iterable[dict]) -> list[dict]:
    """Allowlisted SKUs that are absent or not uniquely identifiable in the Active Master."""
    matches = _primary_matches(rows)
    missing = []
    for group, price_book, sku in PRIMARY_PACKAGE_SKUS:
        count = len(matches[(price_book, sku)])
        if count == 1:
            continue
        reason = PRIMARY_MISSING_REASON_ABSENT if count == 0 else PRIMARY_MISSING_REASON_AMBIGUOUS
        missing.append({"製品": group, "Price Book": price_book, "SKU": sku, "理由": reason})
    return missing


def filter_primary_package_rows(
    rows: Iterable[dict],
    *,
    keyword: str = "",
    groups: Iterable[str] | None = None,
) -> list[dict]:
    keyword = (keyword or "").strip().casefold()
    group_set = set(groups or [])
    filtered = []
    for row in rows:
        if keyword and keyword not in row.get("_primary_search", ""):
            continue
        if group_set and row.get("製品") not in group_set:
            continue
        filtered.append(row)
    return filtered


def display_primary_package_rows(rows: Iterable[dict]) -> list[dict]:
    return [{key: row.get(key) for key in PRIMARY_COLUMN_ORDER} for row in rows]


USD_PRICE_COLUMNS = ("MSRP USD", "Dealer USD")
JPY_PRICE_COLUMNS = ("SpaceOne参考売価 JPY",)

SHIPPING_TAB_LABEL = "国際輸送費（参考）"
SHIPPING_INFO = (
    "国際輸送費はActive SO_MASTERに登録されている参考値です。"
    "実際の案件では、Deep Trekkerのメーカー見積に記載されたShipping / Insuranceを優先して確認してください。"
)
SHIPPING_MISSING_WARNING = "一部の主要機体はActive SO_MASTERに国際輸送費の参考値がありません（要確認）。"
SHIPPING_STATUS_AVAILABLE = "参考値"
SHIPPING_STATUS_REVIEW = "要確認"
SHIPPING_REASON_NO_SHEET = "SO_MASTERに対応Sheetなし"
SHIPPING_REASON_ABSENT = "SO_MASTERにSKUなし"
SHIPPING_REASON_DUPLICATE = "同一Sheet内で複数行一致"
SHIPPING_REASON_INCOMPLETE = "保険または送料が未設定"
SHIPPING_USD_COLUMNS = ("保険 USD", "国際送料 USD", "送料・保険合計 USD")
SHIPPING_JPY_COLUMNS = ("参考換算 JPY",)
SHIPPING_COLUMN_ORDER = ["製品", "SKU", "製品名", *SHIPPING_USD_COLUMNS, *SHIPPING_JPY_COLUMNS, "状態"]

# Primary product group -> Active SO_MASTER sheet. DTG3 has no SO_MASTER sheet; nothing is inferred.
SHIPPING_SHEET_BY_GROUP: dict[str, Optional[str]] = {
    "DTG3": None,
    "PHOTON": "PHOTON",
    "PIVOT": "PIVOT",
    "REVOLUTION": "REVOLUTION",
    "Utility Crawler": "MAG",
    "A-150": "A-150",
    "A-200": "A-200",
}
# Fixed SO_MASTER columns (0-based): B = SKU, C = 製品名, L = 保険（3%）USD, M = 送料（単体の目安）USD.
_SO_SKU_COL, _SO_NAME_COL, _SO_INSURANCE_COL, _SO_SHIPPING_COL = 1, 2, 11, 12


def currency_column_config(usd_columns: Iterable[str] = (), jpy_columns: Iterable[str] = ()) -> dict:
    """Display-only currency formats. Values stay numeric; None stays empty."""
    import streamlit as st

    config = {name: st.column_config.NumberColumn(name, format="dollar") for name in usd_columns}
    config.update({name: st.column_config.NumberColumn(name, format="yen") for name in jpy_columns})
    return config


def _usd_amount(value) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _clean_text(value) -> Optional[str]:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def _read_shipping_sheets(path: Path, sheet_names: Iterable[str]) -> dict[str, dict[str, list[tuple]]]:
    """Read-only scan: {sheet: {normalized SKU: [row values, ...]}} for rows with a SKU in column B."""
    import openpyxl

    from parsers.spaceone_master_parser import classify_spaceone_sku

    wanted = set(sheet_names)
    result: dict[str, dict[str, list[tuple]]] = {}
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        for sheet_name in workbook.sheetnames:
            if sheet_name not in wanted:
                continue
            by_sku: dict[str, list[tuple]] = {}
            for row in workbook[sheet_name].iter_rows(max_col=_SO_SHIPPING_COL + 1, values_only=True):
                if len(row) <= _SO_SKU_COL:
                    continue
                sku, _error, _kind, _raw = classify_spaceone_sku(row[_SO_SKU_COL])
                if sku:
                    by_sku.setdefault(sku, []).append(tuple(row) + (None,) * (_SO_SHIPPING_COL + 1 - len(row)))
            result[sheet_name] = by_sku
    finally:
        workbook.close()
    return result


def extract_shipping_reference_rows(path: Path, exchange_rate: float) -> list[dict]:
    """Shipping / insurance reference values for the primary SKUs from an SO_MASTER snapshot file.

    Exact SKU match within the mapped sheet only. Absent, duplicated or incomplete rows are 要確認.
    """
    sheets = _read_shipping_sheets(path, {name for name in SHIPPING_SHEET_BY_GROUP.values() if name})
    rows = []
    for group, _price_book, sku in PRIMARY_PACKAGE_SKUS:
        sheet = SHIPPING_SHEET_BY_GROUP.get(group)
        name = insurance = shipping = None
        if sheet is None:
            reason = SHIPPING_REASON_NO_SHEET
        else:
            found = sheets.get(sheet, {}).get(sku, [])
            if not found:
                reason = SHIPPING_REASON_ABSENT
            elif len(found) > 1:
                reason = SHIPPING_REASON_DUPLICATE
            else:
                values = found[0]
                name = _clean_text(values[_SO_NAME_COL])
                insurance = _usd_amount(values[_SO_INSURANCE_COL])
                shipping = _usd_amount(values[_SO_SHIPPING_COL])
                reason = None if insurance is not None and shipping is not None else SHIPPING_REASON_INCOMPLETE
        total = insurance + shipping if insurance is not None and shipping is not None else None
        rows.append(
            {
                "製品": group,
                "SKU": sku,
                "製品名": name,
                "保険 USD": insurance,
                "国際送料 USD": shipping,
                "送料・保険合計 USD": total,
                "参考換算 JPY": total * float(exchange_rate) if total is not None else None,
                "状態": SHIPPING_STATUS_AVAILABLE if reason is None else SHIPPING_STATUS_REVIEW,
                "_reason": reason,
                "_search": " ".join((group, sku, name or "")).casefold(),
            }
        )
    return rows


def shipping_reference_issues(rows: Iterable[dict]) -> list[dict]:
    return [
        {"製品": row["製品"], "SKU": row["SKU"], "理由": row["_reason"]}
        for row in rows
        if row.get("_reason")
    ]


def filter_shipping_reference_rows(rows: Iterable[dict], *, keyword: str = "") -> list[dict]:
    keyword = (keyword or "").strip().casefold()
    return [row for row in rows if not keyword or keyword in row.get("_search", "")]


def display_shipping_reference_rows(rows: Iterable[dict]) -> list[dict]:
    return [{key: row.get(key) for key in SHIPPING_COLUMN_ORDER} for row in rows]


def load_shipping_reference_rows(exchange_rate: float, *, get_active: Optional[Callable] = None) -> Optional[list[dict]]:
    """Rows from the current Active SO_MASTER snapshot, or None when no Active SO_MASTER exists."""
    from models import PriceMasterType

    if get_active is None:
        from agents.price_master import get_active_master as get_active
    active = get_active(PriceMasterType.SO_MASTER)
    if active is None:
        return None
    return extract_shipping_reference_rows(Path(active.path), exchange_rate)


def _reference_sales_candidates(books, exchange_rate: float):
    from agents.sku_link import build_sku_link_preview
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

    primary_tab, all_tab, shipping_tab = st.tabs([PRIMARY_TAB_LABEL, ALL_PRODUCTS_TAB_LABEL, SHIPPING_TAB_LABEL])
    price_columns = currency_column_config(USD_PRICE_COLUMNS, JPY_PRICE_COLUMNS)

    with primary_tab:
        missing = missing_primary_package_skus(rows)
        if missing:
            st.warning(PRIMARY_MISSING_WARNING)
            st.dataframe(missing, use_container_width=True, hide_index=True)
        primary_rows = build_primary_package_rows(rows)
        primary_columns = st.columns([2, 1])
        with primary_columns[0]:
            primary_keyword = st.text_input("製品・SKUを検索", placeholder="例：PHOTON / 9680 / NAV / A-200")
        with primary_columns[1]:
            selected_groups = st.multiselect("製品", list(PRIMARY_GROUP_ORDER))
        primary_filtered = filter_primary_package_rows(primary_rows, keyword=primary_keyword, groups=selected_groups)
        st.caption(f"{len(primary_filtered)} / {len(PRIMARY_PACKAGE_SKUS)} 件")
        st.dataframe(
            display_primary_package_rows(primary_filtered),
            use_container_width=True,
            hide_index=True,
            column_order=PRIMARY_COLUMN_ORDER,
            column_config=price_columns,
        )

    with all_tab:
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
            column_config=price_columns,
        )

    with shipping_tab:
        st.info(SHIPPING_INFO)
        try:
            shipping_rows = load_shipping_reference_rows(float(exchange_rate))
        except Exception:  # A broken reference file must not take down the price catalog.
            shipping_rows = None
            st.warning("Active SO_MASTERから国際輸送費の参考値を読み込めませんでした。価格マスター管理を確認してください。")
        else:
            if shipping_rows is None:
                st.warning("Active SO_MASTERがありません。国際輸送費の参考値は表示できません。")
        if shipping_rows is not None:
            issues = shipping_reference_issues(shipping_rows)
            if issues:
                st.warning(SHIPPING_MISSING_WARNING)
                st.dataframe(issues, use_container_width=True, hide_index=True)
            shipping_keyword = st.text_input("製品・SKUを検索（国際輸送費）", placeholder="例：PHOTON / 9680 / NAV / A-200")
            shipping_filtered = filter_shipping_reference_rows(shipping_rows, keyword=shipping_keyword)
            st.caption(f"{len(shipping_filtered)} / {len(shipping_rows)} 件")
            st.dataframe(
                display_shipping_reference_rows(shipping_filtered),
                use_container_width=True,
                hide_index=True,
                column_order=SHIPPING_COLUMN_ORDER,
                column_config=currency_column_config(SHIPPING_USD_COLUMNS, SHIPPING_JPY_COLUMNS),
            )
