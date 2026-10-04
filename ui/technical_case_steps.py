from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from models import TechnicalCaseStatus
from ui.work_status import (
    INFO_COMPLETE,
    INFO_IN_PROGRESS,
    INFO_LABELS,
    INFO_MISSING,
    INFO_NOT_STARTED,
    INFO_REVIEW_REQUIRED,
    INFO_WAITING,
    WorkSummary,
)

SESSION_CASE_STEP = "technical_case_step"
TECHNICAL_STEP_IDS = (1, 2, 3, 4, 5, 6, 7)
TECHNICAL_STEP_KEYS = {
    1: "intake",
    2: "requirements",
    3: "knowledge",
    4: "manufacturer",
    5: "response",
    6: "customer_reply",
    7: "complete",
}
STEP_INCOMPLETE = "INCOMPLETE"
STEP_STATUS_LABELS = {
    **INFO_LABELS,
    STEP_INCOMPLETE: "未完了",
}
DEFAULT_STEP_TITLES = {
    "intake": "受付",
    "requirements": "要件整理",
    "knowledge": "技術情報確認",
    "manufacturer": "メーカー確認",
    "response": "回答整理",
    "customer_reply": "顧客回答",
    "complete": "完了",
}


@dataclass
class TechnicalStepState:
    step: int
    key: str
    title: str
    status: str
    review_count: int = 0

    @property
    def is_complete(self) -> bool:
        return self.status == INFO_COMPLETE

    def badge_label(self, labels: Optional[dict] = None, unit: str = "件") -> str:
        mapping = labels or STEP_STATUS_LABELS
        label = mapping.get(self.status, self.status)
        if self.review_count:
            return f"{label} {self.review_count}{unit}"
        return label


@dataclass
class TechnicalWorkflow:
    steps: list[TechnicalStepState] = field(default_factory=list)
    current_step: int = 1
    review_required: int = 0

    @property
    def total(self) -> int:
        return len(self.steps) or len(TECHNICAL_STEP_IDS)

    @property
    def completed(self) -> int:
        return sum(1 for item in self.steps if item.is_complete)

    @property
    def current(self) -> TechnicalStepState:
        return self.step_state(self.current_step) or self.steps[0]

    def step_state(self, step: int) -> Optional[TechnicalStepState]:
        for item in self.steps:
            if item.step == step:
                return item
        return None

    def step_status(self, step: int) -> str:
        item = self.step_state(step)
        return item.status if item is not None else INFO_NOT_STARTED

    def step_is_complete(self, step: int) -> bool:
        item = self.step_state(step)
        return bool(item and item.is_complete)


def normalize_case_step(value) -> int:
    try:
        step = int(value)
    except (TypeError, ValueError):
        return 1
    return step if step in TECHNICAL_STEP_IDS else 1


def step_button_key(step: int) -> str:
    return f"technical_case_step_{step}"


def step_title(step: int, labels: Optional[dict] = None) -> str:
    key = TECHNICAL_STEP_KEYS.get(step, "intake")
    mapping = labels or {}
    return mapping.get(f"step_{key}", DEFAULT_STEP_TITLES[key])


def _item_status(summary: WorkSummary, key: str) -> str:
    item = summary.item(key)
    return item.status if item is not None else INFO_NOT_STARTED


def _item_reviews(summary: WorkSummary, key: str) -> int:
    item = summary.item(key)
    return item.review_count if item is not None else 0


def technical_step_status(step: int, summary: WorkSummary) -> tuple[str, int]:
    if step == 1:
        inquiry = _item_status(summary, "inquiry")
        case_info = _item_status(summary, "case_info")
        if inquiry == INFO_COMPLETE and case_info == INFO_COMPLETE:
            return INFO_COMPLETE, 0
        if inquiry == INFO_MISSING and case_info == INFO_MISSING:
            return INFO_MISSING, 0
        return INFO_IN_PROGRESS, 0
    if step == 2:
        return _item_status(summary, "requirements"), 0
    if step == 3:
        return _item_status(summary, "knowledge"), 0
    if step == 4:
        questions = _item_status(summary, "manufacturer_questions")
        review = summary.item("human_review")
        response = _item_status(summary, "manufacturer_response")
        review_status = review.status if review is not None else INFO_NOT_STARTED
        reviews = review.review_count if review is not None else 0
        if questions == INFO_NOT_STARTED:
            return INFO_NOT_STARTED, 0
        if response == INFO_COMPLETE:
            return INFO_COMPLETE, 0
        if review_status == INFO_REVIEW_REQUIRED:
            return INFO_REVIEW_REQUIRED, reviews
        if review_status == INFO_IN_PROGRESS:
            return INFO_IN_PROGRESS, reviews
        if review_status == INFO_COMPLETE:
            return INFO_WAITING, 0
        return INFO_WAITING if questions == INFO_COMPLETE else questions, reviews
    if step == 5:
        response = _item_status(summary, "manufacturer_response")
        evidence = summary.item("evidence_validation")
        evidence_status = evidence.status if evidence is not None else INFO_NOT_STARTED
        reviews = evidence.review_count if evidence is not None else 0
        if response in {INFO_NOT_STARTED, INFO_WAITING}:
            return INFO_NOT_STARTED, 0
        if evidence_status == INFO_REVIEW_REQUIRED:
            return INFO_REVIEW_REQUIRED, reviews
        if response == INFO_COMPLETE and evidence_status == INFO_COMPLETE:
            return INFO_COMPLETE, 0
        return INFO_IN_PROGRESS, reviews
    if step == 6:
        return _item_status(summary, "customer_reply"), 0
    if summary.process_status == TechnicalCaseStatus.COMPLETED.value:
        return INFO_COMPLETE, 0
    return STEP_INCOMPLETE, 0


def infer_current_step(summary: WorkSummary) -> int:
    if summary.process_status == TechnicalCaseStatus.COMPLETED.value:
        return 7
    for step in TECHNICAL_STEP_IDS:
        status, _ = technical_step_status(step, summary)
        if status != INFO_COMPLETE:
            return step
    return 7


def build_technical_workflow(summary: WorkSummary, labels: Optional[dict] = None) -> TechnicalWorkflow:
    steps = []
    for step in TECHNICAL_STEP_IDS:
        status, reviews = technical_step_status(step, summary)
        key = TECHNICAL_STEP_KEYS[step]
        steps.append(
            TechnicalStepState(
                step=step,
                key=key,
                title=step_title(step, labels),
                status=status,
                review_count=reviews,
            )
        )
    return TechnicalWorkflow(
        steps=steps,
        current_step=infer_current_step(summary),
        review_required=summary.review_required,
    )


def selected_or_current(session_value, workflow: TechnicalWorkflow) -> int:
    if session_value is None:
        return 1
    return normalize_case_step(session_value)
