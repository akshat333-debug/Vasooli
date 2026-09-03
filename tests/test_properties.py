"""Property-based tests over generated records.

The example-based tests check the cases I thought of. These check the cases I
did not: Hypothesis constructs adversarial records — expired mandates, zero
budgets, amounts a rupee either side of a cap — and asserts the invariants hold
for all of them.

Every property here is a safety invariant. If one fails, the engine has
scheduled a debit it should not have.
"""

from datetime import datetime, timedelta

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from vasooli.decide import Action, decide, earliest_legal_retry
from vasooli.models import (
    MAX_RETRY_BUDGET,
    PRE_DEBIT_NOTICE_HOURS,
    RBI_STANDARD_CAP_PAISE,
    AtRiskRecord,
    MandateStatus,
    Method,
    SubscriptionStatus,
)
from vasooli.taxonomy import FailureClass

NOW = datetime(2026, 9, 3, 9, 0)

records = st.builds(
    AtRiskRecord,
    subscription_id=st.just("sub_P"),
    customer_id=st.just("cust_P"),
    mandate_id=st.just("tkn_P"),
    invoice_id=st.just("inv_P"),
    method=st.sampled_from(list(Method)),
    bank=st.sampled_from(["HDFC", "SBI", "ICICI"]),
    amount_paise=st.integers(min_value=1, max_value=60_000_00),
    mandate_status=st.sampled_from(list(MandateStatus)),
    mandate_max_amount_paise=st.integers(min_value=1, max_value=60_000_00),
    mandate_valid_until=st.datetimes(
        min_value=NOW - timedelta(days=90), max_value=NOW + timedelta(days=400)
    ),
    subscription_status=st.just(SubscriptionStatus.ACTIVE),
    attempts_used=st.integers(min_value=0, max_value=MAX_RETRY_BUDGET),
    error_code=st.just("BAD_REQUEST_ERROR"),
    error_reason=st.just("insufficient_funds"),
    error_description=st.just("balance low"),
    last_attempt_at=st.datetimes(
        min_value=NOW - timedelta(days=10), max_value=NOW
    ),
    pre_debit_notified_at=st.one_of(
        st.none(),
        st.datetimes(min_value=NOW - timedelta(days=20), max_value=NOW),
    ),
    salary_day=st.integers(min_value=1, max_value=28),
)

classes = st.sampled_from(list(FailureClass))
P = settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow], deadline=None)


@P
@given(records, classes)
def test_a_scheduled_retry_never_precedes_the_legal_notice_floor(rec, fc):
    d = decide(rec, fc, NOW)
    if d.action is Action.RETRY_SCHEDULED:
        assert d.scheduled_at >= earliest_legal_retry(rec, NOW)


@P
@given(records, classes)
def test_a_scheduled_retry_never_falls_after_the_mandate_expires(rec, fc):
    d = decide(rec, fc, NOW)
    if d.action is Action.RETRY_SCHEDULED:
        assert d.scheduled_at <= rec.mandate_valid_until


@P
@given(records, classes)
def test_a_dead_mandate_is_never_scheduled(rec, fc):
    d = decide(rec, fc, NOW)
    if rec.mandate_status is not MandateStatus.ACTIVE:
        assert d.action is not Action.RETRY_SCHEDULED


@P
@given(records, classes)
def test_an_exhausted_budget_is_never_scheduled(rec, fc):
    if rec.attempts_remaining <= 0:
        assert decide(rec, fc, NOW).action is Action.STOP_EXHAUSTED


@P
@given(records, classes)
def test_nothing_above_the_rbi_cap_is_ever_auto_actioned(rec, fc):
    # The compliance invariant. If this ever fails, the engine has made a debit
    # a merchant may not make unattended.
    if rec.amount_paise > RBI_STANDARD_CAP_PAISE:
        assert decide(rec, fc, NOW).action is not Action.RETRY_SCHEDULED


@P
@given(records, classes)
def test_nothing_above_its_own_mandate_cap_is_ever_scheduled(rec, fc):
    if rec.exceeds_mandate_cap:
        assert decide(rec, fc, NOW).action is not Action.RETRY_SCHEDULED


@P
@given(records, classes)
def test_an_unclassified_failure_is_never_auto_actioned(rec, fc):
    if fc is FailureClass.UNKNOWN and rec.attempts_remaining > 0 \
            and rec.mandate_status is MandateStatus.ACTIVE:
        assert decide(rec, fc, NOW).action is Action.HUMAN_REVIEW


@P
@given(records, classes)
def test_every_decision_carries_a_verdict_and_a_rule(rec, fc):
    d = decide(rec, fc, NOW)
    assert d.verdict.strip()
    assert 1 <= d.rule_fired <= 8


@P
@given(records, classes)
def test_only_scheduled_decisions_carry_a_time_and_a_probability(rec, fc):
    d = decide(rec, fc, NOW)
    if d.action is Action.RETRY_SCHEDULED:
        assert d.scheduled_at is not None and d.expected_success is not None
        assert 0.0 <= d.expected_success <= 1.0
    else:
        assert d.scheduled_at is None


@P
@given(records, classes)
def test_decisions_are_deterministic(rec, fc):
    assert decide(rec, fc, NOW).model_dump() == decide(rec, fc, NOW).model_dump()


@P
@given(records)
def test_a_missing_notice_always_costs_the_full_notice_period(rec):
    if rec.pre_debit_notified_at is None:
        assert earliest_legal_retry(rec, NOW) == NOW + timedelta(
            hours=PRE_DEBIT_NOTICE_HOURS
        )
