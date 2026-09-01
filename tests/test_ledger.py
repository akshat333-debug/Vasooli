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
