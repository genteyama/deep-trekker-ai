from agents.question_review import apply_question_review, default_review_status
from agents.technical_case_agent import run_manufacturer_response_analysis, run_technical_case_analysis
from agents.technical_case_persistence import (
    build_record,
    record_contains_secrets,
    response_run_from_record,
    revision_from_response_run,
    run_from_record,
)
from llm.mock_provider import DEFAULT_MOCK_PAYLOAD, MockTechnicalCaseProvider
from models import (
    QuestionReviewStatus,
    QuestionStatus,
    QuestionTarget,
    TechnicalCaseRecord,
    TechnicalCaseStatus,
    TechnicalQuestion,
)
from repositories.sqlite import loads_json
from repositories.sqlite_quote_repository import SqliteQuoteRepository
from repositories.sqlite_technical_case_repository import SqliteTechnicalCaseRepository
from tests.test_quote_builder import _photon_draft
from ui.technical_case_persistence import resume_case_into_session, start_new_technical_case


def _repo(tmp_path) -> SqliteTechnicalCaseRepository:
    return SqliteTechnicalCaseRepository(tmp_path / "ops.sqlite3")


def _analyze(provider=None):
    return run_technical_case_analysis(
        "管内点検",
        "サンプル株式会社",
        None,
        "直径300mmの管を点検したい。",
        provider=provider or MockTechnicalCaseProvider(),
    )


def test_technical_case_save_and_read(tmp_path):
    repo = _repo(tmp_path)
    run = _analyze()
    record = build_record(run)
    repo.save_case(record)
    loaded = repo.get_case(record.case_id)
    assert loaded is not None
    assert loaded.case_title == "管内点検"
    assert loaded.customer_name == "サンプル株式会社"
    assert loaded.original_inquiry == "直径300mmの管を点検したい。"
    assert loaded.provider == "mock"
    assert loaded.status == TechnicalCaseStatus.ANALYZED.value
    assert loaded.schema_version == 1


def test_recent_list_and_resume(tmp_path):
    repo = _repo(tmp_path)
    run = _analyze()
    repo.save_case(build_record(run))
    recent = repo.list_recent_cases()
    assert recent[0].case_id == run.case.case_id
    assert recent[0].customer_name == "サンプル株式会社"
    loaded = repo.get_case(recent[0].case_id)
    restored = run_from_record(loaded)
    assert restored.inquiry_text == run.inquiry_text
    assert restored.case_summary == run.case_summary
    assert restored.provider_name == "mock"


def test_knowledge_snapshot_is_immutable_after_save(tmp_path):
    repo = _repo(tmp_path)
    run = run_technical_case_analysis(
        "MAG",
        "顧客",
        None,
        "MAG Utility Crawlerで測定した場所を把握したい。",
        provider=MockTechnicalCaseProvider(),
    )
    original = run.knowledge_snapshot.as_dict()
    repo.save_case(build_record(run))
    run.knowledge_snapshot.items[0].statement = "mutated after save"
    loaded = repo.get_case(run.case.case_id)
    assert loaded.knowledge_snapshot["items"][0]["statement"] == original["items"][0]["statement"]
    assert loaded.knowledge_snapshot["items"][0]["fact_id"] == original["items"][0]["fact_id"]
    assert loaded.knowledge_snapshot["items"][0]["source_reference"] == original["items"][0]["source_reference"]


def test_question_human_review_keeps_edited_original(tmp_path):
    repo = _repo(tmp_path)
    run = _analyze()
    question = run.manufacturer_questions[0]
    updated = apply_question_review(question, "EDITED", "人が直したメーカー確認")
    run.manufacturer_questions[0] = updated
    repo.save_case(build_record(run))
    loaded = repo.get_case(run.case.case_id)
    review = loaded.question_human_reviews[0]
    assert review.review_status == "EDITED"
    assert review.ai_original == question.ai_original_question or question.question
    assert review.human_edited == "人が直したメーカー確認"
    restored = TechnicalQuestion.model_validate(loaded.manufacturer_questions[0])
    assert restored.question == "人が直したメーカー確認"
    assert restored.ai_original_question == (question.ai_original_question or question.question)


def test_ai_suggested_is_not_auto_approved_on_save(tmp_path):
    repo = _repo(tmp_path)
    run = _analyze()
    suggested = TechnicalQuestion(
        question_id="Q-AI",
        case_id=run.case.case_id,
        target=QuestionTarget.MANUFACTURER,
        question="一般知識の確認",
        status=QuestionStatus.DRAFT,
        classification="AI_SUGGESTED",
        source="AI_SUGGESTED",
        review_status=default_review_status(
            TechnicalQuestion(question_id="TMP", case_id=run.case.case_id, classification="AI_SUGGESTED")
        ),
        ai_original_question="一般知識の確認",
    )
    assert suggested.review_status == QuestionReviewStatus.PENDING.value
    run.manufacturer_questions.append(suggested)
    repo.save_case(build_record(run))
    loaded = repo.get_case(run.case.case_id)
    saved = next(item for item in loaded.question_human_reviews if item.question_id == "Q-AI")
    assert saved.review_status == "PENDING"


