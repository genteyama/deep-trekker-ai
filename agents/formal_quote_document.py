from typing import Optional

from models import (
    ApprovedQuoteSnapshot,
    FormalQuoteDocument,
    FormalQuoteIssuer,
    FormalQuoteLine,
    QuoteDraft,
    QuoteDraftStatus,
)


class FormalQuoteDocumentError(ValueError):
    pass


def build_formal_quote_document(
    snapshot: ApprovedQuoteSnapshot,
    *,
    official_quote_number: Optional[str] = None,
) -> FormalQuoteDocument:
    if isinstance(snapshot, QuoteDraft):
        raise FormalQuoteDocumentError("FormalQuoteDocument requires an ApprovedQuoteSnapshot.")
    if not isinstance(snapshot, ApprovedQuoteSnapshot):
        raise FormalQuoteDocumentError("FormalQuoteDocument requires an ApprovedQuoteSnapshot.")
    if snapshot.status not in {QuoteDraftStatus.APPROVED, QuoteDraftStatus.SUPERSEDED}:
        raise FormalQuoteDocumentError(
            f"FormalQuoteDocument requires an approved snapshot. Current status is {snapshot.status.value}."
        )
    quote_number = _clean(official_quote_number) or snapshot.official_quote_number or snapshot.quote_number_candidate
    issuer = None
    if snapshot.issuer_snapshot is not None:
        issuer = FormalQuoteIssuer(
            company_name=snapshot.issuer_snapshot.company_name,
            address=snapshot.issuer_snapshot.address,
            office_address=snapshot.issuer_snapshot.office_address,
            telephone=snapshot.issuer_snapshot.telephone,
        )
    document = FormalQuoteDocument(
        snapshot_id=snapshot.approved_quote_snapshot_id,
        snapshot_version=snapshot.quote_version,
        quote_number=quote_number,
        customer_name=snapshot.customer,
        subject=snapshot.title,
        issue_date=snapshot.issue_date,
        valid_until=snapshot.valid_until,
        issuer=issuer,
        customer_lines=[
            FormalQuoteLine(
                item_name=line.display_name,
                customer_description=_customer_description(line.description),
                quantity=line.quantity,
                unit_price=line.unit_price_jpy,
                amount=line.amount_jpy,
            )
            for line in snapshot.customer_lines_snapshot
        ],
        subtotal=snapshot.subtotal_ex_tax_jpy,
        tax_rate=snapshot.tax_rate,
        tax_amount=snapshot.tax_jpy,
        total=snapshot.total_jpy,
        remarks=_remark_texts(snapshot),
        source_approved_snapshot_id=snapshot.approved_quote_snapshot_id,
    )
    _assert_totals_match_snapshot(document, snapshot)
    _assert_displayed_amounts_add_up(document)
    return document


def formal_quote_comparable(document: FormalQuoteDocument) -> dict:
    return {
        "quote_number": document.quote_number,
        "customer_name": document.customer_name,
        "subject": document.subject,
        "issue_date": document.issue_date,
        "valid_until": document.valid_until,
        "lines": [
            {
                "item_name": line.item_name,
                "customer_description": line.customer_description,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "amount": line.amount,
            }
            for line in document.customer_lines
        ],
        "subtotal": document.subtotal,
        "tax_amount": document.tax_amount,
        "total": document.total,
        "remarks": list(document.remarks),
    }


def format_document_amount(value: Optional[float]) -> str:
    if value is None:
        return ""
    return f"{int(round(value)):,}"


def format_document_date(value: Optional[str]) -> str:
    if not value:
        return ""
    return value.replace("-", "/")


def _assert_totals_match_snapshot(document: FormalQuoteDocument, snapshot: ApprovedQuoteSnapshot) -> None:
    if document.subtotal != snapshot.subtotal_ex_tax_jpy:
        raise FormalQuoteDocumentError("FormalQuoteDocument subtotal does not match ApprovedQuoteSnapshot.")
    if document.tax_amount != snapshot.tax_jpy:
        raise FormalQuoteDocumentError("FormalQuoteDocument tax does not match ApprovedQuoteSnapshot.")
    if document.total != snapshot.total_jpy:
        raise FormalQuoteDocumentError("FormalQuoteDocument total does not match ApprovedQuoteSnapshot.")
    if len(document.customer_lines) != len(snapshot.customer_lines_snapshot):
        raise FormalQuoteDocumentError("FormalQuoteDocument line count does not match Approved customer lines.")
    if document.remarks != _remark_texts(snapshot):
        raise FormalQuoteDocumentError("FormalQuoteDocument remarks must be the Approved Snapshot final remarks only.")


def _assert_displayed_amounts_add_up(document: FormalQuoteDocument) -> None:
    # The customer reads the printed yen values, so they must add up as printed. A snapshot whose
    # amounts only add up before display rounding (e.g. legacy fractional prices) is refused, not adjusted.
    def shown(value: Optional[float]) -> int:
        return int(format_document_amount(value).replace(",", "") or 0)

    lines = sum(shown(line.amount) for line in document.customer_lines)
    if lines != shown(document.subtotal):
        raise FormalQuoteDocumentError(
            f"Displayed line amounts ({lines:,}) do not add up to the displayed subtotal "
            f"({shown(document.subtotal):,}). Revise the quote prices before issuing the document."
        )
    if document.total is not None and shown(document.subtotal) + shown(document.tax_amount) != shown(document.total):
        raise FormalQuoteDocumentError(
            f"Displayed subtotal and tax ({shown(document.subtotal):,} + {shown(document.tax_amount):,}) do not add up "
            f"to the displayed total ({shown(document.total):,}). Revise the quote prices before issuing the document."
        )


def _remark_texts(snapshot: ApprovedQuoteSnapshot) -> list[str]:
    texts = []
    for item in snapshot.remarks or []:
        text = item.text if hasattr(item, "text") else str(item)
        if text and str(text).strip():
            texts.append(str(text).strip())
    return texts


def _customer_description(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None
