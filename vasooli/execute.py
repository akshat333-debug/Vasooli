"""Execute a recovery batch under one of two arms, and log every decision.

HOW THE TWO ARMS ARE MADE COMPARABLE

The comparison is the only claim this project actually makes, so the mechanism
deserves to be stated plainly rather than buried.

For each (subscription, attempt_index) pair we draw ONE uniform random number,
seeded from the subscription id and the attempt index. Both arms see the same
draw. What differs is the probability that draw is tested against, and that
probability is a function of WHEN the arm chose to retry.

    success  <=>  u[sub, attempt]  <  p(failure_class, attempt, when_arm_retried)

So the sequencer cannot win by getting luckier records. It can only win by
choosing better moments, and by declining to spend attempts that were never
going to land. That is the entire hypothesis, and this construction is what
makes it falsifiable — if the thesis is wrong, the sequencer loses on the same
draws.

THE LATE-REVOCATION HAZARD

A mandate can be revoked between the moment a retry is decided and the moment it
is attempted. This is simulated for a deterministic subset of records. The
sequencer re-checks mandate state at the action boundary and refuses; the
baseline does not and burns an attempt.

This mirrors RunFuse's reason for tripping at call boundaries rather than
mid-tool: a check performed at the wrong moment lets the world change underneath
the decision.

BASELINE IS NAIVE ABOUT STRATEGY, NOT ABOUT LAW

The baseline retries on a fixed T+1/T+3/T+5 schedule and ignores failure class
and mandate state — that is what it is for. It still respects the RBI pre-debit
notice floor and the same batch-level breaker, because comparing a compliant
system against a non-compliant one would prove nothing.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta

from pydantic import BaseModel

from .decide import Action, Decision, days_to_replenish, decide, earliest_legal_retry
from .diagnose import diagnose_batch
from .ledger import Ledger
from .models import AtRiskRecord, MandateStatus
from .policy import RecoveryFuse, RecoveryPolicy, RecoveryTripped
from .sim.model import success_probability
from .taxonomy import FailureClass

#: Fraction of scheduled retries whose mandate is revoked after the decision was
#: made but before the debit is attempted. Deterministic per subscription.
LATE_REVOCATION_RATE = 0.08

BASELINE_OFFSETS_DAYS = (1, 3, 5)


def _draw(subscription_id: str, attempt_index: int) -> float:
    """The shared uniform draw. Identical across arms by construction."""
    h = hashlib.sha256(f"{subscription_id}:{attempt_index}".encode()).hexdigest()
    return int(h[:16], 16) / float(1 << 64)


def _late_revocation(subscription_id: str) -> bool:
    h = hashlib.sha256(f"revoke:{subscription_id}".encode()).hexdigest()
    return (int(h[:16], 16) / float(1 << 64)) < LATE_REVOCATION_RATE


class RecordOutcome(BaseModel):
    subscription_id: str
    amount_paise: int
    failure_class: FailureClass
    recovered: bool
    attempts_spent: int
    attempts_preserved: int
    terminal_reason: str


class BatchResult(BaseModel):
    run_id: str
    arm: str
    records: int
    outcomes: list[RecordOutcome]
    actions_taken: int
    value_at_risk_paise: int
    value_recovered_paise: int
    attempts_spent: int
    wasted_attempts: int
    soft_warnings: list[str]
    tripped: str | None = None

    @property
    def recovery_rate(self) -> float:
        return (self.value_recovered_paise / self.value_at_risk_paise
                if self.value_at_risk_paise else 0.0)

    @property
    def paise_per_attempt(self) -> float:
        return (self.value_recovered_paise / self.attempts_spent
                if self.attempts_spent else 0.0)


def _attempt(
    rec: AtRiskRecord,
    fc: FailureClass,
    at: datetime,
    attempt_index: int,
) -> bool:
    """Simulate one debit. Shared draw, arm-dependent timing.

    Physical constraints are applied to BOTH arms before any probability is
    considered, because they are properties of the world and not of strategy:

      * A revoked, expired or paused mandate cannot be debited. Not "rarely" —
        the bank rejects it.
      * A debit above the amount registered on the mandate is rejected on
        presentation.

    This was a real bug. Without these two lines the baseline arm was credited
    with recovering money from dead mandates and over-cap debits, which inflated
    it against the sequencer. The bug flattered nothing about this project's own
    thesis, which is exactly why it was worth finding: the sequencer's job is to
    NOT attempt these, so letting them succeed in simulation destroyed the only
    advantage being measured.
    """
    if rec.mandate_status is not MandateStatus.ACTIVE:
        return False
    if rec.exceeds_mandate_cap:
        return False

    p = success_probability(
        fc,
        attempt_index,
        hours_since_failure=(at - rec.last_attempt_at).total_seconds() / 3600.0,
        days_to_replenish=days_to_replenish(at, rec.salary_day),
    )
    return _draw(rec.subscription_id, attempt_index) < p


def run_batch(
    records: list[AtRiskRecord],
    *,
    arm: str,
    now: datetime,
    ledger: Ledger,
    policy: RecoveryPolicy | None = None,
    use_llm: bool = False,
) -> BatchResult:
    """Run one arm over the batch, writing every decision to the ledger."""
    run_id = uuid.uuid4().hex[:12]
    fuse = RecoveryFuse(policy)
    diagnoses, _ = diagnose_batch(records, use_llm=use_llm)
    by_id = {d.subscription_id: d for d in diagnoses}

    outcomes: list[RecordOutcome] = []
    attempts_spent = wasted = 0
    tripped: str | None = None

    ledger.append(run_id=run_id, arm=arm, event="batch_start",
                  verdict=f"started — {len(records)} at-risk records, arm={arm}",
                  records=len(records))

    for rec in records:
        fc = by_id[rec.subscription_id].failure_class
        spent = 0
        recovered = False
        reason = ""

        if arm == "sequencer":
            decision = decide(rec, fc, now)
            ledger.append(run_id=run_id, arm=arm, event="decision",
                          verdict=decision.verdict, subscription_id=rec.subscription_id,
                          action=decision.action.value, failure_class=fc.value,
                          amount_paise=rec.amount_paise)
            if decision.action is not Action.RETRY_SCHEDULED:
                outcomes.append(RecordOutcome(
                    subscription_id=rec.subscription_id, amount_paise=rec.amount_paise,
                    failure_class=fc, recovered=False, attempts_spent=0,
                    attempts_preserved=rec.attempts_remaining,
                    terminal_reason=decision.verdict))
                continue
            schedule = _sequencer_schedule(rec, fc, now, decision)
        else:
            schedule = _baseline_schedule(rec, now)
            ledger.append(run_id=run_id, arm=arm, event="decision",
                          verdict=f"baseline: fixed T+1/T+3/T+5, {rec.attempts_remaining} "
                                  f"attempt(s) available, failure class not consulted",
                          subscription_id=rec.subscription_id,
                          failure_class=fc.value, amount_paise=rec.amount_paise)

        for i, at in enumerate(schedule):
            attempt_index = rec.attempts_used + i
            try:
                fuse.check(rec.amount_paise)
            except RecoveryTripped as t:
                tripped = t.verdict
                ledger.append(run_id=run_id, arm=arm, event="fuse_trip",
                              verdict=t.verdict, subscription_id=rec.subscription_id)
                break

            # Action boundary. State may have changed since the decision.
            if arm == "sequencer" and _late_revocation(rec.subscription_id):
                reason = ("stopped at execution: mandate revoked after the decision "
                          "was made — attempt preserved by the pre-flight re-check")
                ledger.append(run_id=run_id, arm=arm, event="preflight_refusal",
                              verdict=reason, subscription_id=rec.subscription_id)
                break

            ok = _attempt(rec, fc, at, attempt_index)
            if arm == "baseline" and _late_revocation(rec.subscription_id):
                # No re-check: the debit is attempted against a dead mandate.
                ok = False

            spent += 1
            attempts_spent += 1
            fuse.record(amount_paise=rec.amount_paise, recovered=ok)
            if not ok:
                wasted += 1

            ledger.append(run_id=run_id, arm=arm, event="attempt",
                          verdict=(f"attempt {attempt_index + 1} at {at:%Y-%m-%d %H:%M} "
                                   f"— {'recovered' if ok else 'failed'}"),
                          subscription_id=rec.subscription_id,
                          amount_paise=rec.amount_paise, recovered=ok)
            if ok:
                recovered = True
                reason = f"recovered on attempt {attempt_index + 1}"
                break

        if tripped:
            break
        if not reason:
            reason = "all available attempts spent without recovery"

        outcomes.append(RecordOutcome(
            subscription_id=rec.subscription_id, amount_paise=rec.amount_paise,
            failure_class=fc, recovered=recovered, attempts_spent=spent,
            attempts_preserved=rec.attempts_remaining - spent,
            terminal_reason=reason))

    result = BatchResult(
        run_id=run_id, arm=arm, records=len(records), outcomes=outcomes,
        actions_taken=fuse.state.actions_taken,
        value_at_risk_paise=sum(r.amount_paise for r in records),
        value_recovered_paise=fuse.state.value_recovered_paise,
        attempts_spent=attempts_spent, wasted_attempts=wasted,
        soft_warnings=fuse.state.soft_warnings, tripped=tripped)

    ledger.append(run_id=run_id, arm=arm, event="batch_end",
                  verdict=(f"finished — ₹{result.value_recovered_paise / 100:,.2f} recovered "
                           f"from {attempts_spent} attempt(s)"),
                  **result.model_dump(include={"value_recovered_paise", "attempts_spent",
                                               "wasted_attempts"}))
    return result


def _sequencer_schedule(
    rec: AtRiskRecord, fc: FailureClass, now: datetime, first: Decision
) -> list[datetime]:
    """Optimal first attempt, then re-scheduled follow-ups if it fails."""
    out = [first.scheduled_at or now]
    for k in range(1, rec.attempts_remaining):
        # A failed attempt means the cause persisted; wait a further cycle.
        out.append(out[-1] + timedelta(days=7 if fc is FailureClass.INSUFFICIENT_FUNDS else 1))
    return out


def _baseline_schedule(rec: AtRiskRecord, now: datetime) -> list[datetime]:
    """Fixed T+1/T+3/T+5, floored by the legal pre-debit notice window."""
    floor = earliest_legal_retry(rec, now)
    return [max(floor, now + timedelta(days=d))
            for d in BASELINE_OFFSETS_DAYS[: rec.attempts_remaining]]
