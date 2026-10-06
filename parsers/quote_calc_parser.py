import re
from collections import defaultdict
from pathlib import Path
from typing import Optional, Union

from openpyxl import load_workbook

from models import (
    CostBasis,
    DomesticShippingMode,
    InsuranceMode,
    LandedCostPolicyCandidate,
    PricingPolicyStatus,
    QuoteCalcAudit,
    QuoteCalcCellAudit,
    RoundingMethod,
)

KNOWN_OPERATIONAL_IMPORT_TAX_RATE = 0.10
KNOWN_OPERATIONAL_INSURANCE_RATE = 0.03
KNOWN_OPERATIONAL_SHIPPING_MARKUP = 1.2
KNOWN_OPERATIONAL_DOMESTIC_JPY = 5000.0

TAX_FORMULA_RE = re.compile(r"^=H(?P<row>\d+)\*(?P<rate>\d+(?:\.\d+)?)$", re.IGNORECASE)
INSURANCE_FORMULA_RE = re.compile(r"^=H(?P<row>\d+)\*(?P<rate>\d+(?:\.\d+)?)$", re.IGNORECASE)
SUM_HK_RE = re.compile(r"^=SUM\(H(?P<row>\d+):K(?P=row)\)$", re.IGNORECASE)


def locate_quote_calc_workbook() -> Optional[Path]:
    # The quote-calc workbook is the QUOTE_CALC master activated in the price master registry.
    # Explicit paths can still be passed to extract_quote_calc_audit() directly.
    from agents.price_master import get_active_master
    from models import PriceMasterType

    active = get_active_master(PriceMasterType.QUOTE_CALC)
    return active.path if active else None


