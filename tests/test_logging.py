"""Operational logging. Silent by default, structured when asked.

These assert on the formatter and the handler directly rather than on captured
stderr: a logging handler binds whatever `sys.stderr` was at construction time,
so tests that read captured output are testing pytest's capture mechanics as
much as the logger.
"""

import json
import logging

import pytest

from vasooli import logging as vlog


@pytest.fixture(autouse=True)
def _clean_logger():
    """Hand every test a genuinely fresh logger.

    configure() is deliberately idempotent, so state left by one test makes the
    next pass or fail for the wrong reason. Clearing `handlers` is not enough —
    the logger object is cached in logging's manager along with its level and
    propagate flag — so the cached instance is dropped outright.
    """
    def drop():
        logging.Logger.manager.loggerDict.pop(vlog.LOGGER, None)

    drop()
    yield
    drop()


def _capture() -> tuple[logging.Logger, list[str]]:
    """Attach a real JsonFormatter to a list sink."""
    lines: list[str] = []

    class Sink(logging.Handler):
        def emit(self, record):
            lines.append(self.format(record))

    log = logging.getLogger(vlog.LOGGER)
    h = Sink()
    h.setFormatter(vlog.JsonFormatter())
    log.addHandler(h)
    log.setLevel(logging.INFO)
    return log, lines


# --- silent by default --------------------------------------------------------

def test_installs_only_a_null_handler_when_unset(monkeypatch):
    # A library that writes to stderr unasked corrupts the output of whatever is
    # calling it, and this CLI's reports are read by a human in a terminal.
    monkeypatch.delenv("VASOOLI_LOG", raising=False)
    log = vlog.configure()
    assert len(log.handlers) == 1
    assert isinstance(log.handlers[0], logging.NullHandler)


def test_installs_a_stream_handler_when_set(monkeypatch):
    monkeypatch.setenv("VASOOLI_LOG", "info")
    log = vlog.configure()
    assert any(isinstance(h, logging.StreamHandler) for h in log.handlers)
    assert log.level == logging.INFO


def test_configure_is_idempotent(monkeypatch):
    monkeypatch.setenv("VASOOLI_LOG", "info")
    a = vlog.configure()
    b = vlog.configure()
    assert a is b
    assert len(a.handlers) == 1


def test_unrecognised_level_falls_back_to_info(monkeypatch):
    monkeypatch.setenv("VASOOLI_LOG", "nonsense")
    assert vlog.configure().level == logging.INFO


def test_never_propagates_to_the_root_logger(monkeypatch):
    # Propagating would let a host application's root handler print our lines
    # even when VASOOLI_LOG is unset.
    monkeypatch.delenv("VASOOLI_LOG", raising=False)
    assert vlog.configure().propagate is False


# --- structure ----------------------------------------------------------------

def test_event_emits_json_with_its_fields(monkeypatch):
    monkeypatch.setenv("VASOOLI_LOG", "info")
    _, lines = _capture()
    vlog.event("execute.batch_complete", records=5, arm="sequencer")
    payload = json.loads(lines[-1])
    assert payload["event"] == "execute.batch_complete"
    assert payload["records"] == 5
    assert payload["arm"] == "sequencer"
    assert payload["level"] == "info"
    assert "ts" in payload


def test_problem_emits_at_warning(monkeypatch):
    monkeypatch.setenv("VASOOLI_LOG", "info")
    _, lines = _capture()
    vlog.problem("diagnose.degraded", reason="gateway down")
    payload = json.loads(lines[-1])
    assert payload["level"] == "warning"
    assert payload["reason"] == "gateway down"


def test_non_serialisable_fields_do_not_crash_the_logger(monkeypatch):
    from datetime import datetime
    monkeypatch.setenv("VASOOLI_LOG", "info")
    _, lines = _capture()
    vlog.event("test", when=datetime(2026, 9, 3), obj=object())
    assert json.loads(lines[-1])["when"].startswith("2026-09-03")


# --- timing -------------------------------------------------------------------

def test_timed_reports_duration_and_success(monkeypatch):
    monkeypatch.setenv("VASOOLI_LOG", "info")
    _, lines = _capture()
    with vlog.timed("diagnose.batch", records=3):
        pass
    payload = json.loads(lines[-1])
    assert payload["ok"] is True
    assert payload["records"] == 3
    assert isinstance(payload["ms"], (int, float))


def test_timed_still_reports_when_the_body_raises(monkeypatch):
    # A slow failure is the one whose duration matters most, so the timing must
    # survive the exception rather than being skipped by it.
    monkeypatch.setenv("VASOOLI_LOG", "info")
    _, lines = _capture()
    with pytest.raises(ValueError), vlog.timed("diagnose.batch"):
        raise ValueError("boom")
    payload = json.loads(lines[-1])
    assert payload["ok"] is False
    assert payload["error"] == "ValueError"


def test_timed_reraises_rather_than_swallowing(monkeypatch):
    monkeypatch.setenv("VASOOLI_LOG", "info")
    _capture()
    with pytest.raises(KeyError), vlog.timed("t"):
        raise KeyError("k")
