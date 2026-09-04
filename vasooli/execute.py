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
is attempted. This is a fact about the WORLD, and both arms live in the same one:
`mandate_status_at()` decides it from the record alone and `_attempt()` consults
it for either arm, so a debit presented against a revoked mandate fails whoever
presented it.

What differs is behaviour, not physics. The sequencer makes an explicit
pre-flight status call at the action boundary and declines without spending an
attempt; the baseline does not ask, spends the attempt, and learns the same fact
from the rejection. An earlier version branched on the arm's NAME (defect 19),
which made a property of the world look like a rule that happened to favour one
arm — the exact criticism the comparison must not be open to.

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

from .decide import (
    Action,
    Decision,
    Escalation,
    days_to_replenish,
    decide,
    earliest_legal_retry,
)
from .diagnose import diagnose_batch
from .ledger import Ledger
from .logging import event
from .models import AtRiskRecord, Diagnosis, MandateStatus
from .policy import ActionRefused, RecoveryFuse, RecoveryPolicy, RecoveryTripped
from .sim.model import success_probability
from .taxonomy import FailureClass

#: Fraction of scheduled retries whose mandate is revoked after the decision was
#: made but before the debit is attempted. Deterministic per subscription.
LATE_REVOCATION_RATE = 0.08

BASELINE_OFFSETS_DAYS = (1, 3, 5)


def _draw(subscription_id: str, attempt_index: int, salt: str = "") -> float:
    """The shared uniform draw. Identical across arms by construction.

    `salt` exists because generate_batch reuses the same subscription ids for
    every seed (sub_SYN0000 ...). Without a salt, every seed in a sweep drew the
    SAME 300 luck values — the seed varied which failure sat in each slot but not
    whether that slot got lucky. Within one comparison that was harmless, since
    both arms still shared the draw, but it meant a 200-seed sweep was far less
    independent than the number suggested.

    Callers pass the batch seed. Both arms of a comparison always receive the
    same salt, so the fairness property is untouched.
    """
    h = hashlib.sha256(f"{salt}:{subscription_id}:{attempt_index}".encode()).hexdigest()
    return int(h[:16], 16) / float(1 << 64)


def _late_revocation(subscription_id: str, salt: str = "") -> bool:
    h = hashlib.sha256(f"revoke:{salt}:{subscription_id}".encode()).hexdigest()
    return (int(h[:16], 16) / float(1 << 64)) < LATE_REVOCATION_RATE


def mandate_status_at(rec: AtRiskRecord, salt: str = "") -> MandateStatus:
    """The mandate's state at execution time. The world, not the arm.

    Takes no `arm` argument, deliberately: nothing observable to one arm may be
    unobservable to the other. See the module docstring.
    """
    if _late_revocation(rec.subscription_id, salt):
        return MandateStatus.REVOKED
    return rec.mandate_status


class RecordOutcome(BaseModel):
    subscription_id: str
    amount_paise: int
    failure_class: FailureClass
    recovered: bool
    attempts_spent: int
    attempts_preserved: int
    terminal_reason: str
    #: Which numbered stopping rule ended this record, and where it routes next.
    #: Grouping the exception list on these instead of on a prefix of the verdict
    #: string is what stopped every above-cap record forming its own group
    #: (defect 22) — the rupee amount is interpolated before the separator.
    rule_fired: int = 0
    escalation: Escalation = Escalation.NONE


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
    breaker_refusals: int = 0
    tripped: str | None = None

    @property
    def records_processed(self) -> int:
        return len(self.outcomes)

    @property
    def truncated(self) -> bool:
        """True when the breaker stopped the run before every record was seen.

        A truncated run is not a result. Its totals are computed over a prefix of
        the batch while `value_at_risk_paise` still counts everything, so any
        rate derived from it understates recovery against a denominator that was
        never attempted. The report must say so rather than print a comparison
        that looks complete.
        """
        return self.records_processed < self.records

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
    salt: str = "",
) -> bool:
    """Simulate one debit. Shared draw, arm-dependent timing.

    Physical constraints are applied to BOTH arms before any probability is
    considered, because they are properties of the world and not of strategy:

      * A revoked, expired or paused mandate cannot be debited. Not "rarely" —
        the bank rejects it.
      * A debit above the amount registered on the mandate is rejected on
        presentation.

      * A debit above the RBI AFA-free cap requires additional factor
        authentication. Presented unattended, the issuer declines it.

    This was a real bug, twice. Without the mandate and mandate-cap lines the
    baseline was credited with recovering money from dead mandates and over-cap
    debits. Without the AFA line it was credited with ₹73,653.24 the network
    would never have released (defect 19) — and the "compliance-adjusted"
    headline existed to subtract, in the report, money the simulator should
    never have paid out in the first place. The sequencer's whole job is to not
    attempt these, so letting them succeed in simulation destroyed the only
    advantage being measured.
    """
    if mandate_status_at(rec, salt) is not MandateStatus.ACTIVE:
        return False
    if rec.exceeds_mandate_cap:
        return False
    if rec.needs_human_approval:
        return False
    if at > rec.mandate_valid_until:
        # Presented after the mandate's validity date. Rejected on presentation,
        # whichever arm scheduled it. Added after an audit found the sequencer
        # scheduling past expiry and the simulator happily paying out on it.
        return False

    p = success_probability(
        fc,
        attempt_index,
        hours_since_failure=(at - rec.last_attempt_at).total_seconds() / 3600.0,
        days_to_replenish=(days_to_replenish(at, rec.salary_day)
                           if rec.salary_day is not None else 0),
    )
    return _draw(rec.subscription_id, attempt_index, salt) < p


