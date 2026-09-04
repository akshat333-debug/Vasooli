"""Failure diagnosis: raw gateway error -> canonical FailureClass.

WHERE THE LLM SITS, AND WHY IT SITS THERE

The structured error pair (code, reason) is machine-generated and finite. A dict
handles it perfectly, deterministically, for free. Putting a language model in
front of a lookup table would be worse in every dimension that matters here:
slower, costlier, non-reproducible, and capable of being wrong about something a
dict is incapable of being wrong about.

So the dict is authoritative wherever it has an answer.

The LLM earns its place on the tail: error_reason values absent from CODE_MAP,
where all that is left is a free-text description written by a bank, in
inconsistent English, that does not restate the code. That is a genuine natural
language problem and there is no dict that solves it.

Two guardrails on the LLM's output:

  1. It may only return a member of FailureClass. Anything else becomes UNKNOWN.
  2. It is explicitly instructed to answer UNKNOWN when unsure, and UNKNOWN routes
     to a human. A classifier that always produces a confident label would spend
     retries on failures nobody actually understood.

On the head of the distribution the LLM is not needed at all, so it is run only
on a SAMPLE, purely to be scored against the dict. That agreement number goes in
the report as a check on the model. Sampling rather than classifying all 100 is
deliberate: calling a model where a dict already has the answer is spend with no
decision attached to it.
"""

from __future__ import annotations

import os
import random
from typing import Any

from openai import OpenAI
from runfuse import Fuse, FusePolicy, FuseTripped

from .logging import problem, timed
from .models import AtRiskRecord, Diagnosis
from .taxonomy import FailureClass, classify_by_code

_ALLOWED = {fc.value for fc in FailureClass}

SYSTEM_PROMPT = """You classify failed recurring-payment (mandate/AutoPay) debits \
for an Indian payment processor.

Return EXACTLY ONE of these labels and nothing else:
INSUFFICIENT_FUNDS - the customer's account lacked balance
BANK_DOWNTIME - the bank or PSP was unreachable or not responding
TECHNICAL_ERROR - a transient gateway/timeout fault, no money moved
MANDATE_REVOKED - the customer cancelled or withdrew the mandate
MANDATE_EXPIRED - the mandate is past its validity period
MANDATE_PAUSED - the mandate is temporarily paused
LIMIT_EXCEEDED - the amount exceeds a limit registered on the mandate
UNKNOWN - you cannot tell with confidence

Answering UNKNOWN is correct and expected when the text is ambiguous. A wrong \
confident label causes a real retry to be spent on a debit that cannot succeed. \
Prefer UNKNOWN over a guess.

Output the label only. No punctuation, no explanation."""


def _policy() -> FusePolicy:
    """Bound the diagnosis stage.

    NOTE on cost limits, verified empirically rather than assumed:

    RunFuse prices a run from its own model pricing table. The gateway reports
    the model as 'claude-haiku-4.5', which is not in that table, so RunFuse warns
    "no pricing for model ... counting cost as $0" and max_cost_usd NEVER TRIPS.
    It is declared below for documentation, but it is inert here. Do not read it
    as a working guardrail.

    Separately, the gateway prepends ~4.1k tokens of its own system prompt to
    every call, so max_total_tokens would also not mean what it appears to mean.

    The limits that actually bind on this deployment are max_steps (exact, one
    call per record) and max_llm_errors (exact). Those are the real protection.

    This is exactly the failure mode RunFuse was written to prevent - a limit
    that looks like it is protecting you while silently accounting $0 - and it
    caught itself. Documented rather than hidden.
    """
    return FusePolicy(
        name="vasooli-diagnose",
        max_steps=250,          # one call per record, with headroom
        max_llm_errors=10,      # a retry storm against the gateway is a bug
        max_wall_time_s=300.0,
        max_cost_usd=2.00,
    )


