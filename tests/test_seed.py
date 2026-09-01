"""The batch must be reproducible and must contain the hard cases."""

from vasooli.models import MandateStatus
from vasooli.sim.seed import generate_batch
from vasooli.taxonomy import FailureClass, classify_by_code


def _dump(batch):
    return [r.model_dump() for r in batch]


def test_batch_is_deterministic_for_a_seed():
    # Both arms are scored on the identical batch. If this ever fails, the
    # arm comparison is meaningless.
    assert _dump(generate_batch(100, seed=42)) == _dump(generate_batch(100, seed=42))


def test_different_seeds_produce_different_batches():
    assert _dump(generate_batch(100, seed=42)) != _dump(generate_batch(100, seed=7))


def test_batch_contains_every_hard_case():
    b = generate_batch(100, seed=42)
    assert any(r.needs_human_approval for r in b), "no record above the RBI cap"
    assert any(r.exceeds_mandate_cap for r in b), "no record above its mandate cap"
    assert any(r.attempts_remaining == 0 for r in b), "no exhausted-budget record"
    assert any(r.pre_debit_notified_at is None for r in b), "no un-notified record"
    assert any(r.mandate_status is MandateStatus.REVOKED for r in b), "no dead mandate"


def test_batch_contains_unclassifiable_records():
    b = generate_batch(100, seed=42)
    unknown = [r for r in b if classify_by_code(r.error_code, r.error_reason) is FailureClass.UNKNOWN]
    assert unknown, "batch has no UNKNOWN records, so the human-review path is untested"


def test_hazard_mandate_dead_but_error_text_reads_recoverable():
    # The trap this project is built to survive: the diagnosis says the debit
    # could work, the mandate says it cannot. Execution must re-check.
    b = generate_batch(100, seed=42)
    trap = [
        r for r in b
        if r.mandate_status is not MandateStatus.ACTIVE
        and classify_by_code(r.error_code, r.error_reason) in
        {FailureClass.INSUFFICIENT_FUNDS, FailureClass.BANK_DOWNTIME, FailureClass.TECHNICAL_ERROR}
    ]
    assert trap, "no record where a live-looking failure sits on a dead mandate"


def test_amounts_are_integer_paise():
    for r in generate_batch(50, seed=1):
        assert isinstance(r.amount_paise, int)
        assert r.amount_paise > 0
