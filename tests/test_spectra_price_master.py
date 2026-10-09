from agents.landed_cost import calculate_landed_cost_scenario
from agents.master_reconciliation import collect_manufacturer_candidates, get_manufacturer_price_by_sku
from agents.online_price_master import OnlinePriceReviewStatus, review_manufacturer_online_price
from agents.price_master import (
    MANUFACTURER_MASTERS,
    ONLINE_SYNC_MASTERS,
    active_price_books,
    attach_price_master_provenance,
    get_active_master,
    import_price_master,
)
from agents.quote_approval import validate_for_approval
from agents.quote_builder import build_quote_draft
from agents.sku_link import create_quote_price_snapshot
from models import (
    InsuranceMode,
    PriceMasterImportStatus,
    PriceMasterType,
    PriceSourceType,
    QuoteDraftStatus,
)
from parsers.spectra_gold_parser import parse_spectra_gold
from repositories.sqlite_price_master_repository import SqlitePriceMasterRepository
from tests.price_book_fixtures import build_workbook
from tests.test_price_master_ui import _open_quote_page, _texts
from tests.test_price_source_safety import _policy


def _spectra_rows(*, first_msrp=1000, first_gold=700):
    return [
        ["Manufacturer’s Suggested Retail Price (USD)"],
        ["SPECTRA Dealer 30% Discount"],
        [None, "Part Number", "Description", "Spectra", "Gold", "Notes:"],
        [None, "SPECTRA0001", "Spectra One", first_msrp, first_gold, "priced"],
        [None, "SPECTRA001", "Similar but distinct", 900, 630, None],
        [None, "MISSING-MSRP", "Missing MSRP", None, 0, "manual quote"],
        [None, "MISSING-GOLD", "Missing Gold", 500, None, "manual quote"],
        [None, "ZERO-BOTH", "Explicit zero", 0, 0, "explicit values"],
        [None, "CONTACT-1", "Contact product", "TBD", "CONTACT PRODUCT TO QUOTE", "ask manufacturer"],
    ]


def spectra_workbook(*, first_msrp=1000, first_gold=700):
    return build_workbook(
        {
            "SPECTRA": _spectra_rows(first_msrp=first_msrp, first_gold=first_gold),
            "ONYX": [
                ["Part Number", "Description", "MSRP", "SP_GOLD"],
                ["ONYX-1", "Onyx must not enter SPECTRA", 9999, 6999.3],
            ],
            "PHOTON": [
                ["Part Number", "Description", "MSRP", "Gold"],
                ["PHOTON-1", "Photon must not enter SPECTRA", 2000, 1400],
            ],
        }
    )


def _import_spectra(data=None, name="SPECTRA GOLD.xlsx"):
    outcome = import_price_master(
        PriceMasterType.SPECTRA_GOLD,
        name,
        data or spectra_workbook().getvalue(),
    )
    assert outcome.status == PriceMasterImportStatus.ACTIVATED
    return outcome.record


def test_spectra_gold_is_a_manual_manufacturer_price_master_not_online_sync():
    assert PriceMasterType.SPECTRA_GOLD.value == "SPECTRA_GOLD"
    assert PriceMasterType.SPECTRA_GOLD in MANUFACTURER_MASTERS
    assert PriceMasterType.SPECTRA_GOLD not in ONLINE_SYNC_MASTERS

    review = review_manufacturer_online_price(PriceMasterType.SPECTRA_GOLD)

    assert review.status == OnlinePriceReviewStatus.NOT_CONFIGURED


def test_valid_spectra_manual_upload_activates_with_validation_summary():
    record = _import_spectra()

    assert record.active is True
    assert record.validation_summary == {
        "sku_count": 6,
        "priced_sku_count": 3,
        "manual_review_count": 3,
        "sheet_count": 1,
        "error_count": 0,
        "warning_count": 3,
    }
    assert get_active_master(PriceMasterType.SPECTRA_GOLD).record.import_id == record.import_id


def test_spectra_sheet_is_required():
    data = build_workbook(
        {
            "ONYX": [
                ["Manufacturer’s Suggested Retail Price (USD)"],
                ["SPECTRA Dealer 30% Discount"],
                ["Part Number", "Description", "Spectra", "Gold"],
                ["ONYX-1", "Wrong sheet", 100, 70],
            ]
        }
    ).getvalue()

    outcome = import_price_master(PriceMasterType.SPECTRA_GOLD, "wrong.xlsx", data)

    assert outcome.status == PriceMasterImportStatus.REJECTED
    assert outcome.reason_code == "SPECTRA_SHEET_MISSING"


