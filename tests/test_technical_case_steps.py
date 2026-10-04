from agents.technical_case_agent import run_technical_case_analysis
from agents.technical_case_persistence import build_record
from llm.mock_provider import MockTechnicalCaseProvider
from models import TechnicalCaseStatus
from ui.technical_case_steps import (
    SESSION_CASE_STEP,
    TECHNICAL_STEP_IDS,
    TECHNICAL_STEP_KEYS,
    build_technical_workflow,
    infer_current_step,
    normalize_case_step,
    selected_or_current,
    step_button_key,
    technical_step_status,
)
from ui.work_status import (
    INFO_COMPLETE,
    INFO_MISSING,
    INFO_NOT_STARTED,
    INFO_REVIEW_REQUIRED,
    INFO_WAITING,
    operations_are_blocked,
    summarize_technical_case,
)


def _analyze():
    return run_technical_case_analysis(
        "タンク肉厚測定",
        "IHI検査計測",
        None,
        "MAG Utility Crawlerで鋼製円筒タンクの水中肉厚測定を検討。",
        provider=MockTechnicalCaseProvider(),
    )


def test_seven_technical_steps_are_defined():
    assert TECHNICAL_STEP_IDS == (1, 2, 3, 4, 5, 6, 7)
    assert [TECHNICAL_STEP_KEYS[step] for step in TECHNICAL_STEP_IDS] == [
        "intake",
        "requirements",
        "knowledge",
        "manufacturer",
        "response",
        "customer_reply",
        "complete",
    ]
    assert [step_button_key(step) for step in TECHNICAL_STEP_IDS] == [
        "technical_case_step_1",
        "technical_case_step_2",
        "technical_case_step_3",
        "technical_case_step_4",
        "technical_case_step_5",
        "technical_case_step_6",
        "technical_case_step_7",
    ]
    assert "provider" not in TECHNICAL_STEP_KEYS.values()


def test_empty_case_current_step_and_progress():
    summary = summarize_technical_case()
    workflow = build_technical_workflow(summary)
    assert infer_current_step(summary) == 1
    assert workflow.current_step == 1
    assert workflow.total == 7
    assert workflow.completed == 0
    assert workflow.step_status(1) == INFO_MISSING
    assert workflow.step_status(4) == INFO_NOT_STARTED
    assert workflow.step_status(7) == "INCOMPLETE"
    assert operations_are_blocked(summary) is False


def test_analyzed_case_current_step_is_manufacturer_review():
    run = _analyze()
    summary = summarize_technical_case(run=run)
    workflow = build_technical_workflow(summary)
    assert workflow.total == 7
    assert 2 <= workflow.completed < 7
    assert workflow.current_step == 4
    status, reviews = technical_step_status(4, summary)
    assert status == INFO_REVIEW_REQUIRED
    assert reviews >= 1
    assert workflow.step_state(4).badge_label().startswith("要確認")
    assert workflow.step_status(5) == INFO_NOT_STARTED
    assert workflow.step_status(6) == INFO_NOT_STARTED


def test_waiting_manufacturer_is_not_complete():
    record = build_record(_analyze())
    record.status = TechnicalCaseStatus.WAITING_MANUFACTURER.value
    summary = summarize_technical_case(record=record)
    workflow = build_technical_workflow(summary)
    assert workflow.step_status(4) in {INFO_REVIEW_REQUIRED, INFO_WAITING}
    assert workflow.step_status(7) != INFO_COMPLETE
    assert workflow.completed < 7
    assert infer_current_step(summary) == 4


def test_completed_case_uses_step_seven():
    record = build_record(_analyze())
    record.status = TechnicalCaseStatus.COMPLETED.value
    summary = summarize_technical_case(record=record)
    workflow = build_technical_workflow(summary)
    assert infer_current_step(summary) == 7
    assert workflow.current_step == 7
    assert workflow.step_status(7) == INFO_COMPLETE


def test_incomplete_steps_remain_navigable():
    summary = summarize_technical_case()
    workflow = build_technical_workflow(summary)
    assert operations_are_blocked(summary) is False
    for step in TECHNICAL_STEP_IDS:
        assert normalize_case_step(step) == step
        assert selected_or_current(step, workflow) == step
    assert selected_or_current(None, workflow) == 1
    assert normalize_case_step("x") == 1


def test_step_change_does_not_require_provider():
    session = {SESSION_CASE_STEP: 1}
    session[SESSION_CASE_STEP] = 5
    assert session[SESSION_CASE_STEP] == 5
    assert "provider" not in TECHNICAL_STEP_KEYS.values()
