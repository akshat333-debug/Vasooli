"""Razorpay webhook ingestion — the same engine, invoked by an event.

Vasooli reasons over a batch handed to it. A real deployment is told about
failures as they happen: `payment.failed`, `subscription.halted`,
`subscription.charged`. This module is that door.

THE ENGINE DOES NOT CHANGE

An event becomes an AtRiskRecord and goes through the identical taxonomy,
stopping rules, breaker and ledger. There is no webhook-specific decision path,
because a second path for the same decision is a second place for it to drift.

WHAT THIS DOOR IS FOR

Verifying, recording and refusing. It does three things and hands off:

  1. Verify the signature before parsing anything. An unverified payload is not
     data, it is an attacker's suggestion, and it must not reach a parser that
     might do something interesting with it.
  2. Reject replays. Razorpay retries deliveries, and a retried
     `payment.failed` must not be counted as a second failure — that would spend
     a retry from a budget of three on an event that happened once.
  3. Answer immediately. Verification and persistence are fast; deciding is not
     necessarily. The endpoint acknowledges and the work happens after, so a
     slow decision can never cause Razorpay to retry a delivery that already
     succeeded.

The pattern is lifted from AutoWatch: verify, persist, acknowledge, then work.

WHAT IT DELIBERATELY DOES NOT DO

It does not act on the event's contents. A webhook body is attacker-controlled
until the signature proves otherwise, and even then it is a merchant's data
rather than an instruction: nothing in the payload can raise a cap, skip a
stopping rule, or schedule a debit. The event supplies facts; decide.py decides.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .ledger import Ledger
from .models import (
    AtRiskRecord,
    MandateStatus,
    Method,
    SubscriptionStatus,
)

#: Events that mean money is at risk. Anything else is acknowledged and ignored —
#: an endpoint that tries to handle every event type it might one day receive is
#: an endpoint with untested branches in it.
HANDLED = frozenset({
    "payment.failed",
    "subscription.halted",
    "subscription.pending",
})


class SignatureInvalid(Exception):
    """The payload did not come from Razorpay, or was altered in transit."""


class EventIgnored(Exception):
    """Well-formed and authentic, but not an event this system acts on."""


def verify_signature(body: bytes, signature: str, secret: str | None = None) -> None:
    """Razorpay signs the raw body with HMAC-SHA256 over the webhook secret.

    Compared with `compare_digest`, not `==`. A naive comparison returns faster
    on an earlier mismatch, which leaks the signature one byte at a time to
    anyone patient enough to measure it.
    """
    key = secret or os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
    if not key:
        raise SignatureInvalid(
            "RAZORPAY_WEBHOOK_SECRET is not set — refusing to accept an "
            "unverifiable payload rather than trusting it"
        )
    expected = hmac.new(key.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature or ""):
        raise SignatureInvalid("signature does not match the payload")


@dataclass(frozen=True)
class Ingested:
    event_id: str
    event_type: str
    record: AtRiskRecord | None
    duplicate: bool
    note: str


def _utc_naive(epoch: int | float) -> datetime:
    """Razorpay sends UTC Unix timestamps.

    `fromtimestamp()` without a timezone reads them in LOCAL time, which would
    shift a mandate's expiry by the host's offset — an engine reasoning about
    dates would then schedule against the wrong day. Read as UTC explicitly,
    then drop the tzinfo so the value stays comparable with the rest of the
    engine, which is naive throughout by design.
    """
    return datetime.fromtimestamp(epoch, tz=UTC).replace(tzinfo=None)


def _payload_entity(payload: dict[str, Any], name: str) -> dict[str, Any]:
    return (payload.get("payload", {}).get(name, {}) or {}).get("entity", {}) or {}


def to_record(event: dict[str, Any], now: datetime) -> AtRiskRecord:
    """Map a Razorpay event onto the engine's own record type.

    Everything absent from the event gets a conservative default rather than an
    optimistic one. An unknown mandate cap becomes the amount itself, so a debit
    the engine cannot prove is under the cap is treated as over it — the safe
    direction for missing information to push a money decision.
    """
    payment = _payload_entity(event, "payment")
    sub = _payload_entity(event, "subscription")

    amount = int(payment.get("amount") or sub.get("amount") or 0)
    err_code = str(payment.get("error_code") or "GATEWAY_ERROR")
    err_reason = str(payment.get("error_reason") or payment.get("error_step") or "unknown")
    err_desc = str(payment.get("error_description") or "")

    sub_id = str(sub.get("id") or payment.get("subscription_id") or event.get("id"))
    mandate_id = str(sub.get("token_id") or payment.get("token_id") or f"tkn_{sub_id}")

    status = str(sub.get("status") or "active")
    mandate_status = {
        "cancelled": MandateStatus.REVOKED,
        "expired": MandateStatus.EXPIRED,
        "paused": MandateStatus.PAUSED,
    }.get(status, MandateStatus.ACTIVE)

    paid = int(sub.get("paid_count") or 0)
    attempts_used = min(int(sub.get("remaining_count") is not None and paid or 0), 3)

    return AtRiskRecord(
        subscription_id=sub_id,
        customer_id=str(sub.get("customer_id") or payment.get("customer_id") or "cust_unknown"),
        mandate_id=mandate_id,
        invoice_id=str(payment.get("invoice_id") or f"inv_{sub_id}"),
        method=Method.UPI_AUTOPAY if str(payment.get("method")) == "upi" else Method.CARD_EMANDATE,
        bank=str(payment.get("bank") or payment.get("wallet") or "UNKNOWN"),
        amount_paise=max(amount, 1),
        mandate_status=mandate_status,
        # Unknown cap -> assume the debit is AT the cap, so anything larger is
        # refused. Missing information must never widen the envelope.
        mandate_max_amount_paise=int(sub.get("max_amount") or max(amount, 1)),
        mandate_valid_until=(
            _utc_naive(sub["end_at"]) if sub.get("end_at")
            else now + timedelta(days=365)
        ),
        subscription_status=(
            SubscriptionStatus.HALTED if status == "halted" else SubscriptionStatus.ACTIVE
        ),
        attempts_used=attempts_used,
        error_code=err_code,
        error_reason=err_reason,
        error_description=err_desc,
        last_attempt_at=(
            _utc_naive(event["created_at"]) if event.get("created_at") else now
        ),
        # No notice can be assumed from an event. Absent proof that one was
        # sent, the engine must schedule as though it has not been.
        pre_debit_notified_at=None,
        salary_day=1,
    )


def ingest(
    body: bytes,
    signature: str,
    ledger: Ledger,
    *,
    run_id: str,
    now: datetime | None = None,
    secret: str | None = None,
) -> Ingested:
    """Verify, deduplicate, record, and return. Decides nothing.

    Raises SignatureInvalid before parsing. Everything downstream may then
    assume the bytes came from Razorpay.
    """
    verify_signature(body, signature, secret)

    now = now or datetime.now(tz=UTC).replace(tzinfo=None)
    try:
        event = json.loads(body)
    except json.JSONDecodeError as e:
        raise EventIgnored(f"authentic but unparseable: {e}") from e

    event_type = str(event.get("event") or "")
    event_id = str(event.get("id") or hashlib.sha256(body).hexdigest()[:16])

    # Razorpay retries deliveries. A replayed payment.failed counted twice would
    # spend a retry from a budget of three on one real failure.
    already = [r for r in ledger.rows() if r["event"] == "webhook_received"
               and r["subscription_id"] == event_id]
    if already:
        ledger.append(run_id=run_id, arm="webhook", event="webhook_duplicate",
                      verdict=f"replay of {event_id} ignored — already ingested",
                      subscription_id=event_id)
        return Ingested(event_id, event_type, None, True, "duplicate delivery")

    if event_type not in HANDLED:
        ledger.append(run_id=run_id, arm="webhook", event="webhook_ignored",
                      verdict=f"{event_type} is not an event this system acts on",
                      subscription_id=event_id)
        return Ingested(event_id, event_type, None, False, "event type not handled")

    record = to_record(event, now)
    ledger.append(
        run_id=run_id, arm="webhook", event="webhook_received",
        verdict=(f"{event_type} accepted for {record.subscription_id}, "
                 f"Rs {record.amount_paise / 100:,.2f} — queued, not yet decided"),
        subscription_id=event_id,
        subscription=record.subscription_id, amount_paise=record.amount_paise,
    )
    return Ingested(event_id, event_type, record, False, "accepted")
