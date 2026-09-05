# Requirements (historical)

> **This is the pre-build requirements document, kept unedited.** It was written
> before any code existed and is preserved as a record of what was planned versus
> what was actually built — including where the two diverged.
>
> It is **not** a description of the current system and its figures are not
> current. For what exists today, read [`../README.md`](../README.md); for the
> architecture as built, [`ARCHITECTURE.md`](ARCHITECTURE.md).
>
> Notable divergences, since they are the interesting part: this planned "~40
> focused tests" and the build has 229; it planned a 3-day schedule that mostly
> held; and it did not anticipate the twenty-seven defects logged in README §16,
> five of which came from an external review and changed reported numbers.
>
> **One factual error below, left in place deliberately.** The problem statement
> says a halted subscription means "the customer is gone." That is wrong, and it
> stayed wrong in the shipped README until an external review challenged it on
> 5 Sep 2026. Razorpay documents that a halted subscription returns to `active`
> once the customer updates the card details; what does not return is the
> automation, since the invoices accrued while halted are never auto-charged.
> The corrected framing is in [`../README.md`](../README.md) §1. It is preserved
> here because a premise that survived from the planning document all the way
> into a public README is exactly the kind of divergence this file exists to
> record.

## One-liner

Treats subscription retries as a regulated, three-attempt budget — and spends them
only on the failures that can actually be recovered.

## The problem

An Indian merchant on Razorpay Subscriptions has recurring debits fail every cycle.
Razorpay auto-retries; when retries are exhausted the subscription moves to `halted`
and the customer is gone. Most dunning systems treat a retry as free and burn the
budget on a fixed T+1 / T+3 / T+5 schedule.

Retries are not free. Each failed debit carries a **hard, externally-imposed budget**:

| Constraint | Source |
|---|---|
| ~3 retries, then subscription → `halted` (terminal) | Razorpay Subscriptions |
| 24h pre-debit notification mandatory before any debit | RBI e-mandate framework 2026 |
| ₹15,000 standard cap (₹1L enhanced categories) | RBI e-mandate framework 2026 |
| Debit above `mandate_max_amount` always fails | mandate terms |
| Revoked/expired mandate cannot be debited, ever | mandate lifecycle |

So a retry is an **irreversible, regulated, capped action against a scarce budget**.
Spending one on a revoked mandate is money that can never be recovered.

That reframing is the project. Not "retry harder" — "allocate three attempts well."

## What Vasooli does

Bounded recovery loop over a batch of at-risk subscriptions:

1. **Detect** — rules only. Invoice issued + charge failed + subscription not halted.
2. **Diagnose** — Claude Haiku maps messy gateway error strings to a canonical
   failure taxonomy. Unmapped → `UNKNOWN` → manual review. Never guesses.
3. **Decide** — deterministic scorer, no LLM. Terminal vs recoverable; if recoverable,
   when and whether to spend a retry vs. send a free nudge instead.
4. **Execute** — wrapped in RunFuse. Hard limits, stopping rules, human-in-the-loop
   above threshold.
5. **Ledger** — hash-chained SQLite. Every decision with its reason string.
6. **Report** — measured batch result vs. a fixed-schedule baseline, plus an honest
   exception list.

## Scope — in

- Synthetic batch of 100 Razorpay-shaped subscription/invoice records, seeded.
- Failure taxonomy + LLM classifier with a deterministic fallback.
- Deterministic retry-allocation policy.
- RunFuse-enforced stopping rules.
- Hash-chained tamper-evident audit ledger.
- Two-arm comparison (baseline vs. sequencer) over the identical seeded batch.
- CLI: `seed`, `detect`, `run --arm {baseline,sequencer}`, `report`, `verify-ledger`.
- ~40 focused tests.
- Optional, time-permitting: ~5 live Razorpay test-mode subscriptions end to end.

## Scope — out (explicitly, and stated in the README)

- No web dashboard. No Next.js, Supabase, Inngest, Vercel.
- No real customer contact. Nudges are **drafted and logged, never sent**.
- No real money. Test mode only, or synthetic.
- No live bank/PSP data. No claim of production performance.
- No trained ML model. Policy is a hand-specified deterministic scorer.

