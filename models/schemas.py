from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from models.enums import (
    DestinationRegion,
    FactConfidence,
    FactScope,
    LinkMethod,
    LinkStatus,
    MatchConfidence,
    MatchStatus,
    CostBasis,
    CustomerPresentationMode,
    DomesticShippingMode,
    ExchangeRateReason,
    ExchangeRateSource,
    FinalPriceStatus,
    PriceMasterImportStatus,
    PriceMasterSourceType,
    PriceMasterType,
    PriceMasterValidationStatus,
    PriceSourceType,
    HistoricalComparisonStatus,
    InsuranceMode,
    PriceAdjustmentReason,
    QuoteAdjustmentType,
    QuoteDraftStatus,
    QuoteWarningSeverity,
    RemarkSource,
    ExportBundleStatus,
    ExportFileType,
    ExportPurpose,
    RequirementType,
    ScenarioCompleteness,
    PriceBasis,
    PriceBookDiffType,
    PricingFormulaType,
    PricingPolicyType,
    PricingPolicyStatus,
    PricingScopeType,
    QuestionStatus,
    RoundingMethod,
    QuestionTarget,
    RecommendationOrigin,
    RecordStatus,
    RelationType,
    ShippingScopeType,
    ShippingType,
    SkuDuplicateClass,
    SkuMappingSource,
    SkuSourceStatus,
    SupplierQuoteLineKind,
    SupplierQuoteOverallStatus,
    SupplierQuoteValidationStatus,
    SuggestedQuestionStatus,
    TechnicalCaseStatus,
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


class QuestionHumanReview(BaseModel):
    question_id: str
    review_status: str = "PENDING"
    ai_original: Optional[str] = None
    human_edited: Optional[str] = None


class ManufacturerResponseRevision(BaseModel):
    revision: int
    analyzed_at: str
    provider: Optional[str] = None
    model: Optional[str] = None
    original_response: Optional[str] = None
    analysis: Optional[dict] = None
    validated_matches: list[dict] = Field(default_factory=list)
    evidence_validation_result: list[dict] = Field(default_factory=list)


class TechnicalCaseRecord(BaseModel):
    case_id: str
    customer_name: Optional[str] = None
    case_title: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    status: str = TechnicalCaseStatus.DRAFT.value
    original_inquiry: Optional[str] = None
    requested_products: list[str] = Field(default_factory=list)
    requirements: list[dict] = Field(default_factory=list)
    customer_goal: list[dict] = Field(default_factory=list)
    existing_equipment: list[dict] = Field(default_factory=list)
    provider: Optional[str] = None
    model: Optional[str] = None
    knowledge_snapshot: Optional[dict] = None
    manufacturer_questions: list[dict] = Field(default_factory=list)
    question_human_reviews: list[QuestionHumanReview] = Field(default_factory=list)
    manufacturer_response_input: Optional[str] = None
    manufacturer_response_analysis: Optional[dict] = None
    validated_matches: list[dict] = Field(default_factory=list)
    evidence_validation_result: list[dict] = Field(default_factory=list)
    last_error: Optional[str] = None
    schema_version: int = 1
    end_user_name: Optional[str] = None
    case_summary: Optional[str] = None
    customer_questions: list[dict] = Field(default_factory=list)
    technical_questions: list[dict] = Field(default_factory=list)
    unresolved_items: list[dict] = Field(default_factory=list)
    analysis_json: Optional[dict] = None
    inquiry_success: bool = False
    response_revisions: list[ManufacturerResponseRevision] = Field(default_factory=list)
    approval_board: Optional[dict] = None
    archived_at: Optional[str] = None
    deleted_at: Optional[str] = None
    parent_case_id: Optional[str] = None
    relation_type: Optional[str] = None


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
    original_text: Optional[str] = None
    normalized_meaning: Optional[str] = None


class TechnicalQuestion(BaseModel):
    question_id: str
    case_id: str
    target: Optional[QuestionTarget] = None
    question: Optional[str] = None
    status: Optional[QuestionStatus] = None
    follow_up_required: bool = False
    created_at: Optional[datetime] = None
    classification: Optional[str] = None
    source: Optional[str] = None
    original_text: Optional[str] = None
    normalized_meaning: Optional[str] = None
    grounding: Optional[str] = None
    related_products: list[str] = Field(default_factory=list)
    review_status: Optional[str] = None
    ai_original_question: Optional[str] = None
    human_edited_question: Optional[str] = None


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
    line_id: Optional[str] = None
    sku: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[int] = None
    unit_price_usd: Optional[float] = None
    line_total_usd: Optional[float] = None
    discount: Optional[float] = None
    notes: Optional[str] = None
    extraction_confidence: Optional[str] = None
    expected_validation_status: Optional[SupplierQuoteValidationStatus] = None


class SupplierQuoteShippingLine(BaseModel):
    shipping_type: Optional[ShippingType] = None
    description: Optional[str] = None
    quantity: Optional[int] = None
    unit_price_usd: Optional[float] = None
    line_total_usd: Optional[float] = None
    destination: Optional[str] = None


class SupplierQuoteInsurance(BaseModel):
    description: Optional[str] = None
    quantity: Optional[int] = None
    amount_usd: Optional[float] = None
    is_separate_line: bool = True


class QuoteKnownIssue(BaseModel):
    code: str
    message: str
    details: Optional[str] = None


class SupplierQuote(BaseModel):
    supplier_quote_id: str
    case_id: str
    quote_number: Optional[str] = None
    quote_reference: Optional[str] = None
    version: Optional[str] = None
    quote_date: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    supplier: Optional[str] = None
    supplier_contact: Optional[str] = None
    currency: Optional[str] = None
    lines: list[SupplierQuoteLine] = Field(default_factory=list)
    shipping_lines: list[SupplierQuoteShippingLine] = Field(default_factory=list)
    shipping_usd: Optional[float] = None
    insurance: Optional[SupplierQuoteInsurance] = None
    insurance_usd: Optional[float] = None
    total_usd: Optional[float] = None
    lead_time: Optional[str] = None
    known_issues: list[QuoteKnownIssue] = Field(default_factory=list)
    source_metadata: dict = Field(default_factory=dict)
    is_manufacturer_source_of_truth: bool = False
    source_file: Optional[str] = None


class LeadTimeSnapshot(BaseModel):
    text: Optional[str] = None
    as_of: Optional[str] = None
    kind: str = "QUOTE_SNAPSHOT"
    is_technical_fact: bool = False
    is_lead_time_master: bool = False


class CustomerQuoteLine(BaseModel):
    line_id: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[int] = None
    unit_price_jpy: Optional[float] = None
    line_total_jpy: Optional[float] = None
    manufacturer_sku: Optional[str] = None
    sku_source: Optional[SkuMappingSource] = SkuMappingSource.UNMAPPED
    notes: Optional[str] = None


class CustomerQuoteShippingBox(BaseModel):
    shipping_type: Optional[ShippingType] = None
    quantity: Optional[int] = None


class CustomerQuoteShipping(BaseModel):
    description: Optional[str] = None
    boxes: list[CustomerQuoteShippingBox] = Field(default_factory=list)
    price_jpy: Optional[float] = None


class CustomerQuoteInsurance(BaseModel):
    included_in_sales_price: bool = True
    separate_line: bool = False
    note: Optional[str] = None


class RequiredConfigurationItem(BaseModel):
    configuration_id: str
    product: Optional[str] = None
    required_sku: Optional[str] = None
    required_description: Optional[str] = None
    requirement_source: Optional[str] = None
    requirement_reference: Optional[str] = None
    human_verified: bool = False
    depends_on_sku: Optional[str] = None
    dependency_source: Optional[str] = None
    match_markers: list[str] = Field(default_factory=list)
    exclude_skus: list[str] = Field(default_factory=list)
    exclude_markers: list[str] = Field(default_factory=list)
    notes: Optional[str] = None


class SupplierQuoteLineValidation(BaseModel):
    line_id: Optional[str] = None
    sku: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[int] = None
    line_kind: SupplierQuoteLineKind = SupplierQuoteLineKind.PRODUCT
    supplier_unit_price_usd: Optional[float] = None
    manufacturer_msrp_usd: Optional[float] = None
    manufacturer_dealer_price_usd: Optional[float] = None
    dealer_rate: Optional[float] = None
    manufacturer_notes: list[str] = Field(default_factory=list)
    manufacturer_status: Optional[SkuSourceStatus] = None
    validation_status: SupplierQuoteValidationStatus
    price_difference_vs_dealer: Optional[float] = None
    price_difference_vs_msrp: Optional[float] = None
    warnings: list[str] = Field(default_factory=list)
    source_reference: Optional[str] = None


class SupplierQuoteValidationSummary(BaseModel):
    product_lines: int = 0
    dealer_match_count: int = 0
    msrp_match_count: int = 0
    no_dealer_discount_count: int = 0
    price_mismatch_count: int = 0
    sku_not_found_count: int = 0
    requires_review_count: int = 0
    missing_component_count: int = 0
    special_price_count: int = 0
    shipping_line_count: int = 0
    insurance_line_count: int = 0


class SupplierQuoteValidationResult(BaseModel):
    supplier_quote_validation_id: str
    quote_reference: Optional[str] = None
    validated_at: Optional[datetime] = None
    price_book_versions: dict = Field(default_factory=dict)
    lines: list[SupplierQuoteLineValidation] = Field(default_factory=list)
    summary: SupplierQuoteValidationSummary = Field(default_factory=SupplierQuoteValidationSummary)
    known_configuration_issues: list[QuoteKnownIssue] = Field(default_factory=list)
    status: SupplierQuoteOverallStatus = SupplierQuoteOverallStatus.REVIEW_REQUIRED
    supplier_quote_total_usd: Optional[float] = None
    uses_supplier_quote_as_product_cost: bool = False
    manufacturer_cost_basis: str = "DT40_PT30_CURRENT_DEALER"


class CustomerQuote(BaseModel):
    quote_number: str
    case_id: str
    configuration_name: Optional[str] = None
    quote_date: Optional[datetime] = None
    customer: Optional[str] = None
    title: Optional[str] = None
    currency: Optional[str] = "JPY"
    lines: list[CustomerQuoteLine] = Field(default_factory=list)
    shipping: Optional[CustomerQuoteShipping] = None
    insurance: Optional[CustomerQuoteInsurance] = None
    lead_time: Optional[LeadTimeSnapshot] = None
    subtotal_ex_tax_jpy: Optional[float] = None
    tax_jpy: Optional[float] = None
    total_jpy: Optional[float] = None
    lead_time_note: Optional[str] = None
    insurance_note: Optional[str] = None
    source_metadata: dict = Field(default_factory=dict)


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
    dealer_price_label: Optional[str] = None


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


class SpaceOnePricingPolicyCandidate(BaseModel):
    pricing_policy_candidate_id: str
    spaceone_item_id: Optional[str] = None
    scope_type: PricingScopeType = PricingScopeType.SKU_SPECIFIC
    product_family: Optional[str] = None
    model: Optional[str] = None
    sku: Optional[str] = None
    price_basis: PriceBasis = PriceBasis.MANUAL
    formula_type: PricingFormulaType = PricingFormulaType.MANUAL
    multiplier: Optional[float] = None
    fixed_price_jpy: Optional[float] = None
    exchange_rate_reference: Optional[str] = None
    detected_exchange_rate: Optional[float] = None
    rounding_method: RoundingMethod = RoundingMethod.ROUNDING_UNKNOWN
    rounding_unit: Optional[float] = None
    source_formula: Optional[str] = None
    jpy_msrp_formula: Optional[str] = None
    source_sheet: Optional[str] = None
    source_row: Optional[int] = None
    effective_from: Optional[datetime] = None
    effective_until: Optional[datetime] = None
    status: PricingPolicyStatus = PricingPolicyStatus.CANDIDATE
    confidence: Optional[str] = None
    notes: Optional[str] = None
    policy_type: PricingPolicyType = PricingPolicyType.MANUAL_REVIEW
    review_reason: Optional[str] = None


class ExchangeRateScenario(BaseModel):
    exchange_rate_scenario_id: str
    name: Optional[str] = None
    currency_from: str = "USD"
    currency_to: str = "JPY"
    rate: Optional[float] = None
    source_type: Optional[str] = None
    effective_from: Optional[datetime] = None
    effective_until: Optional[datetime] = None
    status: PricingPolicyStatus = PricingPolicyStatus.CANDIDATE
    notes: Optional[str] = None


class PricingPatternSummary(BaseModel):
    pattern_id: str
    formula: Optional[str] = None
    price_basis: Optional[PriceBasis] = None
    formula_type: Optional[PricingFormulaType] = None
    multiplier: Optional[float] = None
    rounding_method: Optional[RoundingMethod] = None
    item_count: int = 0
    review_count: int = 0
    representative_skus: list[str] = Field(default_factory=list)
    source_sheets: list[str] = Field(default_factory=list)


class SalesPriceCandidate(BaseModel):
    sales_price_candidate_id: str
    spaceone_item_id: str
    manufacturer_sku: Optional[str] = None
    name_ja: Optional[str] = None
    manufacturer_msrp_usd: Optional[float] = None
    manufacturer_dealer_price_usd: Optional[float] = None
    exchange_rate: Optional[float] = None
    price_basis: Optional[PriceBasis] = None
    pricing_policy_candidate_id: Optional[str] = None
    source_formula: Optional[str] = None
    raw_sales_price_jpy: Optional[float] = None
    rounded_sales_price_jpy: Optional[float] = None
    current_spaceone_sales_price_jpy: Optional[float] = None
    difference_jpy: Optional[float] = None
    difference_rate: Optional[float] = None
    reference_gross_margin_rate: Optional[float] = None
    status: PricingPolicyStatus = PricingPolicyStatus.CANDIDATE
    warnings: list[str] = Field(default_factory=list)
    source_reference: Optional[str] = None
    skipped_reason: Optional[str] = None
    # Pricing Policy v1 provenance. source_reference holds the SpaceOne master sheet.
    pricing_policy_type: Optional[PricingPolicyType] = None
    multiplier: Optional[float] = None
    fixed_price_jpy: Optional[float] = None
    source_row: Optional[int] = None


class HistoricalPriceComparison(BaseModel):
    sku: Optional[str] = None
    item_name: Optional[str] = None
    quote_number: Optional[str] = None
    configuration_name: Optional[str] = None
    pricing_policy_candidate_id: Optional[str] = None
    policy_sales_price_jpy: Optional[float] = None
    historical_quote_price_jpy: Optional[float] = None
    difference_jpy: Optional[float] = None
    comparison_status: HistoricalComparisonStatus = HistoricalComparisonStatus.NOT_COMPARABLE
    notes: Optional[str] = None


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
    sales_price_formula: Optional[str] = None
    sales_price_formula_row: Optional[int] = None
    jpy_msrp_formula: Optional[str] = None
    detected_exchange_rate: Optional[float] = None
    exchange_rate_source_cell: Optional[str] = None
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


class ManufacturerSkuLink(BaseModel):
    manufacturer_sku_link_id: str
    spaceone_item_id: str
    spaceone_sku: Optional[str] = None
    manufacturer_sku: Optional[str] = None
    manufacturer_price_book: Optional[str] = None
    link_status: LinkStatus = LinkStatus.UNLINKED
    link_method: Optional[LinkMethod] = None
    linked_at: Optional[datetime] = None
    linked_by: Optional[str] = None
    notes: Optional[str] = None


class CurrentManufacturerValues(BaseModel):
    sku: str
    description: Optional[str] = None
    msrp_usd: Optional[float] = None
    dealer_price_usd: Optional[float] = None
    dealer_rate: Optional[float] = None
    notes: list[str] = Field(default_factory=list)
    source_status: Optional[SkuSourceStatus] = None
    price_book: Optional[str] = None
    source_sheets: list[str] = Field(default_factory=list)
    price_book_version: Optional[str] = None


class LegacyManufacturerValues(BaseModel):
    legacy_manufacturer_msrp: Optional[float] = None
    legacy_manufacturer_dealer_price: Optional[float] = None
    legacy_reference: Optional[CellReference] = None


class PriceDifference(BaseModel):
    legacy_msrp: Optional[float] = None
    current_msrp: Optional[float] = None
    msrp_delta: Optional[float] = None
    legacy_dealer_price: Optional[float] = None
    current_dealer_price: Optional[float] = None
    dealer_price_delta: Optional[float] = None


class QuotePriceSnapshot(BaseModel):
    snapshot_id: str
    sku: str
    price_book: Optional[str] = None
    price_book_version: Optional[str] = None
    manufacturer_msrp_usd: Optional[float] = None
    manufacturer_dealer_price_usd: Optional[float] = None
    exchange_rate: Optional[float] = None
    captured_at: Optional[datetime] = None
    source_reference: Optional[str] = None
    price_source_type: Optional[PriceSourceType] = None
    price_master_import_id: Optional[str] = None
    price_master_sha256: Optional[str] = None
    price_master_filename: Optional[str] = None


class PriceMasterImport(BaseModel):
    import_id: str
    master_type: PriceMasterType
    source_type: PriceMasterSourceType = PriceMasterSourceType.FILE_UPLOAD
    original_filename: Optional[str] = None
    stored_path: str
    sha256: str
    size_bytes: Optional[int] = None
    imported_at: str
    active: bool = False
    validation_status: PriceMasterValidationStatus = PriceMasterValidationStatus.VALID
    validation_summary: dict = Field(default_factory=dict)
    activated_at: Optional[str] = None
    deactivated_at: Optional[str] = None


class PriceMasterImportOutcome(BaseModel):
    status: PriceMasterImportStatus
    master_type: PriceMasterType
    record: Optional[PriceMasterImport] = None
    reason_code: Optional[str] = None


class ManufacturerPriceSource(BaseModel):
    source_key: str
    display_name: str
    source_url: str = ""
    enabled: bool = False
    parser_profile: str
    lifecycle_status: str
    last_checked_at: Optional[str] = None
    last_check_status: Optional[str] = None
    last_error: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
    row_version: int = 0


class SkuLinkPreviewItem(BaseModel):
    spaceone_item_id: str
    spaceone_sku: Optional[str] = None
    name_ja: Optional[str] = None
    spaceone_sales_price: Optional[float] = None
    match_status: Optional[MatchStatus] = None
    link: ManufacturerSkuLink
    current_values: Optional[CurrentManufacturerValues] = None
    legacy: LegacyManufacturerValues = Field(default_factory=LegacyManufacturerValues)
    price_difference: Optional[PriceDifference] = None
    review_reason: Optional[str] = None


class SkuLinkPreview(BaseModel):
    total_items: int = 0
    auto_linked: int = 0
    review_required: int = 0
    manually_linked: int = 0
    no_link_required: int = 0
    unlinked: int = 0
    items: list[SkuLinkPreviewItem] = Field(default_factory=list)
    current_candidates: list[SKUMasterCandidate] = Field(default_factory=list)


class ManualLinkResult(BaseModel):
    accepted: bool
    message: str
    preview: SkuLinkPreview


class LandedCostPolicyCandidate(BaseModel):
    landed_cost_policy_candidate_id: str
    policy_name: Optional[str] = None
    import_tax_rate: Optional[float] = None
    import_tax_basis: CostBasis = CostBasis.REVIEW_REQUIRED
    insurance_mode: InsuranceMode = InsuranceMode.NONE
    insurance_rate: Optional[float] = None
    insurance_basis: CostBasis = CostBasis.REVIEW_REQUIRED
    domestic_shipping_mode: DomesticShippingMode = DomesticShippingMode.REVIEW_REQUIRED
    domestic_shipping_jpy: Optional[float] = None
    shipping_markup_multiplier: Optional[float] = None
    rounding_method: RoundingMethod = RoundingMethod.ROUNDING_UNKNOWN
    rounding_unit: Optional[float] = None
    source_formula_refs: list[str] = Field(default_factory=list)
    status: PricingPolicyStatus = PricingPolicyStatus.CANDIDATE
    confidence: Optional[str] = None
    notes: Optional[str] = None


class LandedCostShippingLine(BaseModel):
    shipping_type: Optional[ShippingType] = None
    quantity: Optional[int] = None
    rate_usd: Optional[float] = None
    exchange_rate: Optional[float] = None
    cost_jpy: Optional[float] = None
    sales_markup_multiplier: Optional[float] = None
    sales_price_candidate_jpy: Optional[float] = None
    source_type: Optional[str] = None
    source_reference: Optional[str] = None
    rule_status: Optional[str] = None
    notes: Optional[str] = None


class ProductCostLine(BaseModel):
    sku: Optional[str] = None
    description: Optional[str] = None
    quantity: int = 1
    dealer_price_usd: Optional[float] = None
    msrp_usd: Optional[float] = None
    exchange_rate: Optional[float] = None
    dealer_cost_jpy: Optional[float] = None
    import_tax_jpy: Optional[float] = None
    insurance_jpy: Optional[float] = None
    domestic_shipping_jpy: Optional[float] = None
    landed_cost_jpy: Optional[float] = None
    standard_sales_price_jpy: Optional[float] = None
    manufacturer_price_snapshot: Optional[QuotePriceSnapshot] = None
    warnings: list[str] = Field(default_factory=list)


class QuoteAdjustment(BaseModel):
    adjustment_id: str
    line_id: Optional[str] = None
    adjustment_type: QuoteAdjustmentType = QuoteAdjustmentType.MANUAL
    original_price_jpy: Optional[float] = None
    final_price_jpy: Optional[float] = None
    amount_jpy: Optional[float] = None
    # Signed decimal against the standard sales price candidate. None when no standard price exists.
    adjustment_rate: Optional[float] = None
    # Legacy free-text reason. Kept so existing drafts and snapshots still read.
    reason: Optional[str] = None
    reason_code: Optional[PriceAdjustmentReason] = None
    reason_note: Optional[str] = None
    entered_by: Optional[str] = None
    entered_at: Optional[datetime] = None
    source_reference: Optional[str] = None


class LandedCostScenario(BaseModel):
    scenario_id: str
    case_id: Optional[str] = None
    name: Optional[str] = None
    exchange_rate: Optional[float] = None
    product_lines: list[ProductCostLine] = Field(default_factory=list)
    shipping_lines: list[LandedCostShippingLine] = Field(default_factory=list)
    insurance_input: Optional[InsuranceMode] = None
    import_tax_policy: Optional[LandedCostPolicyCandidate] = None
    domestic_shipping_policy: Optional[LandedCostPolicyCandidate] = None
    calculation_policy: Optional[LandedCostPolicyCandidate] = None
    captured_at: Optional[datetime] = None
    source_references: list[str] = Field(default_factory=list)
    unresolved_components: list[str] = Field(default_factory=list)
    adjustments: list[QuoteAdjustment] = Field(default_factory=list)
    status: ScenarioCompleteness = ScenarioCompleteness.INCOMPLETE
    warnings: list[str] = Field(default_factory=list)


class QuoteEconomicsComparison(BaseModel):
    configuration_name: Optional[str] = None
    quote_number: Optional[str] = None
    product_sales_calculated_jpy: Optional[float] = None
    product_sales_historical_jpy: Optional[float] = None
    product_sales_difference_jpy: Optional[float] = None
    shipping_sales_calculated_jpy: Optional[float] = None
    shipping_sales_historical_jpy: Optional[float] = None
    shipping_sales_difference_jpy: Optional[float] = None
    total_sales_calculated_jpy: Optional[float] = None
    total_sales_historical_jpy: Optional[float] = None
    total_sales_difference_jpy: Optional[float] = None
    landed_cost_jpy: Optional[float] = None
    gross_profit_jpy: Optional[float] = None
    gross_margin_rate: Optional[float] = None
    status: ScenarioCompleteness = ScenarioCompleteness.INCOMPLETE
    notes: Optional[str] = None


class QuoteCalcCellAudit(BaseModel):
    sheet: str
    cell: str
    formula: Optional[str] = None
    displayed_value: Optional[float] = None
    notes: Optional[str] = None


class QuoteCalcAudit(BaseModel):
    source_path: Optional[str] = None
    cells: list[QuoteCalcCellAudit] = Field(default_factory=list)
    observed_import_tax_rate: Optional[float] = None
    observed_import_tax_basis: CostBasis = CostBasis.REVIEW_REQUIRED
    observed_insurance_rate: Optional[float] = None
    observed_insurance_mode: InsuranceMode = InsuranceMode.NONE
    observed_insurance_basis: CostBasis = CostBasis.REVIEW_REQUIRED
    observed_shipping_markup: Optional[float] = None
    domestic_observations: list[str] = Field(default_factory=list)
    sheet_differences: list[str] = Field(default_factory=list)
    known_rule_checks: list[str] = Field(default_factory=list)
    policy_candidate: Optional[LandedCostPolicyCandidate] = None


class QuoteEconomicsResult(BaseModel):
    scenario_id: str
    product_sales_total_jpy: Optional[float] = None
    shipping_sales_total_jpy: Optional[float] = None
    total_sales_ex_tax_jpy: Optional[float] = None
    product_landed_cost_total_jpy: Optional[float] = None
    shipping_cost_total_jpy: Optional[float] = None
    other_cost_total_jpy: Optional[float] = None
    total_landed_cost_jpy: Optional[float] = None
    gross_profit_jpy: Optional[float] = None
    gross_margin_rate: Optional[float] = None
    status: ScenarioCompleteness = ScenarioCompleteness.INCOMPLETE
    warnings: list[str] = Field(default_factory=list)
    comparisons: list[HistoricalPriceComparison] = Field(default_factory=list)
    economics_comparison: Optional[QuoteEconomicsComparison] = None


class QuoteConfigurationLine(BaseModel):
    line_id: str
    manufacturer_sku: Optional[str] = None
    manufacturer_description: Optional[str] = None
    customer_display_name: Optional[str] = None
    customer_description: Optional[str] = None
    quantity: int = 1
    requirement_type: RequirementType = RequirementType.MANUAL_COMPONENT
    required_by_sku: Optional[str] = None
    dependency_source: Optional[str] = None
    manufacturer_price_snapshot: Optional[QuotePriceSnapshot] = None
    landed_cost_jpy: Optional[float] = None
    dealer_price_usd: Optional[float] = None
    dealer_cost_jpy: Optional[float] = None
    import_tax_jpy: Optional[float] = None
    insurance_jpy: Optional[float] = None
    domestic_shipping_jpy: Optional[float] = None
    standard_sales_price_candidate_jpy: Optional[float] = None
    standard_sales_price_candidate_id: Optional[str] = None
    # Pricing Policy v1 provenance of the standard candidate. SpaceOne master import / SHA is recorded in
    # the draft source_references. All optional so drafts saved before Step B still load.
    pricing_policy_type: Optional[PricingPolicyType] = None
    pricing_policy_candidate_id: Optional[str] = None
    pricing_multiplier: Optional[float] = None
    pricing_fixed_price_jpy: Optional[float] = None
    pricing_source_formula: Optional[str] = None
    pricing_source_sheet: Optional[str] = None
    pricing_source_row: Optional[int] = None
    final_sales_price_jpy: Optional[float] = None
    final_price_status: FinalPriceStatus = FinalPriceStatus.NOT_SET
    customer_presentation_status: CustomerPresentationMode = CustomerPresentationMode.UNDECIDED
    bundled_into_line_id: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)


