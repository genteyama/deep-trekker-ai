from datetime import datetime, timezone
from typing import Optional

from data.update_inbox.dealer_update_september_2026 import (
    DEALER_UPDATE_DATE,
    DEALER_UPDATE_REFERENCE,
    DEALER_UPDATE_TITLE,
    DEFAULT_SHIPPING_FLAGS,
    LEAD_TIMES,
    MATCH_HINTS,
    PRODUCT_SPECS,
    SHIPPING_NOTES,
    STANDARD_SHIPPING_RATES,
)
from models import (
    RecordStatus,
    ShippingRule,
    ShippingScopeType,
    ShippingType,
    UpdateCandidate,
    UpdateCategory,
    UpdateConfidence,
    UpdateSource,
    UpdateSourceType,
    YesNoUnknown,
)

AGENT_INTERNAL_NAME = "update_inbox_agent"


class UpdateInboxStore:
    def __init__(self) -> None:
        self.sources: list[UpdateSource] = []
        self.candidates: list[UpdateCandidate] = []
        self.shipping_rules: list[ShippingRule] = []
        self._counter = 0

    def next_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}-{self._counter:03d}"

    def add_result(self, source: UpdateSource, candidates: list[UpdateCandidate], shipping_rules: list[ShippingRule]) -> None:
        self.sources.append(source)
        self.candidates.extend(candidates)
        self.shipping_rules.extend(shipping_rules)


def create_shipping_rule(
    shipping_rule_id: str,
    *,
    shipping_type: Optional[ShippingType] = None,
    destination_region=None,
    rate_usd: Optional[float] = None,
    currency: str = "USD",
    dangerous_goods: YesNoUnknown = YesNoUnknown.UNKNOWN,
    battery_included: YesNoUnknown = YesNoUnknown.UNKNOWN,
    product_scope: Optional[str] = None,
    sku_scope: Optional[list[str]] = None,
    case_id: Optional[str] = None,
    scope_type: ShippingScopeType = ShippingScopeType.STANDARD,
    source_type: Optional[str] = None,
    source_reference: Optional[str] = None,
    announced_at: Optional[datetime] = None,
    effective_from: Optional[datetime] = None,
    status: RecordStatus = RecordStatus.CANDIDATE,
    notes: Optional[str] = None,
    update_candidate_id: Optional[str] = None,
) -> ShippingRule:
    return ShippingRule(
        shipping_rule_id=shipping_rule_id,
        shipping_type=shipping_type,
        destination_region=destination_region,
        rate_usd=rate_usd,
        currency=currency,
        dangerous_goods=dangerous_goods,
        battery_included=battery_included,
        product_scope=product_scope,
        sku_scope=list(sku_scope or []),
        case_id=case_id,
        scope_type=scope_type,
        source_type=source_type,
        source_reference=source_reference,
        announced_at=announced_at,
        effective_from=effective_from,
        status=status,
        notes=notes,
        update_candidate_id=update_candidate_id,
    )


def organize_pasted_update(
    *,
    source_type: UpdateSourceType = UpdateSourceType.DEALER_UPDATE_EMAIL,
    source_title: Optional[str] = None,
    source_sender: Optional[str] = None,
    source_date: Optional[datetime] = None,
    source_text: Optional[str] = None,
    source_reference: Optional[str] = None,
    imported_at: Optional[datetime] = None,
    store: Optional[UpdateInboxStore] = None,
) -> tuple[UpdateSource, list[UpdateCandidate], list[ShippingRule]]:
    inbox = store or UpdateInboxStore()
    source = UpdateSource(
        update_source_id=inbox.next_id("src"),
        source_type=source_type,
        source_title=source_title,
        source_sender=source_sender,
        source_date=source_date,
        source_text=source_text,
        source_reference=source_reference,
        imported_at=imported_at or datetime.now(timezone.utc),
    )
    candidates: list[UpdateCandidate] = []
    shipping_rules: list[ShippingRule] = []
    if _matches_september_2026_dealer_update(source_title, source_text):
        candidates, shipping_rules = _build_september_2026_candidates(inbox, source)
    inbox.add_result(source, candidates, shipping_rules)
    return source, candidates, shipping_rules


def create_manual_candidate(
    *,
    category: UpdateCategory,
    summary: Optional[str] = None,
    product: Optional[str] = None,
    sku: Optional[str] = None,
    new_value: Optional[str] = None,
    unit: Optional[str] = None,
    effective_from: Optional[datetime] = None,
    source_sender: Optional[str] = None,
    notes: Optional[str] = None,
    source_type: UpdateSourceType = UpdateSourceType.MANUAL,
    source_reference: Optional[str] = None,
    is_time_sensitive: bool = False,
    case_id: Optional[str] = None,
    shipping_type: Optional[ShippingType] = None,
    store: Optional[UpdateInboxStore] = None,
) -> tuple[UpdateSource, UpdateCandidate, Optional[ShippingRule]]:
    inbox = store or UpdateInboxStore()
    source = UpdateSource(
        update_source_id=inbox.next_id("src"),
        source_type=source_type,
        source_title=summary,
        source_sender=source_sender,
        source_date=effective_from,
        source_text=summary,
        source_reference=source_reference or source_sender,
        imported_at=datetime.now(timezone.utc),
    )
    candidate = UpdateCandidate(
        update_candidate_id=inbox.next_id("cand"),
        update_source_id=source.update_source_id,
        category=category,
        title=summary,
        summary=summary,
        product=product,
        sku=sku,
        new_value=new_value,
        unit=unit,
        effective_from=effective_from,
        is_time_sensitive=is_time_sensitive,
        confidence=UpdateConfidence.MANUAL_UNVERIFIED,
        status=RecordStatus.CANDIDATE,
        notes=notes,
        target_master=_target_master_for(category),
    )
    shipping_rule = None
    if category == UpdateCategory.SHIPPING:
        rate = _parse_optional_float(new_value)
        shipping_rule = create_shipping_rule(
            inbox.next_id("ship"),
            shipping_type=shipping_type or ShippingType.CUSTOM,
            rate_usd=rate,
            product_scope=product,
            sku_scope=[sku] if sku else [],
            case_id=case_id,
            scope_type=ShippingScopeType.CASE_SPECIFIC if (case_id or product or sku) else ShippingScopeType.STANDARD,
            source_type=source_type.value,
            source_reference=source_sender,
            effective_from=effective_from,
            notes=notes,
            update_candidate_id=candidate.update_candidate_id,
        )
    inbox.add_result(source, [candidate], [shipping_rule] if shipping_rule else [])
    return source, candidate, shipping_rule


