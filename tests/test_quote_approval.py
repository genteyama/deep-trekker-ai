from pydantic import ValidationError
import pytest

from agents.quote_approval import (
    QuoteApprovalError,
    QuoteApprovalStore,
    all_confirmations,
    apply_human_final_price_inputs,
    apply_ihi_photon_human_final_fixture,
    approve_quote,
    create_revision_draft,
    generate_quote_outputs,
    load_photon_human_final_input,
    validate_for_approval,
)
from agents.quote_builder import (
    apply_final_price,
    apply_minimum_margin_reference,
    apply_presentation_mode,
    apply_selected_remarks,
    apply_shipping_final_price,
    apply_tax_rate,
)
from models import (
    CustomerPresentationMode,
    FinalPriceStatus,
    QuoteDraftStatus,
)
from tests.test_quote_builder import _mag_draft, _photon_draft


def _confirm_remarks(draft):
    apply_selected_remarks(draft, [item.text for item in draft.remark_candidates])
    return draft


def _ready_photon():
    draft = _photon_draft()
    apply_ihi_photon_human_final_fixture(draft)
    _confirm_remarks(draft)
    return draft


def _approve(draft, store=None, **kwargs):
    return approve_quote(
        draft,
        approved_by="弦",
        confirmations=all_confirmations(),
        store=store,
        **kwargs,
    )


def test_non_ready_status_cannot_be_approved():
    draft = _ready_photon()
    draft.status = QuoteDraftStatus.DRAFT

    result = validate_for_approval(draft)

    assert result.can_approve is False
    assert "READY_FOR_APPROVAL" in (result.blocking_reason or "")
    with pytest.raises(QuoteApprovalError, match="READY_FOR_APPROVAL"):
        _approve(draft)


def test_approval_revalidates_and_ignores_ui_ready_flag():
    draft = _photon_draft(tax_rate=0.1)
    draft.status = QuoteDraftStatus.READY_FOR_APPROVAL

    result = validate_for_approval(draft)

    assert result.current_status == QuoteDraftStatus.READY_FOR_APPROVAL
    assert result.can_approve is False
    assert result.critical_warnings
    with pytest.raises(QuoteApprovalError):
        _approve(draft)


def test_critical_warning_blocks_approval():
    draft = _mag_draft(tax_rate=0.1)
    draft.status = QuoteDraftStatus.READY_FOR_APPROVAL

    result = validate_for_approval(draft)

    assert any("Required Component unresolved" in item for item in result.critical_warnings)
    assert result.can_approve is False


def test_margin_warning_can_be_acknowledged():
    draft = _ready_photon()
    apply_minimum_margin_reference(draft, 0.99)
    warning = next(item for item in draft.warnings if "below the entered reference" in item)

    result = validate_for_approval(draft)
    approval, snapshot = _approve(draft, warnings_acknowledged=[warning])

    assert result.can_approve is True
    assert warning in result.regular_warnings
    assert warning not in result.critical_warnings
    assert warning in approval.warnings_acknowledged
    assert snapshot.subtotal_ex_tax_jpy == 7160000
    assert draft.status == QuoteDraftStatus.APPROVED


def test_approved_snapshot_is_created_and_immutable():
    draft = _ready_photon()
    approval, snapshot = _approve(draft)
    original_total = snapshot.total_jpy
    original_rate = snapshot.exchange_rate

    assert approval.status == QuoteDraftStatus.APPROVED
    assert draft.status == QuoteDraftStatus.APPROVED
    assert snapshot.quote_version == 1
    assert snapshot.subtotal_ex_tax_jpy == 7160000
    with pytest.raises((ValidationError, TypeError)):
        snapshot.total_jpy = 1
    draft.exchange_rate = 1
    draft.subtotal_ex_tax_jpy = 1
    assert snapshot.exchange_rate == original_rate
    assert snapshot.total_jpy == original_total


def test_approved_values_do_not_follow_later_master_changes():
    draft = _ready_photon()
    _, snapshot = _approve(draft)
    original = snapshot.manufacturer_price_snapshots[0].manufacturer_dealer_price_usd
    original_final = snapshot.configuration_snapshot[0].final_sales_price_jpy
    original_margin = snapshot.gross_margin_rate

    draft.pricing_context.manufacturer_price_snapshots[0].manufacturer_dealer_price_usd = 1
    draft.configuration_lines[0].manufacturer_price_snapshot.manufacturer_dealer_price_usd = 1
    draft.configuration_lines[0].final_sales_price_jpy = 1
    draft.configuration_lines[0].landed_cost_jpy = 1

    assert snapshot.manufacturer_price_snapshots[0].manufacturer_dealer_price_usd == original
    assert snapshot.configuration_snapshot[0].final_sales_price_jpy == original_final
    assert snapshot.gross_margin_rate == original_margin
    assert original != 1


