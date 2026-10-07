from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from agents.quote_builder import (
    FINAL_PRICE_KEPT_MARKER,
    STANDARD_DIVERGED_MARKER,
    apply_exchange_rate,
    apply_final_price,
    build_ihi_quote_draft,
)
from models import (
    ApprovedQuoteSnapshot,
    ExchangeRateReason,
    ExchangeRateSource,
    FinalPriceStatus,
    PriceAdjustmentReason,
    QuoteDraft,
)
from repositories.sqlite_quote_repository import SqliteQuoteRepository
from tests.test_exchange_rate_safety import _candidate, _line
from tests.test_quote_approval import _approve, _ready_photon
from tests.test_quote_builder import _landed, _photon_sales

FX_FIELDS = (
    "market_reference_rate",
    "market_reference_date",
    "market_reference_source",
    "exchange_rate_buffer",
    "exchange_rate_reason_code",
    "exchange_rate_reason_note",
    "exchange_rate_set_by",
    "exchange_rate_set_at",
)
ADJUSTMENT_FIELDS = ("adjustment_rate", "reason_code", "reason_note")
SET_AT = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)


def _legacy_draft_payload(draft: QuoteDraft) -> dict:
    payload = draft.model_dump(mode="json")
    for key in FX_FIELDS:
        payload["pricing_context"].pop(key)
    for item in payload["adjustments"]:
        for key in ADJUSTMENT_FIELDS:
            item.pop(key)
    return payload


def _draft_at_160():
    sales = _photon_sales()
    scenario, _ = _landed("PHOTON", sales)
    scenario = scenario.model_copy(update={"exchange_rate": 160.0})
    return build_ihi_quote_draft("PHOTON", scenario, sales, exchange_rate_source=ExchangeRateSource.STANDARD_DEFAULT)


def _warnings(line, marker):
    return [item for item in line.warnings if marker in item]


def test_legacy_draft_without_new_fields_reads_and_round_trips(tmp_path):
    draft = _ready_photon()
    loaded = QuoteDraft.model_validate(_legacy_draft_payload(draft))

    assert all(getattr(loaded.pricing_context, key) is None for key in FX_FIELDS)
    assert all(item.adjustment_rate is None and item.reason_code is None for item in loaded.adjustments)
    assert [item.reason for item in loaded.adjustments] == [item.reason for item in draft.adjustments]

    repo = SqliteQuoteRepository(tmp_path / "legacy.sqlite3")
    repo.save_draft(loaded)
    assert repo.get_draft(loaded.quote_draft_id).draft == loaded


def test_legacy_approved_snapshot_reads_with_empty_new_fields(tmp_path):
    _, snapshot = _approve(_ready_photon())
    payload = snapshot.model_dump(mode="json")
    for key in FX_FIELDS + ("adjustments_snapshot",):
        payload.pop(key)

    legacy = ApprovedQuoteSnapshot.model_validate(payload)

    assert all(getattr(legacy, key) is None for key in FX_FIELDS)
    assert legacy.adjustments_snapshot == []
    assert legacy.exchange_rate == snapshot.exchange_rate
    assert legacy.total_jpy == snapshot.total_jpy


def test_default_160_draft_has_no_invented_provenance():
    draft = _draft_at_160()

    assert draft.exchange_rate == 160.0
    assert draft.pricing_context.exchange_rate_source == ExchangeRateSource.STANDARD_DEFAULT
    assert all(getattr(draft.pricing_context, key) is None for key in FX_FIELDS)


def test_manual_rate_change_saves_human_provenance():
    draft = _draft_at_160()

    apply_exchange_rate(
        draft,
        165,
        reason_code=ExchangeRateReason.LONG_TERM_PROJECT,
        reason_note="納期 6 か月",
        set_by="弦",
        set_at=SET_AT,
    )

    context = draft.pricing_context
    assert draft.exchange_rate == 165.0
    assert context.exchange_rate_source == ExchangeRateSource.MANUAL_OVERRIDE
    assert context.exchange_rate_reason_code == ExchangeRateReason.LONG_TERM_PROJECT
    assert (context.exchange_rate_reason_note, context.exchange_rate_set_by, context.exchange_rate_set_at) == (
        "納期 6 か月",
        "弦",
        SET_AT,
    )


