"""The arm comparison must be fair, and physical limits must bind both arms."""

import tempfile

import pytest

from vasooli.execute import _draw, run_batch
from vasooli.ledger import Ledger
from vasooli.models import MandateStatus
from vasooli.sim.seed import BATCH_NOW, generate_batch


@pytest.fixture
def ledger(tmp_path):
    L = Ledger(tmp_path / "e.db")
    yield L
    L.close()


def _run(ledger, arm, n=100):
    return run_batch(generate_batch(n, seed=42), arm=arm, now=BATCH_NOW,
                     ledger=ledger, use_llm=False)


def test_random_draw_is_shared_and_stable():
    # The fairness mechanism: both arms test the same draw against different
    # probabilities. If this ever varies, the comparison is worthless.
    assert _draw("sub_A", 0) == _draw("sub_A", 0)
    assert _draw("sub_A", 0) != _draw("sub_A", 1)
    assert 0.0 <= _draw("sub_A", 0) <= 1.0


def test_both_arms_see_every_record(ledger):
    for arm in ("baseline", "sequencer"):
        assert len(_run(ledger, arm).outcomes) == 100


def test_runs_are_deterministic(ledger):
    a = _run(ledger, "sequencer")
    b = _run(ledger, "sequencer")
    assert a.value_recovered_paise == b.value_recovered_paise
    assert a.attempts_spent == b.attempts_spent


def test_sequencer_spends_fewer_attempts_than_the_baseline(ledger):
    # The thesis. If this inverts, the project's claim is false and the report
    # should say so rather than this test being deleted.
    assert _run(ledger, "sequencer").attempts_spent < _run(ledger, "baseline").attempts_spent


def test_sequencer_never_debits_above_the_rbi_cap(ledger):
    batch = generate_batch(100, seed=42)
    by = {r.subscription_id: r for r in batch}
    res = _run(ledger, "sequencer")
    assert not [o for o in res.outcomes
                if o.attempts_spent and by[o.subscription_id].needs_human_approval]


def test_no_arm_ever_recovers_from_a_dead_mandate(ledger):
    # Physical reality, applied to both arms. Bank rejects it, full stop.
    batch = generate_batch(100, seed=42)
    by = {r.subscription_id: r for r in batch}
    for arm in ("baseline", "sequencer"):
        for o in _run(ledger, arm).outcomes:
            if by[o.subscription_id].mandate_status is not MandateStatus.ACTIVE:
                assert not o.recovered


def test_no_arm_ever_recovers_above_the_mandate_cap(ledger):
    batch = generate_batch(100, seed=42)
    by = {r.subscription_id: r for r in batch}
    for arm in ("baseline", "sequencer"):
        for o in _run(ledger, arm).outcomes:
            if by[o.subscription_id].exceeds_mandate_cap:
                assert not o.recovered


def test_no_record_exceeds_its_retry_budget(ledger):
    batch = generate_batch(100, seed=42)
    by = {r.subscription_id: r for r in batch}
    for arm in ("baseline", "sequencer"):
        for o in _run(ledger, arm).outcomes:
            assert o.attempts_spent <= by[o.subscription_id].attempts_remaining


def test_every_record_has_a_terminal_reason(ledger):
    # No silent outcomes. Every record explains itself.
    assert all(o.terminal_reason.strip() for o in _run(ledger, "sequencer").outcomes)


def test_ledger_chain_survives_a_full_run(ledger):
    _run(ledger, "baseline")
    _run(ledger, "sequencer")
    v = ledger.verify()
    assert v.ok and v.rows > 200


def test_preflight_refusal_is_recorded_in_the_ledger(ledger):
    res = _run(ledger, "sequencer")
    rows = [r for r in ledger.rows(res.run_id) if r["event"] == "preflight_refusal"]
    assert rows, "late-revocation hazard never exercised"
    assert all("preserved" in r["verdict"] for r in rows)
