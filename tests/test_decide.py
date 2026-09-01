"""Every stopping rule gets a test that fails if the rule is removed.

These are the tests that matter most in this project. A stopping rule that is
silently deleted does not crash anything — it just starts spending retries on
debits that cannot succeed, and the only symptom is a slightly worse number in a
report nobody re-derives.
"""

from datetime import datetime, timedelta

import pytest

from vasooli.decide import Action, days_to_replenish, decide, earliest_legal_retry
from vasooli.models import (
    PRE_DEBIT_NOTICE_HOURS,
    RBI_STANDARD_CAP_PAISE,
    AtRiskRecord,
    MandateStatus,
    Method,
    SubscriptionStatus,
)
from vasooli.taxonomy import FailureClass

NOW = datetime(2026, 9, 2, 9, 0)


def rec(**kw) -> AtRiskRecord:
    base = dict(
        subscription_id="sub_T", customer_id="cust_T", mandate_id="tkn_T",
        invoice_id="inv_T", method=Method.UPI_AUTOPAY, bank="HDFC",
        amount_paise=49900, mandate_status=MandateStatus.ACTIVE,
        mandate_max_amount_paise=99800,
        mandate_valid_until=NOW + timedelta(days=200),
        subscription_status=SubscriptionStatus.ACTIVE, attempts_used=0,
        error_code="BAD_REQUEST_ERROR", error_reason="insufficient_funds",
        error_description="low balance", last_attempt_at=NOW - timedelta(hours=6),
        pre_debit_notified_at=NOW - timedelta(hours=48), salary_day=1,
    )
    base.update(kw)
    return AtRiskRecord(**base)


# --- rule 1: exhausted budget -------------------------------------------------

def test_exhausted_budget_stops():
    d = decide(rec(attempts_used=3), FailureClass.INSUFFICIENT_FUNDS, NOW)
    assert d.action is Action.STOP_EXHAUSTED
    assert d.scheduled_at is None


# --- rule 2: terminal failure class ------------------------------------------

@pytest.mark.parametrize("fc", [FailureClass.MANDATE_REVOKED, FailureClass.MANDATE_EXPIRED,
                                FailureClass.MANDATE_PAUSED, FailureClass.LIMIT_EXCEEDED])
def test_terminal_class_stops_and_preserves_attempts(fc):
    d = decide(rec(attempts_used=0), fc, NOW)
    assert d.action is Action.STOP_TERMINAL
    assert "preserved" in d.verdict


# --- rule 3: dead mandate under a live-looking failure ------------------------

@pytest.mark.parametrize("status", [MandateStatus.REVOKED, MandateStatus.EXPIRED,
                                    MandateStatus.PAUSED])
def test_dead_mandate_stops_even_when_the_failure_looks_recoverable(status):
    # The trap. The error text says "insufficient funds", which is recoverable.
    # The mandate says the debit can never be presented.
    d = decide(rec(mandate_status=status), FailureClass.INSUFFICIENT_FUNDS, NOW)
    assert d.action is Action.STOP_TERMINAL
    assert "dead mandate" in d.verdict


# --- rule 4: unclassified -----------------------------------------------------

def test_unknown_class_goes_to_a_human_not_a_retry():
    d = decide(rec(), FailureClass.UNKNOWN, NOW)
    assert d.action is Action.HUMAN_REVIEW


# --- rule 5: over the mandate's own cap --------------------------------------

def test_amount_above_mandate_cap_goes_to_a_human():
    d = decide(rec(amount_paise=50000, mandate_max_amount_paise=30000),
               FailureClass.INSUFFICIENT_FUNDS, NOW)
    assert d.action is Action.HUMAN_REVIEW
    assert "mandate cap" in d.verdict


# --- rule 6: over the RBI standard cap ---------------------------------------

def test_amount_above_rbi_cap_goes_to_a_human():
    over = RBI_STANDARD_CAP_PAISE + 1
    d = decide(rec(amount_paise=over, mandate_max_amount_paise=over * 2),
               FailureClass.INSUFFICIENT_FUNDS, NOW)
    assert d.action is Action.HUMAN_REVIEW
    assert "RBI" in d.verdict


def test_amount_exactly_at_the_rbi_cap_is_still_automatable():
    # Boundary: the rule is "above the cap", not "at" it.
    d = decide(rec(amount_paise=RBI_STANDARD_CAP_PAISE,
                   mandate_max_amount_paise=RBI_STANDARD_CAP_PAISE * 2),
               FailureClass.INSUFFICIENT_FUNDS, NOW)
    assert d.action is Action.RETRY_SCHEDULED


# --- rule ordering ------------------------------------------------------------

def test_exhaustion_is_checked_before_everything_else():
    # A record that is both exhausted and over the cap must report exhaustion:
    # it is the cheaper, more certain refusal.
    d = decide(rec(attempts_used=3, amount_paise=RBI_STANDARD_CAP_PAISE + 1),
               FailureClass.UNKNOWN, NOW)
    assert d.action is Action.STOP_EXHAUSTED


# --- the legal floor ----------------------------------------------------------

def test_missing_pre_debit_notice_delays_the_retry_by_the_notice_period():
    r = rec(pre_debit_notified_at=None)
    assert earliest_legal_retry(r, NOW) == NOW + timedelta(hours=PRE_DEBIT_NOTICE_HOURS)


def test_stale_notice_does_not_delay_the_retry():
    r = rec(pre_debit_notified_at=NOW - timedelta(days=10))
    assert earliest_legal_retry(r, NOW) == NOW


def test_scheduled_retry_never_precedes_the_legal_floor():
    r = rec(pre_debit_notified_at=None)
    d = decide(r, FailureClass.INSUFFICIENT_FUNDS, NOW)
    assert d.action is Action.RETRY_SCHEDULED
    assert d.scheduled_at >= earliest_legal_retry(r, NOW)


# --- timing -------------------------------------------------------------------

def test_replenishment_arithmetic():
    assert days_to_replenish(datetime(2026, 9, 5, 9, 0), salary_day=1) == -4
    assert days_to_replenish(datetime(2026, 9, 1, 9, 0), salary_day=1) == 0
    # Salary day falls in the previous month.
    assert days_to_replenish(datetime(2026, 9, 2, 9, 0), salary_day=28) == -5


def test_insufficient_funds_retry_targets_the_replenishment_window():
    # The thesis in one test: the scheduler must not fire immediately into an
    # empty account when waiting is available and better.
    r = rec(salary_day=15, pre_debit_notified_at=NOW - timedelta(hours=48))
    d = decide(r, FailureClass.INSUFFICIENT_FUNDS, NOW)
    assert d.action is Action.RETRY_SCHEDULED
    assert d.expected_success > 0.5, "scheduler ignored the replenishment cycle"


def test_every_decision_carries_a_verdict():
    for fc in FailureClass:
        assert decide(rec(), fc, NOW).verdict.strip()
