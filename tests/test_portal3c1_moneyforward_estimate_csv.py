"""PORTAL-3C.1: MoneyForward 見積書CSV（品目縦並び / 法人 / Shift-JIS）, template v1 (2026-11)."""

import csv
import io
from pathlib import Path

import pytest
from openpyxl import load_workbook
from pypdf import PdfReader

from agents import simple_quote_builder as sb
from agents.moneyforward_estimate_csv import (
    MF_ESTIMATE_CSV_V1,
    MoneyForwardCsvError,
    build_estimate_csv,
    estimate_csv_filename,
    moneyforward_tax_value,
)
from agents.price_master import import_price_master
from agents.quote_approval import all_confirmations, approve_quote, create_revision_draft
from agents.quote_builder import apply_final_price, apply_tax_rate
from agents.quote_export import export_spaceone_quote_excel, export_spaceone_quote_pdf
from models import FinalPriceStatus, PriceAdjustmentReason, PriceMasterType, QuoteDraftStatus, ShippingType
from repositories.shipping_rule_repository import ShippingRuleRepository
from repositories.sqlite_quote_repository import SqliteQuoteRepository
from tests.test_portal3b1_1_product_picker import (  # noqa: F401  (autouse fixture)
    RATE,
    _line,
    _pick,
    _sales,
    _spectra,
    masters,
)

SAMPLE = Path(__file__).parent / "fixtures" / "moneyforward" / "estimate_csv_v1_sample.csv"
H = MF_ESTIMATE_CSV_V1.headers
COL = {name: index for index, name in enumerate(H)}
A = ("DT40", "9680-BASE")
B = ("PT30", "11490")
C = ("SPECTRA_GOLD", "SPECTRA0001")


def _rows(data: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(data.decode("cp932"), newline="")))


def _rate(shipping_type):
    return ShippingRuleRepository().get_active_standard_global(shipping_type)


def _quote(customer="株式会社テスト計測", title="水中ドローン一式, 「点検」用", *, keys=(A, B, C), tax=0.10, number=None, edit=None):
    draft = sb.create_simple_quote_draft(
        customer=customer, title=title, items=_pick(*keys), exchange_rate=RATE, tax_rate=tax, sales_candidates=_sales()
    )
    for line in draft.configuration_lines:
        if line.final_sales_price_jpy is None:
            apply_final_price(
                draft,
                line.line_id,
                FinalPriceStatus.MANUAL_OVERRIDE,
                amount_jpy=250000,
                reason_code=list(PriceAdjustmentReason)[0],
                reason_note="社内メモ：Dealer価格から算出",
            )
    sb.set_quantity(draft, _line(draft, *A).line_id, 2)
    if any(key[0] != "SPECTRA_GOLD" for key in keys):
        sb.add_global_shipping(draft, _rate(ShippingType.LARGE_BOX), quantity=2)
        sb.add_global_shipping(draft, _rate(ShippingType.SMALL_BOX))
    if C in keys:
        sb.set_spectra_shipping(draft, actual_rate_usd=1800.0, reason="SPECTRA メーカー見積")
    if edit is not None:
        edit(draft)
    if tax != 0.10:
        apply_tax_rate(draft, tax)
    repo = SqliteQuoteRepository()
    repo.save_draft(draft)
    candidate = draft.model_copy(deep=True)
    _, snapshot = approve_quote(
        candidate, approved_by="sales@example.com", confirmations=all_confirmations(), official_quote_number=number
    )
    repo.record_approval(candidate, snapshot)
    return candidate, snapshot


# ---- template v1 ---------------------------------------------------------------------------------


def test_template_matches_the_moneyforward_sample_exactly():
    raw = SAMPLE.read_bytes()
    sample = _rows(raw)  # 6: the sample decodes as CP932
    assert tuple(sample[0]) == H  # 1: header, same order
    assert len(H) == 33 and {len(row) for row in sample} == {33}  # 2
    assert {row[0] for row in sample[1:]} == {MF_ESTIMATE_CSV_V1.csv_type} == {"30301"}  # 3
    assert [row[1] for row in sample[1:]] == ["見積書"] + ["品目"] * 7  # 4, 5
    assert {row[COL["品目消費税率"]] for row in sample[2:]} == set(MF_ESTIMATE_CSV_V1.tax_values)
    assert MF_ESTIMATE_CSV_V1.encoding == "cp932" and not raw.startswith(b"\xef\xbb\xbf")


def test_output_has_the_template_structure_and_decodes_as_cp932():
    _draft, snapshot = _quote()
    data = build_estimate_csv(snapshot)
    assert not data.startswith(b"\xef\xbb\xbf")
    with pytest.raises(UnicodeDecodeError):
        data.decode("utf-8")  # Shift-JIS, not UTF-8
    rows = _rows(data)
    assert tuple(rows[0]) == tuple(_rows(SAMPLE.read_bytes())[0])
    assert {len(row) for row in rows} == {33}
    assert {row[0] for row in rows[1:]} == {"30301"}
    assert rows[1][1] == "見積書" and {row[1] for row in rows[2:]} == {"品目"}