def extract_quote_calc_audit(
    source: Union[str, Path],
) -> QuoteCalcAudit:
    formulas = load_workbook(source, data_only=False)
    if hasattr(source, "seek"):
        source.seek(0)
    values = load_workbook(source, data_only=True)
    if hasattr(source, "seek"):
        source.seek(0)
    path = source if isinstance(source, Path) else Path(str(source)) if isinstance(source, str) else None
    cells: list[QuoteCalcCellAudit] = []
    tax_rates = []
    insurance_rates = []
    shipping_markups = []
    domestic_by_sheet = defaultdict(list)
    sheet_notes = []

    for sheet_name in formulas.sheetnames:
        formula_sheet = formulas[sheet_name]
        value_sheet = values[sheet_name] if sheet_name in values.sheetnames else None
        for row in formula_sheet.iter_rows(min_row=1, max_row=formula_sheet.max_row, max_col=12):
            row_number = row[0].row
            h_formula = _cell_formula(row[7])
            i_formula = _cell_formula(row[8])
            j_formula = _cell_formula(row[9])
            k_formula = _cell_formula(row[10])
            g_formula = _cell_formula(row[6])
            f_formula = _cell_formula(row[5])
            displayed = _row_values(value_sheet, row_number) if value_sheet is not None else {}

            tax_match = TAX_FORMULA_RE.fullmatch((i_formula or "").replace(" ", ""))
            if tax_match:
                rate = float(tax_match.group("rate"))
                tax_rates.append(rate)
                cells.append(
                    QuoteCalcCellAudit(
                        sheet=sheet_name,
                        cell=f"I{row_number}",
                        formula=i_formula,
                        displayed_value=displayed.get("I"),
                        notes="Import tax = H * rate. Basis is PRODUCT_DEALER_JPY.",
                    )
                )
            insurance_match = INSURANCE_FORMULA_RE.fullmatch((k_formula or "").replace(" ", ""))
            if insurance_match:
                rate = float(insurance_match.group("rate"))
                insurance_rates.append(rate)
                cells.append(
                    QuoteCalcCellAudit(
                        sheet=sheet_name,
                        cell=f"K{row_number}",
                        formula=k_formula,
                        displayed_value=displayed.get("K"),
                        notes="Insurance = H * rate. Basis is PRODUCT_DEALER_JPY.",
                    )
                )
            if SUM_HK_RE.fullmatch((g_formula or "").replace(" ", "")):
                cells.append(
                    QuoteCalcCellAudit(
                        sheet=sheet_name,
                        cell=f"G{row_number}",
                        formula=g_formula,
                        displayed_value=displayed.get("G"),
                        notes="Product subtotal = SUM(H:K). Shipping is outside this sum.",
                    )
                )
            if h_formula:
                cells.append(
                    QuoteCalcCellAudit(
                        sheet=sheet_name,
                        cell=f"H{row_number}",
                        formula=h_formula,
                        displayed_value=displayed.get("H"),
                        notes="Dealer JPY cell. IHI sheet stores a number, not DealerUSD*FX.",
                    )
                )
            j_value = displayed.get("J")
            if tax_match and (j_formula or _is_number(j_value)):
                domestic_by_sheet[sheet_name].append(
                    {
                        "row": row_number,
                        "formula": j_formula,
                        "value": float(j_value) if _is_number(j_value) else None,
                    }
                )
                cells.append(
                    QuoteCalcCellAudit(
                        sheet=sheet_name,
                        cell=f"J{row_number}",
                        formula=j_formula,
                        displayed_value=float(j_value) if _is_number(j_value) else None,
                        notes="Domestic shipping is a typed number on audited product rows, not a formula.",
                    )
                )
            markup = _shipping_markup(f_formula, g_formula, displayed)
            if markup is not None:
                shipping_markups.append(markup)
                cells.append(
                    QuoteCalcCellAudit(
                        sheet=sheet_name,
                        cell=f"F{row_number}/G{row_number}",
                        formula=f_formula or g_formula,
                        displayed_value=markup,
                        notes="Shipping sales / shipping cost. IHI uses typed 1.2, not a live formula.",
                    )
                )

        if "120%" in _sheet_text(formula_sheet) or "DTの120" in _sheet_text(formula_sheet):
            sheet_notes.append(f"{sheet_name}: shipping label refers to DT 120%.")
        if sheet_name not in domestic_by_sheet and any(
            item.sheet == sheet_name and item.cell.startswith("I") for item in cells
        ):
            domestic_by_sheet[sheet_name] = []

    tax_rate = _unique_rate(tax_rates)
    insurance_rate = _unique_rate(insurance_rates)
    shipping_markup = _unique_rate(shipping_markups)
    domestic_notes, domestic_mode = _domestic_basis(domestic_by_sheet)
    known_checks = _compare_known_rules(tax_rate, insurance_rate, shipping_markup, domestic_by_sheet)
    policy = LandedCostPolicyCandidate(
        landed_cost_policy_candidate_id="lcp-quote-calc",
        policy_name="SpaceOne quote-calc legacy candidate",
        import_tax_rate=tax_rate,
        import_tax_basis=CostBasis.PRODUCT_DEALER_JPY if tax_rate is not None else CostBasis.REVIEW_REQUIRED,
        insurance_mode=InsuranceMode.PERCENTAGE if insurance_rate is not None else InsuranceMode.NONE,
        insurance_rate=insurance_rate,
        insurance_basis=CostBasis.PRODUCT_DEALER_JPY if insurance_rate is not None else CostBasis.REVIEW_REQUIRED,
        domestic_shipping_mode=domestic_mode,
        domestic_shipping_jpy=None,
        shipping_markup_multiplier=shipping_markup,
        rounding_method=RoundingMethod.ROUNDING_UNKNOWN,
        rounding_unit=None,
        source_formula_refs=[f"{item.sheet}!{item.cell}" for item in cells[:40]],
        status=(
            PricingPolicyStatus.REVIEW_REQUIRED
            if domestic_mode == DomesticShippingMode.REVIEW_REQUIRED
            else PricingPolicyStatus.CANDIDATE
        ),
        confidence="HIGH" if tax_rate is not None and insurance_rate is not None else "LOW",
        notes=(
            "Extracted from DT/PT quote-calc formulas. "
            "Rates are not hardcoded in the engine. "
            "Domestic shipping basis is inconsistent across sheets. "
            "Rounding is not a live formula on the audited IHI sheet."
        ),
    )
    return QuoteCalcAudit(
        source_path=str(path) if path else None,
        cells=cells,
        observed_import_tax_rate=tax_rate,
        observed_import_tax_basis=policy.import_tax_basis,
        observed_insurance_rate=insurance_rate,
        observed_insurance_mode=policy.insurance_mode,
        observed_insurance_basis=policy.insurance_basis,
        observed_shipping_markup=shipping_markup,
        domestic_observations=domestic_notes,
        sheet_differences=sheet_notes + domestic_notes,
        known_rule_checks=known_checks,
        policy_candidate=policy,
    )


def extract_landed_cost_policy_candidate(
    source: Union[str, Path],
) -> LandedCostPolicyCandidate:
    audit = extract_quote_calc_audit(source)
    if audit.policy_candidate is None:
        raise ValueError("Quote-calc policy candidate could not be extracted.")
    return audit.policy_candidate


def _cell_formula(cell) -> Optional[str]:
    value = cell.value
    if isinstance(value, str) and value.startswith("="):
        return value
    return None


def _row_values(sheet, row_number: int) -> dict:
    values = {}
    for column, letter in enumerate(("F", "G", "H", "I", "J", "K"), start=6):
        value = sheet.cell(row_number, column).value
        if _is_number(value):
            values[letter] = float(value)
    return values


