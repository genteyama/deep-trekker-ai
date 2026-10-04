from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Optional

from llm.completeness import REQUESTED_PRODUCT_CATALOG, detect_catalog_names
from models import MatchConfidence, ResponseMatchCandidate, SuggestedQuestionStatus, TechnicalQuestion

REASON_NO_MODEL_MATCH = "NO_MODEL_MATCH"
REASON_EVIDENCE_MISSING = "EVIDENCE_MISSING"
REASON_EVIDENCE_NOT_IN_RESPONSE = "EVIDENCE_NOT_IN_RESPONSE"
REASON_PRODUCT_SCOPE_MISMATCH = "PRODUCT_SCOPE_MISMATCH"
REASON_TOPIC_SCOPE_MISMATCH = "TOPIC_SCOPE_MISMATCH"

CLAIM_STATUSES = {
    SuggestedQuestionStatus.ANSWERED.value,
    SuggestedQuestionStatus.PARTIAL.value,
    SuggestedQuestionStatus.ANSWERED,
    SuggestedQuestionStatus.PARTIAL,
}

# Accessories stay out of inquiry product detection; they are entities for MR scope only.
ACCESSORY_ENTITY_CATALOG = (
    "Cygnus Thickness Gauge",
    "Sonar",
)
PRODUCT_ENTITY_CATALOG = REQUESTED_PRODUCT_CATALOG + ACCESSORY_ENTITY_CATALOG

TOPIC_FAMILIES = (
    ("tether", ("テザー", "繰出", "走行距離", "tether", "payout", "travel distance")),
    ("heading", ("方位", "heading", "yaw", "orientation", "方向情報", "姿勢", "向き")),
    ("depth", ("水深", "depth")),
    ("altitude", ("高度", "altitude")),
    ("surface_transition", ("面移動", "90度", "連続して移動", "surface transition")),
    ("simultaneous_mount", ("同時搭載", "simultaneous")),
    ("recording", ("記録", "recording")),
    ("lead_time", ("納期", "lead time", "lead-time")),
    ("recommendation", ("推奨構成", "recommended configuration", "メーカーが推奨")),
    ("compatibility", ("互換", "組み合わせ", "compatibility", "integration kit")),
    ("suitability", ("適している", "適性", "suitability")),
    ("self_position", ("自己位置", "self-position", "self position", "position awareness", "位置把握")),
)
SENSOR_TOPICS = frozenset({"self_position", "depth", "altitude", "tether", "heading"})


@dataclass
class EvidenceCheck:
    evidence_valid: bool = True
    product_scope_valid: bool = True
    topic_scope_valid: bool = True
    requires_human_review: bool = False
    reason: Optional[str] = None
    original_status: Optional[str] = None
    question_topic: Optional[str] = None
    evidence_topic: Optional[str] = None
    question_products: list[str] = None
    evidence_products: list[str] = None

    def __post_init__(self) -> None:
        if self.question_products is None:
            self.question_products = []
        if self.evidence_products is None:
            self.evidence_products = []

    def as_dict(self) -> dict:
        return asdict(self)


def product_aliases(name: str) -> list[str]:
    aliases = [name]
    first = name.split()[0]
    if first and first.casefold() not in {item.casefold() for item in aliases}:
        aliases.append(first)
    return aliases


def extract_product_entities(text: Optional[str], catalog: tuple[str, ...] = PRODUCT_ENTITY_CATALOG) -> list[str]:
    blob = text or ""
    found = []
    for official in catalog:
        aliases = sorted(product_aliases(official), key=len, reverse=True)
        for alias in aliases:
            if not alias:
                continue
            if not re.search(rf"(?<![A-Za-z0-9_]){re.escape(alias)}(?![A-Za-z0-9_])", blob, re.I):
                continue
            if alias.casefold() == "mag" and "magnet" in blob.casefold() and "mag utility" not in blob.casefold():
                continue
            if official not in found:
                found.append(official)
            break
    extra = detect_catalog_names(blob, catalog)
    for item in extra:
        if item not in found:
            found.append(item)
    return found


def matched_topics(*texts: Optional[str]) -> list[str]:
    blob = "\n".join(item or "" for item in texts).casefold()
    if not blob.strip():
        return []
    matches = []
    for family, aliases in TOPIC_FAMILIES:
        if any(alias.casefold() in blob for alias in aliases):
            matches.append(family)
    return matches


def classify_topic(*texts: Optional[str]) -> Optional[str]:
    matches = matched_topics(*texts)
    if not matches:
        return None
    if "self_position" in matches:
        return "self_position"
    sensor_hits = [item for item in matches if item in SENSOR_TOPICS]
    if len(sensor_hits) > 1:
        return None
    return matches[0]


def evidence_in_response(evidence: Optional[str], response_text: Optional[str]) -> bool:
    snippet = (evidence or "").strip()
    source = response_text or ""
    if not snippet:
        return False
    return snippet in source


def _unique(items: list[str]) -> list[str]:
    found = []
    for item in items:
        if item and item not in found:
            found.append(item)
    return found


