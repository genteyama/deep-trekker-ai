from agents.approval import HumanApprovalInput, apply_human_approval, build_approval_board
from agents.facts import (
    ERROR_DUPLICATE_FACT,
    ERROR_NO_ANSWER,
    ERROR_NOT_APPROVED,
    FACT_STATUS_HUMAN_REGISTERED,
    WARNING_REUSABLE,
    WARNING_TIME_SENSITIVE_REUSABLE,
    FactRegistrationInput,
    draft_fact_candidate,
    fact_registration_warnings,
    looks_like_spaceone_derived_holding_force,
    register_technical_fact,
)
from agents.technical_case_agent import run_manufacturer_response_analysis
from models import (
    ApprovalRecord,
    FactConfidence,
    FactScope,
    QuestionStatus,
    QuestionTarget,
    SuggestedQuestionStatus,
    TechnicalQuestion,
)


def _question(question_id: str, text: str) -> TechnicalQuestion:
    return TechnicalQuestion(
        question_id=question_id,
        case_id="CASE-FACT-001",
        target=QuestionTarget.MANUFACTURER,
        question=text,
        status=QuestionStatus.SENT,
    )


def _unapproved_item():
    run = run_manufacturer_response_analysis(
        [_question("Q-FACT-001", "面移動できるか")],
        "メーカーからの返信サンプルです。",
    )
    return build_approval_board(run).items[0]


def _approved_item_clean(answer="MAGは異なる面へ連続して移動できない。"):
    run = run_manufacturer_response_analysis(
        [_question("Q-FACT-001", "面移動できるか")],
        "メーカーからの返信サンプルです。",
    )
    board = build_approval_board(run)
    apply_human_approval(
        board,
        "Q-FACT-001",
        HumanApprovalInput(
            approved_status=SuggestedQuestionStatus.ANSWERED,
            approved_answer=answer,
        ),
    )
    return board.get_item("Q-FACT-001")


def test_unapproved_ai_candidate_cannot_create_fact():
    item = _unapproved_item()
    draft = draft_fact_candidate(item)
    result = register_technical_fact(
        item,
        FactRegistrationInput(fact="仮のFact", scope=FactScope.CASE_ONLY),
    )

    assert draft is None
    assert result.success is False
    assert result.error_code == ERROR_NOT_APPROVED
    assert item.registered_facts == []


def test_fact_cannot_be_created_without_technical_answer():
    item = _unapproved_item()
    item.approval = ApprovalRecord(
        approval_id="APR-NO-ANSWER",
        question_id=item.question.question_id,
        approved_status=SuggestedQuestionStatus.ANSWERED,
        approved_answer="承認だけ先に進んだ体裁",
    )
    result = register_technical_fact(
        item,
        FactRegistrationInput(fact="仮のFact", scope=FactScope.CASE_ONLY),
    )

    assert item.is_applied is True
    assert item.answer is None
    assert result.success is False
    assert result.error_code == ERROR_NO_ANSWER
    assert item.registered_facts == []


def test_fact_is_created_only_after_human_registration():
    item = _approved_item_clean()
    assert item.registered_facts == []

    result = register_technical_fact(
        item,
        FactRegistrationInput(
            product="MAG Utility Crawler",
            topic="surface_transition",
            fact="MAGは異なる面へ連続して移動できない。",
            scope=FactScope.PRODUCT_REUSABLE,
            confidence=FactConfidence.MANUFACTURER_CONFIRMED,
        ),
    )

    assert result.success is True
    assert result.fact.status == FACT_STATUS_HUMAN_REGISTERED
    assert result.fact.scope == FactScope.PRODUCT_REUSABLE
    assert result.fact.confidence == FactConfidence.MANUFACTURER_CONFIRMED
    assert "answer_id=" in result.fact.source_reference
    assert "question_id=" in result.fact.source_reference
    assert "approval_id=" in result.fact.source_reference


def test_case_only_and_product_reusable_can_be_registered():
    item = _approved_item_clean("PHOTON + Cygnusを提案する")
    case_only = register_technical_fact(
        item,
        FactRegistrationInput(
            product="PHOTON",
            topic="ihi_tank_proposal",
            fact="今回の水中タンク内部ではPHOTON + Cygnusを提案する",
            scope=FactScope.CASE_ONLY,
            confidence=FactConfidence.SPACEONE_VERIFIED,
        ),
    )
    reusable = register_technical_fact(
        item,
        FactRegistrationInput(
            product="MAG Utility Crawler",
            topic="positioning",
            fact="水深・高度・テザー繰出量を利用して構造物上の自己位置を把握する機能はない",
            scope=FactScope.PRODUCT_REUSABLE,
            confidence=FactConfidence.MANUFACTURER_CONFIRMED,
        ),
    )

    assert case_only.fact.scope == FactScope.CASE_ONLY
    assert reusable.fact.scope == FactScope.PRODUCT_REUSABLE
    assert len(item.registered_facts) == 2