class CustomerQuoteLineDraft(BaseModel):
    customer_quote_line_id: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    quantity: int = 1
    unit_price_jpy: Optional[float] = None
    amount_jpy: Optional[float] = None
    source_configuration_line_ids: list[str] = Field(default_factory=list)
    presentation_mode: CustomerPresentationMode = CustomerPresentationMode.SEPARATE_LINE
    display_order: int = 0
    notes: Optional[str] = None
    pricing_source: Optional[str] = None
    human_adjusted: bool = False
    adjustment_reference: Optional[str] = None
    historical_preview_unit_price_jpy: Optional[float] = None
    line_kind: str = "PRODUCT"


class QuoteDraftPricingContext(BaseModel):
    exchange_rate: Optional[float] = None
    exchange_rate_source: Optional[ExchangeRateSource] = None
    # Market reference is information only. Costs always use QuoteDraft.exchange_rate.
    market_reference_rate: Optional[float] = None
    market_reference_date: Optional[str] = None
    market_reference_source: Optional[str] = None
    exchange_rate_buffer: Optional[float] = None
    exchange_rate_reason_code: Optional[ExchangeRateReason] = None
    exchange_rate_reason_note: Optional[str] = None
    exchange_rate_set_by: Optional[str] = None
    exchange_rate_set_at: Optional[datetime] = None
    tax_rate: Optional[float] = None
    minimum_margin_reference: Optional[float] = None
    landed_cost_policy_candidate_id: Optional[str] = None
    shipping_snapshot_id: Optional[str] = None
    pricing_policy_candidate_ids: list[str] = Field(default_factory=list)
    manufacturer_price_snapshots: list[QuotePriceSnapshot] = Field(default_factory=list)
    landed_cost_policy_snapshot: Optional[LandedCostPolicyCandidate] = None
    source_references: list[str] = Field(default_factory=list)


