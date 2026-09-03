# Vasooli

**Treats subscription retries as a regulated, three-attempt budget — and spends them only on the failures that can actually be recovered.**

Razorpay AI Buildathon 2026 · Track 03, AI Revenue Recovery

---

## The problem

A recurring debit fails. Razorpay auto-retries. When the retries run out, the subscription moves to `halted` and the customer is gone.

Most dunning systems treat a retry as free and burn it on a fixed T+1 / T+3 / T+5 schedule. Retries are not free. Every failed debit carries a hard, externally imposed budget:

| Constraint | Source |
|---|---|
| ~3 retries, then the subscription halts — permanently | Razorpay Subscriptions |
| A pre-debit notification must precede any debit | RBI e-mandate framework, 2026 |
| ₹15,000 standard cap on an unattended recurring debit | RBI e-mandate framework, 2026 |
| A debit above `mandate_max_amount` is rejected on presentation | mandate terms |
| A revoked or expired mandate can never be debited | mandate lifecycle |

So a retry is an **irreversible, regulated, capped action drawn against a scarce budget.** Spending one on a revoked mandate is money that can never be recovered, and nothing in a normal dashboard will tell you it happened.

That reframing is the whole project. Not *retry harder* — **allocate three attempts well.**

---

## Measured result

100 synthetic at-risk subscriptions, ₹277,822.71 at risk, seed 42. Both arms see identical records and identical random draws.

### Headline — compliance-adjusted

|  | baseline | sequencer | delta |
|---|---:|---:|---:|
| Recovered | ₹57,571.00 | **₹58,875.00** | +₹1,304.00 |
| Attempts spent | 165 | **77** | −88 |
| Wasted attempts | 134 | **52** | −82 |
| **Recovered per attempt** | ₹348.92 | **₹764.61** | **+119.1%** |

The headline metric is **recovery per attempt**, not gross recovery, because the retry budget is the scarce resource.

### The baseline wins on the raw numbers. It wins by breaking a rule.

Unadjusted, the baseline beats the sequencer on *both* axes — ₹131,224 against ₹58,875 in total, and ₹795.30 against ₹764.61 per attempt.

₹73,653.24 of the baseline's total came from **unattended debits above the RBI e-mandate standard cap of ₹15,000** — debits automation is not permitted to make alone. That is not revenue a merchant can bank. Remove those two actions and the ranking inverts decisively on both axes.

Both bases are printed side by side in [`BATCH_REPORT.txt`](BATCH_REPORT.txt) so the adjusted headline can be checked against the unadjusted figures. Picking whichever was flattering would have been easy and is the whole thing this project is against.

### Honest exception list — 75 of 100 records unrecovered, ₹218,947.71 still at risk

| Count | Value | Reason |
|---:|---:|---|
| 22 | ₹29,378.00 | all available attempts spent without recovery |
| 13 | ₹21,587.00 | retry budget already exhausted on arrival |
| 9 | ₹11,891.00 | mandate revoked *after* the decision — caught at execution |
| 9 | ₹17,591.00 | `MANDATE_REVOKED` |
| 5 | ₹3,495.00 | mandate revoked despite an `INSUFFICIENT_FUNDS` failure |
| 5 | ₹4,195.00 | `LIMIT_EXCEEDED` |
| 4 | ₹6,396.00 | `MANDATE_EXPIRED` |
| 3 | ₹1,497.00 | unclassifiable by dict or model → human |
| 2 | ₹48,965.47 | `MANDATE_PAUSED` |
| 2 | ₹73,653.24 | above the RBI standard cap → human |
| 1 | ₹299.00 | above the mandate's own cap → human |

**86 retry attempts were preserved by refusing to act.** That is the number the project is actually optimising, and it is invisible in any report that only counts wins.

---

## Does the claim survive scrutiny?

One seed proves nothing. `uv run vasooli experiments` runs five checks against the result; full output in [`EXPERIMENTS.txt`](EXPERIMENTS.txt).

### It is not an artefact of seed 42

Across **40 independent seeds**, the sequencer led on recovery-per-attempt in **40 of 40**. Median **+126.2%**, 5th percentile **+68.6%**, worst seed **+52.2%**. No losing seeds — and if there had been, they would be listed, because the sweep publishes them.

### Most of the advantage is refusal, not timing — and the project used to imply otherwise

This is the finding that changed how the project describes itself.

