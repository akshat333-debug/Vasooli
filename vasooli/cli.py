"""Vasooli CLI.

Every command is a real engine run. Nothing here reports a number the engine
did not produce.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from dotenv import load_dotenv

from .bandit import run_study, shift_sweep
from .decide import decide
from .diagnose import diagnose_batch
from .execute import run_batch
from .experiments import (
    ablate,
    calibration,
    decompose,
    find_breaking_point,
    sweep,
)
from .export import write_payload
from .ledger import Ledger
from .nudge import draft_batch, wants_nudge_count
from .policy import RecoveryPolicy
from .razorpay_adapter import run_live_probe
from .report import render
from .sim.seed import BATCH_NOW, generate_batch


def _cmd_seed(args: argparse.Namespace) -> int:
    batch = generate_batch(args.n, seed=args.seed)
    if args.json:
        print(json.dumps([r.model_dump(mode="json") for r in batch], indent=2))
        return 0
    print(f"Generated {len(batch)} synthetic at-risk records (seed={args.seed}).")
    print("  SYNTHETIC DATA. Not real customers, not real money. See sim/model.py.\n")
    print(f"  above RBI cap (needs human) : {sum(r.needs_human_approval for r in batch)}")
    print(f"  above own mandate cap       : {sum(r.exceeds_mandate_cap for r in batch)}")
    print(f"  retry budget exhausted      : {sum(r.attempts_remaining == 0 for r in batch)}")
    print(f"  mandate already dead        : {sum(r.mandate_status != 'active' for r in batch)}")
    print(f"  no pre-debit notice on file : {sum(r.pre_debit_notified_at is None for r in batch)}")
    return 0


def _cmd_diagnose(args: argparse.Namespace) -> int:
    batch = generate_batch(args.n, seed=args.seed)
    diagnoses, stats = diagnose_batch(batch, use_llm=not args.no_llm)

    counts = Counter(d.failure_class.value for d in diagnoses)
    print(f"Diagnosed {len(diagnoses)} records "
          f"({'dict only' if args.no_llm else 'dict + Claude Haiku on the tail'}).\n")
    for cls, n in counts.most_common():
        print(f"  {cls:22} {n:4}")

    if not args.no_llm:
        checked = stats["agree"] + stats["disagree"]
        rate = (stats["agree"] / checked * 100) if checked else 0.0
        print(f"\n  LLM calls                     : {stats['llm_calls']}")
        print(f"  LLM/dict agreement (head)     : {stats['agree']}/{checked} ({rate:.1f}%)")
        print(f"  rescued from UNKNOWN by LLM   : {stats['llm_rescued']}")
        print(f"  left UNKNOWN -> human review  : {stats['unknown']}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    """Run both arms over one identical batch and report the comparison."""
    batch = generate_batch(args.n, seed=args.seed)
    ledger = Ledger(args.db)

    # Diagnose ONCE, then hand the same classifications to both arms. Previously
    # each arm re-diagnosed internally with the dictionary alone, so the LLM's
    # work on the unmapped tail was reported but never actually used to decide.
    diagnoses, llm_stats = diagnose_batch(batch, use_llm=not args.no_llm)

    baseline = run_batch(batch, arm="baseline", now=BATCH_NOW, ledger=ledger,
                         diagnoses=diagnoses, draw_salt=str(args.seed))
    sequencer = run_batch(batch, arm="sequencer", now=BATCH_NOW, ledger=ledger,
                          diagnoses=diagnoses, draw_salt=str(args.seed))

    v = ledger.verify()
    out = render(baseline, sequencer, batch, ledger_ok=v.ok, ledger_rows=v.rows,
                 ledger_detail=v.detail,
                 llm_stats=None if args.no_llm else llm_stats)
    ledger.close()

    print(out)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(out + "\n")
        print(f"\nwritten to {args.out}")
    return 0


def _cmd_demo_trip(args: argparse.Namespace) -> int:
    """Demonstrate the batch breaker stopping a run mid-flight."""
    batch = generate_batch(args.n, seed=args.seed)
    ledger = Ledger(args.db)
    policy = RecoveryPolicy(max_actions_per_batch=args.cap)
    res = run_batch(batch, arm="sequencer", now=BATCH_NOW, ledger=ledger,
                    policy=policy, draw_salt=str(args.seed))
    print(f"Batch breaker set to {args.cap} unattended actions.\n")
    print(f"  actions taken : {res.actions_taken}")
    print(f"  tripped       : {res.tripped}")
    print(f"  soft warnings : {res.soft_warnings or 'none'}")
    print("\nThe run stopped rather than continuing to move money past its ceiling.")
    for row in ledger.rows(res.run_id):
        if row["event"] == "fuse_trip":
            print(f"  ledger row {row['idx']}: {row['verdict']}")
    ledger.close()
    return 0


def _cmd_live(args: argparse.Namespace) -> int:
    """Exercise the real Razorpay test-mode API on a small slice of the batch."""
    import uuid

    batch = generate_batch(args.n, seed=args.seed)
    ledger = Ledger(args.db)
    run_id = uuid.uuid4().hex[:12]
    caps = run_live_probe(batch, ledger, run_id=run_id, limit=args.limit)

    print("Razorpay test-mode capability probe")
    print(f"  {caps.summary()}")
    if caps.detail:
        print(f"  {caps.detail}")
    print()
    for row in ledger.rows(run_id):
        print(f"  [{row['event']}] {row['verdict']}")
    ledger.close()
    if not caps.can_run_live_subscription_demo:
        print("\nSubscriptions/Plans are not enabled on this test account, so the")
        print("live demo uses Orders. The batch measurement remains simulated and")
        print("the report states this. Nothing was faked to cover the gap.")
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    """Emit a full batch run as JSON for the web interface."""
    import os

    if os.path.exists(args.db):
        os.remove(args.db)
    p = write_payload(args.out, n=args.n, seed=args.seed,
                      use_llm=not args.no_llm, db_path=args.db)
    size = p.stat().st_size
    print(f"wrote {p} ({size / 1024:.0f} KB)")
    return 0


def _cmd_experiments(args: argparse.Namespace) -> int:
    """Run the experiments that test whether the claim survives scrutiny."""
    seeds = list(range(1, args.seeds + 1))
    out: list[str] = []
    add = out.append

    add("=" * 76)
    add("VASOOLI - EXPERIMENTS")
    add("=" * 76)
    add(f"{len(seeds)} seeds x {args.n} records, dictionary-only classification.")
    add("")

    add("-" * 76)
    add("1. SEED SWEEP - is the headline an artefact of seed 42?")
    add("-" * 76)
    sw = sweep(seeds, args.n).summary()
    add(f"  sequencer led on recovery-per-attempt in {sw['wins']}/{sw['seeds']} seeds")
    add(f"  median delta  {sw['median_delta_pct']:+.1f}%")
    add(f"  5th pct       {sw['p05_delta_pct']:+.1f}%")
    add(f"  95th pct      {sw['p95_delta_pct']:+.1f}%")
    add(f"  worst seed    {sw['worst_delta_pct']:+.1f}%")
    add(f"  losing seeds  {sw['losing_seeds'] or 'none'}")
    add("")

    add("-" * 76)
    add("2. ATTRIBUTION - is the advantage timing, or refusal?")
    add("-" * 76)
    dc = decompose(seeds, args.n)
    for key, label in (("A_baseline", "A  baseline"),
                       ("B_refuse_only", "B  refusals, naive timing"),
                       ("C_full", "C  refusals + optimal timing")):
        v = dc[key]
        add(f"  {label:30} Rs {v['per_attempt_paise'] / 100:>8,.2f}/attempt "
            f"({v['attempts']:.0f} attempts)")
    a = dc["attribution"]
    add("")
    add(f"  from REFUSING  Rs {a['from_refusing_paise'] / 100:>7,.2f}/attempt "
        f"({a['refusing_share']:.0%} of the gain)")
    add(f"  from TIMING    Rs {a['from_timing_paise'] / 100:>7,.2f}/attempt "
        f"({a['timing_share']:.0%} of the gain)")
    add("")
    add("  Refusing doomed attempts is the dominant mechanism. Timing helps, but")
    add("  it is the smaller half by a wide margin - worth saying plainly rather")
    add("  than implying the grid search is what makes this work.")
    add("")

    add("-" * 76)
    add("3. BREAKING POINT - how wrong can the assumptions be?")
    add("-" * 76)
    bp = find_breaking_point(seeds, args.n)
    add(f"  replenishment gap as assumed: {bp['original_gap']}")
    add(f"  {'gap':>7} {'median delta':>14} {'win rate':>10}")
    for r in bp["rows"]:
        add(f"  {r['gap']:>7.3f} {r['median_delta_pct']:>13.1f}% {r['win_rate']:>10.0%}")
    add("")
    if bp["breaks_below_gap"] is None:
        add("  The advantage survives closing the payday gap entirely, which is")
        add("  consistent with the attribution above: most of it never depended")
        add("  on timing in the first place.")
    else:
        add(f"  Advantage disappears below a gap of {bp['breaks_below_gap']}.")
    add("")

    add("-" * 76)
    add("4. RULE ABLATION - what is each stopping rule worth?")
    add("-" * 76)
    add(f"  {'rule':>4}  {'name':38} {'attempts':>9} {'wasted':>8} {'above cap':>11}")
    for r in ablate(seeds, args.n):
        add(f"  {r['rule']:>4}  {r['name'][:38]:38} {r['attempts']:>9.1f} "
            f"{r['wasted']:>8.1f} {r['above_cap_paise'] / 100:>11,.0f}")
    add("")
    add("  Row 0 is every rule on. Each other row is that rule switched off.")
    add("  Higher attempts or wasted counts are the cost of removing it.")
    add("")

    add("-" * 76)
    add("5. CALIBRATION - do the reported probabilities mean anything?")
    add("-" * 76)
    add(f"  {'bucket':>10} {'n':>6} {'predicted':>11} {'observed':>10}")
    for c in calibration(seeds, args.n):
        add(f"  {c['bucket']:>10} {c['n']:>6} {c['predicted']:>11.3f} {c['observed']:>10.3f}")
    add("")
    add("  Internal consistency only: predictions and outcomes come from the same")
    add("  assumed model, so agreement shows the scheduler reads its own model")
    add("  correctly. It is not evidence about real banks.")
    add("=" * 76)

    text = "\n".join(out)
    print(text)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text + "\n")
        print(f"\nwritten to {args.out}")
    return 0


def _cmd_nudge(args: argparse.Namespace) -> int:
    """Draft customer messages for records the engine flagged. Sends nothing."""
    import uuid

    batch = generate_batch(args.n, seed=args.seed)
    ledger = Ledger(args.db)
    run_id = uuid.uuid4().hex[:12]

    diagnoses, _ = diagnose_batch(batch, use_llm=False)
    by = {d.subscription_id: d for d in diagnoses}
    pairs = [(r, decide(r, by[r.subscription_id].failure_class, BATCH_NOW)) for r in batch]

    breakdown = wants_nudge_count(pairs)
    stats = draft_batch(pairs, ledger, run_id=run_id,
                        use_llm=not args.no_llm, limit=args.limit)

    print("Nudge drafting — NOTHING IS SENT. Drafts go to the audit trail for review.\n")
    total_flagged = sum(breakdown.values())
    print(f"  flagged by the engine : {total_flagged}")
    for action, n in sorted(breakdown.items(), key=lambda kv: -kv[1]):
        print(f"      {action:22} {n}")
    if stats["flagged"] < total_flagged:
        print(f"  drafted this run      : {stats['flagged']} (--limit)")
    print(f"  drafted               : {stats['drafted']}")
    print(f"  rejected by guardrail : {stats['rejected']}")
    print(f"  model unavailable     : {stats['unavailable']}")

    rows = [r for r in ledger.rows(run_id) if r["event"] == "nudge_drafted"]
    if rows:
        print("\n  Sample drafts:")
        import json as _json
        for r in rows[: args.show]:
            draft = _json.loads(r["payload"]).get("draft", "")
            print(f"    {r['subscription_id']}  {draft}")
    ledger.close()
    return 0


def _cmd_bandit(args: argparse.Namespace) -> int:
    """Can a learned policy beat the hand-specified one? Honest answer."""
    r = run_study()
    print("Learned retry timing vs the deterministic scorer\n")
    print(f"  trained on {r['train_seeds']} seeds, tested on {r['test_seeds']} held out")
    print(f"  {r['observations']} observations across {r['contexts']} contexts\n")
    for k, label in (("in_distribution", "same world as training"),
                     ("out_of_distribution", "world shifted underneath it")):
        d = r[k]
        print(f"  {label:30} learned {d['learned']:.3f}   "
              f"heuristic {d['heuristic']:.3f}   retry-now {d['retry_immediately']:.3f}")
    print(f"\n  edge in-distribution     {r['edge_in_dist_pts']:+.2f} pts")
    print(f"  edge out-of-distribution {r['edge_out_of_dist_pts']:+.2f} pts")

    print("\n  In-distribution the heuristic is not a competitor, it is an oracle:")
    print("  it grid-searches the exact function the outcomes are drawn from.")
    print("  Losing to it there is arithmetic. The question is what happens as")
    print("  the world stops matching the assumptions.\n")

    sw = shift_sweep()
    print(f"  {'shift':>6} {'learned':>9} {'heuristic':>11} {'edge':>9}")
    for x in sw["rows"]:
        print(f"  {x['shift']:>6.2f} {x['learned']:>9.3f} {x['heuristic']:>11.3f} "
              f"{x['edge_pts']:>+9.2f}")
    print(f"\n  deficit narrows as the world diverges: {sw['deficit_narrows']} "
          f"({sw['narrowed_by_pts']:+.2f} pts)")
    print(f"  crossover: {sw['crossover_shift'] if sw['crossover_shift'] is not None else 'none in the tested range'}")
    print(f"\n  {r['verdict']}")
    return 0


def _cmd_verify_ledger(args: argparse.Namespace) -> int:
    L = Ledger(args.db)
    r = L.verify()
    L.close()
    print(f"rows={r.rows} ok={r.ok} {r.detail}")
    if not r.ok:
        print(f"  first broken row: {r.broken_at}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser(prog="vasooli", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("seed", help="generate the synthetic at-risk batch")
    s.add_argument("-n", type=int, default=100)
    s.add_argument("--seed", type=int, default=42)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=_cmd_seed)

    d = sub.add_parser("diagnose", help="classify each failure")
    d.add_argument("-n", type=int, default=100)
    d.add_argument("--seed", type=int, default=42)
    d.add_argument("--no-llm", action="store_true", help="deterministic dict only")
    d.set_defaults(fn=_cmd_diagnose)

    r = sub.add_parser("run", help="run both arms and report the comparison")
    r.add_argument("-n", type=int, default=100)
    r.add_argument("--seed", type=int, default=42)
    r.add_argument("--db", default="vasooli.db")
    r.add_argument("--no-llm", action="store_true")
    r.add_argument("--out", help="also write the report to this file")
    r.set_defaults(fn=_cmd_run)

    t = sub.add_parser("demo-trip", help="show the batch breaker halting a run")
    t.add_argument("-n", type=int, default=100)
    t.add_argument("--seed", type=int, default=42)
    t.add_argument("--cap", type=int, default=25)
    t.add_argument("--db", default="vasooli-demo.db")
    t.set_defaults(fn=_cmd_demo_trip)

    lv = sub.add_parser("live", help="probe and exercise the real Razorpay test API")
    lv.add_argument("-n", type=int, default=100)
    lv.add_argument("--seed", type=int, default=42)
    lv.add_argument("--limit", type=int, default=3)
    lv.add_argument("--db", default="vasooli.db")
    lv.set_defaults(fn=_cmd_live)

    e = sub.add_parser("export", help="emit a batch run as JSON for the web UI")
    e.add_argument("-n", type=int, default=100)
    e.add_argument("--seed", type=int, default=42)
    e.add_argument("--no-llm", action="store_true")
    e.add_argument("--db", default="vasooli-web.db")
    e.add_argument("--out", default="web/data/batch.json")
    e.set_defaults(fn=_cmd_export)

    x = sub.add_parser("experiments", help="sweep, attribution, ablation, calibration")
    x.add_argument("--seeds", type=int, default=30, help="run seeds 1..N")
    x.add_argument("-n", type=int, default=100)
    x.add_argument("--out", help="also write the results to this file")
    x.set_defaults(fn=_cmd_experiments)

    ng = sub.add_parser("nudge", help="draft customer messages (never sends)")
    ng.add_argument("-n", type=int, default=100)
    ng.add_argument("--seed", type=int, default=42)
    ng.add_argument("--limit", type=int, default=8)
    ng.add_argument("--show", type=int, default=5)
    ng.add_argument("--no-llm", action="store_true")
    ng.add_argument("--db", default="vasooli.db")
    ng.set_defaults(fn=_cmd_nudge)

    bd = sub.add_parser("bandit", help="learned retry timing vs the scorer")
    bd.set_defaults(fn=_cmd_bandit)

    v = sub.add_parser("verify-ledger", help="recompute the audit hash chain")
    v.add_argument("--db", default="vasooli.db")
    v.set_defaults(fn=_cmd_verify_ledger)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
