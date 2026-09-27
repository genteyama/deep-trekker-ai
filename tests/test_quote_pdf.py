from pathlib import Path

import pytest

from agents.formal_quote_document import build_formal_quote_document, formal_quote_comparable
from agents.quote_export import (
    CUSTOMER_FORBIDDEN_TERMS,
    QuoteExportError,
    assert_spaceone_excel_pdf_match,
    export_spaceone_quote_excel,
    export_spaceone_quote_pdf,
    scan_customer_pdf_leaks,
    unique_output_path,
)
from agents.quote_pdf import extract_pdf_text, pdf_page_info, render_formal_quote_pdf
from models import ExportFileType, ExportPurpose, QuoteDraftStatus
from repositories.sqlite_quote_repository import SqliteQuoteRepository
from tests.test_quote_approval import _approve, _ready_photon
from tests.test_quote_builder import _photon_draft


def _photon_snapshot():
    return _approve(_ready_photon())[1]


def test_formal_document_is_built_only_from_approved_snapshot():
    snapshot = _photon_snapshot()
    document = build_formal_quote_document(snapshot, official_quote_number="8195")

    assert document.source_approved_snapshot_id == snapshot.approved_quote_snapshot_id
    assert document.quote_number == "8195"
    assert document.customer_name == snapshot.customer
    assert document.subject == snapshot.title
    assert document.issue_date == "2026-09-26"
    assert document.valid_until == "2026-10-31"
    assert document.subtotal == 7160000
    assert document.tax_amount == 716000
    assert document.total == 7876000
    assert len(document.customer_lines) == len(snapshot.customer_lines_snapshot)
    assert document.remarks == [item.text for item in snapshot.remarks]
    assert len(document.remarks) == 5


def test_draft_cannot_build_document_or_formal_pdf(tmp_path):
    draft = _photon_draft()

    with pytest.raises(Exception, match="ApprovedQuoteSnapshot"):
        build_formal_quote_document(draft, official_quote_number="8195")
    with pytest.raises(QuoteExportError, match="ApprovedQuoteSnapshot"):
        export_spaceone_quote_pdf(draft, output_dir=tmp_path, official_quote_number="8195")


def test_ready_for_approval_cannot_export_formal_pdf(tmp_path):
    draft = _ready_photon()
    assert draft.status == QuoteDraftStatus.READY_FOR_APPROVAL
    with pytest.raises(QuoteExportError, match="ApprovedQuoteSnapshot"):
        export_spaceone_quote_pdf(draft, output_dir=tmp_path, official_quote_number="8195")


def test_ihi_photon_pdf_matches_excel_and_snapshot(tmp_path):
    snapshot = _photon_snapshot()
    document = build_formal_quote_document(snapshot, official_quote_number="8195")
    _, excel_path = export_spaceone_quote_excel(
        snapshot,
        output_dir=tmp_path,
        official_quote_number="8195",
        generated_by="弦",
        purpose=ExportPurpose.FORMAL,
    )
    bundle, pdf_path = export_spaceone_quote_pdf(
        snapshot,
        output_dir=tmp_path,
        official_quote_number="8195",
        generated_by="弦",
        purpose=ExportPurpose.FORMAL,
    )
    text = extract_pdf_text(pdf_path)
    info = pdf_page_info(pdf_path)

    assert pdf_path.name == "8195_spaceone_quote.pdf"
    assert pdf_path.stat().st_size > 0
    assert info["page_count"] >= 1
    assert info["pages"][0]["height"] > info["pages"][0]["width"]
    assert abs(info["pages"][0]["width"] - 595.27) < 8
    assert document.subtotal == 7160000
    assert document.tax_amount == 716000
    assert document.total == 7876000
    assert "7,160,000" in text
    assert "716,000" in text
    assert "7,876,000" in text
    assert "8195" in text
    assert snapshot.customer in text
    assert "2026/09/26" in text
    assert "2026/10/31" in text
    for remark in document.remarks:
        assert remark in text
    assert scan_customer_pdf_leaks(pdf_path) == set()
    for term in CUSTOMER_FORBIDDEN_TERMS:
        assert term.lower() not in text.lower()
    assert bundle.file_manifest[-1].file_type == ExportFileType.SPACEONE_QUOTE_PDF
    assert bundle.file_manifest[-1].total == 7876000
    assert bundle.file_manifest[-1].subtotal_ex_tax == 7160000
    assert bundle.file_manifest[-1].tax == 716000
    assert bundle.file_manifest[-1].sha256
    assert bundle.file_manifest[-1].approved_snapshot_id == snapshot.approved_quote_snapshot_id
    assert_spaceone_excel_pdf_match(excel_path, pdf_path, document)
    comparable = formal_quote_comparable(document)
    assert len(comparable["lines"]) == len(document.customer_lines)
    assert comparable["issue_date"] == snapshot.issue_date
    assert comparable["valid_until"] == snapshot.valid_until