def test_market_reference_is_saved_only_when_given_and_never_drives_costs():
    draft = _draft_at_160()

    apply_exchange_rate(
        draft,
        165,
        reason_code="MARKET_PLUS_BUFFER",
        market_reference_rate="158.2",
        market_reference_date="2026-10-07",
        market_reference_source="manual entry",
        exchange_rate_buffer=5,
    )

    context = draft.pricing_context
    assert (context.market_reference_rate, context.exchange_rate_buffer) == (158.2, 5.0)
    assert (context.market_reference_date, context.market_reference_source) == ("2026-10-07", "manual entry")
    assert draft.exchange_rate == 165.0
    assert all(line.manufacturer_price_snapshot.exchange_rate == 165.0 for line in draft.configuration_lines)

    apply_exchange_rate(draft, 166)
    assert (context.market_reference_rate, context.exchange_rate_buffer) == (158.2, 5.0)
    assert context.exchange_rate_reason_code is None

    with pytest.raises(ValueError):
        apply_exchange_rate(draft, 167, market_reference_rate="0")
    with pytest.raises(ValueError):
        apply_exchange_rate(draft, 167, exchange_rate_buffer="nan")
    assert draft.exchange_rate == 166.0


def test_change_back_to_160_stays_manual_override_with_provenance():
    draft = _draft_at_160()

    apply_exchange_rate(draft, 165)
    apply_exchange_rate(draft, 160, reason_code=ExchangeRateReason.PRIOR_QUOTE_ALIGNMENT)

    assert draft.exchange_rate == 160.0
    assert draft.pricing_context.exchange_rate_source == ExchangeRateSource.MANUAL_OVERRIDE
    assert draft.pricing_context.exchange_rate_reason_code == ExchangeRateReason.PRIOR_QUOTE_ALIGNMENT


def test_rate_change_keeps_final_prices_recalculates_margin_and_warns():
    draft = _ready_photon()
    finals = [(line.final_sales_price_jpy, line.final_price_status) for line in draft.configuration_lines]
    landed = draft.economics_result.total_landed_cost_jpy
    margin = draft.economics_result.gross_margin_rate

    apply_exchange_rate(draft, 165)

    assert [(line.final_sales_price_jpy, line.final_price_status) for line in draft.configuration_lines] == finals
    assert draft.economics_result.total_landed_cost_jpy < landed
    assert draft.economics_result.gross_margin_rate > margin
    for line in draft.configuration_lines:
        assert len(_warnings(line, FINAL_PRICE_KEPT_MARKER)) == 1
        assert _warnings(line, STANDARD_DIVERGED_MARKER) == []

    apply_exchange_rate(draft, 170)
    assert all(len(_warnings(line, FINAL_PRICE_KEPT_MARKER)) == 1 for line in draft.configuration_lines)


def test_standard_candidate_divergence_warns_without_changing_status():
    draft = _ready_photon()
    line = _line(draft)
    apply_final_price(draft, line.line_id, FinalPriceStatus.USE_STANDARD_CANDIDATE)
    final = line.final_sales_price_jpy

    apply_exchange_rate(draft, 165, sales_candidates=[_candidate("9680-BASE", 3400000.0, 165.0)])

    assert line.standard_sales_price_candidate_jpy == 3400000.0
    assert line.final_sales_price_jpy == final
    assert line.final_price_status == FinalPriceStatus.USE_STANDARD_CANDIDATE
    assert len(_warnings(line, STANDARD_DIVERGED_MARKER)) == 1

    apply_final_price(draft, line.line_id, FinalPriceStatus.USE_STANDARD_CANDIDATE)
    assert line.final_sales_price_jpy == 3400000.0
    assert _warnings(line, STANDARD_DIVERGED_MARKER) == []
    assert _warnings(line, FINAL_PRICE_KEPT_MARKER) == []


