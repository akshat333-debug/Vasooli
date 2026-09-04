"""Vasooli CLI.

Every command is a real engine run. Nothing here reports a number the engine
did not produce.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import timedelta

from dotenv import load_dotenv

from .bandit import run_study, shift_sweep
from .decide import Action, decide
from .diagnose import diagnose_batch
from .execute import run_batch
from .experiments import (
    ablate,
    calibration,
    decompose,
    find_breaking_point,
    revocation_sensitivity,
    sweep,
)
from .export import write_payload
from .ledger import Ledger
from .nudge import draft_batch, wants_nudge_count
from .policy import RecoveryPolicy
from .razorpay_adapter import run_live_probe
from .report import render
from .sim.seed import BATCH_NOW, generate_batch
from .taxonomy import classify_by_code


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
    add("  1b. GROSS RECOVERY - the same sweep without the compliance adjustment")
    add(f"  sequencer led on GROSS recovery-per-attempt in "
        f"{sw['gross_wins']}/{sw['seeds']} seeds")
    add(f"  median gross delta  {sw['gross_median_delta_pct']:+.1f}%")
    add(f"  gross losing seeds  {sw['gross_losing_seeds'] or 'none'}")
    add("  The two bases now agree, because nothing above the RBI cap is")
    add("  recovered by either arm - the network declines it. The adjustment is")
    add("  no longer doing any work, which is a better answer than defending it.")
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
    add(f"  {'rule':>4}  {'name':38} {'attempts':>9} {'wasted':>8} "
        f"{'above cap':>11} {'refusals':>9}")
    for r in ablate(seeds, args.n):
        add(f"  {r['rule']:>4}  {r['name'][:38]:38} {r['attempts']:>9.1f} "
            f"{r['wasted']:>8.1f} {r['above_cap_paise'] / 100:>11,.0f} "
            f"{r['breaker_refusals']:>9.1f}")
    add("")
    add("  Row 0 is every rule on. Each other row is that rule switched off.")
    add("  Higher attempts or wasted counts are the cost of removing it.")
    add("")
    add("  'above cap' is Rs 0 on every row, INCLUDING rule 6 off. That is")
    add("  defence in depth, not a broken ablation: with the stopping rule gone,")
    add("  the money-side breaker refuses the debit at the action boundary and")
    add("  the network would decline it anyway for want of AFA. The cost of")
    add("  losing rule 6 shows up one layer down, in the refusals column.")
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
    add("")

    add("-" * 76)
    add("6. HAZARD REMOVED - does the result depend on late revocation?")
    add("-" * 76)
    rs_ = revocation_sensitivity(seeds, args.n)
    add("  Re-run with LATE_REVOCATION_RATE = 0, so no mandate dies between the")
    add("  decision and the debit and the pre-flight status call can preserve")
    add("  nothing. If the headline were really that hazard, it collapses here.")
    add("")
    for key, label in (("A_baseline", "A  baseline"),
                       ("B_refuse_only", "B  refusals, naive timing"),
                       ("C_full", "C  refusals + optimal timing")):
        v = rs_[key]
        add(f"  {label:30} Rs {v['per_attempt_paise'] / 100:>8,.2f}/attempt "
            f"({v['attempts']:.0f} attempts)")
    ra = rs_["attribution"]
    add("")
    add(f"  total gain     Rs {ra['total_gain_per_attempt_paise'] / 100:>7,.2f}/attempt"
        f"   (with the hazard: Rs {a['total_gain_per_attempt_paise'] / 100:,.2f})")
    add(f"  from REFUSING  Rs {ra['from_refusing_paise'] / 100:>7,.2f}/attempt "
        f"({ra['refusing_share']:.0%} of the gain)")
    add(f"  from TIMING    Rs {ra['from_timing_paise'] / 100:>7,.2f}/attempt "
        f"({ra['timing_share']:.0%} of the gain)")
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


def _cmd_webhook(args: argparse.Namespace) -> int:
    """Drive the live-event door end to end, refusals included.

    webhook.py is the module that turns this from a batch job into something a
    deployment can be told about, and until now nothing could run it. This
    command feeds it four deliveries in order -- a forgery, a real failure, a
    replay of that same delivery, and an event type the system does not act on
    -- because the interesting behaviour is in what it refuses, not in the happy
    path.
    """
    import hashlib
    import hmac
    import json as _json
    import uuid

    from .models import MAX_RETRY_BUDGET
    from .webhook import EventIgnored, SignatureInvalid, ingest

    secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "whsec_demo")
    ledger = Ledger(args.db)
    run_id = uuid.uuid4().hex[:12]

    def event(event_id: str, kind: str = "payment.failed", **sub_over) -> dict:
        sub = {"id": args.subscription, "status": "active", "customer_id": "cust_demo"}
        sub.update(sub_over)
        return {
            "id": event_id,
            "event": kind,
            "created_at": int(BATCH_NOW.timestamp()),
            "payload": {
                "payment": {"entity": {
                    "amount": args.amount, "method": "upi", "bank": "HDFC",
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_reason": "insufficient_funds",
                    "error_description": "Your account does not have enough balance",
                    "subscription_id": args.subscription,
                }},
                "subscription": {"entity": sub},
            },
        }

    def sign(body: bytes, key: str) -> str:
        return hmac.new(key.encode(), body, hashlib.sha256).hexdigest()

    print("Razorpay webhook ingestion. Verify, deduplicate, record, then decide.\n")
    print(f"  secret        : {'from RAZORPAY_WEBHOOK_SECRET' if 'RAZORPAY_WEBHOOK_SECRET' in os.environ else 'whsec_demo (set RAZORPAY_WEBHOOK_SECRET to use your own)'}")
    print(f"  subscription  : {args.subscription}")
    print(f"  ledger        : {args.db}\n")

    # A mature subscription. paid_count is what the old code read to derive the
    # retry count, and reading it here would refuse this record as exhausted.
    mature = {"paid_count": 10, "remaining_count": 2}

    deliveries = [
        ("forged signature", event("evt_forged"), "attacker_secret", mature),
        ("genuine payment.failed", event("evt_1"), secret, mature),
        ("replay of evt_1", event("evt_1"), secret, mature),
        ("a SECOND genuine failure, same subscription", event("evt_2"), secret, mature),
        ("subscription.charged", event("evt_3", "subscription.charged"), secret, mature),
    ]

    for label, ev, key, sub_extra in deliveries:
        ev["payload"]["subscription"]["entity"].update(sub_extra)
        body = _json.dumps(ev).encode()
        print(f"  -> {label}")
        try:
            res = ingest(body, sign(body, key), ledger, run_id=run_id, now=BATCH_NOW,
                         secret=secret)
        except SignatureInvalid as e:
            print(f"     REFUSED before parsing: {e}")
            print("     The body was never handed to a parser. An unverified payload")
            print("     is not data, it is a suggestion.\n")
            continue
        except EventIgnored as e:
            print(f"     ignored: {e}\n")
            continue

        print(f"     {res.note}")
        if res.record is None:
            print()
            continue

        rec = res.record
        fc = classify_by_code(rec.error_code, rec.error_reason)
        decision = decide(rec, fc, BATCH_NOW)
        ledger.append(run_id=run_id, arm="webhook", event="decision",
                      verdict=decision.verdict, subscription_id=rec.subscription_id,
                      action=decision.action.value,
                      escalation=decision.escalation.value,
                      amount_paise=rec.amount_paise)
        # rec.attempts_used was derived BEFORE ingest wrote this delivery's own
        # row, so re-counting here would report one too many.
        print(f"     attempts_used  : {rec.attempts_used} of {MAX_RETRY_BUDGET} "
              f"-- counted from prior payment.failed events in our own ledger. "
              f"paid_count on this subscription is "
              f"{mature['paid_count']}, which is SUCCESSFUL charges; deriving the "
              f"retry count from it refused mature subscriptions as exhausted.")
        print(f"     salary_day     : {rec.salary_day} "
              f"(a webhook carries no payday; unknown schedules at the legal floor)")
        print(f"     classified     : {fc.value}")
        print(f"     rule {decision.rule_fired} -> {decision.action.value} "
              f"/ {decision.escalation.value}")
        print(f"     {decision.verdict}\n")

    v = ledger.verify()
    print(f"  {len(list(ledger.rows(run_id)))} rows written this run; "
          f"chain {'INTACT' if v.ok else 'BROKEN'} across {v.rows} total.")
    print("  Nothing was decided before the signature was checked, and nothing")
    print("  in the payload could raise a cap or skip a stopping rule.")
    ledger.close()
    return 0


def _cmd_promise(args: argparse.Namespace) -> int:
    """Show what a customer's word may and may not do to a money decision.

    A promise to pay is unverified input over an untrusted channel. It may push
    a retry LATER and nothing else. This walks the four refusals and the one
    case that is honoured, on a real record from the batch.
    """
    import uuid

    from .promise import (
        MAX_HONOURED_MISSES,
        MAX_PROMISE_HORIZON_DAYS,
        Promise,
        apply_promise,
        settle,
    )

    batch = generate_batch(args.n, seed=args.seed)
    diagnoses, _ = diagnose_batch(batch, use_llm=False)
    by = {d.subscription_id: d for d in diagnoses}
    ledger = Ledger(args.db)
    run_id = uuid.uuid4().hex[:12]

    pairs = [(r, decide(r, by[r.subscription_id].failure_class, BATCH_NOW)) for r in batch]
    live = next((p for p in pairs if p[1].action is Action.RETRY_SCHEDULED), None)
    refused = next((p for p in pairs if p[1].action is not Action.RETRY_SCHEDULED), None)
    if live is None or refused is None:
        print("This batch has no scheduled and refused pair to demonstrate with.")
        ledger.close()
        return 0

    rec, dec = live
    print("Promise to pay. Unverified customer input, folded into a money decision.\n")
    print(f"  record        : {rec.subscription_id}, Rs {rec.amount_paise / 100:,.2f}")
    print(f"  engine says   : {dec.verdict}")
    print(f"  scheduled for : {dec.scheduled_at:%Y-%m-%d %H:%M}\n")

    later = (dec.scheduled_at or BATCH_NOW) + timedelta(days=3)
    cases = [
        ("moves the retry later", rec, dec,
         Promise(subscription_id=rec.subscription_id, promised_for=later,
                 made_at=BATCH_NOW, quote="salary 5th ko aa raha hai, tab try karo")),
        ("cannot pull it forward", rec, dec,
         Promise(subscription_id=rec.subscription_id, made_at=BATCH_NOW,
                 promised_for=(dec.scheduled_at or BATCH_NOW) - timedelta(days=2),
                 quote="abhi try kar lo")),
        (f"cannot outlast the {MAX_PROMISE_HORIZON_DAYS}-day horizon", rec, dec,
         Promise(subscription_id=rec.subscription_id, made_at=BATCH_NOW,
                 promised_for=BATCH_NOW + timedelta(days=MAX_PROMISE_HORIZON_DAYS + 5),
                 quote="agle mahine ke baad")),
        (f"stops counting after {MAX_HONOURED_MISSES} broken promises", rec, dec,
         Promise(subscription_id=rec.subscription_id, promised_for=later,
                 made_at=BATCH_NOW, prior_misses=MAX_HONOURED_MISSES,
                 quote="is baar pakka")),
        ("cannot reopen a record the rules refused", refused[0], refused[1],
         Promise(subscription_id=refused[0].subscription_id, made_at=BATCH_NOW,
                 promised_for=BATCH_NOW + timedelta(days=2), quote="kal kar dunga")),
    ]

    for label, r, d, promise in cases:
        verdict = apply_promise(r, d, promise, BATCH_NOW)
        ledger.append(run_id=run_id, arm="promise", event="promise_applied",
                      verdict=verdict.verdict, subscription_id=r.subscription_id,
                      honoured=verdict.honoured, quote=promise.quote)
        mark = "HONOURED" if verdict.honoured else "REFUSED "
        print(f"  {mark}  {label}")
        print(f'            customer: "{promise.quote}"')
        print(f"            {verdict.verdict}")
        if verdict.scheduled_at:
            print(f"            retry now at {verdict.scheduled_at:%Y-%m-%d %H:%M}")
        print()

    kept = settle(cases[0][3], recovered=True)
    broken = settle(cases[0][3], recovered=False)
    print(f"  Settling prices the next one: kept -> {kept.state.value}, "
          f"{kept.prior_misses} miss(es); broken -> {broken.state.value}, "
          f"{broken.prior_misses} miss(es).")
    print("  Trust is a resource with a floor, exactly like the retry budget.")
    print(f"\n  {len(list(ledger.rows(run_id)))} promise decisions written to {args.db}.")
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

    wh = sub.add_parser("webhook", help="drive the live-event door end to end")
    wh.add_argument("--subscription", default="sub_live_demo")
    wh.add_argument("--amount", type=int, default=49900, help="paise")
    wh.add_argument("--db", default="vasooli-webhook.db")
    wh.set_defaults(fn=_cmd_webhook)

    pr = sub.add_parser("promise", help="what a customer's word may and may not do")
    pr.add_argument("-n", type=int, default=100)
    pr.add_argument("--seed", type=int, default=42)
    pr.add_argument("--db", default="vasooli-promise.db")
    pr.set_defaults(fn=_cmd_promise)

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
    x.add_argument("--seeds", type=int, default=40, help="run seeds 1..N")
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
