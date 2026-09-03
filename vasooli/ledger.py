"""Append-only, hash-chained audit ledger.

Every decision the system makes about money lands here before anything is
executed — what was seen, what it was classified as, what was decided, why, and
what happened. The chain exists so the audit trail cannot be quietly edited after
the fact to make a batch look better than it was.

Chain rule: hash(row) = HMAC-SHA256(key, prev_hash || canonical_json(payload)).
Changing any historical payload breaks every hash after it, and `verify()`
reports the first broken index rather than a bare True/False, so a tamper is
locatable.

WHY HMAC AND NOT A PLAIN HASH

A plain SHA-256 chain detects an *accidental* edit and nothing else. Anyone who
can write to the database can also recompute every subsequent hash, and the
result verifies clean — which means the chain protects against corruption but
not against the insider it was built for.

Keying the chain fixes that: forging it now requires the key as well as write
access, and the key lives outside the database. Set VASOOLI_LEDGER_KEY and the
chain is unforgeable without it.

If the variable is unset the ledger still works, using a published constant, and
`verify()` says so in plain words rather than implying a protection it does not
have. That is the honest default for a project someone clones and runs: it must
work out of the box, and it must not overstate what it proved.

Pattern carried over from QuantProto's experiment ledger, where the same problem
appears: a number is only trustworthy if the record behind it cannot be revised.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

GENESIS = "0" * 64

#: Used when VASOOLI_LEDGER_KEY is unset. Published on purpose — a secret in
#: source control is not a secret, and pretending otherwise would be worse than
#: saying plainly that an unkeyed chain is tamper-EVIDENT but not tamper-PROOF.
_UNKEYED = b"vasooli-unkeyed-ledger"


def _key() -> tuple[bytes, bool]:
    """(key, is_keyed). Read at call time so tests can set it per-case."""
    env = os.environ.get("VASOOLI_LEDGER_KEY", "")
    return (env.encode(), True) if env else (_UNKEYED, False)

_SCHEMA = """
create table if not exists ledger (
    idx        integer primary key autoincrement,
    ts         text    not null,
    run_id     text    not null,
    arm        text    not null,
    subscription_id text,
    event      text    not null,
    verdict    text    not null,
    payload    text    not null,
    prev_hash  text    not null,
    hash       text    not null
);
create index if not exists ledger_run on ledger(run_id, idx);
"""


def _canonical(payload: dict[str, Any]) -> str:
    """Stable JSON so a hash never changes because a dict reordered."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _row_hash(prev_hash: str, payload: dict[str, Any]) -> str:
    key, _ = _key()
    return hmac.new(key, (prev_hash + _canonical(payload)).encode(),
                    hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    rows: int
    #: Ledger index of the first row whose hash does not match. None when ok.
    broken_at: int | None = None
    detail: str = ""
    #: False when the chain was built with the published fallback key, i.e.
    #: anyone with write access could rebuild it and it would still verify.
    keyed: bool = False

    @property
    def strength(self) -> str:
        if not self.ok:
            return "broken"
        return "tamper-proof" if self.keyed else "tamper-evident"


class Ledger:
    def __init__(self, path: str | Path = "vasooli.db") -> None:
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def _tip(self) -> str:
        row = self.conn.execute("select hash from ledger order by idx desc limit 1").fetchone()
        return row["hash"] if row else GENESIS

    def append(
        self,
        *,
        run_id: str,
        arm: str,
        event: str,
        verdict: str,
        subscription_id: str | None = None,
        **payload: Any,
    ) -> str:
        """Append one decision. `verdict` is the human-readable reason string.

        The verdict format mirrors RunFuse's trip verdicts — a short machine-ish
        label, an em dash, and the reason a person needs. It is the single most
        important field in the row: a log that records what happened without
        recording why is not an audit trail.
        """
        ts = datetime.now(UTC).isoformat()
        body = {
            "ts": ts,
            "run_id": run_id,
            "arm": arm,
            "subscription_id": subscription_id,
            "event": event,
            "verdict": verdict,
            "payload": payload,
        }
        prev = self._tip()
        h = _row_hash(prev, body)
        self.conn.execute(
            "insert into ledger (ts, run_id, arm, subscription_id, event, verdict,"
            " payload, prev_hash, hash) values (?,?,?,?,?,?,?,?,?)",
            (ts, run_id, arm, subscription_id, event, verdict,
             _canonical(payload), prev, h),
        )
        self.conn.commit()
        return h

    def verify(self) -> VerifyResult:
        """Recompute the whole chain. Reports where it first breaks."""
        prev = GENESIS
        rows = self.conn.execute("select * from ledger order by idx").fetchall()
        for r in rows:
            body = {
                "ts": r["ts"],
                "run_id": r["run_id"],
                "arm": r["arm"],
                "subscription_id": r["subscription_id"],
                "event": r["event"],
                "verdict": r["verdict"],
                "payload": json.loads(r["payload"]),
            }
            if r["prev_hash"] != prev:
                return VerifyResult(
                    False, len(rows), r["idx"],
                    f"row {r['idx']}: prev_hash does not match the previous row's hash",
                )
            if _row_hash(prev, body) != r["hash"]:
                return VerifyResult(
                    False, len(rows), r["idx"],
                    f"row {r['idx']}: payload was modified after it was written",
                )
            prev = r["hash"]
        _, keyed = _key()
        detail = (
            "chain intact, keyed" if keyed else
            "chain intact, unkeyed — detects accidental edits, but anyone with "
            "write access could rebuild it; set VASOOLI_LEDGER_KEY to prevent that"
        )
        return VerifyResult(True, len(rows), None, detail, keyed)

    def rows(self, run_id: str | None = None) -> list[sqlite3.Row]:
        if run_id:
            return self.conn.execute(
                "select * from ledger where run_id = ? order by idx", (run_id,)
            ).fetchall()
        return self.conn.execute("select * from ledger order by idx").fetchall()

    def close(self) -> None:
        self.conn.close()
