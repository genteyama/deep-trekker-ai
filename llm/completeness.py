from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Iterable, Optional

from llm.analysis_schema import ExtractedQuestion, ExtractedRequirement, TechnicalCaseAnalysisResponse
from models import ManufacturerResponseAnalysis, SuggestedQuestionStatus, TechnicalQuestion

SEVERITY_WARNING = "WARNING"
SEVERITY_FAIL = "FAIL"
ERROR_COMPLETENESS = "COMPLETENESS_ERROR"

REQUESTED_PRODUCT_CATALOG = (
    "MAG Utility Crawler",
    "PipeTrekker",
    "PHOTON",
    "REVOLUTION",
    "PIVOT",
    "DT340",
    "DT420",
)
EXISTING_EQUIPMENT_CATALOG = (
    "CHASING ROV",
)
NARROWING_TECHNOLOGIES = ("GPS", "IMU", "USBL", "DVL", "SLAM", "LiDAR", "INS")
CUSTOMER_POSITION_PHRASES = ("位置を把握", "測定した場所", "位置把握", "自己位置")
UNSUPPORTED_FACT_PATTERNS = (
    re.compile(r"最適製品"),
    re.compile(r"(スペースワン|SpaceOne)推奨"),
    re.compile(r"(センサー|機能)が(ある|ない)"),
    re.compile(r"(ATEX|IECEx|防爆認証)が必要"),
    re.compile(r"(\$|USD|万円)\s*\d+"),
    re.compile(r"納期.{0,12}\d.{0,8}(週|日|か月|ヶ月)"),
)
MEASUREMENT_RE = re.compile(
    r"(?:約)?\d+(?:\.\d+)?(?:\s*[～~\-]\s*(?:約)?\d+(?:\.\d+)?)?\s*(?:mm|cm|m|kg|℃|°C)",
    re.IGNORECASE,
)
GOAL_PHRASES = ("肉厚測定", "厚さ測定", "thickness measurement")
CUSTOMER_REQUIRED = "CUSTOMER_REQUIRED"
AI_SUGGESTED = "AI_SUGGESTED"


@dataclass
class CompletenessIssue:
    severity: str
    code: str
    message: str

    def as_dict(self) -> dict:
        return asdict(self)


class CompletenessError(Exception):
    def __init__(self, issues: list[CompletenessIssue]) -> None:
        self.issues = issues
        super().__init__("; ".join(item.message for item in issues))


def _norm(text: Optional[str]) -> str:
    return (text or "").strip()


def _haystack(values: Iterable[Optional[str]]) -> str:
    return "\n".join(_norm(item) for item in values if _norm(item))


def detect_catalog_names(text: str, catalog: Iterable[str]) -> list[str]:
    found = []
    blob = text or ""
    for name in catalog:
        if name.casefold() in blob.casefold() and name not in found:
            found.append(name)
    return found


def detect_explicit_measurements(text: str) -> list[ExtractedRequirement]:
    items = []
    seen = set()
    for match in MEASUREMENT_RE.finditer(text or ""):
        value = re.sub(r"\s+", "", match.group(0))
        start = max(0, match.start() - 16)
        original = (text or "")[start:match.end()].strip(" 　、。:：\n")
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append(
            ExtractedRequirement(
                category="stated_measurement",
                label="explicit_measurement",
                value=value,
                original_text=original,
                normalized_meaning="customer-stated measurement",
                notes="Extracted from customer wording. Not a manufacturer specification.",
            )
        )
    return items


def detect_phrase_requirements(text: str, phrases: Iterable[str], category: str, label: str) -> list[ExtractedRequirement]:
    items = []
    blob = text or ""
    for phrase in phrases:
        if phrase.casefold() in blob.casefold():
            items.append(
                ExtractedRequirement(
                    category=category,
                    label=label,
                    value=phrase,
                    original_text=phrase,
                    normalized_meaning=phrase,
                )
            )
    return items


