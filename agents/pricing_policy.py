import math
import re
from collections import defaultdict
from typing import Optional, Sequence

from models import (
    ExchangeRateScenario,
    HistoricalComparisonStatus,
    HistoricalPriceComparison,
    LinkStatus,
    PriceBasis,
    PricingFormulaType,
    PricingPatternSummary,
    PricingPolicyStatus,
    PricingScopeType,
    RoundingMethod,
    SalesPriceCandidate,
    SkuLinkPreview,
    SkuLinkPreviewItem,
    SpaceOneMasterItem,
    SpaceOnePricingPolicyCandidate,
)

MULTIPLIER_RE = re.compile(
    r"^=(?P<col>[EF])(?P<row>\d+)\*(?P<mult>\d+(?:\.\d+)?)$",
    re.IGNORECASE,
)
PASSTHROUGH_RE = re.compile(r"^=(?P<col>[EF])(?P<row>\d+)$", re.IGNORECASE)
ROUND_RE = re.compile(
    r"^=(?P<fn>ROUND(?:UP|DOWN)?)\((?P<inner>.+),(?P<digits>-?\d+)\)$",
    re.IGNORECASE,
)
COMPARISON_TOLERANCE_JPY = 0.5


def extract_pricing_policies(
    items: Sequence[SpaceOneMasterItem],
) -> list[SpaceOnePricingPolicyCandidate]:
    policies = []
    for item in items:
        if item.is_legacy_shipping:
            continue
        policy = _policy_from_item(item)
        if policy is not None:
            policies.append(policy)
    return policies


def summarize_pricing_patterns(
    policies: Sequence[SpaceOnePricingPolicyCandidate],
) -> list[PricingPatternSummary]:
    groups = defaultdict(list)
    for policy in policies:
        groups[_pattern_key(policy)].append(policy)
    summaries = []
    for index, policies_in_group in enumerate(groups.values(), start=1):
        first = policies_in_group[0]
        skus = []
        sheets = []
        for policy in policies_in_group:
            if policy.sku and policy.sku not in skus:
                skus.append(policy.sku)
            if policy.source_sheet and policy.source_sheet not in sheets:
                sheets.append(policy.source_sheet)
        summaries.append(
            PricingPatternSummary(
                pattern_id=f"pattern-{index:03d}",
                formula=_pattern_formula(first),
                price_basis=first.price_basis,
                formula_type=first.formula_type,
                multiplier=first.multiplier,
                rounding_method=first.rounding_method,
                item_count=len(policies_in_group),
                review_count=sum(
                    1 for policy in policies_in_group if policy.status == PricingPolicyStatus.REVIEW_REQUIRED
                ),
                representative_skus=skus[:5],
                source_sheets=sheets,
            )
        )
    summaries.sort(key=lambda item: (-item.item_count, item.formula or ""))
    return summaries


def detected_exchange_rate_scenario(
    items: Sequence[SpaceOneMasterItem],
) -> Optional[ExchangeRateScenario]:
    for item in items:
        if item.detected_exchange_rate is None:
            continue
        return ExchangeRateScenario(
            exchange_rate_scenario_id="fx-detected-master",
            name="SpaceOne master detected rate",
            rate=item.detected_exchange_rate,
            source_type="SPACEONE_MASTER_DETECTED",
            status=PricingPolicyStatus.CANDIDATE,
            notes="Detected from the master sheet. Not a permanent 160/170 rule.",
        )
    return None


def build_exchange_rate_scenario(rate: float, *, name: Optional[str] = None) -> ExchangeRateScenario:
    return ExchangeRateScenario(
        exchange_rate_scenario_id=f"fx-user-{rate}",
        name=name or "User specified exchange rate",
        rate=rate,
        source_type="USER_SPECIFIED",
        status=PricingPolicyStatus.CANDIDATE,
        notes="Exchange Rate is supplied at simulation time. It is not embedded in the Pricing Policy.",
    )


def simulate_sales_price_candidates(
    preview: SkuLinkPreview,
    policies: Sequence[SpaceOnePricingPolicyCandidate],
    exchange: ExchangeRateScenario,
    items: Sequence[SpaceOneMasterItem],
) -> list[SalesPriceCandidate]:
    policy_by_item = {policy.spaceone_item_id: policy for policy in policies}
    item_by_id = {item.spaceone_item_id: item for item in items}
    candidates = []
    for preview_item in preview.items:
        candidates.append(
            _sales_candidate(
                preview_item,
                policy_by_item.get(preview_item.spaceone_item_id),
                item_by_id.get(preview_item.spaceone_item_id),
                exchange,
            )
        )
    return candidates


