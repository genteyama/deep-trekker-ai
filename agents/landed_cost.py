from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence
import json

from agents.sku_link import create_quote_price_snapshot
from models import (
    CostBasis,
    DomesticShippingMode,
    HistoricalComparisonStatus,
    HistoricalPriceComparison,
    InsuranceMode,
    LandedCostPolicyCandidate,
    LandedCostScenario,
    LandedCostShippingLine,
    PricingPolicyStatus,
    ProductCostLine,
    QuoteAdjustment,
    QuoteEconomicsComparison,
    QuoteEconomicsResult,
    QuotePriceSnapshot,
    SalesPriceCandidate,
    ScenarioCompleteness,
    ShippingType,
    SKUMasterCandidate,
)

SHIPPING_SNAPSHOT_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "golden_cases" / "ihi_quote_001" / "shipping_snapshots.json"
)
IHI_KNOWN_PRODUCTS = {
    "MAG": ("9701-MAG-4K", "9735", "5608", "2604", "2601"),
    "PHOTON": ("9680-BASE", "8459", "5608", "7851-PHOTON"),
}
IHI_UNRESOLVED = {
    "MAG": (),
    "PHOTON": (),
}
IHI_SHIPPING = {
    "MAG": ((ShippingType.LARGE_BOX, 2),),
    "PHOTON": ((ShippingType.LARGE_BOX, 1), (ShippingType.SMALL_BOX, 1)),
}
IHI_SHEET_DOMESTIC_FIRST_LINE_JPY = 10000.0
IHI_DEVELOPMENT_DEALER_VALUES = {
    "9701-MAG-4K": {"dealer_price_usd": 21262.2, "msrp_usd": 35437, "description": "MAG CRAWLER PACKAGE 4K", "price_book": "DT40"},
    "9735": {"dealer_price_usd": 7245.0, "msrp_usd": 12075, "description": "ELEVATING PAN TILT CAMERA KIT", "price_book": "DT40"},
    "5608": {"dealer_price_usd": 10448.0, "msrp_usd": 10448, "description": "CYGNUS THICKNESS GAUGE", "price_book": "DT40"},
    "9680-BASE": {"dealer_price_usd": 10434.6, "msrp_usd": 17391, "description": "PHOTON BASE PACKAGE", "price_book": "DT40"},
    "8459": {"dealer_price_usd": 472.2, "msrp_usd": 787, "description": "SPARE BATTERY - PHOTON", "price_book": "DT40"},
    "7851-PHOTON": {"dealer_price_usd": 1047.6, "msrp_usd": 1746, "description": "CYGNUS INTEGRATION KIT - PHOTON", "price_book": "DT40"},
}


def load_shipping_snapshots(path: Optional[Path] = None) -> dict:
    snapshot_path = path or SHIPPING_SNAPSHOT_PATH
    with snapshot_path.open(encoding="utf-8") as file:
        return json.load(file)


def september_dealer_update_shipping_rate(shipping_type: ShippingType) -> Optional[float]:
    snapshot = load_shipping_snapshots()["dealer_update_september_2026"]
    for item in snapshot["rates"]:
        if item["shipping_type"] == shipping_type.value:
            return float(item["rate_usd"])
    return None


def supplier_quote_shipping_rate(shipping_type: ShippingType) -> Optional[float]:
    snapshot = load_shipping_snapshots()["supplier_quote_ihi"]
    for item in snapshot["rates"]:
        if item["shipping_type"] == shipping_type.value:
            return float(item["rate_usd"])
    return None


def build_shipping_line(
    shipping_type: ShippingType,
    quantity: int,
    rate_usd: float,
    exchange_rate: float,
    policy: LandedCostPolicyCandidate,
    *,
    source_type: str,
    source_reference: Optional[str] = None,
    rule_status: Optional[str] = None,
    notes: Optional[str] = None,
) -> LandedCostShippingLine:
    cost_jpy = _round_money(quantity * rate_usd * exchange_rate)
    markup = policy.shipping_markup_multiplier
    sales = _round_money(cost_jpy * markup) if markup is not None else None
    return LandedCostShippingLine(
        shipping_type=shipping_type,
        quantity=quantity,
        rate_usd=rate_usd,
        exchange_rate=exchange_rate,
        cost_jpy=cost_jpy,
        sales_markup_multiplier=markup,
        sales_price_candidate_jpy=sales,
        source_type=source_type,
        source_reference=source_reference,
        rule_status=rule_status,
        notes=notes,
    )


