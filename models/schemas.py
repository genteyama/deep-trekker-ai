from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from models.enums import (
    DestinationRegion,
    FactConfidence,
    FactScope,
    MatchConfidence,
    MatchStatus,
    PriceBookDiffType,
    QuestionStatus,
    QuestionTarget,
    RecommendationOrigin,
    RecordStatus,
    RelationType,
    ShippingScopeType,
    ShippingType,
    SkuDuplicateClass,
    SkuSourceStatus,
    SuggestedQuestionStatus,
    UpdateCategory,
    UpdateConfidence,
    UpdateSourceType,
    ValidationSeverity,
    YesNoUnknown,
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


class TechnicalFactCandidate(BaseModel):
    fact_candidate_id: str
    case_id: Optional[str] = None
    question_id: Optional[str] = None
    answer_id: Optional[str] = None
    product: Optional[str] = None
    topic: Optional[str] = None
    fact: Optional[str] = None
    scope: Optional[FactScope] = None
    source_type: Optional[str] = None
    source_reference: Optional[str] = None
    suggested_confidence: Optional[FactConfidence] = None
    notes: Optional[str] = None
    is_time_sensitive: bool = False


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
    scope: Optional[FactScope] = None
    is_time_sensitive: bool = False
    notes: Optional[str] = None


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
    dealer_equals_msrp: bool = False
    no_dealer_discount_note: bool = False
    notes: Optional[str] = None
    source_price_book: Optional[str] = None
    source_sheet: Optional[str] = None
    source_row: Optional[int] = None
    source_status: Optional[SkuSourceStatus] = SkuSourceStatus.ACTIVE
    price_book_version: Optional[str] = None
    effective_date: Optional[datetime] = None
    last_synced_at: Optional[datetime] = None


class SKUSourceOccurrence(BaseModel):
    sku: str
    source_price_book: Optional[str] = None
    source_sheet: Optional[str] = None
    source_row: Optional[int] = None
    description: Optional[str] = None
    msrp_usd: Optional[float] = None
    dealer_price_usd: Optional[float] = None
    notes: Optional[str] = None
    source_status: Optional[SkuSourceStatus] = SkuSourceStatus.ACTIVE
    dealer_equals_msrp: bool = False
    no_dealer_discount_note: bool = False


class SKUMasterCandidate(BaseModel):
    sku: str
    description: Optional[str] = None
    msrp_usd: Optional[float] = None
    dealer_price_usd: Optional[float] = None
    dealer_rate: Optional[float] = None
    dealer_equals_msrp: bool = False
    no_dealer_discount_note: bool = False
    source_status: Optional[SkuSourceStatus] = SkuSourceStatus.ACTIVE
    occurrence_count: int = 1
    duplicate_class: Optional[SkuDuplicateClass] = None
    occurrences: list[SKUSourceOccurrence] = Field(default_factory=list)


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


class PriceBookIssue(BaseModel):
    severity: ValidationSeverity
    code: str
    message: str
    sku: Optional[str] = None
    source_sheet: Optional[str] = None
    details: Optional[str] = None


class PriceBookSheetSummary(BaseModel):
    sheet_name: str
    product_family: Optional[str] = None
    model: Optional[str] = None
    item_count: int = 0
    header_found: bool = False
    skipped: bool = False
    skip_reason: Optional[str] = None
    source_status: Optional[SkuSourceStatus] = None


class PriceBookImportResult(BaseModel):
    source_price_book: Optional[str] = None
    version: Optional[str] = None
    imported_at: Optional[datetime] = None
    sheets: list[PriceBookSheetSummary] = Field(default_factory=list)
    items: list[SKU] = Field(default_factory=list)
    occurrences: list[SKUSourceOccurrence] = Field(default_factory=list)
    candidates: list[SKUMasterCandidate] = Field(default_factory=list)
    warnings: list[PriceBookIssue] = Field(default_factory=list)
    errors: list[PriceBookIssue] = Field(default_factory=list)
    infos: list[PriceBookIssue] = Field(default_factory=list)


class PriceBookDiffItem(BaseModel):
    sku: str
    change_types: list[PriceBookDiffType] = Field(default_factory=list)
    old_msrp: Optional[float] = None
    new_msrp: Optional[float] = None
    old_dealer_price: Optional[float] = None
    new_dealer_price: Optional[float] = None
    old_description: Optional[str] = None
    new_description: Optional[str] = None
    old_notes: Optional[str] = None
    new_notes: Optional[str] = None


class PriceBookDiff(BaseModel):
    items: list[PriceBookDiffItem] = Field(default_factory=list)

    def count(self, change_type: PriceBookDiffType) -> int:
        return sum(1 for item in self.items if change_type in item.change_types)


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


SHIPPING_RULE_PRIORITY = (
    "SUPPLIER_QUOTE_CASE_SPECIFIC",
    "MANUFACTURER_CASE_SPECIFIC_REPLY",
    "LATEST_DEALER_UPDATE_STANDARD",
    "PAST_CASE_ACTUAL",
    "UNKNOWN_NEEDS_REVIEW",
)


class ShippingRule(BaseModel):
    shipping_rule_id: str
    shipping_type: Optional[ShippingType] = None
    destination_region: Optional[DestinationRegion] = None
    rate_usd: Optional[float] = None
    currency: str = "USD"
    dangerous_goods: YesNoUnknown = YesNoUnknown.UNKNOWN
    battery_included: YesNoUnknown = YesNoUnknown.UNKNOWN
    product_scope: Optional[str] = None
    sku_scope: list[str] = Field(default_factory=list)
    case_id: Optional[str] = None
    scope_type: ShippingScopeType = ShippingScopeType.STANDARD
    source_type: Optional[str] = None
    source_reference: Optional[str] = None
    announced_at: Optional[datetime] = None
    effective_from: Optional[datetime] = None
    effective_until: Optional[datetime] = None
    status: RecordStatus = RecordStatus.CANDIDATE
    notes: Optional[str] = None
    update_candidate_id: Optional[str] = None


class UpdateSource(BaseModel):
    update_source_id: str
    source_type: Optional[UpdateSourceType] = None
    source_title: Optional[str] = None
    source_sender: Optional[str] = None
    source_date: Optional[datetime] = None
    source_text: Optional[str] = None
    source_reference: Optional[str] = None
    imported_at: Optional[datetime] = None


class UpdateCandidate(BaseModel):
    update_candidate_id: str
    update_source_id: str
    category: Optional[UpdateCategory] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    product: Optional[str] = None
    sku: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    unit: Optional[str] = None
    effective_from: Optional[datetime] = None
    is_time_sensitive: bool = False
    confidence: Optional[UpdateConfidence] = None
    status: RecordStatus = RecordStatus.CANDIDATE
    notes: Optional[str] = None
    target_master: Optional[str] = None


class CellReference(BaseModel):
    workbook: Optional[str] = None
    workbook_id: Optional[str] = None
    sheet: Optional[str] = None
    cell: Optional[str] = None
    formula: Optional[str] = None


class SpaceOneValues(BaseModel):
    name_ja: Optional[str] = None
    name_en: Optional[str] = None
    description: Optional[str] = None
    manufacturer_msrp_usd: Optional[float] = None
    manufacturer_dealer_price_usd: Optional[float] = None
    sales_price: Optional[float] = None
    notes: Optional[str] = None
    category: Optional[str] = None


class ManufacturerValues(BaseModel):
    sku: Optional[str] = None
    description: Optional[str] = None
    msrp_usd: Optional[float] = None
    dealer_price_usd: Optional[float] = None
    dealer_rate: Optional[float] = None
    notes: list[str] = Field(default_factory=list)
    source_status: Optional[SkuSourceStatus] = None
    source_price_book: Optional[str] = None
    source_sheets: list[str] = Field(default_factory=list)


class RecommendedChange(BaseModel):
    field: str
    current_value: Optional[float] = None
    manufacturer_value: Optional[float] = None


class SpaceOneMasterItem(BaseModel):
    spaceone_item_id: str
    source_sheet: Optional[str] = None
    source_row: Optional[int] = None
    spaceone_sku: Optional[str] = None
    normalized_sku: Optional[str] = None
    sku_cell_type: Optional[str] = None
    sku_raw: Optional[str] = None
    part_number_invalid: bool = False
    is_legacy_shipping: bool = False
    old_reference: Optional[CellReference] = None
    values: SpaceOneValues = Field(default_factory=SpaceOneValues)


class SpaceOneMasterImportResult(BaseModel):
    source_name: Optional[str] = None
    imported_at: Optional[datetime] = None
    items: list[SpaceOneMasterItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class MasterReconciliationIssue(BaseModel):
    code: str
    message: str
    details: Optional[str] = None


class MasterReconciliationResult(BaseModel):
    spaceone_item_id: str
    source_sheet: Optional[str] = None
    source_row: Optional[int] = None
    spaceone_sku: Optional[str] = None
    normalized_sku: Optional[str] = None
    manufacturer_price_book: Optional[str] = None
    manufacturer_candidate: Optional[SKUMasterCandidate] = None
    primary_status: MatchStatus
    issues: list[MasterReconciliationIssue] = Field(default_factory=list)
    old_reference: Optional[CellReference] = None
    current_spaceone_values: SpaceOneValues = Field(default_factory=SpaceOneValues)
    manufacturer_values: Optional[ManufacturerValues] = None
    recommended_changes: list[RecommendedChange] = Field(default_factory=list)
    old_msrp: Optional[float] = None
    new_msrp: Optional[float] = None
    old_dealer_price: Optional[float] = None
    new_dealer_price: Optional[float] = None


class MasterReconciliationSummary(BaseModel):
    total_rows: int = 0
    compared_rows: int = 0
    exact_match: int = 0
    price_mismatch: int = 0
    price_missing: int = 0
    sku_not_found: int = 0
    part_number_invalid: int = 0
    obsolete_only: int = 0
    needs_review: int = 0
    multiple_spaceone_rows: int = 0
    source_price_conflict: int = 0
    legacy_shipping: int = 0


class MasterReconciliationReport(BaseModel):
    summary: MasterReconciliationSummary = Field(default_factory=MasterReconciliationSummary)
    results: list[MasterReconciliationResult] = Field(default_factory=list)


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
