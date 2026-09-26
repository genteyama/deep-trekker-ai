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


class MockTechnicalCaseProvider(TechnicalCaseProvider):
    name = "mock"

    def __init__(
        self,
        payload: Optional[dict] = None,
        error: Optional[Exception] = None,
    ) -> None:
        self._payload = payload
        self._error = error

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