def calculate_landed_cost_scenario(
    *,
    scenario_id: str,
    case_id: Optional[str],
    name: Optional[str],
    exchange_rate: float,
    policy: LandedCostPolicyCandidate,
    product_inputs: Sequence[dict],
    shipping_lines: Sequence[LandedCostShippingLine],
    sales_candidates: Optional[Sequence[SalesPriceCandidate]] = None,
    unresolved_components: Optional[Sequence[str]] = None,
    insurance_mode: Optional[InsuranceMode] = None,
    supplier_insurance_usd: Optional[float] = None,
    manual_insurance_jpy: Optional[float] = None,
    domestic_shipping_jpy: Optional[float] = None,
    price_book_candidates: Optional[Sequence[SKUMasterCandidate]] = None,
    captured_at: Optional[datetime] = None,
    source_references: Optional[Sequence[str]] = None,
    adjustments: Optional[Sequence[QuoteAdjustment]] = None,
) -> tuple[LandedCostScenario, QuoteEconomicsResult]:
    captured = captured_at or datetime.now(timezone.utc)
    mode = insurance_mode or policy.insurance_mode
    product_lines = []
    warnings = []
    other_cost = 0.0
    unresolved = list(unresolved_components or [])

    for index, item in enumerate(product_inputs):
        line, line_warnings = _product_cost_line(
            item,
            exchange_rate=exchange_rate,
            policy=policy,
            insurance_mode=mode,
            sales_candidates=sales_candidates or [],
            domestic_shipping_jpy=_domestic_for_line(index, policy, domestic_shipping_jpy),
            price_book_candidates=price_book_candidates or [],
            snapshot_id=f"{scenario_id}-{item.get('sku') or index}",
            captured_at=captured,
        )
        product_lines.append(line)
        warnings.extend(line_warnings)

    if mode == InsuranceMode.SUPPLIER_QUOTED:
        if supplier_insurance_usd is None:
            unresolved.append("Supplier-quoted insurance amount")
            warnings.append("InsuranceMode.SUPPLIER_QUOTED requires an explicit supplier amount. It is not inferred.")
        else:
            other_cost += _round_money(supplier_insurance_usd * exchange_rate)
            warnings.append("Supplier-quoted insurance is a separate cost. It is not the internal percentage policy.")
    elif mode == InsuranceMode.FIXED_JPY:
        if manual_insurance_jpy is None:
            unresolved.append("Fixed insurance JPY")
        else:
            other_cost += _round_money(manual_insurance_jpy)
    elif mode == InsuranceMode.MANUAL:
        if manual_insurance_jpy is None:
            unresolved.append("Manual insurance JPY")
        else:
            other_cost += _round_money(manual_insurance_jpy)
    elif mode == InsuranceMode.PERCENTAGE and policy.insurance_rate is None:
        unresolved.append("Internal insurance rate")
        warnings.append("PERCENTAGE insurance requires a Policy rate. 3% is not hardcoded.")
    elif mode == InsuranceMode.NONE:
        warnings.append("Insurance mode is NONE. Customer-quote 'included' is not an internal cost.")

    if policy.import_tax_rate is None:
        unresolved.append("Import tax rate")
        warnings.append("Import tax rate must be supplied by Policy / Scenario. 10% is not hardcoded.")
    if policy.import_tax_basis not in {CostBasis.PRODUCT_DEALER_JPY, CostBasis.MANUAL}:
        warnings.append(f"Import tax basis {policy.import_tax_basis.value} is not an extracted quote-calc basis.")
    if policy.domestic_shipping_mode == DomesticShippingMode.REVIEW_REQUIRED:
        warnings.append(
            "Domestic shipping basis is REVIEW_REQUIRED. "
            "The known 5000-yen rule does not match the quote-calc sheet."
        )
        if domestic_shipping_jpy is None:
            unresolved.append("Domestic shipping basis")
    if any(line.dealer_price_usd is None for line in product_lines):
        unresolved.append("Manufacturer dealer price")
    if any(line.sku is None for line in product_lines):
        unresolved.append("Product SKU")

    product_landed = _sum(line.landed_cost_jpy for line in product_lines)
    shipping_cost = _sum(line.cost_jpy for line in shipping_lines)
    product_sales = _sum(line.standard_sales_price_jpy for line in product_lines)
    shipping_sales = _sum(line.sales_price_candidate_jpy for line in shipping_lines)
    if any(line.standard_sales_price_jpy is None for line in product_lines):
        unresolved.append("Product sales price candidate")
        warnings.append("Landed Cost Engine does not recalculate SalesPriceCandidate.")
    if policy.shipping_markup_multiplier is None and shipping_lines:
        warnings.append("Shipping sales candidate is omitted because markup is not a confirmed Policy value.")
    total_sales = None if product_sales is None or shipping_sales is None else _round_money(product_sales + shipping_sales)
    total_landed = None
    if product_landed is not None and shipping_cost is not None:
        total_landed = _round_money(product_landed + shipping_cost + other_cost)

    complete = not unresolved
    status = ScenarioCompleteness.COMPLETE if complete else ScenarioCompleteness.INCOMPLETE
    gross_profit = None
    gross_margin = None
    if complete and total_sales is not None and total_landed is not None and total_sales:
        gross_profit = _round_money(total_sales - total_landed)
        gross_margin = round(gross_profit / total_sales, 6)
    elif not complete:
        warnings.append("Official gross margin is withheld because the scenario is INCOMPLETE.")

    scenario = LandedCostScenario(
        scenario_id=scenario_id,
        case_id=case_id,
        name=name,
        exchange_rate=exchange_rate,
        product_lines=product_lines,
        shipping_lines=list(shipping_lines),
        insurance_input=mode,
        import_tax_policy=policy,
        domestic_shipping_policy=policy,
        calculation_policy=policy,
        captured_at=captured,
        source_references=list(source_references or []),
        unresolved_components=unresolved,
        adjustments=list(adjustments or []),
        status=status,
        warnings=_unique(warnings),
    )
    economics = QuoteEconomicsResult(
        scenario_id=scenario_id,
        product_sales_total_jpy=product_sales,
        shipping_sales_total_jpy=shipping_sales,
        total_sales_ex_tax_jpy=total_sales,
        product_landed_cost_total_jpy=product_landed,
        shipping_cost_total_jpy=shipping_cost,
        other_cost_total_jpy=_round_money(other_cost),
        total_landed_cost_jpy=total_landed,
        gross_profit_jpy=gross_profit,
        gross_margin_rate=gross_margin,
        status=status,
        warnings=_unique(warnings),
    )
    return scenario, economics


