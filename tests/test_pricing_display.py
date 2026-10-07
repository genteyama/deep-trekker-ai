import json
from pathlib import Path

import pytest

from models import ExchangeRateReason, FinalPriceStatus, PriceAdjustmentReason, PricingPolicyType
from repositories.sqlite_quote_repository import SqliteQuoteRepository
from tests.test_exchange_rate_safety import _no_official_files, _open_quote_page
from tests.test_quote_builder import _line, _mag_v1, _photon_draft, _v1, _v1_mag_draft
from ui.pricing_display import (
    display_signed_percent,
    display_signed_yen,
    market_reference_candidate,
    parse_exchange_rate_form,
    price_comparison,
    rate_change_notice,
    standard_price_basis,
    submit_exchange_rate,
    submit_final_price,
    validate_final_price_input,
)
from ui.quote_steps import FX_METADATA_KEYS, SESSION_FX_EDITOR, separate_product_lines
from ui.warning_summary import summarize_draft_warnings

WORKSPACE = json.loads((Path(__file__).resolve().parents[1] / "locales" / "ja.json").read_text(encoding="utf-8"))[
    "pages"
]["quote_control"]["workspace"]


def _fx_form(rate, **extra):
    return parse_exchange_rate_form({"rate": rate, **extra})


def _no_recalculation(rate):
    raise AssertionError("Standard candidates must not be recalculated for a metadata-only update.")


def test_exchange_rate_reasons_have_japanese_labels_and_keep_enum_values():
    labels = WORKSPACE["fx_reasons"]

    assert set(labels) == {item.value for item in ExchangeRateReason}
    assert labels["MARKET_PLUS_BUFFER"] == "市場参考＋リスクバッファ"
    assert labels["PRIOR_QUOTE_ALIGNMENT"] == "過去見積との整合"
    assert labels["OTHER"] == "その他"
    assert _fx_form("165", reason_code="LONG_TERM_PROJECT")["reason_code"] == ExchangeRateReason.LONG_TERM_PROJECT


def test_price_adjustment_reasons_have_japanese_labels():
    labels = WORKSPACE["adjustment_reasons"]

    assert set(labels) == {item.value for item in PriceAdjustmentReason}
    assert labels["COMPETITIVE_RESPONSE"] == "競合対応"
    assert labels["MULTI_UNIT"] == "複数台・一括導入"
    assert labels["MANUFACTURER_SPECIAL_PRICE"] == "メーカー特別価格"
    assert labels["ROUNDING"] == "端数調整"


def test_market_reference_candidate_is_display_only_sum():
    assert market_reference_candidate(158.2, 5.0) == 163.2
    assert market_reference_candidate(158.2, None) == 158.2
    assert market_reference_candidate(None, 5.0) is None
    parsed = _fx_form("160", market_rate="158.2", buffer="5")
    assert parsed["rate"] == 160
    assert (parsed["market_reference_rate"], parsed["exchange_rate_buffer"]) == (158.2, 5.0)
    with pytest.raises(ValueError, match="fx_market_invalid"):
        _fx_form("160", market_rate="abc")
    with pytest.raises(ValueError, match="fx_invalid"):
        _fx_form("0")


def test_same_rate_saves_metadata_only_without_recalculation():
    draft = _photon_draft()
    standards = [line.standard_sales_price_candidate_jpy for line in draft.configuration_lines]
    parsed = _fx_form(
        "170",
        reason_code="MARKET_PLUS_BUFFER",
        reason_note="月初レート",
        set_by="sales",
        market_rate="165",
        market_date="2026-10-01",
        market_source="bank TTS",
        buffer="5",
    )

    assert submit_exchange_rate(draft, parsed, recalculate=_no_recalculation) is False
    context = draft.pricing_context
    assert draft.exchange_rate == 170
    assert context.exchange_rate_reason_code == ExchangeRateReason.MARKET_PLUS_BUFFER
    assert (context.market_reference_rate, context.exchange_rate_buffer) == (165, 5)
    assert (context.market_reference_date, context.market_reference_source) == ("2026-10-01", "bank TTS")
    assert context.exchange_rate_set_by == "sales"
    assert [line.standard_sales_price_candidate_jpy for line in draft.configuration_lines] == standards


