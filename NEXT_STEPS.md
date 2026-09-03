# Next steps

Everything originally listed here has been built. What follows is the record of
what each item turned out to be worth — including the two that produced negative
results — and what is genuinely left.

---

## Done

| # | Item | What it actually produced |
|---|---|---|
| 1.1 | Seed sweep | 40/40 wins, median +126.2%, worst +52.2%. Also **found a bug**: every seed shared identical luck, because the draw keyed only on subscription id and those repeat across seeds. Salted with the seed; headline numbers moved. |
| 1.2 | Sensitivity | Closing the payday gap to zero barely dented the advantage — which **contradicted the project's own story** and led directly to 1.2b. |
| 1.2b | Attribution | Refusal is **83%** of the gain, timing **17%**. The most elaborate part of the engine is the smaller half. README rewritten to lead with refusal. |
| 1.3 | Rule ablation | Rule 3 costs most to remove. Rule 6 is the only one whose removal breaches the cap (₹86,599). **Rule 7 does nothing on this data** — reported, not dropped. |
| 2.1 | Hinglish nudge drafter | Built with guardrails. The first version of the figure guardrail was wrong in the dangerous direction and discarded 3 safe drafts in 6; inverted to catch invented numbers instead. No send path exists, and a test enforces that. |
| 2.2 | Promise-to-pay | A promise may move a retry **later and nothing else**. Trust decays after two broken promises. |
| 2.3 | Webhook ingestion | Signature before parsing, `compare_digest`, replay rejection, and missing information never widens the envelope. **Found a bug**: Razorpay's UTC timestamps were being read in local time. |
| 3.1 | Learned retry timing | **Negative result.** The bandit loses to the heuristic in both worlds. In-distribution the heuristic is an *oracle*, so losing there is arithmetic; the deficit narrows monotonically as assumptions degrade but never crosses zero. Not wired into `decide.py`, and a test enforces that. |
| 3.2 | Calibration | Reported, and labelled as internal consistency only — predictions and outcomes come from the same assumed model. |
| 4.1 | CI | Engine and web. Deliberately given **no credentials**, so a test that starts needing one fails there. |
| 4.2 | Coverage | 90% floor, currently 93%. |
| 4.3 | Keyed ledger | HMAC-SHA256. Unkeyed it reports "tamper-evident", not "tamper-proof", in those words. |
| 4.4 | Property tests | 11 invariants × 300 generated examples. No violations. |
| 4.5 | Structured logging | Deliberately minimal — the ledger is already the record of decisions, and two accounts of one event that can disagree is worse than one. |
| 5.2/5.3 | Policy comparison | Real engine runs, not projections. No "what if" slider, on purpose. |
| 5.4 | Accessibility | Attempt grid `aria-hidden` with a text equivalent. All text WCAG AA, measured. |

Also fixed along the way, both found by building the above rather than by looking
for them: the compliance-adjusted headline contained a raw number (mixing two
bases in one table), and the same bug existed independently in the interface.

---

## Left

### 5.1 Deploy the site — one decision away

Both paths are configured and verified:

- **GitHub Pages.** `.github/workflows/pages.yml` is committed and inert until
  Pages is enabled at *Settings → Pages → Source: GitHub Actions*. The build is
  verified with `NEXT_PUBLIC_BASE_PATH=/Vasooli`, which Pages needs because it
  serves from `/<repo>` rather than the domain root. Local builds are unaffected.
- **Vercel.** `output: "export"` with no base path. Point Vercel at `web/` and it
  works with no further configuration.

Not done because publishing is outward-facing and changes settings on your
accounts. One decision, then it is live.

### Genuinely open, in order of value

**Parse promises from free text.** `promise.py` takes structured promises. A
customer replies "salary 5th ko aa raha hai" and extracting a date from that is a
real language problem and the natural third place for the model. The module
states plainly that it does not do this yet.

**Feed real outcomes to the bandit.** The negative result says learning pays only
once assumptions are badly wrong. Finding out whether they are needs production
data, not more simulation — this is blocked on data, not on effort, and no amount
of further simulator work will resolve it.

**Anchor the ledger externally.** The chain is now unforgeable without the key,
but a holder of the key can still rebuild it. Periodically publishing the root
hash somewhere append-only would close that.

**Exercise rule 7 with a batch.** It is covered by a test and by property tests,
but no seeded batch has ever triggered it. A seed generator that produces
mandates expiring inside the notice window would prove it fires in situ.

**Multi-currency and multi-region.** Everything is paise and RBI. The stopping
rules are India-shaped by design, and generalising them is a real piece of work
rather than a config change.

---

## Still deliberately not doing

- **A database behind the web app.** The interface is a viewer over one exported
  run. A live query path would let it show a number the engine never produced.
- **Authentication or multi-tenancy.** There is no second user.
- **Sending anything to a customer.** Drafts are stored for review. That boundary
  is the design, not a time constraint.
- **Automating Razorpay checkout to activate a mandate.** A machine completing
  consent on a human's behalf is what the stopping rules refuse everywhere else.
- **More seeded records.** 100 exercises every rule and every hazard. 10,000 would
  make the numbers bigger without making them more true.
