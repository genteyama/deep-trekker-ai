"""Display and input helpers for exchange rate and sales price decisions in the quote workspace.

Pure functions so the Streamlit screens stay thin and the rules can be unit tested.
"""

from __future__ import annotations

from typing import Optional

from agents.pricing_policy import parse_exchange_rate
from agents.quote_builder import (
    CANDIDATE_NOT_APPLIED_MARKER,
    FINAL_PRICE_KEPT_MARKER,
    STALE_CANDIDATE_MARKER,
    STANDARD_DIVERGED_MARKER,
    apply_exchange_rate,
    apply_final_price,
)
from models import ExchangeRateReason, FinalPriceStatus, PriceAdjustmentReason, PricingPolicyType

SALES_MASTER_MISSING_MARKER = "SpaceOne price master (SO_MASTER) is not set"

# (needle in line.warnings, review reason key). The first match wins.
STANDARD_REVIEW_RULES = (
    ("policy identity is ambiguous", "ambiguous_candidates"),
    ("does not match the quote manufacturer snapshot MSRP", "msrp_mismatch"),
    (STALE_CANDIDATE_MARKER, "stale_rate"),
    (SALES_MASTER_MISSING_MARKER, "sales_master_missing"),
    ("could not be calculated", "not_calculable"),
)


def reason_options(enum_type) -> list[str]:
    return [item.value for item in enum_type]


def reason_label(labels: dict, code) -> str:
    value = getattr(code, "value", code)
    if value is None:
        return ""
    return labels.get(value, value)


def exchange_rate_reason_options() -> list[str]:
    return reason_options(ExchangeRateReason)


def price_adjustment_reason_options() -> list[str]:
    return reason_options(PriceAdjustmentReason)


def market_reference_candidate(market_rate: Optional[float], buffer: Optional[float]) -> Optional[float]:
    """Display only: market reference + buffer. Never used as the quote calculation rate."""
    if market_rate is None:
        return None
    return round(market_rate + (buffer or 0.0), 4)


def optional_number(text) -> Optional[float]:
    if text is None or str(text).strip() == "":
        return None
    return float(str(text).strip().replace(",", ""))


def optional_text(text) -> Optional[str]:
    value = (text or "").strip() if isinstance(text, str) else text
    return value or None


def standard_price_basis(workspace: dict, line) -> dict:
    """How the standard sales price was decided, in staff words. status: OK or REVIEW."""
    texts = workspace.get("standard_basis", {})
    policy_type = getattr(line, "pricing_policy_type", None)
    standard = getattr(line, "standard_sales_price_candidate_jpy", None)
    if standard is not None and policy_type == PricingPolicyType.MSRP_MULTIPLIER:
        multiplier = getattr(line, "pricing_multiplier", None)
        return {
            "status": "OK",
            "text": texts.get("msrp_multiplier", "MSRP × {multiplier}").format(multiplier=_multiplier_text(multiplier)),
            "reason": None,
        }
    if standard is not None and policy_type == PricingPolicyType.FIXED_JPY:
        return {"status": "OK", "text": texts.get("fixed_jpy", "FIXED"), "reason": None}
    if standard is not None:
        # Drafts saved before Pricing Policy v1 have a standard price without a recorded policy.
        return {"status": "OK", "text": texts.get("legacy", ""), "reason": None}
    return {
        "status": "REVIEW",
        "text": texts.get("review", "REVIEW"),
        "reason": standard_review_reason(workspace, line),
    }


def standard_review_reason(workspace: dict, line) -> str:
    # Reads the existing line.warnings; no separate review state is kept.
    reasons = workspace.get("standard_review_reasons", {})
    warnings = getattr(line, "warnings", []) or []
    for message in warnings:
        for needle, key in STANDARD_REVIEW_RULES:
            if needle in message:
                return reasons.get(key, key)
    policy_type = getattr(line, "pricing_policy_type", None)
    if policy_type == PricingPolicyType.MANUAL_REVIEW:
        return reasons.get("special_formula", "special_formula")
    if any(CANDIDATE_NOT_APPLIED_MARKER in item for item in warnings):
        return reasons.get("policy_unclassified", "policy_unclassified")
    return reasons.get("no_policy", "no_policy")


def price_comparison(line) -> dict:
    """Standard sales price → case final price, with the signed difference and rate."""
    standard = getattr(line, "standard_sales_price_candidate_jpy", None)
    final = getattr(line, "final_sales_price_jpy", None)
    difference = None
    rate = None
    if standard is not None and final is not None:
        difference = round(final - standard, 4)
        rate = round(difference / standard, 6) if standard else None
    return {"standard": standard, "final": final, "difference": difference, "rate": rate}


def display_signed_yen(value, empty: str) -> str:
    if value is None:
        return empty
    amount = int(round(value))
    sign = "+" if amount > 0 else ("-" if amount < 0 else "±")
    return f"{sign}¥{abs(amount):,}"


