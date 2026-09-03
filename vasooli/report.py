"""Batch reporting. The exception list is not optional output.

Two rules this module exists to enforce:

  1. The headline comparison is COMPLIANCE-ADJUSTED. A naive retry loop can
     always beat a bounded one on gross recovery by doing things it is not
     allowed to do. Reporting raw totals side by side would credit the baseline
     for debits above the RBI standard cap, which no merchant may make
     unattended. Both the raw and the adjusted numbers are printed; the adjusted
     one is the claim.

  2. Every unrecovered record appears in the exception list, grouped by the
     reason it was not recovered. There is no filter, no top-N, and no
     "interesting cases only". A recovery report that shows the wins and hides
     the rest is marketing.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .execute import BatchResult
from .models import AtRiskRecord


def _rs(paise: float) -> str:
    return f"Rs {paise / 100:,.2f}"


def compliance_split(result: BatchResult, records: list[AtRiskRecord]) -> tuple[int, int]:
    """(recovered within the unattended envelope, recovered by exceeding it)."""
    by = {r.subscription_id: r for r in records}
    within = over = 0
    for o in result.outcomes:
        if not o.recovered:
            continue
        if by[o.subscription_id].needs_human_approval:
            over += o.amount_paise
        else:
            within += o.amount_paise
    return within, over


def render(
    baseline: BatchResult,
    sequencer: BatchResult,
    records: list[AtRiskRecord],
    *,
    ledger_ok: bool,
    ledger_rows: int,
    llm_stats: dict[str, Any] | None = None,
) -> str:
    b_in, b_over = compliance_split(baseline, records)
    s_in, s_over = compliance_split(sequencer, records)
    at_risk = sequencer.value_at_risk_paise
    L: list[str] = []
    add = L.append

    add("=" * 78)
    add("VASOOLI - BOUNDED SUBSCRIPTION RECOVERY - BATCH REPORT")
    add("=" * 78)
    add("")
    add("SYNTHETIC DATA. Outcomes come from a seeded assumption-driven model")
    add("(vasooli/sim/model.py), not from real banks. The comparison between arms")
    add("is meaningful because both face identical records and identical random")
    add("draws. The absolute rupee figures are NOT a claim about production.")
    add("")
    add(f"Records at risk : {sequencer.records}")
    add(f"Value at risk   : {_rs(at_risk)}")
    add("")

    if baseline.truncated or sequencer.truncated:
        add("!" * 78)
        add("INCOMPLETE RUN - THE NUMBERS BELOW ARE NOT A RESULT")
        add("!" * 78)
        for r in (baseline, sequencer):
            if r.truncated:
                add(f"  {r.arm}: processed {r.records_processed} of {r.records} records "
                    f"before the batch breaker stopped it")
                add(f"    {r.tripped}")
        add("")
        add("  Totals are computed over a prefix of the batch while 'value at risk'")
        add("  counts every record, so the rates below are measured against a")
        add("  denominator that was never attempted. Raise the breaker ceiling and")
        add("  re-run before quoting any of this.")
        add("")

    add("-" * 78)
    add("HEADLINE - compliance-adjusted (what automation may lawfully do alone)")
    add("-" * 78)
    add(f"  {'':22}{'baseline':>16}{'sequencer':>16}{'delta':>16}")
    add(f"  {'recovered':22}{_rs(b_in):>16}{_rs(s_in):>16}{_rs(s_in - b_in):>16}")
    add(f"  {'attempts spent':22}{baseline.attempts_spent:>16}{sequencer.attempts_spent:>16}"
        f"{sequencer.attempts_spent - baseline.attempts_spent:>16}")
    add(f"  {'wasted attempts':22}{baseline.wasted_attempts:>16}{sequencer.wasted_attempts:>16}"
        f"{sequencer.wasted_attempts - baseline.wasted_attempts:>16}")
    # Per-attempt must use the SAME basis as the row above it. This section is
    # compliance-adjusted, so the numerator excludes debits outside the
    # unattended envelope for both arms. Dividing raw recovery by attempts here
    # -- which is what this line used to do -- credited the baseline with the
    # very debit the row above had just removed, mixing two bases inside one
    # table and understating the gap.
    bpa = (b_in / baseline.attempts_spent) if baseline.attempts_spent else 0.0
    spa = (s_in / sequencer.attempts_spent) if sequencer.attempts_spent else 0.0
    add(f"  {'recovered / attempt':22}{_rs(bpa):>16}{_rs(spa):>16}{_rs(spa - bpa):>16}")
    add("")
    add("  Headline metric is recovery per attempt, because the retry budget is")
    add("  the scarce resource - three attempts, then the subscription halts.")
    add("")

    add("-" * 78)
    add("RAW TOTALS - shown for honesty, not as the claim")
    add("-" * 78)
    add(f"  baseline  recovered {_rs(baseline.value_recovered_paise)}"
        f"  (of which {_rs(b_over)} came from debits above the RBI standard cap)")
    add(f"  sequencer recovered {_rs(sequencer.value_recovered_paise)}"
        f"  (of which {_rs(s_over)} came from debits above the RBI standard cap)")
    rb = baseline.paise_per_attempt
    rs_ = sequencer.paise_per_attempt
    add(f"  raw recovered / attempt: baseline {_rs(rb)}, sequencer {_rs(rs_)}")
    add("  (both numerators include above-cap debits; shown so the adjusted")
    add("   headline above can be checked against the unadjusted figures)")
    if b_over > s_over:
        add("")
        add("  NOTE: the baseline's raw total is higher only because it made")
        add("  unattended debits above the cap. Those are not recoveries a merchant")
        add("  may bank; they are compliance failures. Hence the adjusted headline.")
    add("")

    add("-" * 78)
    add("EXCEPTION LIST - every record not recovered by the sequencer")
    add("-" * 78)
    groups: dict[str, list] = defaultdict(list)
    for o in sequencer.outcomes:
        if not o.recovered:
            groups[o.terminal_reason.split(" - ")[0].split(" — ")[0]].append(o)
    total_unrec = sum(len(v) for v in groups.values())
    total_value = sum(o.amount_paise for v in groups.values() for o in v)
    for reason, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        val = sum(o.amount_paise for o in items)
        add(f"  {len(items):>4}  {_rs(val):>14}   {reason}")
    add("")
    add(f"  {total_unrec} of {sequencer.records} records unrecovered, {_rs(total_value)} still at risk.")
    add(f"  Attempts preserved by refusing to act: "
        f"{sum(o.attempts_preserved for o in sequencer.outcomes if not o.recovered)}")
    add("")

    add("-" * 78)
    add("FAILURE MIX")
    add("-" * 78)
    for cls, n in Counter(o.failure_class.value for o in sequencer.outcomes).most_common():
        rec = sum(1 for o in sequencer.outcomes if o.failure_class.value == cls and o.recovered)
        add(f"  {cls:22} {n:>4} records, {rec:>3} recovered")
    add("")

    if llm_stats:
        add("-" * 78)
        add("AI USAGE")
        add("-" * 78)
        checked = llm_stats["agree"] + llm_stats["disagree"]
        errs = llm_stats.get("llm_errors", 0)
        add(f"  LLM calls made               : {llm_stats['llm_calls']}")
        if errs:
            add(f"  Calls that never reached it  : {errs}  <-- model unreachable")
        if checked:
            add(f"  Agreement with the dict      : {llm_stats['agree']}/{checked}"
                f" (sampled head, scoring only)")
        else:
            add("  Agreement with the dict      : not measured (no call succeeded)")
        add(f"  Records classified by the LLM: {llm_stats['llm_rescued']} (unmapped tail)")
        add(f"  Left UNKNOWN -> human review : {llm_stats['unknown']}")
        add("  No language model participated in any decision to move money.")
        if llm_stats.get("degraded"):
            add("")
            add("  DEGRADED: the model was unavailable and the run fell back to the")
            add("  dictionary alone. Unmapped failures went to human review.")
            add(f"    reason: {llm_stats.get('degraded_reason', 'unspecified')}")
        if llm_stats.get("fuse_aborted"):
            add("")
            add("  DEGRADED: the AI-stage circuit breaker aborted mid-batch. Remaining")
            add("  records were classified by the dictionary alone. Money decisions")
            add("  were unaffected - the breaker bounds the AI stage only.")
            add(f"    reason: {llm_stats.get('fuse_reason', 'unspecified')}")
        add("")

    add("-" * 78)
    add("CONTROLS")
    add("-" * 78)
    add(f"  Audit chain verified : {'INTACT' if ledger_ok else 'BROKEN'} ({ledger_rows} rows)")
    for w in sequencer.soft_warnings:
        add(f"  Soft warning         : {w}")
    add(f"  Batch breaker        : {sequencer.tripped or 'not tripped'}")
    add("=" * 78)
    return "\n".join(L)
