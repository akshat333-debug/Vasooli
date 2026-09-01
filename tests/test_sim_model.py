"""The outcome model is an assumption. These tests pin its shape, not its truth."""

from vasooli.sim.model import success_probability as p
from vasooli.taxonomy import TERMINAL, FailureClass


def test_terminal_classes_have_exactly_zero_probability():
    # Not "low" — zero. Any nonzero value here would flatter the baseline arm
    # and therefore flatter this project's own thesis.
    for fc in TERMINAL:
        assert p(fc, 0, 48, 0) == 0.0


def test_unknown_is_never_retried_successfully():
    assert p(FailureClass.UNKNOWN, 0, 48, 0) == 0.0


def test_insufficient_funds_improves_after_replenishment():
    before = p(FailureClass.INSUFFICIENT_FUNDS, 0, 24, days_to_replenish=9)
    after = p(FailureClass.INSUFFICIENT_FUNDS, 0, 24, days_to_replenish=-1)
    assert after > before, "timing must matter, or the sequencer has nothing to exploit"


def test_bank_downtime_improves_after_the_outage_window():
    during = p(FailureClass.BANK_DOWNTIME, 0, 2, 5)
    after = p(FailureClass.BANK_DOWNTIME, 0, 20, 5)
    assert after > during


def test_later_attempts_decay():
    a0 = p(FailureClass.TECHNICAL_ERROR, 0, 5, 5)
    a2 = p(FailureClass.TECHNICAL_ERROR, 2, 5, 5)
    assert a2 < a0


def test_probabilities_stay_in_range():
    for fc in FailureClass:
        for att in range(4):
            for h in (0, 5, 20, 100):
                for d in (-5, 0, 3, 12):
                    assert 0.0 <= p(fc, att, h, d) <= 1.0
