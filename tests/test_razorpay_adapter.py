"""Adapter safety. These run offline — no network, no credentials."""

import pytest

from vasooli import razorpay_adapter as rz
from vasooli.ledger import Ledger
from vasooli.sim.seed import generate_batch


def test_refuses_a_live_key(monkeypatch):
    # This project retries debits in a loop. It must never hold a live key.
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_live_ABCDEFGH")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "whatever")
    with pytest.raises(rz.RazorpayUnavailable, match="test mode only"):
        rz._auth()


def test_missing_credentials_raise_rather_than_default(monkeypatch):
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    with pytest.raises(rz.RazorpayUnavailable):
        rz._auth()


def test_probe_without_credentials_reports_unavailable_not_crash(monkeypatch):
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    caps = rz.probe()
    assert not caps.authenticated
    assert not caps.can_run_live_subscription_demo
    assert caps.detail


def test_capability_summary_names_what_is_missing():
    caps = rz.Capabilities(True, True, True, True, False, False,
                           detail="account cannot access: subscriptions, plans")
    assert not caps.can_run_live_subscription_demo
    assert "subscriptions" in caps.summary()


def test_degradation_is_written_to_the_ledger(monkeypatch, tmp_path):
    # The behaviour that matters: when the API cannot be used, the run says so
    # in the audit trail instead of silently pretending.
    monkeypatch.setattr(rz, "probe", lambda: rz.Capabilities(
        False, False, False, False, False, False, detail="no credentials"))
    L = Ledger(tmp_path / "r.db")
    caps = rz.run_live_probe(generate_batch(5, seed=1), L, run_id="test1")
    events = [r["event"] for r in L.rows("test1")]
    assert "razorpay_degraded" in events
    verdict = [r["verdict"] for r in L.rows("test1") if r["event"] == "razorpay_degraded"][0]
    assert "no live API call was made" in verdict
    assert not caps.orders
    L.close()


def test_live_errors_are_recorded_not_swallowed(monkeypatch, tmp_path):
    monkeypatch.setattr(rz, "probe", lambda: rz.Capabilities(
        True, True, True, True, False, False))

    def boom(rec):
        raise rz.RazorpayUnavailable("order creation failed [500]: nope")

    monkeypatch.setattr(rz, "create_test_order", boom)
    L = Ledger(tmp_path / "r2.db")
    rz.run_live_probe(generate_batch(3, seed=1), L, run_id="test2", limit=2)
    errs = [r for r in L.rows("test2") if r["event"] == "razorpay_error"]
    assert len(errs) == 2
    assert all("recorded rather than swallowed" in r["verdict"] for r in errs)
    L.close()
