"""Manual International Shipping Reference Master (standard GLOBAL shipping rates).

Versioned: saving a new rate supersedes the current APPROVED version; rows are never
updated in value or deleted. Reference only: nothing here is applied to quotes automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import math
import sqlite3
from pathlib import Path
from typing import Optional
from uuid import uuid4

from models import (
    DestinationRegion,
    RecordStatus,
    ShippingChargeBasis,
    ShippingRule,
    ShippingScopeType,
    ShippingType,
)
from repositories.postgres import is_postgres
from repositories.sqlite import connect_sqlite, default_sqlite_path, now_iso

STANDARD_GLOBAL_TYPES: tuple[ShippingType, ...] = (
    ShippingType.LARGE_BOX,
    ShippingType.SMALL_BOX,
    ShippingType.PIPE_TREKKER,
)
# The charge basis belongs to the shipping type and is never user-editable.
CHARGE_BASIS_BY_TYPE: dict[ShippingType, ShippingChargeBasis] = {
    ShippingType.LARGE_BOX: ShippingChargeBasis.PER_PARCEL,
    ShippingType.SMALL_BOX: ShippingChargeBasis.PER_PARCEL,
    ShippingType.PIPE_TREKKER: ShippingChargeBasis.PER_ORDER_BASE,
}
SHIPPING_TYPE_LABELS: dict[ShippingType, str] = {
    ShippingType.LARGE_BOX: "Large Box Shipping Globally",
    ShippingType.SMALL_BOX: "Small Box Shipping Globally",
    ShippingType.PIPE_TREKKER: "Pipe Trekker Shipping Globally",
}
SHIPPING_APPLICABILITY_LABELS: dict[ShippingType, str] = {
    ShippingType.LARGE_BOX: "Large Box適用のROV本体・オプション等",
    ShippingType.SMALL_BOX: "Small Box適用のオプション・部品等",
    ShippingType.PIPE_TREKKER: "Pipe Trekker本体注文時",
}
CHARGE_BASIS_LABELS: dict[ShippingChargeBasis, str] = {
    ShippingChargeBasis.PER_PARCEL: "1個口あたり",
    ShippingChargeBasis.PER_ORDER_BASE: "PT本体発注時の基本一式",
}
MANUAL_SOURCE_TYPE = "MANUAL"
SEED_EFFECTIVE_FROM = "2026-10-23"
SEED_SOURCE_REFERENCE = "Manual shipping reference / confirmed as of 2026-10-23"
SEED_CREATED_BY = "system:PORTAL-2A.3 seed"
SEED_RATES: tuple[tuple[str, ShippingType, str], ...] = (
    ("ship-std-global-large_box-20261023-seed", ShippingType.LARGE_BOX, "2922.15"),
    ("ship-std-global-small_box-20261023-seed", ShippingType.SMALL_BOX, "1356.00"),
    ("ship-std-global-pipe_trekker-20261023-seed", ShippingType.PIPE_TREKKER, "8828.15"),
)
_VERSION_STATUSES = (RecordStatus.APPROVED.value, RecordStatus.SUPERSEDED.value)
_COLUMNS = (
    "shipping_rule_id, shipping_type, destination_region, rate_usd, currency, charge_basis, scope_type, "
    "source_type, source_reference, effective_from, status, notes, created_at, created_by"
)


class ShippingRuleRepositoryError(RuntimeError):
    pass


class ShippingRuleValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ShippingRuleVersion:
    rule: ShippingRule
    created_at: str
    created_by: Optional[str]


@dataclass(frozen=True)
class ActiveStandardShippingRate:
    rule: ShippingRule
    created_at: str
    created_by: Optional[str]
    # registered_at: first version of this type; last_updated_at: the current APPROVED version.
    registered_at: str
    last_updated_at: str


def validate_rate_usd(value) -> Decimal:
    """Required, numeric, finite, > 0, at most 2 decimal places."""
    if value is None or isinstance(value, bool) or (isinstance(value, str) and not value.strip()):
        raise ShippingRuleValidationError("USD金額を入力してください。")
    if isinstance(value, float) and not math.isfinite(value):
        raise ShippingRuleValidationError("USD金額が不正です。")
    try:
        amount = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError) as error:
        raise ShippingRuleValidationError("USD金額は数値で入力してください。") from error
    if not amount.is_finite():
        raise ShippingRuleValidationError("USD金額が不正です。")
    if amount <= 0:
        raise ShippingRuleValidationError("USD金額は0より大きい値を入力してください。")
    if amount != amount.quantize(Decimal("0.01")):
        raise ShippingRuleValidationError("USD金額は小数2桁までで入力してください。")
    return amount.quantize(Decimal("0.01"))


def validate_effective_from(value) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as error:
        raise ShippingRuleValidationError("基準日を入力してください。") from error


def _clean_notes(notes: Optional[str]) -> Optional[str]:
    text = (notes or "").strip()
    return text or None


class ShippingRuleRepository:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else default_sqlite_path()
        self._connection = connect_sqlite(self.path)
        self._initialize()

    def close(self) -> None:
        self._connection.close()

    def _initialize(self) -> None:
        # PostgreSQL: schema and seed come from deploy/migrations/20261122_shipping_rules.sql
        # (executescript is a no-op there). Local SQLite bootstraps the same table and seed.
        if is_postgres(self._connection):
            return
        seed_values = ",\n".join(
            "('{id}', '{type}', 'GLOBAL', {rate}, 'USD', '{basis}', 'STANDARD', 'MANUAL', "
            "'{ref}', '{eff}', 'APPROVED', NULL, '{created}', '{by}')".format(
                id=seed_id,
                type=shipping_type.value,
                rate=rate,
                basis=CHARGE_BASIS_BY_TYPE[shipping_type].value,
                ref=SEED_SOURCE_REFERENCE,
                eff=SEED_EFFECTIVE_FROM,
                created=now_iso(),
                by=SEED_CREATED_BY,
            )
            for seed_id, shipping_type, rate in SEED_RATES
        )
        self._connection.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS shipping_rules (
                id INTEGER PRIMARY KEY,
                shipping_rule_id TEXT NOT NULL UNIQUE,
                shipping_type TEXT NOT NULL,
                destination_region TEXT NOT NULL,
                rate_usd NUMERIC NOT NULL,
                currency TEXT NOT NULL DEFAULT 'USD',
                charge_basis TEXT NOT NULL,
                scope_type TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_reference TEXT,
                effective_from TEXT NOT NULL,
                status TEXT NOT NULL,
                notes TEXT,
                created_at TEXT NOT NULL,
                created_by TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_shipping_rules_type ON shipping_rules(shipping_type);
            CREATE INDEX IF NOT EXISTS idx_shipping_rules_region ON shipping_rules(destination_region);
            CREATE INDEX IF NOT EXISTS idx_shipping_rules_scope ON shipping_rules(scope_type);
            CREATE INDEX IF NOT EXISTS idx_shipping_rules_status ON shipping_rules(status);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_shipping_rules_one_approved
                ON shipping_rules(shipping_type, destination_region, scope_type) WHERE status = 'APPROVED';
            INSERT OR IGNORE INTO shipping_rules ({_COLUMNS}) VALUES
            {seed_values};
            """
        )
        self._connection.commit()

    # ---- reads -------------------------------------------------------------------------------

    def _version(self, row) -> ShippingRuleVersion:
        effective = row["effective_from"]
        rule = ShippingRule(
            shipping_rule_id=row["shipping_rule_id"],
            shipping_type=ShippingType(row["shipping_type"]),
            destination_region=DestinationRegion(row["destination_region"]),
            rate_usd=float(row["rate_usd"]),
            currency=row["currency"],
            charge_basis=ShippingChargeBasis(row["charge_basis"]),
            scope_type=ShippingScopeType(row["scope_type"]),
            source_type=row["source_type"],
            source_reference=row["source_reference"],
            effective_from=datetime.fromisoformat(str(effective)) if effective else None,
            status=RecordStatus(row["status"]),
            notes=row["notes"],
        )
        return ShippingRuleVersion(rule=rule, created_at=row["created_at"], created_by=row["created_by"])

    def _registered_at(self, shipping_type: ShippingType) -> Optional[str]:
        row = self._connection.execute(
            """
            SELECT MIN(created_at) AS registered_at FROM shipping_rules
            WHERE shipping_type = ? AND destination_region = ? AND scope_type = ? AND status IN (?, ?)
            """,
            (shipping_type.value, DestinationRegion.GLOBAL.value, ShippingScopeType.STANDARD.value, *_VERSION_STATUSES),
        ).fetchone()
        return row["registered_at"] if row is not None else None

    def get_active_standard_global(self, shipping_type: ShippingType) -> Optional[ActiveStandardShippingRate]:
        shipping_type = ShippingType(shipping_type)
        try:
            row = self._connection.execute(
                f"""
                SELECT {_COLUMNS} FROM shipping_rules
                WHERE shipping_type = ? AND destination_region = ? AND scope_type = ? AND status = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (
                    shipping_type.value,
                    DestinationRegion.GLOBAL.value,
                    ShippingScopeType.STANDARD.value,
                    RecordStatus.APPROVED.value,
                ),
            ).fetchone()
            if row is None:
                return None
            version = self._version(row)
            registered_at = self._registered_at(shipping_type) or version.created_at
        except sqlite3.Error as error:
            raise ShippingRuleRepositoryError(f"Failed to read shipping rules: {error}") from error
        return ActiveStandardShippingRate(
            rule=version.rule,
            created_at=version.created_at,
            created_by=version.created_by,
            registered_at=registered_at,
            last_updated_at=version.created_at,
        )

    def list_active_standard_global(self) -> list[ActiveStandardShippingRate]:
        """Current APPROVED STANDARD / GLOBAL rate per type, in fixed type order. Missing types are omitted."""
        result = []
        for shipping_type in STANDARD_GLOBAL_TYPES:
            active = self.get_active_standard_global(shipping_type)
            if active is not None:
                result.append(active)
        return result

    def list_history(self, shipping_type: Optional[ShippingType] = None) -> list[ShippingRuleVersion]:
        """All STANDARD / GLOBAL versions, newest first."""
        clause = "destination_region = ? AND scope_type = ?"
        params: list = [DestinationRegion.GLOBAL.value, ShippingScopeType.STANDARD.value]
        if shipping_type is not None:
            clause += " AND shipping_type = ?"
            params.append(ShippingType(shipping_type).value)
        try:
            rows = self._connection.execute(
                f"SELECT {_COLUMNS} FROM shipping_rules WHERE {clause} ORDER BY created_at DESC, id DESC",
                tuple(params),
            ).fetchall()
        except sqlite3.Error as error:
            raise ShippingRuleRepositoryError(f"Failed to read shipping rule history: {error}") from error
        return [self._version(row) for row in rows]

    # ---- writes (explicit human action only) -------------------------------------------------

    def save_standard_global_rate(
        self,
        shipping_type: ShippingType,
        *,
        rate_usd,
        effective_from,
        notes: Optional[str] = None,
        created_by: Optional[str] = None,
        source_reference: Optional[str] = None,
    ) -> Optional[ActiveStandardShippingRate]:
        """Save a new APPROVED version and supersede the previous one.

        Returns None (and writes nothing) when rate, effective date and notes are unchanged.
        """
        shipping_type = ShippingType(shipping_type)
        if shipping_type not in CHARGE_BASIS_BY_TYPE:
            raise ShippingRuleValidationError("この区分は標準国際輸送費として登録できません。")
        amount = validate_rate_usd(rate_usd)
        effective = validate_effective_from(effective_from)
        cleaned_notes = _clean_notes(notes)
        current = self.get_active_standard_global(shipping_type)
        if (
            current is not None
            and Decimal(str(current.rule.rate_usd)).quantize(Decimal("0.01")) == amount
            and current.rule.effective_from is not None
            and current.rule.effective_from.date().isoformat() == effective
            and _clean_notes(current.rule.notes) == cleaned_notes
        ):
            return None
        new_id = f"ship-std-global-{shipping_type.value.lower()}-{uuid4().hex[:12]}"
        try:
            with self._connection:
                if current is not None:
                    self._connection.execute(
                        "UPDATE shipping_rules SET status = ? WHERE shipping_rule_id = ? AND status = ?",
                        (RecordStatus.SUPERSEDED.value, current.rule.shipping_rule_id, RecordStatus.APPROVED.value),
                    )
                self._connection.execute(
                    f"INSERT INTO shipping_rules ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        new_id,
                        shipping_type.value,
                        DestinationRegion.GLOBAL.value,
                        str(amount),
                        "USD",
                        CHARGE_BASIS_BY_TYPE[shipping_type].value,
                        ShippingScopeType.STANDARD.value,
                        MANUAL_SOURCE_TYPE,
                        source_reference or "Manual update in 価格マスター管理",
                        effective,
                        RecordStatus.APPROVED.value,
                        cleaned_notes,
                        now_iso(),
                        created_by,
                    ),
                )
        except sqlite3.Error as error:
            raise ShippingRuleRepositoryError(f"Failed to save shipping rule: {error}") from error
        return self.get_active_standard_global(shipping_type)
