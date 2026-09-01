"""The taxonomy's job is to refuse to guess. These tests pin that."""

import pytest

from vasooli.taxonomy import (
    CODE_MAP,
    RECOVERABLE,
    TERMINAL,
    FailureClass,
    classify_by_code,
    is_recoverable,
    is_terminal,
)


def test_known_codes_map_to_their_class():
    assert classify_by_code("BAD_REQUEST_ERROR", "mandate_revoked") is FailureClass.MANDATE_REVOKED
    assert classify_by_code("GATEWAY_ERROR", "bank_unavailable") is FailureClass.BANK_DOWNTIME


def test_unmapped_code_is_unknown_not_a_guess():
    # The whole point: an unrecognised failure must not be smuggled into a
    # recoverable class, because that would let it consume a retry.
    assert classify_by_code("GATEWAY_ERROR", "npci_response_code_u69") is FailureClass.UNKNOWN
    assert classify_by_code("TOTAL", "nonsense") is FailureClass.UNKNOWN


def test_recoverable_and_terminal_are_disjoint():
    assert not (RECOVERABLE & TERMINAL)


def test_unknown_is_neither_recoverable_nor_terminal():
    # UNKNOWN must fall through to human review, not be auto-actioned either way.
    assert not is_recoverable(FailureClass.UNKNOWN)
    assert not is_terminal(FailureClass.UNKNOWN)


@pytest.mark.parametrize("fc", [FailureClass.MANDATE_REVOKED, FailureClass.MANDATE_EXPIRED,
                                FailureClass.MANDATE_PAUSED, FailureClass.LIMIT_EXCEEDED])
def test_dead_mandate_classes_are_terminal(fc):
    # Regression guard: if someone ever moves one of these into RECOVERABLE,
    # the system starts burning retries on debits that can never succeed.
    assert is_terminal(fc)


def test_every_code_map_value_is_a_real_class():
    for v in CODE_MAP.values():
        assert isinstance(v, FailureClass)
        assert v is not FailureClass.UNKNOWN