def ihi_historical_comparison_lines(case: dict) -> list[dict]:
    quotes = {
        "MAG": case["mag_customer_quote"],
        "PHOTON": case["photon_customer_quote"],
    }
    lines = []
    for mapping in case["expected_validation"].get("human_verified_sku_mappings") or []:
        quote = quotes.get(mapping.get("quote") or "")
        historical = None
        if quote:
            historical = _historical_price(quote, mapping.get("customer_line_description"))
        lines.append(
            {
                "quote": mapping.get("quote"),
                "quote_number": quote.get("quote_number") if quote else None,
                "customer_line_description": mapping.get("customer_line_description"),
                "expected_manufacturer_sku": mapping.get("expected_manufacturer_sku"),
                "historical_price_jpy": historical,
            }
        )
    return lines


def _historical_price(quote: dict, description: Optional[str]) -> Optional[float]:
    if not description:
        return None
    for line in quote.get("lines") or []:
        if line.get("description") == description:
            return line.get("unit_price_jpy")
    return None


def compare_ihi_historical_prices(
    sales_candidates: Sequence[SalesPriceCandidate],
    policies: Sequence[SpaceOnePricingPolicyCandidate],
    *,
    historical_lines: Sequence[dict],
) -> list[HistoricalPriceComparison]:
    policy_by_id = {policy.pricing_policy_candidate_id: policy for policy in policies}
    by_sheet_sku = {}
    for candidate in sales_candidates:
        policy = policy_by_id.get(candidate.pricing_policy_candidate_id or "")
        sheet = policy.source_sheet if policy else None
        if candidate.manufacturer_sku:
            by_sheet_sku[(sheet, candidate.manufacturer_sku)] = candidate
    results = []
    for line in historical_lines:
        sku = line.get("expected_manufacturer_sku")
        if not sku:
            results.append(
                HistoricalPriceComparison(
                    item_name=line.get("customer_line_description"),
                    quote_number=line.get("quote_number"),
                    configuration_name=line.get("quote"),
                    comparison_status=HistoricalComparisonStatus.NOT_COMPARABLE,
                    notes="No human-verified manufacturer SKU. Not compared.",
                )
            )
            continue
        sheet = _sheet_for_configuration(line.get("quote"))
        candidate = by_sheet_sku.get((sheet, sku))
        historical = line.get("historical_price_jpy")
        if historical is None:
            results.append(
                HistoricalPriceComparison(
                    sku=sku,
                    item_name=line.get("customer_line_description"),
                    quote_number=line.get("quote_number"),
                    configuration_name=line.get("quote"),
                    comparison_status=HistoricalComparisonStatus.MISSING_IN_HISTORICAL_QUOTE,
                    notes=(
                        "DT40 dependency is recorded. Historical Customer Quote has no independent sales line. "
                        "This is an audit, not a verdict that the past quote is wrong. "
                        "360,000 JPY is not treated as including this SKU."
                    ),
                )
            )
            continue
        if candidate is None or candidate.raw_sales_price_jpy is None:
            results.append(
                HistoricalPriceComparison(
                    sku=sku,
                    item_name=line.get("customer_line_description"),
                    quote_number=line.get("quote_number"),
                    configuration_name=line.get("quote"),
                    historical_quote_price_jpy=float(historical),
                    comparison_status=HistoricalComparisonStatus.NOT_COMPARABLE,
                    notes="Sales Price Candidate is not available for this historical line. Historical price is kept for mapping only.",
                )
            )
            continue
        difference = round(candidate.raw_sales_price_jpy - float(historical), 2)
        status = (
            HistoricalComparisonStatus.MATCH
            if abs(difference) <= COMPARISON_TOLERANCE_JPY
            else HistoricalComparisonStatus.DIFFERENCE
        )
        results.append(
            HistoricalPriceComparison(
                sku=sku,
                item_name=line.get("customer_line_description"),
                quote_number=line.get("quote_number"),
                configuration_name=line.get("quote"),
                pricing_policy_candidate_id=candidate.pricing_policy_candidate_id,
                policy_sales_price_jpy=candidate.raw_sales_price_jpy,
                historical_quote_price_jpy=float(historical),
                difference_jpy=difference,
                comparison_status=status,
                notes="IHI Customer Quote is historical output, not a Pricing Policy source.",
            )
        )
    return results


