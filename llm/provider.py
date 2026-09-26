from abc import ABC, abstractmethod
import os
from typing import Optional


class ProviderError(Exception):
    pass


class TechnicalCaseProvider(ABC):
    name = "base"

    @abstractmethod
    def analyze_technical_case(
        self,
        inquiry_text: Optional[str],
        case_name: Optional[str] = None,
        customer_name: Optional[str] = None,
        end_user_name: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> dict:
        raise NotImplementedError


def get_technical_case_provider(
    provider_name: Optional[str] = None,
) -> TechnicalCaseProvider:
    from llm.mock_provider import MockTechnicalCaseProvider

    selected = (provider_name or os.getenv("TECHNICAL_CASE_PROVIDER") or "mock")
    selected = selected.strip().lower()
    if selected == "mock":
        return MockTechnicalCaseProvider()

    raise ProviderError(f"Provider '{selected}' is not available yet")