def test_pdf_export_does_not_overwrite_existing_file(tmp_path):
    snapshot = _photon_snapshot()
    first = tmp_path / "8195_spaceone_quote.pdf"
    first.write_bytes(b"existing")
    _, path = export_spaceone_quote_pdf(
        snapshot,
        output_dir=tmp_path,
        official_quote_number="8195",
        purpose=ExportPurpose.FORMAL,
    )

    assert first.read_bytes() == b"existing"
    assert path != first
    assert path.exists()
    assert path.stat().st_size > 0


def test_logo_and_seal_are_optional(tmp_path, monkeypatch):
    snapshot = _photon_snapshot()
    document = build_formal_quote_document(snapshot, official_quote_number="8195")
    missing = tmp_path / "missing.png"
    path = tmp_path / "optional_branding.pdf"
    render_formal_quote_pdf(document, path, logo_path=missing, seal_path=missing)

    assert path.exists()
    assert path.stat().st_size > 0
    assert snapshot.customer in extract_pdf_text(path)


def test_reloaded_approved_snapshot_reproduces_the_same_pdf_content(tmp_path):
    snapshot = _photon_snapshot()
    repo = SqliteQuoteRepository(tmp_path / "quotes.sqlite3")
    repo.save_snapshot(snapshot)
    repo.close()
    reopened = SqliteQuoteRepository(tmp_path / "quotes.sqlite3")
    loaded = reopened.get_snapshot(snapshot.approved_quote_snapshot_id)
    original = build_formal_quote_document(snapshot, official_quote_number="8195")
    restored = build_formal_quote_document(loaded, official_quote_number="8195")
    _, first = export_spaceone_quote_pdf(
        snapshot, output_dir=tmp_path, official_quote_number="8195", purpose=ExportPurpose.FORMAL
    )
    _, second = export_spaceone_quote_pdf(
        loaded, output_dir=tmp_path, official_quote_number="8195", purpose=ExportPurpose.FORMAL
    )

    assert loaded.approved_quote_snapshot_id == snapshot.approved_quote_snapshot_id
    assert formal_quote_comparable(original) == formal_quote_comparable(restored)
    assert extract_pdf_text(first) == extract_pdf_text(second)
    assert "7,876,000" in extract_pdf_text(second)


def test_pdf_module_does_not_touch_pricing_or_landed_cost():
    source = Path("agents/quote_pdf.py").read_text(encoding="utf-8")
    forbidden = (
        "pricing_policy",
        "landed_cost",
        "dealer_price",
        "gross_margin",
        "DT40",
        "PT30",
        "manufacturer discount",
        "supplier_quote",
    )
    lowered = source.lower()
    for item in forbidden:
        assert item.lower() not in lowered


def test_unique_pdf_path_helper_does_not_overwrite(tmp_path):
    existing = tmp_path / "8195_spaceone_quote.pdf"
    existing.write_text("kept")
    path = unique_output_path(tmp_path, "8195_spaceone_quote.pdf")
    assert path != existing
    assert existing.read_text() == "kept"
