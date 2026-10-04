from types import SimpleNamespace

from agents.technical_case_agent import run_technical_case_analysis
from agents.technical_case_persistence import build_record
from llm.mock_provider import MockTechnicalCaseProvider
from models import TechnicalCaseStatus
from tests.test_quote_builder import _photon_draft
from ui.components.status import progress_text, render_recent_case_card, status_badge_html
from ui.styles import FAVICON_PATH, favicon_path, page_icon_value
from ui.work_status import (
    INFO_COMPLETE,
    INFO_MISSING,
    INFO_REVIEW_REQUIRED,
    INFO_WAITING,
    KIND_QUOTE,
    KIND_TECHNICAL,
    operations_are_blocked,
    summarize_quote,
    summarize_technical_case,
)


def _analyze():
    return run_technical_case_analysis(
        "タンク肉厚測定",
        "IHI検査計測",
        None,
        "MAG Utility Crawlerで鋼製円筒タンクの水中肉厚測定を検討。",
        provider=MockTechnicalCaseProvider(),
    )


def test_empty_technical_case_progress_and_review_count():
    summary = summarize_technical_case()
    assert summary.kind == KIND_TECHNICAL
    assert summary.total == 9
    assert summary.completed == 0
    assert summary.review_required == 0
    assert summary.item("inquiry").status == INFO_MISSING
    assert summary.process_status == TechnicalCaseStatus.DRAFT.value
    assert operations_are_blocked(summary) is False


def test_analyzed_technical_case_progress_and_waiting_manufacturer():
    run = _analyze()
    summary = summarize_technical_case(run=run)
    assert summary.completed >= 3
    assert summary.total == 9
    assert summary.review_required >= 1
    assert summary.item("inquiry").status == INFO_COMPLETE
    assert summary.item("requirements").status == INFO_COMPLETE
    assert summary.item("manufacturer_response").status == INFO_WAITING
    assert summary.process_label() in {"作成中", "解析済み", "メーカー質問レビュー中", "メーカー回答待ち"}
    assert operations_are_blocked(summary) is False


def test_technical_record_summary_uses_saved_fields():
    record = build_record(_analyze())
    record.status = TechnicalCaseStatus.WAITING_MANUFACTURER.value
    summary = summarize_technical_case(record=record)
    assert summary.customer == "IHI検査計測"
    assert summary.title == "タンク肉厚測定"
    assert summary.process_status == TechnicalCaseStatus.WAITING_MANUFACTURER.value
    assert summary.process_label() == "メーカー回答待ち"
    assert summary.review_required >= 1


def test_quote_progress_and_review_count_without_mutating_draft():
    draft = _photon_draft()
    before = draft.model_dump()
    summary = summarize_quote(draft)
    assert draft.model_dump() == before
    assert summary.kind == KIND_QUOTE
    assert summary.total == 12
    assert 0 < summary.completed < summary.total
    assert summary.review_required >= 1
    assert summary.item("configuration").status == INFO_COMPLETE
    assert summary.item("human_review").status == INFO_REVIEW_REQUIRED
    assert summary.item("approval").status != INFO_COMPLETE
    assert operations_are_blocked(summary) is False


def test_approved_quote_marks_approval_complete():
    draft = _photon_draft()
    snapshot = SimpleNamespace(customer=draft.customer, title=draft.title)
    summary = summarize_quote(draft, snapshot)
    assert summary.process_status == "APPROVED"
    assert summary.item("approval").status == INFO_COMPLETE
    assert operations_are_blocked(summary) is False


def test_progress_text_and_status_badge_include_japanese():
    summary = summarize_technical_case()
    text = progress_text(summary, {"progress_label": "進捗", "review_label": "要確認", "review_unit": "件"})
    assert "進捗：0 / 9" in text
    assert "要確認：0件" in text
    html = status_badge_html("要確認 2", tone="is-review")
    assert "要確認 2" in html
    assert "dt-status-badge" in html


def test_recent_case_card_shows_kind_and_progress():
    html_parts = []

    class _St:
        def markdown(self, value, unsafe_allow_html=False):
            html_parts.append(value)

    import ui.components.status as status_mod

    original = status_mod.st
    status_mod.st = _St()
    try:
        render_recent_case_card(
            kind_label="営業・技術",
            customer="IHI検査計測",
            title="タンク肉厚測定",
            process_label="メーカー回答待ち",
            progress="進捗：5 / 8",
            review_label="要確認：2件",
            updated_at="2026-10-04T09:30:00+09:00",
            updated_prefix="更新：",
        )
        render_recent_case_card(
            kind_label="見積",
            customer="NTT-WE",
            title="REVOLUTION構成",
            process_label="見積レビュー中",
            progress="進捗：4 / 12",
            review_label="要確認：3件",
            updated_at="2026-10-04T08:00:00+09:00",
            updated_prefix="更新：",
        )
    finally:
        status_mod.st = original

    joined = " ".join(html_parts)
    assert "営業・技術" in joined
    assert "見積" in joined
    assert "IHI検査計測" in joined
    assert "NTT-WE" in joined
    assert "dt-kind-badge" in joined


def test_favicon_uses_asset_and_falls_back(tmp_path, monkeypatch):
    from ui import styles

    if FAVICON_PATH.exists():
        assert favicon_path() == FAVICON_PATH
        assert page_icon_value() == str(FAVICON_PATH)
    monkeypatch.setattr(styles, "FAVICON_PATH", tmp_path / "missing.png")
    assert styles.favicon_path() is None
    assert styles.page_icon_value() == "🌊"


def test_home_recent_work_distinguishes_technical_and_quote(monkeypatch):
    from ui.home import _recent_work_items
    from ui.work_status import KIND_QUOTE, KIND_TECHNICAL

    record = build_record(_analyze())
    draft = _photon_draft()

    class TechRepo:
        def list_recent_cases(self, limit=8, *, view="active"):
            return [
                SimpleNamespace(
                    case_id=record.case_id,
                    customer_name=record.customer_name,
                    case_title=record.case_title,
                    status=record.status,
                    updated_at="2026-10-04T09:30:00",
                    provider="mock",
                )
            ]

        def get_case(self, case_id):
            return record

    class QuoteRepo:
        def list_recent_drafts(self, limit=8, *, view="active"):
            return [
                SimpleNamespace(
                    quote_draft_id="qd-1",
                    version=1,
                    customer_name=draft.customer or "NTT-WE",
                    subject=draft.title or "REVOLUTION構成",
                    configuration_name=draft.configuration_name,
                    status="REVIEW_REQUIRED",
                    updated_at="2026-10-04T08:00:00",
                )
            ]

        def get_draft(self, quote_draft_id, version):
            return SimpleNamespace(draft=draft)

        def get_snapshot_for_draft(self, quote_draft_id, version):
            return None

    monkeypatch.setattr("ui.home.get_technical_case_repository", lambda: TechRepo())
    monkeypatch.setattr("ui.home.get_quote_repository", lambda: QuoteRepo())
    items = _recent_work_items()
    kinds = {item["kind"] for item in items}
    assert kinds == {KIND_TECHNICAL, KIND_QUOTE}
    tech = next(item for item in items if item["kind"] == KIND_TECHNICAL)
    quote = next(item for item in items if item["kind"] == KIND_QUOTE)
    assert tech["customer"] == "IHI検査計測"
    assert quote["customer"]
    assert tech["process"]
    assert quote["process"]