def _requirement_blob(items: list[ExtractedRequirement]) -> str:
    return _haystack(
        [
            item.original_text or item.value or item.label or item.notes
            for item in items
        ]
    )


def _question_has_narrowing(question: ExtractedQuestion, inquiry: str) -> bool:
    text = _haystack([question.question, question.normalized_meaning, question.original_text])
    if not any(phrase in (inquiry or "") for phrase in CUSTOMER_POSITION_PHRASES) and not any(
        phrase in text for phrase in CUSTOMER_POSITION_PHRASES
    ):
        # still flag invented positioning tech not present in the inquiry
        pass
    for tech in NARROWING_TECHNOLOGIES:
        if tech.casefold() in text.casefold() and tech.casefold() not in (inquiry or "").casefold():
            return True
    return False


def _mark_ai_suggested(question: ExtractedQuestion) -> ExtractedQuestion:
    return question.model_copy(
        update={
            "classification": AI_SUGGESTED,
            "source": AI_SUGGESTED,
        }
    )


def harden_analysis(
    inquiry_text: Optional[str],
    analysis: TechnicalCaseAnalysisResponse,
) -> TechnicalCaseAnalysisResponse:
    inquiry = inquiry_text or ""
    products = list(analysis.requested_products)
    for name in detect_catalog_names(inquiry, REQUESTED_PRODUCT_CATALOG):
        if not any(name.casefold() == item.casefold() for item in products):
            products.append(name)

    requirements = list(analysis.requirements)
    covered = _requirement_blob(requirements).casefold()
    for item in detect_explicit_measurements(inquiry):
        token = (item.value or "").casefold()
        if token and token not in covered:
            requirements.append(item)
            covered += " " + token

    customer_goal = list(analysis.customer_goal)
    if not customer_goal:
        customer_goal.extend(detect_phrase_requirements(inquiry, GOAL_PHRASES, "customer_goal", "customer_goal"))

    existing_equipment = list(analysis.existing_equipment)
    for name in detect_catalog_names(inquiry, EXISTING_EQUIPMENT_CATALOG):
        if name.casefold() not in _requirement_blob(existing_equipment).casefold():
            existing_equipment.append(
                ExtractedRequirement(
                    category="existing_equipment",
                    label="existing_equipment",
                    value=name,
                    original_text=name,
                    normalized_meaning=name,
                )
            )

    def rewrite(questions: list[ExtractedQuestion]) -> list[ExtractedQuestion]:
        rewritten = []
        for question in questions:
            current = question
            if current.classification == CUSTOMER_REQUIRED and current.source == AI_SUGGESTED:
                current = _mark_ai_suggested(current)
            if _question_has_narrowing(current, inquiry):
                current = _mark_ai_suggested(current)
            rewritten.append(current)
        return rewritten

    return analysis.model_copy(
        update={
            "requested_products": products,
            "requirements": requirements,
            "customer_goal": customer_goal,
            "existing_equipment": existing_equipment,
            "customer_questions": rewrite(analysis.customer_questions),
            "manufacturer_questions": rewrite(analysis.manufacturer_questions),
            "technical_questions": rewrite(analysis.technical_questions),
        }
    )