class QuoteRemark(BaseModel):
    text: str
    source: RemarkSource = RemarkSource.HUMAN_ENTERED
    selected: bool = False


class IssuerSnapshot(BaseModel):
    company_name: Optional[str] = None
    address: Optional[str] = None
    office_address: Optional[str] = None
    telephone: Optional[str] = None
    source_reference: Optional[str] = None


class QuoteDraft(BaseModel):
    quote_draft_id: str
    quote_version: int = 1
    case_id: Optional[str] = None
    customer: Optional[str] = None
    title: Optional[str] = None
    configuration_name: Optional[str] = None
    configuration_lines: list[QuoteConfigurationLine] = Field(default_factory=list)
    customer_lines: list[CustomerQuoteLineDraft] = Field(default_factory=list)
    shipping_lines: list[LandedCostShippingLine] = Field(default_factory=list)
    exchange_rate: Optional[float] = None
    pricing_context: QuoteDraftPricingContext = Field(default_factory=QuoteDraftPricingContext)
    landed_cost_scenario_id: Optional[str] = None
    subtotal_ex_tax_jpy: Optional[float] = None
    tax_rate: Optional[float] = None
    tax_jpy: Optional[float] = None
    total_jpy: Optional[float] = None
    economics_result: Optional[QuoteEconomicsResult] = None
    completeness: ScenarioCompleteness = ScenarioCompleteness.INCOMPLETE
    status: QuoteDraftStatus = QuoteDraftStatus.DRAFT
    warnings: list[str] = Field(default_factory=list)
    remarks: list[str] = Field(default_factory=list)
    remark_candidates: list[QuoteRemark] = Field(default_factory=list)
    lead_time_text: Optional[str] = None
    issue_date: Optional[str] = None
    valid_until: Optional[str] = None
    auto_valid_until: bool = True
    issuer_snapshot: Optional[IssuerSnapshot] = None
    adjustments: list[QuoteAdjustment] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    source_references: list[str] = Field(default_factory=list)
    archived_at: Optional[str] = None
    deleted_at: Optional[str] = None
    parent_quote_id: Optional[str] = None
    source_quote_id: Optional[str] = None
    relation_type: Optional[str] = None


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