def compare_quote_economics(
    economics: QuoteEconomicsResult,
    *,
    configuration_name: str,
    quote_number: Optional[str],
    historical_product_sales_jpy: Optional[float],
    historical_shipping_sales_jpy: Optional[float],
    historical_total_sales_jpy: Optional[float],
    product_comparisons: Optional[Sequence[HistoricalPriceComparison]] = None,
) -> QuoteEconomicsResult:
    comparison = QuoteEconomicsComparison(
        configuration_name=configuration_name,
        quote_number=quote_number,
        product_sales_calculated_jpy=economics.product_sales_total_jpy,
        product_sales_historical_jpy=historical_product_sales_jpy,
        product_sales_difference_jpy=_delta(economics.product_sales_total_jpy, historical_product_sales_jpy),
        shipping_sales_calculated_jpy=economics.shipping_sales_total_jpy,
        shipping_sales_historical_jpy=historical_shipping_sales_jpy,
        shipping_sales_difference_jpy=_delta(economics.shipping_sales_total_jpy, historical_shipping_sales_jpy),
        total_sales_calculated_jpy=economics.total_sales_ex_tax_jpy,
        total_sales_historical_jpy=historical_total_sales_jpy,
        total_sales_difference_jpy=_delta(economics.total_sales_ex_tax_jpy, historical_total_sales_jpy),
        landed_cost_jpy=economics.total_landed_cost_jpy,
        gross_profit_jpy=economics.gross_profit_jpy,
        gross_margin_rate=economics.gross_margin_rate,
        status=economics.status,
        notes="Historical Customer Quote is an acceptance comparison, not a calculation source.",
    )
    return economics.model_copy(
        update={
            "comparisons": list(product_comparisons or economics.comparisons),
            "economics_comparison": comparison,
        }
    )