def validate_analysis_completeness(
    inquiry_text: Optional[str],
    analysis: TechnicalCaseAnalysisResponse,
) -> list[CompletenessIssue]:
    inquiry = inquiry_text or ""
    issues = []
    stated_products = detect_catalog_names(inquiry, REQUESTED_PRODUCT_CATALOG)
    if stated_products and not analysis.requested_products:
        issues.append(
            CompletenessIssue(
                SEVERITY_WARNING,
                "EMPTY_REQUESTED_PRODUCTS",
                "Customer text states a product name but requested_products is empty.",
            )
        )
    if detect_explicit_measurements(inquiry) and not analysis.requirements:
        issues.append(
            CompletenessIssue(
                SEVERITY_WARNING,
                "EMPTY_REQUIREMENTS",
                "Customer text states numeric requirements but requirements is empty.",
            )
        )

    fact_text = _haystack(
        [analysis.case_summary]
        + [_requirement_blob(analysis.requirements), _requirement_blob(analysis.customer_goal)]
    )
    for pattern in UNSUPPORTED_FACT_PATTERNS:
        if pattern.search(fact_text) and not pattern.search(inquiry):
            issues.append(
                CompletenessIssue(
                    SEVERITY_FAIL,
                    "UNSUPPORTED_ASSERTION",
                    "Analysis asserts a specification that is not in the customer text.",
                )
            )
            break

    for group in (analysis.customer_questions, analysis.manufacturer_questions, analysis.technical_questions):
        for question in group:
            if question.classification == CUSTOMER_REQUIRED and question.source == AI_SUGGESTED:
                issues.append(
                    CompletenessIssue(
                        SEVERITY_FAIL,
                        "AI_SUGGESTED_AS_CUSTOMER_REQUIRED",
                        "AI_SUGGESTED content was treated as CUSTOMER_REQUIRED.",
                    )
                )
            if question.classification == CUSTOMER_REQUIRED and _question_has_narrowing(question, inquiry):
                issues.append(
                    CompletenessIssue(
                        SEVERITY_FAIL,
                        "CUSTOMER_WORDING_NARROWED",
                        "Customer wording was replaced with a specific technology.",
                    )
                )
    return issues


def validate_manufacturer_match_completeness(
    questions: list[TechnicalQuestion],
    analysis: ManufacturerResponseAnalysis,
    response_text: Optional[str] = None,
) -> list[CompletenessIssue]:
    issues = []
    expected_ids = [item.question_id for item in questions]
    match_ids = [item.question_id for item in analysis.matches]
    if questions and not analysis.matches:
        issues.append(
            CompletenessIssue(
                SEVERITY_FAIL,
                "EMPTY_MATCHES",
                "Open manufacturer questions exist but matches is empty.",
            )
        )
        return issues

    missing = [item_id for item_id in expected_ids if item_id not in set(match_ids)]
    if missing:
        issues.append(
            CompletenessIssue(
                SEVERITY_FAIL,
                "MISSING_QUESTION_MATCH",
                "One or more question IDs have no match: " + ", ".join(missing),
            )
        )

    seen = set()
    duplicates = []
    for item_id in match_ids:
        if item_id in seen and item_id not in duplicates:
            duplicates.append(item_id)
        seen.add(item_id)
    if duplicates:
        issues.append(
            CompletenessIssue(
                SEVERITY_FAIL,
                "DUPLICATE_QUESTION_MATCH",
                "Duplicate matches exist for: " + ", ".join(duplicates),
            )
        )

    response = response_text or ""
    unmatched_blob = _haystack(
        [item.original_text or item.summary for item in analysis.unmatched_information]
    )
    if (
        questions
        and analysis.matches == []
        and unmatched_blob
        and response
        and response.strip() in unmatched_blob
    ):
        issues.append(
            CompletenessIssue(
                SEVERITY_FAIL,
                "RESPONSE_DUMPED_TO_UNMATCHED",
                "Manufacturer response was dumped into unmatched_information.",
            )
        )

    for match in analysis.matches:
        status = getattr(match.suggested_status, "value", match.suggested_status)
        if status in {SuggestedQuestionStatus.ANSWERED.value, SuggestedQuestionStatus.PARTIAL.value}:
            if not _norm(match.evidence_text):
                issues.append(
                    CompletenessIssue(
                        SEVERITY_FAIL,
                        "MISSING_EVIDENCE",
                        f"Match {match.question_id} is {status} without evidence.",
                    )
                )
    return issues


def raise_if_fail(issues: list[CompletenessIssue]) -> None:
    fails = [item for item in issues if item.severity == SEVERITY_FAIL]
    if fails:
        raise CompletenessError(fails)
