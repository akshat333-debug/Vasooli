# Vasooli — 5-minute pitch script

Target 4:45. Record terminal + browser, voiceover. Unlisted YouTube.

Live site for the browser segments: https://akshat333-debug.github.io/Vasooli/

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
> Retries are not free. Razorpay's retry limit gives you about three attempts. RBI's e-mandate framework adds a mandatory 24-hour pre-debit notice, and a ₹15,000 ceiling above which the debit needs additional factor authentication — which means an unattended presentation above it doesn't just break a rule, it gets **declined**.
>
> So a retry is an irreversible, regulated, capped action against a scarce budget. Spending one on a mandate the customer already cancelled is money you can never get back — and nothing in a normal dashboard tells you it happened.
>
> Vasooli treats those three attempts as the thing to optimise.

## 0:35–2:15 — Live demo

**`uv run vasooli seed`** — 100 synthetic Razorpay-shaped at-risk records.

> Synthetic, and I'll be precise about that in a minute. Note what's in the batch: dead mandates, records with the budget already spent, records above the RBI cap, records above their own mandate cap. Hard cases on purpose.

**`uv run vasooli run`** — the headline table.

> Two arms over the identical batch. Baseline: fixed schedule, retries everything. Sequencer: diagnoses first, then decides.
>
> Baseline spends 160 attempts. Sequencer spends 77 and recovers more — ₹765 per attempt against ₹360. That's 112% better on the metric that matters, because attempts are the scarce thing.
>
> And look at the row underneath. Raw and compliance-adjusted are the **same number** on both sides. There's no adjustment here to argue about.

**Scroll to the BASIS block.**

> That took a correction to get to, and it's the most interesting thing in this project.
>
> An earlier build of this engine credited the baseline with ₹73,000 of recoveries above the RBI cap, and my report subtracted them afterwards. That was my strongest slide: "the naive system only wins by breaking a rule."
>
> An external reviewer pointed out that above ₹15,000 the debit needs AFA, so the bank declines it. That money was never deliverable. My compliance headline was correcting a bug in my own simulator, not measuring a behaviour.
>
> So I fixed the world, and the finding got **better**. The baseline wasn't merely breaking a rule. It was burning five attempts on debits that could never settle.
>
> Now three independent layers refuse them: the stopping rule declines to schedule it, the money-side breaker refuses it at the action boundary, and the world declines it on presentation. Switch the stopping rule off in the ablation and above-cap recovery is *still* zero — the refusals just move down a layer. That's defence in depth, measured rather than claimed.

**Scroll to the escalation queue.**

> And here's the half a stopping rule doesn't give you. Refusing to debit is only half an answer — the money is still owed.
>
> Every record the engine declines carries a route, as structured data on the decision, not English in a log line. ₹73,000 goes to a customer-present payment link with AFA, because the right answer to "above the cap" isn't "give up", it's "ask the customer". ₹85,000 goes to a fresh mandate registration link — and that link is real: the adapter captures the live test-mode `short_url` from Razorpay Subscriptions.
>
> The baseline produces zero escalations. It halts them silently.

**Scroll to the exception list, then the halts row.**

> Seventy-five of a hundred records unrecovered, every one listed with why. No filter, no top-N. And 86 attempts preserved by refusing to act.
>
> That number is an abstraction, so here's its rupee meaning: recoverable subscriptions each arm drove to `halted` — live mandate, recoverable failure, inside both caps, every attempt burned anyway. Baseline kills 27. Sequencer kills 22. Five recurring customers, ₹13,195 a month, still alive next cycle.

**`uv run vasooli demo-trip`** — breaker halts a run.

**`uv run vasooli experiments --seeds 40`** — the part that makes it defensible.

> One seed proves nothing, so I ran forty. Sequencer led in forty of forty, median +114%. Same answer on gross recovery, unadjusted — forty of forty.
>
> Then I tried to break my own thesis. My claim was that timing retries around payday is what pays. So I closed the payday gap to zero — removed every reason for timing to matter — and the advantage barely moved.
>
> That meant my story was wrong. I decomposed it: refusing doomed attempts is 82% of the gain, timing is 18%. The most elaborate part of my engine is the smaller half, and the README says so.
>
> Last section: the reviewer also asked whether my result was really just one seeded hazard — mandates dying between the decision and the debit. So I removed the hazard entirely and re-ran. The gain goes from ₹350 to ₹320. It's 8%.