class QuoteWarningItem(BaseModel):
    message: str
    severity: QuoteWarningSeverity = QuoteWarningSeverity.WARNING


class QuoteApproval(BaseModel):
    quote_approval_id: str
    quote_draft_id: str
    quote_version: int
    status: QuoteDraftStatus
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    approval_comment: Optional[str] = None
    warnings_acknowledged: list[str] = Field(default_factory=list)
    confirmations: dict[str, bool] = Field(default_factory=dict)
    critical_warnings: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_references: list[str] = Field(default_factory=list)


class QuoteReviewSummary(BaseModel):
    quote_draft_id: str
    quote_version: int
    status: QuoteDraftStatus
    customer: Optional[str] = None
    title: Optional[str] = None
    configuration_name: Optional[str] = None
    configuration_rows: list[dict] = Field(default_factory=list)
    customer_lines: list[dict] = Field(default_factory=list)
    shipping_description: Optional[str] = None
    shipping_price_jpy: Optional[float] = None
    quantities: list[dict] = Field(default_factory=list)
    subtotal_ex_tax_jpy: Optional[float] = None
    tax_rate: Optional[float] = None
    tax_jpy: Optional[float] = None
    total_jpy: Optional[float] = None
    total_landed_cost_jpy: Optional[float] = None
    gross_profit_jpy: Optional[float] = None
    gross_margin_rate: Optional[float] = None
    remarks: list[QuoteRemark] = Field(default_factory=list)
    lead_time_text: Optional[str] = None
    valid_until: Optional[str] = None
    unresolved_warnings: list[QuoteWarningItem] = Field(default_factory=list)