def test_rate_change_saves_metadata_and_recalculates():
    draft = _v1_mag_draft(_mag_v1())
    requested = []

    def recalculate(rate):
        requested.append(rate)
        return _mag_v1(rate)

    changed = submit_exchange_rate(
        draft, _fx_form("160", reason_code="CUSTOMER_CONDITION", reason_note="顧客指定"), recalculate=recalculate
    )

    assert changed is True
    assert requested == [160]
    assert draft.exchange_rate == 160
    assert draft.pricing_context.exchange_rate_reason_code == ExchangeRateReason.CUSTOMER_CONDITION
    assert draft.pricing_context.exchange_rate_reason_note == "顧客指定"
    assert _line(draft, "9701-MAG-4K").standard_sales_price_candidate_jpy == 6237000


def test_standard_price_basis_for_msrp_fixed_and_review():
    draft = _v1_mag_draft(_mag_v1())

    msrp = standard_price_basis(WORKSPACE, _line(draft, "9701-MAG-4K"))
    fixed = standard_price_basis(WORKSPACE, _line(draft, "2604"))

    assert (msrp["status"], msrp["text"]) == ("OK", "MSRP × 採用為替 × 1.10")
    assert (fixed["status"], fixed["text"]) == ("OK", "固定標準価格")


def test_manual_review_lines_show_review_with_japanese_reason():
    special = _v1("9701-MAG-4K", 1.1).model_copy(
        update={"pricing_policy_type": PricingPolicyType.MANUAL_REVIEW, "multiplier": None, "raw_sales_price_jpy": None}
    )
    sales = [item for item in _mag_v1() if item.manufacturer_sku not in {"9701-MAG-4K", "9735"}]
    sales += [special, _v1("9735", 1.1, row=19), _v1("9735", 1.1, row=25)]
    sales = [item for item in sales if item.manufacturer_sku != "5608"]
    draft = _v1_mag_draft(sales)

    results = {sku: standard_price_basis(WORKSPACE, _line(draft, sku)) for sku in ("9701-MAG-4K", "9735", "5608")}

    assert all(item["status"] == "REVIEW" and item["text"] == "要確認" for item in results.values())
    assert results["9701-MAG-4K"]["reason"] == "特殊な価格式のため確認が必要です"
    assert results["9735"]["reason"] == "同じSKUの価格候補が複数あります"
    assert results["5608"]["reason"] == "メーカーSKUを特定できません"


def test_standard_to_final_difference_and_rate_display():
    line = _line(_v1_mag_draft(_mag_v1()), "9701-MAG-4K").model_copy(
        update={"standard_sales_price_candidate_jpy": 6500000.0, "final_sales_price_jpy": 6300000.0}
    )

    comparison = price_comparison(line)

    assert comparison["difference"] == -200000
    assert display_signed_yen(comparison["difference"], "—") == "-¥200,000"
    assert display_signed_percent(comparison["rate"], "—") == "-3.08%"
    assert display_signed_yen(None, "—") == "—"
    assert price_comparison(line.model_copy(update={"standard_sales_price_candidate_jpy": None}))["difference"] is None


def test_adjustment_reason_rules():
    line = _line(_v1_mag_draft(_mag_v1()), "9701-MAG-4K")
    standard = line.standard_sales_price_candidate_jpy

    assert validate_final_price_input(line, "6000000", "", "")["error"] == "reason_required"
    assert validate_final_price_input(line, str(int(standard)), "", "")["error"] is None
    assert validate_final_price_input(line, "6,000,000", "OTHER", " ")["error"] == "note_required"
    ok = validate_final_price_input(line, "6000000", "OTHER", "保守契約込み")
    assert (ok["error"], ok["amount"], ok["reason_note"]) == (None, 6000000, "保守契約込み")
    assert validate_final_price_input(line, "abc", "", "")["error"] == "amount_invalid"
    no_standard = line.model_copy(update={"standard_sales_price_candidate_jpy": None})
    assert validate_final_price_input(no_standard, "6000000", "", "")["error"] is None


