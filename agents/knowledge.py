from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

from agents.fact_retrieval import (
    facts_as_provider_payload,
    is_retrievable_fact,
    retrieve_approved_facts_for_products,
)
from llm.usage import utc_now_iso


@dataclass
class KnowledgeSnapshotItem:
    fact_id: str
    statement: str
    source_reference: Optional[str]
    selected: bool
    retrieved_at: str
    product: Optional[str] = None
    topic: Optional[str] = None
    scope: Optional[str] = None
    status: Optional[str] = None
    confidence: Optional[str] = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class KnowledgeContextSnapshot:
    retrieved_at: str
    items: list[KnowledgeSnapshotItem] = field(default_factory=list)

    def selected_facts(self) -> list[KnowledgeSnapshotItem]:
        return [item for item in self.items if item.selected]

    def as_dict(self) -> dict:
        return {
            "retrieved_at": self.retrieved_at,
            "items": [item.as_dict() for item in self.items],
        }


def is_default_selected(item: dict) -> bool:
    return is_retrievable_fact(item) and not item.get("superseded")


def build_knowledge_snapshot(
    products: list[str],
    selected_fact_ids: Optional[list[str]] = None,
    catalog: Optional[list[dict]] = None,
    retrieved_at: Optional[str] = None,
) -> KnowledgeContextSnapshot:
    timestamp = retrieved_at or utc_now_iso()
    candidates = retrieve_approved_facts_for_products(products, catalog=catalog)
    snapshot_items = []
    for item in candidates:
        fact_id = item.get("fact_id") or ""
        default_on = is_default_selected(item)
        selected = default_on if selected_fact_ids is None else fact_id in set(selected_fact_ids)
        snapshot_items.append(
            KnowledgeSnapshotItem(
                fact_id=fact_id,
                statement=item.get("fact") or "",
                source_reference=item.get("source_reference"),
                selected=selected,
                retrieved_at=timestamp,
                product=item.get("product"),
                topic=item.get("topic"),
                scope=str(item.get("scope") or ""),
                status=item.get("status"),
                confidence=str(item.get("confidence") or ""),
            )
        )
    return KnowledgeContextSnapshot(retrieved_at=timestamp, items=snapshot_items)


def selected_catalog_facts(
    products: list[str],
    selected_fact_ids: Optional[list[str]] = None,
    catalog: Optional[list[dict]] = None,
) -> list[dict]:
    snapshot = build_knowledge_snapshot(products, selected_fact_ids, catalog=catalog)
    selected_ids = {item.fact_id for item in snapshot.selected_facts()}
    return [
        item
        for item in retrieve_approved_facts_for_products(products, catalog=catalog)
        if item.get("fact_id") in selected_ids
    ]


def provider_knowledge_payload(facts: list[dict]) -> list[dict]:
    return facts_as_provider_payload(facts)
