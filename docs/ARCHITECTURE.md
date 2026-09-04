# Architecture

This is the standalone architecture reference. `README.md` covers the same
ground in more depth (§6 Architecture, §7 Module reference, §8 The decision
engine in full, §9 How the two arms are made comparable) — this file exists
so the pipeline and the module boundaries are readable without opening the
whole README, and so nobody has to guess where the design notes live.

## The pipeline

```
                    100 synthetic at-risk records (seeded, reproducible)
                     or a live Razorpay webhook (webhook.py, same record type)
                                        │
                                        ▼
  ┌──────────── DETECT ──────────────────────────────────────────────┐
  │  rules only. no model.                                            │
  │  invoice issued + charge failed + subscription not halted         │
  └────────────────────────────┬──────────────────────────────────────┘
                               ▼
  ┌──────────── DIAGNOSE (diagnose.py) ───────────────────────────────┐
  │  error_code + reason  ──►  dict  ──► authoritative where it knows  │
  │  free-text description ──►  Claude Haiku  ──► the unmapped tail    │
  │  neither is confident  ──►  UNKNOWN  ──► human review              │
  │  guarded by RunFuse (max_steps, max_llm_errors)                    │
  └────────────────────────────┬──────────────────────────────────────┘
                               ▼
  ┌──────────── DECIDE (decide.py) ───────────────────────────────────┐
  │  ** NO LANGUAGE MODEL RUNS HERE **                                 │
  │  7 stopping rules in order, then a deterministic grid search over  │
  │  the legal retry window for the moment of highest expected success │
  │  emits: action, rule_fired, escalation, scheduled_at, verdict      │
  └────────────────────────────┬──────────────────────────────────────┘
                               ▼
  ┌──────────── EXECUTE (execute.py) ─────────────────────────────────┐
  │  RecoveryFuse.check() at every action boundary                     │
  │  pre-flight mandate re-check: state may have changed since decide  │
  │  physical constraints bind BOTH arms before any probability        │
  └────────────────────────────┬──────────────────────────────────────┘
                               ▼
  ┌──────────── LEDGER (ledger.py) ───────────────────────────────────┐
  │  HMAC-SHA256 hash chain in SQLite. every decision + its verdict.   │
  │  `vasooli verify-ledger` locates tampering by row index.           │
  │  the web ledger page recomputes this chain in the browser.        │
  └────────────────────────────┬──────────────────────────────────────┘
                               ▼
         report.py  ──►  BATCH_REPORT.txt   (single-basis headline + escalation queue)
         export.py  ──►  web/data/batch.json  ──►  Next.js static viewer
```

**Side paths.** `promise.py` folds a customer's stated promise-to-pay into an
existing decision — it can only push a retry *later*, never earlier, never
reopen a stopped record. `nudge.py` drafts Hinglish customer messages under a
guardrail and never sends them. `experiments.py` and `bandit.py` measure the
engine across many seeds rather than running it once. `razorpay_adapter.py`
talks to the real Razorpay test-mode API. `logging.py` emits operational JSON,
silent by default.

## Why this shape

Four things decided the pipeline's structure, in order of how load-bearing
they are:

1. **The retry budget is a scarce resource, not a rate.** Razorpay halts a
   subscription after 3 failed attempts. That makes an attempt something to
   *allocate*, not something to spend freely — so DETECT and DECIDE exist to
   refuse work before EXECUTE ever touches money.
2. **No language model decides whether to move money.** DIAGNOSE reads a
   bank's free text (a genuine language problem); DECIDE is 7 deterministic
   stopping rules plus a grid search, reproducible byte-for-byte on a rerun.
   Auditability and regulator-facing reproducibility require this split.
3. **Both arms (baseline vs. sequencer) must live in the same physical
   world.** EXECUTE applies mandate status, cap checks and expiry to both
   arms identically — the comparison is only meaningful if a fact about the
   world (a revoked mandate) can't be seen by one arm and not the other. See
   `README.md` §9 for the full argument and the regression test that
   enforces it (`_attempt()`'s source contains no `arm` branch).
4. **Every decision is written before it is acted on, and the record is
   checkable, not just claimed.** LEDGER is append-only and HMAC-chained; the
   web interface recomputes that chain client-side rather than trusting a
   stored `verified: true` flag, and lets a reader tamper with a row to watch
   the break propagate.

## Module map

| Module | Role |
|---|---|
| `models.py` | The record schema (`AtRiskRecord`) and domain constants (retry budget, RBI cap, notice window). |
| `taxonomy.py` | The canonical `FailureClass` enum and the deterministic `CODE_MAP` dictionary. |
| `sim/seed.py`, `sim/model.py` | Synthetic batch generator and the named, documented success-probability assumptions it's scored against. |
| `diagnose.py` | Dictionary-first, LLM-on-the-unmapped-tail classification, wrapped in a RunFuse breaker. |
| `decide.py` | The 7 stopping rules + scheduling rule. No model runs here. |
| `policy.py` | `RecoveryFuse` — the money-side circuit breaker, per-debit refusal vs. aggregate trip. |
| `execute.py` | Runs one arm over a batch: shared random draw, physical constraints, ledger writes. |
| `ledger.py` | The HMAC-SHA256 hash chain and its verifier. |
| `report.py` | The text report: one basis, escalation queue, exception list. |
| `export.py` | Serialises a real run to JSON for the web interface. |
| `experiments.py`, `bandit.py` | Seed sweeps, attribution, ablation, and a (negative-result) learned-timing bandit. |
| `webhook.py` | Real Razorpay webhook ingestion — same engine, live events. |
| `promise.py` | Customer promise-to-pay, one-directional. |
| `nudge.py` | Guardrailed customer-message drafting. No send path exists. |
| `razorpay_adapter.py` | Real Razorpay test-mode API calls. |
| `cli.py` | 14 commands — every module that decides something has one, so nothing here is describable but unrunnable. |

Full per-module detail, line counts and the eight logged categories of defect
are in `README.md` §7 and §16. The live interface is at
<https://akshat333-debug.github.io/Vasooli/>.