def required_question_entities(question: TechnicalQuestion) -> list[str]:
    related = list(question.related_products or [])
    text_blob = " ".join(
        [
            question.question or "",
            question.normalized_meaning or "",
            question.grounding or "",
            " ".join(related),
        ]
    )
    from_text = _unique(extract_product_entities(text_blob))
    from_id = []
    for token in (question.question_id or "").split("_"):
        from_id.extend(extract_product_entities(token))
    from_id = _unique(from_id)
    if from_text:
        return _unique(from_text + from_id)
    return []


def product_scope_covers(required: list[str], evidence_entities: list[str]) -> bool:
    if not required:
        return True
    return set(required).issubset(set(evidence_entities))


def topic_scope_covers(question_topic: Optional[str], evidence_topics: list[str], evidence_topic: Optional[str]) -> bool:
    evidence_sensors = [item for item in evidence_topics if item in SENSOR_TOPICS]
    if "self_position" in evidence_sensors:
        return question_topic == "self_position"
    if question_topic in SENSOR_TOPICS:
        unique_sensors = list(dict.fromkeys(evidence_sensors))
        if len(unique_sensors) > 1:
            return False
        if unique_sensors and unique_sensors[0] != question_topic:
            return False
    if question_topic and evidence_topic and question_topic != evidence_topic:
        return False
    return True


def _status_value(value) -> Optional[str]:
    if value is None:
        return None
    return getattr(value, "value", value)


def check_match(
    question: TechnicalQuestion,
    candidate: ResponseMatchCandidate,
    response_text: Optional[str],
) -> EvidenceCheck:
    status = _status_value(candidate.suggested_status)
    evidence_text = " ".join(
        [
            candidate.evidence_text or "",
            candidate.answer_summary or "",
        ]
    )
    question_products = required_question_entities(question)
    evidence_products = extract_product_entities(evidence_text)
    question_topics = matched_topics(question.question_id, question.question, question.normalized_meaning)
    evidence_topics = matched_topics(candidate.evidence_text, candidate.answer_summary)
    question_topic = classify_topic(question.question_id, question.question, question.normalized_meaning)
    evidence_topic = classify_topic(candidate.evidence_text, candidate.answer_summary)
    check = EvidenceCheck(
        original_status=status,
        question_topic=question_topic,
        evidence_topic=evidence_topic,
        question_products=question_products,
        evidence_products=evidence_products,
    )

    if status not in {SuggestedQuestionStatus.ANSWERED.value, SuggestedQuestionStatus.PARTIAL.value}:
        return check

    if not (candidate.evidence_text or "").strip():
        check.evidence_valid = False
    elif not evidence_in_response(candidate.evidence_text, response_text):
        check.evidence_valid = False
        check.reason = REASON_EVIDENCE_NOT_IN_RESPONSE

    check.product_scope_valid = product_scope_covers(question_products, evidence_products)
    check.topic_scope_valid = topic_scope_covers(question_topic, evidence_topics, evidence_topic)

    if not check.evidence_valid:
        check.requires_human_review = True
        check.reason = check.reason or REASON_EVIDENCE_MISSING
        return check
    if not check.product_scope_valid:
        check.requires_human_review = True
        check.reason = REASON_PRODUCT_SCOPE_MISMATCH
        return check
    if not check.topic_scope_valid:
        check.requires_human_review = True
        check.reason = REASON_TOPIC_SCOPE_MISMATCH
        return check

    if question_topic and evidence_topic is None:
        check.requires_human_review = True
    return check


def downgrade_status(status: Optional[str], check: EvidenceCheck) -> SuggestedQuestionStatus:
    current = status or SuggestedQuestionStatus.FOLLOW_UP_REQUIRED.value
    if check.reason in {
        REASON_EVIDENCE_MISSING,
        REASON_EVIDENCE_NOT_IN_RESPONSE,
        REASON_PRODUCT_SCOPE_MISMATCH,
        REASON_TOPIC_SCOPE_MISMATCH,
    }:
        return SuggestedQuestionStatus.FOLLOW_UP_REQUIRED
    return SuggestedQuestionStatus(current) if current in SuggestedQuestionStatus.__members__ else SuggestedQuestionStatus.FOLLOW_UP_REQUIRED


def apply_evidence_guard(
    question: TechnicalQuestion,
    candidate: ResponseMatchCandidate,
    response_text: Optional[str],
) -> tuple[ResponseMatchCandidate, EvidenceCheck]:
    check = check_match(question, candidate, response_text)
    status = _status_value(candidate.suggested_status)
    if check.reason:
        updated = candidate.model_copy(
            update={
                "suggested_status": downgrade_status(status, check),
                "follow_up_required": True,
            }
        )
        return updated, check
    return candidate, check


def missing_match_candidate(question: TechnicalQuestion) -> ResponseMatchCandidate:
    return ResponseMatchCandidate(
        question_id=question.question_id,
        answer_summary=None,
        suggested_status=SuggestedQuestionStatus.FOLLOW_UP_REQUIRED,
        follow_up_required=True,
        follow_up_question=question.question,
        confidence=MatchConfidence.LOW,
        evidence_text=None,
    )
