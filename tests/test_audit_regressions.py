"""Regressions for defects found in the full-project audit.

Each test here corresponds to a bug that was live in a pushed commit. They are
grouped separately from the feature tests because their value is specifically
that they fail if the fix is reverted.
"""

import ast
import inspect
import textwrap
from datetime import timedelta

import pytest
from hypothesis import given, settings
from test_properties import records  # shared Hypothesis strategy (a strategy object)

from vasooli import diagnose as dg
from vasooli.decide import Action, Escalation, best_retry_time, decide
from vasooli.execute import _attempt, _sequencer_schedule, mandate_status_at, run_batch
from vasooli.ledger import Ledger
from vasooli.models import MAX_RETRY_BUDGET, RBI_STANDARD_CAP_PAISE, MandateStatus
from vasooli.policy import ActionRefused, RecoveryFuse, RecoveryPolicy, RecoveryTripped
from vasooli.report import pushed_to_halt, render
from vasooli.sim.seed import BATCH_NOW, generate_batch
from vasooli.taxonomy import FailureClass
from vasooli.webhook import to_record


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


# --- BUG 12: the viewer reimplemented the engine's rule ordering --------------

def test_every_decision_reports_which_rule_fired():
    # The web viewer used to recompute the stopping-rule order in TypeScript to
    # show a decision trace. A second copy of a money decision, in a language
    # with no tests against this file, is free to drift silently. The engine now
    # reports it and the viewer only renders it.
    batch = generate_batch(100, seed=42)
    from vasooli.diagnose import diagnose_batch
    diagnoses, _ = diagnose_batch(batch, use_llm=False)
    for rec, diag in zip(batch, diagnoses):
        d = decide(rec, diag.failure_class, BATCH_NOW)
        assert 1 <= d.rule_fired <= 8, f"{rec.subscription_id} reported rule {d.rule_fired}"


def test_rule_fired_matches_the_action_it_implies():
    rule_action = {
        1: Action.STOP_EXHAUSTED, 2: Action.STOP_TERMINAL, 3: Action.STOP_TERMINAL,
        4: Action.HUMAN_REVIEW, 5: Action.HUMAN_REVIEW, 6: Action.HUMAN_REVIEW,
        7: Action.STOP_TERMINAL, 8: Action.RETRY_SCHEDULED,
    }
    batch = generate_batch(100, seed=42)
    from vasooli.diagnose import diagnose_batch
    diagnoses, _ = diagnose_batch(batch, use_llm=False)
    for rec, diag in zip(batch, diagnoses):
        d = decide(rec, diag.failure_class, BATCH_NOW)
        assert rule_action[d.rule_fired] is d.action, (
            f"{rec.subscription_id}: rule {d.rule_fired} implies "
            f"{rule_action[d.rule_fired]} but action was {d.action}"
        )


def test_export_carries_rule_fired_for_every_record():
    import tempfile

    from vasooli.export import build_payload
    p = build_payload(20, seed=42, use_llm=False, db_path=tempfile.mktemp(suffix=".db"))
    assert all(1 <= r["rule_fired"] <= 8 for r in p["records"])


# --- BUG 13: the money breaker accepted a negative debit ----------------------

@pytest.mark.parametrize("amount", [-1, -50000, 0])
def test_breaker_refuses_non_positive_amounts(amount):
    # A negative debit would DECREASE the batch's attempted total, quietly
    # raising the ceiling for every action after it.
    from vasooli.policy import RecoveryFuse, RecoveryTripped
    f = RecoveryFuse()
    with pytest.raises(RecoveryTripped, match="invalid_amount"):
        f.check(amount)


def test_breaker_still_accepts_a_normal_debit():
    from vasooli.policy import RecoveryFuse
    f = RecoveryFuse()
    f.check(49900)
    f.record(amount_paise=49900, recovered=True)
    assert f.state.value_recovered_paise == 49900


# --- D18: the fuse declared two limits and enforced neither ------------------

def test_fuse_refuses_a_debit_above_the_unattended_cap():
    f = RecoveryFuse()
    with pytest.raises(ActionRefused):
        f.check(RBI_STANDARD_CAP_PAISE + 1)
    assert f.state.refusals == 1


def test_an_above_cap_refusal_is_not_a_batch_trip():
    # The distinction is the whole point. A per-debit limit that halted the run
    # would truncate the comparison it exists to protect -- that was defect 2.
    f = RecoveryFuse()
    with pytest.raises(ActionRefused):
        f.check(RBI_STANDARD_CAP_PAISE + 1)
    f.check(100)  # the batch continues
    assert f.state.refusals == 1


