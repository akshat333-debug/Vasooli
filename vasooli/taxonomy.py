"""Canonical failure taxonomy for recurring-debit failures.

A gateway hands back a short code plus a free-text description that varies by bank,
by PSP and by month. Everything downstream — the stopping rules, the retry scorer,
the report — keys off the canonical class, never off the raw string.

The critical design rule: there is an explicit UNKNOWN class and it routes to human
review. A classifier that always produces a confident answer would silently spend
retries on failures nobody understood.
"""

from __future__ import annotations

from enum import StrEnum


class FailureClass(StrEnum):
    # Recoverable: the mandate is alive, the debit could succeed on a later attempt.
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    BANK_DOWNTIME = "BANK_DOWNTIME"
    TECHNICAL_ERROR = "TECHNICAL_ERROR"

    # Terminal for automation: no retry can ever succeed. Spending one is pure waste.
    MANDATE_REVOKED = "MANDATE_REVOKED"
    MANDATE_EXPIRED = "MANDATE_EXPIRED"
    MANDATE_PAUSED = "MANDATE_PAUSED"

    # Terminal until a human or the customer changes something.
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"

    # Explicitly not classified. Never auto-actioned.
    UNKNOWN = "UNKNOWN"


#: Classes where a retry has a non-zero chance of succeeding.
RECOVERABLE: frozenset[FailureClass] = frozenset(
    {
        FailureClass.INSUFFICIENT_FUNDS,
        FailureClass.BANK_DOWNTIME,
        FailureClass.TECHNICAL_ERROR,
    }
)

#: Classes where a retry is guaranteed to fail. Spending an attempt here is the
#: single most expensive mistake the system can make, because the retry budget is
#: capped at 3 and exhausting it halts the subscription.
TERMINAL: frozenset[FailureClass] = frozenset(
    {
        FailureClass.MANDATE_REVOKED,
        FailureClass.MANDATE_EXPIRED,
        FailureClass.MANDATE_PAUSED,
        FailureClass.LIMIT_EXCEEDED,
    }
)

#: Not classified with enough confidence to act on.
NEEDS_HUMAN: frozenset[FailureClass] = frozenset({FailureClass.UNKNOWN})


def is_recoverable(fc: FailureClass) -> bool:
    return fc in RECOVERABLE


def is_terminal(fc: FailureClass) -> bool:
    return fc in TERMINAL


#: Deterministic fallback mapping from Razorpay-shaped error codes.
#: Used when the LLM is unavailable, and as the ground truth the LLM classifier is
#: scored against. Codes absent here fall through to UNKNOWN rather than a guess.
CODE_MAP: dict[str, FailureClass] = {
    "BAD_REQUEST_ERROR:insufficient_funds": FailureClass.INSUFFICIENT_FUNDS,
    "GATEWAY_ERROR:payment_failed_insufficient_balance": FailureClass.INSUFFICIENT_FUNDS,
    "BAD_REQUEST_ERROR:mandate_revoked": FailureClass.MANDATE_REVOKED,
    "BAD_REQUEST_ERROR:mandate_cancelled": FailureClass.MANDATE_REVOKED,
    "BAD_REQUEST_ERROR:mandate_expired": FailureClass.MANDATE_EXPIRED,
    "BAD_REQUEST_ERROR:mandate_paused": FailureClass.MANDATE_PAUSED,
    "BAD_REQUEST_ERROR:amount_exceeds_mandate_limit": FailureClass.LIMIT_EXCEEDED,
    "BAD_REQUEST_ERROR:payment_limit_exceeded": FailureClass.LIMIT_EXCEEDED,
    "GATEWAY_ERROR:bank_unavailable": FailureClass.BANK_DOWNTIME,
    "GATEWAY_ERROR:issuer_down": FailureClass.BANK_DOWNTIME,
    "GATEWAY_ERROR:upi_psp_unavailable": FailureClass.BANK_DOWNTIME,
    "SERVER_ERROR:gateway_technical_error": FailureClass.TECHNICAL_ERROR,
    "GATEWAY_ERROR:payment_timed_out": FailureClass.TECHNICAL_ERROR,
}


def classify_by_code(error_code: str, error_reason: str) -> FailureClass:
    """Deterministic classification from the structured error pair.

    Returns UNKNOWN for anything unmapped. Deliberately does no fuzzy matching —
    that is the LLM's job, and its output is checked against this.
    """
    return CODE_MAP.get(f"{error_code}:{error_reason}", FailureClass.UNKNOWN)