Three arms over identical records and draws: **A** the baseline, **B** the sequencer's stopping rules with the baseline's naive schedule, **C** the full sequencer. `B − A` is what refusing is worth; `C − B` is what timing is worth.

| Arm | Per attempt |
|---|---:|
| A — baseline | ₹283.24 |
| B — refusals only, naive timing | ₹589.47 |
| C — refusals + optimal timing | ₹652.99 |

**83% of the gain comes from refusing doomed attempts. 17% comes from timing them well.**

The grid search over the payday cycle is the most elaborate part of this engine and it is the smaller half by a wide margin. The dominant mechanism is the boring one: *don't spend an attempt that cannot succeed.* Saying so plainly is worth more than letting the interesting machinery take credit for the simple idea's work.

Confirming it independently: closing the assumed payday gap to **zero** — removing every reason for timing to matter — still leaves the sequencer ahead by +147% at a 100% win rate. If timing were doing the work, that should have collapsed it.

### Every stopping rule was priced

Each rule switched off in turn, averaged across seeds:

| Rule | Attempts | Wasted | Above cap |
|---|---:|---:|---:|
| all rules on | 76.3 | 44.2 | ₹0 |
| 1 — retry budget exhausted | 81.7 | 47.4 | ₹0 |
| 2 — terminal failure class | 81.2 | 49.1 | ₹0 |
| 3 — mandate not active | **84.8** | **52.6** | ₹0 |
| 4 — failure unclassified | 81.7 | 49.5 | ₹0 |
| 5 — above the mandate's own cap | 83.6 | 51.5 | ₹0 |
| 6 — above the RBI standard cap | 82.3 | 47.5 | **₹86,599** |
| 7 — mandate expires before notice | 76.3 | 44.2 | ₹0 |

Rule 3 is the most expensive to remove. Rule 6 is the only one whose removal produces debits outside the compliance envelope — it is doing exactly the job it exists for.

**Rule 7 changes nothing on this data**, and that is reported rather than quietly dropped. No record in these seeds has a mandate expiring inside the notice window. It is kept because it prevents a real and expensive mistake — the audit that found it caught the scheduler placing a retry six days past expiry — and a rule that guards a rare catastrophe still earns its place. But it has not been exercised by a batch, only by a test.

---

## What is real and what is simulated

Stated plainly, because the track's bar rewards honesty over inflated numbers.

**Simulated:**
- The 100 at-risk records (`vasooli/sim/seed.py`, seeded, reproducible).
- Every recovery outcome. Success probabilities are **assumptions**, documented as named constants in [`vasooli/sim/model.py`](vasooli/sim/model.py). They are not measured, not fitted, and not derived from Razorpay or any bank's data. No public dataset of Indian mandate-retry outcomes exists, and this project did not use one of unclear provenance instead.

**Real:**
- Live Razorpay **test-mode** API calls. `uv run vasooli live` probes the account's actual capabilities and creates a real test-mode Plan, Subscription, and Orders, logged to the audit trail with their IDs.
- The failure taxonomy, every stopping rule, the circuit breaker, the audit chain, and the arm comparison logic. All of it runs; none of it is mocked in the measurement path.
- Claude Haiku classification of free-text bank error descriptions.

**What the numbers do and do not claim:**
- The **absolute rupee figure is not a claim about production performance.** It is the output of the assumptions above.
- The **comparison between arms is meaningful**, because both arms face identical records and identical seeded random draws. The sequencer cannot win by being handed easier records — only by choosing better moments and by declining attempts that were never going to land. If the thesis were wrong, the sequencer would lose on the same draws.

**Live Razorpay Subscriptions, and where that stops being automated:** `uv run vasooli live` creates a real test-mode Plan and Subscription (`vasooli/razorpay_adapter.py::create_test_subscription`) — not mocked, verifiable in the Razorpay test dashboard. That subscription is created in `created` status, not `active`: Razorpay only activates a subscription once the customer completes mandate authentication through checkout, a browser-driven consent step. This adapter deliberately does not automate that step — a machine completing consent on a human's behalf is exactly the class of unattended action this project's own stopping rules refuse elsewhere. Vasooli's job starts after a subscription is active and failing, not through onboarding it. The account initially returned `401` on Subscriptions and Plans (not enabled); the adapter probes capability live rather than assuming either state, so the pre-enablement degradation path — recording the gap and falling back to Orders — is still exercised and tested. See [What broke](#what-broke).

