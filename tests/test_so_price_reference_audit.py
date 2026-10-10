import hashlib
from datetime import datetime
from io import BytesIO

from openpyxl import Workbook

from agents.so_price_reference_audit import ReferenceAuditStatus, audit_price_references
from repositories.sqlite_price_master_repository import SqlitePriceMasterRepository

DT40_ID = "1xVJqlhF-sqMKJ3bnZ5hYjP2lTiYMl_5VaODFBL5CIx4"


def _workbook(sheets: dict) -> BytesIO:
    workbook = Workbook()
    first = True
    for title, rows in sheets.items():
        sheet = workbook.active if first else workbook.create_sheet(title)
        sheet.title = title
        first = False
        for row in rows:
            sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer


def _formula(cell: str, fallback: float) -> str:
    return (
        '=IFERROR(IMPORTRANGE("https://docs.google.com/spreadsheets/d/'
        f'{DT40_ID}/edit","PHOTON!{cell}"),{fallback})'
    )


def _books():
    manufacturer = _workbook(
        {
            "PHOTON": [
                ["Part Number", "Description", "MSRP", "DT40", "Notes:"],
                ["SKU-A", "Item A", 100, 60, None],
                ["SKU-B", "Item B", 200, 120, None],
                ["SKU-OK", "Independent", 300, 180, None],
                ["SKU-FORMULA", "Formula", 400, 240, None],
                ["SKU-NO-REF", "No reference", 700, 420, None],
            ],
            "PIVOT": [
                ["Part Number", "Description", "MSRP", "DT40", "Notes:"],
                ["DUP-SKU", "Duplicate", 500, 300, None],
                ["CONFLICT", "Conflict A", 10, 6, None],
            ],
            "MAG": [
                ["Part Number", "Description", "MSRP", "DT40", "Notes:"],
                ["DUP-SKU", "Duplicate", 500, 300, None],
                ["CONFLICT", "Conflict B", 20, 12, None],
            ],
            "REVOLUTION-OBSOLETE": [
                ["Part Number", "Description", "MSRP", "DT40", "Notes:"],
                ["OLD-SKU", "Obsolete", 1, 1, None],
            ],
        }
    )
    pt30 = _workbook(
        {
            "A-200": [
                ["Part Number", "Description", "MSRP", "PT30", "Notes:"],
                ["PT-ONLY", "Pipe", 50, 35, None],
            ]
        }
    )
    so = _workbook(
        {
            "_SRC_DT40": [
                ["Part Number", "（メーカー）定価", "卸値"],
                ["ONLY-SRC", 1, 1],
            ],
            "PHOTON": [
                ["Part Number", "製品名", "内容", "（メーカー）定価", "卸値"],
                ["SKU-A", "正しい参照", None, _formula("C2", 100), _formula("D2", 60)],
                ["SKU-B", "別row", None, _formula("C2", 100), _formula("D2", 60)],
                ["9685", "未登録", None, _formula("C2", 1), _formula("D2", 1)],
                ["DUP-SKU", "重複", None, _formula("C2", 500), _formula("D2", 300)],
                ["CONFLICT", "価格衝突", None, _formula("C2", 10), _formula("D2", 6)],
                ["OLD-SKU", "廃番", None, _formula("C2", 1), _formula("D2", 1)],
                ["SKU-FORMULA", "非対応式", None, "=SUM(A1)", "=SUM(B1)"],
                ["SKU-OK", "列ごとの監査", None, _formula("C4", 300), _formula("D3", 120)],
                ["SKU-NO-REF", "参照なし", None, 700, 420],
                [datetime(2020, 1, 1), "不正SKU", None, None, None],
                [None, "キャビブラスター輸送費", None, None, None],
            ],
        }
    )
    return so, manufacturer, pt30


def _by_sku(report):
    grouped = {}
    for row in report.rows:
        grouped.setdefault(row.normalized_sku or row.so_sku, {})[row.field] = row
    return grouped


