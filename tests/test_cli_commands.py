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


def test_explain_traces_every_rule_not_just_the_one_that_fired(db, capsys):
    # A trace showing only the rule that fired hides the ones that nearly did,
    # which is the difference between an explanation and an assertion.
    assert main(["explain", "sub_SYN0002", "--db", db]) == 0
    out = capsys.readouterr().out
    for n in range(1, 8):
        assert f"  {n}  " in out
    assert "FIRED" in out
    assert "not reached (rule" in out
    assert "WHAT ARRIVED" in out
    assert "HOW IT WAS CLASSIFIED" in out
    assert "next step" in out


def test_explain_refuses_an_unknown_subscription(db, capsys):
    assert main(["explain", "sub_NOPE", "--db", db]) == 1
    assert "No record" in capsys.readouterr().out


def test_explain_survives_a_ledger_that_has_never_been_written(db, capsys):
    assert main(["explain", "sub_SYN0000", "--db", db]) == 0
    assert "No rows for this subscription" in capsys.readouterr().out


def test_worklist_writes_one_row_per_unrecovered_record(tmp_path, db, capsys):
    out_csv = tmp_path / "w.csv"
    assert main(["worklist", "--no-llm", "--db", db, "--out", str(out_csv)]) == 0

    import csv

    rows = list(csv.DictReader(out_csv.open()))
    assert rows
    # Every row carries a route and a concrete instruction. A worklist with an
    # unrouted row is a row nobody can action.
    for r in rows:
        assert r["escalation"] not in ("", "NONE")
        assert r["next_step"]
        assert float(r["amount_inr"]) > 0
    # Largest first: the point of the file is that the top of it is where the
    # money is.
    amounts = [float(r["amount_inr"]) for r in rows]
    assert amounts == sorted(amounts, reverse=True)
    assert "still owed" in capsys.readouterr().out