def run_batch(
    records: list[AtRiskRecord],
    *,
    arm: str,
    now: datetime,
    ledger: Ledger,
    policy: RecoveryPolicy | None = None,
    use_llm: bool = False,
    diagnoses: list[Diagnosis] | None = None,
    disabled_rules: frozenset[int] = frozenset(),
    timing: str = "optimal",
    draw_salt: str = "",
) -> BatchResult:
    """Run one arm over the batch, writing every decision to the ledger.

    `diagnoses` should be supplied by the caller so that both arms reason over
    the IDENTICAL classification — including anything the LLM resolved on the
    tail. Re-diagnosing per arm was a real bug: the CLI classified with the
    model, reported statistics about it, and then each arm silently re-ran the
    dictionary alone, so a record the model had rescued was still treated as
    UNKNOWN when the money decision was actually made. The report described work
    that never reached the decision.

    When omitted, diagnosis is computed here (dictionary-only by default), which
    keeps the function usable standalone in tests.
    """
    run_id = uuid.uuid4().hex[:12]
    fuse = RecoveryFuse(policy)
    if diagnoses is None:
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
        escalation = Escalation.NONE
        rule = 0

        if arm == "sequencer":
            decision = decide(rec, fc, now, disabled_rules=disabled_rules)
            ledger.append(run_id=run_id, arm=arm, event="decision",
                          verdict=decision.verdict, subscription_id=rec.subscription_id,
                          action=decision.action.value, failure_class=fc.value,
                          amount_paise=rec.amount_paise)
            if decision.action is not Action.RETRY_SCHEDULED:
                outcomes.append(RecordOutcome(
                    subscription_id=rec.subscription_id, amount_paise=rec.amount_paise,
                    failure_class=fc, recovered=False, attempts_spent=0,
                    attempts_preserved=rec.attempts_remaining,
                    terminal_reason=decision.verdict,
                    rule_fired=decision.rule_fired,
                    escalation=decision.escalation))
                continue
            schedule = (
                _sequencer_schedule(rec, fc, now, decision)
                if timing == "optimal"
                # Attribution variant: keep the sequencer's refusals but
                # borrow the baseline's naive schedule, so the value of
                # WHEN can be separated from the value of WHETHER.
                else _baseline_schedule(rec, now)
            )
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
                fuse.check(rec.amount_paise, attempts_on_subscription=attempt_index)
            except ActionRefused as r:
                # One debit refused at the money boundary. The batch continues:
                # a per-debit limit that tripped the run would truncate the
                # comparison it exists to protect.
                reason = r.verdict
                escalation = Escalation.AFA_PAYMENT_LINK
                rule = 6
                ledger.append(run_id=run_id, arm=arm, event="breaker_refusal",
                              verdict=r.verdict, subscription_id=rec.subscription_id,
                              amount_paise=rec.amount_paise)
                break
            except RecoveryTripped as t:
                tripped = t.verdict
                ledger.append(run_id=run_id, arm=arm, event="fuse_trip",
                              verdict=t.verdict, subscription_id=rec.subscription_id)
                break

            # Action boundary. The world may have moved since the decision, so
            # the sequencer pays for a status call rather than paying with an
            # attempt. The baseline makes no such call — and that, not a
            # different world, is why it burns the attempt.
            if arm == "sequencer":
                live = mandate_status_at(rec, draw_salt)
                if live is not MandateStatus.ACTIVE:
                    reason = (f"stopped at execution: mandate {live.value} after the "
                              "decision was made — attempt preserved by the "
                              "pre-flight re-check")
                    escalation = Escalation.RE_MANDATE_LINK
                    rule = 3
                    ledger.append(run_id=run_id, arm=arm, event="preflight_refusal",
                                  verdict=reason, subscription_id=rec.subscription_id)
                    break

            ok = _attempt(rec, fc, at, attempt_index, draw_salt)

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

        if not reason:
            if tripped:
                reason = "batch breaker tripped before this record finished"
            else:
                reason = "all available attempts spent without recovery"
                # The budget is now gone. This is the subscription Razorpay
                # halts, and the only route left is winning the customer back.
                escalation = Escalation.WINBACK_CAMPAIGN
                rule = 8

        # Recorded even when the breaker tripped mid-record. Previously this
        # append was skipped on a trip, so attempts already spent on that record
        # were counted in the batch total but belonged to no outcome — the
        # per-record and batch-level accounting disagreed, silently.
        outcomes.append(RecordOutcome(
            subscription_id=rec.subscription_id, amount_paise=rec.amount_paise,
            failure_class=fc, recovered=recovered, attempts_spent=spent,
            attempts_preserved=rec.attempts_remaining - spent,
            terminal_reason=reason,
            rule_fired=rule if arm == "sequencer" else 0,
            escalation=escalation if arm == "sequencer" else Escalation.NONE))

        if tripped:
            break

    result = BatchResult(
        run_id=run_id, arm=arm, records=len(records), outcomes=outcomes,
        actions_taken=fuse.state.actions_taken,
        value_at_risk_paise=sum(r.amount_paise for r in records),
        value_recovered_paise=fuse.state.value_recovered_paise,
        attempts_spent=attempts_spent, wasted_attempts=wasted,
        soft_warnings=fuse.state.soft_warnings,
        breaker_refusals=fuse.state.refusals, tripped=tripped)

    event("execute.batch_complete", arm=arm, run_id=run_id,
          records=len(records), processed=len(outcomes),
          attempts=attempts_spent, wasted=wasted,
          recovered_paise=fuse.state.value_recovered_paise,
          tripped=bool(tripped))
    ledger.append(run_id=run_id, arm=arm, event="batch_end",
                  verdict=(f"finished — ₹{result.value_recovered_paise / 100:,.2f} recovered "
                           f"from {attempts_spent} attempt(s)"),
                  **result.model_dump(include={"value_recovered_paise", "attempts_spent",
                                               "wasted_attempts"}))
    return result


