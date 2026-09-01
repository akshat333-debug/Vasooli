"""Synthetic recovery-outcome model.

READ THIS BEFORE BELIEVING ANY NUMBER THIS PROJECT PRINTS.

These probabilities are ASSUMPTIONS. They are not measured, not fitted, and not
derived from Razorpay or any bank's data. No public dataset of Indian
subscription-mandate retry outcomes exists, and this project will not pretend
otherwise by scraping something of unclear provenance.

What that means for the results:

  * The ABSOLUTE rupee figure this project reports is NOT a claim about
    production performance. It is the output of the assumptions below.
  * The COMPARISON between the baseline arm and the sequencer arm IS meaningful,
    because both arms are scored by this identical model under an identical seed.
    The sequencer cannot win by being handed easier records.

Every assumption is a named constant so a reader can change one and re-run.

Shape of the assumptions, and why:

  INSUFFICIENT_FUNDS is the interesting case. It is not a fixed probability — it
  is a function of WHEN you retry relative to the customer's salary cycle. This
  is the entire thesis of the project: a retry on day 3 and a retry on day 8 cost
  the same scarce attempt and do not have the same expected value.

  BANK_DOWNTIME is time-dependent in a different way: outages resolve. Retrying
  into a live outage wastes an attempt; waiting out the window does not.

  TECHNICAL_ERROR is roughly time-independent — a transient gateway fault is
  about as likely to clear on the next attempt as the one after.

  Terminal classes are hard zero. Not "low" — zero. A revoked mandate cannot be
  debited. Any nonzero value here would let the baseline arm look better than
  reality allows, which would flatter this project's own thesis.
"""

from __future__ import annotations

from ..taxonomy import FailureClass

# --- INSUFFICIENT_FUNDS -------------------------------------------------------
#: Retrying while the account is still empty. Most of the baseline's wasted spend.
IF_BEFORE_REPLENISH = 0.18
#: Retrying on or shortly after the customer's typical replenishment day.
IF_AFTER_REPLENISH = 0.62
#: Days after replenishment before the balance is drawn down again.
IF_REPLENISH_WINDOW_DAYS = 4

# --- BANK_DOWNTIME ------------------------------------------------------------
#: Retrying inside the outage window.
DOWNTIME_DURING = 0.09
#: Retrying after the outage has plausibly cleared.
DOWNTIME_AFTER = 0.81
#: Assumed outage duration.
DOWNTIME_WINDOW_HOURS = 12

# --- TECHNICAL_ERROR ----------------------------------------------------------
TECHNICAL_FLAT = 0.55

# --- Global -------------------------------------------------------------------
#: Each successive attempt on the same invoice is modestly less likely to land —
#: the easy failures resolve first, leaving harder ones.
PER_ATTEMPT_DECAY = 0.88


def success_probability(
    failure_class: FailureClass,
    attempt_index: int,
    hours_since_failure: float,
    days_to_replenish: int,
) -> float:
    """Assumed P(retry succeeds). See module docstring — these are assumptions.

    Args:
        attempt_index: 0 for the first retry, 1 for the second, etc.
        hours_since_failure: elapsed time between the failure and this retry.
        days_to_replenish: days from the retry moment until the customer's
            typical replenishment day. Negative means replenishment has passed.
    """
    match failure_class:
        case FailureClass.INSUFFICIENT_FUNDS:
            replenished = -IF_REPLENISH_WINDOW_DAYS <= days_to_replenish <= 0
            base = IF_AFTER_REPLENISH if replenished else IF_BEFORE_REPLENISH
        case FailureClass.BANK_DOWNTIME:
            base = (
                DOWNTIME_AFTER
                if hours_since_failure >= DOWNTIME_WINDOW_HOURS
                else DOWNTIME_DURING
            )
        case FailureClass.TECHNICAL_ERROR:
            base = TECHNICAL_FLAT
        case _:
            # Terminal, or unclassified. A retry cannot succeed.
            return 0.0

    return base * (PER_ATTEMPT_DECAY**attempt_index)
