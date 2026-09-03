"""Operational logging. Deliberately small, because the ledger already exists.

Every decision this system makes about money is already recorded, structurally
and immutably, in the hash-chained ledger. Duplicating that into a log file
would create a second account of the same events, free to disagree with the
first — and when an audit trail and a log disagree, you have neither.

So this covers only what the ledger does not: how long things took, what the
process was doing, and errors that never became decisions. Operational facts,
not financial ones.

JSON lines, because these are meant to be shipped somewhere and queried rather
than read by a person scrolling a terminal.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from contextlib import contextmanager
from typing import Any

LOGGER = "vasooli"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname.lower(),
            "event": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if extra:
            payload.update(extra)
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure(level: str | None = None) -> logging.Logger:
    """Set up the logger once. Silent by default.

    A library that writes to stderr unasked is a library that corrupts someone
    else's output, so nothing is emitted unless VASOOLI_LOG is set.
    """
    log = logging.getLogger(LOGGER)
    if log.handlers:
        return log
    lvl = (level or os.environ.get("VASOOLI_LOG", "")).upper()
    if not lvl:
        log.addHandler(logging.NullHandler())
        log.propagate = False
        return log
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(JsonFormatter())
    log.addHandler(h)
    log.setLevel(getattr(logging, lvl, logging.INFO))
    log.propagate = False
    return log


def event(name: str, **fields: Any) -> None:
    configure().info(name, extra={"fields": fields})


def problem(name: str, **fields: Any) -> None:
    configure().warning(name, extra={"fields": fields})


@contextmanager
def timed(name: str, **fields: Any):
    """Time a stage. Emits even when the body raises, because a slow failure is
    the one you most want the duration of."""
    start = time.perf_counter()
    try:
        yield
    except Exception as e:
        event(name, ms=round((time.perf_counter() - start) * 1000, 1),
              ok=False, error=type(e).__name__, **fields)
        raise
    else:
        event(name, ms=round((time.perf_counter() - start) * 1000, 1), ok=True, **fields)