def test_draft_has_version_and_approved_draft_cannot_be_edited():
    draft = _ready_photon()
    assert draft.quote_version == 1
    _approve(draft)

    with pytest.raises(ValueError, match="Approved drafts cannot be edited"):
        apply_tax_rate(draft, 0.08)


def test_new_version_and_supersede_history():
    store = QuoteApprovalStore()
    first = _ready_photon()
    _, snapshot_v1 = _approve(first, store=store)
    revision = create_revision_draft(snapshot_v1, store=store)
    apply_ihi_photon_human_final_fixture(revision)
    _confirm_remarks(revision)
    _, snapshot_v2 = _approve(revision, store=store)

    stored_v1 = store.snapshots[snapshot_v1.approved_quote_snapshot_id]
    assert revision.quote_version == 2
    assert revision.quote_draft_id != first.quote_draft_id
    assert stored_v1.status == QuoteDraftStatus.SUPERSEDED
    assert first.status == QuoteDraftStatus.SUPERSEDED
    assert snapshot_v2.status == QuoteDraftStatus.APPROVED
    assert stored_v1.total_jpy == snapshot_v1.total_jpy
    assert snapshot_v1.approved_quote_snapshot_id in store.snapshots


def test_internal_transfer_keeps_bundled_component():
    draft = _mag_draft(tax_rate=0.1)
    parent = next(line for line in draft.configuration_lines if line.manufacturer_sku == "2604")
    child = next(line for line in draft.configuration_lines if line.manufacturer_sku == "2601")
    apply_presentation_mode(
        draft,
        child.line_id,
        CustomerPresentationMode.BUNDLED_WITH_PARENT,
        bundled_into_line_id=parent.line_id,
    )
    for line in draft.configuration_lines:
        if line.customer_presentation_status == CustomerPresentationMode.SEPARATE_LINE:
            apply_final_price(draft, line.line_id, FinalPriceStatus.USE_STANDARD_CANDIDATE)
    apply_shipping_final_price(draft, 1000000)
    _confirm_remarks(draft)
    _, snapshot = _approve(draft)
    outputs = generate_quote_outputs(snapshot)
    internal_skus = [row.part_number for row in outputs.internal_transfer.rows]
    spaceone_names = [line.item_name for line in outputs.spaceone_quote.lines]
    mf_names = [row.item_name for row in outputs.moneyforward.rows]

    assert "2601" in internal_skus
    assert child.landed_cost_jpy not in (None, 0)
    assert any(row.part_number == "2601" and row.landed_subtotal_jpy == child.landed_cost_jpy for row in outputs.internal_transfer.rows)
    assert all("2601" not in (name or "") and "POWER BRUSH BASE" not in (name or "") for name in spaceone_names)
    assert all("POWER BRUSH BASE" not in (name or "") for name in mf_names)
    assert outputs.spaceone_quote.total == snapshot.total_jpy
    assert outputs.moneyforward.total_jpy == snapshot.total_jpy


def test_spaceone_and_moneyforward_hide_internal_cost_and_bom():
    draft = _ready_photon()
    _, snapshot = _approve(draft)
    outputs = generate_quote_outputs(snapshot)
    spaceone = outputs.spaceone_quote.model_dump()
    moneyforward = outputs.moneyforward.model_dump()

    assert "dealer_price_usd" not in str(spaceone.keys())
    assert "landed_cost_jpy" not in spaceone
    assert "gross_margin_rate" not in spaceone
    assert "dealer_price_usd" not in moneyforward
    assert all(row.part_number != "2601" for row in outputs.internal_transfer.rows if False)
    assert [line.item_name for line in outputs.spaceone_quote.lines] == [
        "DeepTrekker PHOTON BASE Package",
        "POWER PACK ASY, PHOTON",
        "THICKNESS GUAGE - CYGNUS",
        "THICKNESS GAUGE - CYGNUS INTEGRATION KIT",
        "国際輸送費",
    ]
    assert [row.item_name for row in outputs.moneyforward.rows] == [
        line.item_name for line in outputs.spaceone_quote.lines
    ]
    assert "保険" not in " ".join(line.item_name or "" for line in outputs.spaceone_quote.lines)
    assert outputs.spaceone_quote.lines[-1].item_detail and "カナダ→日本" in outputs.spaceone_quote.lines[-1].item_detail
    assert "\t" in outputs.moneyforward.tsv_preview
    assert outputs.moneyforward.tsv_preview.splitlines()[0] == "品目\t品目詳細\t単価\t数量\t金額\t備考"


