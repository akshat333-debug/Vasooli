"""Experiments that test whether this project's claim survives scrutiny.

Everything in the main report comes from a single seeded batch. That is enough
to demonstrate the mechanism and not nearly enough to defend the claim, because
the obvious question about any single seed is whether it was chosen. This module
exists to answer three attacks:

  sweep        "You picked the seed."
               Run many seeds, report the distribution, publish the losses.

  sensitivity  "Your assumptions are doing the work."
               Sweep the simulator's constants and find where the conclusion
               stops holding. Report the breaking point rather than a range that
               happens to look safe.

  ablation     "You assert eight rules matter. Prove it."
               Switch each rule off, re-run, and measure what it was worth.

All three run dictionary-only. Calling a language model 200 times to classify
error codes a dictionary already knows is spend with no decision attached, and
it would make a sweep take an hour instead of seconds.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from . import sim
from .decide import decide
from .diagnose import diagnose_batch
from .execute import run_batch
from .ledger import Ledger
from .report import compliance_split
from .sim.seed import BATCH_NOW, generate_batch

#: Experiments write to an in-memory ledger. They are measurements of the
#: engine, not runs of it, and should not pollute the audit trail with
#: hundreds of thousands of hypothetical decisions.
_MEM = ":memory:"


@dataclass
class ArmSummary:
    recovered_within_paise: int
    recovered_above_cap_paise: int
    attempts_spent: int
    wasted_attempts: int
    breaker_refusals: int = 0

    @property
    def paise_per_attempt(self) -> float:
        return (self.recovered_within_paise / self.attempts_spent
                if self.attempts_spent else 0.0)

    @property
    def gross_paise(self) -> int:
        """Everything recovered, envelope or not.

        The headline divides WITHIN-envelope recovery by attempts, which a
        reviewer can fairly call scoring the arm that declines 42% of the batch
        value on the remaining 58%. So the gross number is published beside it.
        Since the AFA fix it is identical for both arms — the world declines
        above-cap debits either way — which is the point: the two bases having
        collapsed onto each other is a stronger answer than an argument about
        which basis is fair.
        """
        return self.recovered_within_paise + self.recovered_above_cap_paise


@dataclass
class SeedResult:
    seed: int
    baseline: ArmSummary
    sequencer: ArmSummary

    @property
    def per_attempt_delta_pct(self) -> float:
        b = self.baseline.paise_per_attempt
        if b == 0:
            return 0.0
        return (self.sequencer.paise_per_attempt - b) / b * 100.0

    @property
    def sequencer_won(self) -> bool:
        return self.sequencer.paise_per_attempt > self.baseline.paise_per_attempt

    @property
    def gross_per_attempt_delta_pct(self) -> float:
        def pa(a: ArmSummary) -> float:
            return a.gross_paise / a.attempts_spent if a.attempts_spent else 0.0
        b = pa(self.baseline)
        return (pa(self.sequencer) - b) / b * 100.0 if b else 0.0

    @property
    def gross_won(self) -> bool:
        return self.gross_per_attempt_delta_pct > 0


def _summarise(res, records) -> ArmSummary:
    within, over = compliance_split(res, records)
    return ArmSummary(within, over, res.attempts_spent, res.wasted_attempts,
                      res.breaker_refusals)


def run_one(
    seed: int,
    n: int = 100,
    *,
    disabled_rules: frozenset[int] = frozenset(),
) -> SeedResult:
    """One batch, both arms, compliance-adjusted. No LLM, no disk ledger."""
    records = generate_batch(n, seed=seed)
    ledger = Ledger(_MEM)
    diagnoses, _ = diagnose_batch(records, use_llm=False)

    bl = run_batch(records, arm="baseline", now=BATCH_NOW, ledger=ledger,
                   diagnoses=diagnoses, draw_salt=str(seed))
    sq = run_batch(records, arm="sequencer", now=BATCH_NOW, ledger=ledger,
                   diagnoses=diagnoses, disabled_rules=disabled_rules,
                   draw_salt=str(seed))
    ledger.close()
    return SeedResult(seed, _summarise(bl, records), _summarise(sq, records))


# --------------------------------------------------------------------------
# 1. Seed sweep
# --------------------------------------------------------------------------

@dataclass
class SweepResult:
    results: list[SeedResult] = field(default_factory=list)

    @property
    def deltas(self) -> list[float]:
        return [r.per_attempt_delta_pct for r in self.results]

    @property
    def wins(self) -> int:
        return sum(1 for r in self.results if r.sequencer_won)

    @property
    def losses(self) -> list[SeedResult]:
        return [r for r in self.results if not r.sequencer_won]

    @property
    def gross_deltas(self) -> list[float]:
        return [r.gross_per_attempt_delta_pct for r in self.results]

    def summary(self) -> dict[str, Any]:
        d = sorted(self.deltas)
        n = len(d)
        return {
            "seeds": n,
            "wins": self.wins,
            "losses": n - self.wins,
            "win_rate": self.wins / n if n else 0.0,
            "median_delta_pct": statistics.median(d) if d else 0.0,
            "mean_delta_pct": statistics.fmean(d) if d else 0.0,
            "p05_delta_pct": d[int(0.05 * n)] if n else 0.0,
            "p95_delta_pct": d[min(int(0.95 * n), n - 1)] if n else 0.0,
            "worst_delta_pct": d[0] if d else 0.0,
            "best_delta_pct": d[-1] if d else 0.0,
            "losing_seeds": [r.seed for r in self.losses],
            # Published beside the headline so nobody has to take the
            # compliance-adjusted basis on trust.
            "gross_wins": sum(1 for r in self.results if r.gross_won),
            "gross_median_delta_pct": (statistics.median(self.gross_deltas)
                                       if self.results else 0.0),
            "gross_losing_seeds": [r.seed for r in self.results if not r.gross_won],
            # Every figure above is a RATE - rupees per attempt. A reader is
            # entitled to ask the cruder question: which arm simply collected
            # more money, budget ignored? The sequencer does not win that one
            # 40/40, and reporting only the rate would let a reviewer discover
            # it and conclude the ratio was hiding something. It is not: the
            # budget is the scarce resource and the rate is the right metric.
            # But the crude number is published beside it so nobody has to
            # find it themselves.
            "total_rupee_wins": sum(
                1 for r in self.results
                if r.sequencer.gross_paise > r.baseline.gross_paise),
            "total_rupee_ties": sum(
                1 for r in self.results
                if r.sequencer.gross_paise == r.baseline.gross_paise),
            "total_rupee_median_delta_paise": (
                statistics.median(r.sequencer.gross_paise - r.baseline.gross_paise
                                  for r in self.results) if self.results else 0),
            "total_rupee_worst_delta_paise": (
                min(r.sequencer.gross_paise - r.baseline.gross_paise
                    for r in self.results) if self.results else 0),
        }


def sweep(seeds: range | list[int], n: int = 100) -> SweepResult:
    return SweepResult([run_one(s, n) for s in seeds])


# --------------------------------------------------------------------------
# 2. Sensitivity to the simulator's assumptions
# --------------------------------------------------------------------------

#: The constants in sim/model.py that the conclusion could plausibly depend on.
#: IF_AFTER_REPLENISH and IF_BEFORE_REPLENISH matter most: the GAP between them
#: is the thesis. If a customer's odds barely improve after payday, then timing a
#: retry around payday cannot be worth anything, and the sequencer's advantage
#: should collapse. Finding that point is more useful than asserting robustness.
TUNABLE = [
    "IF_BEFORE_REPLENISH",
    "IF_AFTER_REPLENISH",
    "DOWNTIME_DURING",
    "DOWNTIME_AFTER",
    "TECHNICAL_FLAT",
    "PER_ATTEMPT_DECAY",
]


def sensitivity(
    constant: str,
    values: list[float],
    seeds: list[int],
    n: int = 100,
) -> list[dict[str, Any]]:
    """Re-run the sweep with one assumption overridden, across several values.

    `constant` is checked against TUNABLE rather than passed straight to
    setattr. Without the check a typo silently creates a NEW attribute on
    sim.model, the sweep runs against completely unchanged assumptions, and the
    result reads as "this constant does not matter" — the most misleading
    possible outcome for a sensitivity analysis.
    """
    if constant not in TUNABLE:
        raise ValueError(
            f"{constant!r} is not a tunable assumption. Expected one of: "
            f"{', '.join(TUNABLE)}"
        )
    model = sim.model
    original = getattr(model, constant)
    out: list[dict[str, Any]] = []
    try:
        for v in values:
            setattr(model, constant, v)
            s = sweep(seeds, n)
            row = s.summary()
            out.append({"constant": constant, "value": v,
                        "median_delta_pct": row["median_delta_pct"],
                        "win_rate": row["win_rate"]})
    finally:
        setattr(model, constant, original)
    return out


def find_breaking_point(
    seeds: list[int],
    n: int = 100,
    steps: int = 9,
) -> dict[str, Any]:
    """Narrow the replenishment gap until the sequencer's advantage disappears.

    The thesis says timing pays because a customer's odds improve after payday.
    Closing that gap should make the advantage vanish. If it does not, the
    measured advantage is coming from somewhere other than the stated mechanism,
    which would be worth knowing.
    """
    model = sim.model
    before0, after0 = model.IF_BEFORE_REPLENISH, model.IF_AFTER_REPLENISH
    mid = (before0 + after0) / 2
    rows: list[dict[str, Any]] = []
    try:
        for i in range(steps):
            # 1.0 -> the original gap, 0.0 -> no gap at all.
            frac = 1.0 - i / (steps - 1)
            model.IF_BEFORE_REPLENISH = mid - (mid - before0) * frac
            model.IF_AFTER_REPLENISH = mid + (after0 - mid) * frac
            gap = model.IF_AFTER_REPLENISH - model.IF_BEFORE_REPLENISH
            s = sweep(seeds, n).summary()
            rows.append({"gap": round(gap, 3),
                         "median_delta_pct": s["median_delta_pct"],
                         "win_rate": s["win_rate"]})
    finally:
        model.IF_BEFORE_REPLENISH, model.IF_AFTER_REPLENISH = before0, after0

    breaks_at = next((r["gap"] for r in rows if r["win_rate"] < 0.5), None)
    return {"rows": rows, "original_gap": round(after0 - before0, 3),
            "breaks_below_gap": breaks_at}


# --------------------------------------------------------------------------
# 3. Rule ablation
# --------------------------------------------------------------------------

RULE_NAMES = {
    1: "Retry budget exhausted",
    2: "Terminal failure class",
    3: "Mandate not active",
    4: "Failure unclassified",
    5: "Above the mandate's own cap",
    6: "Above the RBI standard cap",
    7: "Mandate expires before notice elapses",
}


def ablate(seeds: list[int], n: int = 100) -> list[dict[str, Any]]:
    """Turn each stopping rule off in turn and measure what it was worth.

    `above_cap_paise` is now ₹0 on every row including rule 6 off, because the
    world declines an above-cap unattended debit whichever arm presents it. The
    column that carries rule 6's cost is `breaker_refusals`: with the rule off,
    the decision layer no longer catches those records and the money-side
    breaker does, at the boundary. Defence in depth, measured.
    """
    base = [run_one(s, n) for s in seeds]
    base_attempts = statistics.fmean(r.sequencer.attempts_spent for r in base)
    base_wasted = statistics.fmean(r.sequencer.wasted_attempts for r in base)
    base_within = statistics.fmean(r.sequencer.recovered_within_paise for r in base)
    base_over = statistics.fmean(r.sequencer.recovered_above_cap_paise for r in base)
    base_ref = statistics.fmean(r.sequencer.breaker_refusals for r in base)

    rows = [{
        "rule": 0, "name": "all rules on",
        "attempts": round(base_attempts, 1), "wasted": round(base_wasted, 1),
        "extra_attempts": 0.0, "extra_wasted": 0.0,
        "recovered_within_paise": round(base_within),
        "above_cap_paise": round(base_over),
        "breaker_refusals": round(base_ref, 1),
    }]

    for rule, name in RULE_NAMES.items():
        off = [run_one(s, n, disabled_rules=frozenset({rule})) for s in seeds]
        a = statistics.fmean(r.sequencer.attempts_spent for r in off)
        w = statistics.fmean(r.sequencer.wasted_attempts for r in off)
        within = statistics.fmean(r.sequencer.recovered_within_paise for r in off)
        over = statistics.fmean(r.sequencer.recovered_above_cap_paise for r in off)
        ref = statistics.fmean(r.sequencer.breaker_refusals for r in off)
        rows.append({
            "rule": rule, "name": name,
            "attempts": round(a, 1), "wasted": round(w, 1),
            "extra_attempts": round(a - base_attempts, 1),
            "extra_wasted": round(w - base_wasted, 1),
            "recovered_within_paise": round(within),
            "above_cap_paise": round(over),
            "breaker_refusals": round(ref, 1),
        })
    return rows


# --------------------------------------------------------------------------
# 4. Calibration
# --------------------------------------------------------------------------

def calibration(seeds: list[int], n: int = 100, bins: int = 5) -> list[dict[str, Any]]:
    """Do the probabilities the engine reports actually mean anything?

    Every scheduled retry carries an `expected_success`. A system that reports
    confidences should be checked against outcomes: when it says 0.6, does it
    land about 0.6 of the time? Bucket the predictions and compare.

    Note the honest limit — the predictions and the outcomes come from the same
    assumed model, so agreement here shows the scheduler reads its own model
    correctly. It is an internal consistency check, not evidence about banks.
    """
    from .execute import _attempt

    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    for seed in seeds:
        records = generate_batch(n, seed=seed)
        diagnoses, _ = diagnose_batch(records, use_llm=False)
        by = {d.subscription_id: d for d in diagnoses}
        for rec in records:
            dec = decide(rec, by[rec.subscription_id].failure_class, BATCH_NOW)
            if dec.expected_success is None or dec.scheduled_at is None:
                continue
            ok = _attempt(rec, by[rec.subscription_id].failure_class,
                          dec.scheduled_at, rec.attempts_used, str(seed))
            idx = min(int(dec.expected_success * bins), bins - 1)
            buckets[idx].append((dec.expected_success, ok))

    out = []
    for i, b in enumerate(buckets):
        if not b:
            continue
        out.append({
            "bucket": f"{i / bins:.1f}-{(i + 1) / bins:.1f}",
            "n": len(b),
            "predicted": round(statistics.fmean(p for p, _ in b), 3),
            "observed": round(sum(1 for _, o in b if o) / len(b), 3),
        })
    return out


# --------------------------------------------------------------------------
# 5. Attribution: is the advantage timing, or refusal?
# --------------------------------------------------------------------------

def decompose(seeds: list[int], n: int = 100) -> dict[str, Any]:
    """Separate the value of WHEN a retry happens from the value of WHETHER.

    This exists because the sensitivity sweep produced an uncomfortable result:
    closing the replenishment gap to zero — removing every reason for timing to
    matter — barely dented the sequencer's advantage. If timing were doing the
    work, that should have collapsed it.

    Three arms over identical records and identical draws:

      A  baseline      naive schedule, no refusals
      B  refuse-only   the sequencer's stopping rules, the baseline's schedule
      C  full          stopping rules and optimal timing

    B - A is what refusing doomed attempts is worth.
    C - B is what timing them well is worth.

    Reporting this honestly matters more than the headline number. A project
    that claims an advantage should know which of its own mechanisms produced
    it, and saying "mostly the boring one" is worth more than implying both
    contributed equally.
    """
    rows = []
    for seed in seeds:
        records = generate_batch(n, seed=seed)
        ledger = Ledger(_MEM)
        diagnoses, _ = diagnose_batch(records, use_llm=False)

        a = run_batch(records, arm="baseline", now=BATCH_NOW, ledger=ledger,
                      diagnoses=diagnoses, draw_salt=str(seed))
        b = run_batch(records, arm="sequencer", now=BATCH_NOW, ledger=ledger,
                      diagnoses=diagnoses, timing="fixed", draw_salt=str(seed))
        c = run_batch(records, arm="sequencer", now=BATCH_NOW, ledger=ledger,
                      diagnoses=diagnoses, timing="optimal", draw_salt=str(seed))
        ledger.close()
        rows.append({k: _summarise(v, records) for k, v in
                     (("A_baseline", a), ("B_refuse_only", b), ("C_full", c))})

    def avg(key: str, attr: str) -> float:
        return statistics.fmean(getattr(r[key], attr) for r in rows)

    out: dict[str, Any] = {"seeds": len(seeds)}
    for key in ("A_baseline", "B_refuse_only", "C_full"):
        out[key] = {
            "recovered_within_paise": round(avg(key, "recovered_within_paise")),
            "attempts": round(avg(key, "attempts_spent"), 1),
            "per_attempt_paise": round(avg(key, "paise_per_attempt"), 1),
        }

    a_pa = out["A_baseline"]["per_attempt_paise"]
    b_pa = out["B_refuse_only"]["per_attempt_paise"]
    c_pa = out["C_full"]["per_attempt_paise"]
    total = c_pa - a_pa
    out["attribution"] = {
        "total_gain_per_attempt_paise": round(total, 1),
        "from_refusing_paise": round(b_pa - a_pa, 1),
        "from_timing_paise": round(c_pa - b_pa, 1),
        "refusing_share": round((b_pa - a_pa) / total, 3) if total else 0.0,
        "timing_share": round((c_pa - b_pa) / total, 3) if total else 0.0,
    }
    return out


# --------------------------------------------------------------------------
# 6. Does the result depend on the late-revocation hazard?
# --------------------------------------------------------------------------

def revocation_sensitivity(seeds: list[int], n: int = 100) -> dict[str, Any]:
    """Re-run the attribution with the late-revocation hazard removed entirely.

    The sequencer's pre-flight status call preserves attempts on mandates that
    died between the decision and the debit. A reviewer can reasonably ask
    whether the headline is really just that hazard. Setting the rate to zero
    answers it with a number instead of an assurance: whatever the gap becomes,
    it is published.
    """
    from . import execute

    original = execute.LATE_REVOCATION_RATE
    try:
        execute.LATE_REVOCATION_RATE = 0.0
        out = decompose(seeds, n)
    finally:
        execute.LATE_REVOCATION_RATE = original
    out["late_revocation_rate"] = 0.0
    return out
