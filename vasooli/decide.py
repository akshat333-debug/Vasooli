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

  1. Retry budget exhausted        -> STOP. Razorpay halts the subscription.
  2. Terminal failure class        -> STOP. A retry cannot succeed.
  3. Mandate not active            -> STOP. Even if the failure looked live.
  4. Unclassified failure          -> HUMAN. Never auto-act on a guess.
  5. Amount over the mandate cap   -> HUMAN. Guaranteed to fail if attempted.
  6. Amount over the RBI cap       -> HUMAN. Automation does not act alone here.
  7. Mandate expires before the
     notice period elapses         -> STOP. No lawful window exists.
  8. Otherwise                     -> schedule the retry at its best moment,
                                      bounded by the mandate's validity date.

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

from pydantic import BaseModel

from .models import PRE_DEBIT_NOTICE_HOURS, AtRiskRecord, MandateStatus
from .sim.model import success_probability
from .taxonomy import FailureClass, is_terminal


class Action(StrEnum):
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    STOP_EXHAUSTED = "STOP_EXHAUSTED"
    STOP_TERMINAL = "STOP_TERMINAL"


class Decision(BaseModel):
    subscription_id: str
    action: Action
    #: When the retry should be attempted. None for every non-retry action.
    scheduled_at: datetime | None = None
    #: Assumed P(success) at the scheduled moment. None for non-retry actions.
    expected_success: float | None = None
    #: Human-readable reason. Always populated. This is what lands in the ledger.
    verdict: str
    #: True when a Hinglish customer nudge should be drafted for this record.
    wants_nudge: bool = False


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

    best_at, best_p = start, -1.0
    for h in range(0, horizon_days * 24 + 1, step_hours):
        at = start + timedelta(hours=h)
        if at > rec.mandate_valid_until:
            break
        p = success_probability(
            failure_class,
            attempt_index,
            hours_since_failure=(at - rec.last_attempt_at).total_seconds() / 3600.0,
            days_to_replenish=days_to_replenish(at, rec.salary_day),
        )
        if p > best_p:
            best_at, best_p = at, p
    return best_at, best_p


def decide(rec: AtRiskRecord, failure_class: FailureClass, now: datetime) -> Decision:
    """Apply the stopping rules, then schedule. See module docstring for order."""

    def d(action: Action, verdict: str, **kw) -> Decision:
        return Decision(subscription_id=rec.subscription_id, action=action,
                        verdict=verdict, **kw)

    # 1. The budget is gone. Attempting anything here halts the subscription.
    if rec.attempts_remaining <= 0:
        return d(
            Action.STOP_EXHAUSTED,
            f"stopped: retry budget exhausted ({rec.attempts_used}/"
            f"{rec.attempts_used}) — a further attempt would halt the subscription",
            wants_nudge=True,
        )

    # 2. The failure class makes a retry pointless.
    if is_terminal(failure_class):
        return d(
            Action.STOP_TERMINAL,
            f"stopped: {failure_class.value} — no retry can succeed, "
            f"{rec.attempts_remaining} attempt(s) preserved",
            wants_nudge=True,
        )

    # 3. The mandate itself is dead, whatever the error text implied.
    if rec.mandate_status is not MandateStatus.ACTIVE:
        return d(
            Action.STOP_TERMINAL,
            f"stopped: mandate is {rec.mandate_status.value} despite a "
            f"{failure_class.value} failure — retry would be spent on a dead mandate",
            wants_nudge=True,
        )

    # 4. Nobody could classify it. Do not guess with someone's money.
    if failure_class is FailureClass.UNKNOWN:
        return d(
            Action.HUMAN_REVIEW,
            "human review: failure could not be classified by dict or model "
            "— refusing to spend an attempt on an unknown cause",
        )

    # 5. The debit is larger than the mandate permits. It cannot succeed.
    if rec.exceeds_mandate_cap:
        return d(
            Action.HUMAN_REVIEW,
            f"human review: amount ₹{rec.amount_paise / 100:,.2f} exceeds the mandate "
            f"cap ₹{rec.mandate_max_amount_paise / 100:,.2f} — needs a fresh mandate",
        )

    # 6. Above the RBI standard cap, automation does not act alone.
    if rec.needs_human_approval:
        return d(
            Action.HUMAN_REVIEW,
            f"human review: amount ₹{rec.amount_paise / 100:,.2f} exceeds the RBI "
            f"e-mandate standard cap — outside the unattended envelope",
        )

    # 7. The mandate expires before a debit could lawfully be presented.
    #    The RBI notice floor and the mandate's validity date can leave no window
    #    at all, and scheduling into that gap would spend an attempt on a debit
    #    the bank will reject — the precise mistake this engine exists to avoid.
    at, p = best_retry_time(rec, failure_class, now)
    if at is None:
        return d(
            Action.STOP_TERMINAL,
            f"stopped: mandate expires {rec.mandate_valid_until:%Y-%m-%d} before a "
            f"debit could lawfully be presented (pre-debit notice floor is "
            f"{earliest_legal_retry(rec, now):%Y-%m-%d}) — "
            f"{rec.attempts_remaining} attempt(s) preserved",
            wants_nudge=True,
        )

    # 8. Eligible. Spend the attempt at its best moment.
    waited = (at - now).total_seconds() / 3600.0
    return d(
        Action.RETRY_SCHEDULED,
        f"retry scheduled +{waited:.0f}h for {failure_class.value} "
        f"(assumed p={p:.2f}, attempt {rec.attempts_used + 1}/"
        f"{rec.attempts_used + rec.attempts_remaining})",
        scheduled_at=at,
        expected_success=p,
        wants_nudge=(p < 0.4),
    )