## Non-negotiable honesty constraints

1. The recovery-success simulator is **assumption-driven and synthetic**. The README
   must state this in its own titled section, not a footnote.
2. The two-arm comparison is the valid claim (identical seed, identical simulator).
   The absolute rupee figure is **not** a claim about production.
3. The exception list ships whole. Nothing dropped because it looked bad.
4. If Razorpay test-mode integration is cut for time, the README says it was cut.
5. Headline metric is **₹ recovered per retry spent**, not ₹ recovered — because the
   constraint is the budget, not the total.

## AI judgment — where an LLM is used, and where it is refused

| Stage | Tool | Rationale |
|---|---|---|
| Detect at-risk | rules / SQL | Deterministic. LLM = liability, zero upside. |
| Classify failure reason | Claude Haiku | Genuine NL problem: free-text, bank-specific, open vocabulary. |
| Decide retry timing | **no LLM** | Non-determinism in a money decision is indefensible. Must be seeded and reproducible. |
| Draft customer nudge | Claude Haiku | Hinglish, tone, context. Genuine NL problem. Draft only. |
| Enforce limits | **no LLM** (RunFuse) | A guardrail an LLM can argue past is not a guardrail. |

Design rule: **an LLM decides how to talk to the customer; it never decides whether
to move money.**

## Stopping rules

- `MANDATE_REVOKED` / `MANDATE_EXPIRED` → terminal, zero retries spent.
- `attempt_n >= 3` → stop, mark `EXHAUSTED`, escalate to re-mandate link.
- `amount > mandate_max_amount` → never auto-retry (guaranteed failure) → human.
- `amount > ₹15,000` → human review regardless of all else.
- Pre-debit notification not sent ≥24h prior → cannot attempt; schedule instead.
- Pre-flight mandate-status re-check **inside execute**, not at decide time.
- Batch-level RunFuse trip on total auto-actions / total value ceiling.
- Soft trip at 80% → warning, run continues.

Every stop emits a ledger row with a RunFuse-style verdict string, e.g.
`"stopped: MANDATE_REVOKED — retry would be spent on a dead mandate"`.

## Data

No public dataset exists for Indian subscription-mandate failure outcomes, and no
unlicensed scraped data will be used. Data is **synthetic and generated in-repo**
(`vasooli/sim/`), seeded and reproducible. Failure-reason mix is skewed toward
`INSUFFICIENT_FUNDS`, consistent with published decline-reason distributions; the
assumed success probabilities live in one documented module so a reader can audit or
replace them. This is stated as a limitation, not presented as empirical data.

## Reuse from prior work (genuine, not decorative)

- **RunFuse** (my PyPI package) — imported as a real dependency, enforcing the batch
  circuit breaker. Its trip-at-boundary semantics directly informed the pre-flight
  mandate re-check.
- **QuantProto** — hash-chained tamper-evident ledger pattern; "fail loudly rather
  than silently substitute synthetic data" posture.
- **AutoWatch** — pipeline shape (fast dumb ingest → durable worker → rules-first
  detection, LLM second → append-only rows → digest) and the documented principle
  "rules-first, statistics-later."

## Success criteria

- [ ] `uv run vasooli run --arm sequencer` completes a 100-record batch end to end.
- [ ] Both arms run over an identical seed and produce a comparison table.
- [ ] Every stopping rule has a test that fails if the rule is removed.
- [ ] `verify-ledger` detects a deliberately tampered row.
- [ ] README contains architecture diagram, real/simulated split, batch result,
      and the full exception list.
- [ ] One real failure encountered during the build, documented with before/after
      ledger evidence.

## Deliverables

Public repo `akshat333-debug/Vasooli` · 5-min unlisted video · project name **Vasooli**
· one-liner above.

## Timeline (hard deadline 5 Sep 2026)

- **Day 1** — seed + taxonomy + ledger + tests. Gate: `seed`/`detect` classify 100 records.
- **Day 2** — decide + execute + RunFuse + both arms + report. **Ship point.**
- **Day 3** — 14:00 code freeze. Razorpay test mode (cuttable) → README → video.
