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
| Recovered | ₹66,767.00 | **₹71,864.00** | +₹5,097.00 |
| Attempts spent | 154 | **71** | −83 |
| Wasted attempts | 120 | **35** | −85 |
| **Recovered per attempt** | ₹635.14 | **₹1,012.17** | **+59.4%** |

The headline metric is **recovery per attempt**, not gross recovery, because the retry budget is the scarce resource.

### Why the raw totals disagree — and why that matters

On raw totals the baseline appears to win: ₹97,812 against ₹71,864.

₹31,045.08 of the baseline's total came from **a single unattended debit above the RBI standard cap** — a debit automation is not permitted to make alone. That is not revenue a merchant can bank. It is a compliance failure wearing a recovery number's clothes.

Strip that one action out and the ranking inverts on both axes. **The naive system only beats the bounded one by doing something it isn't allowed to do.** That is the most useful thing this project found, and it is the reason the report prints raw and adjusted figures side by side instead of quietly picking the flattering one.

### Honest exception list — 64 of 100 records unrecovered, ₹205,958.71 still at risk

| Count | Value | Reason |
|---:|---:|---|
| 15 | ₹20,885.00 | all available attempts spent without recovery |
| 13 | ₹21,587.00 | retry budget already exhausted on arrival |
| 8 | ₹15,092.00 | `MANDATE_REVOKED` |
| 5 | ₹3,495.00 | mandate revoked despite an `INSUFFICIENT_FUNDS` failure |
| 5 | ₹7,395.00 | mandate revoked *after* the decision — caught at execution |
| 5 | ₹4,195.00 | `LIMIT_EXCEEDED` |
| 4 | ₹6,396.00 | `MANDATE_EXPIRED` |
| 4 | ₹3,996.00 | unclassifiable by dict or model → human |
| 2 | ₹48,965.47 | `MANDATE_PAUSED` |
| 2 | ₹73,653.24 | above the RBI standard cap → human |
| 1 | ₹299.00 | above the mandate's own cap → human |

**75 retry attempts were preserved by refusing to act.** That is the number the project is actually optimising, and it is invisible in any report that only counts wins.

Full report: [`BATCH_REPORT.txt`](BATCH_REPORT.txt). Regenerate with `uv run vasooli run`.

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
  │  7 stopping rules, then a deterministic grid search over the       │
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

**A language model decides how to talk to a customer. It never decides whether to move money.**

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
| 7 | Otherwise | Schedule the retry at its best moment |

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

**4. The Razorpay test account couldn't do Subscriptions, then could.** The key initially authenticated for Orders, Payments and Invoices but returned `401` on Subscriptions and Plans — that product wasn't enabled on the account. The wrong responses were to crash on startup or to quietly pretend the calls happened. The adapter probes what the account can actually do rather than hardcoding either answer, writes the result to the ledger, and — while the gap existed — degraded to Orders-only with the degradation printed in the report. Once Subscriptions was enabled mid-build, the same probe picked it up with no code change, and `uv run vasooli live` now creates a real test-mode Plan and Subscription. That surfaced the next honest boundary: the subscription comes back `created`, not `active`, because activation needs the customer to complete mandate consent through checkout — a browser step this adapter refuses to automate on the customer's behalf, for the same reason the decision engine refuses to auto-act above the RBI cap. Both states — capability absent, capability present but requiring a human step — are logged and tested (`tests/test_razorpay_adapter.py`).

The through-line: three of the four were cases where something *looked* like it was working. That is what the audit trail and the arm comparison are for.

---

## What this deliberately does not have

No dashboard, no web service, no queue.

The graded substance of a recovery system is the measurement and the audit trail, and both live in the engine. A UI over this would have been surface area, not evidence — it would not have changed a single number in the report, and every hour spent on it is an hour not spent on the stopping rules or on chasing down why the baseline appeared to win.

The audit trail is queryable SQLite and the report is a text file. Both are legible without a frontend, and `verify-ledger` proves the chain independently of anything that renders it.

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
| `vasooli verify-ledger` | Recompute the audit hash chain |

```bash
uv run pytest
```

78 tests. Hermetic — no network, no API keys, no gateway required.

---

## Project layout

```
vasooli/
├── taxonomy.py           8 failure classes; explicit UNKNOWN
├── models.py             record schema; paise only; RBI caps encoded
├── diagnose.py           dict-authoritative + Haiku on the tail
├── decide.py             7 stopping rules + deterministic scorer, no LLM
├── policy.py             RecoveryFuse — the money-side breaker
├── execute.py            both arms, shared random draw, pre-flight re-check
├── ledger.py             hash-chained tamper-evident audit trail
├── report.py             compliance-adjusted report + exception list
├── razorpay_adapter.py   test-mode only; capability-probed
└── sim/
    ├── model.py          the assumptions, as named constants
    └── seed.py           seeded batch with three hazards built in
```

Prior work this builds on: [RunFuse](https://github.com/akshat333-debug/RunFuse) (bounded execution, imported here), [QuantProto](https://github.com/akshat333-debug/QuantProto) (hash-chained ledger; fail loudly rather than silently substitute), [AutoWatch](https://github.com/akshat333-debug/AutoWatch) (rules-first detection, model second).

MIT.