def test_manufacturer_response_revision_is_appended(tmp_path):
    repo = _repo(tmp_path)
    run = _analyze()
    repo.save_case(build_record(run))
    first = run_manufacturer_response_analysis(run.manufacturer_questions, "メーカーからの返信サンプルです。")
    second = run_manufacturer_response_analysis(run.manufacturer_questions, "メーカーからの返信サンプルです。再解析。")
    repo.save_manufacturer_response_result(run.case.case_id, revision_from_response_run(first))
    repo.save_manufacturer_response_result(run.case.case_id, revision_from_response_run(second))
    loaded = repo.get_case(run.case.case_id)
    assert len(loaded.response_revisions) == 2
    assert loaded.response_revisions[0].original_response == "メーカーからの返信サンプルです。"
    assert loaded.response_revisions[1].original_response == "メーカーからの返信サンプルです。再解析。"
    assert loaded.manufacturer_response_input == "メーカーからの返信サンプルです。再解析。"
    assert loaded.status == TechnicalCaseStatus.MANUFACTURER_RESPONSE_RECEIVED.value


def test_provider_model_snapshot_is_kept_on_resume(tmp_path):
    repo = _repo(tmp_path)
    run = _analyze()
    run.model = "qwen3.5:9b"
    run.provider_name = "ollama"
    repo.save_case(build_record(run))
    loaded = repo.get_case(run.case.case_id)
    assert loaded.provider == "ollama"
    assert loaded.model == "qwen3.5:9b"
    session = {}
    resume_case_into_session(loaded, session)
    assert session["technical_case_run"].provider_name == "ollama"
    assert session["technical_case_run"].model == "qwen3.5:9b"


def test_resume_does_not_reanalyze(tmp_path):
    calls = {"technical_case": 0, "manufacturer_response": 0}

    class CountingProvider(MockTechnicalCaseProvider):
        name = "counting"

        def analyze_technical_case(self, **kwargs):
            calls["technical_case"] += 1
            return dict(DEFAULT_MOCK_PAYLOAD)

        def analyze_manufacturer_response(self, **kwargs):
            calls["manufacturer_response"] += 1
            return super().analyze_manufacturer_response(**kwargs)

    provider = CountingProvider()
    run = _analyze(provider)
    repo = _repo(tmp_path)
    repo.save_case(build_record(run))
    loaded = repo.get_case(run.case.case_id)
    session = {}
    resume_case_into_session(loaded, session)
    assert calls["technical_case"] == 1
    assert calls["manufacturer_response"] == 0
    assert session["input_customer_inquiry"] == run.inquiry_text
    start_new_technical_case(session)
    assert "technical_case_run" not in session


def test_quote_persistence_unchanged_on_same_database(tmp_path):
    path = tmp_path / "shared.sqlite3"
    quotes = SqliteQuoteRepository(path)
    cases = SqliteTechnicalCaseRepository(path)
    draft = _photon_draft()
    quotes.save_draft(draft, {"step": 2})
    run = _analyze()
    cases.save_case(build_record(run))
    loaded_quote = quotes.get_draft(draft.quote_draft_id)
    assert loaded_quote is not None
    assert loaded_quote.draft.quote_draft_id == draft.quote_draft_id
    tables = {
        row[0]
        for row in quotes._connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "quote_drafts" in tables
    assert "approved_quote_snapshots" in tables
    assert "technical_cases" in tables


def test_api_keys_and_thinking_are_not_saved(tmp_path):
    repo = _repo(tmp_path)
    run = _analyze()
    run.analysis_json = {
        "case_summary": "ok",
        "api_key": "secret-value",
        "GEMINI_API_KEY": "AIzaSyDummyKeyValue12",
        "thinking": "hidden chain",
        "notes": "plain",
    }
    run.error_details = "failed key=AIzaSyDummyKeyValue12"
    record = build_record(run)
    repo.save_case(record)
    loaded = repo.get_case(run.case.case_id)
    raw = repo._connection.execute(
        "SELECT payload_json FROM technical_cases WHERE case_id = ?",
        (run.case.case_id,),
    ).fetchone()["payload_json"]
    payload = loads_json(raw)
    assert "api_key" not in (payload.get("analysis_json") or {})
    assert "thinking" not in (payload.get("analysis_json") or {})
    assert "AIzaSyDummyKeyValue12" not in raw
    assert "secret-value" not in raw
    assert record_contains_secrets(loaded) is False


def test_response_run_roundtrip_keeps_validation(tmp_path):
    repo = _repo(tmp_path)
    run = _analyze()
    repo.save_case(build_record(run))
    response = run_manufacturer_response_analysis(run.manufacturer_questions, "メーカーからの返信サンプルです。")
    saved = repo.save_manufacturer_response_result(run.case.case_id, revision_from_response_run(response))
    restored = response_run_from_record(saved)
    assert restored is not None
    assert restored.original_response_text == "メーカーからの返信サンプルです。"
    assert restored.matches
    assert saved.validated_matches
    assert saved.evidence_validation_result
