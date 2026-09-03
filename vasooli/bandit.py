"""Learn when to retry, instead of being told.

WHAT THIS REPLACES

`decide.best_retry_time` grid-searches over probabilities a human wrote down in
`sim/model.py`. That is a heuristic wearing an optimiser's clothes: it finds the
best moment *according to assumptions nobody validated*. This module learns the
timing from observed outcomes instead.

THE TRAP, STATED BEFORE THE RESULTS

A learner trained against `sim/model.py` and then evaluated against
`sim/model.py` will rediscover `sim/model.py` and post a magnificent score. That
score would mean nothing. It would measure whether the bandit can fit a function
it was handed the answer key to, which is not a question anyone asked.

So evaluation here is deliberately hostile:

  in-distribution      train and test on the same assumed world. Reported, but
                       labelled as meaningless — it is a sanity check that the
                       learner learns at all, not evidence.

  out-of-distribution  train on one world, test on a PERTURBED one where the
                       constants have shifted. This is the only number worth
                       reading, because in reality the world will not match the
                       assumptions the learner grew up on.

If the bandit beats the heuristic in-distribution and loses out-of-distribution,
that is the honest finding and it gets reported as such. A learner that only
wins when the world matches its training set is a liability in production, where
the world never does.

WHERE IT SITS IN THE ENGINE

Nowhere, yet. This is an experiment, not a component: `decide.py` still uses the
deterministic scorer, because a sampled policy in a money path breaks the
reproducibility argument the whole project rests on. Promoting it would need a
frozen posterior and a way to explain a specific debit to a regulator, and
neither is built. See NEXT_STEPS.md.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from . import sim
from .decide import days_to_replenish, decide, earliest_legal_retry
from .diagnose import diagnose_batch
from .execute import _attempt
from .sim.seed import BATCH_NOW, generate_batch
from .taxonomy import RECOVERABLE, FailureClass

#: Candidate delays, in hours, measured from the earliest lawful moment. These
#: are the arms. Keeping them coarse and few is deliberate: a bandit with 200
#: arms and 3,000 observations learns nothing, and the real decision a merchant
#: makes is "today, in a few days, or after payday" rather than "in 37 hours".
ARMS_HOURS = (0, 24, 72, 168, 336)


def _replenish_bucket(days: int) -> str:
    """Coarse position in the customer's pay cycle."""
    if days >= -4:
        return "fresh"
    if days >= -14:
        return "mid"
    return "late"


def context_of(rec, failure_class: FailureClass, at) -> tuple:
    """The features the policy is allowed to condition on.

    Kept small on purpose. Every extra dimension splits the same finite
    observations into more buckets, and a bandit with one observation per bucket
    is just a random number generator with extra steps.
    """
    # `bank` was in this tuple and has been removed. With eight banks the
    # context space was 1,055 cells against ~2,200 observations — a median of
    # ONE observation per cell, 88% of cells under five. A posterior built on
    # one sample is a random number generator with extra steps, and the power
    # check said so before any accuracy number was looked at.
    return (
        failure_class.value,
        _replenish_bucket(days_to_replenish(at, rec.salary_day)),
        min(rec.attempts_used, 2),
    )


@dataclass
class ThompsonBandit:
    """Beta-Bernoulli Thompson sampling over a small set of timing arms.

    Thompson sampling rather than epsilon-greedy because the cost of exploring
    here is a real retry out of a budget of three. Sampling from the posterior
    explores in proportion to genuine uncertainty rather than at a fixed rate,
    which matters when every exploratory pull spends something scarce.
    """

    #: (context, arm) -> [successes + 1, failures + 1]
    posterior: dict[tuple, list[float]] = field(default_factory=dict)
    rng: random.Random = field(default_factory=lambda: random.Random(7))

    def _post(self, ctx: tuple, arm: int) -> list[float]:
        return self.posterior.setdefault((ctx, arm), [1.0, 1.0])

    def choose(self, ctx: tuple) -> int:
        """Sample each arm's posterior, take the best draw."""
        best, best_sample = ARMS_HOURS[0], -1.0
        for arm in ARMS_HOURS:
            a, b = self._post(ctx, arm)
            s = self.rng.betavariate(a, b)
            if s > best_sample:
                best, best_sample = arm, s
        return best

    def best(self, ctx: tuple) -> int:
        """Greedy arm — posterior mean, no sampling. Used at evaluation time."""
        def mean(arm: int) -> float:
            a, b = self._post(ctx, arm)
            return a / (a + b)

        return max(ARMS_HOURS, key=mean)

    def update(self, ctx: tuple, arm: int, success: bool) -> None:
        p = self._post(ctx, arm)
        p[0 if success else 1] += 1.0

    @property
    def observations(self) -> int:
        return int(sum(a + b - 2 for a, b in self.posterior.values()))


