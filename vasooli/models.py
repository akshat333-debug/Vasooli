"""Record schema. Razorpay-shaped, deliberately not Razorpay-identical.

Field names mirror the Subscriptions/Invoices API closely enough that the live
test-mode adapter is a rename, not a rewrite. Amounts are in paise throughout —
never floats, never rupees — because this is money.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from .taxonomy import FailureClass

#: RBI e-mandate framework 2026: standard cap on a recurring debit without
#: additional factor of authentication. Above this, a human approves.
RBI_STANDARD_CAP_PAISE = 15_000_00

#: Razorpay Subscriptions retries a failed charge a bounded number of times before
#: moving the subscription to `halted`. That makes attempts a scarce budget.
MAX_RETRY_BUDGET = 3

#: RBI e-mandate framework 2026: pre-debit notification must precede the debit.
PRE_DEBIT_NOTICE_HOURS = 24


class MandateStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"
    PAUSED = "paused"


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    HALTED = "halted"


class Method(StrEnum):
    UPI_AUTOPAY = "upi_autopay"
    CARD_EMANDATE = "card_emandate"


class AtRiskRecord(BaseModel):
    """One subscription whose recurring debit has failed and is at risk of halting."""

    subscription_id: str
    customer_id: str
    mandate_id: str
    invoice_id: str

    method: Method
    bank: str
    amount_paise: int = Field(gt=0)

    mandate_status: MandateStatus
    mandate_max_amount_paise: int = Field(gt=0)
    mandate_valid_until: datetime

    subscription_status: SubscriptionStatus
    attempts_used: int = Field(ge=0, le=MAX_RETRY_BUDGET)

    #: Structured error pair from the gateway.
    error_code: str
    error_reason: str
    #: Free-text, bank-specific, inconsistent. This is the LLM's input.
    error_description: str

    last_attempt_at: datetime
    pre_debit_notified_at: datetime | None = None

    #: Day of month the customer's balance typically replenishes. Drives retry
    #: timing for INSUFFICIENT_FUNDS. Synthetic; a real system would learn this.
    salary_day: int = Field(ge=1, le=28)

    @property
    def attempts_remaining(self) -> int:
        return max(0, MAX_RETRY_BUDGET - self.attempts_used)

    @property
    def exceeds_mandate_cap(self) -> bool:
        """A debit above the mandate's own ceiling can never succeed."""
        return self.amount_paise > self.mandate_max_amount_paise

    @property
    def needs_human_approval(self) -> bool:
        """Above the RBI standard cap, automation does not act alone."""
        return self.amount_paise > RBI_STANDARD_CAP_PAISE


class Diagnosis(BaseModel):
    subscription_id: str
    failure_class: FailureClass
    #: "llm" or "code_map" — recorded so the report can show LLM/fallback agreement.
    source: str
    rationale: str