def _shipping_markup(f_formula: Optional[str], g_formula: Optional[str], displayed: dict) -> Optional[float]:
    if f_formula and g_formula and f_formula.replace(" ", "") == g_formula.replace(" ", "") + "*1.2":
        return 1.2
    if f_formula and "*1.2" in f_formula.replace(" ", ""):
        return 1.2
    sales = displayed.get("F")
    cost = displayed.get("G")
    if _is_number(sales) and _is_number(cost) and cost:
        ratio = round(float(sales) / float(cost), 4)
        if abs(ratio - 1.2) <= 0.0001:
            return 1.2
    return None


def _domestic_basis(domestic_by_sheet: dict) -> tuple[list[str], DomesticShippingMode]:
    notes = []
    modes = set()
    for sheet_name, rows in domestic_by_sheet.items():
        numeric = [item for item in rows if item["value"]]
        formulas = [item for item in rows if item["formula"]]
        if formulas:
            notes.append(f"{sheet_name}: domestic J has a formula; basis stays REVIEW_REQUIRED.")
            modes.add(DomesticShippingMode.REVIEW_REQUIRED)
            continue
        if not numeric:
            notes.append(f"{sheet_name}: no domestic J amount.")
            continue
        amounts = {item["value"] for item in numeric}
        if amounts == {10000.0} and len(numeric) == 1:
            notes.append(f"{sheet_name}: J=10000 on one product line only. Not a 5000 rule.")
            modes.add(DomesticShippingMode.FIRST_PRODUCT_LINE)
        elif amounts == {10000.0} and len(numeric) > 1:
            notes.append(f"{sheet_name}: J=10000 on multiple product lines. Not a 5000 rule.")
            modes.add(DomesticShippingMode.PER_PRODUCT_LINE)
        else:
            notes.append(f"{sheet_name}: domestic J amounts {sorted(amounts)}. Basis unclear.")
            modes.add(DomesticShippingMode.REVIEW_REQUIRED)
    if not modes:
        return notes or ["Domestic shipping formula was not found."], DomesticShippingMode.REVIEW_REQUIRED
    if modes == {DomesticShippingMode.FIRST_PRODUCT_LINE}:
        notes.append("First-line-only 10000 is sheet-specific, not a general policy.")
        return notes, DomesticShippingMode.REVIEW_REQUIRED
    if len(modes) > 1:
        notes.append("Domestic allocation differs across sheets. Do not invent a 5000-yen rule.")
        return notes, DomesticShippingMode.REVIEW_REQUIRED
    if modes == {DomesticShippingMode.PER_PRODUCT_LINE}:
        notes.append("Per-line 10000 is sheet-specific and conflicts with the known 5000 operational note.")
        return notes, DomesticShippingMode.REVIEW_REQUIRED
    return notes, DomesticShippingMode.REVIEW_REQUIRED


def _compare_known_rules(
    tax_rate: Optional[float],
    insurance_rate: Optional[float],
    shipping_markup: Optional[float],
    domestic_by_sheet: dict,
) -> list[str]:
    checks = []
    if tax_rate == KNOWN_OPERATIONAL_IMPORT_TAX_RATE:
        checks.append("Import tax 10% matches the quote-calc I=H*0.1 formulas. Keep as Policy Candidate.")
    elif tax_rate is not None:
        checks.append(f"Import tax observed {tax_rate} does not match the known 10% note. REVIEW_REQUIRED.")
    if insurance_rate == KNOWN_OPERATIONAL_INSURANCE_RATE:
        checks.append("Insurance 3% matches the quote-calc K=H*0.03 formulas. Keep as Policy Candidate.")
    elif insurance_rate is not None:
        checks.append(f"Insurance observed {insurance_rate} does not match the known 3% note. REVIEW_REQUIRED.")
    if shipping_markup == KNOWN_OPERATIONAL_SHIPPING_MARKUP:
        checks.append("Shipping markup 1.2 matches the quote-calc shipping rows. Keep as Policy Candidate.")
    elif shipping_markup is not None:
        checks.append(f"Shipping markup observed {shipping_markup} does not match the known 1.2 note. REVIEW_REQUIRED.")
    domestic_values = {
        item["value"]
        for rows in domestic_by_sheet.values()
        for item in rows
        if item["value"] is not None
    }
    if domestic_values == {KNOWN_OPERATIONAL_DOMESTIC_JPY}:
        checks.append("Domestic shipping 5000 matches the sheet. Keep as Policy Candidate.")
    else:
        checks.append(
            "Domestic shipping 5000 does not match the sheet "
            f"(observed {sorted(domestic_values) if domestic_values else 'none'}). REVIEW_REQUIRED."
        )
    return checks


def _unique_rate(values: list[float]) -> Optional[float]:
    unique = {round(value, 6) for value in values}
    if len(unique) == 1:
        return unique.pop()
    return None


def _sheet_text(sheet) -> str:
    parts = []
    for row in sheet.iter_rows(max_col=6, max_row=min(sheet.max_row, 40), values_only=True):
        for value in row:
            if isinstance(value, str):
                parts.append(value)
    return " ".join(parts)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
