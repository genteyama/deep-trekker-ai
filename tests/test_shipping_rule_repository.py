from datetime import date
import math

import pytest

from models import (
    DestinationRegion,
    RecordStatus,
    ShippingChargeBasis,
    ShippingScopeType,
    ShippingType,
)
from repositories.shipping_rule_repository import (
    CHARGE_BASIS_BY_TYPE,
    SEED_CREATED_BY,
    SEED_SOURCE_REFERENCE,
    ShippingRuleRepository,
    ShippingRuleValidationError,
    validate_rate_usd,
)
from repositories.sqlite import now_iso


@pytest.fixture
def repository(tmp_path):
    return ShippingRuleRepository(tmp_path / "shipping.sqlite3")


def _insert_raw(repository, shipping_rule_id, *, region="GLOBAL", scope="STANDARD", status="APPROVED", rate="1.00"):
    repository._connection.execute(
        """
        INSERT INTO shipping_rules (shipping_rule_id, shipping_type, destination_region, rate_usd, currency,
            charge_basis, scope_type, source_type, source_reference, effective_from, status, notes, created_at, created_by)
        VALUES (?, 'LARGE_BOX', ?, ?, 'USD', 'PER_PARCEL', ?, 'MANUAL', NULL, '2026-01-01', ?, NULL, ?, NULL)
        """,
        (shipping_rule_id, region, rate, scope, status, now_iso()),
    )
    repository._connection.commit()


def test_initial_seed_has_three_standard_global_rates(repository):
    active = {item.rule.shipping_type: item for item in repository.list_active_standard_global()}
    assert list(active) == [ShippingType.LARGE_BOX, ShippingType.SMALL_BOX, ShippingType.PIPE_TREKKER]
    assert active[ShippingType.LARGE_BOX].rule.rate_usd == pytest.approx(2922.15)
    assert active[ShippingType.SMALL_BOX].rule.rate_usd == pytest.approx(1356.00)
    assert active[ShippingType.PIPE_TREKKER].rule.rate_usd == pytest.approx(8828.15)
    for item in active.values():
        rule = item.rule
        assert rule.status == RecordStatus.APPROVED
        assert rule.scope_type == ShippingScopeType.STANDARD
        assert rule.destination_region == DestinationRegion.GLOBAL
        assert rule.source_type == "MANUAL"
        assert rule.source_reference == SEED_SOURCE_REFERENCE
        assert rule.currency == "USD"
        assert rule.effective_from.date() == date(2026, 10, 23)
        assert item.created_by == SEED_CREATED_BY


def test_seed_is_idempotent(tmp_path):
    path = tmp_path / "shipping.sqlite3"
    ShippingRuleRepository(path)
    again = ShippingRuleRepository(path)
    assert len(again.list_history()) == 3


def test_charge_basis_per_type(repository):
    active = {item.rule.shipping_type: item.rule.charge_basis for item in repository.list_active_standard_global()}
    assert active[ShippingType.LARGE_BOX] == ShippingChargeBasis.PER_PARCEL
    assert active[ShippingType.SMALL_BOX] == ShippingChargeBasis.PER_PARCEL
    assert active[ShippingType.PIPE_TREKKER] == ShippingChargeBasis.PER_ORDER_BASE
    assert CHARGE_BASIS_BY_TYPE[ShippingType.PIPE_TREKKER] == ShippingChargeBasis.PER_ORDER_BASE


def test_first_save_into_empty_type_and_get_active(repository):
    repository._connection.execute("DELETE FROM shipping_rules WHERE shipping_type = 'SMALL_BOX'")
    repository._connection.commit()
    assert repository.get_active_standard_global(ShippingType.SMALL_BOX) is None

    saved = repository.save_standard_global_rate(
        ShippingType.SMALL_BOX, rate_usd=1400, effective_from=date(2026, 12, 1), notes="first", created_by="a@example.com"
    )
    assert saved.rule.rate_usd == pytest.approx(1400.00)
    assert saved.rule.charge_basis == ShippingChargeBasis.PER_PARCEL
    assert saved.rule.status == RecordStatus.APPROVED
    assert saved.created_by == "a@example.com"
    assert saved.registered_at == saved.last_updated_at == saved.created_at
    assert repository.get_active_standard_global(ShippingType.SMALL_BOX).rule.shipping_rule_id == saved.rule.shipping_rule_id