**`uv run vasooli verify-ledger`** — chain intact. Then tamper one row and re-run to show it locating the break.

## 2:15–3:15 — Architecture and the AI choices

> Detect is rules. Diagnose is where a model earns its place — free-text bank error descriptions, inconsistent English, open vocabulary. Real language problem, Claude Haiku.
>
> But the structured error code is a finite set, so a dictionary answers that, deterministically and for free. The model is only load-bearing on the unmapped tail. On the head I run it on a sample purely to score it against the dict.
>
> And the model is allowed to say "I don't know". Unclassifiable records go to a person. A classifier that always sounds confident spends real retries on failures nobody understood.
>
> Then the important part: **no language model runs in the decision to move money.** Timing is a deterministic scorer over the legal retry window — and it's injected now, not imported, so the fact it currently shares a function with the simulator is a visible default rather than a hidden coupling.
>
> Seven stopping rules and a scheduling rule, each with a test that fails if the rule is deleted — because a deleted stopping rule doesn't crash anything, it just quietly starts burning attempts.
>
> The AI breaker is RunFuse, my own package on PyPI. Honestly though: RunFuse guards the AI side. It doesn't cap rupees. So the money side has its own breaker on the same semantics — and it now distinguishes a *per-debit* limit, which refuses one action and lets the batch continue, from an *aggregate* limit, which stops the run. That distinction matters because a per-debit limit that tripped the batch would truncate the measurement it exists to protect. I know because I shipped that bug once already.

## 3:15–4:25 — What broke

> Twenty-two logged defects. I'll give you three.
>
> **My own circuit breaker was silently doing nothing.** RunFuse prices runs from a model-pricing table. My gateway reported a model that wasn't in it, so it logged "counting cost as $0" and the cost limit could never trip. A limit that looks like protection while accounting zero — exactly the failure mode I wrote RunFuse to catch, and I walked into it with my own library. The env template now points at a priced model, which makes the limit real instead of decorative.
>
> **The same shape came back, twice more.** My `RecoveryPolicy` declared a ₹15,000 per-debit cap and a three-attempt budget, both with comments saying "never exceed" — and enforced neither. Neither field was read anywhere in the codebase. The test file for that module opens with the line "limits that do not trip are decoration".
>
> **And the one I couldn't have found myself.** My late-revocation hazard called the same pure hash function on both code paths, gated by `if arm == "sequencer"` and `if arm == "baseline"`. So it wasn't a fact both arms faced, it was a rule that favoured mine. It's now a function of the record that takes no arm argument at all — and there's a test that parses the AST of the attempt function and fails if the word "arm" ever reappears in it.
>
> The pattern across all twenty-two: nearly every one *looked* like it was working. Several were guardrails that were themselves the hazard. And the five that mattered most came from someone else reading my code — because the thing you're least able to audit is the mechanism your own claim depends on.

## 4:25–4:45 — Close

> Everything measured here is synthetic and the README says exactly which parts are assumption and which are real Razorpay test-mode calls — a Plan, a Subscription and Orders, created for real. Activation needs the customer to authenticate the mandate, and this batch job deliberately doesn't do that on their behalf.
>
> The absolute rupee figure isn't a production claim. The comparison is, because both arms face identical records and identical random draws — if my thesis were wrong, the sequencer would lose on the same draws.
>
> 227 tests, hermetic. 92% coverage. Every decision hash-chained.
>
> Retries are a budget of three. Vasooli spends them on the failures that can actually be recovered, refuses the ones that can't — loudly and on the record — and gives every rupee it refuses somewhere to go.
>
> The live interface is at the link in the description — every page is the real output of this batch, including a chain you can try to tamper with yourself.

---

## Notes

- Do **not** claim production numbers. The synthetic framing is a strength here.
- **The compliance beat is now a correction story, and it is stronger than the original.** "I had the right finding for the wrong reason, and fixing it made the finding sharper" beats "look at my number". Don't rush it.
- The escalation queue is the answer to the track's "compliant escalation" bar. Show it on the web page, not the terminal — it reads better.
- Have the tampered-ledger demo pre-staged; don't type SQL live.
- If asked about the ablation showing ₹0 above-cap on every row: that is the point, say it as defence in depth and show the refusals column moving.
