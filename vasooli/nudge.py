"""Draft a customer message. Never send one.

WHY THIS IS THE SECOND PLACE A MODEL BELONGS

Classification reads what a bank wrote. This writes what a customer reads, and
that is the other genuine language problem in the system: a message to an Indian
subscriber whose autopay just failed should sound like a person, in the register
they actually use, and neither a template nor a dictionary does that well.

WHY IT STILL DOES NOT DECIDE ANYTHING

`decide.py` has already determined that this record warrants a nudge and why.
The model receives that decision and writes prose for it. It cannot choose to
nudge a customer the engine did not flag, cannot change the amount, and cannot
change what happens next. It is a writer working from a brief.

THE GUARDRAILS, AND WHY EACH ONE EXISTS

A model writing customer-facing text about money can cause real harm in ways a
classifier cannot, so its output is checked rather than trusted:

  * No URLs. A model that invents a payment link has invented a phishing target.
    Any draft containing one is rejected outright rather than cleaned up.
  * No invented figures. The amount is substituted after generation from the
    record, so the model never has to get a number right.
  * No promises. Drafts claiming a refund, a waiver, a deadline extension or a
    consequence ("account will be closed") are rejected — those are commitments
    a merchant makes, not a model.
  * Bounded length. Anything long enough to bury a term is too long.

NOTHING IS SENT

There is no send path in this module, and there is no configuration that adds
one. Drafts are written to the audit trail for a person to review. Sending is a
decision with a recipient, a channel and a consent question attached, and none
of those belong to an unattended batch.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any

from .decide import Action, Decision
from .ledger import Ledger
from .models import AtRiskRecord

if TYPE_CHECKING:
    from openai import OpenAI

#: Longer than this and a term could be buried in it.
MAX_CHARS = 320

#: Anything that looks like a link. Checked before a draft is ever stored.
_URL = re.compile(r"(https?://|www\.|\.com|\.in\b|bit\.ly|rzp\.io)", re.IGNORECASE)

#: Commitments a merchant makes, not a model. Matching drafts are rejected.
_PROMISES = re.compile(
    r"\b(refund|waive[dr]?|discount|free|cashback|guarantee|"
    r"will be (closed|terminated|suspended|blocked)|legal action|penalt)",
    re.IGNORECASE,
)

#: Placeholder the model is told to use. Substituted from the record afterwards,
#: so a wrong number is structurally impossible rather than merely unlikely.
AMOUNT_TOKEN = "{amount}"

#: Any digit the model wrote itself. The first version of this guardrail
#: required the placeholder to be PRESENT, which rejected three perfectly safe
#: drafts in six for the crime of not mentioning the amount at all — a message
#: without a figure is fine. The risk was always the opposite: a figure the
#: model made up. This catches that and lets the harmless case through.
_STRAY_DIGIT = re.compile(r"\d")

SYSTEM_PROMPT = f"""You write short SMS/WhatsApp messages to Indian subscribers \
whose recurring autopay payment has failed.

Register: natural Hinglish — the everyday mix of Hindi and English an Indian \
customer support agent actually uses. Roman script only, never Devanagari. \
Warm and matter-of-fact, never pushy, never guilt-tripping.

Hard rules:
- Write the amount as exactly {AMOUNT_TOKEN}. Never write a number yourself.
- Never include a link, URL, phone number or app name.
- Never promise a refund, waiver, discount, extension or any consequence.
- Never threaten. No account closure, no penalties, no legal language.
- One or two sentences. Under 40 words.
- No greeting line, no sign-off, no emoji.