def _client() -> OpenAI:
    return OpenAI(
        base_url=os.environ.get("VASOOLI_LLM_BASE_URL", "http://localhost:20128/v1"),
        api_key=os.environ.get("VASOOLI_LLM_API_KEY", ""),
    )


def _ask_llm(client: OpenAI, rec: AtRiskRecord) -> tuple[FailureClass, bool]:
    """One classification call. Returns (class, reached_the_model).

    A network error, a gateway 500, or a malformed response all resolve to
    UNKNOWN, which routes the record to a human. Nothing here may raise into the
    batch: a classifier that cannot answer is a record a person looks at, not a
    run that dies.

    The second element of the tuple exists because "the model answered UNKNOWN"
    and "the model was unreachable" are different facts, and collapsing them
    into one made the report lie. With the gateway down, the run counted 20
    disagreements — as if a working model had given 20 different answers —
    rather than 24 failed calls.

    FuseTripped is deliberately NOT caught. It is not a call failure; it is the
    guardrail deciding the stage should stop. Swallowing it here turned every
    subsequent record into a silent UNKNOWN and left the trip out of the report
    entirely. It belongs to the caller, which records it and degrades the whole
    remaining batch to the dictionary in one visible step.
    """
    user = (
        f"Bank: {rec.bank}\n"
        f"Method: {rec.method.value}\n"
        f"Gateway code: {rec.error_code}\n"
        f"Gateway reason: {rec.error_reason}\n"
        f"Description from the bank: {rec.error_description}"
    )
    try:
        resp = client.chat.completions.create(
            model=os.environ.get("VASOOLI_LLM_MODEL", "kr/claude-haiku-4.5"),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            max_tokens=12,
            temperature=0,
        )
        raw = (resp.choices[0].message.content or "").strip().upper()
    except FuseTripped:
        # The guardrail speaking, not a failed call. Belongs to the caller.
        raise
    except Exception:  # noqa: BLE001 - containment boundary, see docstring
        # Deliberately broad. This is a containment boundary, not error handling:
        # anything at all that goes wrong in the AI stage becomes "ask a human"
        # rather than an exception crossing into the money stage.
        return FailureClass.UNKNOWN, False
    return (FailureClass(raw) if raw in _ALLOWED else FailureClass.UNKNOWN), True


