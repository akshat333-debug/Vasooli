"""Vasooli CLI. Day 1 surface: seed, diagnose, verify-ledger."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from dotenv import load_dotenv

from .diagnose import diagnose_batch
from .ledger import Ledger
from .sim.seed import generate_batch


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

    v = sub.add_parser("verify-ledger", help="recompute the audit hash chain")
    v.add_argument("--db", default="vasooli.db")
    v.set_defaults(fn=_cmd_verify_ledger)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
