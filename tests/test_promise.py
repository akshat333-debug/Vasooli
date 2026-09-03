"""A promise is unverified customer input. These tests pin what it may not do."""

from datetime import timedelta

import pytest

from vasooli.decide import Action, decide
from vasooli.models import MandateStatus
from vasooli.promise import (
    MAX_HONOURED_MISSES,
    MAX_PROMISE_HORIZON_DAYS,
    Promise,
    PromiseState,
    apply_promise,
    settle,
)
from vasooli.sim.seed import BATCH_NOW, generate_batch
from vasooli.taxonomy import FailureClass


def _live():
    b = generate_batch(100, seed=42)
    return next(r for r in b
                if r.mandate_status is MandateStatus.ACTIVE and r.attempts_used == 0)


def _scheduled(rec):
    d = decide(rec, FailureClass.INSUFFICIENT_FUNDS, BATCH_NOW)
    assert d.action is Action.RETRY_SCHEDULED
    return d


def _promise(rec, days, misses=0):
    return Promise(subscription_id=rec.subscription_id,
                   promised_for=BATCH_NOW + timedelta(days=days),
                   made_at=BATCH_NOW, prior_misses=misses)


# --- what a promise must never do ---------------------------------------------

def test_a_promise_cannot_reopen_a_refused_record():
    # The most important rule here. Customer input is not an override for a
    # mandate or compliance decision.
    b = generate_batch(100, seed=42)
    dead = next(r for r in b if r.mandate_status is not MandateStatus.ACTIVE)
    d = decide(dead, FailureClass.INSUFFICIENT_FUNDS, BATCH_NOW)
    assert d.action is not Action.RETRY_SCHEDULED

    out = apply_promise(dead, d, _promise(dead, 3), BATCH_NOW)
    assert not out.honoured
    assert out.scheduled_at is None
    assert "does not reopen it" in out.verdict


def test_a_promise_cannot_pull_a_retry_forward():
    # Unverified input may only push a money action away, never nearer.
    rec = _live()
    d = _scheduled(rec)
    early = Promise(subscription_id=rec.subscription_id,
                    promised_for=BATCH_NOW, made_at=BATCH_NOW)
    out = apply_promise(rec, d, early, BATCH_NOW)
    assert not out.honoured
    assert out.scheduled_at == d.scheduled_at
    assert "never" in out.verdict and "forward" in out.verdict


def test_a_promise_never_precedes_the_legal_notice_floor():
    rec = _live().model_copy(update={"pre_debit_notified_at": None})
    d = decide(rec, FailureClass.INSUFFICIENT_FUNDS, BATCH_NOW)
    if d.action is Action.RETRY_SCHEDULED:
        out = apply_promise(rec, d, _promise(rec, 10), BATCH_NOW)
        if out.scheduled_at:
            assert out.scheduled_at >= BATCH_NOW + timedelta(hours=24)


def test_a_promise_after_the_mandate_expires_is_ignored():
    rec = _live()
    d = _scheduled(rec)
    far = Promise(subscription_id=rec.subscription_id,
                  promised_for=rec.mandate_valid_until + timedelta(days=1),
                  made_at=BATCH_NOW)
    out = apply_promise(rec, d, far, BATCH_NOW)
    assert not out.honoured
    assert "after the mandate expires" in out.verdict


def test_a_promise_beyond_the_horizon_is_ignored():
    rec = _live()
    d = _scheduled(rec)
    out = apply_promise(rec, d, _promise(rec, MAX_PROMISE_HORIZON_DAYS + 5), BATCH_NOW)
    assert not out.honoured
    assert "horizon" in out.verdict


# --- trust decays --------------------------------------------------------------

def test_a_repeat_breaker_stops_moving_the_schedule():
    # Trust is a resource with a floor, like the retry budget. A system that
    # reschedules forever on a customer's word burns the whole budget waiting.
    rec = _live()
    d = _scheduled(rec)
    out = apply_promise(rec, d, _promise(rec, 3, misses=MAX_HONOURED_MISSES), BATCH_NOW)
    assert not out.honoured
    assert "previous promises broken" in out.verdict


@pytest.mark.parametrize("misses", range(MAX_HONOURED_MISSES))
def test_a_promise_is_still_honoured_below_the_miss_limit(misses):
    rec = _live()
    d = _scheduled(rec)
    later = (d.scheduled_at - BATCH_NOW).days + 2
    out = apply_promise(rec, d, _promise(rec, later, misses=misses), BATCH_NOW)
    assert out.honoured
    assert out.scheduled_at > d.scheduled_at


# --- settlement ------------------------------------------------------------------

def test_a_broken_promise_increments_the_miss_count():
    p = _promise(_live(), 3)
    assert settle(p, recovered=False).prior_misses == 1
    assert settle(p, recovered=False).state is PromiseState.BROKEN


def test_a_kept_promise_does_not():
    p = _promise(_live(), 3)
    assert settle(p, recovered=True).prior_misses == 0
    assert settle(p, recovered=True).state is PromiseState.KEPT


def test_no_promise_leaves_the_decision_untouched():
    rec = _live()
    d = _scheduled(rec)
    out = apply_promise(rec, d, None, BATCH_NOW)
    assert out.scheduled_at == d.scheduled_at
    assert not out.honoured


def test_every_verdict_explains_itself():
    rec = _live()
    d = _scheduled(rec)
    for p in (None, _promise(rec, 1), _promise(rec, 60), _promise(rec, 3, misses=9)):
        assert apply_promise(rec, d, p, BATCH_NOW).verdict.strip()
