from __future__ import annotations

from json import loads
from pathlib import Path
from typing import Optional

from llm.completeness import REQUESTED_PRODUCT_CATALOG, detect_catalog_names
from models import FactConfidence, FactScope, TechnicalFact

CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "technical_facts" / "human_approved.json"
ALLOWED_STATUSES = {"HUMAN_REGISTERED"}
ALLOWED_SCOPES = {FactScope.PRODUCT_REUSABLE.value, FactScope.PRODUCT_REUSABLE}
ALLOWED_CONFIDENCE = {
    FactConfidence.MANUFACTURER_CONFIRMED,
    FactConfidence.SPACEONE_VERIFIED,
    FactConfidence.MANUFACTURER_CONFIRMED.value,
    FactConfidence.SPACEONE_VERIFIED.value,
}
SOURCE_TECHNICAL_FACT = "TECHNICAL_FACT"


def load_human_approved_catalog(path: Optional[Path] = None) -> list[dict]:
    catalog_path = path or CATALOG_PATH
    payload = loads(catalog_path.read_text(encoding="utf-8"))
    return list(payload.get("facts") or [])


def detect_requested_products(inquiry_text: Optional[str]) -> list[str]:
    return detect_catalog_names(inquiry_text or "", REQUESTED_PRODUCT_CATALOG)


def _product_matches(fact_product: Optional[str], requested: list[str]) -> bool:
    product = (fact_product or "").strip()
    if not product:
        return False
    requested_blob = " ".join(requested)
    return product.casefold() in requested_blob.casefold() or any(
        item.casefold() in product.casefold() for item in requested
    )


def is_retrievable_fact(item: dict) -> bool:
    if (item.get("status") or "") not in ALLOWED_STATUSES:
        return False
    if item.get("scope") not in ALLOWED_SCOPES:
        return False
    if item.get("confidence") not in ALLOWED_CONFIDENCE:
        return False
    return bool((item.get("fact") or "").strip())


def retrieve_approved_facts_for_products(
    products: list[str],
    catalog: Optional[list[dict]] = None,
) -> list[dict]:
    if not products:
        return []
    selected = []
    for item in catalog if catalog is not None else load_human_approved_catalog():
        if not is_retrievable_fact(item):
            continue
        if _product_matches(item.get("product"), products):
            selected.append(item)
    return selected


def facts_as_provider_payload(facts: list[dict]) -> list[dict]:
    payload = []
    for item in facts:
        payload.append(
            {
                "fact_id": item.get("fact_id"),
                "product": item.get("product"),
                "topic": item.get("topic"),
                "fact": item.get("fact"),
                "confidence": item.get("confidence"),
                "source_reference": item.get("source_reference"),
                "notes": item.get("notes"),
                "remaining_open_question": item.get("remaining_open_question"),
            }
        )
    return payload


def fact_applies_to_inquiry(item: dict, inquiry_text: Optional[str]) -> bool:
    blob = inquiry_text or ""
    triggers = item.get("inquiry_triggers") or []
    if not triggers:
        return True
    return any(trigger in blob for trigger in triggers)


def build_fact_grounded_questions(inquiry_text: Optional[str], facts: list[dict]) -> list[dict]:
    questions = []
    for item in facts:
        if not fact_applies_to_inquiry(item, inquiry_text):
            continue
        question = (item.get("remaining_open_question") or "").strip()
        if not question:
            continue
        questions.append(
            {
                "question": question,
                "classification": "CONFIGURATION_CHECK",
                "source": SOURCE_TECHNICAL_FACT,
                "original_text": None,
                "normalized_meaning": item.get("fact"),
                "grounding": item.get("fact_id"),
            }
        )
    return questions


TOPIC_ALREADY_ASKED = {
    "FACT-MAG-SURFACE-TRANSITION": ("面移動", "連続して移動", "90度"),
    "FACT-MAG-SELF-POSITION": ("自己位置", "測定位置の記録"),
    "FACT-MAG-CYGNUS": ("Cygnus", "Integration Kit"),
    "FACT-MAG-UNDERWATER-TANK-RECOMMENDATION": ("ROVと超音波", "メーカーはROV", "推奨はROV"),
}


def merge_manufacturer_questions(existing: list, grounded: list[dict]) -> list:
    merged = list(existing)
    existing_text = "\n".join(_question_text(item) for item in existing).casefold()
    for item in grounded:
        question = item.get("question") or ""
        markers = TOPIC_ALREADY_ASKED.get(item.get("grounding") or "", ())
        if question.casefold() in existing_text:
            continue
        if any(marker.casefold() in existing_text for marker in markers):
            continue
        merged.append(item)
        existing_text += "\n" + question.casefold()
    return merged


def _question_text(item) -> str:
    if isinstance(item, dict):
        return item.get("question") or ""
    return getattr(item, "question", None) or ""


def facts_to_models(facts: list[dict]) -> list[TechnicalFact]:
    models = []
    for item in facts:
        models.append(
            TechnicalFact(
                fact_id=item["fact_id"],
                case_id=item.get("case_id") or "CATALOG",
                product=item.get("product"),
                topic=item.get("topic"),
                fact=item.get("fact"),
                source_type=item.get("source_type"),
                source_reference=item.get("source_reference"),
                confidence=item.get("confidence"),
                status=item.get("status"),
                scope=item.get("scope"),
                is_time_sensitive=bool(item.get("is_time_sensitive")),
                notes=item.get("notes"),
            )
        )
    return models