def _eligible(records, diagnoses):
    """Records the stopping rules would actually let us schedule.

    The bandit only ever chooses timing. It never overrides a refusal, so it is
    only trained and evaluated on records the engine would have retried anyway.
    """
    by = {d.subscription_id: d for d in diagnoses}
    out = []
    for rec in records:
        fc = by[rec.subscription_id].failure_class
        if fc not in RECOVERABLE:
            continue
        d = decide(rec, fc, BATCH_NOW)
        if d.scheduled_at is None:
            continue
        out.append((rec, fc))
    return out


def train(bandit: ThompsonBandit, seeds: list[int], n: int = 100) -> ThompsonBandit:
    for seed in seeds:
        records = generate_batch(n, seed=seed)
        diagnoses, _ = diagnose_batch(records, use_llm=False)
        for rec, fc in _eligible(records, diagnoses):
            floor = earliest_legal_retry(rec, BATCH_NOW)
            ctx = context_of(rec, fc, floor)
            arm = bandit.choose(ctx)
            at = floor + timedelta(hours=arm)
            if at > rec.mandate_valid_until:
                # Never learn from an attempt the engine would not have made.
                continue
            ok = _attempt(rec, fc, at, rec.attempts_used, str(seed))
            bandit.update(ctx, arm, ok)
    return bandit


def _evaluate(bandit: ThompsonBandit, seeds: list[int], n: int) -> dict[str, float]:
    """Success rate of the learned policy vs the hand-specified scorer."""
    learned = heuristic = immediate = 0
    total = 0
    for seed in seeds:
        records = generate_batch(n, seed=seed)
        diagnoses, _ = diagnose_batch(records, use_llm=False)
        by = {d.subscription_id: d for d in diagnoses}
        for rec, fc in _eligible(records, diagnoses):
            floor = earliest_legal_retry(rec, BATCH_NOW)
            ctx = context_of(rec, fc, floor)

            arm_at = floor + timedelta(hours=bandit.best(ctx))
            if arm_at > rec.mandate_valid_until:
                arm_at = floor
            heur_at = decide(rec, by[rec.subscription_id].failure_class,
                             BATCH_NOW).scheduled_at or floor

            total += 1
            learned += _attempt(rec, fc, arm_at, rec.attempts_used, str(seed))
            heuristic += _attempt(rec, fc, heur_at, rec.attempts_used, str(seed))
            immediate += _attempt(rec, fc, floor, rec.attempts_used, str(seed))

    if not total:
        return {"n": 0}
    return {
        "n": total,
        "learned": learned / total,
        "heuristic": heuristic / total,
        "retry_immediately": immediate / total,
    }


#: How the world is perturbed for out-of-distribution evaluation. These shift
#: the assumptions the learner grew up on, which is the only way to find out
#: whether it learned something about retries or merely memorised sim/model.py.
PERTURBATION = {
    "IF_BEFORE_REPLENISH": 0.30,   # from 0.18 — low balance hurts less
    "IF_AFTER_REPLENISH": 0.45,    # from 0.62 — payday helps less
    "DOWNTIME_WINDOW_HOURS": 36,   # from 12   — outages last much longer
    "TECHNICAL_FLAT": 0.35,        # from 0.55
}


