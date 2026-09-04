"""Decide what to do with one at-risk subscription.

NO LANGUAGE MODEL RUNS IN THIS FILE, AND THAT IS THE POINT.

A model decides how to talk to a customer. It never decides whether to move
money. The reasons are not stylistic:

  * Reproducibility. A regulator, a merchant, or a judge asking "why did you
    debit this customer on the 7th" must get the same answer every time. A
    sampled model cannot promise that.
  * Testability. Every stopping rule below has a test that fails if the rule is
    deleted. You cannot write that test against a prompt.
  * Auditability. The verdict strings here are derived from the inputs, so the
    audit trail explains the decision rather than narrating it after the fact.

THE STOPPING RULES, IN ORDER. Order matters: the cheapest and most certain
refusals come first, so no work is done on a record that was never eligible.

  1. Retry budget exhausted        -> STOP.  WINBACK_CAMPAIGN
  2. Terminal failure class        -> STOP.  RE_MANDATE_LINK (MANDATE_UPGRADE
                                             when the class is LIMIT_EXCEEDED)
  3. Mandate not active            -> STOP.  RE_MANDATE_LINK
  4. Unclassified failure          -> HUMAN. HUMAN_REVIEW
  5. Amount over the mandate cap   -> HUMAN. MANDATE_UPGRADE
  6. Amount over the RBI cap       -> HUMAN. AFA_PAYMENT_LINK
  7. Mandate expires before the
     notice period elapses         -> STOP.  RE_MANDATE_LINK
  8. Otherwise                     -> schedule the retry at its best moment,
                                      bounded by the mandate's validity date.

Seven of the eight are stopping rules; rule 8 is the scheduling rule. Each stop
carries an Escalation, because refusing to debit is only half an answer — the
rupee is still owed, and the route it takes next is part of the decision.

Rules 1-3 exist because the retry budget is only three attempts deep. Spending
one on a record that could never have succeeded is the most expensive mistake
available to this system, and it is invisible unless you look for it.

Rule 7 was added after an audit found the scheduler doing exactly that: it
placed a retry six days past the mandate's expiry and reported a confident
p=0.62 for a debit the bank would have rejected outright. The stopping rules
guarded against dead mandates on the way in, but the scheduler could still
create one on the way out.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel

from .models import PRE_DEBIT_NOTICE_HOURS, AtRiskRecord, MandateStatus
from .sim.model import success_probability as _sim_scorer
from .taxonomy import FailureClass, is_terminal


class Scorer(Protocol):
    """Assumed P(success) for a debit, given a class, an attempt and a moment.

    Injected rather than imported so that the fact the scheduler currently
    optimises against the SAME function the simulator grades it with is a
    visible default and not a hidden coupling. Swapping in a model learned from
    a merchant's own history is a one-argument change; nothing else in this
    module knows where the number came from.
    """

    def __call__(
        self,
        failure_class: FailureClass,
        attempt_index: int,
        *,
        hours_since_failure: float,
        days_to_replenish: int,
    ) -> float: ...


#: The default scorer. See sim/model.py for every assumption it encodes.
success_probability: Scorer = _sim_scorer


class Action(StrEnum):
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    STOP_EXHAUSTED = "STOP_EXHAUSTED"
    STOP_TERMINAL = "STOP_TERMINAL"


class Escalation(StrEnum):
    """The compliant next step when automation will not retry.

    A stop is not an escalation. Refusing to debit is only half an answer: the
    rupee is still at risk and someone has to do something about it. Every
    record the engine declines therefore carries the route it goes down, as
    DATA rather than as English buried in a verdict string, so the exception
    list is a queue a human can work rather than a graveyard.
    """

    NONE = "NONE"                          # a retry is scheduled; nothing to route
    WINBACK_CAMPAIGN = "WINBACK_CAMPAIGN"  # budget gone; fresh invoice + nudge
    RE_MANDATE_LINK = "RE_MANDATE_LINK"    # mandate dead; new registration link
    MANDATE_UPGRADE = "MANDATE_UPGRADE"    # above the mandate's own registered cap
    AFA_PAYMENT_LINK = "AFA_PAYMENT_LINK"  # above the RBI AFA-free cap; customer-present
    HUMAN_REVIEW = "HUMAN_REVIEW"          # nobody could classify it; a person reads it


class Decision(BaseModel):
    subscription_id: str
    action: Action
    #: When the retry should be attempted. None for every non-retry action.
    scheduled_at: datetime | None = None
    #: Assumed P(success) at the scheduled moment. None for non-retry actions.
    expected_success: float | None = None
    #: Human-readable reason. Always populated. This is what lands in the ledger.
    verdict: str
    #: True when this record warrants a customer nudge instead of, or
    #: alongside, a retry — a terminal stop the customer must act on, or a
    #: retry whose odds are poor enough that asking is worth more than
    #: spending an attempt.
    #:
    #: Consumed by nudge.py, which drafts the message. The flag is the
    #: decision; the copy is a separate, model-written and guard-railed step.
    wants_nudge: bool = False
    #: Which numbered stopping rule decided this record (1-8, see module
    #: docstring). Exported so a viewer can show the trace without
    #: reimplementing the rule ordering — a duplicated decision rule living in
    #: a UI is a rule that will silently drift out of step with this file.
    rule_fired: int = 0
    #: The compliant next step for this record. Structured, not prose — the
    #: report and the UI group on this, which is what stopped the exception
    #: list fragmenting one group per rupee amount (defect 22).
    escalation: Escalation = Escalation.NONE


def days_to_replenish(at: datetime, salary_day: int) -> int:
    """Days from `at` back to the most recent replenishment day, negated.

    Returns 0 or negative when replenishment has already happened this cycle
    (0 = today, -3 = three days ago), matching sim.model's convention. The
    further negative, the longer the balance has had to be drawn down again.
    """
    if at.day >= salary_day:
        return -(at.day - salary_day)
    # Replenishment day fell in the previous month.
    prev_month_end = at.replace(day=1) - timedelta(days=1)
    day = min(salary_day, prev_month_end.day)
    last = prev_month_end.replace(day=day)
    return -(at - last).days


def earliest_legal_retry(rec: AtRiskRecord, now: datetime) -> datetime:
    """The soonest moment a debit may lawfully be attempted.

    RBI's e-mandate framework requires a pre-debit notification ahead of the
    debit. If one is already on file the clock has run; if not, we must send one
    and wait the notice period. This is a legal floor, not an optimisation — it
    is applied to both arms.
    """
    if rec.pre_debit_notified_at is None:
        return now + timedelta(hours=PRE_DEBIT_NOTICE_HOURS)
    ready = rec.pre_debit_notified_at + timedelta(hours=PRE_DEBIT_NOTICE_HOURS)
    return max(now, ready)


def best_retry_time(
    rec: AtRiskRecord,
    failure_class: FailureClass,
    now: datetime,
    *,
    horizon_days: int = 14,
    step_hours: int = 6,
    scorer: Scorer = success_probability,
) -> tuple[datetime | None, float]:
    """Search the legal window for the moment with the highest assumed success.

    A plain grid search. It is deliberately boring: exhaustive over a small
    bounded grid, fully deterministic, and trivial to explain to someone who
    needs to trust the debit. Ties resolve to the earliest moment, because
    recovering the same rupee sooner is strictly better for the merchant.

    The window is bounded on BOTH ends. The lower bound is the RBI pre-debit
    notice floor. The upper bound is the mandate's own validity date, because a
    debit presented after the mandate expires is rejected — scheduling into that
    region would be the exact mistake this project exists to prevent, committed
    by the component that is supposed to prevent it.

    Returns (None, 0.0) when the legal window is empty, i.e. the mandate expires
    before a debit could lawfully be presented at all.
    """
    start = earliest_legal_retry(rec, now)
    if start > rec.mandate_valid_until:
        return None, 0.0

    attempt_index = rec.attempts_used

    if rec.salary_day is None:
        # No replenishment day known, so there is nothing to time against and
        # the grid search would be optimising over a fiction. Schedule at the
        # legal floor and score it with replenishment treated as neutral.
        return start, scorer(
            failure_class,
            attempt_index,
            hours_since_failure=(start - rec.last_attempt_at).total_seconds() / 3600.0,
            days_to_replenish=0,
        )

    best_at, best_p = start, -1.0
    for h in range(0, horizon_days * 24 + 1, step_hours):
        at = start + timedelta(hours=h)
        if at > rec.mandate_valid_until:
            break
        p = scorer(
            failure_class,
            attempt_index,
            hours_since_failure=(at - rec.last_attempt_at).total_seconds() / 3600.0,
            days_to_replenish=days_to_replenish(at, rec.salary_day),
        )
        if p > best_p:
            best_at, best_p = at, p
    return best_at, best_p


def decide(
    rec: AtRiskRecord,
    failure_class: FailureClass,
    now: datetime,
    *,
    disabled_rules: frozenset[int] = frozenset(),
    scorer: Scorer = success_probability,
) -> Decision:
    """Apply the stopping rules, then schedule. See module docstring for order.

    `disabled_rules` exists for ablation only (see experiments.py): switching a
    rule off and re-running measures what that rule is actually worth, in wasted
    attempts and rupees. It is never used in a real run — a rule that can be
    turned off by an argument is a rule that can be turned off by accident, so
    the default is empty and every caller in the engine leaves it alone.
    """

    def d(rule: int, action: Action, verdict: str,
          escalation: Escalation = Escalation.NONE, **kw) -> Decision:
        return Decision(subscription_id=rec.subscription_id, action=action,
                        verdict=verdict, rule_fired=rule, escalation=escalation, **kw)

    def on(rule: int) -> bool:
        return rule not in disabled_rules

    # 1. The budget is gone. Attempting anything here halts the subscription.
    if on(1) and rec.attempts_remaining <= 0:
        return d(
            1,
            Action.STOP_EXHAUSTED,
            f"stopped: retry budget exhausted ({rec.attempts_used}/"
            f"{rec.attempts_used}) — a further attempt would halt the subscription",
            escalation=Escalation.WINBACK_CAMPAIGN,
            wants_nudge=True,
        )

    # 2. The failure class makes a retry pointless.
    if on(2) and is_terminal(failure_class):
        return d(
            2,
            Action.STOP_TERMINAL,
            f"stopped: {failure_class.value} — no retry can succeed, "
            f"{rec.attempts_remaining} attempt(s) preserved",
            escalation=(Escalation.MANDATE_UPGRADE
                        if failure_class is FailureClass.LIMIT_EXCEEDED
                        else Escalation.RE_MANDATE_LINK),
            wants_nudge=True,
        )

    # 3. The mandate itself is dead, whatever the error text implied.
    if on(3) and rec.mandate_status is not MandateStatus.ACTIVE:
        return d(
            3,
            Action.STOP_TERMINAL,
            f"stopped: mandate is {rec.mandate_status.value} despite a "
            f"{failure_class.value} failure — retry would be spent on a dead mandate",
            escalation=Escalation.RE_MANDATE_LINK,
            wants_nudge=True,
        )

    # 4. Nobody could classify it. Do not guess with someone's money.
    if on(4) and failure_class is FailureClass.UNKNOWN:
        return d(
            4,
            Action.HUMAN_REVIEW,
            "human review: failure could not be classified by dict or model "
            "— refusing to spend an attempt on an unknown cause",
            escalation=Escalation.HUMAN_REVIEW,
        )

    # 5. The debit is larger than the mandate permits. It cannot succeed.
    if on(5) and rec.exceeds_mandate_cap:
        return d(
            5,
            Action.HUMAN_REVIEW,
            f"human review: amount ₹{rec.amount_paise / 100:,.2f} exceeds the mandate "
            f"cap ₹{rec.mandate_max_amount_paise / 100:,.2f} — needs a fresh mandate",
            escalation=Escalation.MANDATE_UPGRADE,
        )

    # 6. Above the RBI standard cap, automation does not act alone.
    if on(6) and rec.needs_human_approval:
        return d(
            6,
            Action.HUMAN_REVIEW,
            f"escalated: amount ₹{rec.amount_paise / 100:,.2f} exceeds the RBI "
            f"e-mandate AFA-free cap — an unattended debit would be declined on "
            f"presentation; routed to a customer-present payment link with AFA, "
            f"{rec.attempts_remaining} attempt(s) preserved",
            escalation=Escalation.AFA_PAYMENT_LINK,
        )

    # 7. The mandate expires before a debit could lawfully be presented.
    #    The RBI notice floor and the mandate's validity date can leave no window
    #    at all, and scheduling into that gap would spend an attempt on a debit
    #    the bank will reject — the precise mistake this engine exists to avoid.
    at, p = best_retry_time(rec, failure_class, now, scorer=scorer)
    if on(7) and at is None:
        return d(
            7,
            Action.STOP_TERMINAL,
            f"stopped: mandate expires {rec.mandate_valid_until:%Y-%m-%d} before a "
            f"debit could lawfully be presented (pre-debit notice floor is "
            f"{earliest_legal_retry(rec, now):%Y-%m-%d}) — "
            f"{rec.attempts_remaining} attempt(s) preserved",
            escalation=Escalation.RE_MANDATE_LINK,
            wants_nudge=True,
        )

    # 8. Eligible. Spend the attempt at its best moment.
    if at is None:
        # Only reachable with rule 7 ablated. There is no lawful moment, so the
        # ablation must still not invent one — it schedules at the floor and the
        # simulator rejects the debit, which is exactly the cost being measured.
        at = earliest_legal_retry(rec, now)
        p = 0.0
    waited = (at - now).total_seconds() / 3600.0
    return d(
        8,
        Action.RETRY_SCHEDULED,
        f"retry scheduled +{waited:.0f}h for {failure_class.value} "
        f"(assumed p={p:.2f}, attempt {rec.attempts_used + 1}/"
        f"{rec.attempts_used + rec.attempts_remaining})"
        + ("" if rec.salary_day is not None else
           " — replenishment day unknown, scheduled at the legal floor rather "
           "than around an assumed payday"),
        scheduled_at=at,
        expected_success=p,
        wants_nudge=(p < 0.4),
    )
