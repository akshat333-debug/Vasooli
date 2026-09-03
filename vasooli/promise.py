"""Promises to pay, and what a broken one is worth knowing.

Until now the engine reasoned only about what a bank said. A customer who
replies to a nudge with "salary 5th ko aa raha hai, tab try karo" is telling it
something no error code carries: when the money will actually be there.

WHAT A PROMISE IS ALLOWED TO DO

Move a retry later, and only later. A promise can push a scheduled attempt back
to the promised date; it can never pull one forward, never add an attempt, never
raise a cap, and never overturn a stopping rule. A customer saying "try again
tomorrow" on a revoked mandate does not make the mandate live.

That asymmetry is deliberate. A promise is unverified customer input arriving
over an untrusted channel, and the only safe direction for unverified input to
push a money action is *away*.

WHAT A BROKEN PROMISE IS WORTH

More than a kept one. A customer who has broken two promises is telling you the
next one is worth less, and a system that keeps rescheduling on their word burns
its whole budget waiting. So promises decay: after `MAX_HONOURED_MISSES` broken
promises the customer's word stops moving the schedule, and the record goes to a
person. Trust here is a resource with a floor, exactly like the retry budget.

NOTHING HERE IS PARSED FROM FREE TEXT YET

Promises arrive as structured records. Extracting a date from a Hinglish reply
is a genuine language problem and a natural place for the model, but it is not
built, so this module does not claim it. See NEXT_STEPS.md.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, Field

from .decide import Action, Decision, earliest_legal_retry
from .models import AtRiskRecord

#: How many broken promises before a customer's word stops moving the schedule.
MAX_HONOURED_MISSES = 2

#: A promise further out than this is not a plan, it is a deferral. The retry
#: budget cannot be held open indefinitely on an unverified say-so.
MAX_PROMISE_HORIZON_DAYS = 30


class PromiseState(StrEnum):
    OPEN = "open"
    KEPT = "kept"
    BROKEN = "broken"


class Promise(BaseModel):
    """A customer's stated intention to pay by a date."""

    subscription_id: str
    promised_for: datetime
    made_at: datetime
    state: PromiseState = PromiseState.OPEN
    #: How many promises this customer has already broken.
    prior_misses: int = Field(default=0, ge=0)
    #: Free-text the customer sent, kept for the audit trail. Never parsed.
    quote: str = ""


class PromiseVerdict(BaseModel):
    subscription_id: str
    honoured: bool
    scheduled_at: datetime | None
    verdict: str


def apply_promise(
    rec: AtRiskRecord,
    decision: Decision,
    promise: Promise | None,
    now: datetime,
) -> PromiseVerdict:
    """Fold a promise into an existing decision. Never overturns a stopping rule.

    Returns the decision's schedule unchanged unless the promise legitimately
    moves it later.
    """
    def v(honoured: bool, at: datetime | None, why: str) -> PromiseVerdict:
        return PromiseVerdict(subscription_id=rec.subscription_id,
                              honoured=honoured, scheduled_at=at, verdict=why)

    if promise is None:
        return v(False, decision.scheduled_at, "no promise on file")

    # A promise cannot resurrect a record the rules already refused. This is the
    # single most important line in the module: customer input is not an
    # override for a compliance or mandate decision.
    if decision.action is not Action.RETRY_SCHEDULED:
        return v(
            False, None,
            f"promise noted but not acted on — the record was already "
            f"{decision.action.value}, and a customer's word does not reopen it",
        )

    if promise.prior_misses >= MAX_HONOURED_MISSES:
        return v(
            False, decision.scheduled_at,
            f"promise ignored — {promise.prior_misses} previous promises broken; "
            f"the schedule no longer moves on this customer's word, sent for review",
        )

    if promise.promised_for > rec.mandate_valid_until:
        return v(
            False, decision.scheduled_at,
            f"promise ignored — {promise.promised_for:%Y-%m-%d} falls after the "
            f"mandate expires on {rec.mandate_valid_until:%Y-%m-%d}",
        )

    if promise.promised_for > now + timedelta(days=MAX_PROMISE_HORIZON_DAYS):
        return v(
            False, decision.scheduled_at,
            f"promise ignored — {promise.promised_for:%Y-%m-%d} is beyond the "
            f"{MAX_PROMISE_HORIZON_DAYS}-day horizon; the budget cannot be held "
            f"open that long on an unverified date",
        )

    floor = earliest_legal_retry(rec, now)
    target = max(promise.promised_for, floor)

    current = decision.scheduled_at
    if current is not None and target <= current:
        return v(
            False, current,
            f"promise noted — {promise.promised_for:%Y-%m-%d} is not later than "
            f"the scheduled attempt; a promise may only move a retry back, never "
            f"pull it forward",
        )

    return v(
        True, target,
        f"retry moved to {target:%Y-%m-%d} on the customer's promise "
        f"({promise.prior_misses} previous miss(es))",
    )


def settle(promise: Promise, recovered: bool) -> Promise:
    """Close a promise once the outcome is known, so the next one is priced."""
    return promise.model_copy(update={
        "state": PromiseState.KEPT if recovered else PromiseState.BROKEN,
        "prior_misses": promise.prior_misses + (0 if recovered else 1),
    })
