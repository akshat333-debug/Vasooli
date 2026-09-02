"""Regressions for defects found in the full-project audit.

Each test here corresponds to a bug that was live in a pushed commit. They are
grouped separately from the feature tests because their value is specifically
that they fail if the fix is reverted.
"""

from datetime import timedelta

import pytest

from vasooli import diagnose as dg
from vasooli.decide import Action, best_retry_time, decide
from vasooli.execute import _sequencer_schedule, run_batch
from vasooli.ledger import Ledger
from vasooli.policy import RecoveryPolicy
from vasooli.report import render
from vasooli.sim.seed import BATCH_NOW, generate_batch
from vasooli.taxonomy import FailureClass


@pytest.fixture
def ledger(tmp_path):
    L = Ledger(tmp_path / "a.db")
    yield L
    L.close()


def _live_record():
    b = generate_batch(100, seed=42)
    return next(r for r in b if r.mandate_status == "active" and r.attempts_used == 0)


# --- BUG 6: scheduler placed retries after the mandate expired ----------------

def test_retry_is_never_scheduled_after_the_mandate_expires():
    rec = _live_record().model_copy(update={
        "mandate_valid_until": BATCH_NOW + timedelta(days=2),
        "salary_day": 10,                 # best probability is ~8 days out
        "pre_debit_notified_at": None,
    })
    d = decide(rec, FailureClass.INSUFFICIENT_FUNDS, BATCH_NOW)
    if d.action is Action.RETRY_SCHEDULED:
        assert d.scheduled_at <= rec.mandate_valid_until, (
            "scheduled a debit the bank would reject — the exact mistake this "
            "engine exists to prevent"
        )


def test_no_lawful_window_stops_instead_of_scheduling():
    # Notice period pushes the earliest legal debit past the mandate's expiry.
    rec = _live_record().model_copy(update={
        "mandate_valid_until": BATCH_NOW + timedelta(hours=6),
        "pre_debit_notified_at": None,     # forces a +24h floor
    })
    d = decide(rec, FailureClass.INSUFFICIENT_FUNDS, BATCH_NOW)
    assert d.action is Action.STOP_TERMINAL
    assert "expires" in d.verdict
    assert d.scheduled_at is None


def test_best_retry_time_returns_none_for_an_empty_window():
    rec = _live_record().model_copy(update={
        "mandate_valid_until": BATCH_NOW + timedelta(hours=1),
        "pre_debit_notified_at": None,
    })
    at, p = best_retry_time(rec, FailureClass.INSUFFICIENT_FUNDS, BATCH_NOW)
    assert at is None and p == 0.0


def test_followup_attempts_are_bounded_by_mandate_validity():
    rec = _live_record().model_copy(update={
        "mandate_valid_until": BATCH_NOW + timedelta(days=3),
        "pre_debit_notified_at": BATCH_NOW - timedelta(hours=48),
        "attempts_used": 0,
    })
    d = decide(rec, FailureClass.INSUFFICIENT_FUNDS, BATCH_NOW)
    if d.action is Action.RETRY_SCHEDULED:
        sched = _sequencer_schedule(rec, FailureClass.INSUFFICIENT_FUNDS, BATCH_NOW, d)
        assert all(s <= rec.mandate_valid_until for s in sched)


def test_simulator_rejects_a_debit_presented_after_expiry():
    from vasooli.execute import _attempt
    rec = _live_record().model_copy(update={
        "mandate_valid_until": BATCH_NOW + timedelta(days=1),
    })
    # Physical reality binds both arms, not just the one that schedules well.
    assert _attempt(rec, FailureClass.INSUFFICIENT_FUNDS,
                    BATCH_NOW + timedelta(days=5), 0) is False


# --- BUG 2: a RunFuse fault took down the whole batch ------------------------

def test_a_runfuse_fault_does_not_kill_the_batch(monkeypatch):
    import contextlib

    class ExplodingFuse:
        def __init__(self, *a, **k): pass
        def wrap(self, c): return c
        def run(self, *a, **k):
            @contextlib.contextmanager
            def cm():
                yield
                raise RuntimeError("simulated RunFuse internal failure")
            return cm()

    monkeypatch.setattr(dg, "Fuse", ExplodingFuse)
    monkeypatch.setattr(dg, "_ask_llm", lambda c, r: (FailureClass.UNKNOWN, True))
    monkeypatch.setenv("VASOOLI_LLM_API_KEY", "x")

    batch = generate_batch(20, seed=42)
    out, stats = dg.diagnose_batch(batch, use_llm=True)

    assert len(out) == len(batch), "records were lost when the AI guardrail failed"
    assert stats.get("fuse_aborted") == 1
    # The dictionary still did its job; the money stage is unaffected.
    assert any(d.failure_class is not FailureClass.UNKNOWN for d in out)


def test_llm_call_failure_degrades_to_unknown_not_an_exception(monkeypatch):
    class Boom:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    raise RuntimeError("gateway exploded")

    fc, reached = dg._ask_llm(Boom(), _live_record())
    assert fc is FailureClass.UNKNOWN
    assert reached is False, 'an unreachable model must not be scored as a disagreement'