def test_a_refusal_is_not_caught_as_a_trip():
    f = RecoveryFuse()
    with pytest.raises(RecoveryTripped):
        f.check(0)
    try:
        f.check(RBI_STANDARD_CAP_PAISE + 1)
    except RecoveryTripped:  # pragma: no cover - fails the assertion below
        pytest.fail("an above-cap refusal must not be a RecoveryTripped")
    except ActionRefused:
        pass


def test_fuse_refuses_an_attempt_beyond_the_subscription_budget():
    f = RecoveryFuse()
    with pytest.raises(ActionRefused):
        f.check(100, attempts_on_subscription=MAX_RETRY_BUDGET)


# --- D19: the world credited debits the network would decline ---------------

def _rec(**over):
    r = generate_batch(20, seed=7)[0]
    return r.model_copy(update=over)


def test_nothing_above_the_rbi_cap_is_ever_recovered():
    rec = _rec(amount_paise=RBI_STANDARD_CAP_PAISE + 1,
               mandate_max_amount_paise=RBI_STANDARD_CAP_PAISE * 10,
               mandate_status=MandateStatus.ACTIVE)
    for attempt in range(MAX_RETRY_BUDGET):
        assert not _attempt(rec, FailureClass.INSUFFICIENT_FUNDS,
                            rec.last_attempt_at + timedelta(days=1), attempt)


@settings(max_examples=100, deadline=None)
@given(rec=records)
def test_no_record_above_the_cap_is_recoverable_by_any_arm(rec):
    if rec.amount_paise <= RBI_STANDARD_CAP_PAISE:
        return
    assert not _attempt(rec, FailureClass.INSUFFICIENT_FUNDS,
                        rec.last_attempt_at + timedelta(days=1), 0)


# --- D21: the hazard was branched on the arm's name -------------------------

def test_the_execution_path_never_branches_on_the_arms_name():
    # _attempt models the world. If it can see which arm is calling, the
    # comparison is no longer between two strategies in one world.
    # Prose is allowed to name the arms; code is not. Strip the docstring and
    # the comments, then look at what is left.
    src = textwrap.dedent(inspect.getsource(_attempt))
    body = ast.parse(src).body[0].body
    if isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    code = "\n".join(ast.unparse(n) for n in body)
    assert "baseline" not in code
    assert "sequencer" not in code
    assert "arm" not in code


def test_late_revocation_is_a_property_of_the_record_not_the_arm():
    revoked = [r for r in generate_batch(200, seed=3)
               if mandate_status_at(r) is MandateStatus.REVOKED
               and r.mandate_status is MandateStatus.ACTIVE]
    assert revoked, "expected the hazard to hit some record in 200"
    rec = revoked[0]
    # No arm argument exists to pass. Both arms get this answer.
    assert not _attempt(rec, FailureClass.INSUFFICIENT_FUNDS,
                        rec.last_attempt_at + timedelta(days=1), 0)


def test_the_baseline_spends_an_attempt_where_the_sequencer_asks_first(tmp_path):
    records_ = generate_batch(100, seed=3)
    L = Ledger(tmp_path / "l.db")
    bl = run_batch(records_, arm="baseline", now=BATCH_NOW, ledger=L)
    sq = run_batch(records_, arm="sequencer", now=BATCH_NOW, ledger=L)
    L.close()
    revoked = {r.subscription_id for r in records_
               if r.mandate_status is MandateStatus.ACTIVE
               and mandate_status_at(r) is MandateStatus.REVOKED}
    assert revoked
    b = {o.subscription_id: o for o in bl.outcomes}
    s = {o.subscription_id: o for o in sq.outcomes}
    spent_b = sum(b[i].attempts_spent for i in revoked if i in b)
    spent_s = sum(s[i].attempts_spent for i in revoked if i in s)
    assert spent_b > spent_s


# --- D22: the exception list fragmented one group per rupee amount ----------

@settings(max_examples=200, deadline=None)
@given(rec=records)
def test_every_refusal_carries_an_escalation(rec):
    d = decide(rec, FailureClass.INSUFFICIENT_FUNDS, BATCH_NOW)
    if d.action is Action.RETRY_SCHEDULED:
        assert d.escalation is Escalation.NONE
    else:
        assert d.escalation is not Escalation.NONE, d.verdict