def display_signed_percent(value, empty: str) -> str:
    if value is None:
        return empty
    sign = "+" if value > 0 else ("-" if value < 0 else "±")
    return f"{sign}{abs(value):.2%}"


def rate_change_notice(draft) -> dict:
    """Lines whose final price was kept, or now differs from the new standard, after a rate change."""
    kept = []
    diverged = []
    for line in draft.configuration_lines:
        name = line.manufacturer_sku or line.line_id
        if any(FINAL_PRICE_KEPT_MARKER in item for item in line.warnings):
            kept.append(name)
        if any(STANDARD_DIVERGED_MARKER in item for item in line.warnings):
            diverged.append(name)
    return {"kept": kept, "diverged": diverged}


def validate_final_price_input(line, amount_text, reason_code, reason_note) -> dict:
    """Return {"amount", "reason_code", "reason_note", "error"}. error is a locale key or None."""
    try:
        amount = parse_amount(amount_text)
    except ValueError:
        return {"amount": None, "reason_code": None, "reason_note": None, "error": "amount_invalid"}
    code = PriceAdjustmentReason(reason_code) if reason_code else None
    note = optional_text(reason_note)
    standard = getattr(line, "standard_sales_price_candidate_jpy", None)
    if standard is not None and amount != standard and code is None:
        return {"amount": amount, "reason_code": None, "reason_note": note, "error": "reason_required"}
    if code == PriceAdjustmentReason.OTHER and note is None:
        return {"amount": amount, "reason_code": code, "reason_note": None, "error": "note_required"}
    return {"amount": amount, "reason_code": code, "reason_note": note, "error": None}


def parse_amount(text) -> float:
    try:
        value = float(str(text).strip().replace(",", "").replace("¥", "").replace("円", ""))
    except (TypeError, ValueError):
        raise ValueError("Amount must be a number.") from None
    if value != value or value in (float("inf"), float("-inf")) or value < 0:
        raise ValueError("Amount must be a finite number of 0 or more.")
    return value


def submit_final_price(draft, line, values: dict, *, reason_labels: dict, entered_by: Optional[str] = None) -> bool:
    """Save a validated manual final price once. Returns False when the same entry is already saved.

    A Streamlit rerun or a double click must not add a second adjustment for the same decision.
    """
    amount = values["amount"]
    code = values["reason_code"]
    note = values["reason_note"]
    if line.final_price_status == FinalPriceStatus.MANUAL_OVERRIDE and line.final_sales_price_jpy == amount:
        last = next((item for item in reversed(draft.adjustments) if item.line_id == line.line_id), None)
        if last is not None and last.reason_code == code and last.reason_note == note:
            return False
    apply_final_price(
        draft,
        line.line_id,
        FinalPriceStatus.MANUAL_OVERRIDE,
        amount_jpy=amount,
        # The legacy free-text reason keeps a readable copy for older readers of adjustments.
        reason=reason_label(reason_labels, code) or None,
        reason_code=code,
        reason_note=note,
        entered_by=entered_by,
    )
    return True


def parse_exchange_rate_form(values: dict) -> dict:
    """Validate the exchange rate form. Raises ValueError with a locale key as the message."""
    try:
        rate = parse_exchange_rate(values.get("rate"))
    except ValueError:
        raise ValueError("fx_invalid") from None
    try:
        market = optional_number(values.get("market_rate"))
        buffer = optional_number(values.get("buffer"))
    except ValueError:
        raise ValueError("fx_market_invalid") from None
    if market is not None:
        try:
            market = parse_exchange_rate(market)
        except ValueError:
            raise ValueError("fx_market_invalid") from None
    reason = values.get("reason_code")
    return {
        "rate": rate,
        "reason_code": ExchangeRateReason(reason) if reason else None,
        "reason_note": optional_text(values.get("reason_note")),
        "set_by": optional_text(values.get("set_by")),
        "market_reference_rate": market,
        "market_reference_date": optional_text(values.get("market_date")),
        "market_reference_source": optional_text(values.get("market_source")),
        "exchange_rate_buffer": buffer,
    }


def submit_exchange_rate(draft, parsed: dict, *, recalculate=None) -> bool:
    """Apply the adopted rate and its metadata. Returns True when costs were recalculated.

    The same rate is a metadata-only update, so standard candidates are not recalculated for it.
    """
    rate = parsed["rate"]
    changed = rate != draft.exchange_rate
    apply_exchange_rate(
        draft,
        rate,
        sales_candidates=recalculate(rate) if changed and recalculate else None,
        reason_code=parsed["reason_code"],
        reason_note=parsed["reason_note"],
        set_by=parsed["set_by"],
        market_reference_rate=parsed["market_reference_rate"],
        market_reference_date=parsed["market_reference_date"],
        market_reference_source=parsed["market_reference_source"],
        exchange_rate_buffer=parsed["exchange_rate_buffer"],
    )
    return changed


def _multiplier_text(value) -> str:
    if value is None:
        return "?"
    return f"{value:.2f}" if round(value, 2) == value else str(value)