def test_reference_audit_classifies_exact_ambiguous_and_unsafe_cases():
    report = audit_price_references(*_books())
    rows = _by_sku(report)

    assert "ONLY-SRC" not in rows
    correct = rows["SKU-A"]
    assert correct["MSRP"].status == ReferenceAuditStatus.CORRECT
    assert correct["DEALER"].status == ReferenceAuditStatus.CORRECT
    assert correct["MSRP"].expected_cell == "C2"
    assert correct["DEALER"].expected_cell == "D2"
    assert correct["MSRP"].safe_to_repair is False

    wrong = rows["SKU-B"]
    assert wrong["MSRP"].status == ReferenceAuditStatus.EXACT_REPAIRABLE
    assert wrong["MSRP"].safe_to_repair is True
    assert wrong["MSRP"].current_referenced_sku == "SKU-A"
    assert wrong["MSRP"].expected_sku == "SKU-B"
    assert wrong["MSRP"].expected_cell == "C3"

    missing = rows["9685"]["MSRP"]
    assert missing.status == ReferenceAuditStatus.SKU_NOT_FOUND
    assert missing.safe_to_repair is False

    assert rows["DUP-SKU"]["MSRP"].status == ReferenceAuditStatus.AMBIGUOUS_OCCURRENCE
    assert rows["DUP-SKU"]["MSRP"].safe_to_repair is False
    assert rows["CONFLICT"]["DEALER"].status == ReferenceAuditStatus.SOURCE_PRICE_CONFLICT
    assert rows["CONFLICT"]["DEALER"].safe_to_repair is False
    assert rows["OLD-SKU"]["MSRP"].status == ReferenceAuditStatus.OBSOLETE_ONLY
    assert rows["OLD-SKU"]["MSRP"].safe_to_repair is False
    assert rows["SKU-FORMULA"]["MSRP"].status == ReferenceAuditStatus.UNSUPPORTED_FORMULA
    assert rows["SKU-FORMULA"]["DEALER"].safe_to_repair is False

    independent = rows["SKU-OK"]
    assert independent["MSRP"].status == ReferenceAuditStatus.CORRECT
    assert independent["DEALER"].status == ReferenceAuditStatus.EXACT_REPAIRABLE
    assert independent["DEALER"].current_referenced_sku == "SKU-B"
    assert independent["DEALER"].safe_to_repair is True

    invalid = next(row for row in report.rows if row.status == ReferenceAuditStatus.INVALID_SKU)
    assert invalid.safe_to_repair is False
    shipping = next(row for row in report.rows if row.so_sku is None)
    assert shipping.status == ReferenceAuditStatus.MANUAL_REVIEW
    assert shipping.safe_to_repair is False
    assert {row.field for row in report.rows if row.normalized_sku == "SKU-A"} == {"MSRP", "DEALER"}


def test_numeric_cells_without_formula_are_not_repairable():
    rows = _by_sku(audit_price_references(*_books()))["SKU-NO-REF"]

    for field_name, expected_cell in (("MSRP", "C6"), ("DEALER", "D6")):
        row = rows[field_name]
        assert row.status == ReferenceAuditStatus.NO_REFERENCE
        assert row.safe_to_repair is False
        assert row.expected_workbook == "DT40"
        assert row.expected_sheet == "PHOTON"
        assert row.expected_row == 6
        assert row.expected_cell == expected_cell


def test_audit_does_not_change_workbooks_or_registry(tmp_path, monkeypatch):
    so, dt40, pt30 = _books()
    so_path = tmp_path / "so.xlsx"
    dt40_path = tmp_path / "dt40.xlsx"
    pt30_path = tmp_path / "pt30.xlsx"
    for path, source in ((so_path, so), (dt40_path, dt40), (pt30_path, pt30)):
        path.write_bytes(source.getvalue())
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (so_path, dt40_path, pt30_path)}

    def fail_registry(*_args, **_kwargs):
        raise AssertionError("price master registry was opened")

    monkeypatch.setattr(SqlitePriceMasterRepository, "__init__", fail_registry)
    report = audit_price_references(so_path, dt40_path, pt30_path)

    after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (so_path, dt40_path, pt30_path)}
    assert after == before
    assert report.rows
    assert all(row.safe_to_repair is False or row.status == ReferenceAuditStatus.EXACT_REPAIRABLE for row in report.rows)