def test_ihi_photon_human_final_acceptance_and_aligned_outputs():
    fixture = load_photon_human_final_input()
    draft = _photon_draft()
    apply_human_final_price_inputs(
        draft,
        line_prices_jpy=fixture["line_prices_jpy"],
        shipping_price_jpy=fixture["shipping_price_jpy"],
        tax_rate=fixture["tax_rate"],
    )
    _confirm_remarks(draft)
    standard_sales = 3547764 + 160548 + 2309008 + 371025 + 872742.6
    _, snapshot = _approve(draft)
    outputs = generate_quote_outputs(snapshot)
    landed = snapshot.total_landed_cost_jpy
    expected_margin = round((7160000 - landed) / 7160000, 6)
    standard_margin = round((standard_sales - landed) / standard_sales, 6)

    assert fixture["source"] == "HUMAN_FINAL_PRICE_INPUT"
    assert snapshot.subtotal_ex_tax_jpy == 7160000
    assert snapshot.tax_jpy == 716000
    assert snapshot.total_jpy == 7876000
    assert snapshot.tax_rate == 0.1
    assert snapshot.gross_margin_rate == expected_margin
    assert snapshot.gross_margin_rate != standard_margin
    assert snapshot.gross_margin_rate != pytest.approx(0.3058, abs=0.0002)
    assert outputs.internal_transfer.customer_total_jpy == 7876000
    assert outputs.spaceone_quote.total == 7876000
    assert outputs.moneyforward.total_jpy == 7876000
    assert outputs.internal_transfer.source_approved_quote_snapshot_id == snapshot.approved_quote_snapshot_id
    assert outputs.spaceone_quote.source_approved_quote_snapshot_id == snapshot.approved_quote_snapshot_id
    assert outputs.moneyforward.source_approved_quote_snapshot_id == snapshot.approved_quote_snapshot_id
    assert snapshot.quote_number_candidate
    assert snapshot.official_quote_number is None
    assert all(item.source.value != "GOLDEN_HISTORICAL_SNAPSHOT" or item.selected for item in snapshot.remarks)


def test_internal_only_stays_on_internal_transfer_only():
    draft = _mag_draft(tax_rate=0.1)
    child = next(line for line in draft.configuration_lines if line.manufacturer_sku == "2601")
    apply_presentation_mode(draft, child.line_id, CustomerPresentationMode.INTERNAL_ONLY)
    for line in draft.configuration_lines:
        if line.customer_presentation_status == CustomerPresentationMode.SEPARATE_LINE:
            apply_final_price(draft, line.line_id, FinalPriceStatus.USE_STANDARD_CANDIDATE)
    apply_shipping_final_price(draft, 1000000)
    _confirm_remarks(draft)
    _, snapshot = _approve(draft)
    outputs = generate_quote_outputs(snapshot)

    assert any(row.part_number == "2601" for row in outputs.internal_transfer.rows)
    assert all("POWER BRUSH BASE" not in (line.item_name or "") for line in outputs.spaceone_quote.lines)
    assert all("POWER BRUSH BASE" not in (row.item_name or "") for row in outputs.moneyforward.rows)
    assert snapshot.total_landed_cost_jpy == draft.economics_result.total_landed_cost_jpy


def test_ihi_mag_cannot_be_approved_while_2601_is_undecided():
    draft = _mag_draft(tax_rate=0.1)
    for line in draft.configuration_lines:
        if line.manufacturer_sku != "2601":
            apply_final_price(draft, line.line_id, FinalPriceStatus.USE_STANDARD_CANDIDATE)
    apply_shipping_final_price(draft, 8194)
    result = validate_for_approval(draft)

    assert draft.status == QuoteDraftStatus.REVIEW_REQUIRED
    assert result.can_approve is False
    assert any("2601" in item and "Required Component unresolved" in item for item in result.critical_warnings)