class ApprovalValidationResult(BaseModel):
    ready_for_approval: bool
    current_status: QuoteDraftStatus
    can_approve: bool
    blocking_reason: Optional[str] = None
    critical_warnings: list[str] = Field(default_factory=list)
    regular_warnings: list[str] = Field(default_factory=list)
    review_summary: Optional[QuoteReviewSummary] = None


class ApprovedQuoteSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    approved_quote_snapshot_id: str
    quote_draft_id: str
    quote_version: int
    case_id: Optional[str] = None
    configuration_name: Optional[str] = None
    customer: Optional[str] = None
    title: Optional[str] = None
    approved_at: datetime
    approved_by: Optional[str] = None
    status: QuoteDraftStatus = QuoteDraftStatus.APPROVED
    configuration_snapshot: list[QuoteConfigurationLine] = Field(default_factory=list)
    customer_lines_snapshot: list[CustomerQuoteLineDraft] = Field(default_factory=list)
    shipping_snapshot: list[LandedCostShippingLine] = Field(default_factory=list)
    manufacturer_price_snapshots: list[QuotePriceSnapshot] = Field(default_factory=list)
    pricing_policy_references: list[str] = Field(default_factory=list)
    landed_cost_policy_snapshot: Optional[LandedCostPolicyCandidate] = None
    exchange_rate: Optional[float] = None
    exchange_rate_source: Optional[ExchangeRateSource] = None
    market_reference_rate: Optional[float] = None
    market_reference_date: Optional[str] = None
    market_reference_source: Optional[str] = None
    exchange_rate_buffer: Optional[float] = None
    exchange_rate_reason_code: Optional[ExchangeRateReason] = None
    exchange_rate_reason_note: Optional[str] = None
    exchange_rate_set_by: Optional[str] = None
    exchange_rate_set_at: Optional[datetime] = None
    adjustments_snapshot: list[QuoteAdjustment] = Field(default_factory=list)
    subtotal_ex_tax_jpy: Optional[float] = None
    tax_rate: Optional[float] = None
    tax_jpy: Optional[float] = None
    total_jpy: Optional[float] = None
    total_landed_cost_jpy: Optional[float] = None
    gross_profit_jpy: Optional[float] = None
    gross_margin_rate: Optional[float] = None
    remarks: list[QuoteRemark] = Field(default_factory=list)
    lead_time_text: Optional[str] = None
    issue_date: Optional[str] = None
    valid_until: Optional[str] = None
    issuer_snapshot: Optional[IssuerSnapshot] = None
    quote_number_candidate: Optional[str] = None
    official_quote_number: Optional[str] = None
    source_references: list[str] = Field(default_factory=list)