def _matches_september_2026_dealer_update(title: Optional[str], text: Optional[str]) -> bool:
    blob = f"{title or ''}\n{text or ''}".lower()
    return any(hint in blob for hint in MATCH_HINTS)


def _build_september_2026_candidates(
    inbox: UpdateInboxStore,
    source: UpdateSource,
) -> tuple[list[UpdateCandidate], list[ShippingRule]]:
    source.source_title = source.source_title or DEALER_UPDATE_TITLE
    source.source_date = source.source_date or DEALER_UPDATE_DATE
    source.source_reference = source.source_reference or DEALER_UPDATE_REFERENCE
    candidates: list[UpdateCandidate] = []
    shipping_rules: list[ShippingRule] = []

    for row in STANDARD_SHIPPING_RATES:
        candidate = UpdateCandidate(
            update_candidate_id=inbox.next_id("cand"),
            update_source_id=source.update_source_id,
            category=UpdateCategory.SHIPPING,
            title=row["title"],
            summary=row["title"],
            new_value=f"{row['rate_usd']:.2f}",
            unit="USD",
            effective_from=DEALER_UPDATE_DATE,
            is_time_sensitive=True,
            confidence=UpdateConfidence.RULE_BASED_UNVERIFIED,
            status=RecordStatus.CANDIDATE,
            notes=SHIPPING_NOTES,
            target_master="ShippingRule",
        )
        rule = create_shipping_rule(
            inbox.next_id("ship"),
            shipping_type=row["shipping_type"],
            destination_region=row["destination_region"],
            rate_usd=row["rate_usd"],
            dangerous_goods=DEFAULT_SHIPPING_FLAGS["dangerous_goods"],
            battery_included=DEFAULT_SHIPPING_FLAGS["battery_included"],
            scope_type=DEFAULT_SHIPPING_FLAGS["scope_type"],
            source_type=UpdateSourceType.DEALER_UPDATE_EMAIL.value,
            source_reference=DEALER_UPDATE_REFERENCE,
            announced_at=DEALER_UPDATE_DATE,
            effective_from=DEALER_UPDATE_DATE,
            notes=SHIPPING_NOTES,
            update_candidate_id=candidate.update_candidate_id,
        )
        candidates.append(candidate)
        shipping_rules.append(rule)

    for row in LEAD_TIMES:
        candidates.append(
            UpdateCandidate(
                update_candidate_id=inbox.next_id("cand"),
                update_source_id=source.update_source_id,
                category=UpdateCategory.LEAD_TIME,
                title=f"{row['product']} lead time",
                summary=f"{row['product']} lead time announced in the September Dealer Update.",
                product=row["product"],
                new_value=row["new_value"],
                unit=row["unit"],
                effective_from=DEALER_UPDATE_DATE,
                is_time_sensitive=True,
                confidence=UpdateConfidence.RULE_BASED_UNVERIFIED,
                status=RecordStatus.CANDIDATE,
                target_master="LeadTimeMaster",
            )
        )

    for row in PRODUCT_SPECS:
        candidates.append(
            UpdateCandidate(
                update_candidate_id=inbox.next_id("cand"),
                update_source_id=source.update_source_id,
                category=UpdateCategory.PRODUCT_SPEC,
                title=row["title"],
                summary=row["summary"],
                product=row["product"],
                new_value=row["new_value"],
                unit=row.get("unit"),
                effective_from=DEALER_UPDATE_DATE,
                is_time_sensitive=bool(row.get("is_time_sensitive")),
                confidence=UpdateConfidence.RULE_BASED_UNVERIFIED,
                status=RecordStatus.CANDIDATE,
                target_master="TechnicalFact",
                notes="Do not register as a TechnicalFact until a human confirms it.",
            )
        )
    return candidates, shipping_rules


def _target_master_for(category: UpdateCategory) -> str:
    mapping = {
        UpdateCategory.SHIPPING: "ShippingRule",
        UpdateCategory.LEAD_TIME: "LeadTimeMaster",
        UpdateCategory.PRODUCT_SPEC: "TechnicalFact",
        UpdateCategory.PRICE: "PriceBook",
        UpdateCategory.PRODUCT_STATUS: "ProductKnowledgeMaster",
        UpdateCategory.WARRANTY: "ProductKnowledgeMaster",
        UpdateCategory.FIRMWARE: "ProductKnowledgeMaster",
        UpdateCategory.MARKETING_MATERIAL: "MarketingMaterial",
        UpdateCategory.OTHER: "Review",
    }
    return mapping[category]


def _parse_optional_float(value: Optional[str]) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return round(float(str(value).replace(",", "").replace("USD", "").strip()), 2)
    except ValueError:
        return None
