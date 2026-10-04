from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EmailDraft:
    recipients: list[str] = field(default_factory=list)
    customer_ids: list[str] = field(default_factory=list)
    subject: str = ""
    body: str = ""
    review_status: str = "NEEDS_HUMAN_REVIEW"
    channel: str = "gmail_future"


def prepare_email_draft(*, customer_ids=None, recipients=None, subject: str = "", body: str = "") -> EmailDraft:
    return EmailDraft(
        customer_ids=list(customer_ids or []),
        recipients=list(recipients or []),
        subject=subject,
        body=body,
        review_status="NEEDS_HUMAN_REVIEW",
    )
