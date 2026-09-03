# Vasooli

**Treats subscription retries as a regulated, three-attempt budget, and spends them only on the failures that can actually be recovered.**

Razorpay AI Buildathon 2026 · Track 03, AI Revenue Recovery

> *Vasooli* (वसूली) is Hindi for recovery or collection.

---

## Table of contents

1. [What this is, in one page](#1-what-this-is-in-one-page)
2. [Status at a glance](#2-status-at-a-glance)
3. [Why the problem is shaped this way](#3-why-the-problem-is-shaped-this-way)
4. [The measured result](#4-the-measured-result)
5. [Does the claim survive scrutiny](#5-does-the-claim-survive-scrutiny)
6. [Architecture](#6-architecture)
7. [Module reference](#7-module-reference)
8. [The decision engine in full](#8-the-decision-engine-in-full)
9. [How the two arms are made comparable](#9-how-the-two-arms-are-made-comparable)
10. [Where a model is used, and where it is refused](#10-where-a-model-is-used-and-where-it-is-refused)
11. [Guardrail inventory](#11-guardrail-inventory)
12. [What is real and what is simulated](#12-what-is-real-and-what-is-simulated)
13. [The web interface](#13-the-web-interface)
14. [Every command](#14-every-command)
15. [Test inventory](#15-test-inventory)
16. [Defect log: everything that broke](#16-defect-log-everything-that-broke)
17. [What is done and what is left](#17-what-is-done-and-what-is-left)
18. [Running and verifying it yourself](#18-running-and-verifying-it-yourself)

---

## 1. What this is, in one page

A recurring debit fails on Razorpay. Razorpay auto-retries. When the retries run out, the subscription moves to `halted` and the customer is gone.

Most dunning systems treat a retry as free and burn it on a fixed T+1 / T+3 / T+5 schedule. Retries are not free. Every failed debit carries a hard, externally imposed budget:

| Constraint | Source |
|---|---|
| ~3 retries, then the subscription halts, permanently | Razorpay Subscriptions |
| A pre-debit notification must precede any debit | RBI e-mandate framework, 2026 |
| ₹15,000 standard cap on an unattended recurring debit | RBI e-mandate framework, 2026 |
| A debit above `mandate_max_amount` is rejected on presentation | mandate terms |
| A revoked or expired mandate can never be debited | mandate lifecycle |

So a retry is an **irreversible, regulated, capped action drawn against a scarce budget.** Spending one on a revoked mandate is money that can never be recovered, and nothing in a normal dashboard will tell you it happened.

That reframing is the whole project. Not *retry harder*, but **allocate three attempts well.**

**Vasooli is a batch engine plus a viewer.** The engine ingests at-risk subscriptions, classifies each failure, applies eight ordered stopping rules, schedules the survivors at their best lawful moment, executes under a circuit breaker, and writes every decision to a hash-chained audit trail. The web interface renders what the engine decided and computes nothing of its own.

---

## 2. Status at a glance

| | |
|---|---|
| **Repo** | `github.com/akshat333-debug/Vasooli`, branch `main` |
| **Engine** | Python 3.11+, 18 modules, ~4,270 lines |
| **Interface** | Next.js 15 + TypeScript + Tailwind v4, ~2,220 lines, 4 pages |
| **Tests** | **194**, hermetic: no network, no API keys, no gateway |
| **Coverage** | **91%** on the engine (CI floor 90%) |
| **Lint** | `ruff` clean; `tsc --noEmit` clean |
| **CI** | GitHub Actions, engine + web, given no credentials on purpose |
| **Live integration** | Razorpay test-mode Plan, Subscription and Orders created for real |
| **Deployment** | Configured for GitHub Pages and Vercel, **not yet published** |

Everything below is reproducible from a clean clone with `uv run pytest` and `uv run vasooli run`.

---

## 3. Why the problem is shaped this way

Read this before judging any design decision, because most of them follow from constraints rather than taste.

**The retry budget is three, and it is terminal.** Razorpay retries a failed subscription charge a bounded number of times, then moves the subscription to `halted`. There is no fourth attempt and no undo. This makes an attempt a *scarce resource*, which is unusual — most systems optimise a rate, this one optimises an allocation.

**The RBI e-mandate framework (2026) sets three hard limits.** A pre-debit notification must reach the customer before the debit. Unattended recurring debits are capped at ₹15,000 (₹1L for certain categories). Both apply equally to UPI AutoPay and card e-mandates. A system that ignores these is not "more aggressive", it is non-compliant.

**A mandate is a separate object from a subscription, with its own lifecycle.** It can be revoked by the customer at any time, expire on its own date, be paused, and carry its own per-transaction ceiling that may be lower than the amount being charged. A subscription can look perfectly healthy while its mandate is dead.

**Failures arrive as a structured code plus free text.** The code (`error_code` + `error_reason`) is machine-generated and finite. The description is written by a bank, in inconsistent English, and does not restate the code. These two facts drive the entire AI-usage decision in §10.

---

## 4. The measured result

100 synthetic at-risk subscriptions, ₹277,822.71 at risk, seed 42. Both arms see identical records and identical random draws.

### Headline, compliance-adjusted

|  | baseline | sequencer | delta |
|---|---:|---:|---:|
| Recovered | ₹57,571.00 | **₹58,875.00** | +₹1,304.00 |
| Attempts spent | 165 | **77** | −88 |
| Wasted attempts | 134 | **52** | −82 |
| **Recovered per attempt** | ₹348.92 | **₹764.61** | **+119.1%** |

The headline metric is **recovery per attempt**, not gross recovery, because the retry budget is the scarce resource.

### The baseline wins on the raw numbers. It wins by breaking a rule.

Unadjusted, the baseline beats the sequencer on *both* axes: ₹131,224 against ₹58,875 in total, and ₹795.30 against ₹764.61 per attempt.

₹73,653.24 of the baseline's total came from **two unattended debits above the RBI standard cap** — debits automation is not permitted to make alone. That is not revenue a merchant can bank. Remove those two actions and the ranking inverts decisively on both axes.

Both bases are printed side by side in [`BATCH_REPORT.txt`](BATCH_REPORT.txt) so the adjusted headline can be checked against the unadjusted figures. Picking whichever was flattering would have been easy, and is the whole thing this project is against.

### Honest exception list: 75 of 100 records unrecovered, ₹218,947.71 still at risk

| Count | Value | Reason |
|---:|---:|---|
| 22 | ₹29,378.00 | all available attempts spent without recovery |
| 13 | ₹21,587.00 | retry budget already exhausted on arrival |
| 9 | ₹11,891.00 | mandate revoked *after* the decision, caught at execution |
| 9 | ₹17,591.00 | `MANDATE_REVOKED` |
| 5 | ₹3,495.00 | mandate revoked despite an `INSUFFICIENT_FUNDS` failure |
| 5 | ₹4,195.00 | `LIMIT_EXCEEDED` |
| 4 | ₹6,396.00 | `MANDATE_EXPIRED` |
| 3 | ₹1,497.00 | unclassifiable by dict or model, sent to a person |
| 2 | ₹48,965.47 | `MANDATE_PAUSED` |
| 2 | ₹73,653.24 | above the RBI standard cap, sent to a person |
| 1 | ₹299.00 | above the mandate's own cap, sent to a person |

**86 retry attempts were preserved by refusing to act.** That is the number the project is actually optimising, and it is invisible in any report that only counts wins.

---

## 5. Does the claim survive scrutiny

One seed proves nothing. `uv run vasooli experiments` runs five checks; full output in [`EXPERIMENTS.txt`](EXPERIMENTS.txt).

### 5.1 It is not an artefact of seed 42

Across **40 independent seeds**, the sequencer led on recovery-per-attempt in **40 of 40**. Median **+126.2%**, 5th percentile **+68.6%**, worst seed **+52.2%**. No losing seeds, and if there had been, the sweep publishes them by number.

### 5.2 Most of the advantage is refusal, not timing

**This finding changed how the project describes itself.**

Three arms over identical records and draws: **A** the baseline, **B** the sequencer's stopping rules with the baseline's naive schedule, **C** the full sequencer. `B − A` is what refusing is worth; `C − B` is what timing is worth.

| Arm | Per attempt |
|---|---:|
| A, baseline | ₹283.24 |
| B, refusals only, naive timing | ₹589.47 |
| C, refusals + optimal timing | ₹652.99 |

**83% of the gain comes from refusing doomed attempts. 17% comes from timing them well.**

The grid search over the payday cycle is the most elaborate part of this engine and it is the smaller half by a wide margin. The dominant mechanism is the boring one: *do not spend an attempt that cannot succeed.*

Confirmed independently: closing the assumed payday gap to **zero**, removing every reason for timing to matter, still leaves the sequencer ahead by +147% at a 100% win rate. If timing were doing the work, that should have collapsed it.

### 5.3 Every stopping rule was priced

Each rule switched off in turn, averaged across seeds:

| Rule | Attempts | Wasted | Above cap |
|---|---:|---:|---:|
| all rules on | 76.3 | 44.2 | ₹0 |
| 1, retry budget exhausted | 81.7 | 47.4 | ₹0 |
| 2, terminal failure class | 81.2 | 49.1 | ₹0 |
| 3, mandate not active | **84.8** | **52.6** | ₹0 |
| 4, failure unclassified | 81.7 | 49.5 | ₹0 |
| 5, above the mandate's own cap | 83.6 | 51.5 | ₹0 |
| 6, above the RBI standard cap | 82.3 | 47.5 | **₹86,599** |
| 7, mandate expires before notice | 76.3 | 44.2 | ₹0 |

Rule 3 is the most expensive to remove. Rule 6 is the only one whose removal produces debits outside the compliance envelope.

**Rule 7 changes nothing on this data**, and that is reported rather than quietly dropped. No record in these seeds has a mandate expiring inside the notice window. It is kept because it prevents a real and expensive mistake (the audit that created it found the scheduler placing a retry six days past expiry), and a rule guarding a rare catastrophe still earns its place. But it has been exercised only by tests, never by a batch.

### 5.4 The machine learning did not work, and that is the finding

The obvious upgrade to `best_retry_time` is to stop grid-searching over constants a human wrote down and learn the timing from outcomes. So that was built: a Beta-Bernoulli Thompson-sampling bandit over five coarse delay arms (0h, 24h, 72h, 168h, 336h), conditioned on failure class, pay-cycle position and attempt index.

It **loses to the hand-specified scorer**, in both worlds.

| | learned | heuristic | edge |
|---|---:|---:|---:|
| Same world as training | 0.459 | 0.552 | **−9.26 pts** |
| World shifted underneath it | 0.395 | 0.441 | **−4.63 pts** |

Two things make that honest rather than embarrassing.

**In-distribution, the heuristic is not a competitor, it is an oracle.** It grid-searches the exact probability function the outcomes are drawn from. Nothing can beat it there, and a learner that appeared to would be a bug. Any project reporting a bandit beating a heuristic on its own simulator is reporting that it handed the learner an answer key.

**The interesting question is what happens as the world stops matching the assumptions.** Shifting the simulator's constants progressively (`PERTURBATION` in `bandit.py`):

| Shift | learned | heuristic | edge |
|---:|---:|---:|---:|
| 0.0 | 0.459 | 0.552 | −9.26 |
| 0.2 | 0.453 | 0.534 | −8.03 |
| 0.4 | 0.442 | 0.514 | −7.25 |
| 0.6 | 0.429 | 0.495 | −6.64 |
| 0.8 | 0.408 | 0.467 | −5.94 |
| 1.0 | 0.395 | 0.441 | −4.63 |

The deficit narrows monotonically: the learner halves its disadvantage as the assumptions degrade, which is what you would expect if it has learned something the assumptions do not contain. **But it never crosses zero in the tested range.** Extrapolating to a crossover would be inventing a result. The honest statement is that learning starts to pay only once your assumptions are badly wrong, and finding out whether they are requires real data rather than more simulation.

**So the bandit is not wired into `decide.py`, and a test enforces that.** A sampled policy in a money path forfeits the reproducibility this project rests on.

### 5.5 Calibration

The engine emits an `expected_success` with every scheduled retry. Bucketed predictions against observed outcomes are reported, and labelled as **internal consistency only**: predictions and outcomes come from the same assumed model, so agreement shows the scheduler reads its own model correctly. It is not evidence about real banks.

---

## 6. Architecture

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
  │  8 stopping rules in order, then a deterministic grid search over  │
  │  the legal retry window for the moment of highest expected success │
  │  emits: action, rule_fired, scheduled_at, expected_success, verdict│
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
  └────────────────────────────┬──────────────────────────────────────┘
                               ▼
         report.py  ──►  BATCH_REPORT.txt   (compliance-adjusted + raw)
         export.py  ──►  web/data/batch.json  ──►  Next.js viewer
```

**Side paths:** `promise.py` folds a customer's promise-to-pay into an existing decision (later only). `nudge.py` drafts Hinglish customer messages and never sends them. `experiments.py` and `bandit.py` measure the engine rather than running it. `razorpay_adapter.py` talks to the real test-mode API. `logging.py` emits operational JSON, silent by default.

---

## 7. Module reference

### Engine, `vasooli/`

| Module | Lines | Responsibility |
|---|---:|---|
| `taxonomy.py` | 94 | 8 canonical `FailureClass` values; `RECOVERABLE` / `TERMINAL` sets; `CODE_MAP` dict from `(error_code, error_reason)` to a class; `classify_by_code()` returns `UNKNOWN` for anything unmapped and never guesses. |
| `models.py` | 98 | `AtRiskRecord` (the record type everything speaks), `Diagnosis`, enums for mandate/subscription/method. Domain constants: `RBI_STANDARD_CAP_PAISE = 15_000_00`, `MAX_RETRY_BUDGET = 3`, `PRE_DEBIT_NOTICE_HOURS = 24`. All amounts are integer paise, never floats. |
| `sim/model.py` | 97 | The assumed success probabilities, as named constants. Terminal classes are hard zero. This is the file to read before believing any number. |
| `sim/seed.py` | 191 | Deterministic batch generator. Failure mix skewed to `insufficient_funds`. Three hazards seeded in deliberately (see §12). |
| `diagnose.py` | 281 | Dictionary-authoritative classification; Claude Haiku on the unmapped tail and on a scored sample of the head; RunFuse-wrapped; containment boundaries so no AI fault reaches the money stage. |
| `decide.py` | 274 | The eight stopping rules and the timing grid search. **No model runs here.** Emits `rule_fired` so the viewer never reimplements the ordering. |
| `policy.py` | 144 | `RecoveryPolicy` and `RecoveryFuse`: the money-side circuit breaker. Caps on attempts, per-debit amount, batch actions and batch value; soft warning at 80%; refuses non-positive amounts. |
| `execute.py` | 354 | Runs one arm over a batch. Shared random draw, pre-flight mandate re-check, physical constraints applied to both arms, ledger writes, `BatchResult` with `truncated` detection. |
| `ledger.py` | 195 | Append-only HMAC-SHA256 hash chain in SQLite. `verify()` reports the first broken row index and whether the chain is keyed. |
| `report.py` | 198 | The text report. Enforces a single basis in the compliance-adjusted table, prints the raw figures alongside, refuses to present a truncated run as a result, and always prints the full exception list. |
| `export.py` | 258 | Serialises a real run to JSON for the viewer, including four real scenario runs. |
| `experiments.py` | 375 | Seed sweep, attribution decomposition, sensitivity / breaking point, rule ablation, calibration. |
| `bandit.py` | ~300 | Thompson-sampling learned timing, with hostile in-/out-of-distribution evaluation. Not wired into the engine. |
| `promise.py` | 151 | Promise-to-pay. May move a retry later and nothing else. Trust decays after 2 broken promises. |
| `nudge.py` | 235 | Hinglish drafting with guardrails. **No send path exists**, and a test asserts its absence. |
| `webhook.py` | 228 | Razorpay ingestion: signature before parsing, `compare_digest`, replay rejection, conservative defaults. Decides nothing. |
| `razorpay_adapter.py` | 266 | Test-mode only, refuses live keys, probes account capability rather than assuming. |
| `logging.py` | 86 | Operational JSON lines. Silent unless `VASOOLI_LOG` is set. |
| `cli.py` | 402 | Ten commands, see §14. |

### Interface, `web/src/`

| File | Lines | Responsibility |
|---|---:|---|
| `app/page.tsx` | 248 | Batch page: hero, attempt ledger, three stat cards, the compliance finding, scenarios, exception list, provenance. |
| `app/records/page.tsx` | 32 | All 100 records, filterable and deep-linkable. |
| `app/ledger/page.tsx` | 42 | The hash-chained audit trail. |
| `app/method/page.tsx` | 281 | What is real, what is simulated, the AI-usage table, and every defect found. |
| `components/AttemptLedger.tsx` | 214 | **The signature view.** All 300 cells of the batch's retry budget, coloured by fate, baseline above sequencer. |
| `components/RecordExplorer.tsx` | 282 | Records table with the decision trace; renders `rule_fired` from the engine. |
| `components/LedgerStream.tsx` | 175 | Ledger rows with filters and paging. |
| `components/Scenarios.tsx` | 129 | Policy comparison across four real engine runs. |
| `components/ExceptionList.tsx` | 111 | Grouped unrecovered records. |
| `components/Sidebar.tsx` | 170 | Rail nav with a custom glyph set. |
| `lib/data.ts` | 196 | Types and formatting. `rupees()` uses `Intl` via `toLocaleString("en-IN")`. |
| `lib/useUrlState.ts` | 43 | Filter state synced to the URL so views are shareable. |
| `app/globals.css` | 237 | Design tokens, type scale, focus ring, skip link, accessibility rules. |

---

## 8. The decision engine in full

`decide(record, failure_class, now)` returns a `Decision` carrying `action`, `rule_fired` (1–8), `scheduled_at`, `expected_success`, `wants_nudge`, and a human-readable `verdict` string that lands verbatim in the ledger.

Rules are checked **in this order**. Order matters: the cheapest and most certain refusals come first, so no work is done on a record that was never eligible.

| # | Condition | Action | Why |
|---|---|---|---|
| 1 | `attempts_remaining <= 0` | `STOP_EXHAUSTED` | Razorpay halts the subscription on a further attempt. |
| 2 | Failure class is terminal | `STOP_TERMINAL` | `MANDATE_REVOKED`, `MANDATE_EXPIRED`, `MANDATE_PAUSED`, `LIMIT_EXCEEDED`. No retry can succeed. |
| 3 | `mandate_status != active` | `STOP_TERMINAL` | Even when the error text reads as recoverable. The mandate is the authority, not the error string. |
| 4 | Class is `UNKNOWN` | `HUMAN_REVIEW` | Never auto-act on a guess. |
| 5 | `amount > mandate_max_amount` | `HUMAN_REVIEW` | Guaranteed rejection on presentation. |
| 6 | `amount > ₹15,000` | `HUMAN_REVIEW` | Outside the unattended envelope under the RBI framework. |
| 7 | Mandate expires before the notice period elapses | `STOP_TERMINAL` | No lawful window exists at all. |
| 8 | Otherwise | `RETRY_SCHEDULED` | Grid search for the best moment, bounded by mandate validity. |

**Rules 1–3 exist because the budget is only three deep.** Spending an attempt on a record that could never have succeeded is the most expensive mistake available to this system, and it is invisible unless you look for it.

**Rule 7 was added by an audit**, after the scheduler was caught placing a retry six days past a mandate's expiry while reporting a confident `p=0.62` for a debit the bank would reject. The stopping rules guarded against dead mandates on the way in; the scheduler could still create one on the way out.

### The timing search (rule 8)

`best_retry_time()` is a plain grid search: every 6 hours across a 14-day horizon, bounded below by the RBI notice floor and above by the mandate's validity date. It picks the moment with the highest assumed success probability, ties resolving to the earliest (recovering the same rupee sooner is strictly better).

It is deliberately boring: exhaustive over a small bounded grid, fully deterministic, and trivial to explain to someone who needs to trust the debit. Returns `(None, 0.0)` when the legal window is empty, which is what rule 7 catches.

---

## 9. How the two arms are made comparable

The comparison is the only claim this project makes, so the mechanism matters.

For each `(subscription, attempt_index)` pair, **one** uniform random number is drawn, seeded from the batch seed plus the subscription id plus the attempt index. **Both arms see the same draw.** What differs is the probability that draw is tested against, and that probability is a function of *when* the arm chose to retry.

```
success  ⟺  u[seed, sub, attempt]  <  p(failure_class, attempt, when_arm_retried)
```

So the sequencer cannot win by getting luckier records. It can only win by choosing better moments, and by declining to spend attempts that were never going to land. If the thesis were wrong, the sequencer would lose on the same draws.

**Physical constraints bind both arms** before any probability is considered: a dead mandate cannot be debited, a debit above the mandate cap is rejected, and a debit presented after expiry is rejected. These are properties of the world, not of strategy.

**The baseline is naive about strategy, not about law.** It retries on a fixed T+1/T+3/T+5 schedule and ignores failure class and mandate state. It still respects the RBI pre-debit notice floor and the same batch breaker, because comparing a compliant system against a non-compliant one would prove nothing.

**The late-revocation hazard.** A deterministic 8% of subscriptions have their mandate revoked between the decision and the attempt. The sequencer re-checks at the action boundary and refuses; the baseline does not and burns the attempt. This mirrors RunFuse's reason for tripping at call boundaries rather than mid-tool: a check performed at the wrong moment lets the world change underneath the decision.

---

## 10. Where a model is used, and where it is refused

| Stage | Tool | Why |
|---|---|---|
| Detect at-risk | rules | Deterministic. A model here is a liability with no upside. |
| Classify the failure | **Claude Haiku** | Free text, bank-specific, open vocabulary. A genuine language problem. |
| Draft the customer nudge | **Claude Haiku** | Hinglish register. Guardrailed, and **never sent**. |
| Decide retry timing | **no model** | Non-determinism in a money decision is indefensible. |
| Enforce the limits | **no model** | A guardrail a model can argue past is not a guardrail. |

**A language model reads what a bank wrote and writes what a customer reads. It never decides whether to move money.**

Two further choices worth naming:

**The dictionary outranks the model.** Where the structured error code is known, a dictionary answers, deterministically and for free. The model is still run on a 20-record sample purely to be *scored* against the dictionary (100% agreement in the current batch), and it is load-bearing only on the unmapped tail. Calling a model where a lookup already has the answer is spend with no decision attached to it.

**The model is allowed to say "I don't know."** It is explicitly instructed to answer `UNKNOWN` when unsure, and `UNKNOWN` routes to a human. In the current batch it declined to classify 3 of 4 unmapped records. That is the guardrail working, not a shortfall.

### The nudge drafter, and why it cannot hurt anyone

`decide.py` flags which records warrant a message. Haiku writes the prose. It cannot choose who gets contacted, cannot change the amount, and cannot change what happens next.

Its output is checked rather than trusted:

- **No links.** A model that invents a payment link has invented a phishing target. Rejected outright, not cleaned up.
- **No figures of its own.** The model writes a placeholder; the real amount is substituted from the record afterwards, so a wrong number is structurally impossible.
- **No promises or threats.** Refunds, waivers, discounts, account closure, legal language.
- **Bounded length**, 320 characters.

Failed drafts are discarded and *counted*, never repaired, because repairing them would hide how often the model produces one.

**There is no send path in the module and no configuration that adds one.** A test asserts the absence of a send function.

> Aapka autopay mandate expire ho gaya hai. Naya mandate set karne ke liye payment settings mein jaaye.
>
> Aapke account mein balance kam hai, isliye Rs 1,299 ka payment fail ho gaya. Please balance add karke dobara try kijiye.

*Real drafts from `uv run vasooli nudge`. The rupee figures were substituted by the engine, not written by the model.*

---

## 11. Guardrail inventory

Six independent layers, each with a different job. Listed because "bounded and gated" is a claim that should be enumerable.

| Layer | Where | Guards against |
|---|---|---|
| **Stopping rules** | `decide.py` | Spending an attempt that cannot succeed, or acting above the compliance envelope. 8 rules, each with a test that fails if the rule is deleted. |
| **RecoveryFuse** | `policy.py` | An unattended batch moving too many rupees or taking too many actions. Hard trip with a verdict string, soft warning at 80%, refuses non-positive amounts. |
| **RunFuse** | `diagnose.py` | The AI stage: step ceiling, error ceiling, retry storms against the gateway. |
| **Containment boundaries** | `diagnose.py` | Any AI-stage fault degrading that record to human review rather than killing the batch. |
| **Pre-flight re-check** | `execute.py` | State changing between the decision and the action. |
| **Hash chain** | `ledger.py` | The record of what happened being edited afterwards. |

### On RunFuse, honestly

[RunFuse](https://github.com/akshat333-debug/RunFuse) is my own package on PyPI, runtime circuit breakers for AI agents. It is a real dependency here, not a citation.

But it guards the **AI** side: model spend, step ceilings, retry storms. It does not cap rupees, and claiming otherwise would be exactly the overclaim this project is built to be the opposite of. So the money side has its own breaker, `RecoveryFuse`, deliberately built on RunFuse's semantics because those semantics are right: hard limits that raise rather than warn, a human-readable verdict on every trip, a soft threshold before the hard stop, and **trips checked at the action boundary, never mid-action.**

**Verified empirically, not assumed:** RunFuse's `max_steps` trips precisely at the boundary and its step counting is exact. Its `max_cost_usd` is **inert** on this deployment, because the gateway reports a model absent from RunFuse's pricing table and cost accounts as `$0`. That is documented in `diagnose.py` rather than left looking like a working limit.

### On the audit trail, honestly

The chain is keyed with HMAC-SHA256, not a plain hash. A plain chain detects an accidental edit and nothing else: anyone who can write to the database can recompute every subsequent hash and the result verifies clean, which protects against corruption but not against the insider an audit trail exists for. With `VASOOLI_LEDGER_KEY` set, forging the chain needs the key as well as write access.

Unset, it still runs, using a published constant, and `verify()` reports **tamper-evident** rather than **tamper-proof**, in those words. A project someone clones must work out of the box, and it must not claim a protection it does not have.

---

## 12. What is real and what is simulated

Stated plainly, because the track's bar rewards honest metrics over inflated ones.

### Simulated

- **The 100 at-risk records** (`vasooli/sim/seed.py`), seeded and reproducible.
- **Every recovery outcome.** The success probabilities are **assumptions**, written as named constants in [`vasooli/sim/model.py`](vasooli/sim/model.py):

  | Constant | Value | Meaning |
  |---|---:|---|
  | `IF_BEFORE_REPLENISH` | 0.18 | Retrying while the account is still empty |
  | `IF_AFTER_REPLENISH` | 0.62 | Retrying on or shortly after payday |
  | `IF_REPLENISH_WINDOW_DAYS` | 4 | How long the balance stays healthy |
  | `DOWNTIME_DURING` | 0.09 | Retrying inside a bank outage |
  | `DOWNTIME_AFTER` | 0.81 | Retrying after it clears |
  | `DOWNTIME_WINDOW_HOURS` | 12 | Assumed outage duration |
  | `TECHNICAL_FLAT` | 0.55 | Transient gateway faults, time-independent |
  | `PER_ATTEMPT_DECAY` | 0.88 | Each successive attempt is modestly less likely |

  These are not measured, not fitted, and not derived from Razorpay or any bank's data. No public dataset of Indian mandate-retry outcomes exists, and this project did not use one of unclear provenance instead.

### Real

- **Live Razorpay test-mode API calls.** `uv run vasooli live` probes the account's actual capabilities and creates a real test-mode Plan, Subscription and Orders, logged to the audit trail with their IDs.
- **The failure taxonomy, all eight stopping rules, both circuit breakers, the hash chain, and the arm comparison logic.** All of it runs; none of it is mocked in the measurement path.
- **Claude Haiku** classification of free-text bank errors and Hinglish nudge drafting.

### What the numbers do and do not claim

- The **absolute rupee figure is not a claim about production performance.** It is the output of the assumptions above.
- The **comparison between arms is meaningful**, because both arms face identical records and identical seeded random draws.

### Three hazards seeded in deliberately

A batch where everything is clean proves nothing, so `sim/seed.py` plants:

1. **Free-text error descriptions that vary by bank and do not restate the code.** The LLM classifier has to actually read them.
2. **Error codes absent from `CODE_MAP`**, which must land in `UNKNOWN` and route to a human rather than being guessed at.
3. **Records whose mandate is already dead while the error text still says something recoverable.** Any system that trusts the diagnosis without re-checking mandate state at execution time will burn a retry on these.

### Live Razorpay Subscriptions, and where that stops being automated

`uv run vasooli live` creates a real test-mode Plan and Subscription, verifiable in the Razorpay dashboard. That subscription is created in `created` status, not `active`: Razorpay only activates a subscription once the customer completes mandate authentication through checkout, a browser-driven consent step.

**This adapter deliberately does not automate that step.** A machine completing consent on a human's behalf is exactly the class of unattended action this project's own stopping rules refuse elsewhere. Vasooli's job starts after a subscription is active and failing, not through onboarding it.

The account initially returned `401` on Subscriptions and Plans; the adapter probes capability live rather than assuming either state, so the pre-enablement degradation path is still exercised and tested.

---

## 13. The web interface

Next.js 15 App Router, TypeScript, Tailwind v4, static export. Custom SVG charts, no chart library.

### The boundary that matters

**The interface renders decisions. It does not make them.** The Python engine is authoritative for every number. `export.py` runs a real batch and serialises exactly what the engine decided; the viewer reads that JSON.

This is enforced concretely: `decide.py` emits `rule_fired` so the decision trace shows which rule fired without the viewer reimplementing the ordering. An earlier version *did* recompute the rule order in TypeScript, and it was removed — a second copy of a money decision, in a language with no tests against `decide.py`, is free to drift silently.

Same reason the policy comparison has **no "what if" slider**: each scenario is a real engine run, because a slider would have to compute an outcome the engine never produced.

### Pages

| Route | Contents |
|---|---|
| `/` | The attempt ledger, the compliance finding, the three numbers that matter, the policy comparison, the exception list |
| `/records` | All 100 records, filterable by decision, each expandable to its full rule trace |
| `/ledger` | The hash-chained audit trail with filters and chain verification status |
| `/method` | What is real, what is simulated, the AI-usage table, and every defect found |

### Why it does not look like a finance dashboard

The visual language was taken from a finance dashboard reference, then inverted where the framing conflicted. A dashboard's job is to make numbers look good: green badges, rising sparklines, an upsell card. This project's thesis is that 75 of 100 records were not recovered and the system that appears to win only wins by breaking a rule. A UI celebrating ₹58,875 with an up-arrow would actively contradict the README.

So the craft transferred and the framing inverted:

- The dual-tone bars became the **attempt budget**: spent versus preserved. In the reference they were decoration; here they are the scarce resource.
- The upsell slot became the **compliance finding**.
- Celebration badges became **three-state semantics**, where *refused* is the product working.
- A single **clay red** appears exactly once in the entire application, on the baseline's non-compliant debit. Scarcity is what makes it land.
- Every verdict string is set in **monospace at readable size**. These are machine output and should look like it, not be styled into prose.

### Accessibility

All text meets WCAG AA (4.5:1 for small text), verified by measurement rather than by eye — with a checker that resolves `oklab()` through a canvas and composites real ancestor backgrounds, after two earlier scripts produced false readings. Skip link, one `h1` per page, ordered headings, every control labelled, visible focus throughout, `touch-action: manipulation`, no horizontal overflow at 375px. The 300-cell attempt grid is `aria-hidden` with a text equivalent beside it, because 300 anonymous divs read aloud is worse than nothing.

Filters are synced to the URL, so a filtered view can be linked and shared. On a page whose purpose is "here is the evidence", sending someone the six records that went to human review should be a URL, not a list of instructions.

---

## 14. Every command

```bash
uv venv && uv pip install -e ".[dev,razorpay]"
cp .env.example .env      # test-mode Razorpay keys only
```

| Command | What it does |
|---|---|
| `uv run vasooli seed` | Generate the synthetic batch and show its hazard mix |
| `uv run vasooli diagnose` | Classify every failure (`--no-llm` for dictionary only) |
| `uv run vasooli run` | Both arms plus the compliance-adjusted report (`--out FILE`) |
| `uv run vasooli experiments` | Seed sweep, attribution, breaking point, ablation, calibration |
| `uv run vasooli bandit` | Learned retry timing versus the deterministic scorer |
| `uv run vasooli nudge` | Draft customer messages for review; **sends nothing** |
| `uv run vasooli demo-trip` | Show the batch breaker halting a run mid-flight |
| `uv run vasooli live` | Probe the real Razorpay test API, create a Subscription and Orders |
| `uv run vasooli export` | Emit a batch run as JSON for the interface |
| `uv run vasooli verify-ledger` | Recompute the audit hash chain |

```bash
uv run pytest          # 194 tests, hermetic
cd web && npm install && npm run dev
```

### Environment variables

| Variable | Purpose | Absent behaviour |
|---|---|---|
| `VASOOLI_LLM_BASE_URL` | OpenAI-compatible gateway | Defaults to `http://localhost:20128/v1` |
| `VASOOLI_LLM_API_KEY` | Gateway key | Degrades to dictionary-only, reported in the output |
| `VASOOLI_LLM_MODEL` | Model id | `kr/claude-haiku-4.5` |
| `VASOOLI_LEDGER_KEY` | Keys the hash chain | Chain reports "tamper-evident", not "tamper-proof" |
| `VASOOLI_LOG` | Enables JSON operational logs | Silent |
| `RAZORPAY_KEY_ID` / `_SECRET` | Test-mode only; live keys refused | Live commands report unavailable |
| `RAZORPAY_WEBHOOK_SECRET` | Webhook signature verification | Ingestion refuses rather than trusts |

---

## 15. Test inventory

**194 tests, hermetic.** No network, no API key, no gateway. CI is given no credentials on purpose, so a test that starts needing one fails there rather than in front of a reader.

| File | Tests | Covers |
|---|---:|---|
| `test_audit_regressions.py` | 20 | One per defect found in the audits; each fails if the fix is reverted |
| `test_webhook.py` | 15 | Signature, replays, conservative defaults, UTC timestamps |
| `test_decide.py` | 14 | Every stopping rule, rule ordering, the legal floor, timing |
| `test_experiments.py` | 14 | Sweep, attribution, ablation, calibration, assumption restoration |
| `test_nudge.py` | 13 | Every guardrail on customer-facing text; absence of a send path |
| `test_execute.py` | 11 | Shared draws, physical constraints, budget, ledger integrity |
| `test_promise.py` | 11 | A promise may only move a retry later; trust decay |
| `test_properties.py` | 11 | Hypothesis, 300 generated examples each, 11 safety invariants |
| `test_logging.py` | 11 | Silent by default, JSON structure, timing survives exceptions |
| `test_ledger.py` | 10 | Hash chain, tamper detection, keyed vs unkeyed |
| `test_razorpay_adapter.py` | 9 | Refuses live keys, capability probing, degradation |
| `test_bandit.py` | 8 | Not wired into the decision path, context power, reproducibility |
| `test_policy.py` | 7 | Breaker limits, soft warnings, non-positive amounts |
| `test_seed.py` | 6 | Determinism, all three hazards present |
| `test_sim_model.py` | 6 | Terminal classes hard zero, curve shapes |
| `test_taxonomy.py` | 6 | `UNKNOWN` is never guessed past |
| `test_diagnose.py` | 5 | Degrades to human review, never to a guess |

The property tests are worth singling out: Hypothesis generates adversarial records (expired mandates, zero budgets, amounts a rupee either side of a cap) and asserts that the engine never schedules past expiry, never precedes the notice floor, never auto-actions above the RBI cap, never touches a dead mandate, and always carries a verdict and a rule. They check the cases I did not think of.

---

## 16. Defect log: everything that broke

Kept in full because the track grades *"what broke, and what you did about it"*, and because the pattern across them is more useful than any single one.

### Found while building

**1. My own circuit breaker was silently inert.** RunFuse prices runs from its own model-pricing table. The gateway reports a model absent from it, so RunFuse logged `no pricing for model ... counting cost as $0` and `max_cost_usd` could never trip. A limit that looks like protection while accounting zero, caught in my own use of my own library.

**2. The batch breaker truncated the measurement.** The first comparison ran with a 60-action ceiling. Both arms hit it and stopped mid-batch, so I was comparing two partial runs. A guardrail sized for a demo had quietly invalidated the metric.

**3. The simulator credited impossible recoveries, and it flattered the baseline.** `_attempt` applied a probability without checking physical reality, crediting the baseline with recovering money from revoked mandates and over-cap debits. This inflated the arm I was arguing against, which is the only reason it was worth finding.

**4. The Razorpay test account could not do Subscriptions, then could.** The adapter probes capability rather than hardcoding either answer. Once enabled mid-build, the same probe picked it up with no code change.

### Found in a deliberate module-by-module audit, after it "worked"

**5. The scheduler was doing the exact thing this project exists to prevent.** `best_retry_time` searched a window bounded only by the notice floor, never by the mandate's expiry. Given a mandate expiring in 2 days and a replenishment cycle 8 days out, it scheduled the retry **6 days after the mandate died**, reporting `p=0.62` for a debit the bank would reject. Now bounded on both ends, with rule 7 added.

**6. A fault in the AI guardrail could kill the money stage.** RunFuse wrapped the whole diagnosis loop; any trip propagated out and killed the batch, including money decisions that never needed a model.

**7. The model's work never reached the decision.** The CLI diagnosed with Claude, printed statistics about it, then each arm silently re-diagnosed with the dictionary alone. One record correctly identified as `MANDATE_REVOKED` was still decided as `UNKNOWN`.

**8. A truncated run rendered as a complete one.** The breaker tripped at 19 of 100 records and the report printed a full headline, computing rates against a denominator of 100.

**9. Attempts spent on the tripped record were orphaned**, counted in the batch total but belonging to no record.

**10. Missing credentials crashed instead of degrading**, in a project whose stated philosophy is to degrade to asking a human.

### Found by building the experiments

**11. A 40-seed sweep shared one set of luck.** `generate_batch` reuses subscription ids across seeds and the outcome draw keyed only on that id, so every seed drew the *same* 300 luck values. The sweep built to prove the result was not seed-dependent was itself barely independent. The draw is now salted with the batch seed.

**12. The compliance-adjusted headline had a raw number in it.** The table is labelled compliance-adjusted and its "recovered" row excludes above-cap debits, but its "recovered / attempt" row divided *raw* recovery by attempts, putting those debits back into the baseline's numerator. Two bases inside one table. The same bug existed independently in the interface.

**13. The project's stated mechanism was mostly not the mechanism.** The sensitivity sweep was built expecting the advantage to collapse once the payday gap closed. It barely moved. Attribution showed refusal doing 83% of the work. Nothing was broken in the code; what was wrong was the story being told about it.

**14. An unreachable model was scored as disagreement.** With the gateway down, the run reported 20 disagreements as if a working model had given 20 different answers, rather than 24 failed calls. An accuracy signal computed from calls that never happened is a lie. A fuse trip was also being swallowed by the same broad catch.

### Found in the UI audit

**15. Seven real contrast failures** in the stat cards (4.17–4.37 against the 4.5 AA floor): muted text on *tinted* backgrounds, which are darker than plain paper.

**16. Razorpay's UTC timestamps were read in local time.** `fromtimestamp()` without a timezone shifts a mandate's expiry by the host's offset, so the engine would schedule against a different day depending on where it runs.

**17. The viewer reimplemented the engine's stopping-rule ordering**, and **the money breaker accepted a negative debit**, which would *decrease* the batch's attempted total and quietly raise the ceiling for every action after it.

### Two non-bugs, investigated and left alone

- `focus:outline-none` on two inputs looked like it killed the focus ring. Measured: it does not. Tailwind v4 emits utilities inside `@layer`, and unlayered CSS wins the cascade regardless of specificity.
- A contrast script reported 24 failures at 1.22:1. Tailwind v4 emits `oklab()`, and the regex was reading its 0–1 components as 0–255 RGB. Rewritten to resolve any colour format through a canvas; the honest count was 7.

### The pattern

Nearly every one was something that **looked** like it was working. Several were guardrails that were themselves the hazard: an inert cost limit, a breaker that truncated the measurement it was protecting, a nudge guardrail that rejected safe drafts while missing the dangerous case, and an audit script that produced confident false readings twice.

That is what the audit trail, the arm comparison, and a deliberate adversarial audit are for, and it is why "it runs and the tests pass" was not where this stopped.

---

## 17. What is done and what is left

### Done

Everything in the original plan, plus everything found while building it. Full record with per-item outcomes in [`NEXT_STEPS.md`](NEXT_STEPS.md).

| Area | State |
|---|---|
| Engine, 8 stopping rules, both breakers, hash chain | Complete |
| Two-arm measurement with shared draws | Complete |
| Seed sweep, attribution, sensitivity, ablation, calibration | Complete |
| Hinglish nudge drafter, guardrailed, no send path | Complete |
| Promise-to-pay | Complete |
| Webhook ingestion | Complete |
| Learned retry timing (bandit) | Complete, **negative result**, not wired in |
| Keyed audit chain, property tests, structured logging | Complete |
| CI, 91% coverage with a 90% floor | Complete |
| Web interface, 4 pages, WCAG AA, deep-linkable | Complete |
| Razorpay test-mode integration | Complete |

### Left

**Deploying the site.** Both paths are configured and verified: `.github/workflows/pages.yml` is committed and inert until Pages is enabled in repo settings, and Vercel needs only `web/` as its root. Not done because publishing is outward-facing and changes settings on an account.

**Genuinely open, in order of value:**

1. **Parse promises from free text.** `promise.py` takes structured promises. A customer replying *"salary 5th ko aa raha hai"* is a real language problem and the natural third place for the model. The module states plainly that it does not do this yet.
2. **Feed real outcomes to the bandit.** The negative result says learning pays only once assumptions are badly wrong. Finding out whether they are needs production data. **Blocked on data, not effort** — no amount of further simulation resolves it.
3. **Anchor the ledger externally.** The chain is unforgeable without the key, but a key-holder can still rebuild it. Periodically publishing the root hash somewhere append-only would close that.
4. **Exercise rule 7 with a batch.** Covered by tests, never triggered by a seeded batch.
5. **Multi-currency and multi-region.** Everything is paise and RBI. The stopping rules are India-shaped by design.

### Deliberately not doing

- **A database behind the web app.** The interface is a viewer over one exported run; a live query path would let it show a number the engine never produced.
- **Authentication or multi-tenancy.** There is no second user.
- **Sending anything to a customer.** Drafts are stored for review. That boundary is the design, not a time constraint.
- **Automating Razorpay checkout to activate a mandate.** A machine completing consent on a human's behalf is what the stopping rules refuse everywhere else.
- **More seeded records.** 100 exercises every rule and every hazard; 10,000 would make the numbers bigger without making them more true.

---

## 18. Running and verifying it yourself

Nothing here needs credentials. Every claim in this README is checkable from a clean clone.

```bash
git clone https://github.com/akshat333-debug/Vasooli && cd Vasooli
uv venv && uv pip install -e ".[dev]"

uv run pytest                    # 194 tests pass with no network
uv run vasooli run               # reproduces the headline table
uv run vasooli experiments       # reproduces the sweep and attribution
uv run vasooli bandit            # reproduces the negative ML result
uv run vasooli verify-ledger     # recomputes the hash chain
uv run vasooli demo-trip         # watch the breaker stop a run
```

To check the honesty claims specifically:

- **"The numbers are not cherry-picked"** → `uv run vasooli experiments`, read the sweep section. 40 seeds, losing seeds published by number.
- **"The exception list is complete"** → `BATCH_REPORT.txt`, the unrecovered count must equal 100 minus recovered.
- **"The model never decides about money"** → `grep -rn "diagnose\|llm\|openai" vasooli/decide.py` returns nothing.
- **"The bandit is not wired in"** → `tests/test_bandit.py::test_it_is_not_wired_into_the_decision_path`.
- **"Nudges are never sent"** → `tests/test_nudge.py::test_module_exposes_no_send_path`.
- **"The audit trail is tamper-evident"** → edit a row in `vasooli.db` and re-run `verify-ledger`; it names the broken index.

---

## Project layout

```
vasooli/
├── taxonomy.py          8 failure classes; explicit UNKNOWN
├── models.py            record schema; paise only; RBI caps encoded
├── diagnose.py          dictionary-authoritative + Haiku on the tail
├── decide.py            8 stopping rules + deterministic scorer, no LLM
├── policy.py            RecoveryFuse, the money-side breaker
├── execute.py           both arms, shared random draw, pre-flight re-check
├── ledger.py            HMAC-keyed hash chain, tamper located by row
├── report.py            compliance-adjusted report + exception list
├── export.py            serialises a real run for the interface
├── experiments.py       sweep, attribution, ablation, calibration
├── bandit.py            learned timing, an experiment and a negative one
├── promise.py           promise-to-pay; may only move a retry later
├── nudge.py             Hinglish drafting, guardrailed, never sends
├── webhook.py           Razorpay ingestion; verifies, dedupes, decides nothing
├── razorpay_adapter.py  test-mode only; capability-probed
├── logging.py           operational JSON; silent unless VASOOLI_LOG is set
├── cli.py               ten commands
└── sim/
    ├── model.py         the assumptions, as named constants
    └── seed.py          seeded batch with three hazards built in

web/                     Next.js 15 viewer, static export
tests/                   194 tests across 17 files
BATCH_REPORT.txt         the measured result, regenerate with `vasooli run`
EXPERIMENTS.txt          the five checks, regenerate with `vasooli experiments`
NEXT_STEPS.md            per-item record of what each upgrade was worth
```

Prior work this builds on: [RunFuse](https://github.com/akshat333-debug/RunFuse) (bounded execution, imported here as a real dependency), [QuantProto](https://github.com/akshat333-debug/QuantProto) (hash-chained ledger; fail loudly rather than silently substitute), [AutoWatch](https://github.com/akshat333-debug/AutoWatch) (rules-first detection, model second; verify-persist-acknowledge-then-work).

MIT.
