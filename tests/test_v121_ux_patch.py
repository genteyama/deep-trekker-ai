import json

from agents.manufacturer_price_source import SOURCE_SPECTRA_GOLD, save_source_setting
from repositories.manufacturer_price_source_repository import ManufacturerPriceSourceRepository
from tests.test_price_master_ui import _open_quote_page, _texts
from tests.test_spectra_quote_entry import _activate_quote_calc, _activate_spectra, _create
from ui.warning_summary import format_warning_details, summarize_draft_warnings


def _ja_workspace():
    with open("locales/ja.json", encoding="utf-8") as file:
        return json.load(file)["pages"]["quote_control"]["workspace"]


def test_future_spectra_source_is_read_only_and_hides_previous_failure():
    repository = ManufacturerPriceSourceRepository()
    source = save_source_setting(
        SOURCE_SPECTRA_GOLD,
        "https://docs.google.com/spreadsheets/d/future-sheet/edit",
        True,
        expected_row_version=0,
        repository=repository,
    )
    repository.record_check(
        SOURCE_SPECTRA_GOLD,
        status="GOOGLE_EXPORT_FAILED",
        error="GOOGLE_EXPORT_FAILED",
        expected_row_version=source.row_version,
    )

    at = _open_quote_page()
    texts = _texts(at)

    assert "SPECTRA GOLD — オンライン連携保留" in texts
    assert "オンライン連携：停止中" in texts
    assert "GOOGLE_EXPORT_FAILED" not in texts
    assert not any(item.key == "manufacturer_source_url_SPECTRA_GOLD" for item in at.text_input)
    assert not any(item.key == "manufacturer_source_enabled_SPECTRA_GOLD" for item in at.checkbox)
    assert not any(item.key == "manufacturer_source_save_SPECTRA_GOLD" for item in at.button)
    assert not any(item.key == "manufacturer_source_check_SPECTRA_GOLD" for item in at.button)
    assert any(item.key == "manufacturer_source_url_DT40" for item in at.text_input)
    assert any(item.key == "manufacturer_source_check_PT30" for item in at.button)


def test_spectra_review_summary_is_concrete_deduplicated_and_localized():
    _activate_spectra()
    _activate_quote_calc()
    draft = _create(international_shipping_usd=None, domestic_shipping_jpy=None)
    workspace = _ja_workspace()

    summary = summarize_draft_warnings(draft)
    kinds = [kind for kind, _count in summary["lines"]]
    lines = [
        workspace["warning_kinds"][kind].format(count=count)
        for kind, count in summary["lines"]
    ]
    details = format_warning_details(
        summary,
        workspace["warning_kinds"],
        workspace["warning_detail_other"],
    )

    assert len(kinds) == len(set(kinds))
    assert "final_price" in kinds
    assert "international_shipping" in kinds
    assert "domestic_shipping" in kinds
    assert "tax" in kinds
    assert "lead_time" in kinds
    assert "販売価格：未設定（1件）" in lines
    assert "国際輸送原価：未設定" in lines
    assert "国内送料原価：未設定" in lines
    assert "納期：未設定" in lines
    assert any("販売価格は自動推定せず" in item for item in details)
    assert not any("SalesPriceCandidate" in item for item in details)
    assert not any("REVIEW_REQUIRED" in item for item in details)


def test_quote_review_ui_hides_internal_status_and_warning_language():
    _activate_spectra()
    _activate_quote_calc()
    draft = _create(international_shipping_usd=None, domestic_shipping_jpy=None)
    at = _open_quote_page()
    at.session_state["quote_draft"] = draft
    at.session_state["quote_workspace_step"] = 4
    at.run()
    at.button(key="check_quote_approval").click().run()

    texts = _texts(at)
    assert "現在の見積は「要確認」のため承認できません。" in texts
    assert "販売価格が未設定です。販売価格は自動推定せず、確認が必要です。" in texts
    assert "国際輸送原価：未設定" in texts
    assert "国内送料原価：未設定" in texts
    assert "SalesPriceCandidate is missing" not in texts
    assert "Engine does not invent a sales price" not in texts
    assert "QuoteDraft.status" not in texts