def build_ihi_landed_cost_scenario(
    configuration: str,
    *,
    exchange_rate: float,
    policy: LandedCostPolicyCandidate,
    dealer_values: dict[str, dict],
    sales_candidates: Sequence[SalesPriceCandidate],
    shipping_source: str = "DEALER_UPDATE_SNAPSHOT",
    price_book_candidates: Optional[Sequence[SKUMasterCandidate]] = None,
    captured_at: Optional[datetime] = None,
) -> tuple[LandedCostScenario, QuoteEconomicsResult]:
    key = configuration.upper()
    products = IHI_KNOWN_PRODUCTS[key]
    unresolved = list(IHI_UNRESOLVED[key])
    from_master = dealer_values_from_candidates(price_book_candidates or [], products)
    product_inputs = []
    for sku in products:
        values = from_master.get(sku) or dealer_values.get(sku)
        if values is None or values.get("dealer_price_usd") is None:
            unresolved.append(f"{sku} Current Dealer")
            continue
        product_inputs.append(
            {
                "sku": sku,
                "quantity": 1,
                "dealer_price_usd": values["dealer_price_usd"],
                "msrp_usd": values.get("msrp_usd"),
                "description": values.get("description"),
                "price_book": values.get("price_book"),
                "price_book_version": values.get("price_book_version"),
                "sales_sheet": key,
            }
        )
    shipping_lines = []
    for shipping_type, quantity in IHI_SHIPPING[key]:
        if shipping_source == "SUPPLIER_QUOTE":
            rate = supplier_quote_shipping_rate(shipping_type)
            reference = "ihi-supplier-quote-shipping"
        else:
            rate = september_dealer_update_shipping_rate(shipping_type)
            reference = "dealer-update-2026-09-shipping"
        if rate is None:
            continue
        shipping_lines.append(
            build_shipping_line(
                shipping_type,
                quantity,
                rate,
                exchange_rate,
                policy,
                source_type=shipping_source,
                source_reference=reference,
                rule_status="SNAPSHOT",
                notes="Human/Golden snapshot. CANDIDATE ShippingRule was not auto-selected.",
            )
        )
    scenario, economics = calculate_landed_cost_scenario(
        scenario_id=f"ihi-{key.lower()}-landed-cost",
        case_id="IHI_QUOTE_001",
        name=f"IHI {key} Landed Cost",
        exchange_rate=exchange_rate,
        policy=policy,
        product_inputs=product_inputs,
        shipping_lines=shipping_lines,
        sales_candidates=sales_candidates,
        unresolved_components=unresolved,
        insurance_mode=InsuranceMode.PERCENTAGE,
        domestic_shipping_jpy=IHI_SHEET_DOMESTIC_FIRST_LINE_JPY,
        price_book_candidates=price_book_candidates,
        captured_at=captured_at,
        source_references=[
            "DT/PT quote-calc sheet",
            "Manufacturer Current Dealer Price",
            "SpaceOne SalesPriceCandidate",
            shipping_source,
        ],
    )
    return scenario, economics


def ihi_historical_sales_totals(quote: dict) -> dict:
    product = sum(float(line.get("line_total_jpy") or 0) for line in quote.get("lines") or [])
    shipping = float((quote.get("shipping") or {}).get("price_jpy") or 0)
    return {
        "product_sales_jpy": product,
        "shipping_sales_jpy": shipping,
        "total_sales_jpy": float(quote.get("subtotal_ex_tax_jpy") or product + shipping),
        "quote_number": quote.get("quote_number"),
    }


