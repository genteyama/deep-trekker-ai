from agents.quote_control_agent import import_price_book
from agents.sku_link import (
    build_sku_link_preview,
    create_quote_price_snapshot,
    get_current_manufacturer_values,
    try_manual_link,
)
from models import LinkStatus, MatchStatus, SpaceOneMasterItem, SpaceOneValues
from parsers.spaceone_master_parser import parse_spaceone_master
from tests.price_book_fixtures import manufacturer_books_for_reconciliation, spaceone_master_book


def _load():
    dt40_file, pt30_file = manufacturer_books_for_reconciliation()
    dt40 = import_price_book(dt40_file, source_price_book="DT40", version="2026-09")
    pt30 = import_price_book(pt30_file, source_price_book="PT30", version="2026-09")
    spaceone = parse_spaceone_master(spaceone_master_book(), source_name="SO_MASTER")
    preview = build_sku_link_preview(spaceone.items, dt40, pt30)
    return dt40, pt30, spaceone, preview


def _item(preview, sku=None, name=None, status=None):
    for item in preview.items:
        if sku and item.spaceone_sku == sku:
            return item
        if name and item.name_ja and name in item.name_ja:
            return item
        if status and item.link.link_status == status and item.link.manufacturer_sku is None:
            return item
    raise AssertionError("item not found")


def test_exact_mismatch_and_missing_can_auto_link():
    _, _, spaceone, preview = _load()
    exact = _item(preview, sku="9680-BASE")
    mismatch = _item(preview, sku="11490")
    missing = _item(preview, sku="7851-PHOTON")

    assert exact.match_status == MatchStatus.EXACT_MATCH
    assert exact.link.link_status == LinkStatus.AUTO_LINKED
    assert exact.link.manufacturer_sku == "9680-BASE"
    assert mismatch.match_status == MatchStatus.PRICE_MISMATCH
    assert mismatch.link.link_status == LinkStatus.AUTO_LINKED
    assert mismatch.link.manufacturer_sku == "11490"
    assert mismatch.legacy.legacy_manufacturer_dealer_price == 68701.1
    assert mismatch.current_values.dealer_price_usd == 1361.5
    assert mismatch.price_difference.dealer_price_delta == -67339.6
    assert missing.match_status == MatchStatus.PRICE_MISSING
    assert missing.link.link_status == LinkStatus.AUTO_LINKED
    assert spaceone.items[0].values.sales_price == exact.spaceone_sales_price == 3540000


def test_uncertain_skus_stay_review_required_and_similar_sku_is_not_guessed():
    _, _, _, preview = _load()
    typo = _item(preview, sku="9680-EXPEET")
    missing = _item(preview, sku="MISSING-SKU")
    obsolete = _item(preview, sku="7511-SC-BASE")
    conflict = _item(preview, sku="CONFLICT-1")
    invalid = next(item for item in preview.items if item.match_status == MatchStatus.PART_NUMBER_INVALID)
    shipping = next(item for item in preview.items if "輸送費" in (item.name_ja or ""))

    assert typo.link.link_status == LinkStatus.REVIEW_REQUIRED
    assert typo.link.manufacturer_sku is None
    assert missing.link.link_status == LinkStatus.REVIEW_REQUIRED
    assert obsolete.link.link_status == LinkStatus.REVIEW_REQUIRED
    assert conflict.link.link_status == LinkStatus.REVIEW_REQUIRED
    assert invalid.link.link_status == LinkStatus.REVIEW_REQUIRED
    assert shipping.link.link_status == LinkStatus.NO_LINK_REQUIRED
    assert all(item.link.manufacturer_sku != "9680-EXPERT" for item in preview.items)


def test_multiple_spaceone_rows_can_share_the_same_manufacturer_sku():
    _, _, _, preview = _load()
    rows = [item for item in preview.items if item.spaceone_sku == "5608"]

    assert len(rows) == 2
    assert {item.link.link_status for item in rows} == {LinkStatus.AUTO_LINKED}
    assert {item.link.manufacturer_sku for item in rows} == {"5608"}


