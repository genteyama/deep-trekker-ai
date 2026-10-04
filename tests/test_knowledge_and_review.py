from copy import deepcopy

from agents.knowledge import build_knowledge_snapshot, selected_catalog_facts
from agents.question_review import apply_question_review, is_auto_approvable
from agents.technical_case_agent import run_technical_case_analysis
from llm.mock_provider import DEFAULT_MOCK_PAYLOAD, MockTechnicalCaseProvider
from models import QuestionReviewStatus, QuestionStatus, QuestionTarget, TechnicalQuestion


MAG_INQUIRY = (
    "MAG Utility Crawlerで鋼製円筒タンクの水中肉厚測定を検討。"
    "側面と底面。測定した場所を把握したい。"
)


def test_unselected_knowledge_is_not_sent_to_provider():
    captured = {}

    class CaptureProvider(MockTechnicalCaseProvider):
        name = "capture"

        def analyze_technical_case(self, **kwargs):
            captured.update(kwargs)
            return dict(DEFAULT_MOCK_PAYLOAD)

    run = run_technical_case_analysis(
        "案件",
        "顧客",
        None,
        MAG_INQUIRY,
        provider=CaptureProvider(),
        selected_fact_ids=["FACT-MAG-SELF-POSITION"],
    )
    sent_ids = [item["fact_id"] for item in captured["approved_technical_facts"]]
    assert sent_ids == ["FACT-MAG-SELF-POSITION"]
    assert [item.fact_id for item in run.knowledge_snapshot.selected_facts()] == ["FACT-MAG-SELF-POSITION"]
    unused = [item.fact_id for item in run.knowledge_snapshot.items if not item.selected]
    assert "FACT-MAG-CYGNUS" in unused


def test_knowledge_snapshot_preserves_source_and_is_immutable():
    snapshot = build_knowledge_snapshot(["MAG Utility Crawler"])
    original = deepcopy(snapshot.as_dict())
    catalog = selected_catalog_facts(["MAG Utility Crawler"])
    catalog[0]["fact"] = "mutated later"
    assert snapshot.items[0].statement == original["items"][0]["statement"]
    assert snapshot.items[0].source_reference.startswith("IHI-TECH-001-MR-001")
    assert snapshot.retrieved_at == snapshot.items[0].retrieved_at


def test_ai_suggested_is_not_auto_approved():
    question = TechnicalQuestion(
        question_id="Q-1",
        case_id="CASE-1",
        target=QuestionTarget.MANUFACTURER,
        question="一般知識の確認",
        status=QuestionStatus.DRAFT,
        classification="AI_SUGGESTED",
        source="AI_SUGGESTED",
        review_status=QuestionReviewStatus.PENDING.value,
    )
    assert is_auto_approvable(question) is False
    approved = apply_question_review(question, "APPROVED")
    assert approved.review_status == "APPROVED"
    rejected = apply_question_review(question, "REJECTED")
    assert rejected.review_status == "REJECTED"
    edited = apply_question_review(question, "EDITED", "人が直した質問")
    assert edited.review_status == "EDITED"
    assert edited.question == "人が直した質問"