def test_spectra_and_gold_columns_are_both_required():
    for missing in ("Spectra", "Gold"):
        headers = ["Part Number", "Description", "Spectra", "Gold"]
        headers.remove(missing)
        data = build_workbook(
            {
                "SPECTRA": [
                    ["Manufacturer’s Suggested Retail Price (USD)"],
                    ["SPECTRA Dealer 30% Discount"],
                    headers,
                    ["S-1", "Missing column", 100],
                ]
            }
        ).getvalue()

        outcome = import_price_master(PriceMasterType.SPECTRA_GOLD, "missing.xlsx", data)

        assert outcome.status == PriceMasterImportStatus.REJECTED
        assert outcome.reason_code == "SPECTRA_COLUMNS_MISSING"


def test_spectra_source_identity_markers_are_required():
    data = build_workbook(
        {
            "SPECTRA": [
                ["Part Number", "Description", "Spectra", "Gold"],
                ["S-1", "Looks similar only", 100, 70],
            ]
        }
    ).getvalue()

    outcome = import_price_master(PriceMasterType.SPECTRA_GOLD, "unrelated.xlsx", data)

    assert outcome.status == PriceMasterImportStatus.REJECTED
    assert outcome.reason_code == "SPECTRA_IDENTITY_UNCONFIRMED"


def test_spectra_column_is_msrp_and_gold_is_dealer_without_inference():
    result = parse_spectra_gold(spectra_workbook(first_msrp=1234, first_gold=456))
    candidate = get_manufacturer_price_by_sku("SPECTRA0001", result.candidates)

    assert candidate.msrp_usd == 1234
    assert candidate.dealer_price_usd == 456
    assert candidate.dealer_price_usd != 1234 * 0.7
    assert candidate.msrp_usd != round(456 / 0.7, 2)


def test_exact_sku_lookup_does_not_use_similar_or_unknown_skus():
    candidates = parse_spectra_gold(spectra_workbook()).candidates

    assert get_manufacturer_price_by_sku("SPECTRA0001", candidates).sku == "SPECTRA0001"
    assert get_manufacturer_price_by_sku("SPECTRA001", candidates).sku == "SPECTRA001"
    assert get_manufacturer_price_by_sku("SPECTRA000", candidates) is None
    assert get_manufacturer_price_by_sku("spectra0001", candidates) is None


def test_missing_price_is_not_promoted_to_zero_cost_but_explicit_zero_pair_is_official():
    result = parse_spectra_gold(spectra_workbook())
    candidates = result.candidates
    missing = get_manufacturer_price_by_sku("MISSING-MSRP", candidates)
    zero = get_manufacturer_price_by_sku("ZERO-BOTH", candidates)
    missing_occurrence = missing.occurrences[0]

    assert missing.msrp_usd is None
    assert missing.dealer_price_usd is None
    assert missing_occurrence.msrp_usd is None
    assert missing_occurrence.dealer_price_usd == 0
    assert zero.msrp_usd == 0
    assert zero.dealer_price_usd == 0
    assert create_quote_price_snapshot(
        "MISSING-MSRP", candidates, snapshot_id="missing"
    ).price_source_type == PriceSourceType.UNKNOWN
    assert create_quote_price_snapshot(
        "ZERO-BOTH", candidates, snapshot_id="zero"
    ).price_source_type == PriceSourceType.OFFICIAL_PRICE_BOOK


def test_unpriced_spectra_line_has_no_landed_cost_and_blocks_approval():
    candidates = parse_spectra_gold(spectra_workbook()).candidates
    scenario, _ = calculate_landed_cost_scenario(
        scenario_id="spectra-missing",
        case_id="SPECTRA",
        name="SPECTRA",
        exchange_rate=160,
        policy=_policy(),
        product_inputs=[{"sku": "MISSING-MSRP", "quantity": 1}],
        shipping_lines=[],
        insurance_mode=InsuranceMode.PERCENTAGE,
        domestic_shipping_jpy=0,
        price_book_candidates=candidates,
    )
    draft = build_quote_draft(
        quote_draft_id="spectra-missing",
        case_id="SPECTRA",
        customer="x",
        title="SPECTRA",
        configuration_name="SPECTRA",
        landed_scenario=scenario,
        sales_candidates=[],
        presentation={
            "product_presentations": [
                {"sku": "MISSING-MSRP", "presentation_mode": "SEPARATE_LINE"}
            ]
        },
    )

    line = draft.configuration_lines[0]
    assert line.dealer_price_usd is None
    assert line.dealer_cost_jpy is None
    assert line.landed_cost_jpy is None
    assert line.standard_sales_price_candidate_jpy is None
    assert draft.status == QuoteDraftStatus.REVIEW_REQUIRED
    assert validate_for_approval(draft).can_approve is False