def test_two_above_cap_records_land_in_one_group(tmp_path):
    above = [r for r in generate_batch(200, seed=11)
             if r.needs_human_approval and r.mandate_status is MandateStatus.ACTIVE][:2]
    assert len(above) == 2
    assert above[0].amount_paise != above[1].amount_paise, "need distinct amounts"
    L = Ledger(tmp_path / "l.db")
    res = run_batch(above, arm="sequencer", now=BATCH_NOW, ledger=L)
    L.close()
    keys = {(o.rule_fired, o.escalation) for o in res.outcomes}
    assert len(keys) == 1
    assert next(iter(keys))[1] is Escalation.AFA_PAYMENT_LINK


# --- D20: attempts_used came from paid_count --------------------------------

def test_a_mature_subscription_is_not_read_as_exhausted():
    from test_webhook import event

    e = event()
    e["payload"]["subscription"]["entity"].update(paid_count=10, remaining_count=2)
    rec = to_record(e, BATCH_NOW)
    assert rec.attempts_used == 0
    assert rec.attempts_remaining == MAX_RETRY_BUDGET


def test_a_webhook_record_has_no_invented_payday():
    from test_webhook import event

    assert to_record(event(), BATCH_NOW).salary_day is None


# --- the halts metric -------------------------------------------------------

def test_the_sequencer_halts_fewer_recoverable_subscriptions(tmp_path):
    records_ = generate_batch(100, seed=42)
    L = Ledger(tmp_path / "l.db")
    bl = run_batch(records_, arm="baseline", now=BATCH_NOW, ledger=L)
    sq = run_batch(records_, arm="sequencer", now=BATCH_NOW, ledger=L)
    L.close()
    assert len(pushed_to_halt(sq, records_)) <= len(pushed_to_halt(bl, records_))


def test_prior_failures_counts_our_own_ledger_not_the_subscription_entity(tmp_path):
    from vasooli.webhook import prior_failures

    L = Ledger(tmp_path / "w.db")
    assert prior_failures(L, "sub_live1") == 0
    for i in range(2):
        L.append(run_id="r", arm="webhook", event="webhook_received",
                 verdict="accepted", subscription_id=f"evt_{i}",
                 subscription="sub_live1", amount_paise=100)
    L.append(run_id="r", arm="webhook", event="webhook_received",
             verdict="accepted", subscription_id="evt_x",
             subscription="sub_other", amount_paise=100)
    # A row that is not a webhook, and one whose payload names no subscription.
    L.append(run_id="r", arm="webhook", event="webhook_ignored",
             verdict="ignored", subscription_id="evt_y")
    assert prior_failures(L, "sub_live1") == 2
    L.close()


def test_repeated_deliveries_walk_the_budget_down(tmp_path):
    # Three real failures should exhaust the budget; the fourth event arrives
    # with attempts_used already capped rather than raising a ValidationError.
    from test_webhook import event

    from vasooli.webhook import prior_failures, to_record

    L = Ledger(tmp_path / "w.db")
    for i in range(5):
        rec = to_record(event(), BATCH_NOW,
                        attempts_used=prior_failures(L, "sub_live1"))
        assert rec.attempts_used <= MAX_RETRY_BUDGET
        L.append(run_id="r", arm="webhook", event="webhook_received",
                 verdict="accepted", subscription_id=f"evt_{i}",
                 subscription="sub_live1", amount_paise=rec.amount_paise)
    L.close()


def test_an_unknown_payday_schedules_at_the_legal_floor():
    from vasooli.decide import earliest_legal_retry

    rec = _rec(salary_day=None, mandate_status=MandateStatus.ACTIVE,
               attempts_used=0, amount_paise=49900,
               mandate_max_amount_paise=100000)
    d = decide(rec, FailureClass.INSUFFICIENT_FUNDS, BATCH_NOW)
    if d.action is Action.RETRY_SCHEDULED:
        assert d.scheduled_at == earliest_legal_retry(rec, BATCH_NOW)
        assert "replenishment day unknown" in d.verdict


def test_the_hazard_sensitivity_restores_the_rate():
    from vasooli import execute
    from vasooli.experiments import revocation_sensitivity

    before = execute.LATE_REVOCATION_RATE
    out = revocation_sensitivity([1], n=20)
    assert execute.LATE_REVOCATION_RATE == before
    assert out["late_revocation_rate"] == 0.0
    # A 20-record single seed is far too small to say anything about the size
    # of the gain; the claim here is only that the switch is restored and the
    # decomposition still runs and adds up.
    a = out["attribution"]
    assert a["from_refusing_paise"] + a["from_timing_paise"] == pytest.approx(
        a["total_gain_per_attempt_paise"], abs=0.2)
