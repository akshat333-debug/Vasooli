"""Diagnosis must degrade to 'ask a human', never to 'guess'.

These tests run with use_llm=False so the suite stays hermetic and offline —
no network, no gateway, no API key required in CI.
"""

from vasooli.diagnose import diagnose_batch
from vasooli.sim.seed import generate_batch
from vasooli.taxonomy import FailureClass, classify_by_code


def test_offline_mode_matches_the_dict_exactly():
    batch = generate_batch(50, seed=42)
    diagnoses, _ = diagnose_batch(batch, use_llm=False)
    for rec, d in zip(batch, diagnoses):
        assert d.failure_class is classify_by_code(rec.error_code, rec.error_reason)
        assert d.source == "code_map"


def test_offline_mode_leaves_unmapped_records_unknown():
    # Without the model, the tail must stay UNKNOWN and route to a human.
    batch = generate_batch(100, seed=42)
    diagnoses, _ = diagnose_batch(batch, use_llm=False)
    unknown = [d for d in diagnoses if d.failure_class is FailureClass.UNKNOWN]
    assert unknown, "expected unmapped records to remain UNKNOWN offline"
    assert all("human review" in d.rationale for d in unknown)


def test_every_record_gets_exactly_one_diagnosis():
    batch = generate_batch(100, seed=42)
    diagnoses, _ = diagnose_batch(batch, use_llm=False)
    assert len(diagnoses) == len(batch)
    assert [d.subscription_id for d in diagnoses] == [r.subscription_id for r in batch]


def test_diagnosis_always_carries_a_rationale():
    # An audit trail entry without a reason is not an audit trail entry.
    diagnoses, _ = diagnose_batch(generate_batch(30, seed=3), use_llm=False)
    assert all(d.rationale.strip() for d in diagnoses)


def test_offline_diagnosis_is_deterministic():
    b = generate_batch(60, seed=11)
    a1, _ = diagnose_batch(b, use_llm=False)
    a2, _ = diagnose_batch(b, use_llm=False)
    assert [d.model_dump() for d in a1] == [d.model_dump() for d in a2]
