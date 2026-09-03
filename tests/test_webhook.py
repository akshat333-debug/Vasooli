"""The webhook is a trust boundary. These tests are mostly about refusing."""

import hashlib
import hmac
import json

import pytest

from vasooli.decide import Action, decide
from vasooli.ledger import Ledger
from vasooli.models import RBI_STANDARD_CAP_PAISE, MandateStatus
from vasooli.sim.seed import BATCH_NOW
from vasooli.taxonomy import FailureClass
from vasooli.webhook import (
    EventIgnored,
    SignatureInvalid,
    ingest,
    to_record,
    verify_signature,
)

SECRET = "whsec_test"


def sign(body: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def event(**over):
    e = {
        "id": "evt_1",
        "event": "payment.failed",
        "created_at": int(BATCH_NOW.timestamp()),
        "payload": {
            "payment": {"entity": {
                "amount": 49900, "method": "upi", "bank": "HDFC",
                "error_code": "BAD_REQUEST_ERROR",
                "error_reason": "insufficient_funds",
                "error_description": "balance low",
                "subscription_id": "sub_live1",
            }},
            "subscription": {"entity": {
                "id": "sub_live1", "status": "active", "customer_id": "cust_1",
            }},
        },
    }
    e.update(over)
    return e


def body_of(e) -> bytes:
    return json.dumps(e).encode()


@pytest.fixture
def ledger(tmp_path):
    L = Ledger(tmp_path / "w.db")
    yield L
    L.close()


# --- the signature gate --------------------------------------------------------

def test_a_bad_signature_is_refused(ledger):
    b = body_of(event())
    with pytest.raises(SignatureInvalid):
        ingest(b, "deadbeef", ledger, run_id="t", secret=SECRET)


def test_a_tampered_body_is_refused(ledger):
    b = body_of(event())
    sig = sign(b)
    tampered = b.replace(b"49900", b"9999900")
    with pytest.raises(SignatureInvalid):
        ingest(tampered, sig, ledger, run_id="t", secret=SECRET)


def test_a_missing_secret_refuses_rather_than_trusts(monkeypatch, ledger):
    monkeypatch.delenv("RAZORPAY_WEBHOOK_SECRET", raising=False)
    b = body_of(event())
    with pytest.raises(SignatureInvalid, match="refusing"):
        ingest(b, sign(b), ledger, run_id="t")


def test_signature_check_is_constant_time():
    # A naive == returns faster on an earlier mismatch, leaking the signature a
    # byte at a time to anyone patient enough to measure it.
    import inspect

    from vasooli import webhook
    assert "compare_digest" in inspect.getsource(webhook.verify_signature)
    assert "== signature" not in inspect.getsource(webhook.verify_signature)


def test_a_valid_signature_passes():
    b = body_of(event())
    verify_signature(b, sign(b), SECRET)


# --- replays -------------------------------------------------------------------

def test_a_replayed_delivery_is_not_counted_twice(ledger):
    # Razorpay retries deliveries. Counting a replay as a second failure would
    # spend a retry from a budget of three on one real event.
    b = body_of(event())
    sig = sign(b)
    first = ingest(b, sig, ledger, run_id="t", secret=SECRET)
    second = ingest(b, sig, ledger, run_id="t", secret=SECRET)
    assert not first.duplicate and first.record is not None
    assert second.duplicate and second.record is None


# --- what it accepts and ignores -------------------------------------------------

def test_an_unhandled_event_is_acknowledged_not_acted_on(ledger):
    b = body_of(event(event="payment.captured"))
    out = ingest(b, sign(b), ledger, run_id="t", secret=SECRET)
    assert out.record is None
    assert "not handled" in out.note


def test_unparseable_but_authentic_body_is_ignored_not_crashed(ledger):
    b = b"{not json"
    with pytest.raises(EventIgnored):
        ingest(b, sign(b), ledger, run_id="t", secret=SECRET)


def test_an_accepted_event_becomes_a_record(ledger):
    b = body_of(event())
    out = ingest(b, sign(b), ledger, run_id="t", secret=SECRET)
    assert out.record.subscription_id == "sub_live1"
    assert out.record.amount_paise == 49900
    assert out.record.bank == "HDFC"


# --- missing information must never widen the envelope ----------------------------

def test_an_unknown_mandate_cap_does_not_widen_the_envelope():
    # With no max_amount in the event, the cap defaults to the amount itself, so
    # anything larger is refused rather than assumed permitted.
    rec = to_record(event(), BATCH_NOW)
    assert rec.mandate_max_amount_paise == rec.amount_paise
    assert not rec.exceeds_mandate_cap


def test_no_pre_debit_notice_is_ever_assumed_from_an_event():
    # An event cannot prove a notice was sent, so the engine must schedule as
    # though none was.
    assert to_record(event(), BATCH_NOW).pre_debit_notified_at is None


def test_a_cancelled_subscription_maps_to_a_dead_mandate():
    e = event()
    e["payload"]["subscription"]["entity"]["status"] = "cancelled"
    assert to_record(e, BATCH_NOW).mandate_status is MandateStatus.REVOKED


def test_a_webhook_record_still_obeys_the_rbi_cap():
    # The event supplies facts; decide.py decides. Nothing in a payload can
    # raise a cap.
    e = event()
    e["payload"]["payment"]["entity"]["amount"] = RBI_STANDARD_CAP_PAISE + 1
    e["payload"]["subscription"]["entity"]["max_amount"] = 10 ** 9
    rec = to_record(e, BATCH_NOW)
    d = decide(rec, FailureClass.INSUFFICIENT_FUNDS, BATCH_NOW)
    assert d.action is Action.HUMAN_REVIEW
    assert "RBI" in d.verdict


def test_the_module_makes_no_decisions():
    import inspect

    from vasooli import webhook
    src = inspect.getsource(webhook)
    assert "run_batch" not in src and "best_retry_time" not in src


def test_razorpay_timestamps_are_read_as_utc_not_local_time():
    # fromtimestamp() without a tz reads a UTC epoch in LOCAL time, shifting a
    # mandate's expiry by the host's offset. An engine that reasons about dates
    # would then schedule against the wrong day depending on where it runs.
    from datetime import UTC, datetime

    epoch = 1_800_000_000
    e = event()
    e["payload"]["subscription"]["entity"]["end_at"] = epoch
    rec = to_record(e, BATCH_NOW)
    expected = datetime.fromtimestamp(epoch, tz=UTC).replace(tzinfo=None)
    assert rec.mandate_valid_until == expected
