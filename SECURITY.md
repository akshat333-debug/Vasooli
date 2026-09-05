# Security

Vasooli is a buildathon submission, not a production payment system. It never
moves real money: `vasooli live` makes real API calls, but only to a
**Razorpay test-mode** account, and the batch engine runs entirely on synthetic
data (`vasooli/sim/`).

## What is actually in scope

- **Webhook signature verification** (`vasooli/webhook.py`) uses
  `hmac.compare_digest` against `RAZORPAY_WEBHOOK_SECRET` and refuses rather
  than trusts when that secret is unset. See `tests/test_webhook.py`.
- **The audit ledger** (`vasooli/ledger.py`) is a hash-chained SQLite log.
  Unkeyed, it detects accidental corruption; set `VASOOLI_LEDGER_KEY` to make
  the chain HMAC-keyed, which also detects a deliberate rewrite by someone with
  write access to the database file. Neither mode is a substitute for an
  external, append-only checkpoint in a real deployment.
- **No customer message is ever sent.** `vasooli nudge` drafts and logs
  customer-facing text; there is no send path in this repository.
- **Secrets** live in `.env` (gitignored) and are read via `os.environ`,
  never hardcoded. `.env.example` documents every variable without values.

## Known limitations (not vulnerabilities, but relevant if you fork this)

Documented in [`README.md §17`](README.md) and [the Method page](https://akshat333-debug.github.io/Vasooli/method/):
the webhook ingestion path is not idempotent under concurrent writers, and
`prior_failures()` / the replay check are full-table scans that do not scale
past a demo-sized ledger. Neither is exploitable in the current deployment —
there is no publicly reachable webhook endpoint — but both would need fixing
before this became a live integration.

## Reporting

This is a solo hackathon project with no users and no production deployment.
If you find something concerning anyway, open a
[GitHub issue](https://github.com/akshat333-debug/Vasooli/issues) or reach the
author at the email on their GitHub profile. Please don't test against
anything other than your own fork or the public demo's static pages — there is
no backend to attack.