def resolve_ihi_dealer_values(candidates: Optional[Sequence[SKUMasterCandidate]] = None) -> dict[str, dict]:
    skus = list(IHI_KNOWN_PRODUCTS["MAG"]) + list(IHI_KNOWN_PRODUCTS["PHOTON"])
    values = dealer_values_from_candidates(candidates or [], skus)
    for sku in skus:
        if sku in values and values[sku].get("dealer_price_usd") is not None:
            continue
        fallback = IHI_DEVELOPMENT_DEALER_VALUES.get(sku)
        if fallback:
            values[sku] = dict(fallback)
    return values


def dealer_values_from_candidates(candidates: Sequence[SKUMasterCandidate], skus: Sequence[str]) -> dict[str, dict]:
    by_sku = {}
    for candidate in candidates:
        if candidate.sku in skus and candidate.sku not in by_sku:
            first = candidate.occurrences[0] if candidate.occurrences else None
            by_sku[candidate.sku] = {
                "dealer_price_usd": candidate.dealer_price_usd,
                "msrp_usd": candidate.msrp_usd,
                "description": candidate.description,
                "price_book": first.source_price_book if first else None,
                "price_book_version": None,
            }
    return by_sku


def policy_from_inputs(
    *,
    import_tax_rate: Optional[float],
    insurance_mode: InsuranceMode,
    insurance_rate: Optional[float],
    shipping_markup_multiplier: Optional[float],
    domestic_shipping_jpy: Optional[float] = None,
    domestic_shipping_mode: DomesticShippingMode = DomesticShippingMode.REVIEW_REQUIRED,
    policy_id: str = "lcp-user",
) -> LandedCostPolicyCandidate:
    return LandedCostPolicyCandidate(
        landed_cost_policy_candidate_id=policy_id,
        policy_name="User / Scenario landed-cost policy",
        import_tax_rate=import_tax_rate,
        import_tax_basis=CostBasis.PRODUCT_DEALER_JPY if import_tax_rate is not None else CostBasis.REVIEW_REQUIRED,
        insurance_mode=insurance_mode,
        insurance_rate=insurance_rate,
        insurance_basis=CostBasis.PRODUCT_DEALER_JPY if insurance_mode == InsuranceMode.PERCENTAGE else CostBasis.MANUAL,
        domestic_shipping_mode=domestic_shipping_mode,
        domestic_shipping_jpy=domestic_shipping_jpy,
        shipping_markup_multiplier=shipping_markup_multiplier,
        status=PricingPolicyStatus.CANDIDATE,
        notes="Rates come from Policy / UI / quote-calc extraction. The engine does not hardcode 10% / 3% / 5000.",
    )