def run_study(
    train_seeds: list[int] | None = None,
    test_seeds: list[int] | None = None,
    n: int = 100,
) -> dict[str, Any]:
    """Train once, evaluate twice: same world, then a shifted one."""
    train_seeds = train_seeds or list(range(1, 41))
    test_seeds = test_seeds or list(range(200, 221))

    bandit = train(ThompsonBandit(), train_seeds, n)
    in_dist = _evaluate(bandit, test_seeds, n)

    model = sim.model
    saved = {k: getattr(model, k) for k in PERTURBATION}
    try:
        for k, v in PERTURBATION.items():
            setattr(model, k, v)
        out_dist = _evaluate(bandit, test_seeds, n)
    finally:
        for k, v in saved.items():
            setattr(model, k, v)

    def edge(d: dict[str, float]) -> float:
        if not d.get("n"):
            return 0.0
        return (d["learned"] - d["heuristic"]) * 100

    return {
        "train_seeds": len(train_seeds),
        "test_seeds": len(test_seeds),
        "observations": bandit.observations,
        "contexts": len({c for c, _ in bandit.posterior}),
        "in_distribution": in_dist,
        "out_of_distribution": out_dist,
        "edge_in_dist_pts": round(edge(in_dist), 2),
        "edge_out_of_dist_pts": round(edge(out_dist), 2),
        "verdict": _verdict(edge(in_dist), edge(out_dist)),
    }


def _verdict(edge_in: float, edge_out: float) -> str:
    if edge_in < -1.0 and edge_out < -1.0:
        return ("The learned policy loses to the hand-specified scorer in both "
                "worlds. Nothing here recommends replacing a deterministic, "
                "explainable rule with a sampled one.")
    if edge_out > 1.0:
        return ("The learned policy beats the hand-specified scorer even after the "
                "world was shifted underneath it. That is the result worth having.")
    if edge_out > -1.0:
        return ("The learned policy matches the hand-specified scorer out of "
                "distribution. It learned the same thing the heuristic already "
                "encodes, at the cost of non-determinism — which is a reason to "
                "keep the heuristic, not to replace it.")
    return ("The learned policy beats the heuristic only when the world matches "
            "its training set, and loses once it shifts. That is overfitting to "
            "the simulator, and it is why this is not wired into decide.py.")


def observations_per_context(bandit: ThompsonBandit) -> dict[str, float]:
    """Are there enough observations per bucket for any of this to mean anything?"""
    counts = [a + b - 2 for a, b in bandit.posterior.values()]
    if not counts:
        return {}
    return {
        "cells": len(counts),
        "median_obs_per_cell": statistics.median(counts),
        "cells_with_fewer_than_5": sum(1 for c in counts if c < 5),
        "share_underpowered": round(
            sum(1 for c in counts if c < 5) / len(counts), 3),
    }


def shift_sweep(
    train_seeds: list[int] | None = None,
    test_seeds: list[int] | None = None,
    n: int = 100,
    steps: int = 6,
) -> dict[str, Any]:
    """Widen the gap between the assumed world and the real one, and watch.

    In-distribution the heuristic is not a competitor, it is an ORACLE: it grid-
    searches the very probability function the outcomes are drawn from. Losing to
    it there is arithmetic, not evidence, and any learner that appeared to beat
    it would be a bug.

    The question worth asking is what happens as the world diverges from the
    assumptions the heuristic trusts. If the learner's deficit shrinks as the
    shift grows, it is learning something the assumptions do not contain, and
    there is a crossover point where learning starts to pay. If the deficit is
    flat, it is not, and the heuristic should stay.

    This reports the whole curve, including the part where the learner loses.
    """
    train_seeds = train_seeds or list(range(1, 41))
    test_seeds = test_seeds or list(range(200, 221))
    bandit = train(ThompsonBandit(), train_seeds, n)

    model = sim.model
    saved = {k: getattr(model, k) for k in PERTURBATION}
    rows: list[dict[str, Any]] = []
    try:
        for i in range(steps):
            frac = i / (steps - 1)
            for k, target in PERTURBATION.items():
                setattr(model, k, saved[k] + (target - saved[k]) * frac)
            ev = _evaluate(bandit, test_seeds, n)
            rows.append({
                "shift": round(frac, 2),
                "learned": round(ev["learned"], 3),
                "heuristic": round(ev["heuristic"], 3),
                "edge_pts": round((ev["learned"] - ev["heuristic"]) * 100, 2),
            })
    finally:
        for k, v in saved.items():
            setattr(model, k, v)

    crossover = next((r["shift"] for r in rows if r["edge_pts"] > 0), None)
    first, last = rows[0]["edge_pts"], rows[-1]["edge_pts"]
    return {
        "rows": rows,
        "crossover_shift": crossover,
        "deficit_narrows": last > first,
        "narrowed_by_pts": round(last - first, 2),
    }
