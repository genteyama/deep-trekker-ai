from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ExtractedRequirement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    category: Optional[str] = None
    label: Optional[str] = None
    value: Optional[str] = None
    unit: Optional[str] = None
    notes: Optional[str] = None


class ExtractedQuestion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question: Optional[str] = None


class UnresolvedItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: Optional[str] = None
    notes: Optional[str] = None


class TechnicalCaseAnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    case_summary: Optional[str] = None
    requested_products: list[str] = Field(default_factory=list)
    requirements: list[ExtractedRequirement] = Field(default_factory=list)
    customer_questions: list[ExtractedQuestion] = Field(default_factory=list)
    manufacturer_questions: list[ExtractedQuestion] = Field(default_factory=list)
    technical_questions: list[ExtractedQuestion] = Field(default_factory=list)
    unresolved_items: list[UnresolvedItem] = Field(default_factory=list)
