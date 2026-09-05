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

> A recurring debit fails on Razorpay. It auto-retries, and when the retries
> run out the subscription is halted for good. Most systems burn all three
> attempts on a fixed schedule and hope. Here's 100 synthetic at-risk
> subscriptions, seeded and reproducible — dead mandates, exhausted budgets,
> amounts above the RBI cap. Hard cases on purpose.

**`uv run vasooli run`**

> Two arms over the identical batch, same random draws. Baseline: fixed
> T+1/T+3/T+5 schedule. Vasooli: diagnoses the failure first, then decides.
> Baseline spends 160 attempts. Vasooli spends 77 and recovers more —
> ₹765 per attempt against ₹360. That's 112% better on the metric that
> matters, because the attempt is the scarce resource, not the rupee.

**`uv run vasooli explain sub_SYN0056`**

> Full rule trace for one record — every one of the 7 stopping rules, in
> order, with the reason each one passed or fired. Nothing here is a
> reconstruction after the fact. Rerun it and it's identical, which is the
> point of having no model in the decision path.

**`uv run vasooli experiments --seeds 40`**

> Not one lucky seed — 40 independent runs, and the sequencer wins all 40.
> Then I tried to break my own thesis: closed the payday-timing gap to zero,
> removed every reason timing should matter, and the advantage barely moved.
> So I decomposed it — refusing doomed attempts is 82% of the gain, timing
> is 18%. The most elaborate part of this engine is the smaller half.

**`uv run vasooli demo-trip`**

> The money-side breaker actually tripping, on camera — 25-action ceiling,
> stopped before it moves past it.

**`uv run vasooli live`**

> Real Razorpay test-mode API call. This creates an actual Subscription, not
> a mock — and it stops there. Activation needs the customer to authenticate
> the mandate, and this batch job deliberately doesn't do that on their
> behalf.

## Segment 2 — Browser (2:00–3:30)

Open https://akshat333-debug.github.io/Vasooli/.

**Home page.** Scroll to the attempt grid, point at it.

> Every one of the 300 retries this batch could spend, laid out as one square
> per attempt. Baseline fills its budget. Vasooli leaves most of it unspent
> and still recovers more.

Scroll to the escalation queue.

> Refusing to debit is only half an answer — the money's still owed. Every
> record the engine declines carries a route, as structured data on the
> decision. ₹73,000 goes to a customer-present payment link with AFA, because
> the answer to "above the cap" isn't "give up." The baseline produces zero
> escalations — it halts subscriptions silently, which is the actual failure
> mode this project is about.

**Click Rulebook.**

> All 7 stopping rules, each with the legal or physical basis, the condition,
> and how many subscriptions it stopped in this batch.

**Click Ledger.** Scroll to the tamper-demo control, click it, show the chain
break, then restore it.

> Every decision is hash-chained before it's acted on. This isn't a claim —
> tamper with a row yourself and watch the verifier locate exactly where the
> chain breaks.

**Click Records.** Click one row to expand.

> Same trace the terminal just printed — every rule, the one that fired,
> where it escalates to.

## Segment 3 — Code (3:30–4:00)

Open `vasooli/decide.py`, scroll to the top.

> Detect and diagnose are rules plus a language model reading free-text bank
> errors — a genuine language problem. But no model runs here, in decide.py.
> Seven stopping rules and a deterministic scheduler decide whether to move
> money. Reproducible, testable, explainable to a regulator. A model reads
> what the bank wrote; it never decides whether to debit anyone.

## Segment 4 — Close (4:00–4:45)

Back in terminal:

```bash
uv run pytest -q
```

Let it print, then:

> 229 tests, hermetic — no network, no API key. 92% coverage. 27 logged
> defects, five of them found by an external reviewer who caught something I
> couldn't see in my own code: my headline was resting on a bug in my own
> simulator. Fixing it made the finding sharper, not weaker.
>
> Retries are a budget of three. Vasooli spends them on the failures that can
> actually be recovered, refuses the ones that can't — loudly, on the record
> — and gives every rupee it refuses somewhere to go.

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
