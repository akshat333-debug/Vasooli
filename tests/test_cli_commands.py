"""Smoke tests for the CLI commands that demonstrate a module end to end.

cli.py is excluded from coverage because it is argument plumbing and print
statements. These tests exist anyway, because two of its commands are the ONLY
way a reader can see webhook.py and promise.py run -- both modules were fully
built, fully tested at unit level, described in the README, and unreachable
from the command line, which meant nobody could actually watch them work.

A smoke test is the right weight here: it asserts the command exits cleanly and
that the specific behaviours it exists to demonstrate actually appear in its
output. If the webhook stops refusing a forged signature, this fails.
"""

import pytest

from vasooli.cli import main
from vasooli.ledger import Ledger


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "cli.db")


def test_webhook_command_demonstrates_every_refusal(db, capsys):
    assert main(["webhook", "--db", db]) == 0
    out = capsys.readouterr().out

    # The four behaviours the door exists for.
    assert "REFUSED before parsing" in out          # signature, before the parser
    assert "duplicate delivery" in out              # replay
    assert "event type not handled" in out          # unhandled type
    assert "RETRY_SCHEDULED" in out                 # the happy path still decides

    # The budget must walk down across two genuine deliveries, and must NOT be
    # derived from paid_count -- a subscription with 10 paid cycles is not
    # exhausted (defect 20).
    assert "attempts_used  : 0 of 3" in out
    assert "attempts_used  : 1 of 3" in out
    assert "SUCCESSFUL charges" in out

    # A live event carries no payday, and the engine must say so rather than
    # timing the retry around an invented one.
    assert "salary_day     : None" in out
    assert "replenishment day unknown" in out


def test_webhook_command_writes_a_verifiable_chain(db):
    assert main(["webhook", "--db", db]) == 0
    L = Ledger(db)
    events = [r["event"] for r in L.rows()]
    v = L.verify()
    L.close()
    assert v.ok
    # The forged delivery must leave NO row: it was refused before parsing.
    assert events.count("webhook_received") == 2
    assert "webhook_duplicate" in events
    assert "webhook_ignored" in events
    assert events.count("decision") == 2


def test_promise_command_honours_one_case_and_refuses_four(db, capsys):
    assert main(["promise", "--db", db, "-n", "60"]) == 0
    out = capsys.readouterr().out
    assert out.count("HONOURED") == 1
    assert out.count("REFUSED") == 4
    # The single most important line in the module.
    assert "does not reopen it" in out
    assert "never pull it forward" in out


def test_promise_command_records_every_verdict(db):
    assert main(["promise", "--db", db, "-n", "60"]) == 0
    L = Ledger(db)
    rows = [r for r in L.rows() if r["event"] == "promise_applied"]
    v = L.verify()
    L.close()
    assert len(rows) == 5
    assert v.ok


def test_promise_command_survives_a_batch_with_nothing_to_show(db, capsys):
    # n=1 may contain no scheduled record, no refused one, or neither. The
    # command must say so rather than raising on a None.
    for n in (1, 2, 3):
        assert main(["promise", "--db", db, "-n", str(n)]) == 0
    assert capsys.readouterr().out
