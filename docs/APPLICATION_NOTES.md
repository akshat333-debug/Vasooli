# Application notes

Not part of the project's design. Kept here because it's genuinely useful and
belongs somewhere durable rather than only in chat history.

## Scam warning (from Razorpay, via the official buildathon page)

Razorpay only contacts candidates through:

- official email addresses ending in `@razorpay.com` or `@f5.com`
- auto-notifications from Workday

Any message from another address claiming to be Razorpay or the Buildathon is
almost certainly a scam. Razorpay never charges candidates for hiring — don't
share personal information, pay a fee, or click a suspicious link.
Report anything odd to Razorpay directly.

## Panel prep: answers to the questions that will actually be asked

**"How would you scale this to 10x volume?"**

The batch path is fine — 100 records is 0.4s, and it is linear in records with
no per-record I/O beyond one ledger append. The webhook path is where it
breaks, and it breaks in a specific, known place: `prior_failures()` and the
replay check in `ingest()` are each a full-table ledger scan, so one delivery
costs 2n. At 453 rows that is free; at a million it is the whole latency
budget. Fix is an index on `(event, subscription_id)`, which turns both into
lookups, plus a per-subscription counter row to remove one scan entirely. It is
a schema migration, not a redesign. The ceiling is written into `webhook.py` as
a comment rather than left to be discovered.

Second bottleneck at volume is the LLM stage, but only on the unmapped tail —
the dictionary handles the head for free and never calls out. On this batch the
model sees 4 records out of 100.

**"What happens when the LLM is unavailable?"**

Classification degrades to the dictionary; anything it cannot name becomes
`UNKNOWN`, which routes to human review. No money decision is affected because
no model participates in one. Demonstrated live: the AI-stage RunFuse breaker
trips on 10 errors and the run continues on the dictionary, and both the report
and `vasooli diagnose` say so rather than reporting a working model.

**"Show me a case where your system fails."**

Two, both already published. The scheduler is over-confident by 0.14 in its top
probability bucket — most wrong exactly where it is most sure. And rule 7 has
never fired on a seeded batch; it is covered by tests only. Both are in
README §17 and the second is in the ablation table as a row that does nothing.

**"Your headline is +112.5% but the money recovered differs by 2.3%."**

Correct, and the README leads with the recurring number for that reason. Both
arms recover about the same money in one cycle. The baseline pays 160 attempts
for it and this pays 77, and because the retry budget is three deep and
terminal, the 83-attempt difference is five subscriptions that stay alive —
₹13,195/month of recurring revenue against a one-cycle difference of ₹1,304.
The per-attempt ratio is the efficiency statistic; the recurring revenue is the
result.

## Submission checklist (unofficial, cross-referenced against this repo)

Structural asks a reviewer's checklist is likely to look for, and where each
one lives here:

| Ask | Where |
|---|---|
| Public repo | `github.com/akshat333-debug/Vasooli` |
| README: description, architecture, setup, demo, limitations | `README.md`, all sections |
| Pinned dependency versions | `requirements.txt` (Python, generated from `uv.lock`), `web/package-lock.json` (JS) |
| `.env.example`, no real keys | `.env.example` |
| Organised source, not one file | `vasooli/` (18 modules), `web/src/` |
| Tests | `tests/` — 229 tests, 92% coverage |
| Sample/synthetic data | `data/` |
| Architecture notes | `docs/ARCHITECTURE.md` |
| Live, runnable demo | <https://akshat333-debug.github.io/Vasooli/> |
