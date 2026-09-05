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