def apply_rounding(
    value: Optional[float],
    method: RoundingMethod,
    unit: Optional[float],
) -> Optional[float]:
    if value is None:
        return None
    if method in {RoundingMethod.NONE, RoundingMethod.ROUNDING_UNKNOWN} or not unit:
        return value
    step = float(unit)
    if method == RoundingMethod.ROUND:
        return round(value / step) * step
    if method == RoundingMethod.ROUND_UP:
        return math.ceil(value / step) * step
    if method == RoundingMethod.ROUND_DOWN:
        return math.floor(value / step) * step
    return value


def _policy_from_item(item: SpaceOneMasterItem) -> Optional[SpaceOnePricingPolicyCandidate]:
    raw = (item.sales_price_formula or "").strip()
    if not raw:
        return None
    rounding_method = RoundingMethod.NONE
    rounding_unit = None
    formula = raw
    inner = raw.replace(" ", "")
    round_match = ROUND_RE.fullmatch(inner)
    if round_match:
        rounding_method, rounding_unit = _rounding_from_excel(round_match)
        formula = "=" + round_match.group("inner")
        inner = formula
    policy = SpaceOnePricingPolicyCandidate(
        pricing_policy_candidate_id=f"ppc-{item.spaceone_item_id}",
        spaceone_item_id=item.spaceone_item_id,
        scope_type=PricingScopeType.SKU_SPECIFIC,
        product_family=item.source_sheet,
        sku=item.normalized_sku or item.spaceone_sku,
        exchange_rate_reference=item.exchange_rate_source_cell,
        detected_exchange_rate=item.detected_exchange_rate,
        rounding_method=rounding_method,
        rounding_unit=rounding_unit,
        source_formula=item.sales_price_formula,
        jpy_msrp_formula=item.jpy_msrp_formula,
        source_sheet=item.source_sheet,
        source_row=item.sales_price_formula_row or item.source_row,
        status=PricingPolicyStatus.CANDIDATE,
        confidence="HIGH",
    )
    if re.fullmatch(r"-?\d+(?:\.\d+)?", inner):
        policy.price_basis = PriceBasis.FIXED_PRICE
        policy.formula_type = PricingFormulaType.FIXED
        policy.fixed_price_jpy = float(inner)
        policy.notes = "Fixed SpaceOne sales price. Manufacturer price changes do not auto-update this."
        return policy
    match = MULTIPLIER_RE.fullmatch(inner)
    if match:
        _apply_multiplier(policy, match)
        return policy
    match = PASSTHROUGH_RE.fullmatch(inner)
    if match:
        _apply_multiplier(policy, match, multiplier=1.0)
        policy.notes = "Sales price copies JPY manufacturer price. Source formula was kept."
        return policy
    policy.price_basis = PriceBasis.SPECIAL_FORMULA
    policy.formula_type = PricingFormulaType.SPECIAL
    policy.status = PricingPolicyStatus.REVIEW_REQUIRED
    policy.confidence = "LOW"
    policy.notes = "Special formula was kept as-is. It was not converted to an approximate multiplier."
    return policy


def _apply_multiplier(policy: SpaceOnePricingPolicyCandidate, match, multiplier: Optional[float] = None) -> None:
    column = match.group("col").upper()
    policy.price_basis = PriceBasis.MANUFACTURER_MSRP if column == "E" else PriceBasis.MANUFACTURER_DEALER
    policy.formula_type = PricingFormulaType.MULTIPLIER
    policy.multiplier = float(match.group("mult")) if multiplier is None else multiplier


def _rounding_from_excel(match) -> tuple[RoundingMethod, Optional[float]]:
    fn = match.group("fn").upper()
    digits = int(match.group("digits"))
    unit = 10 ** (-digits) if digits <= 0 else None
    if fn == "ROUND":
        return RoundingMethod.ROUND, unit
    if fn == "ROUNDUP":
        return RoundingMethod.ROUND_UP, unit
    return RoundingMethod.ROUND_DOWN, unit