def test_update_supersedes_previous_and_keeps_history(repository, monkeypatch):
    import repositories.shipping_rule_repository as module

    before = repository.get_active_standard_global(ShippingType.LARGE_BOX)
    assert before.registered_at == before.last_updated_at

    monkeypatch.setattr(module, "now_iso", lambda: "2027-01-05T03:00:00+00:00")
    updated = repository.save_standard_global_rate(
        ShippingType.LARGE_BOX, rate_usd="3100.00", effective_from="2027-01-01", notes="price change", created_by="b@example.com"
    )
    assert updated.rule.rate_usd == pytest.approx(3100.00)
    # 登録日時 stays at the first version; 最終更新日時 is the new version's created_at.
    assert updated.registered_at == before.registered_at
    assert updated.last_updated_at == "2027-01-05T03:00:00+00:00" == updated.created_at
    # 基準日 is independent of created_at.
    assert updated.rule.effective_from.date() == date(2027, 1, 1)

    history = repository.list_history(ShippingType.LARGE_BOX)
    assert [(item.rule.status, item.rule.rate_usd) for item in history] == [
        (RecordStatus.APPROVED, pytest.approx(3100.00)),
        (RecordStatus.SUPERSEDED, pytest.approx(2922.15)),
    ]
    approved = [item for item in repository.list_history() if item.rule.status == RecordStatus.APPROVED]
    assert len(approved) == 3


def test_types_are_independent(repository):
    repository.save_standard_global_rate(ShippingType.PIPE_TREKKER, rate_usd=9000, effective_from="2027-01-01")
    assert repository.get_active_standard_global(ShippingType.PIPE_TREKKER).rule.rate_usd == pytest.approx(9000)
    assert repository.get_active_standard_global(ShippingType.LARGE_BOX).rule.rate_usd == pytest.approx(2922.15)
    assert repository.get_active_standard_global(ShippingType.SMALL_BOX).rule.rate_usd == pytest.approx(1356.00)
    assert len(repository.list_history(ShippingType.LARGE_BOX)) == 1
    assert len(repository.list_history(ShippingType.PIPE_TREKKER)) == 2


def test_only_global_standard_rows_are_returned(repository):
    _insert_raw(repository, "case-specific", scope="CASE_SPECIFIC", rate="620.00")
    _insert_raw(repository, "usa-only", region="USA", rate="100.00")
    active = repository.get_active_standard_global(ShippingType.LARGE_BOX)
    assert active.rule.rate_usd == pytest.approx(2922.15)
    ids = {item.rule.shipping_rule_id for item in repository.list_history()}
    assert "case-specific" not in ids and "usa-only" not in ids


def test_same_content_creates_no_new_version(repository):
    current = repository.get_active_standard_global(ShippingType.SMALL_BOX)
    result = repository.save_standard_global_rate(ShippingType.SMALL_BOX, rate_usd=1356.0, effective_from="2026-10-23", notes="  ")
    assert result is None
    assert len(repository.list_history(ShippingType.SMALL_BOX)) == 1
    assert repository.get_active_standard_global(ShippingType.SMALL_BOX).rule.shipping_rule_id == current.rule.shipping_rule_id


@pytest.mark.parametrize("value", [0, -1, "0", "-0.01"])
def test_rejects_zero_or_negative(value):
    with pytest.raises(ShippingRuleValidationError):
        validate_rate_usd(value)


@pytest.mark.parametrize("value", [None, "", "abc", "12a", True, [1]])
def test_rejects_non_numeric(value):
    with pytest.raises(ShippingRuleValidationError):
        validate_rate_usd(value)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, "NaN", "Infinity"])
def test_rejects_nan_and_infinity(value):
    with pytest.raises(ShippingRuleValidationError):
        validate_rate_usd(value)


def test_accepts_up_to_two_decimals_and_rejects_more():
    assert str(validate_rate_usd(2922.15)) == "2922.15"
    assert str(validate_rate_usd("1356")) == "1356.00"
    assert str(validate_rate_usd("8,828.15")) == "8828.15"
    with pytest.raises(ShippingRuleValidationError):
        validate_rate_usd("10.001")


def test_invalid_save_writes_nothing(repository):
    with pytest.raises(ShippingRuleValidationError):
        repository.save_standard_global_rate(ShippingType.LARGE_BOX, rate_usd=0, effective_from="2027-01-01")
    with pytest.raises(ShippingRuleValidationError):
        repository.save_standard_global_rate(ShippingType.LARGE_BOX, rate_usd=10, effective_from="")
    with pytest.raises(ShippingRuleValidationError):
        repository.save_standard_global_rate(ShippingType.CUSTOM, rate_usd=10, effective_from="2027-01-01")
    assert len(repository.list_history()) == 3


def test_admin_tokyo_display_format():
    from ui.price_master import format_imported_at

    assert format_imported_at("2026-11-22T05:34:00+00:00") == "2026-11-22 14:34"