def test_time_sensitive_flag_and_reusable_warning():
    warnings = fact_registration_warnings(FactScope.PRODUCT_REUSABLE, True)
    item = _approved_item_clean("納期は約5か月")
    result = register_technical_fact(
        item,
        FactRegistrationInput(
            product="MAG Utility Crawler",
            topic="lead_time",
            fact="MAG納期 約5か月",
            scope=FactScope.PRODUCT_REUSABLE,
            is_time_sensitive=True,
            confidence=FactConfidence.SPACEONE_VERIFIED,
        ),
    )

    assert WARNING_REUSABLE in warnings
    assert WARNING_TIME_SENSITIVE_REUSABLE in warnings
    assert result.success is True
    assert result.fact.is_time_sensitive is True


def test_manufacturer_confirmed_is_only_set_by_human_registration():
    item = _approved_item_clean()
    draft = draft_fact_candidate(item)
    result = register_technical_fact(
        item,
        FactRegistrationInput(
            product="MAG Utility Crawler",
            topic="surface_transition",
            fact="MAGは異なる面へ連続して移動できない。",
            scope=FactScope.PRODUCT_REUSABLE,
            confidence=FactConfidence.MANUFACTURER_CONFIRMED,
        ),
    )

    assert draft.suggested_confidence == FactConfidence.AI_EXTRACTED_UNVERIFIED
    assert draft.suggested_confidence != FactConfidence.MANUFACTURER_CONFIRMED
    assert result.fact.confidence == FactConfidence.MANUFACTURER_CONFIRMED


def test_duplicate_fact_is_blocked_but_same_answer_can_have_other_topics():
    item = _approved_item_clean()
    first = register_technical_fact(
        item,
        FactRegistrationInput(
            product="MAG Utility Crawler",
            topic="surface_transition",
            fact="MAGは異なる面へ連続して移動できない。",
            scope=FactScope.PRODUCT_REUSABLE,
            confidence=FactConfidence.MANUFACTURER_CONFIRMED,
        ),
    )
    duplicate = register_technical_fact(
        item,
        FactRegistrationInput(
            product="MAG Utility Crawler",
            topic="surface_transition",
            fact="MAGは異なる面へ連続して移動できない。",
            scope=FactScope.PRODUCT_REUSABLE,
            confidence=FactConfidence.MANUFACTURER_CONFIRMED,
        ),
    )
    other_topic = register_technical_fact(
        item,
        FactRegistrationInput(
            product="MAG Utility Crawler",
            topic="positioning",
            fact="水深・高度・テザー繰出量を利用して構造物上の自己位置を把握する機能はない",
            scope=FactScope.PRODUCT_REUSABLE,
            confidence=FactConfidence.MANUFACTURER_CONFIRMED,
        ),
    )

    assert first.success is True
    assert duplicate.success is False
    assert duplicate.error_code == ERROR_DUPLICATE_FACT
    assert other_topic.success is True
    assert len(item.registered_facts) == 2


def test_wheel_force_keeps_conditions_and_does_not_treat_45kgf_as_manufacturer_guarantee():
    item = _approved_item_clean("マグネットホイールは無垢鋼板面で1輪あたり50 lb")
    result = register_technical_fact(
        item,
        FactRegistrationInput(
            product="MAG Utility Crawler",
            topic="magnet_wheel",
            fact="無垢の鋼板面に対して1輪あたり50 lb",
            scope=FactScope.PRODUCT_REUSABLE,
            confidence=FactConfidence.MANUFACTURER_CONFIRMED,
            notes="条件: 無垢鋼板面、1輪あたり。約45kgfはSpaceOneの単純合計でありメーカー保証値ではない。",
        ),
    )

    assert "無垢" in result.fact.fact
    assert "1輪" in result.fact.fact
    assert "50 lb" in result.fact.fact
    assert looks_like_spaceone_derived_holding_force(result.fact.notes) is True
    assert looks_like_spaceone_derived_holding_force(result.fact.fact) is False
    assert "保証" in result.fact.notes


def test_case_only_recommendation_is_not_auto_converted_to_product_fact():
    item = _approved_item_clean("今回の水中タンク内部ではPHOTON + Cygnusを提案する")
    draft = draft_fact_candidate(item)

    assert draft.scope == FactScope.CASE_ONLY
    assert item.registered_facts == []
    assert draft.fact != "PHOTONはすべてのタンク肉厚測定に適している"