def test_repeated_overrides_are_measured_against_the_standard_price():
    draft = _ready_photon()
    line = _line(draft)
    line.standard_sales_price_candidate_jpy = 1_000_000.0
    start = len(draft.adjustments)

    apply_final_price(draft, line.line_id, FinalPriceStatus.MANUAL_OVERRIDE, amount_jpy=950_000)
    apply_final_price(
        draft,
        line.line_id,
        FinalPriceStatus.MANUAL_OVERRIDE,
        amount_jpy=900_000,
        reason_code=PriceAdjustmentReason.COMPETITIVE_RESPONSE,
        reason_note="競合 A 社対抗",
    )

    first, second = draft.adjustments[start:]
    assert (first.original_price_jpy, first.amount_jpy, first.adjustment_rate) == (1_000_000.0, -50_000.0, -0.05)
    assert (second.original_price_jpy, second.amount_jpy, second.adjustment_rate) == (1_000_000.0, -100_000.0, -0.1)
    assert second.reason_code == PriceAdjustmentReason.COMPETITIVE_RESPONSE
    assert second.reason_note == "競合 A 社対抗"
    assert first.reason_code is None


def test_override_without_standard_price_does_not_invent_a_rate():
    draft = _ready_photon()
    line = _line(draft)
    line.standard_sales_price_candidate_jpy = None
    previous = line.final_sales_price_jpy

    apply_final_price(draft, line.line_id, FinalPriceStatus.MANUAL_OVERRIDE, amount_jpy=3_500_000, reason_code="OTHER")

    adjustment = draft.adjustments[-1]
    assert adjustment.original_price_jpy == previous
    assert adjustment.amount_jpy == round(3_500_000 - previous, 4)
    assert adjustment.adjustment_rate is None
    assert adjustment.reason_code == PriceAdjustmentReason.OTHER


def test_approval_snapshot_fixes_fx_provenance_and_adjustments():
    draft = _ready_photon()
    line = _line(draft)
    apply_exchange_rate(
        draft,
        165,
        sales_candidates=[_candidate("9680-BASE", 3_400_000.0, 165.0)],
        reason_code=ExchangeRateReason.MARKET_PLUS_BUFFER,
        reason_note="市場 158.2 + 5",
        set_by="弦",
        set_at=SET_AT,
        market_reference_rate=158.2,
        market_reference_date="2026-10-07",
        exchange_rate_buffer=5,
    )
    apply_final_price(
        draft,
        line.line_id,
        FinalPriceStatus.MANUAL_OVERRIDE,
        amount_jpy=3_300_000,
        reason_code=PriceAdjustmentReason.PUBLIC_TENDER,
        reason_note="入札",
    )

    _, snapshot = _approve(draft)

    assert snapshot.exchange_rate == 165.0
    assert snapshot.exchange_rate_reason_code == ExchangeRateReason.MARKET_PLUS_BUFFER
    assert (snapshot.market_reference_rate, snapshot.exchange_rate_buffer) == (158.2, 5.0)
    assert (snapshot.exchange_rate_set_by, snapshot.exchange_rate_set_at) == ("弦", SET_AT)
    assert snapshot.adjustments_snapshot == draft.adjustments
    last = snapshot.adjustments_snapshot[-1]
    assert (last.reason_code, last.reason_note, last.final_price_jpy) == (PriceAdjustmentReason.PUBLIC_TENDER, "入札", 3_300_000)
    assert (last.original_price_jpy, last.amount_jpy) == (3_400_000.0, -100_000.0)
    assert last.adjustment_rate == round(-100_000 / 3_400_000, 6)


def test_snapshot_stays_immutable_and_detached_from_the_draft():
    draft = _ready_photon()
    apply_exchange_rate(draft, 165, reason_code=ExchangeRateReason.BUDGET_PLANNING)
    _, snapshot = _approve(draft)

    with pytest.raises(ValidationError):
        snapshot.exchange_rate_reason_code = ExchangeRateReason.OTHER
    with pytest.raises(ValueError):
        apply_exchange_rate(draft, 160)
    draft.adjustments[0].reason_note = "changed after approval"

    assert snapshot.exchange_rate_reason_code == ExchangeRateReason.BUDGET_PLANNING
    assert snapshot.adjustments_snapshot[0].reason_note is None
