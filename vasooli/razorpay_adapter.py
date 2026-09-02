"""Razorpay test-mode adapter.

WHAT IS REAL HERE, STATED UP FRONT

This project's batch measurement is synthetic and says so everywhere. This module
is the one place that talks to Razorpay's real test-mode API. It exists to prove
the engine drives a real payment API rather than only its own simulator.

It also handles the case that actually occurred during the build: the test
account authenticates fine for Orders, Payments and Invoices, but returns 401 on
Plans and Subscriptions because the Subscriptions product is not enabled on it.

The interesting design question is what a recovery system should do when a
capability it depends on is missing. The wrong answers are to crash on startup,
or to silently pretend the calls happened. Both are common and both are worse
than the boring right answer: probe what is actually available, record the gap in
the audit trail, and degrade to the simulator with the degradation stated in the
report rather than hidden in it.

That is the same instinct as QuantProto refusing to substitute synthetic prices
for a failed live feed without saying so.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import requests

from .ledger import Ledger
from .models import AtRiskRecord

API = "https://api.razorpay.com/v1"
TIMEOUT = 20


class RazorpayUnavailable(RuntimeError):
    """Credentials absent or the account cannot do what was asked."""


@dataclass(frozen=True)
class Capabilities:
    """What this specific test account can actually do, probed not assumed."""

    authenticated: bool
    orders: bool
    payments: bool
    invoices: bool
    subscriptions: bool
    plans: bool
    detail: str = ""

    @property
    def can_run_live_subscription_demo(self) -> bool:
        return self.authenticated and self.subscriptions and self.plans

    def summary(self) -> str:
        avail = [n for n in ("orders", "payments", "invoices", "subscriptions", "plans")
                 if getattr(self, n)]
        missing = [n for n in ("orders", "payments", "invoices", "subscriptions", "plans")
                   if not getattr(self, n)]
        return (f"authenticated={self.authenticated}; available={avail or 'none'}; "
                f"unavailable={missing or 'none'}")


def _auth() -> tuple[str, str]:
    kid = os.environ.get("RAZORPAY_KEY_ID", "")
    sec = os.environ.get("RAZORPAY_KEY_SECRET", "")
    if not kid or not sec:
        raise RazorpayUnavailable("RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not set")
    if not kid.startswith("rzp_test_"):
        # Refuse live credentials outright. This project moves money in loops;
        # it has no business holding a live key.
        raise RazorpayUnavailable(
            f"refusing to run against a non-test key ({kid[:8]}...) — test mode only"
        )
    return kid, sec


def probe() -> Capabilities:
    """Ask the account what it can do. Never assume from the key alone."""
    try:
        auth = _auth()
    except RazorpayUnavailable as e:
        return Capabilities(False, False, False, False, False, False, detail=str(e))

    got: dict[str, bool] = {}
    for name in ("orders", "payments", "invoices", "subscriptions", "plans"):
        try:
            r = requests.get(f"{API}/{name}", params={"count": 1}, auth=auth, timeout=TIMEOUT)
            got[name] = r.status_code == 200
        except requests.RequestException:
            got[name] = False

    authed = any(got.values())
    detail = "" if all(got.values()) else (
        "account cannot access: " + ", ".join(n for n, ok in got.items() if not ok)
    )
    return Capabilities(authenticated=authed, detail=detail, **got)


def create_test_order(rec: AtRiskRecord) -> dict:
    """Create a real test-mode Order mirroring one at-risk record.

    Orders are the closest primitive this account can actually exercise. The
    record's amount, currency and identifiers are carried across so the object in
    the Razorpay dashboard corresponds to a record in our batch.
    """
    auth = _auth()
    payload = {
        "amount": rec.amount_paise,
        "currency": "INR",
        "receipt": rec.invoice_id,
        "notes": {
            "vasooli_subscription_id": rec.subscription_id,
            "vasooli_mandate_id": rec.mandate_id,
            "vasooli_failure_reason": rec.error_reason,
            "vasooli_note": "synthetic recovery record - test mode only",
        },
    }
    r = requests.post(f"{API}/orders", json=payload, auth=auth, timeout=TIMEOUT)
    if r.status_code not in (200, 201):
        raise RazorpayUnavailable(f"order creation failed [{r.status_code}]: {r.text[:200]}")
    return r.json()


def run_live_probe(
    records: list[AtRiskRecord],
    ledger: Ledger,
    *,
    run_id: str,
    limit: int = 5,
) -> Capabilities:
    """Exercise the real API on a small slice, logging everything to the ledger.

    Returns the probed capabilities so the report can state exactly which parts
    of the run were real and which were simulated.
    """
    caps = probe()
    ledger.append(
        run_id=run_id, arm="live", event="razorpay_probe",
        verdict=f"probed test-mode account — {caps.summary()}",
        detail=caps.detail,
    )

    if not caps.orders:
        ledger.append(
            run_id=run_id, arm="live", event="razorpay_degraded",
            verdict=("degraded to simulator — the test account cannot create orders; "
                     "no live API call was made and the report says so"),
        )
        return caps

    for rec in records[:limit]:
        try:
            order = create_test_order(rec)
            ledger.append(
                run_id=run_id, arm="live", event="razorpay_order_created",
                verdict=(f"live test-mode order {order['id']} created for "
                         f"Rs {rec.amount_paise / 100:,.2f}"),
                subscription_id=rec.subscription_id,
                order_id=order["id"], amount_paise=rec.amount_paise,
                status=order.get("status"),
            )
        except RazorpayUnavailable as e:
            # A failure against the real API is data, not a crash. Record it.
            ledger.append(
                run_id=run_id, arm="live", event="razorpay_error",
                verdict=f"live call failed and was recorded rather than swallowed — {e}",
                subscription_id=rec.subscription_id,
            )

    return caps
