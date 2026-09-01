"""Seeded synthetic batch generator.

Produces Razorpay-shaped at-risk records. Fully deterministic for a given seed so
that the baseline arm and the sequencer arm face byte-identical inputs.

The failure mix is skewed heavily toward INSUFFICIENT_FUNDS, consistent with
publicly reported decline-reason distributions for Indian recurring debits. It is
a plausible mix, not a measured one — see sim/model.py.

Three hazards are deliberately seeded in, because a batch where everything is
clean proves nothing:

  1. Free-text error descriptions that vary by bank and do not restate the code.
     The LLM classifier has to actually read them.
  2. Error codes absent from CODE_MAP, which must land in UNKNOWN and route to a
     human rather than being guessed at.
  3. Records whose mandate is already dead while the error text still says
     something recoverable. Any system that trusts the diagnosis without
     re-checking mandate state at execution time will burn a retry on these.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from ..models import (
    RBI_STANDARD_CAP_PAISE,
    AtRiskRecord,
    MandateStatus,
    Method,
    SubscriptionStatus,
)

#: Fixed reference "now" so batches are reproducible across machines and days.
BATCH_NOW = datetime(2026, 9, 2, 9, 0, 0)

BANKS = ["HDFC", "SBI", "ICICI", "AXIS", "KOTAK", "PNB", "BOB", "YES"]

#: (error_code, error_reason, weight). Weights approximate a plausible mix.
FAILURE_MIX: list[tuple[str, str, int]] = [
    ("BAD_REQUEST_ERROR", "insufficient_funds", 38),
    ("GATEWAY_ERROR", "payment_failed_insufficient_balance", 14),
    ("GATEWAY_ERROR", "bank_unavailable", 8),
    ("GATEWAY_ERROR", "issuer_down", 3),
    ("GATEWAY_ERROR", "upi_psp_unavailable", 3),
    ("SERVER_ERROR", "gateway_technical_error", 7),
    ("GATEWAY_ERROR", "payment_timed_out", 5),
    ("BAD_REQUEST_ERROR", "mandate_revoked", 8),
    ("BAD_REQUEST_ERROR", "mandate_cancelled", 3),
    ("BAD_REQUEST_ERROR", "mandate_expired", 5),
    ("BAD_REQUEST_ERROR", "mandate_paused", 3),
    ("BAD_REQUEST_ERROR", "amount_exceeds_mandate_limit", 3),
    # Hazard 2: not in CODE_MAP. Must resolve to UNKNOWN, not a guess.
    ("GATEWAY_ERROR", "npci_response_code_u69", 2),
    ("BAD_REQUEST_ERROR", "collect_request_declined_by_payer", 2),
]

#: Hazard 1: free text that a human would read, not a restatement of the code.
DESCRIPTIONS: dict[str, list[str]] = {
    "insufficient_funds": [
        "Your account does not have enough balance to complete this transaction.",
        "Txn declined by {bank} - available balance lower than debit amount",
        "AUTOPAY DEBIT FAILED. Insufficient balance in a/c XXXX{last4}.",
        "balance low, please add funds and we will try again",
    ],
    "payment_failed_insufficient_balance": [
        "Payment failed. The customer's bank reported a low balance.",
        "{bank} returned: funds unavailable at time of debit",
    ],
    "bank_unavailable": [
        "{bank} is currently not responding. Please retry after some time.",
        "Issuing bank down for maintenance, debit could not be attempted",
    ],
    "issuer_down": ["Issuer {bank} unreachable during debit window."],
    "upi_psp_unavailable": [
        "UPI handle's PSP did not respond within the mandate execution window.",
    ],
    "gateway_technical_error": [
        "An internal error occurred while processing the mandate debit.",
        "Unexpected error at gateway. No money was moved.",
    ],
    "payment_timed_out": [
        "The debit request timed out before {bank} confirmed.",
        "no response received, txn marked failed after timeout",
    ],
    "mandate_revoked": [
        "The customer has cancelled this AutoPay mandate from their UPI app.",
        "Mandate revoked at payer end. No further debits are permitted.",
        "e-mandate withdrawn by customer via net banking on {bank}",
    ],
    "mandate_cancelled": [
        "This mandate was cancelled and is no longer active.",
    ],
    "mandate_expired": [
        "Mandate validity period has ended. A fresh mandate is required.",
        "e-mandate past its valid-until date, debit rejected by {bank}",
    ],
    "mandate_paused": [
        "The customer has temporarily paused this mandate.",
    ],
    "amount_exceeds_mandate_limit": [
        "Debit amount is higher than the maximum approved on this mandate.",
        "{bank} rejected: value exceeds per-txn cap registered on the mandate",
    ],
    "npci_response_code_u69": [
        "NPCI returned U69. Refer to the NPCI response code master.",
    ],
    "collect_request_declined_by_payer": [
        "Payer actively declined the collect request in their app.",
    ],
}

#: Reasons that imply the mandate itself is dead.
_DEAD_MANDATE_REASONS = {
    "mandate_revoked": MandateStatus.REVOKED,
    "mandate_cancelled": MandateStatus.REVOKED,
    "mandate_expired": MandateStatus.EXPIRED,
    "mandate_paused": MandateStatus.PAUSED,
}


def generate_batch(n: int = 100, seed: int = 42) -> list[AtRiskRecord]:
    """Generate a deterministic batch of at-risk records."""
    rng = random.Random(seed)
    weights = [w for _, _, w in FAILURE_MIX]
    records: list[AtRiskRecord] = []

    for i in range(n):
        code, reason, _ = rng.choices(FAILURE_MIX, weights=weights, k=1)[0]
        bank = rng.choice(BANKS)

        template = rng.choice(DESCRIPTIONS[reason])
        description = template.format(bank=bank, last4=f"{rng.randint(1000, 9999)}")

        # Most subscriptions are modest; a long tail crosses the RBI cap and must
        # go to a human regardless of how recoverable the failure looks.
        if rng.random() < 0.08:
            amount = rng.randint(RBI_STANDARD_CAP_PAISE + 1, 45_000_00)
        else:
            amount = rng.choice([199, 299, 499, 799, 1299, 2499, 4999]) * 100

        mandate_max = int(amount * rng.choice([1.0, 1.2, 1.5, 2.0]))
        # Hazard: mandate cap set below the current debit (plan price rose).
        if rng.random() < 0.06:
            mandate_max = int(amount * 0.7)

        mandate_status = _DEAD_MANDATE_REASONS.get(reason, MandateStatus.ACTIVE)
        # Hazard 3: mandate died but the failure text still reads as recoverable.
        if mandate_status is MandateStatus.ACTIVE and rng.random() < 0.07:
            mandate_status = MandateStatus.REVOKED

        valid_until = BATCH_NOW + timedelta(days=rng.randint(30, 400))
        if mandate_status is MandateStatus.EXPIRED:
            valid_until = BATCH_NOW - timedelta(days=rng.randint(1, 60))

        last_attempt = BATCH_NOW - timedelta(hours=rng.randint(2, 72))
        notified = (
            last_attempt - timedelta(hours=rng.randint(24, 96))
            if rng.random() < 0.85
            else None
        )

        records.append(
            AtRiskRecord(
                subscription_id=f"sub_SYN{i:04d}",
                customer_id=f"cust_SYN{rng.randint(1000, 9999)}",
                mandate_id=f"tkn_SYN{i:04d}",
                invoice_id=f"inv_SYN{i:04d}",
                method=rng.choices(
                    [Method.UPI_AUTOPAY, Method.CARD_EMANDATE], weights=[7, 3]
                )[0],
                bank=bank,
                amount_paise=amount,
                mandate_status=mandate_status,
                mandate_max_amount_paise=mandate_max,
                mandate_valid_until=valid_until,
                subscription_status=SubscriptionStatus.ACTIVE,
                # Includes already-exhausted subscriptions: the batch must
                # contain records the sequencer is obliged to refuse.
                attempts_used=rng.choices([0, 1, 2, 3], weights=[5, 3, 2, 1])[0],
                error_code=code,
                error_reason=reason,
                error_description=description,
                last_attempt_at=last_attempt,
                pre_debit_notified_at=notified,
                salary_day=rng.choice([1, 1, 2, 5, 7, 10, 15, 25, 28]),
            )
        )

    return records