---

## Architecture

```
                    100 synthetic at-risk records (seeded, reproducible)
                                        │
                                        ▼
  ┌──────────── DETECT ──────────────────────────────────────────────┐
  │  rules only. no model.                                            │
  │  invoice issued + charge failed + subscription not halted         │
  └────────────────────────────┬──────────────────────────────────────┘
                               ▼
  ┌──────────── DIAGNOSE ─────────────────────────────────────────────┐
  │  error_code + reason  ──►  dict  ──► authoritative where it knows  │
  │  free-text description ──►  Claude Haiku  ──► the unmapped tail    │
  │  neither is confident  ──►  UNKNOWN  ──► human review              │
  │  guarded by RunFuse (max_steps, max_llm_errors)                    │
  └────────────────────────────┬──────────────────────────────────────┘
                               ▼
  ┌──────────── DECIDE ───────────────────────────────────────────────┐
  │  ** NO LANGUAGE MODEL RUNS HERE **                                 │
  │  8 stopping rules, then a deterministic grid search over the       │
  │  legal retry window for the moment of highest expected success     │
  └────────────────────────────┬──────────────────────────────────────┘
                               ▼
  ┌──────────── EXECUTE ──────────────────────────────────────────────┐
  │  RecoveryFuse.check() at every action boundary                     │
  │  pre-flight mandate re-check — state may have changed since decide │
  │  Razorpay test-mode adapter (capability-probed, degrades honestly) │
  └────────────────────────────┬──────────────────────────────────────┘
                               ▼
  ┌──────────── LEDGER ───────────────────────────────────────────────┐
  │  hash-chained SQLite. every decision + its verdict string.         │
  │  `vasooli verify-ledger` locates tampering by row index.           │
  └────────────────────────────┬──────────────────────────────────────┘
                               ▼
                    compliance-adjusted report + full exception list
```

---

## AI judgment — where a model is used, and where it is refused

The track grades *"the right tool in the right place, **and where you chose not to use one**."* Here is the second half.

| Stage | Tool | Why |
|---|---|---|
| Detect at-risk | rules | Deterministic. A model here is a liability with no upside. |
| Classify failure | **Claude Haiku** | Genuine NL problem: free text, bank-specific, open vocabulary. |
| Decide retry timing | **no model** | Non-determinism in a money decision is indefensible. |
| Enforce limits | **no model** | A guardrail a model can argue past is not a guardrail. |

**A language model reads what a bank wrote. It never decides whether to move money.**

Two further choices worth naming:

- **The dict outranks the model.** Where the structured error code is known, a dictionary answers — deterministically, reproducibly, for free. The model is still run on a 20-record sample purely to be *scored* against the dict (100% agreement in the current batch), and it is load-bearing only on the unmapped tail. Calling a model where a lookup already has the answer is spend with no decision attached to it.
- **The model is allowed to say "I don't know."** It is explicitly instructed to answer `UNKNOWN` when unsure, and `UNKNOWN` routes to a human. In the current batch it declined to classify 3 of 4 unmapped records. That is the guardrail working, not a shortfall — a classifier that always produces a confident label would spend real retries on failures nobody understood.

---

## Stopping rules

Checked in order. Cheapest and most certain refusals first.

| # | Rule | Action |
|---|---|---|
| 1 | Retry budget exhausted | STOP — a further attempt halts the subscription |
| 2 | Terminal failure class | STOP — no retry can succeed |
| 3 | Mandate not active | STOP — even when the error text looked recoverable |
| 4 | Failure unclassified | HUMAN — never auto-act on a guess |
| 5 | Amount above the mandate cap | HUMAN — guaranteed rejection if attempted |
| 6 | Amount above the RBI standard cap | HUMAN — outside the unattended envelope |
| 7 | Mandate expires before the notice period elapses | STOP — no lawful window exists |
| 8 | Otherwise | Schedule the retry at its best moment, bounded by mandate validity |

Plus batch-level ceilings on actions and total value, with a soft warning at 80% before the hard trip, and a legal floor: no debit is scheduled before the RBI pre-debit notice period has elapsed — **applied to both arms**, because comparing a compliant system against a non-compliant one would prove nothing.

Every rule has a test that fails if the rule is deleted (`tests/test_decide.py`). A stopping rule that is silently removed does not crash anything — it just starts spending retries on debits that cannot succeed, and the only symptom is a slightly worse number in a report nobody re-derives.

