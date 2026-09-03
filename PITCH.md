# Vasooli — 5-minute pitch script

Target 4:45. Record terminal + face-cam or voiceover. Unlisted YouTube.

Run these before recording so output is fresh:
```bash
rm -f vasooli.db && uv run vasooli seed && uv run vasooli run && uv run vasooli demo-trip && uv run vasooli live && uv run pytest -q
```

---

## 0:00–0:35 — The problem

> A recurring debit fails on Razorpay. It auto-retries. When the retries run out, the subscription is halted and that customer is gone for good.
>
> Almost every dunning system treats a retry as free — fires them on a fixed T+1, T+3, T+5 schedule and hopes.
>
> Retries are not free. RBI's e-mandate framework and Razorpay's own retry limit mean each failed debit gives you a budget of about three attempts, a mandatory 24-hour pre-debit notice, and a ₹15,000 cap on what automation may debit unattended.
>
> So a retry is an irreversible, regulated, capped action against a scarce budget. Spending one on a mandate the customer already cancelled is money you can never get back — and nothing in a normal dashboard tells you it happened.
>
> Vasooli treats those three attempts as the thing to optimise.

## 0:35–2:05 — Live demo

**`uv run vasooli seed`** — 100 synthetic Razorpay-shaped at-risk records.

> Synthetic, and I'll be precise about that in a minute. Note what's in the batch: 22 already-dead mandates, 13 with the budget already spent, records above the RBI cap, records above their own mandate cap. Hard cases on purpose.

**`uv run vasooli run`** — the headline table.

> Two arms over the identical batch. Baseline: fixed schedule, retries everything. Sequencer: diagnoses first, then decides.
>
> Baseline spends 165 attempts. Sequencer spends 77 and recovers more — ₹765 per attempt against ₹349. That is 119% better on the metric that matters, because attempts are the scarce thing.

**Scroll to RAW TOTALS.**

> Now the part I want to be honest about, because it's the most interesting thing I found.
>
> On raw totals the baseline wins on both axes — ₹131,000 against ₹59,000, and more per attempt too. I dug into where that came from. Seventy-three thousand rupees of it is two debits above the RBI standard cap. Those are debits automation is not allowed to make on its own.
>
> That's not revenue. That's a compliance failure with a recovery number painted on it. Strip that single action and the ranking flips on both axes.
>
> **The naive system only beats the bounded one by doing something it isn't allowed to do.** I'd rather show you that than a cherry-picked uplift.

**Scroll to the exception list.**

> Seventy-five of a hundred records unrecovered, every one listed with why. Two hundred and nineteen thousand rupees still at risk. I'm not hiding that — and 86 retry attempts were preserved by refusing to act, which is the number this thing is actually optimising.

**`uv run vasooli demo-trip`** — breaker halts a run.

**`uv run vasooli experiments`** — the part that makes it defensible.

> One seed proves nothing, so I ran forty. The sequencer led in forty of forty, median +126%.
>
> Then I tried to break my own thesis. My claim was that timing retries around payday is what pays. So I closed the payday gap to zero — removed every reason for timing to matter — and the advantage barely moved.
>
> That meant my story was wrong. I decomposed it: refusing doomed attempts is 83% of the gain, timing is 17%. The most elaborate part of my engine is the smaller half. I changed the README to say so, because the alternative is letting the clever machinery take credit for the simple idea's work.

**`uv run vasooli verify-ledger`** — chain intact. Then tamper one row and re-run to show it locating the break.

## 2:05–3:10 — Architecture and the AI choices

> Detect is rules. Diagnose is where a model earns its place — free-text bank error descriptions, inconsistent English, open vocabulary. Real language problem, Claude Haiku.
>
> But the structured error code is a finite set, so a dictionary answers that, deterministically and for free. The model is only load-bearing on the unmapped tail. On the head I run it on a 20-record sample purely to score it against the dict — 100% agreement.
>
> And the model is allowed to say "I don't know." It declined to classify 3 of 4 unmapped records and sent them to a human. That's the guardrail working. A classifier that always sounds confident spends real retries on failures nobody understood.
>
> Then the important part: **no language model runs in the decision to move money.** Timing is a deterministic scorer over the legal retry window. Reproducible, testable, explainable to a regulator. A model reads what the bank wrote. It never decides whether to debit anyone.
>
> Seven stopping rules, each with a test that fails if the rule is deleted — because a deleted stopping rule doesn't crash anything, it just quietly starts burning attempts.
>
> The breaker is built on RunFuse, my own package on PyPI. Honestly though: RunFuse guards the AI side. It doesn't cap rupees. So the money side has its own breaker built on the same semantics — hard limits, verdict strings, and trips checked at the action boundary, never mid-action.

## 3:10–4:25 — What broke

> Four real failures. I'll give you the two that matter.
>
> **First: my own circuit breaker was silently doing nothing.** RunFuse prices runs from a model-pricing table. My gateway reports a model that isn't in it, so it logged "counting cost as $0" and the cost limit could never trip. A limit that looks like protection while accounting zero — which is exactly the failure mode I wrote RunFuse to catch, and I walked straight into it with my own library. It's documented as inert in the code now, with step limits as the real bound.
>
> **Second, and this is the one I'm proudest of catching: my simulator was cheating in favour of the arm I was arguing against.** I ran the comparison and the baseline beat me on gross recovery. Instead of tuning until I won, I traced it — and found `_attempt` was applying a probability without checking physical reality. It was crediting the baseline with recovering money from revoked mandates and from debits above the mandate cap. Banks reject both outright.
>
> That bug inflated my opponent. Which is the only reason it was worth finding — the sequencer's whole advantage is not attempting those, so letting them succeed in simulation destroyed the thing I was measuring.
>
> Fixed it, re-ran, and the baseline *still* led on gross. That's when I found the compliance thing. The bug and the finding were two different problems and I'd have missed the second if I'd stopped at the first.
>
> Also: the Razorpay test account can't do Subscriptions — 401 on that endpoint. The adapter probes capability, writes the gap to the ledger, degrades to the simulator, and prints the degradation. It doesn't crash and it doesn't pretend.

## 4:25–4:45 — Close

> Everything measured here is synthetic and the README says exactly which parts are assumption and which are real Razorpay test-mode calls. The absolute rupee figure isn't a production claim. The comparison is, because both arms face identical records and identical random draws — if my thesis were wrong, the sequencer would lose on the same draws.
>
> 90 tests, hermetic. Every decision hash-chained.
>
> Retries are a budget of three. Vasooli spends them on the failures that can actually be recovered — and refuses, loudly and on the record, the ones that can't.

---

## Notes

- Do **not** claim production numbers. The synthetic framing is a strength here.
- The compliance finding is the strongest 40 seconds. Don't rush it.
- Have the tampered-ledger demo pre-staged; don't type SQL live.
- If asked why no dashboard: the graded substance is the measurement and the audit trail, both of which are the engine. A UI would have been surface area, not evidence.
