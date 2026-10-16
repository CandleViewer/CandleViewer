"""Unit tests for ReadOnlyGate (E09-T04)."""

from __future__ import annotations

import pytest

from candleviewer.net.binding_check import BindingCheckResult
from candleviewer.net.read_only_gate import ReadOnlyGate

_PASSING = BindingCheckResult(
    safe=True,
    bound_addresses=("127.0.0.1:8000",),
    reason_code="net.binding_safe",
    reason_text="All listening sockets are loopback/mesh-only.",
)
_FAILING = BindingCheckResult(
    safe=False,
    bound_addresses=("0.0.0.0:8000",),
    reason_code="net.public_binding_detected",
    reason_text="bad bind",
)


def test_gate_defaults_to_writable() -> None:
    gate = ReadOnlyGate()
    assert gate.is_read_only is False


def test_gate_trip_sets_read_only_and_reason() -> None:
    gate = ReadOnlyGate()
    gate.trip(reason_code="net.public_binding_detected", reason_text="bad bind")
    assert gate.is_read_only is True
    assert gate.reason_code == "net.public_binding_detected"
    assert gate.reason_text == "bad bind"


def test_gate_clear_restores_writable_state_given_a_passing_check() -> None:
    gate = ReadOnlyGate()
    gate.trip(reason_code="x", reason_text="y")
    gate.clear(check_result=_PASSING)
    assert gate.is_read_only is False
    assert gate.reason_code is None
    assert gate.reason_text is None


def test_gate_clear_rejects_a_failing_check_result() -> None:
    gate = ReadOnlyGate()
    gate.trip(reason_code="x", reason_text="y")
    with pytest.raises(ValueError):
        gate.clear(check_result=_FAILING)
    assert gate.is_read_only is True


def test_gate_trip_survives_a_raising_listener_and_still_notifies_the_rest() -> None:
    """A listener raising must not escape `trip()`/`clear()` (it would kill
    the scheduler loop) and must not stop other listeners being notified;
    the gate itself stays tripped (fail-closed) regardless."""
    calls: list[bool] = []

    def _bad_listener(tripped: bool, reason_code: str | None, reason_text: str | None) -> None:
        raise RuntimeError("listener boom")

    def _good_listener(tripped: bool, reason_code: str | None, reason_text: str | None) -> None:
        calls.append(tripped)

    gate = ReadOnlyGate()
    gate.subscribe(_bad_listener)
    gate.subscribe(_good_listener)

    gate.trip(reason_code="x", reason_text="y")

    assert gate.is_read_only is True
    assert calls == [True]

    gate.clear(check_result=_PASSING)

    assert gate.is_read_only is False
    assert calls == [True, False]


def test_gate_latched_reason_code_is_none_for_a_trip() -> None:
    gate = ReadOnlyGate()
    gate.trip(reason_code="net.public_binding_detected", reason_text="bad bind")
    assert gate.latched_reason_code is None


def test_gate_latched_reason_code_names_the_latch_over_a_trip() -> None:
    gate = ReadOnlyGate()
    gate.trip(reason_code="net.public_binding_detected", reason_text="bad bind")
    gate.latch(reason_code="secrets.kek_unavailable", reason_text="kek")
    assert gate.latched_reason_code == "secrets.kek_unavailable"
