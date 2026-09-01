"""Vasooli CLI. Day 1 surface: seed, diagnose, verify-ledger."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from dotenv import load_dotenv

from .diagnose import diagnose_batch
from .execute import run_batch
from .ledger import Ledger
from .policy import RecoveryPolicy
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

    _, llm_stats = diagnose_batch(batch, use_llm=not args.no_llm)

    baseline = run_batch(batch, arm="baseline", now=BATCH_NOW, ledger=ledger)
    sequencer = run_batch(batch, arm="sequencer", now=BATCH_NOW, ledger=ledger)

    v = ledger.verify()
    out = render(baseline, sequencer, batch, ledger_ok=v.ok, ledger_rows=v.rows,
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
    res = run_batch(batch, arm="sequencer", now=BATCH_NOW, ledger=ledger, policy=policy)
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

    v = sub.add_parser("verify-ledger", help="recompute the audit hash chain")
    v.add_argument("--db", default="vasooli.db")
    v.set_defaults(fn=_cmd_verify_ledger)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