### On RunFuse, honestly

[RunFuse](https://github.com/akshat333-debug/RunFuse) is my own package on PyPI — runtime circuit breakers for AI agents. It is a real dependency here, not a citation.

But it guards the **AI** side: model spend, step ceilings, retry storms. It does not cap rupees, and claiming otherwise would be exactly the overclaim this project is built to be the opposite of. So the money side has its own breaker, `RecoveryFuse`, deliberately built on RunFuse's semantics because those semantics are right: hard limits that raise rather than warn, a human-readable verdict on every trip, a soft threshold before the hard stop, and **trips checked at the action boundary, never mid-action.**

That last point is not a stylistic echo. RunFuse trips at LLM call boundaries rather than mid-tool because a limit checked at the wrong moment lets state change underneath the decision. The identical problem exists here — a mandate can be revoked between deciding to retry and retrying — which is why `execute.py` re-checks instead of trusting the decision it was handed. In the current batch that re-check preserved 5 attempts.

---

## What broke

Four real failures during the build. None of them were manufactured for this section.

**1. The circuit breaker was silently inert.** RunFuse prices runs from its own model-pricing table. The local gateway reports the model as `claude-haiku-4.5`, which isn't in that table, so RunFuse warned `no pricing for model ... counting cost as $0` and `max_cost_usd` could never trip. A limit that looks like protection while accounting zero — precisely the failure mode RunFuse exists to prevent, caught in my own use of it. Now documented as inert in `diagnose.py`, with `max_steps` as the binding constraint.

**2. The batch breaker truncated the measurement.** The first comparison ran with a 60-action ceiling. Both arms hit it and stopped mid-batch, so I was comparing two partial runs and didn't notice until the outcome counts didn't reach 100. A guardrail sized for a demo had quietly invalidated the metric. The ceiling is now sized above the batch's worst case, and the trip is demonstrated deliberately via `vasooli demo-trip`.

**3. The simulator credited impossible recoveries — and it flattered the baseline.** `_attempt` applied a probability without first checking physical reality, so the baseline was being credited with recovering money from revoked mandates and from debits above the mandate cap. Banks reject both outright. This inflated the arm I was arguing against, which is the only reason it was worth finding: the sequencer's entire advantage is *not attempting* those, so letting them succeed in simulation destroyed the thing being measured. Both constraints now apply to both arms before any probability is considered.

**4. The Razorpay test account could not do Subscriptions, then could.** The key initially authenticated for Orders, Payments and Invoices but returned `401` on Subscriptions and Plans — that product wasn't enabled on the account. The wrong responses were to crash on startup or to quietly pretend the calls happened. The adapter probes what the account can actually do rather than hardcoding either answer, writes the result to the ledger, and — while the gap existed — degraded to Orders-only with the degradation printed in the report. Once Subscriptions was enabled mid-build, the same probe picked it up with no code change, and `uv run vasooli live` now creates a real test-mode Plan and Subscription. That surfaced the next honest boundary: the subscription comes back `created`, not `active`, because activation needs the customer to complete mandate consent through checkout — a browser step this adapter refuses to automate on the customer's behalf, for the same reason the decision engine refuses to auto-act above the RBI cap. Both states — capability absent, capability present but requiring a human step — are logged and tested (`tests/test_razorpay_adapter.py`).

### Then I audited the whole thing and found six more

The four above were found while building. After the project "worked", I ran a deliberate module-by-module and flow-by-flow audit, specifically asking what happens when each component misbehaves. It found six defects in already-committed code. All six are fixed, each with a regression test in [`tests/test_audit_regressions.py`](tests/test_audit_regressions.py) that fails if the fix is reverted.

**5. The scheduler was doing the exact thing this project exists to prevent.** `best_retry_time` searched a window bounded only by the RBI notice floor — never by the mandate's own expiry date. Given a mandate expiring in 2 days and a replenishment cycle 8 days out, it scheduled the retry 6 days *after the mandate died*, and reported `assumed p=0.62` for a debit the bank would reject outright. The stopping rules caught dead mandates on the way in; the scheduler could still manufacture one on the way out. Now the search window is bounded on both ends, follow-up attempts are truncated at expiry, and a mandate that dies before the notice period elapses is a new terminal stopping rule (#7). The simulator was complicit too — it paid out on post-expiry debits — so that constraint now binds both arms.

**6. A fault in the AI guardrail could kill the money stage.** RunFuse wrapped the whole diagnosis loop in `with fuse.run(...)`. Any trip or internal fault propagated straight out of `diagnose_batch`, through the CLI, and killed the entire batch — including every money decision that never needed a model at all. A guardrail that can take down more than it protects is a worse failure than the one it guards against. Diagnosis now has explicit containment boundaries: any AI-stage fault degrades that record to `UNKNOWN` → human review, the batch continues on the dictionary, and the report prints the degradation.

**7. The model's work never reached the decision.** `vasooli run` diagnosed the batch with Claude, printed statistics about it — *"Records classified by the LLM: 1"* — and then each arm silently **re-diagnosed with the dictionary alone**, discarding the model's output. One record (`sub_SYN0055`) that the model correctly identified as `MANDATE_REVOKED` was still being treated as `UNKNOWN` when the actual money decision was made. The README claimed the model was load-bearing on the tail; in the run path it wasn't. Diagnosis now happens once and is threaded into both arms. That single record is why the exception list above shows 9 `MANDATE_REVOKED` and 3 unclassified, rather than 8 and 4.

**8. A truncated run rendered as a complete one.** When the batch breaker tripped, the run stopped mid-batch — 19 of 100 records processed — and the report printed a full headline comparison with no warning, computing rates against a denominator of all 100. The report now refuses to present a truncated run as a result and says why.

**9. Attempts spent on the record that tripped were orphaned.** The trip broke out before appending that record's outcome, so its attempts counted toward the batch total but belonged to no record. Batch-level and per-record accounting disagreed silently. Now the partial outcome is recorded before the break.

**10. Missing credentials crashed instead of degrading.** No `VASOOLI_LLM_API_KEY` produced a raw `OpenAIError` out of the OpenAI SDK constructor rather than falling back to dictionary-only classification — in a project whose stated philosophy is *degrade to asking a human, never guess*.

**On RunFuse specifically:** I tested it in isolation against this gateway before assuming it was at fault. `max_steps` trips precisely at the boundary, step counting is exact, and the `$0` cost accounting is a pricing-table gap on an unrecognised model name, not a logic error. **RunFuse was correct; Vasooli's containment of it was not.** That distinction is the whole lesson — a dependency being right does not make your use of it safe.

**11. A 40-seed sweep shared one set of 40 seeds' worth of luck.** `generate_batch` reuses the same subscription ids for every seed, and the outcome draw was keyed only on that id — so every seed in a sweep drew the *same* 300 luck values. The seed varied which failure sat in each slot, not whether the slot got lucky. Within a single comparison this was harmless, since both arms still shared the draw and the fairness property held. But it meant the sweep built to prove the result was not seed-dependent was itself far less independent than "40 seeds" implied. The draw is now salted with the batch seed, which changed the headline figures — reported above.

**12. The compliance-adjusted headline had a raw number in it.** The table is labelled *compliance-adjusted* and its "recovered" row excludes above-cap debits, but its "recovered / attempt" row divided *raw* recovery by attempts — putting the very debits the row above had just removed back into the baseline's numerator. Two bases inside one table. Fixed to a single basis, with the raw per-attempt figures printed in the raw section so both can be checked.

**13. The project's stated mechanism was mostly not the mechanism.** The sensitivity sweep was built expecting the advantage to collapse once the payday gap closed. It did not — it barely moved. The attribution that followed showed refusal doing 83% of the work and timing 17%. Nothing was broken in the code; what was wrong was the story being told about it, which leaned on the elaborate part rather than the part that pays. The README now leads with refusal.

The through-line across all thirteen: nearly every one was something that *looked* like it was working. Three were guardrails that were themselves the hazard, and one was a story that outran its evidence. That is what the audit trail, the arm comparison, and a deliberate adversarial audit are for — and it is why "it runs and the tests pass" was not where I stopped.

---

## The interface

```bash
uv run vasooli export          # engine emits the batch as JSON
cd web && npm install && npm run dev
```

Next.js 15, TypeScript, Tailwind v4. Static-exportable, so the built site can be opened without a server and can never drift from the batch it was built from.

**The engine stays authoritative.** The interface computes nothing. `vasooli export` runs a real batch, reads the real hash-chained ledger, and serialises exactly what the engine decided; the web app renders that and nothing else. For a system whose claim is that every money action is explainable, a UI that could derive a number the engine never produced would mean the audit trail was no longer the whole story.

Four views:

| View | What it is for |
|---|---|
| **Batch** | The attempt ledger, the compliance finding, the full exception list |
| **Records** | All 100 decisions, filterable, each expanding to the rule that fired |
| **Audit trail** | The 434 hash-chained rows with chain verification |
| **Method** | What is real, what is simulated, and every defect found |

The interface reflects whichever run produced its `batch.json`, including that run's failures — if the model was unreachable, the Method view says so and reports the AI stage as degraded rather than hiding it. Re-sync with `uv run vasooli export`.

### Why it does not look like a finance dashboard

The obvious reference for this product is a payments dashboard — dark rail, warm canvas, soft accent cards. That craft is worth taking and it is taken here. Its *framing* is not.

A typical dashboard is built to make numbers look good: a green badge, a rising sparkline, a celebratory total. This project's entire thesis is that the flattering number is the dishonest one — 64 of 100 records were not recovered, and the system that appears to win does so by breaking a rule. A UI that celebrated ₹71,864 with an up-arrow would contradict the README two clicks away.

So the visual language is inverted where it matters:

- The hero is the **attempt budget**, not a revenue total. The signature view draws all 300 retries the batch was allowed to spend, one cell each, nothing aggregated away — the argument is visible before a single number is read.
- The slot a dashboard reserves for an upsell holds **the compliance finding** instead.
- Colour is semantic and fixed: sage recovered, periwinkle refused, mustard escalated to a person. **Refusal is the product working**, so it is not styled as a loss.
- Clay red appears **exactly once in the entire application**, on the baseline's single non-compliant debit. Scarcity is what makes it read as an alarm.
- Every verdict string is set in monospace at readable size. These are machine output and should look like it, not be styled into prose.

---

## Run it

```bash
uv venv && uv pip install -e ".[dev,razorpay]"
cp .env.example .env      # add keys; test-mode Razorpay keys only
```

```bash
uv run vasooli run
```

| Command | Does |
|---|---|
| `vasooli seed` | Generate the synthetic batch and show its hazard mix |
| `vasooli diagnose` | Classify every failure (`--no-llm` for dict only) |
| `vasooli run` | Both arms + the compliance-adjusted report |
| `vasooli demo-trip` | Show the batch breaker halting a run mid-flight |
| `vasooli live` | Probe the real Razorpay test API and create test Orders |
| `vasooli experiments` | Seed sweep, attribution, ablation, calibration |
| `vasooli export` | Emit the batch as JSON for the interface |
| `vasooli verify-ledger` | Recompute the audit hash chain |

```bash
uv run pytest
```

114 tests, 93% coverage on the engine. Hermetic — no network, no API keys, no gateway required.

---

## Project layout

```
vasooli/
├── taxonomy.py           8 failure classes; explicit UNKNOWN
├── models.py             record schema; paise only; RBI caps encoded
├── diagnose.py           dict-authoritative + Haiku on the tail
├── decide.py             8 stopping rules + deterministic scorer, no LLM
├── policy.py             RecoveryFuse — the money-side breaker
├── execute.py            both arms, shared random draw, pre-flight re-check
├── ledger.py             hash-chained tamper-evident audit trail
├── report.py             compliance-adjusted report + exception list
├── razorpay_adapter.py   test-mode only; capability-probed
├── export.py            serialises a real run for the interface
├── experiments.py       sweep, attribution, ablation, calibration
└── sim/
    ├── model.py          the assumptions, as named constants
    └── seed.py           seeded batch with three hazards built in

web/                      Next.js 15 + Tailwind v4, static-exportable
├── data/batch.json       written by `vasooli export`; the only data source
└── src/
    ├── app/              batch · records · ledger · method
    ├── components/       AttemptLedger is the signature view
    └── lib/data.ts       types mirroring export.py; computes nothing
```

Planned upgrades, ranked with effort estimates and honest notes on which ones are easy to do badly: [`NEXT_STEPS.md`](NEXT_STEPS.md).

Prior work this builds on: [RunFuse](https://github.com/akshat333-debug/RunFuse) (bounded execution, imported here), [QuantProto](https://github.com/akshat333-debug/QuantProto) (hash-chained ledger; fail loudly rather than silently substitute), [AutoWatch](https://github.com/akshat333-debug/AutoWatch) (rules-first detection, model second).

MIT.