def test_final_price_save_adds_one_adjustment_per_decision():
    draft = _v1_mag_draft(_mag_v1())
    line = _line(draft, "9701-MAG-4K")
    values = validate_final_price_input(line, "6300000", "COMPETITIVE_RESPONSE", "")

    assert submit_final_price(draft, line, values, reason_labels=WORKSPACE["adjustment_reasons"]) is True
    assert submit_final_price(draft, line, values, reason_labels=WORKSPACE["adjustment_reasons"]) is False

    adjustments = [item for item in draft.adjustments if item.line_id == line.line_id]
    assert len(adjustments) == 1
    assert adjustments[0].reason_code == PriceAdjustmentReason.COMPETITIVE_RESPONSE
    assert adjustments[0].reason == "競合対応"
    assert line.final_price_status == FinalPriceStatus.MANUAL_OVERRIDE
    assert line.final_sales_price_jpy == 6300000


def test_rate_change_warnings_are_available_once_for_the_screen():
    draft = _v1_mag_draft(_mag_v1())
    line = _line(draft, "9701-MAG-4K")
    submit_final_price(
        draft, line, validate_final_price_input(line, str(int(line.standard_sales_price_candidate_jpy)), "", ""), reason_labels={}
    )
    submit_exchange_rate(draft, _fx_form("160"), recalculate=lambda rate: _mag_v1(rate))

    notice = rate_change_notice(draft)
    kinds = dict(summarize_draft_warnings(draft)["lines"])

    assert notice["kept"] == ["9701-MAG-4K"]
    assert _line(draft, "9701-MAG-4K").final_sales_price_jpy == 6627000
    assert kinds.get("fx_final_kept") == 1
    assert "fx_final_kept" in WORKSPACE["warning_kinds"]


def test_workspace_saves_fx_metadata_once_without_changing_rate(tmp_path, monkeypatch):
    _no_official_files(tmp_path, monkeypatch)
    at = _open_quote_page()
    at.button(key="ihi_photon_draft").click().run()
    draft_id = at.session_state["quote_draft"].quote_draft_id
    at.session_state["quote_workspace_step"] = 2
    at.run()

    at.text_input(key=FX_METADATA_KEYS["market_reference_rate"]).set_value("158.2")
    at.text_input(key=FX_METADATA_KEYS["exchange_rate_buffer"]).set_value("5")
    at.selectbox(key=FX_METADATA_KEYS["exchange_rate_reason_code"]).set_value("MARKET_PLUS_BUFFER")
    at.run()

    # Typing alone does not save anything.
    assert at.session_state["quote_draft"].pricing_context.market_reference_rate is None
    visible = " ".join(item.value for item in at.markdown)
    assert "参考候補：163.20円/USD" in visible

    at.button(key="apply_quote_exchange_rate").click().run()

    assert not at.exception
    draft = at.session_state["quote_draft"]
    assert draft.exchange_rate == 160
    assert draft.pricing_context.market_reference_rate == 158.2
    assert draft.pricing_context.exchange_rate_reason_code == ExchangeRateReason.MARKET_PLUS_BUFFER
    assert at.text_input(key=SESSION_FX_EDITOR).value == "160"
    stored = SqliteQuoteRepository().get_draft(draft_id)
    assert stored.draft.pricing_context.exchange_rate_buffer == 5


def test_workspace_requires_reason_before_saving_a_different_final_price(tmp_path, monkeypatch):
    _no_official_files(tmp_path, monkeypatch)
    at = _open_quote_page()
    at.button(key="ihi_photon_draft").click().run()
    draft = at.session_state["quote_draft"]
    line = separate_product_lines(draft)[0]
    # Without official files no SO_MASTER candidate exists, so a standard price is placed for this UI check.
    line.standard_sales_price_candidate_jpy = 1000000.0
    at.session_state["quote_workspace_step"] = 2
    at.run()
    other = 999000

    at.text_input(key=f"manual_price_{line.line_id}").set_value(str(other))
    at.button(key=f"apply_manual_{line.line_id}").click().run()

    assert not at.exception
    assert _line(at.session_state["quote_draft"], line.manufacturer_sku).final_sales_price_jpy is None
    assert any("価格調整理由を選んでください" in item.value for item in at.warning)

    at.selectbox(key=f"adjust_reason_{line.line_id}").set_value("ROUNDING")
    at.button(key=f"apply_manual_{line.line_id}").click().run()

    saved = at.session_state["quote_draft"]
    assert _line(saved, line.manufacturer_sku).final_sales_price_jpy == other
    adjustments = [item for item in saved.adjustments if item.line_id == line.line_id]
    assert [item.reason_code for item in adjustments] == [PriceAdjustmentReason.ROUNDING]