def test_only_spectra_sheet_enters_spectra_master():
    result = parse_spectra_gold(spectra_workbook())
    skus = {item.sku for item in result.candidates}

    assert "SPECTRA0001" in skus
    assert "ONYX-1" not in skus
    assert "PHOTON-1" not in skus
    assert {item.source_sheet for item in result.occurrences} == {"SPECTRA"}


def test_new_valid_snapshot_activates_and_invalid_upload_preserves_it():
    first = _import_spectra()
    second = _import_spectra(spectra_workbook(first_gold=701).getvalue(), "SPECTRA GOLD v2.xlsx")

    invalid = build_workbook(
        {"SPECTRA": [["Part Number", "Description", "Spectra", "Gold"], ["S-1", "No markers", 1, 1]]}
    ).getvalue()
    rejected = import_price_master(PriceMasterType.SPECTRA_GOLD, "invalid.xlsx", invalid)

    history = SqlitePriceMasterRepository().list_imports(PriceMasterType.SPECTRA_GOLD)
    assert second.import_id != first.import_id
    assert len(history) == 2
    assert next(item for item in history if item.import_id == first.import_id).active is False
    assert rejected.status == PriceMasterImportStatus.REJECTED
    assert get_active_master(PriceMasterType.SPECTRA_GOLD).record.import_id == second.import_id


def test_active_spectra_master_flows_to_quote_with_provenance_and_no_inferred_sales_price():
    record = _import_spectra()
    masters = active_price_books()
    assert [item.record.master_type for item in masters] == [PriceMasterType.SPECTRA_GOLD]
    candidates = collect_manufacturer_candidates(*[item.book for item in masters])
    scenario, _ = calculate_landed_cost_scenario(
        scenario_id="spectra-priced",
        case_id="SPECTRA",
        name="SPECTRA",
        exchange_rate=160,
        policy=_policy(),
        product_inputs=[{"sku": "SPECTRA0001", "quantity": 1}],
        shipping_lines=[],
        insurance_mode=InsuranceMode.PERCENTAGE,
        domestic_shipping_jpy=0,
        price_book_candidates=candidates,
    )
    draft = build_quote_draft(
        quote_draft_id="spectra-priced",
        case_id="SPECTRA",
        customer="x",
        title="SPECTRA",
        configuration_name="SPECTRA",
        landed_scenario=scenario,
        sales_candidates=[],
        presentation={
            "product_presentations": [
                {"sku": "SPECTRA0001", "presentation_mode": "SEPARATE_LINE"}
            ]
        },
    )
    attach_price_master_provenance(draft, [item.record for item in masters])

    line = draft.configuration_lines[0]
    snapshot = line.manufacturer_price_snapshot
    assert snapshot.price_source_type == PriceSourceType.OFFICIAL_PRICE_BOOK
    assert snapshot.price_book == "SPECTRA_GOLD"
    assert snapshot.manufacturer_msrp_usd == 1000
    assert snapshot.manufacturer_dealer_price_usd == 700
    assert snapshot.price_master_import_id == record.import_id
    assert snapshot.price_master_sha256 == record.sha256
    assert snapshot.price_master_filename == "SPECTRA GOLD.xlsx"
    assert line.dealer_cost_jpy == 112000
    assert line.standard_sales_price_candidate_jpy is None
    assert draft.status == QuoteDraftStatus.REVIEW_REQUIRED
    assert validate_for_approval(draft).can_approve is False


def test_price_master_ui_shows_manual_spectra_section_and_paused_online_label():
    at = _open_quote_page()
    texts = _texts(at)

    assert "SPECTRA GOLD（手動アップロード）" in texts
    assert "SPECTRA GOLD — オンライン連携保留" in texts
    assert "現在はExcel手動アップロードで価格マスターを運用しています" in texts
    assert any(item.key == "price_master_import_SPECTRA_GOLD" for item in at.button)
