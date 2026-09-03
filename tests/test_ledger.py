"""An audit trail that can be edited afterwards is not an audit trail."""

import json
import sqlite3

import pytest

from vasooli.ledger import GENESIS, Ledger


@pytest.fixture
def ledger(tmp_path):
    L = Ledger(tmp_path / "t.db")
    yield L
    L.close()


def _fill(L, n=5):
    for i in range(n):
        L.append(run_id="r1", arm="sequencer", event="decision",
                 verdict=f"ok — row {i}", subscription_id=f"sub_{i}", amount_paise=100 * i)


def test_empty_chain_verifies(ledger):
    assert ledger.verify().ok


def test_clean_chain_verifies(ledger):
    _fill(ledger)
    r = ledger.verify()
    assert r.ok and r.rows == 5 and r.broken_at is None


def test_first_row_chains_from_genesis(ledger):
    _fill(ledger, 1)
    assert ledger.rows()[0]["prev_hash"] == GENESIS


def test_edited_payload_is_detected_at_the_right_row(tmp_path):
    p = tmp_path / "t.db"
    L = Ledger(p); _fill(L); L.close()

    c = sqlite3.connect(p)
    c.execute("update ledger set payload=? where idx=3", (json.dumps({"amount_paise": 999999}),))
    c.commit(); c.close()

    L2 = Ledger(p)
    r = L2.verify()
    assert not r.ok
    assert r.broken_at == 3
    L2.close()


def test_deleted_row_breaks_the_chain(tmp_path):
    p = tmp_path / "t.db"
    L = Ledger(p); _fill(L); L.close()

    c = sqlite3.connect(p); c.execute("delete from ledger where idx=3"); c.commit(); c.close()

    L2 = Ledger(p)
    assert not L2.verify().ok
    L2.close()


def test_verdict_is_always_recorded(ledger):
    _fill(ledger)
    assert all(row["verdict"] for row in ledger.rows())


# --- keyed chain (4.3) --------------------------------------------------------

def test_unkeyed_chain_says_so_rather_than_implying_protection(monkeypatch, tmp_path):
    # A plain chain detects corruption but not an insider who can rewrite it.
    # The default must work out of the box AND not overstate what it proved.
    monkeypatch.delenv("VASOOLI_LEDGER_KEY", raising=False)
    L = Ledger(tmp_path / "u.db")
    _fill(L)
    v = L.verify()
    assert v.ok and not v.keyed
    assert v.strength == "tamper-evident"
    assert "unkeyed" in v.detail and "write access" in v.detail
    L.close()


def test_keyed_chain_reports_tamper_proof(monkeypatch, tmp_path):
    monkeypatch.setenv("VASOOLI_LEDGER_KEY", "a-real-secret")
    L = Ledger(tmp_path / "k.db")
    _fill(L)
    v = L.verify()
    assert v.ok and v.keyed and v.strength == "tamper-proof"
    L.close()


def test_a_forged_chain_fails_without_the_key(monkeypatch, tmp_path):
    # The whole point: rewriting the database is not enough any more.
    p = tmp_path / "f.db"
    monkeypatch.setenv("VASOOLI_LEDGER_KEY", "right-key")
    L = Ledger(p)
    _fill(L)
    L.close()

    monkeypatch.setenv("VASOOLI_LEDGER_KEY", "wrong-key")
    L2 = Ledger(p)
    v = L2.verify()
    assert not v.ok, "a chain built under another key verified clean"
    assert v.broken_at == 1
    L2.close()


def test_the_same_key_still_verifies(monkeypatch, tmp_path):
    p = tmp_path / "s.db"
    monkeypatch.setenv("VASOOLI_LEDGER_KEY", "stable")
    L = Ledger(p); _fill(L); L.close()
    L2 = Ledger(p)
    assert L2.verify().ok
    L2.close()