class InternalQuoteTransferRow(BaseModel):
    part_number: Optional[str] = None
    item_name: Optional[str] = None
    quantity: int = 1
    dealer_unit_price_usd: Optional[float] = None
    dealer_amount_usd: Optional[float] = None
    dealer_cost_jpy: Optional[float] = None
    import_tax_jpy: Optional[float] = None
    insurance_jpy: Optional[float] = None
    domestic_shipping_jpy: Optional[float] = None
    landed_subtotal_jpy: Optional[float] = None
    spaceone_standard_sales_jpy: Optional[float] = None
    adjusted_unit_price_jpy: Optional[float] = None
    sales_amount_jpy: Optional[float] = None
    gross_profit_jpy: Optional[float] = None
    gross_margin_rate: Optional[float] = None
    presentation_mode: Optional[CustomerPresentationMode] = None
    requirement_type: Optional[RequirementType] = None


class InternalShippingEconomicsRow(BaseModel):
    shipping_type: Optional[str] = None
    quantity: Optional[int] = None
    usd_rate: Optional[float] = None
    usd_amount: Optional[float] = None
    exchange_rate: Optional[float] = None
    cost_jpy: Optional[float] = None
    standard_sales_candidate_jpy: Optional[float] = None
    final_sales_price_jpy: Optional[float] = None
    gross_profit_jpy: Optional[float] = None
    gross_margin_rate: Optional[float] = None
    source_snapshot_id: Optional[str] = None
    line_role: str = "COMPONENT"