def test_manual_link_accepts_existing_sku_and_rejects_invalid_ones():
    dt40, pt30, spaceone, preview = _load()
    typo = _item(preview, sku="9680-EXPEET")
    sales_before = [item.values.sales_price for item in spaceone.items]

    accepted = try_manual_link(preview, typo.spaceone_item_id, "9680-EXPERT")
    assert accepted.accepted is False
    assert _item(accepted.preview, sku="9680-EXPEET").link.manufacturer_sku is None
    unknown = try_manual_link(preview, typo.spaceone_item_id, "NOT-A-REAL-SKU")
    assert unknown.accepted is False
    conflict = try_manual_link(preview, typo.spaceone_item_id, "CONFLICT-1")
    assert conflict.accepted is False
    obsolete = try_manual_link(preview, typo.spaceone_item_id, "7511-SC-BASE")
    assert obsolete.accepted is False
    assert _item(obsolete.preview, sku="9680-EXPEET").link.link_status == LinkStatus.REVIEW_REQUIRED
    linked = try_manual_link(preview, typo.spaceone_item_id, "9680-BASE")
    assert linked.accepted is True
    item = _item(linked.preview, sku="9680-EXPEET")
    assert item.link.link_status == LinkStatus.MANUALLY_LINKED
    assert item.link.manufacturer_sku == "9680-BASE"
    assert item.current_values.msrp_usd == 17391
    assert [row.values.sales_price for row in spaceone.items] == sales_before


def test_current_values_come_from_manufacturer_master_not_legacy():
    dt40, pt30, _, preview = _load()
    current = get_current_manufacturer_values("11490", list(dt40.candidates) + list(pt30.candidates))
    mismatch = _item(preview, sku="11490")

    assert current.msrp_usd == 1945
    assert current.dealer_price_usd == 1361.5
    assert mismatch.legacy.legacy_manufacturer_msrp == 77000
    assert mismatch.current_values.msrp_usd != mismatch.legacy.legacy_manufacturer_msrp
    assert mismatch.legacy.legacy_reference.cell == "D40"
    assert get_current_manufacturer_values("CONFLICT-1", list(dt40.candidates) + list(pt30.candidates)) is None


def test_quote_snapshot_stays_fixed_after_current_master_changes():
    dt40, pt30, _, _ = _load()
    candidates = list(dt40.candidates) + list(pt30.candidates)
    snapshot = create_quote_price_snapshot(
        "11490",
        candidates,
        snapshot_id="snap-001",
        price_book_version="2026-09",
        source_reference="DT40",
    )
    target = next(item for item in candidates if item.sku == "11490")
    original_msrp = snapshot.manufacturer_msrp_usd
    target.msrp_usd = 1
    target.dealer_price_usd = 1

    assert snapshot.sku == "11490"
    assert snapshot.manufacturer_msrp_usd == original_msrp == 1945
    assert snapshot.manufacturer_dealer_price_usd == 1361.5
    assert snapshot.price_book_version == "2026-09"
    later = get_current_manufacturer_values("11490", candidates)
    assert later.msrp_usd == 1
    assert snapshot.manufacturer_msrp_usd != later.msrp_usd


def test_empty_sku_is_review_required():
    dt40, pt30, spaceone, _ = _load()
    empty = SpaceOneMasterItem(
        spaceone_item_id="so-empty",
        source_sheet="PHOTON",
        source_row=99,
        spaceone_sku=None,
        normalized_sku=None,
        values=SpaceOneValues(name_ja="SKU空の商品"),
    )
    preview = build_sku_link_preview(list(spaceone.items) + [empty], dt40, pt30)
    item = next(row for row in preview.items if row.spaceone_item_id == "so-empty")

    assert item.link.link_status == LinkStatus.REVIEW_REQUIRED
    assert item.link.manufacturer_sku is None
