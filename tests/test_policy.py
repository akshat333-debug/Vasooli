"""The money-side breaker. Limits that do not trip are decoration."""

import pytest

from vasooli.models import MAX_RETRY_BUDGET, RBI_STANDARD_CAP_PAISE
from vasooli.policy import RecoveryFuse, RecoveryPolicy, RecoveryTripped


def test_defaults_match_the_external_constraints():
    # These are not tuning knobs — they are the law and the gateway's behaviour.
    p = RecoveryPolicy()
    assert p.max_attempts_per_subscription == MAX_RETRY_BUDGET
    assert p.max_auto_amount_paise == RBI_STANDARD_CAP_PAISE


def test_action_ceiling_trips_at_the_boundary_not_after():
    f = RecoveryFuse(RecoveryPolicy(max_actions_per_batch=3))
    for _ in range(3):
        f.check(100); f.record(amount_paise=100, recovered=False)
    with pytest.raises(RecoveryTripped) as e:
        f.check(100)
    assert "max_actions_per_batch" in e.value.verdict


def test_value_ceiling_trips_before_the_money_moves():
    f = RecoveryFuse(RecoveryPolicy(max_total_auto_value_paise=1000))
    f.check(600); f.record(amount_paise=600, recovered=False)
    with pytest.raises(RecoveryTripped) as e:
        f.check(600)  # would reach 1200
    assert "max_total_auto_value_paise" in e.value.verdict
    # Nothing was recorded for the refused action.
    assert f.state.value_attempted_paise == 600


def test_trip_carries_a_readable_verdict_and_the_state():
    f = RecoveryFuse(RecoveryPolicy(max_actions_per_batch=1))
    f.check(100); f.record(amount_paise=100, recovered=True)
    with pytest.raises(RecoveryTripped) as e:
        f.check(100)
    assert "—" in e.value.verdict, "verdict must explain, not just name the limit"
    assert e.value.state.actions_taken == 1


def test_soft_warning_fires_once_per_limit_not_once_per_action():
    f = RecoveryFuse(RecoveryPolicy(max_actions_per_batch=10))
    for _ in range(9):
        f.check(100); f.record(amount_paise=100, recovered=False)
    actions = [w for w in f.state.soft_warnings if w.startswith("soft: actions")]
    assert len(actions) == 1, f"expected one warning, got {len(actions)}"


def test_soft_warning_does_not_fire_below_the_threshold():
    f = RecoveryFuse(RecoveryPolicy(max_actions_per_batch=100))
    for _ in range(5):
        f.check(100); f.record(amount_paise=100, recovered=False)
    assert not f.state.soft_warnings


def test_recovered_value_only_counts_successes():
    f = RecoveryFuse()
    f.record(amount_paise=500, recovered=True)
    f.record(amount_paise=700, recovered=False)
    assert f.state.value_recovered_paise == 500
    assert f.state.value_attempted_paise == 1200