class InternalQuoteTransferPayload(BaseModel):
    source_approved_quote_snapshot_id: str
    rows: list[InternalQuoteTransferRow] = Field(default_factory=list)
    shipping_rows: list[InternalShippingEconomicsRow] = Field(default_factory=list)
    product_sales_ex_tax_jpy: Optional[float] = None
    shipping_sales_ex_tax_jpy: Optional[float] = None
    customer_subtotal_ex_tax_jpy: Optional[float] = None
    customer_tax_jpy: Optional[float] = None
    customer_total_jpy: Optional[float] = None
    product_landed_cost_jpy: Optional[float] = None
    shipping_cost_jpy: Optional[float] = None
    total_landed_cost_jpy: Optional[float] = None
    gross_profit_jpy: Optional[float] = None
    gross_margin_rate: Optional[float] = None


class SpaceOneQuoteLine(BaseModel):
    item_name: Optional[str] = None
    item_detail: Optional[str] = None
    unit_price_jpy: Optional[float] = None
    quantity: int = 1
    amount_jpy: Optional[float] = None


class SpaceOneQuotePayload(BaseModel):
    source_approved_quote_snapshot_id: str
    customer: Optional[str] = None
    title: Optional[str] = None
    quote_number_candidate: Optional[str] = None
    official_quote_number: Optional[str] = None
    issue_date: Optional[str] = None
    valid_until: Optional[str] = None
    lines: list[SpaceOneQuoteLine] = Field(default_factory=list)
    subtotal: Optional[float] = None
    tax_rate: Optional[float] = None
    tax: Optional[float] = None
    total: Optional[float] = None
    international_shipping_description: Optional[str] = None
    remarks: list[str] = Field(default_factory=list)


