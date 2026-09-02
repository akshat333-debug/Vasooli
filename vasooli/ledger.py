"""Append-only, hash-chained audit ledger.

Every decision the system makes about money lands here before anything is
executed — what was seen, what it was classified as, what was decided, why, and
what happened. The chain exists so the audit trail cannot be quietly edited after
the fact to make a batch look better than it was.

Chain rule: hash(row) = sha256(prev_hash || canonical_json(payload)). Changing any
historical payload breaks every hash after it, and `verify()` reports the first
broken index rather than a bare True/False, so a tamper is locatable.

Pattern carried over from QuantProto's experiment ledger, where the same problem
appears: a number is only trustworthy if the record behind it cannot be revised.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

GENESIS = "0" * 64

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
    return hashlib.sha256((prev_hash + _canonical(payload)).encode()).hexdigest()


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    rows: int
    #: Ledger index of the first row whose hash does not match. None when ok.
    broken_at: int | None = None
    detail: str = ""


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
        return VerifyResult(True, len(rows), None, "chain intact")

    def rows(self, run_id: str | None = None) -> list[sqlite3.Row]:
        if run_id:
            return self.conn.execute(
                "select * from ledger where run_id = ? order by idx", (run_id,)
            ).fetchall()
        return self.conn.execute("select * from ledger order by idx").fetchall()

    def close(self) -> None:
        self.conn.close()
