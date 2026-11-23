"""MoneyForward クラウド請求書 見積書CSV（品目縦並び / 法人 / Shift-JIS）, template v1 (2026-11).

The template is the sample MoneyForward provides for 見積書一覧 → CSV一括追加
(csv_sample_with_vertical_item_hojin_shiftjis.csv, kept byte for byte in
tests/fixtures/moneyforward/estimate_csv_v1_sample.csv). One quote is one 見積書 row followed by one 品目 row
per customer line; every row has the same 33 columns. When MoneyForward changes the format, add a new
template here and compare its header with the new sample in the tests.

Source of truth is the ApprovedQuoteSnapshot only (through the same FormalQuoteDocument as the PDF / Excel,
so names, details, prices, quantities and the line order match the customer documents). Nothing is read
from the current price masters. MoneyForward issues the quote number and recalculates 小計 / 消費税 /
合計金額 from the 品目 rows, so those columns stay empty.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
import io
import re
from typing import Optional

from models import ApprovedQuoteSnapshot


@dataclass(frozen=True)
class MoneyForwardEstimateCsvTemplate:
    version: str
    headers: tuple[str, ...]
    csv_type: str
    estimate_row: str
    item_row: str
    encoding: str
    line_terminator: str
    tax_values: tuple[str, ...]


MF_ESTIMATE_CSV_V1 = MoneyForwardEstimateCsvTemplate(
    version="MoneyForward見積CSV v1（2026-11時点）",
    headers=(
        "csv_type(変更不可)",
        "行形式",
        "取引先名称",
        "件名",
        "発行日",
        "見積書番号",
        "メモ",
        "タグ",
        "小計",
        "消費税",
        "合計金額",
        "取引先敬称",
        "取引先郵便番号",
        "取引先都道府県",
        "取引先住所1",
        "取引先住所2",
        "取引先部署",
        "取引先担当者役職",
        "取引先担当者氏名",
        "自社担当者氏名",
        "備考",
        "受注ステータス",
        "メール送信ステータス",
        "郵送ステータス",
        "ダウンロードステータス",
        "品名",
        "品目コード",
        "単価",
        "数量",
        "単位",
        "詳細",
        "金額",
        "品目消費税率",
    ),
    csv_type="30301",
    estimate_row="見積書",
    item_row="品目",
    encoding="cp932",
    line_terminator="\n",
    # 品目消費税率 values used in the sample.
    tax_values=("免税", "非課税", "不課税", "5%", "8%", "軽8%", "10%"),
)
TEMPLATE = MF_ESTIMATE_CSV_V1
SHIPPING_ITEM_NAME = "国際輸送費"
# A 0% quote does not say whether it is 免税, 非課税 or 不課税; a person chooses one.
ZERO_TAX_CATEGORIES = ("免税", "非課税", "不課税")
_TAX_BY_PERCENT = {10: "10%", 8: "8%", 5: "5%"}
_UNSAFE_FILENAME = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f\s]+')


class MoneyForwardCsvError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def moneyforward_tax_value(tax_rate: Optional[float], zero_tax_category: Optional[str] = None) -> str:
    """品目消費税率 for the quote tax rate: 10% / 8% / 5%, or the chosen category for 0%."""
    if tax_rate is None:
        raise MoneyForwardCsvError("TAX_RATE_MISSING", "消費税率が未設定のため、MoneyForward CSVを作成できません。")
    percent = round(float(tax_rate) * 100, 6)
    if percent == 0:
        if zero_tax_category in ZERO_TAX_CATEGORIES:
            return zero_tax_category
        raise MoneyForwardCsvError(
            "TAX_ZERO_CATEGORY_REQUIRED",
            "消費税率0%の見積です。MoneyForward CSVには免税・非課税・不課税のいずれかを選択してください。",
        )
    if percent.is_integer() and int(percent) in _TAX_BY_PERCENT:
        return _TAX_BY_PERCENT[int(percent)]
    raise MoneyForwardCsvError(
        "TAX_RATE_UNSUPPORTED",
        f"MoneyForward CSVで使用できない税率です（{percent:g}%）。使用できるのは10% / 8% / 5% / 0%（免税・非課税・不課税）です。",
    )


def build_estimate_rows(
    snapshot: ApprovedQuoteSnapshot,
    *,
    zero_tax_category: Optional[str] = None,
) -> list[list[str]]:
    """The 見積書 row and the 品目 rows (each 33 values, "" for empty) of one approved quote."""
    from agents.formal_quote_document import build_formal_quote_document
    from agents.quote_export import require_approved_snapshot

    snapshot = require_approved_snapshot(snapshot)
    customer = (snapshot.customer or "").strip()
    if not customer:
        raise MoneyForwardCsvError("CUSTOMER_REQUIRED", "取引先名称（顧客名）が空のため、MoneyForward CSVを作成できません。")
    tax = moneyforward_tax_value(snapshot.tax_rate, zero_tax_category)
    document = build_formal_quote_document(snapshot)
    if len(document.customer_lines) != len(snapshot.customer_lines_snapshot):
        raise MoneyForwardCsvError("LINES_MISMATCH", "見積明細を承認済みデータから作成できませんでした。")

    skus = {line.line_id: line.manufacturer_sku for line in snapshot.configuration_snapshot}
    items = []
    shipping_total = None
    for source, line in zip(snapshot.customer_lines_snapshot, document.customer_lines):
        amount = _yen(line.amount, line.item_name)
        if source.line_kind == "SHIPPING":
            # DT / PT GlobalShipping rows and SPECTRA shipping are one customer line, as on the PDF.
            shipping_total = (shipping_total or 0) + amount
            continue
        unit = _yen(line.unit_price, line.item_name)
        if unit * int(line.quantity) != amount:
            raise MoneyForwardCsvError("AMOUNT_MISMATCH", f"{line.item_name}: 単価 × 数量 が金額と一致しません。")
        sku = next((skus.get(line_id) for line_id in source.source_configuration_line_ids if skus.get(line_id)), None)
        items.append(
            _item_row(
                name=line.item_name or "",
                code=sku or "",
                unit=unit,
                quantity=int(line.quantity),
                detail=line.customer_description or "",
                amount=amount,
                tax=tax,
            )
        )
    if shipping_total is not None:
        items.append(
            _item_row(name=SHIPPING_ITEM_NAME, code="", unit=shipping_total, quantity=1, detail="", amount=shipping_total, tax=tax)
        )
    if not items:
        raise MoneyForwardCsvError("NO_ITEMS", "見積明細がないため、MoneyForward CSVを作成できません。")
    total = sum(int(row[TEMPLATE.headers.index("金額")]) for row in items)
    if document.subtotal is None or total != round(document.subtotal):
        raise MoneyForwardCsvError("SUBTOTAL_MISMATCH", "品目の金額合計が承認済みの税抜見積額と一致しません。")
    rows = [_estimate_row(snapshot, customer, document.remarks)] + items
    _check_no_internal_terms(rows)
    return rows


def _check_no_internal_terms(rows: list[list[str]]) -> None:
    """The same internal-term guard as the customer PDF / Excel (品目コード holds the SKU and is not text)."""
    from agents.quote_export import _forbidden_terms_in

    code = TEMPLATE.headers.index("品目コード")
    leaked = set()
    for row in rows:
        for index, value in enumerate(row):
            if index != code:
                leaked |= _forbidden_terms_in(value)
    if leaked:
        raise MoneyForwardCsvError("INTERNAL_TERMS", f"顧客向けCSVに社内用の語句が含まれています：{sorted(leaked)}")


def render_estimate_csv(rows: list[list[str]]) -> bytes:
    """CSV bytes in the template encoding. Raises (never replaces) when a character cannot be encoded."""
    _check_encodable(rows)
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL, lineterminator=TEMPLATE.line_terminator)
    writer.writerow(TEMPLATE.headers)
    for row in rows:
        if len(row) != len(TEMPLATE.headers):
            raise MoneyForwardCsvError("COLUMN_COUNT", "MoneyForward CSVの列数が正しくありません。")
        writer.writerow(row)
    return buffer.getvalue().encode(TEMPLATE.encoding, errors="strict")


def build_estimate_csv(snapshot: ApprovedQuoteSnapshot, *, zero_tax_category: Optional[str] = None) -> bytes:
    return render_estimate_csv(build_estimate_rows(snapshot, zero_tax_category=zero_tax_category))


def estimate_csv_filename(snapshot: ApprovedQuoteSnapshot, *, on: Optional[datetime] = None) -> str:
    """moneyforward_estimate_<顧客名>_<YYYYMMDD>.csv (the date is the export date, not the issue date)."""
    name = _UNSAFE_FILENAME.sub("_", (snapshot.customer or "").strip()).strip("._")[:40] or "customer"
    return f"moneyforward_estimate_{name}_{(on or datetime.now()).strftime('%Y%m%d')}.csv"


def _estimate_row(snapshot: ApprovedQuoteSnapshot, customer: str, remarks: list[str]) -> list[str]:
    from agents.quote_dates import parse_quote_date

    issue = parse_quote_date(snapshot.issue_date)
    values = {
        "csv_type(変更不可)": TEMPLATE.csv_type,
        "行形式": TEMPLATE.estimate_row,
        "取引先名称": customer,
        "件名": (snapshot.title or "").strip(),
        # The issue date saved on the quote only; the export date is never used as the issue date.
        "発行日": issue.strftime("%Y/%m/%d") if issue else "",
        # 見積書番号 / メモ / タグ / 小計 / 消費税 / 合計金額 stay empty: MoneyForward numbers the quote and
        # recalculates the totals from the 品目 rows. No portal ID is written.
        # 自社担当者氏名 stays empty: the portal keeps only the login e-mail, not a person's name.
        "備考": "\n".join(remarks),
    }
    return [values.get(header, "") for header in TEMPLATE.headers]


def _item_row(*, name: str, code: str, unit: int, quantity: int, detail: str, amount: int, tax: str) -> list[str]:
    values = {
        "csv_type(変更不可)": TEMPLATE.csv_type,
        "行形式": TEMPLATE.item_row,
        "品名": name,
        "品目コード": code,
        "単価": str(unit),
        "数量": str(quantity),
        "詳細": detail,
        "金額": str(amount),
        "品目消費税率": tax,
    }
    return [values.get(header, "") for header in TEMPLATE.headers]


def _yen(value, label) -> int:
    if value is None:
        raise MoneyForwardCsvError("PRICE_MISSING", f"{label}: 売価が未確定のため、MoneyForward CSVを作成できません。")
    number = float(value)
    if not number.is_integer():
        raise MoneyForwardCsvError("PRICE_NOT_YEN", f"{label}: 金額が円単位ではありません（{number}）。")
    return int(number)


def _check_encodable(rows: list[list[str]]) -> None:
    problems = []
    for row in rows:
        label = "見積書" if row[1] == TEMPLATE.estimate_row else f"品目「{row[TEMPLATE.headers.index('品名')]}」"
        for header, value in zip(TEMPLATE.headers, row):
            bad = sorted({character for character in str(value) if not _encodable(character)})
            if bad:
                problems.append(f"{label} の {header}：{'、'.join(f'「{c}」(U+{ord(c):04X})' for c in bad)}")
    if problems:
        raise MoneyForwardCsvError(
            "ENCODING",
            "Shift-JIS（CP932）で出力できない文字があります。該当箇所を修正してください。\n" + "\n".join(problems),
        )


def _encodable(character: str) -> bool:
    try:
        character.encode(TEMPLATE.encoding, errors="strict")
    except UnicodeEncodeError:
        return False
    return True


__all__ = [
    "MF_ESTIMATE_CSV_V1",
    "MoneyForwardCsvError",
    "SHIPPING_ITEM_NAME",
    "ZERO_TAX_CATEGORIES",
    "build_estimate_csv",
    "build_estimate_rows",
    "estimate_csv_filename",
    "moneyforward_tax_value",
    "render_estimate_csv",
]
