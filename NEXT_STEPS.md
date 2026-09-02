# Next steps

Ranked by how much each one improves the project, not by how interesting it is to build.

The submission is complete as it stands. Everything here is upgrade, and the ordering
assumes one goal: make the central claim harder to attack, then make the product deeper,
then make the engineering more mature.

---

## Tier 1 — makes the central claim much harder to attack

These are the cheapest and highest-value items in the list. Each one directly answers a
question a sharp panelist will ask, and none of them needs new infrastructure.

### 1.1 Run many seeds, report a distribution

**The problem it fixes.** Every number in this project comes from seed 42. The first
question a skeptic asks is *"did you pick the seed?"* Right now the honest answer is
"no, but you can't tell from what I've shown you."

**What to build.** `vasooli sweep --seeds 200`, running both arms over each seed and
reporting the distribution of the per-attempt delta: median, IQR, and the count of seeds
where the sequencer loses. Publish the losing seeds too.

The claim becomes *"the sequencer led on recovery-per-attempt in N of 200 seeds, median
+X%"* — a statistical result rather than an anecdote. If it turns out to win only
narrowly, that is worth knowing before a judge finds it.

**Effort:** ~2 hours. The batch already runs in under a second; this is a loop, an
aggregation, and a histogram.

**Watch out for:** the LLM stage should be disabled in a sweep (dictionary-only), or 200
seeds becomes 4,800 model calls for no decision value. Say so in the output.

### 1.2 Sensitivity analysis on the simulator's assumptions

**The problem it fixes.** The whole measurement rests on about eight hand-chosen
constants in `sim/model.py`. The README is honest that they are assumptions, but honesty
about an assumption is weaker than showing the conclusion survives it being wrong.

**What to build.** Sweep each constant across a plausible range (say ±50%), re-run, and
plot where the conclusion holds and where it breaks. `IF_AFTER_REPLENISH` and
`IF_BEFORE_REPLENISH` matter most — the gap between them *is* the thesis, so find the
point at which the gap gets small enough that timing stops paying.

**Report the breaking point.** "The sequencer's advantage holds while the replenished/
unreplenished success gap exceeds roughly N points; below that, timing stops mattering
and the two arms converge." That sentence is worth more than any headline number,
because it tells a reader exactly what would have to be true for this to be wrong.

**Effort:** ~3 hours.

### 1.3 Ablate the stopping rules

**The problem it fixes.** Eight rules are asserted to earn their place. Nothing measures
what each one is worth.

**What to build.** Disable one rule at a time, re-run the batch, report the cost in
wasted attempts and rupees. Expect rules 2 and 3 (terminal class, dead mandate) to
dominate and rule 7 to be worth almost nothing on this seed — which is fine and worth
saying, because a rule that prevents a rare catastrophe is still worth keeping.

This also makes an excellent UI view: eight rows, each showing what turning that rule off
would have cost.

**Effort:** ~2 hours, and it reuses the sweep harness from 1.1.

---

## Tier 2 — closes gaps between what is claimed and what exists

### 2.1 Build the Hinglish nudge drafter

**Status.** `decide.py` computes `wants_nudge` on every decision. Nothing consumes it.
The Method page used to advertise a Claude Haiku drafter; that claim has been removed
because the drafter does not exist.

**What to build.** For records flagged `wants_nudge` — terminal stops the customer must
act on, and retries with poor odds where asking is worth more than spending an attempt —
draft a short Hinglish message with Haiku. Write it to the ledger. **Never send it.**

The track brief lists "Hinglish voice recovery" as a direction, and this is the honest
version of it: the model writes, a person decides whether to send.

**Effort:** ~2 hours. It also restores a genuine second use of the model, which
strengthens the "right tool in the right place" argument rather than leaving it resting
on classification alone.

### 2.2 Promise-to-pay tracker

Another listed brief direction, and a natural extension: if a customer responds to a
nudge with a date, that date should change the retry schedule — and a broken promise
should change the next decision. Currently the sequencer has no notion of anything the
customer said.

**Effort:** ~4 hours. Needs 2.1 first.

### 2.3 Webhook ingestion — batch becomes continuous

**What it fixes.** Vasooli currently reasons over a batch handed to it. A real deployment
receives `payment.failed` and `subscription.halted` webhooks as they happen.

**What to build.** The AutoWatch pattern that was cut on day 3: HMAC-verified endpoint →
202 immediately → durable job → the same engine, unchanged. The engine does not need to
know it was invoked by a webhook rather than a batch.

**Effort:** ~6 hours including the durable-job layer. This is the largest item in Tier 2
and the one most likely to break something, so do it after the Tier 1 work is banked.