def diagnose_batch(
    records: list[AtRiskRecord],
    *,
    use_llm: bool = True,
    head_sample: int = 20,
    sample_seed: int = 42,
) -> tuple[list[Diagnosis], dict[str, Any]]:
    """Diagnose a batch. Returns (diagnoses, agreement stats).

    Resolution order, and the reason for it:
      * dict has an answer  -> dict wins. Deterministic beats probabilistic when
        both are available.
      * dict says UNKNOWN   -> the LLM's answer is used. This is the tail the
        LLM exists for.
      * no LLM available    -> UNKNOWN stands, and the record goes to a human.
        The system degrades to "ask a person", never to "guess".

    The LLM is called on every tail record (it is load-bearing there) and on a
    seeded sample of `head_sample` mapped records (scoring only).
    """
    stats: dict[str, Any] = {
        "llm_calls": 0, "agree": 0, "disagree": 0, "llm_rescued": 0, "unknown": 0,
        "llm_errors": 0,
    }
    out: list[Diagnosis] = []

    # Building the client or the fuse can fail — missing credentials, a bad base
    # URL, a RunFuse version whose wrap() signature moved. None of that is a
    # reason to lose the batch: the dict still classifies the head, and the tail
    # becomes human review. Degrade, record why, continue.
    client, fuse = None, None
    if use_llm:
        try:
            client = _client()
            fuse = Fuse(_policy())
            client = fuse.wrap(client)
        except Exception as e:  # noqa: BLE001 - containment boundary, see above
            stats["degraded"] = 1
            stats["degraded_reason"] = str(e)[:200]
            client, fuse = None, None
            problem("diagnose.degraded", reason=str(e)[:200])

    # Seeded sample of mapped records to score the model against the dict.
    mapped = [r.subscription_id for r in records
              if classify_by_code(r.error_code, r.error_reason) is not FailureClass.UNKNOWN]
    scored = set(random.Random(sample_seed).sample(mapped, min(head_sample, len(mapped))))

    def _run(rec: AtRiskRecord) -> Diagnosis:
        deterministic = classify_by_code(rec.error_code, rec.error_reason)

        if client is None:
            fc, source, why = deterministic, "code_map", "LLM disabled; dict only"
            if fc is FailureClass.UNKNOWN:
                why = "unmapped error code and no classifier available - human review"
            return Diagnosis(subscription_id=rec.subscription_id, failure_class=fc,
                             source=source, rationale=why)

        if deterministic is not FailureClass.UNKNOWN:
            # Dict is authoritative here. Call the model only on the sample, and
            # only to score it - its answer is never obeyed on the head.
            if rec.subscription_id not in scored:
                return Diagnosis(
                    subscription_id=rec.subscription_id, failure_class=deterministic,
                    source="code_map", rationale="code_map authoritative; llm not consulted",
                )
            llm, reached = _ask_llm(client, rec)
            stats["llm_calls"] += 1
            if not reached:
                # Unreachable is not disagreement. Scoring a model that never
                # answered would report a false accuracy signal.
                stats["llm_errors"] += 1
                note = "llm unreachable"
            elif llm == deterministic:
                stats["agree"] += 1
                note = f"llm agreed ({llm.value})"
            else:
                stats["disagree"] += 1
                note = f"llm said {llm.value}"
            return Diagnosis(
                subscription_id=rec.subscription_id,
                failure_class=deterministic,
                source="code_map",
                rationale=f"code_map authoritative; {note}",
            )

        # Tail: the model is load-bearing here.
        llm, reached = _ask_llm(client, rec)
        stats["llm_calls"] += 1
        if not reached:
            stats["llm_errors"] += 1

        # The tail: only the free text can settle this.
        if llm is not FailureClass.UNKNOWN:
            stats["llm_rescued"] += 1
            return Diagnosis(
                subscription_id=rec.subscription_id, failure_class=llm, source="llm",
                rationale=f"unmapped code '{rec.error_reason}'; classified from description",
            )

        stats["unknown"] += 1
        return Diagnosis(
            subscription_id=rec.subscription_id, failure_class=FailureClass.UNKNOWN,
            source="llm", rationale="neither dict nor model could classify - human review",
        )

    if fuse:
        try:
            with fuse.run("diagnose-batch"), timed("diagnose.batch", records=len(records)):
                # Appended one at a time, deliberately. This was a list
                # comprehension, and a comprehension is atomic: when the fuse
                # tripped partway through, `out` was never rebound and stayed
                # empty, so every record classified before the trip was silently
                # thrown away and re-run through the dictionary. The comment
                # below claimed those records were kept and they were not, and
                # `classified_before_trip` logged 0 on every single trip.
                for rec in records:
                    out.append(_run(rec))
        except Exception as e:  # noqa: BLE001 - containment boundary
            # A RunFuse trip or internal fault must not destroy the batch. The
            # guardrail exists to bound the AI stage, not to be able to kill the
            # money stage — a limit that can take down more than it protects is
            # a worse failure than the one it was guarding against.
            #
            # Records already classified ARE kept, including anything the model
            # rescued from UNKNOWN before the trip. The remainder fall back to
            # the dictionary, which needs no model, and anything the dictionary
            # cannot name becomes human review.
            stats["fuse_aborted"] = 1
            stats["fuse_reason"] = str(e)[:200]
            problem("diagnose.fuse_aborted", reason=str(e)[:200],
                    classified_before_trip=len(out))
            done = {d.subscription_id for d in out}
            client = None  # force the dict-only path in _run
            out = out + [_run(r) for r in records if r.subscription_id not in done]
    else:
        out = [_run(r) for r in records]

    return out, stats
