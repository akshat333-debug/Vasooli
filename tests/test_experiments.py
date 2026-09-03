"""The experiments are what make the headline defensible, so they get tests too.

An experiment that silently stops measuring what it claims to measure is worse
than no experiment, because it produces a number people trust.
"""

import pytest

from vasooli.execute import _draw
from vasooli.experiments import (
    RULE_NAMES,
    ablate,
    calibration,
    decompose,
    find_breaking_point,
    run_one,
    sweep,
)

SEEDS = [1, 2, 3, 4, 5]


# --- BUG 14: every seed in a sweep shared identical luck ----------------------

def test_draws_differ_across_seeds():
    # generate_batch reuses subscription ids for every seed. Without a salt the
    # whole sweep drew the same 300 luck values, so "40 seeds" was far less
    # independent than it sounded.
    assert _draw("sub_SYN0000", 0, "1") != _draw("sub_SYN0000", 0, "2")


def test_draws_are_stable_for_a_given_seed():
    assert _draw("sub_SYN0000", 0, "7") == _draw("sub_SYN0000", 0, "7")


def test_both_arms_of_a_comparison_share_the_salt():
    # The fairness property must survive salting: within one seed, both arms
    # test the same draw. If this breaks, every comparison is meaningless.
    a, b = run_one(3), run_one(3)
    assert a.baseline.attempts_spent == b.baseline.attempts_spent
    assert a.sequencer.recovered_within_paise == b.sequencer.recovered_within_paise


# --- sweep --------------------------------------------------------------------

def test_sweep_reports_every_seed_and_names_its_losses():
    s = sweep(SEEDS)
    r = s.summary()
    assert r["seeds"] == len(SEEDS)
    assert r["wins"] + r["losses"] == len(SEEDS)
    # Losing seeds must be enumerable, not just counted — a sweep that hides
    # which seeds lost is not evidence.
    assert isinstance(r["losing_seeds"], list)
    assert len(r["losing_seeds"]) == r["losses"]


def test_sweep_is_deterministic():
    assert sweep(SEEDS).summary() == sweep(SEEDS).summary()


# --- attribution ---------------------------------------------------------------

def test_attribution_shares_sum_to_one():
    d = decompose(SEEDS)
    a = d["attribution"]
    assert abs(a["refusing_share"] + a["timing_share"] - 1.0) < 0.01


def test_refusing_arm_spends_fewer_attempts_than_the_baseline():
    # B keeps the baseline's schedule and adds only the stopping rules, so any
    # attempt reduction it shows is attributable to refusal alone.
    d = decompose(SEEDS)
    assert d["B_refuse_only"]["attempts"] < d["A_baseline"]["attempts"]


def test_optimal_timing_is_not_worse_than_naive_timing():
    d = decompose(SEEDS)
    assert d["C_full"]["per_attempt_paise"] >= d["B_refuse_only"]["per_attempt_paise"]


# --- sensitivity ----------------------------------------------------------------

def test_breaking_point_restores_the_constants_it_mutates():
    from vasooli.sim import model
    before = (model.IF_BEFORE_REPLENISH, model.IF_AFTER_REPLENISH)
    find_breaking_point([1, 2], n=30, steps=3)
    assert (model.IF_BEFORE_REPLENISH, model.IF_AFTER_REPLENISH) == before, (
        "a sensitivity sweep leaked a mutated assumption into the live model"
    )


def test_breaking_point_narrows_the_gap_monotonically():
    rows = find_breaking_point([1, 2], n=30, steps=4)["rows"]
    gaps = [r["gap"] for r in rows]
    assert gaps == sorted(gaps, reverse=True)
    assert gaps[-1] == pytest.approx(0.0, abs=1e-9)


# --- ablation -------------------------------------------------------------------

def test_ablation_covers_every_stopping_rule():
    rows = ablate([1, 2], n=40)
    assert {r["rule"] for r in rows} == {0, *RULE_NAMES}


def test_disabling_a_rule_never_reduces_attempts():
    # Every rule exists to stop an attempt. Removing one can only cost attempts
    # or leave them unchanged; a rule whose removal SAVED attempts would mean
    # the rule was causing spend rather than preventing it.
    rows = ablate([1, 2, 3], n=60)
    base = next(r for r in rows if r["rule"] == 0)["attempts"]
    for r in rows:
        if r["rule"]:
            assert r["attempts"] >= base - 0.01, f"rule {r['rule']} reduced attempts"


def test_only_the_rbi_rule_produces_above_cap_debits_when_removed():
    rows = ablate([1, 2, 3], n=60)
    for r in rows:
        if r["rule"] == 6:
            assert r["above_cap_paise"] > 0, "rule 6 removal should breach the cap"
        else:
            assert r["above_cap_paise"] == 0, (
                f"rule {r['rule']} removal produced above-cap debits"
            )


# --- calibration ------------------------------------------------------------------

def test_calibration_buckets_are_well_formed():
    rows = calibration(SEEDS, n=60)
    assert rows
    for r in rows:
        assert r["n"] > 0
        assert 0.0 <= r["predicted"] <= 1.0
        assert 0.0 <= r["observed"] <= 1.0