# ---- 見積書 row -------------------------------------------------------------------------------------


def test_estimate_row_customer_title_date_and_empty_number():
    draft, snapshot = _quote(number="MF-OLD-1")  # even a stored number is not written
    estimate = dict(zip(H, _rows(build_estimate_csv(snapshot))[1]))
    assert estimate["取引先名称"] == "株式会社テスト計測"
    assert estimate["件名"] == "水中ドローン一式, 「点検」用"
    assert estimate["発行日"] == snapshot.issue_date.replace("-", "/")
    assert estimate["見積書番号"] == ""
    for empty in ("メモ", "タグ", "小計", "消費税", "合計金額", "自社担当者氏名", "取引先敬称", "取引先郵便番号", "取引先住所1"):
        assert estimate[empty] == ""
    text = build_estimate_csv(snapshot).decode("cp932")
    for internal in (draft.quote_draft_id, snapshot.approved_quote_snapshot_id, snapshot.quote_number_candidate, "MF-OLD-1"):
        assert internal not in text


def test_remarks_are_the_customer_remarks_only():
    draft, snapshot = _quote()
    estimate = dict(zip(H, _rows(build_estimate_csv(snapshot))[1]))
    expected = "\n".join(item.text.strip() for item in snapshot.remarks if item.text and item.text.strip())
    assert estimate["備考"] == expected
    assert "社内メモ" not in build_estimate_csv(snapshot).decode("cp932")


def test_customer_is_required():
    _draft, snapshot = _quote()
    with pytest.raises(MoneyForwardCsvError) as error:
        build_estimate_csv(snapshot.model_copy(update={"customer": "  "}))
    assert error.value.code == "CUSTOMER_REQUIRED" and "取引先名称" in error.value.message


def test_only_approved_snapshots_are_exported():
    draft, _snapshot = _quote()
    with pytest.raises(Exception):
        build_estimate_csv(draft)


# ---- 品目 rows -----------------------------------------------------------------------------------


def _items(snapshot):
    return [dict(zip(H, row)) for row in _rows(build_estimate_csv(snapshot))[2:]]


def test_item_rows_use_the_approved_customer_lines_in_order(tmp_path):
    def reorder(draft):
        sb.move_line(draft, _line(draft, *C).line_id, -2)  # C, A, B

    draft, snapshot = _quote(edit=reorder)
    items = _items(snapshot)
    products = [line for line in snapshot.customer_lines_snapshot if line.line_kind != "SHIPPING"]
    assert [item["品名"] for item in items[:-1]] == [line.display_name for line in products]
    assert [item["品目コード"] for item in items[:-1]] == ["SPECTRA0001", "9680-BASE", "11490"]
    for item, line in zip(items, products):
        assert item["単価"] == str(int(line.unit_price_jpy))  # the quote's final price
        assert item["数量"] == str(line.quantity)
        assert item["金額"] == str(int(line.amount_jpy))
        assert item["品目消費税率"] == "10%"
    assert items[1]["数量"] == "2"
    manual = _line(draft, *B)
    assert items[2]["単価"] == "250000" and manual.final_price_status == FinalPriceStatus.MANUAL_OVERRIDE
    # Same order as the PDF.
    _bundle, pdf = export_spaceone_quote_pdf(snapshot, output_dir=tmp_path)
    text = "".join(page.extract_text() for page in PdfReader(str(pdf)).pages)
    names = [item["品名"] for item in items]
    assert sorted(names, key=text.find) == names


def test_shipping_is_one_last_row_with_all_parts():
    draft, snapshot = _quote()
    items = _items(snapshot)
    shipping = items[-1]
    parts = sb.shipping_breakdown(draft)
    total = int(parts["dt_pt_customer"] + parts["spectra_customer"])
    assert len(draft.global_shipping_lines) == 2 and draft.spectra_shipping is not None
    assert (shipping["品名"], shipping["単価"], shipping["数量"], shipping["金額"]) == ("国際輸送費", str(total), "1", str(total))
    assert shipping["品目コード"] == "" and shipping["詳細"] == "" and shipping["品目消費税率"] == "10%"
    assert sum(1 for item in items if item["品名"] == "国際輸送費") == 1
    assert sum(int(item["金額"]) for item in items) == int(snapshot.subtotal_ex_tax_jpy)
    text = build_estimate_csv(snapshot).decode("cp932")
    for detail in ("Large", "Small", "LARGE_BOX", "個口", "1.2"):
        assert detail not in text


# ---- 税 -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(("rate", "value"), [(0.10, "10%"), (0.08, "8%"), (0.05, "5%")])
def test_tax_rates(rate, value):
    _draft, snapshot = _quote(tax=rate)
    assert {item["品目消費税率"] for item in _items(snapshot)} == {value}


