# Vasooli — 5-minute pitch script

Four segments: terminal, browser, code, close. Record terminal + browser,
voiceover over both. Unlisted YouTube.

Live site: https://akshat333-debug.github.io/Vasooli/

Run once before recording so output is fresh, then run each command live during
the terminal segment (don't paste pre-captured output — the point is that it's
running, not staged):
```bash
rm -f vasooli.db && uv run vasooli seed && uv run vasooli run && uv run vasooli explain sub_SYN0056 && uv run vasooli experiments --seeds 40 && uv run vasooli demo-trip && uv run vasooli live
```

---

## Segment 1 — Terminal (0:00–2:00)

Fresh terminal, project root. Run each command, let it finish, narrate over
the output before moving to the next.

**`uv run vasooli seed`**

> A recurring debit fails on Razorpay. It auto-retries three times, and then
> the subscription halts — it stops charging itself, and comes back only if
> the customer updates their card. Most systems burn all three attempts on a
> fixed schedule and hope. Here's 100 synthetic at-risk subscriptions, seeded
> and reproducible — dead mandates, exhausted budgets, amounts above the RBI
> cap. Hard cases on purpose.

**`uv run vasooli run`**

> Two arms, identical batch, same random draws. Baseline: the fixed-interval
> schedule dunning tools ship. Vasooli: diagnoses the failure first, then
> decides.
>
> Look at the top row and notice it's boring — ₹57,571 against ₹58,875. Both
> arms recover about the same money this cycle. If that were my claim I
> wouldn't have a project.
>
> Here's the claim. The baseline spent **160 attempts** to get that. Vasooli
> spent **77**. The budget is three deep and it doesn't refill, so what those
> extra 83 attempts bought the baseline is **five more halted subscriptions**
> — twenty-seven against twenty-two. Halted isn't deleted, but it stops
> charging automatically, its invoices never auto-charge again, and it only
> comes back if the customer goes and fixes their card themselves.
>
> That's **₹13,195 a month** moved off autopilot — ten times the one-cycle
> difference, in month one, and it recurs. A dunning dashboard reports the
> top row. The top row is the wrong row.

**`uv run vasooli explain sub_SYN0056`**

> Full rule trace for one record — all 7 stopping rules in order, with why
> each passed or fired. Not reconstructed after the fact. Rerun it, it's
> identical: that's what having no model in the decision path buys you.

**`uv run vasooli experiments --seeds 40`**

> Not one lucky seed — 40 independent runs. On efficiency it wins 40 of 40.
> On raw rupees collected, budget ignored, it wins 25 and loses 14 — the tool
> prints that itself, because you'd find it anyway. Then I tried to break my own thesis: closed the payday-timing
> gap to zero and the advantage barely moved. So I decomposed it — refusing
> doomed attempts is 82% of the gain, timing is 18%. The most elaborate part
> of this engine is the smaller half.

**`uv run vasooli demo-trip`**

> The money-side breaker actually tripping, on camera — 25-action ceiling,
> stopped before it moves past it.

**`uv run vasooli live`**

> Real Razorpay test-mode API call — an actual Subscription, not a mock. And
> it stops there. Activation needs the customer to authenticate the mandate,
> and a batch job deliberately doesn't do that on their behalf.

## Segment 2 — Browser (2:00–3:30)

Open https://akshat333-debug.github.io/Vasooli/.

**Home page.** Scroll to the attempt grid, point at it.

> All 300 retries this batch could spend, one square per attempt. Baseline
> fills its budget. Vasooli leaves most of it unspent.

Scroll to the escalation queue.

> Refusing to debit is half an answer — the money's still owed. Every record
> the engine declines carries a route, as structured data on the decision.
> ₹73,000 goes to a customer-present payment link with AFA, because the answer
> to "above the cap" isn't "give up." The baseline produces zero escalations.

**Click Rulebook.**

> All 7 stopping rules, each with the legal or physical basis, the condition,
> and how many subscriptions it stopped in this batch.

**Click Ledger.** Scroll to the tamper-demo control, click it, show the chain
break, then restore it.

> Every decision is hash-chained before it's acted on. Not a claim — tamper
> with a row yourself and watch the verifier locate where the chain breaks.

**Click Records.** Click one row to expand.

> Same trace the terminal just printed — every rule, the one that fired,
> where it escalates to.

## Segment 3 — Code (3:30–4:00)

Open `vasooli/decide.py`, scroll to the top.

> Diagnosis uses a language model to read free-text bank errors — a genuine
> language problem. No model runs here, in decide.py. Seven stopping rules and
> a deterministic scheduler decide whether to move money. A model reads what
> the bank wrote; it never decides whether to debit anyone.

## Segment 4 — Close (4:00–4:45)

Back in terminal:

```bash
uv run pytest -q
```

Let it print, then:

> 229 tests, hermetic — no network, no API key. 92% coverage. 27 logged
> defects, five found by an external reviewer who caught what I couldn't see:
> my headline was resting on a bug in my own simulator. Fixing it made the
> finding sharper.
>
> Retries are a budget of three. Vasooli spends them on the failures that can
> actually be recovered, refuses the ones that can't — loudly, on the record
> — and gives every rupee it refuses somewhere to go. Same money this cycle,
> half the budget, and ₹13,195 a month still collecting on its own.

Stop recording once "229 passed" is on screen and the last line is spoken.

---

## Notes

- Do **not** claim production numbers. The synthetic framing is a strength here.
- The compliance-correction story ("I had the right finding for the wrong
  reason, and fixing it made it sharper") is the single strongest beat in the
  whole video. It's compressed into the close now — if time allows, expand it
  back into Segment 1 after `vasooli run`, using the BASIS block on screen.
- Have the tampered-ledger demo pre-staged; don't type SQL live.
- If asked about the ablation showing ₹0 above-cap on every row: that's the
  point — say it as defence in depth and show the refusals column moving.
- Segment timings are a guide, not a hard cut. Terminal segment is the most
  important 2 minutes — a system visibly running beats slides every time.
- **Word budget.** The blockquoted narration is ~660 words, about 4.5 minutes
  at 145 wpm. That only fits a 5-minute video if you narrate *over* command
  execution rather than waiting for each to finish in silence. Time a dry run;
  if you land over 5:00, cut the browser segment's Records beat and the
  `demo-trip` line first — both are visible without narration.
- Two claims to keep exactly as written, because both were wrong in an earlier
  draft and a Razorpay engineer will know: `halted` **is** reversible (customer
  updates the card), and T+1/T+3/T+5 is **not** Razorpay's native schedule
  (theirs is T+1/T+2/T+3) — it is the generic dunning cadence the baseline arm
  models. Say "the fixed schedule dunning tools ship", never "Razorpay's
  schedule".