# --- BUG 3: missing credentials crashed instead of degrading ------------------

def test_missing_llm_credentials_degrade_rather_than_crash(monkeypatch):
    monkeypatch.delenv("VASOOLI_LLM_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "")
    batch = generate_batch(10, seed=42)
    out, stats = dg.diagnose_batch(batch, use_llm=True)
    assert len(out) == len(batch)
    # Either it degraded cleanly, or it had credentials and worked. Never a crash.
    assert stats.get("degraded") in (1, None)


# --- BUG 1: LLM diagnoses were computed, reported, then discarded -------------

def test_supplied_diagnoses_are_the_ones_actually_used(ledger):
    batch = generate_batch(30, seed=42)
    # Force every record to a terminal class. If run_batch re-diagnoses
    # internally, it will disagree and attempts will be spent.
    from vasooli.models import Diagnosis
    forced = [Diagnosis(subscription_id=r.subscription_id,
                        failure_class=FailureClass.MANDATE_REVOKED,
                        source="test", rationale="forced") for r in batch]
    res = run_batch(batch, arm="sequencer", now=BATCH_NOW, ledger=ledger,
                    diagnoses=forced)
    assert res.attempts_spent == 0, "run_batch ignored the diagnoses it was given"
    assert all(o.failure_class is FailureClass.MANDATE_REVOKED for o in res.outcomes)


# --- BUG 5 & 4: truncated runs -------------------------------------------------

def test_attempt_accounting_is_consistent_when_the_breaker_trips(ledger):
    batch = generate_batch(100, seed=42)
    res = run_batch(batch, arm="baseline", now=BATCH_NOW, ledger=ledger,
                    policy=RecoveryPolicy(max_actions_per_batch=5))
    assert res.attempts_spent == sum(o.attempts_spent for o in res.outcomes), (
        "attempts were spent on a record that produced no outcome"
    )


def test_truncated_run_is_flagged_not_presented_as_a_result(ledger):
    batch = generate_batch(100, seed=42)
    pol = RecoveryPolicy(max_actions_per_batch=10)
    bl = run_batch(batch, arm="baseline", now=BATCH_NOW, ledger=ledger, policy=pol)
    sq = run_batch(batch, arm="sequencer", now=BATCH_NOW, ledger=ledger, policy=pol)
    assert bl.truncated or sq.truncated
    out = render(bl, sq, batch, ledger_ok=True, ledger_rows=1)
    assert "NOT A RESULT" in out, "a truncated run rendered as if complete"


def test_complete_run_is_not_flagged_as_truncated(ledger):
    batch = generate_batch(100, seed=42)
    bl = run_batch(batch, arm="baseline", now=BATCH_NOW, ledger=ledger)
    sq = run_batch(batch, arm="sequencer", now=BATCH_NOW, ledger=ledger)
    assert not bl.truncated and not sq.truncated
    assert "NOT A RESULT" not in render(bl, sq, batch, ledger_ok=True, ledger_rows=1)


# --- BUG 11: an unreachable model was scored as a disagreement ----------------

def test_unreachable_model_is_counted_separately_from_disagreement(monkeypatch):
    # With the gateway down, the run reported 20 "disagreements" — as if a
    # working model had given 20 different answers — instead of failed calls.
    # An accuracy signal computed from calls that never happened is a lie.
    monkeypatch.setattr(dg, "_ask_llm", lambda c, r: (FailureClass.UNKNOWN, False))
    monkeypatch.setenv("VASOOLI_LLM_API_KEY", "x")
    out, stats = dg.diagnose_batch(generate_batch(40, seed=42), use_llm=True)

    assert stats["llm_errors"] > 0
    assert stats["disagree"] == 0, "unreachable calls were scored as disagreements"
    assert stats["agree"] == 0
    assert len(out) == 40


def test_report_does_not_claim_agreement_when_no_call_succeeded(ledger):
    from vasooli.report import render
    batch = generate_batch(50, seed=42)
    bl = run_batch(batch, arm="baseline", now=BATCH_NOW, ledger=ledger)
    sq = run_batch(batch, arm="sequencer", now=BATCH_NOW, ledger=ledger)
    stats = {"llm_calls": 24, "agree": 0, "disagree": 0, "llm_rescued": 0,
             "unknown": 4, "llm_errors": 24}
    out = render(bl, sq, batch, ledger_ok=True, ledger_rows=1, llm_stats=stats)
    assert "model unreachable" in out
    assert "not measured" in out


def test_fuse_trip_reaches_the_caller_instead_of_being_swallowed(monkeypatch):
    # _ask_llm must not absorb FuseTripped. Swallowing it turned every later
    # record into a silent UNKNOWN and kept the trip out of the report.
    from runfuse import FuseTripped, Verdict

    verdict = Verdict(severity="hard", fuse="max_steps",
                      reason="test trip", run_id="t")

    class Tripping:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    raise FuseTripped(verdict)

    with pytest.raises(FuseTripped):
        dg._ask_llm(Tripping(), _live_record())
