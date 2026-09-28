from typing import Optional

from llm.provider import ProviderError, TechnicalCaseProvider

DEFAULT_MOCK_PAYLOAD = {
    "case_summary": (
        "これは開発確認用の固定サンプルです。"
        "入力された問い合わせを解析した結果ではありません。"
    ),
    "requested_products": ["PipeTrekker"],
    "requirements": [
        {
            "category": "usage",
            "label": "点検対象",
            "value": "管内点検",
            "unit": None,
            "notes": "開発用サンプルです。入力文から抽出したものではありません。",
        },
        {
            "category": "environment",
            "label": "管内径",
            "value": None,
            "unit": "mm",
            "notes": "未確認のため、値は入れていません。",
        },
    ],
    "customer_questions": [
        {"question": "点検する管の内径と管種を教えてください。"},
        {"question": "走行距離と管内の障害物の有無を教えてください。"},
    ],
    "manufacturer_questions": [
        {"question": "指定された管条件で走行できる構成があるか確認してください。"},
    ],
    "technical_questions": [
        {"question": "顧客指定の製品を、推奨構成として扱っていないか確認してください。"},
    ],
    "unresolved_items": [
        {
            "label": "管内径",
            "notes": "値が未確認です。推測していません。",
        },
        {
            "label": "推奨製品",
            "notes": "正式な推奨は未確定です。",
        },
    ],
}


DEFAULT_RESPONSE_SUMMARY = (
    "これは開発確認用の固定サンプルです。"
    "入力されたメーカー回答を解析した結果ではありません。"
)


def build_default_manufacturer_response_payload(questions: Optional[list] = None) -> dict:
    matches = []
    for index, item in enumerate(questions or []):
        question_id = item.get("question_id") or f"Q-MOCK-{index + 1}"
        if index == 0:
            matches.append(
                {
                    "question_id": question_id,
                    "answer_summary": "開発用サンプルです。この質問には明確な回答があった体裁です。",
                    "suggested_status": "ANSWERED",
                    "follow_up_required": False,
                    "follow_up_question": None,
                    "confidence": "HIGH",
                    "evidence_text": "開発用の固定根拠です。",
                }
            )
        elif index == 1:
            matches.append(
                {
                    "question_id": question_id,
                    "answer_summary": "開発用サンプルです。一部だけ回答された体裁です。",
                    "suggested_status": "PARTIAL",
                    "follow_up_required": True,
                    "follow_up_question": "残りの条件を確認してください。",
                    "confidence": "MEDIUM",
                    "evidence_text": "一部の説明だけが含まれている体裁です。",
                }
            )
        else:
            matches.append(
                {
                    "question_id": question_id,
                    "answer_summary": None,
                    "suggested_status": "FOLLOW_UP_REQUIRED",
                    "follow_up_required": True,
                    "follow_up_question": "この質問への回答が見当たりません。再確認してください。",
                    "confidence": "LOW",
                    "evidence_text": None,
                }
            )

    return {
        "response_summary": DEFAULT_RESPONSE_SUMMARY,
        "matches": matches,
        "unmatched_information": [
            {
                "summary": "質問されていない追加情報の開発用サンプルです。",
                "original_text": "開発用の未対応情報です。TechnicalFactには登録しません。",
            }
        ],
        "overall_follow_up_required": True,
    }


class MockTechnicalCaseProvider(TechnicalCaseProvider):
    name = "mock"

    def __init__(
        self,
        payload: Optional[dict] = None,
        error: Optional[Exception] = None,
        response_payload: Optional[dict] = None,
        response_error: Optional[Exception] = None,
    ) -> None:
        self._payload = payload
        self._error = error
        self._response_payload = response_payload
        self._response_error = response_error

    def analyze_technical_case(
        self,
        inquiry_text: Optional[str],
        case_name: Optional[str] = None,
        customer_name: Optional[str] = None,
        end_user_name: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> dict:
        if self._error is not None:
            if isinstance(self._error, ProviderError):
                raise self._error
            raise ProviderError(str(self._error))
        if self._payload is not None:
            return self._payload
        return dict(DEFAULT_MOCK_PAYLOAD)

    def analyze_manufacturer_response(
        self,
        questions: list,
        response_text: Optional[str],
        system_prompt: Optional[str] = None,
    ) -> dict:
        if self._response_error is not None:
            if isinstance(self._response_error, ProviderError):
                raise self._response_error
            raise ProviderError(str(self._response_error))
        if self._response_payload is not None:
            return self._response_payload
        return build_default_manufacturer_response_payload(questions)

    def test_connection(self):
        from llm.provider import ConnectionTestResult

        return ConnectionTestResult(
            success=True,
            provider=self.name,
            model=None,
            fallbacks_enabled=False,
        )
