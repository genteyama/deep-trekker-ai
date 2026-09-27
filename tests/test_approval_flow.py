from datetime import datetime, timezone

from agents.approval import (
    ERROR_ALREADY_APPLIED,
    HumanApprovalInput,
    apply_human_approval,
    build_approval_board,
    summarize_approvals,
)
from agents.technical_case_agent import run_manufacturer_response_analysis
from models import (
    AnswerSourceType,
    QuestionStatus,
    QuestionTarget,
    SuggestedQuestionStatus,
    TechnicalQuestion,
)

FIXED_TIME = datetime(2026, 9, 27, 1, 0, 0, tzinfo=timezone.utc)


def _question(question_id: str, text: str) -> TechnicalQuestion:
    return TechnicalQuestion(
        question_id=question_id,
        case_id="CASE-AP-001",
        target=QuestionTarget.MANUFACTURER,
        question=text,
        status=QuestionStatus.SENT,
        follow_up_required=False,
    )


def _board():
    run = run_manufacturer_response_analysis(
        [
            _question("Q-AP-001", "組み合わせは可能か"),
            _question("Q-AP-002", "同時搭載できるか"),
            _question("Q-AP-003", "水深は分かるか"),
        ],
        "メーカーからの返信サンプルです。",
    )
    return build_approval_board(run)


def test_ai_candidate_does_not_create_answer_or_change_status():
    board = _board()

    assert all(item.answer is None for item in board.items)
    assert all(item.approval is None for item in board.items)
    assert all(item.question.status == QuestionStatus.SENT for item in board.items)
    assert all(not item.is_applied for item in board.items)


def test_human_apply_creates_answer_and_updates_status():
    board = _board()
    result = apply_human_approval(
        board,
        "Q-AP-001",
        HumanApprovalInput(
            approved_status=SuggestedQuestionStatus.ANSWERED,
            approved_answer="組み合わせ可能です。",
            follow_up_required=False,
        ),
        approved_at=FIXED_TIME,
    )

    assert result.success is True
    item = board.get_item("Q-AP-001")
    assert item.is_applied is True
    assert item.answer is not None
    assert item.answer.question_id == "Q-AP-001"
    assert item.answer.answer == "組み合わせ可能です。"
    assert item.answer.answered_by is None
    assert item.answer.answered_at == FIXED_TIME
    assert item.answer.source_type == AnswerSourceType.MANUFACTURER_RESPONSE.value
    assert item.answer.original_text == "メーカーからの返信サンプルです。"
    assert item.question.status == QuestionStatus.ANSWERED
    assert item.question.status != QuestionStatus.CLOSED


def test_human_can_change_answered_to_partial():
    board = _board()
    apply_human_approval(
        board,
        "Q-AP-001",
        HumanApprovalInput(
            approved_status=SuggestedQuestionStatus.PARTIAL,
            approved_answer="一部だけ確認できました。",
            follow_up_required=True,
            follow_up_question="残りの条件を確認してください。",
        ),
        approved_at=FIXED_TIME,
    )
    item = board.get_item("Q-AP-001")

    assert item.ai_candidate.suggested_status == SuggestedQuestionStatus.ANSWERED
    assert item.approval.approved_status == SuggestedQuestionStatus.PARTIAL
    assert item.approval.ai_suggested_status == SuggestedQuestionStatus.ANSWERED
    assert item.approval.ai_suggested_answer != item.approval.approved_answer
    assert item.question.status == QuestionStatus.PARTIAL


def test_human_can_set_follow_up_required():
    board = _board()
    apply_human_approval(
        board,
        "Q-AP-002",
        HumanApprovalInput(
            approved_status=SuggestedQuestionStatus.FOLLOW_UP_REQUIRED,
            approved_answer=None,
            follow_up_required=False,
            follow_up_question="再確認してください。",
        ),
        approved_at=FIXED_TIME,
    )
    item = board.get_item("Q-AP-002")

    assert item.question.status == QuestionStatus.FOLLOW_UP_REQUIRED
    assert item.question.follow_up_required is True
    assert item.approval.approved_follow_up_required is True


def test_approval_keeps_ai_and_human_results_separately():
    board = _board()
    apply_human_approval(
        board,
        "Q-AP-001",
        HumanApprovalInput(
            approved_status=SuggestedQuestionStatus.PARTIAL,
            approved_answer="人が直した要約です。",
        ),
        approved_at=FIXED_TIME,
    )
    item = board.get_item("Q-AP-001")

    assert item.ai_candidate.answer_summary != "人が直した要約です。"
    assert item.approval.ai_suggested_answer == item.ai_candidate.answer_summary
    assert item.approval.approved_answer == "人が直した要約です。"
    assert item.approval.approved_at == FIXED_TIME


def test_answered_by_is_not_invented():
    board = _board()
    apply_human_approval(
        board,
        "Q-AP-001",
        HumanApprovalInput(approved_status=SuggestedQuestionStatus.ANSWERED),
        approved_at=FIXED_TIME,
    )

    assert board.get_item("Q-AP-001").answer.answered_by is None
    assert board.get_item("Q-AP-001").approval.approved_by is None


def test_same_question_is_not_applied_twice():
    board = _board()
    first = apply_human_approval(
        board,
        "Q-AP-001",
        HumanApprovalInput(
            approved_status=SuggestedQuestionStatus.ANSWERED,
            approved_answer="最初の反映",
        ),
        approved_at=FIXED_TIME,
    )
    second = apply_human_approval(
        board,
        "Q-AP-001",
        HumanApprovalInput(
            approved_status=SuggestedQuestionStatus.PARTIAL,
            approved_answer="二重反映",
        ),
        approved_at=FIXED_TIME,
    )

    assert first.success is True
    assert second.success is False
    assert second.error_code == ERROR_ALREADY_APPLIED
    assert board.get_item("Q-AP-001").answer.answer == "最初の反映"
    assert board.get_item("Q-AP-001").question.status == QuestionStatus.ANSWERED


def test_summary_tracks_applied_and_pending_by_question():
    board = _board()
    apply_human_approval(
        board,
        "Q-AP-001",
        HumanApprovalInput(approved_status=SuggestedQuestionStatus.ANSWERED),
        approved_at=FIXED_TIME,
    )
    apply_human_approval(
        board,
        "Q-AP-003",
        HumanApprovalInput(approved_status=SuggestedQuestionStatus.FOLLOW_UP_REQUIRED),
        approved_at=FIXED_TIME,
    )
    summary = summarize_approvals(board)

    assert summary["total"] == 3
    assert summary["applied"] == 2
    assert summary["pending"] == 1
    assert summary["answered"] == 1
    assert summary["partial"] == 0
    assert summary["follow_up_required"] == 1
    assert board.get_item("Q-AP-002").is_applied is False
    assert board.get_item("Q-AP-002").question.status == QuestionStatus.SENT