Say what happened and what the customer can do. Nothing else."""

REASON_BRIEF = {
    "MANDATE_REVOKED": "their autopay mandate was cancelled, so a new one is needed",
    "MANDATE_EXPIRED": "their autopay mandate has expired and needs to be set up again",
    "MANDATE_PAUSED": "their autopay mandate is paused and needs to be resumed",
    "LIMIT_EXCEEDED": "the amount is above the limit set on their autopay mandate",
    "INSUFFICIENT_FUNDS": "the payment did not go through due to low balance",
    "BANK_DOWNTIME": "their bank could not be reached when the payment was tried",
    "TECHNICAL_ERROR": "a temporary technical issue stopped the payment",
    "UNKNOWN": "the payment did not go through",
}


class NudgeRejected(Exception):
    """A draft failed a guardrail and was discarded rather than repaired."""


def check_draft(text: str) -> str:
    """Validate a draft. Raises NudgeRejected rather than sanitising.

    Repairing a bad draft would hide how often the model produces one. A
    rejection is a fact worth counting.
    """
    t = text.strip().strip('"')
    if not t:
        raise NudgeRejected("empty draft")
    if len(t) > MAX_CHARS:
        raise NudgeRejected(f"too long ({len(t)} chars, limit {MAX_CHARS})")
    if _URL.search(t):
        raise NudgeRejected("contains something link-shaped")
    if _PROMISES.search(t):
        raise NudgeRejected("contains a promise or threat the merchant has not made")
    # Strip the placeholder before looking for digits, so the one legitimate
    # number in the message does not trip the check that exists to catch
    # illegitimate ones.
    without_token = t.replace(AMOUNT_TOKEN, "")
    if _STRAY_DIGIT.search(without_token):
        raise NudgeRejected("wrote a figure of its own instead of the placeholder")
    return t


def render(draft: str, rec: AtRiskRecord) -> str:
    """Substitute the real amount. The model never handles the figure itself."""
    return draft.replace(AMOUNT_TOKEN, f"Rs {rec.amount_paise / 100:,.0f}")


def draft_one(client: OpenAI, rec: AtRiskRecord, decision: Decision) -> str:
    """One draft, validated. Raises NudgeRejected if it fails a guardrail."""
    brief = REASON_BRIEF.get(
        decision.verdict.split(":")[0].strip().upper(), "the payment did not go through"
    )
    for fc, text in REASON_BRIEF.items():
        if fc in decision.verdict:
            brief = text
            break

    resp = client.chat.completions.create(
        model=os.environ.get("VASOOLI_LLM_MODEL", "kr/claude-haiku-4.5"),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"Situation: {brief}.\n"
                f"This is a subscription payment. Write the message."
            )},
        ],
        max_tokens=120,
        temperature=0.6,
    )
    return check_draft(resp.choices[0].message.content or "")


def draft_batch(
    pairs: list[tuple[AtRiskRecord, Decision]],
    ledger: Ledger,
    *,
    run_id: str,
    use_llm: bool = True,
    limit: int | None = None,
) -> dict[str, Any]:
    """Draft messages for every record the engine flagged, and store them.

    Returns counts, including how many drafts were rejected by a guardrail —
    that number is the point of having the guardrails, so it is reported rather
    than swallowed.
    """
    wanted = [(r, d) for r, d in pairs if d.wants_nudge]
    if limit is not None:
        wanted = wanted[:limit]

    stats = {"flagged": len(wanted), "drafted": 0, "rejected": 0, "unavailable": 0}
    if not wanted:
        return stats

    client = None
    if use_llm:
        try:
            from .diagnose import _client
            client = _client()
        except Exception:  # noqa: BLE001 - containment boundary
            client = None

    for rec, dec in wanted:
        if client is None:
            stats["unavailable"] += 1
            continue
        try:
            text = render(draft_one(client, rec, dec), rec)
        except NudgeRejected as e:
            stats["rejected"] += 1
            ledger.append(
                run_id=run_id, arm="nudge", event="nudge_rejected",
                verdict=f"draft discarded by a guardrail — {e}",
                subscription_id=rec.subscription_id,
            )
            continue
        except Exception as e:  # noqa: BLE001 - containment boundary
            stats["unavailable"] += 1
            ledger.append(
                run_id=run_id, arm="nudge", event="nudge_unavailable",
                verdict=f"drafting failed and was recorded, not retried — {e}"[:200],
                subscription_id=rec.subscription_id,
            )
            continue

        stats["drafted"] += 1
        ledger.append(
            run_id=run_id, arm="nudge", event="nudge_drafted",
            verdict=(f"drafted for review, NOT SENT — {dec.action.value} on "
                     f"Rs {rec.amount_paise / 100:,.2f}"),
            subscription_id=rec.subscription_id,
            draft=text, action=dec.action.value,
        )

    return stats


def wants_nudge_count(pairs: list[tuple[AtRiskRecord, Decision]]) -> dict[str, int]:
    """How the flagged set breaks down by decision, for the report."""
    out: dict[str, int] = {}
    for _, d in pairs:
        if d.wants_nudge:
            key = d.action.value if isinstance(d.action, Action) else str(d.action)
            out[key] = out.get(key, 0) + 1
    return out
