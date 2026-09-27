from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from models.enums import (
    FactConfidence,
    MatchConfidence,
    QuestionStatus,
    QuestionTarget,
    RecommendationOrigin,
    RelationType,
    SuggestedQuestionStatus,
    ValidationSeverity,
)


class Case(BaseModel):
    case_id: str
    case_name: Optional[str] = None
    customer_name: Optional[str] = None
    end_user_name: Optional[str] = None
    status: Optional[str] = None
    requested_products: list[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CaseRequirement(BaseModel):
    requirement_id: str
    case_id: str
    category: Optional[str] = None
    label: Optional[str] = None
    value: Optional[str] = None
    unit: Optional[str] = None
    source: Optional[str] = None
    confirmed: bool = False
    notes: Optional[str] = None


class TechnicalQuestion(BaseModel):
    question_id: str
    case_id: str
    target: Optional[QuestionTarget] = None
    question: Optional[str] = None
    status: Optional[QuestionStatus] = None
    follow_up_required: bool = False
    created_at: Optional[datetime] = None


class ResponseMatchCandidate(BaseModel):
    question_id: str
    answer_summary: Optional[str] = None
    suggested_status: Optional[SuggestedQuestionStatus] = None
    follow_up_required: bool = False
    follow_up_question: Optional[str] = None
    confidence: Optional[MatchConfidence] = None
    evidence_text: Optional[str] = None


class UnmatchedInformation(BaseModel):
    summary: Optional[str] = None
    original_text: Optional[str] = None


class ManufacturerResponseAnalysis(BaseModel):
    response_summary: Optional[str] = None
    matches: list[ResponseMatchCandidate] = Field(default_factory=list)
    unmatched_information: list[UnmatchedInformation] = Field(default_factory=list)
    overall_follow_up_required: bool = False


class ApprovalRecord(BaseModel):
    approval_id: str
    question_id: str
    approved_status: SuggestedQuestionStatus
    approved_answer: Optional[str] = None
    approved_follow_up_required: bool = False
    approved_follow_up_question: Optional[str] = None
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None
    ai_suggested_status: Optional[SuggestedQuestionStatus] = None
    ai_suggested_answer: Optional[str] = None
    ai_suggested_follow_up_question: Optional[str] = None


class TechnicalAnswer(BaseModel):
    answer_id: str
    question_id: str
    answer: Optional[str] = None
    answered_by: Optional[str] = None
    answered_at: Optional[datetime] = None
    source_type: Optional[str] = None
    confidence: Optional[str] = None
    original_text: Optional[str] = None


class TechnicalFact(BaseModel):
    fact_id: str
    case_id: str
    product: Optional[str] = None
    topic: Optional[str] = None
    fact: Optional[str] = None
    source_type: Optional[str] = None
    source_reference: Optional[str] = None
    confidence: Optional[FactConfidence] = None
    status: Optional[str] = None


class ConfigurationItem(BaseModel):
    sku: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[int] = None
    notes: Optional[str] = None


class Configuration(BaseModel):
    configuration_id: str
    case_id: str
    name: Optional[str] = None
    description: Optional[str] = None
    recommendation_origin: Optional[RecommendationOrigin] = None
    status: Optional[str] = None
    items: list[ConfigurationItem] = Field(default_factory=list)


class SKU(BaseModel):
    sku: str
    product_family: Optional[str] = None
    model: Optional[str] = None
    description: Optional[str] = None
    msrp_usd: Optional[float] = None
    dealer_price_usd: Optional[float] = None
    dealer_rate: Optional[float] = None
    notes: Optional[str] = None
    source_price_book: Optional[str] = None
    source_sheet: Optional[str] = None
    price_book_version: Optional[str] = None
    effective_date: Optional[datetime] = None
    last_synced_at: Optional[datetime] = None


class SKURelation(BaseModel):
    source_sku: str
    relation_type: RelationType
    target_sku: str
    notes: Optional[str] = None
    status: Optional[str] = None


class SupplierQuoteLine(BaseModel):
    sku: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[int] = None
    unit_price_usd: Optional[float] = None
    line_total_usd: Optional[float] = None
    discount: Optional[float] = None
    notes: Optional[str] = None
    extraction_confidence: Optional[str] = None


class SupplierQuote(BaseModel):
    supplier_quote_id: str
    case_id: str
    quote_number: Optional[str] = None
    version: Optional[str] = None
    quote_date: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    supplier_contact: Optional[str] = None
    currency: Optional[str] = None
    lines: list[SupplierQuoteLine] = Field(default_factory=list)
    shipping_usd: Optional[float] = None
    insurance_usd: Optional[float] = None
    total_usd: Optional[float] = None
    lead_time: Optional[str] = None
    source_file: Optional[str] = None


class ValidationResult(BaseModel):
    validation_id: str
    case_id: str
    validation_type: Optional[str] = None
    severity: Optional[ValidationSeverity] = None
    status_code: Optional[str] = None
    message: Optional[str] = None
    sku: Optional[str] = None
    details: Optional[str] = None
    requires_human_review: bool = False


class PricingPolicy(BaseModel):
    exchange_rate: Optional[float] = None
    import_cost_rate: Optional[float] = None
    insurance_rate: Optional[float] = None
    domestic_shipping_jpy: Optional[float] = None
    target_gross_margin_rate: Optional[float] = None
    rounding_unit: Optional[float] = None


class CostScenario(BaseModel):
    cost_scenario_id: str
    case_id: str
    configuration_id: Optional[str] = None
    exchange_rate: Optional[float] = None
    product_cost_jpy: Optional[float] = None
    international_shipping_jpy: Optional[float] = None
    insurance_jpy: Optional[float] = None
    import_cost_jpy: Optional[float] = None
    domestic_shipping_jpy: Optional[float] = None
    landed_cost_jpy: Optional[float] = None
    suggested_sales_price_jpy: Optional[float] = None
    approved_sales_price_jpy: Optional[float] = None
    gross_profit_jpy: Optional[float] = None
    gross_margin_rate: Optional[float] = None
    status: Optional[str] = None