def _product_cost_line(
    item: dict,
    *,
    exchange_rate: float,
    policy: LandedCostPolicyCandidate,
    insurance_mode: InsuranceMode,
    sales_candidates: Sequence[SalesPriceCandidate],
    domestic_shipping_jpy: float,
    price_book_candidates: Sequence[SKUMasterCandidate],
    snapshot_id: str,
    captured_at: datetime,
) -> tuple[ProductCostLine, list[str]]:
    warnings = []
    sku = item.get("sku")
    quantity = int(item.get("quantity") or 1)
    dealer_usd = item.get("dealer_price_usd")
    msrp_usd = item.get("msrp_usd")
    if item.get("use_supplier_msrp_as_cost"):
        raise ValueError("Supplier MSRP is not a product cost basis.")
    snapshot = item.get("manufacturer_price_snapshot")
    if snapshot is None and sku:
        if price_book_candidates:
            snapshot = create_quote_price_snapshot(
                sku,
                price_book_candidates,
                snapshot_id=snapshot_id,
                price_book_version=item.get("price_book_version"),
                source_reference=item.get("price_book"),
                captured_at=captured_at,
                exchange_rate=exchange_rate,
            )
            dealer_usd = snapshot.manufacturer_dealer_price_usd if snapshot.manufacturer_dealer_price_usd is not None else dealer_usd
            msrp_usd = snapshot.manufacturer_msrp_usd if snapshot.manufacturer_msrp_usd is not None else msrp_usd
        else:
            snapshot = QuotePriceSnapshot(
                snapshot_id=snapshot_id,
                sku=sku,
                price_book=item.get("price_book"),
                price_book_version=item.get("price_book_version"),
                manufacturer_msrp_usd=msrp_usd,
                manufacturer_dealer_price_usd=dealer_usd,
                exchange_rate=exchange_rate,
                captured_at=captured_at,
                source_reference="scenario-input",
            )
    dealer_jpy = _round_money(dealer_usd * quantity * exchange_rate) if dealer_usd is not None else None
    import_tax = None
    if dealer_jpy is not None and policy.import_tax_rate is not None:
        if policy.import_tax_basis == CostBasis.PRODUCT_DEALER_JPY:
            import_tax = _round_money(dealer_jpy * policy.import_tax_rate)
        else:
            warnings.append("Import tax basis is not PRODUCT_DEALER_JPY. Tax was not invented.")
    insurance = 0.0
    if insurance_mode == InsuranceMode.PERCENTAGE and dealer_jpy is not None and policy.insurance_rate is not None:
        if policy.insurance_basis == CostBasis.PRODUCT_DEALER_JPY:
            insurance = _round_money(dealer_jpy * policy.insurance_rate)
        else:
            warnings.append("Internal insurance basis is not PRODUCT_DEALER_JPY. Percentage was not applied.")
            insurance = None
    elif insurance_mode in {InsuranceMode.SUPPLIER_QUOTED, InsuranceMode.NONE}:
        insurance = 0.0
    elif insurance_mode in {InsuranceMode.FIXED_JPY, InsuranceMode.MANUAL}:
        insurance = 0.0
    sales = _pick_sales_candidate(sales_candidates, sku, item.get("sales_sheet"))
    sales_price = sales.raw_sales_price_jpy if sales else item.get("standard_sales_price_jpy")
    if sales is None and item.get("standard_sales_price_jpy") is None:
        warnings.append(f"{sku}: SalesPriceCandidate is missing. Engine does not invent a sales price.")
    landed = None
    if dealer_jpy is not None and import_tax is not None and insurance is not None:
        landed = _round_money(dealer_jpy + import_tax + insurance + domestic_shipping_jpy)
    return (
        ProductCostLine(
            sku=sku,
            description=item.get("description"),
            quantity=quantity,
            dealer_price_usd=dealer_usd,
            msrp_usd=msrp_usd,
            exchange_rate=exchange_rate,
            dealer_cost_jpy=dealer_jpy,
            import_tax_jpy=import_tax,
            insurance_jpy=insurance,
            domestic_shipping_jpy=domestic_shipping_jpy,
            landed_cost_jpy=landed,
            standard_sales_price_jpy=sales_price,
            manufacturer_price_snapshot=snapshot,
            warnings=warnings,
        ),
        warnings,
    )


def _domestic_for_line(index: int, policy: LandedCostPolicyCandidate, amount: Optional[float]) -> float:
    if amount is None:
        return 0.0
    if policy.domestic_shipping_mode == DomesticShippingMode.PER_PRODUCT_LINE:
        return float(amount)
    if policy.domestic_shipping_mode in {
        DomesticShippingMode.FIRST_PRODUCT_LINE,
        DomesticShippingMode.PER_QUOTE,
        DomesticShippingMode.FIXED_JPY,
        DomesticShippingMode.MANUAL,
        DomesticShippingMode.REVIEW_REQUIRED,
    }:
        return float(amount) if index == 0 else 0.0
    return 0.0


def _pick_sales_candidate(
    candidates: Sequence[SalesPriceCandidate],
    sku: Optional[str],
    sales_sheet: Optional[str],
) -> Optional[SalesPriceCandidate]:
    matches = [item for item in candidates if item.manufacturer_sku == sku]
    if sales_sheet:
        sheet_matches = [
            item for item in matches if (item.source_reference or "").upper() == sales_sheet.upper()
        ]
        if sheet_matches:
            return sheet_matches[0]
    return matches[0] if matches else None


def _sum(values) -> Optional[float]:
    total = 0.0
    seen = False
    for value in values:
        if value is None:
            return None
        total += value
        seen = True
    return _round_money(total) if seen else 0.0


def _delta(left: Optional[float], right: Optional[float]) -> Optional[float]:
    if left is None or right is None:
        return None
    return _round_money(left - right)


def _round_money(value: float) -> float:
    return round(float(value), 4)


def _unique(values: Sequence[str]) -> list[str]:
    seen = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen
