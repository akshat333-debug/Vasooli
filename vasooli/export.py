"""Export a batch run as JSON for the web interface.

The Python side stays authoritative. Nothing is computed in the browser that
isn't computed here first — the interface renders decisions, it does not make
them. That boundary matters for a system whose claim is that every money action
is explainable: if the UI could derive a number the engine never produced, the
audit trail would no longer be the whole story.

So this module runs a real batch, reads the real ledger, and serialises exactly
what the engine decided. The web app is a viewer.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .decide import decide
from .diagnose import diagnose_batch
from .execute import BatchResult, run_batch
from .ledger import Ledger
from .models import MAX_RETRY_BUDGET, AtRiskRecord
from .report import ESCALATION_LABEL, compliance_split, pushed_to_halt
from .sim.seed import BATCH_NOW, generate_batch


def _arm_payload(res: BatchResult, records: list[AtRiskRecord]) -> dict[str, Any]:
    within, over = compliance_split(res, records)
    return {
        "arm": res.arm,
        "run_id": res.run_id,
        "records": res.records,
        "records_processed": res.records_processed,
        "truncated": res.truncated,
        "tripped": res.tripped,
        "soft_warnings": res.soft_warnings,
        "attempts_spent": res.attempts_spent,
        "wasted_attempts": res.wasted_attempts,
        "breaker_refusals": res.breaker_refusals,
        "pushed_to_halt": [o.model_dump(mode="json") for o in pushed_to_halt(res, records)],
        "value_at_risk_paise": res.value_at_risk_paise,
        "value_recovered_paise": res.value_recovered_paise,
        "recovered_within_envelope_paise": within,
        "recovered_above_cap_paise": over,
        # Raw basis (includes above-cap debits) and compliance-adjusted
        # basis. The adjusted one is the claim; both are exported so a
        # reader can check one against the other.
        "paise_per_attempt": res.paise_per_attempt,
        "adjusted_paise_per_attempt": (
            within / res.attempts_spent if res.attempts_spent else 0.0
        ),
        "outcomes": [o.model_dump(mode="json") for o in res.outcomes],
    }


def build_payload(
    n: int = 100,
    seed: int = 42,
    *,
    use_llm: bool = True,
    db_path: str = "vasooli-web.db",
) -> dict[str, Any]:
    """Run a full batch and return everything the interface needs."""
    records = generate_batch(n, seed=seed)
    ledger = Ledger(db_path)

    diagnoses, llm_stats = diagnose_batch(records, use_llm=use_llm)
    by_diag = {d.subscription_id: d for d in diagnoses}

    baseline = run_batch(records, arm="baseline", now=BATCH_NOW, ledger=ledger,
                         diagnoses=diagnoses, draw_salt=str(seed))
    sequencer = run_batch(records, arm="sequencer", now=BATCH_NOW, ledger=ledger,
                          diagnoses=diagnoses, draw_salt=str(seed))

    bl_out = {o.subscription_id: o for o in baseline.outcomes}
    sq_out = {o.subscription_id: o for o in sequencer.outcomes}

    rows: list[dict[str, Any]] = []
    for rec in records:
        diag = by_diag[rec.subscription_id]
        dec = decide(rec, diag.failure_class, BATCH_NOW)
        b, s = bl_out.get(rec.subscription_id), sq_out.get(rec.subscription_id)
        rows.append({
            "subscription_id": rec.subscription_id,
            "customer_id": rec.customer_id,
            "mandate_id": rec.mandate_id,
            "invoice_id": rec.invoice_id,
            "bank": rec.bank,
            "method": rec.method.value,
            "amount_paise": rec.amount_paise,
            "mandate_status": rec.mandate_status.value,
            "mandate_max_amount_paise": rec.mandate_max_amount_paise,
            "mandate_valid_until": rec.mandate_valid_until.isoformat(),
            "attempts_used": rec.attempts_used,
            "attempts_remaining": rec.attempts_remaining,
            "error_code": rec.error_code,
            "error_reason": rec.error_reason,
            "error_description": rec.error_description,
            "last_attempt_at": rec.last_attempt_at.isoformat(),
            "pre_debit_notified_at": (
                rec.pre_debit_notified_at.isoformat() if rec.pre_debit_notified_at else None
            ),
            "salary_day": rec.salary_day,
            "exceeds_mandate_cap": rec.exceeds_mandate_cap,
            "needs_human_approval": rec.needs_human_approval,
            "failure_class": diag.failure_class.value,
            "diagnosis_source": diag.source,
            "diagnosis_rationale": diag.rationale,
            "action": dec.action.value,
            "rule_fired": dec.rule_fired,
            "escalation": dec.escalation.value,
            "escalation_label": ESCALATION_LABEL.get(dec.escalation.value, ""),
            "verdict": dec.verdict,
            "scheduled_at": dec.scheduled_at.isoformat() if dec.scheduled_at else None,
            "expected_success": dec.expected_success,
            "baseline": {
                "recovered": b.recovered if b else False,
                "attempts_spent": b.attempts_spent if b else 0,
                "attempts_preserved": b.attempts_preserved if b else 0,
                "terminal_reason": b.terminal_reason if b else "not processed",
            },
            "sequencer": {
                "recovered": s.recovered if s else False,
                "attempts_spent": s.attempts_spent if s else 0,
                "attempts_preserved": s.attempts_preserved if s else 0,
                "terminal_reason": s.terminal_reason if s else "not processed",
                "rule_fired": s.rule_fired if s else 0,
                "escalation": s.escalation.value if s else "NONE",
            },
        })

    verify = ledger.verify()
    entries = [
        {
            "idx": r["idx"],
            "ts": r["ts"],
            "run_id": r["run_id"],
            "arm": r["arm"],
            "subscription_id": r["subscription_id"],
            "event": r["event"],
            "verdict": r["verdict"],
            # The payload is part of the hashed body, so the viewer cannot
            # recompute the chain without it. Exporting it is what turns the
            # audit trail from a claim the page makes into one the reader can
            # check in their own browser.
            "payload": json.loads(r["payload"]),
            "hash": r["hash"],
            "prev_hash": r["prev_hash"],
        }
        for r in ledger.rows()
    ]
    ledger.close()

    return {
        "meta": {
            "generated_at": datetime.now(UTC).isoformat(),
            "batch_reference_time": BATCH_NOW.isoformat(),
            "seed": seed,
            "record_count": n,
            "retry_budget_per_record": MAX_RETRY_BUDGET,
            "synthetic": True,
            "disclaimer": (
                "Recovery outcomes come from a seeded, assumption-driven model in "
                "vasooli/sim/model.py. They are not measured from real banks. The "
                "comparison between arms is valid because both face identical records "
                "and identical random draws; the absolute rupee figures are not a "
                "claim about production performance."
            ),
        },
        "arms": {
            "baseline": _arm_payload(baseline, records),
            "sequencer": _arm_payload(sequencer, records),
        },
        "records": rows,
        "ledger": {
            "verified": verify.ok,
            "rows": verify.rows,
            "broken_at": verify.broken_at,
            "detail": verify.detail,
            "keyed": verify.keyed,
            "strength": verify.strength,
            "entries": entries,
        },
        "escalation_labels": ESCALATION_LABEL,
        "llm": llm_stats,
        "scenarios": build_scenarios(n, seed),
    }


def write_payload(path: str | Path, **kwargs: Any) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(build_payload(**kwargs), indent=2))
    return p


#: Policy variations worth showing side by side. Each is a REAL engine run, not
#: a projection — the interface must never compute a scenario the engine did not
#: actually produce, which is the same boundary every other number here respects.
SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "default",
        "name": "As shipped",
        "note": "Every stopping rule on, ceilings sized above the batch.",
        "policy": {},
        "disabled_rules": [],
    },
    {
        "id": "no_compliance_rule",
        "name": "Without the RBI cap rule",
        "note": "Rule 6 off. Nothing above the cap is recovered anyway -- the "
                "breaker catches it at the action boundary and the network "
                "would decline it regardless. The cost moves one layer down, "
                "into the refusals row.",
        "policy": {},
        "disabled_rules": [6],
    },
    {
        "id": "no_mandate_check",
        "name": "Without the dead-mandate check",
        "note": "Rule 3 off. Costs nothing here, because the pre-flight status "
                "call at the action boundary catches the same records without "
                "spending an attempt. Deliberate redundancy: the rule is what "
                "produces the re-mandate escalation, the boundary check is what "
                "survives the world changing after the decision.",
        "policy": {},
        "disabled_rules": [3],
    },
    {
        "id": "tight_breaker",
        "name": "Breaker set to 40 actions",
        "note": "The batch stops mid-run. Included so the truncation warning is "
                "visible rather than described.",
        "policy": {"max_actions_per_batch": 40},
        "disabled_rules": [],
    },
]


def build_scenarios(n: int = 100, seed: int = 42) -> list[dict[str, Any]]:
    """Run each policy variation for real and summarise it."""
    from .policy import RecoveryPolicy

    records = generate_batch(n, seed=seed)
    diagnoses, _ = diagnose_batch(records, use_llm=False)
    out: list[dict[str, Any]] = []

    for sc in SCENARIOS:
        ledger = Ledger(":memory:")
        policy = RecoveryPolicy(**sc["policy"]) if sc["policy"] else None
        res = run_batch(
            records, arm="sequencer", now=BATCH_NOW, ledger=ledger,
            diagnoses=diagnoses, policy=policy,
            disabled_rules=frozenset(sc["disabled_rules"]),
            draw_salt=str(seed),
        )
        ledger.close()
        within, over = compliance_split(res, records)
        out.append({
            "id": sc["id"], "name": sc["name"], "note": sc["note"],
            "disabled_rules": sc["disabled_rules"],
            "attempts_spent": res.attempts_spent,
            "wasted_attempts": res.wasted_attempts,
            "breaker_refusals": res.breaker_refusals,
            "recovered_within_envelope_paise": within,
            "recovered_above_cap_paise": over,
            "adjusted_paise_per_attempt": (
                within / res.attempts_spent if res.attempts_spent else 0.0
            ),
            "records_processed": res.records_processed,
            "truncated": res.truncated,
            "tripped": res.tripped,
        })
    return out