class FormalQuoteIssuer(BaseModel):
    company_name: Optional[str] = None
    address: Optional[str] = None
    office_address: Optional[str] = None
    telephone: Optional[str] = None


class FormalQuoteLine(BaseModel):
    item_name: Optional[str] = None
    customer_description: Optional[str] = None
    quantity: int = 1
    unit_price: Optional[float] = None
    amount: Optional[float] = None
    remarks: Optional[str] = None


class FormalQuoteDocument(BaseModel):
    snapshot_id: str
    snapshot_version: int
    quote_number: Optional[str] = None
    customer_name: Optional[str] = None
    subject: Optional[str] = None
    issue_date: Optional[str] = None
    valid_until: Optional[str] = None
    issuer: Optional[FormalQuoteIssuer] = None
    customer_lines: list[FormalQuoteLine] = Field(default_factory=list)
    subtotal: Optional[float] = None
    tax_rate: Optional[float] = None
    tax_amount: Optional[float] = None
    total: Optional[float] = None
    remarks: list[str] = Field(default_factory=list)
    source_approved_snapshot_id: str


class MoneyForwardQuoteRow(BaseModel):
    item_name: Optional[str] = None
    item_detail: Optional[str] = None
    unit_price_jpy: Optional[float] = None
    quantity: int = 1
    amount_jpy: Optional[float] = None
    notes: Optional[str] = None


class MoneyForwardQuotePayload(BaseModel):
    source_approved_quote_snapshot_id: str
    rows: list[MoneyForwardQuoteRow] = Field(default_factory=list)
    subtotal_ex_tax_jpy: Optional[float] = None
    tax_jpy: Optional[float] = None
    total_jpy: Optional[float] = None
    tsv_preview: str = ""


class QuoteOutputBundle(BaseModel):
    source_approved_quote_snapshot_id: str
    internal_transfer: InternalQuoteTransferPayload
    spaceone_quote: SpaceOneQuotePayload
    moneyforward: MoneyForwardQuotePayload


class ExportFileManifest(BaseModel):
    file_type: ExportFileType
    filename: str
    purpose: ExportPurpose = ExportPurpose.DEVELOPMENT
    approved_snapshot_id: str
    quote_version: int
    generated_at: datetime
    subtotal_ex_tax: Optional[float] = None
    tax: Optional[float] = None
    total: Optional[float] = None
    row_count: int = 0
    sha256: Optional[str] = None
    pdf_layout_prepared: bool = False


class ApprovedQuoteExportBundle(BaseModel):
    export_bundle_id: str
    approved_quote_snapshot_id: str
    case_id: Optional[str] = None
    quote_version: int
    official_quote_number: Optional[str] = None
    quote_number_candidate: Optional[str] = None
    generated_at: datetime
    generated_by: Optional[str] = None
    moneyforward_payload: MoneyForwardQuotePayload
    internal_transfer_payload: InternalQuoteTransferPayload
    spaceone_quote_payload: SpaceOneQuotePayload
    file_manifest: list[ExportFileManifest] = Field(default_factory=list)
    status: ExportBundleStatus = ExportBundleStatus.VALIDATED
    warnings: list[str] = Field(default_factory=list)


class ActivityEvent(BaseModel):
    event_id: str
    event_type: str
    occurred_at: str
    entity_kind: str
    entity_id: str
    entity_version: Optional[int] = None
    customer_name: Optional[str] = None
    title: Optional[str] = None
    payload: dict = Field(default_factory=dict)
    schema_version: int = 1


class CustomerRecord(BaseModel):
    customer_id: str
    customer_name: str
    department: Optional[str] = None
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    end_user: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