def _sales_candidate(
    preview_item: SkuLinkPreviewItem,
    policy: Optional[SpaceOnePricingPolicyCandidate],
    item: Optional[SpaceOneMasterItem],
    exchange: ExchangeRateScenario,
) -> SalesPriceCandidate:
    current_sales = preview_item.spaceone_sales_price
    candidate = SalesPriceCandidate(
        sales_price_candidate_id=f"spc-{preview_item.spaceone_item_id}",
        spaceone_item_id=preview_item.spaceone_item_id,
        name_ja=preview_item.name_ja,
        current_spaceone_sales_price_jpy=current_sales,
        exchange_rate=exchange.rate,
        pricing_policy_candidate_id=policy.pricing_policy_candidate_id if policy else None,
        source_formula=policy.source_formula if policy else None,
        price_basis=policy.price_basis if policy else None,
        source_reference=policy.source_sheet if policy else None,
    )
    if preview_item.link.link_status not in {LinkStatus.AUTO_LINKED, LinkStatus.MANUALLY_LINKED}:
        candidate.status = PricingPolicyStatus.REVIEW_REQUIRED
        candidate.skipped_reason = "Manufacturer SKU未確定"
        candidate.warnings.append("Manufacturer SKU未確定")
        return candidate
    current = preview_item.current_values
    if current is None:
        candidate.status = PricingPolicyStatus.REVIEW_REQUIRED
        candidate.skipped_reason = "Current Manufacturer Value is not available."
        candidate.warnings.append("Current Manufacturer Value is not available.")
        return candidate
    candidate.manufacturer_sku = preview_item.link.manufacturer_sku
    candidate.manufacturer_msrp_usd = current.msrp_usd
    candidate.manufacturer_dealer_price_usd = current.dealer_price_usd
    if policy is None:
        candidate.status = PricingPolicyStatus.REVIEW_REQUIRED
        candidate.warnings.append("No SpaceOne sales formula was found.")
        return candidate
    if policy.formula_type == PricingFormulaType.SPECIAL:
        candidate.status = PricingPolicyStatus.REVIEW_REQUIRED
        candidate.warnings.append("Special formula cannot be simulated as a simple multiplier.")
        return candidate
    if exchange.rate is None:
        candidate.status = PricingPolicyStatus.REVIEW_REQUIRED
        candidate.warnings.append("Exchange Rate is required for simulation and is not taken from Pricing Policy.")
        return candidate
    raw = _raw_sales_price(policy, current.msrp_usd, current.dealer_price_usd, exchange.rate)
    if raw is None:
        candidate.status = PricingPolicyStatus.REVIEW_REQUIRED
        candidate.warnings.append("Sales Price Candidate could not be calculated from Current Manufacturer Value.")
        return candidate
    rounded = apply_rounding(raw, policy.rounding_method, policy.rounding_unit)
    candidate.raw_sales_price_jpy = raw
    candidate.rounded_sales_price_jpy = rounded
    if current_sales is not None:
        candidate.difference_jpy = round(raw - current_sales, 2)
        if current_sales:
            candidate.difference_rate = round((raw - current_sales) / current_sales, 4)
    if current.dealer_price_usd is not None and raw:
        reference_cost = current.dealer_price_usd * exchange.rate
        candidate.reference_gross_margin_rate = round((raw - reference_cost) / raw, 4)
        candidate.warnings.append("参考粗利率（輸入諸経費除く）。Insurance / Tax / Shipping は含みません。")
    return candidate


def _raw_sales_price(policy, msrp_usd, dealer_usd, rate) -> Optional[float]:
    if policy.formula_type == PricingFormulaType.FIXED:
        return policy.fixed_price_jpy
    usd = None
    if policy.price_basis == PriceBasis.MANUFACTURER_MSRP:
        usd = msrp_usd
    elif policy.price_basis == PriceBasis.MANUFACTURER_DEALER:
        usd = dealer_usd
    if usd is None or policy.multiplier is None:
        return None
    return round(usd * rate * policy.multiplier, 4)


def _pattern_key(policy: SpaceOnePricingPolicyCandidate) -> tuple:
    if policy.formula_type == PricingFormulaType.SPECIAL:
        return ("SPECIAL", policy.source_formula)
    return (
        policy.price_basis,
        policy.formula_type,
        policy.multiplier,
        policy.rounding_method,
        policy.rounding_unit,
        policy.fixed_price_jpy,
    )


def _pattern_formula(policy: SpaceOnePricingPolicyCandidate) -> str:
    if policy.formula_type == PricingFormulaType.FIXED:
        return f"FIXED {policy.fixed_price_jpy}"
    if policy.formula_type == PricingFormulaType.SPECIAL:
        return policy.source_formula or "SPECIAL"
    basis = "MSRP JPY" if policy.price_basis == PriceBasis.MANUFACTURER_MSRP else "Dealer JPY"
    return f"{basis} × {policy.multiplier}"


def _sheet_for_configuration(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    key = name.upper()
    if key == "MAG":
        return "MAG"
    if key == "PHOTON":
        return "PHOTON"
    return name