def test_unsupported_and_zero_tax_are_not_guessed():
    _draft, snapshot = _quote(tax=0.03)
    with pytest.raises(MoneyForwardCsvError) as error:
        build_estimate_csv(snapshot)
    assert error.value.code == "TAX_RATE_UNSUPPORTED" and "MoneyForward CSVで使用できない税率です" in error.value.message

    _draft, zero = _quote(tax=0.0)
    with pytest.raises(MoneyForwardCsvError) as error:
        build_estimate_csv(zero)
    assert error.value.code == "TAX_ZERO_CATEGORY_REQUIRED"
    assert {item["品目消費税率"] for item in _rows_with(zero, "非課税")} == {"非課税"}
    with pytest.raises(MoneyForwardCsvError):
        moneyforward_tax_value(0.0, "10%")


def _rows_with(snapshot, category):
    return [dict(zip(H, row)) for row in _rows(build_estimate_csv(snapshot, zero_tax_category=category))[2:]]


# ---- encoding / CSV ------------------------------------------------------------------------------


def test_japanese_comma_quote_and_newline_survive():
    customer = '株式会社"ダブル",カンマ\n改行テスト'
    _draft, snapshot = _quote(customer=customer, title="件名「一式」, \"引用\"")
    estimate = dict(zip(H, _rows(build_estimate_csv(snapshot))[1]))
    assert estimate["取引先名称"] == customer.strip()
    assert estimate["件名"] == "件名「一式」, \"引用\""


def test_characters_outside_cp932_stop_the_export_and_are_named():
    _draft, snapshot = _quote(customer="𠮷野家テスト株式会社")
    with pytest.raises(MoneyForwardCsvError) as error:
        build_estimate_csv(snapshot)
    assert error.value.code == "ENCODING"
    assert "取引先名称" in error.value.message and "𠮷" in error.value.message and "U+20BB7" in error.value.message


def test_filename_is_readable_and_safe():
    from datetime import datetime

    _draft, snapshot = _quote(customer='株式会社/テスト:計測*"')
    name = estimate_csv_filename(snapshot, on=datetime(2026, 11, 23))
    assert name == "moneyforward_estimate_株式会社_テスト_計測_20261123.csv"
    assert snapshot.quote_draft_id not in name


# ---- snapshot ------------------------------------------------------------------------------------


def test_csv_does_not_change_after_master_and_shipping_updates():
    _draft, snapshot = _quote()
    before = build_estimate_csv(snapshot)
    import_price_master(PriceMasterType.SPECTRA_GOLD, "SPECTRA-new.xlsx", _spectra(250000, 175000))
    ShippingRuleRepository().save_standard_global_rate(ShippingType.LARGE_BOX, rate_usd=9999, effective_from="2027-01-01")
    stored = SqliteQuoteRepository().get_snapshot_for_draft(snapshot.quote_draft_id, snapshot.quote_version)
    assert build_estimate_csv(stored) == before


def test_no_internal_values_in_the_customer_csv():
    draft, snapshot = _quote()
    text = build_estimate_csv(snapshot).decode("cp932")
    for term in ("Dealer", "Gold", "DT40", "PT30", "SPECTRA_GOLD", "原価", "粗利", "Price Book", "社内メモ"):
        assert term not in text
    for line in draft.configuration_lines:
        snapshot_price = line.manufacturer_price_snapshot
        for value in (snapshot_price.manufacturer_dealer_price_usd, line.dealer_cost_jpy, line.landed_cost_jpy):
            assert f",\"{value:g}\"" not in text and f",\"{int(value)}\"," not in text


# ---- regression ----------------------------------------------------------------------------------


def test_pdf_excel_and_revision_still_work(tmp_path):
    draft, snapshot = _quote(number=None)
    export_spaceone_quote_pdf(snapshot, output_dir=tmp_path)
    _bundle, excel = export_spaceone_quote_excel(snapshot, output_dir=tmp_path)
    assert load_workbook(excel)["見積書"]["B8"].value in (None, "")
    assert snapshot.status == QuoteDraftStatus.APPROVED
    revision = create_revision_draft(snapshot)
    assert [line.manufacturer_sku for line in revision.configuration_lines] == [
        line.manufacturer_sku for line in draft.configuration_lines
    ]


# ---- UI ------------------------------------------------------------------------------------------


def _approved_ui(snapshot_tax=0.10):
    from tests.test_portal3b1_1_product_picker import _open_builder

    draft, snapshot = _quote(tax=snapshot_tax)
    at = _open_builder()
    at.session_state["quote_draft"] = SqliteQuoteRepository().get_draft(draft.quote_draft_id, draft.quote_version).draft
    at.session_state["approved_quote_snapshot"] = snapshot
    at.run()
    assert not at.exception
    return at


def test_ui_has_the_moneyforward_download_and_no_old_buttons():
    at = _approved_ui()
    keys = [item.key for item in at.button]
    assert "export_mf_tsv" not in keys and "export_mf_csv" not in keys
    downloads = at.get("download_button")
    assert any("MoneyForward用CSVをダウンロード" in str(item.proto.label) for item in downloads)
    assert "**MoneyForward CSV**" in [item.value for item in at.markdown]


def test_ui_shows_why_the_csv_cannot_be_made():
    at = _approved_ui(snapshot_tax=0.03)
    assert at.button(key="export_mf_estimate_csv").disabled
    assert any("MoneyForward CSVで使用できない税率です" in item.value for item in at.error)
