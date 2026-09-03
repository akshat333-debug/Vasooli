"""Guardrails on customer-facing text. These are the safety-critical tests here.

A classifier that is wrong costs a retry. A message that is wrong reaches a
customer, so every one of these checks a way the model could cause real harm.
All hermetic — no model is called.
"""

import pytest

from vasooli.decide import decide
from vasooli.diagnose import diagnose_batch
from vasooli.ledger import Ledger
from vasooli.nudge import (
    AMOUNT_TOKEN,
    MAX_CHARS,
    NudgeRejected,
    check_draft,
    draft_batch,
    render,
    wants_nudge_count,
)
from vasooli.sim.seed import BATCH_NOW, generate_batch


def _pairs(n=100, seed=42):
    batch = generate_batch(n, seed=seed)
    diagnoses, _ = diagnose_batch(batch, use_llm=False)
    by = {d.subscription_id: d for d in diagnoses}
    return [(r, decide(r, by[r.subscription_id].failure_class, BATCH_NOW)) for r in batch]


# --- what must be rejected ----------------------------------------------------

@pytest.mark.parametrize("bad", [
    "Payment fail ho gaya, click https://rzp.io/x to pay",
    "Aapka payment fail hua, visit www.example.org",
    "Payment failed, pay at somebank.com now",
])
def test_rejects_anything_link_shaped(bad):
    # A model that invents a payment link has invented a phishing target.
    with pytest.raises(NudgeRejected, match="link-shaped"):
        check_draft(bad)


@pytest.mark.parametrize("bad", [
    "Payment fail ho gaya. Aapko full refund mil jayega.",
    "Balance kam hai. Hum late fee waive kar denge.",
    "Payment nahi hua, warna aapka account will be closed.",
    "Pay now or we will take legal action.",
    "Aaj hi pay karein aur 20% discount payein.",
])
def test_rejects_promises_and_threats(bad):
    # Refunds, waivers and consequences are commitments a merchant makes.
    with pytest.raises(NudgeRejected, match="promise or threat"):
        check_draft(bad)


def test_rejects_a_figure_the_model_invented():
    # The real risk: a number the model made up reaching a customer.
    with pytest.raises(NudgeRejected, match="figure of its own"):
        check_draft("Aapka Rs 4999 ka payment fail ho gaya, dobara try karein.")


def test_rejects_an_empty_draft():
    with pytest.raises(NudgeRejected, match="empty"):
        check_draft("   ")


def test_rejects_an_overlong_draft():
    with pytest.raises(NudgeRejected, match="too long"):
        check_draft("a" * (MAX_CHARS + 1))


# --- what must be allowed -----------------------------------------------------

def test_allows_a_draft_using_the_placeholder():
    t = check_draft(f"Aapka {AMOUNT_TOKEN} ka payment fail ho gaya, dobara try karein.")
    assert AMOUNT_TOKEN in t


def test_allows_a_draft_that_never_mentions_the_amount():
    # The first version of this guardrail rejected these, which was wrong: a
    # message without a figure is safe, and three of six real drafts were being
    # discarded for it.
    assert check_draft("Aapka autopay mandate expire ho gaya hai, naya set kijiye.")


def test_strips_surrounding_quotes():
    assert check_draft('"Payment fail ho gaya, dobara try karein."').startswith("Payment")


# --- the amount is substituted, never generated -------------------------------

def test_amount_comes_from_the_record_not_the_model():
    rec = generate_batch(1, seed=42)[0]
    out = render(f"Aapka {AMOUNT_TOKEN} ka payment fail ho gaya.", rec)
    assert AMOUNT_TOKEN not in out
    assert f"{rec.amount_paise / 100:,.0f}" in out


# --- batch behaviour ----------------------------------------------------------

def test_only_flagged_records_are_drafted(tmp_path):
    pairs = _pairs()
    L = Ledger(tmp_path / "n.db")
    stats = draft_batch(pairs, L, run_id="t", use_llm=False)
    assert stats["flagged"] == sum(1 for _, d in pairs if d.wants_nudge)
    assert stats["drafted"] == 0  # no model available
    assert stats["unavailable"] == stats["flagged"]
    L.close()


def test_nothing_is_drafted_when_nothing_is_flagged(tmp_path):
    L = Ledger(tmp_path / "n2.db")
    assert draft_batch([], L, run_id="t")["flagged"] == 0
    L.close()


def test_module_exposes_no_send_path():
    # The absence of a send function is the design, so it is asserted rather
    # than assumed. If someone adds one, this fails and they have to argue for it.
    import vasooli.nudge as m
    assert not [n for n in dir(m) if "send" in n.lower() or "dispatch" in n.lower()]


def test_breakdown_counts_by_decision():
    b = wants_nudge_count(_pairs())
    assert sum(b.values()) == sum(1 for _, d in _pairs() if d.wants_nudge)