def _sequencer_schedule(
    rec: AtRiskRecord, fc: FailureClass, now: datetime, first: Decision
) -> list[datetime]:
    """Optimal first attempt, then fixed follow-ups if it fails.

    SIMPLIFICATION, stated rather than hidden: the follow-ups are a fixed +7d
    (insufficient funds) or +1d (everything else) rather than a fresh search,
    and neither arm models a new 24h pre-debit notice per follow-up, which RBI
    requires. Both arms are simplified identically, so the comparison is
    unaffected; the absolute schedules are not production-legal as written.

    Follow-ups are truncated at the mandate's validity date for the same reason
    the first attempt is: a debit presented after expiry is rejected, so a
    scheduled slot beyond it is an attempt guaranteed to be wasted.
    """
    out = [first.scheduled_at or now]
    for _ in range(1, rec.attempts_remaining):
        # A failed attempt means the cause persisted; wait a further cycle.
        nxt = out[-1] + timedelta(days=7 if fc is FailureClass.INSUFFICIENT_FUNDS else 1)
        if nxt > rec.mandate_valid_until:
            break
        out.append(nxt)
    return out


def _baseline_schedule(rec: AtRiskRecord, now: datetime) -> list[datetime]:
    """Fixed T+1/T+3/T+5, floored by the legal pre-debit notice window."""
    floor = earliest_legal_retry(rec, now)
    return [max(floor, now + timedelta(days=d))
            for d in BASELINE_OFFSETS_DAYS[: rec.attempts_remaining]]
