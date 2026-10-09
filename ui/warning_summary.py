from __future__ import annotations

from collections import Counter

from ui.quote_steps import unresolved_required_lines

WARNING_RULES = (
    ("Official manufacturer price book is not set", "price_source"),
    ("SpaceOne price master (SO_MASTER) is not set", "sales_master"),
    ("Standard sales price candidate does not match the quote exchange rate", "stale_candidate"),
    ("Standard sales price candidate was not applied", "standard_review"),
    ("Final sales price was kept after the quote exchange rate changed", "fx_final_kept"),
    ("Standard sales price candidate changed but the final sales price keeps the previous value", "fx_diverged"),
    ("SalesPriceCandidate is missing", "sales_price"),
    ("Landed Cost Engine does not recalculate SalesPriceCandidate", "sales_price"),
    ("Final sales price is not set", "final_price"),
    ("Shipping customer price is not set", "shipping"),
    ("Shipping sales candidate is omitted", "shipping"),
    ("Customer tax rate is not set", "tax"),
    ("Import tax rate must be supplied", "tax"),
    ("Internal insurance rate", "insurance"),
    ("Domestic shipping basis is REVIEW_REQUIRED", "domestic_policy"),
    ("Final sales and landed cost are not both complete", "incomplete_totals"),
    ("Official gross margin is withheld", "margin"),
    ("Gross Margin unavailable", "margin"),
    ("Customer presentation is UNDECIDED", "presentation"),
    ("Required Component unresolved", "required"),
    ("Landed cost is missing", "landed"),
    ("Manufacturer Price Snapshot is missing", "snapshot"),
)


def collect_raw_warnings(draft) -> list[str]:
    if draft is None:
        return []
    messages = list(draft.warnings)
    for line in draft.configuration_lines:
        messages.extend(line.warnings)
    return messages


def classify_warning(message: str) -> str:
    for needle, kind in WARNING_RULES:
        if needle in message:
            return kind
    return "other"


def summarize_draft_warnings(draft) -> dict:
    raw = list(dict.fromkeys(collect_raw_warnings(draft)))
    counts = Counter(classify_warning(item) for item in raw)
    unresolved = unresolved_required_lines(draft)
    if unresolved and not counts["required"]:
        counts["required"] += len(unresolved)
    for line in draft.shipping_lines:
        if line.cost_jpy is not None:
            continue
        notes = line.notes or ""
        if "International shipping cost" in notes:
            counts["international_shipping"] = 1
        if "Domestic shipping cost" in notes:
            counts["domestic_shipping"] = 1
    if not draft.lead_time_text:
        counts["lead_time"] = 1
    lines = []
    if counts["price_source"]:
        lines.append(("price_source", counts["price_source"]))
    if counts["stale_candidate"]:
        lines.append(("stale_candidate", counts["stale_candidate"]))
    for kind in ("fx_final_kept", "fx_diverged", "standard_review"):
        if counts[kind]:
            lines.append((kind, counts[kind]))
    if counts["sales_master"]:
        lines.append(("sales_master", counts["sales_master"]))
    if counts["final_price"]:
        lines.append(("final_price", counts["final_price"]))
    elif counts["sales_price"]:
        lines.append(("sales_price", counts["sales_price"]))
    if counts["international_shipping"]:
        lines.append(("international_shipping", 1))
    if counts["domestic_shipping"]:
        lines.append(("domestic_shipping", 1))
    if counts["shipping"]:
        lines.append(("shipping", counts["shipping"]))
    if counts["tax"]:
        lines.append(("tax", counts["tax"]))
    if counts["insurance"]:
        lines.append(("insurance", counts["insurance"]))
    if counts["domestic_policy"]:
        lines.append(("domestic_policy", counts["domestic_policy"]))
    if counts["margin"]:
        lines.append(("margin", counts["margin"]))
    if counts["presentation"]:
        lines.append(("presentation", counts["presentation"]))
    if counts["required"]:
        lines.append(("required", counts["required"]))
    if counts["landed"]:
        lines.append(("landed", counts["landed"]))
    if counts["snapshot"]:
        lines.append(("snapshot", counts["snapshot"]))
    if counts["lead_time"]:
        lines.append(("lead_time", 1))
    if counts["other"]:
        lines.append(("other", counts["other"]))
    return {
        "count": sum(count for _kind, count in lines),
        "lines": lines,
        "raw": raw,
    }


def format_warning_lines(summary: dict, labels: dict) -> list[str]:
    formatted = []
    for kind, count in summary["lines"]:
        template = labels.get(kind, labels.get("other", "{count}"))
        formatted.append(template.format(count=count))
    return formatted


def format_warning_details(summary: dict, labels: dict, generic: str) -> list[str]:
    details = []
    for message in summary["raw"]:
        kind = classify_warning(message)
        if kind == "incomplete_totals":
            continue
        if kind == "sales_price":
            text = labels.get("sales_price_detail", labels.get("sales_price", generic))
        elif kind == "other":
            text = generic
        else:
            text = labels.get(kind, generic)
        rendered = text.format(count=1)
        if rendered not in details:
            details.append(rendered)
    return details