---

## Tier 3 — the actual machine learning upgrade

### 3.1 Learn the retry policy instead of hand-specifying it

**The honest framing first.** `best_retry_time` currently grid-searches over probabilities
that a human wrote down. That is a heuristic dressed as an optimiser. The genuine upgrade
is to learn the policy from outcomes.

**What to build.** A contextual bandit — Thompson sampling over
`(bank, error_code, hour_of_day, days_since_replenish, attempt_index)` — that learns which
(context, timing) pairs actually pay, updating from each observed outcome.

**The trap to avoid.** On synthetic data, a learner trained against `sim/model.py` will
rediscover `sim/model.py`. That proves the mechanism runs; it proves nothing about
reality, and presenting it as accuracy would be exactly the kind of overclaim this
project is built to avoid. State that limitation prominently, and evaluate on held-out
seeds with a *different* generating model than the one used for training.

**Effort:** ~8 hours done properly, including the honest evaluation. Do not start it
unless there is time to do the evaluation part — the learner alone is the easy half.

### 3.2 Calibration reporting

The engine already emits a probability with every scheduled retry (`expected_success`).
Nothing checks whether those probabilities are any good. Bucket predictions and plot
observed frequency against predicted — a reliability diagram.

This is cheap, it is directly relevant to a system that reports confidences, and being
able to say *"when we predict 0.6, it lands 0.6 of the time"* is a strong, checkable
claim. **Effort:** ~2 hours.

---

## Tier 4 — engineering maturity

| # | Item | Why | Effort |
|---|---|---|---|
| 4.1 | **CI on GitHub Actions** — pytest, ruff, tsc, next build | A green badge is the cheapest credibility signal on a public repo, and it stops a broken push from reaching a judge | 1 h |
| 4.2 | **Coverage report with a floor** | 100 tests is a count, not a measure. Coverage plus a threshold makes regressions visible | 1 h |
| 4.3 | **Sign the ledger, don't just chain it** | The hash chain detects edits, but anyone with write access can recompute the whole chain and it verifies clean. An HMAC keyed outside the database, or periodic anchoring of the root, makes it tamper-evident against an insider — which is the threat an audit trail actually exists for | 3 h |
| 4.4 | **Property-based tests on `decide()`** | Hypothesis over generated records, asserting invariants: never schedules past mandate expiry, never exceeds the budget, never auto-acts above the RBI cap. QuantProto already works this way | 3 h |
| 4.5 | **Structured logging** | `print` in the CLI is fine; the engine should emit structured events so a real deployment can ship them somewhere | 2 h |

---

## Tier 5 — presentation and product

| # | Item | Why | Effort |
|---|---|---|---|
| 5.1 | **Deploy the site** | `next build` already static-exports. Vercel or GitHub Pages, then link it from the README so a judge clicks rather than clones | 30 min |
| 5.2 | **Scenario switcher in the UI** | Export several policy configurations and let the viewer compare them. Keeps the "interface computes nothing" boundary intact — each scenario is a real engine run | 3 h |
| 5.3 | **Run-to-run diff view** | Show what changed between two batches. Useful once the sweep from 1.1 exists | 3 h |
| 5.4 | **Screen-reader pass** | Contrast is now WCAG AA throughout and every control is labelled, but the 300-cell attempt grid is decorative to a screen reader. It needs a text equivalent | 2 h |

---

## Deliberately not doing

Listed so the omissions read as decisions rather than oversights.

- **A database behind the web app.** The interface is a viewer over one exported run.
  Adding a live query path would let it show a number the engine never produced.
- **Authentication / multi-tenancy.** There is no second user. It would be scaffolding
  for a requirement that does not exist.
- **Real customer contact of any kind.** Nudges are drafted and stored, never sent. That
  boundary is not a time constraint; it is the design.
- **Automating Razorpay checkout to activate a mandate.** A machine completing consent on
  a human's behalf is the exact class of unattended action the stopping rules refuse
  everywhere else.
- **More seeded records.** 100 is enough to exercise every rule and every hazard. Going
  to 10,000 would make the numbers look bigger without making them more true.

---

## Suggested order

If there is one day: **1.1, 1.2, 4.1, 5.1.** The claim gets much stronger, CI goes green,
and the site is live and linkable.

If there is a week: add **1.3, 2.1, 3.2, 4.3.** That covers the ablation, closes the nudge
gap, adds calibration, and hardens the audit trail — after which the honest-metrics story
is close to airtight.

Leave **3.1** for last. It is the most interesting item here and the easiest one to do
badly.
