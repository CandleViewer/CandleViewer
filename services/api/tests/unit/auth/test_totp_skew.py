"""TOTP clock-skew diagnostics (E09-Q05 gap #2146): `detect_skew` and `TotpSkewReporter`.

They only observe a rejection and never accept a code: SR-021 stays at +/-1 step and `verify_code`
alone decides acceptance. Fixed secret and clock, no network, no sleeps.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest
import structlog
from hypothesis import given
from hypothesis import strategies as st
from prometheus_client import REGISTRY, generate_latest

from candleviewer.auth.metrics import (
    AUTH_EXPORTED_NAMES,
    auth_totp_clock_skew_total,
    export_auth_metrics,
)
from candleviewer.auth.totp import (
    TOTP_SKEW_DIAGNOSTIC_STEPS,
    detect_skew,
    generate_code,
    time_step_for,
)
from candleviewer.auth.totp_skew import Surface, TotpSkewReporter
from candleviewer.observability.health_probes import SystemEvent
from candleviewer.observability.metrics import CollectorRegistry
from candleviewer.observability.metrics_catalogue import live_specs

from .mfa_fakes import RecordingSystemEvents

#: The codes of steps -12..+12 are pairwise distinct and "000000"/"123456" match none of them.
SECRET = bytes(range(1, 21))
NOW = 1_800_000_000.0
CURRENT = time_step_for(NOW)
BEHIND, AHEAD = "authenticator_behind", "authenticator_ahead"


def _code_at(offset: int) -> str:
    return generate_code(SECRET, CURRENT + offset)


def _counter(kind: str) -> float:
    return REGISTRY.get_sample_value("auth_totp_clock_skew_total", {"kind": kind}) or 0.0


async def _report(
    events: RecordingSystemEvents,
    code: str,
    *,
    surface: Surface = "login",
    seeds: Sequence[bytes] = (SECRET,),
) -> None:
    await TotpSkewReporter(events).report_rejection(seeds, code, unix_time=NOW, surface=surface)


class _Stalls:
    async def write(self, event: SystemEvent) -> None:
        await asyncio.Event().wait()  # never completes: only the reporter's timeout ends it


# -- detect_skew -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("offset", "expected"),
    [(o, o) for o in (-10, -3, -2, 2, 3, 10)] + [(o, None) for o in (-12, -11, -1, 0, 1, 11, 12)],
)
def test_detect_skew_names_a_step_only_between_the_accepted_and_the_diagnostic_window(
    offset: int, expected: int | None
) -> None:
    assert detect_skew(SECRET, _code_at(offset), unix_time=NOW) == expected


@pytest.mark.parametrize("code", ["000000", "123456", "", "12345", "1234567", "12345a", "١٢٣٤٥٦"])
def test_detect_skew_ignores_a_code_that_is_wrong_or_malformed(code: str) -> None:
    assert detect_skew(SECRET, code, unix_time=NOW) is None


def test_detect_skew_never_tries_a_negative_time_step() -> None:
    # unix_time 0 is step 0, so step -2 does not exist: only the +2 side can match.
    assert detect_skew(SECRET, generate_code(SECRET, 2), unix_time=0.0) == 2


@given(
    secret=st.binary(min_size=20, max_size=20),
    unix_time=st.floats(min_value=0, max_value=4_000_000_000, allow_nan=False),
    offset=st.integers(min_value=-14, max_value=14),
)
def test_detect_skew_only_names_a_step_whose_code_it_was_given(
    secret: bytes, unix_time: float, offset: int
) -> None:
    current = time_step_for(unix_time)
    if current + offset < 0:
        return
    code = generate_code(secret, current + offset)
    found = detect_skew(secret, code, unix_time=unix_time)
    if 1 < abs(offset) <= TOTP_SKEW_DIAGNOSTIC_STEPS:
        assert found is not None  # a collision can only swap in another step with the same code
    if found is not None:
        assert 1 < abs(found) <= TOTP_SKEW_DIAGNOSTIC_STEPS
        assert generate_code(secret, current + found) == code


# -- TotpSkewReporter --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("offset", "kind", "side", "surface"),
    [(-3, BEHIND, "behind", "login"), (2, AHEAD, "ahead of", "step_up")],
)
async def test_report_rejection_raises_one_event_and_moves_the_metric(
    offset: int, kind: str, side: str, surface: Surface
) -> None:
    events, before = RecordingSystemEvents(), _counter(kind)
    await _report(events, _code_at(offset), surface=surface)
    assert _counter(kind) == before + 1
    (event,) = events.written
    assert (event.component, event.kind, event.severity) == ("auth", "totp_clock_skew", "warning")
    steps, seconds = abs(offset), abs(offset) * 30
    assert f"clock skew: the authenticator is {steps} steps ({seconds} s) {side} the server" in (
        event.message
    )
    assert event.details == {
        "surface": surface,
        "kind": kind,
        "offset_steps": str(offset),
        "offset_seconds": str(offset * 30),
    }
    assert event.correlation_id is None


async def test_report_rejection_checks_every_seed_and_reports_once() -> None:
    events = RecordingSystemEvents()
    await _report(events, _code_at(-5), seeds=[bytes(range(21, 41)), SECRET, SECRET])
    assert len(events.written) == 1


async def test_report_rejection_without_an_event_sink_still_counts() -> None:
    before = _counter(BEHIND)
    reporter = TotpSkewReporter()
    await reporter.report_rejection([SECRET], _code_at(-4), unix_time=NOW, surface="enrolment")
    assert _counter(BEHIND) == before + 1


async def test_neither_the_log_nor_the_event_carries_the_code_or_the_secret() -> None:
    code, events = _code_at(-3), RecordingSystemEvents()
    with structlog.testing.capture_logs() as logs:
        await _report(events, code)
    (line,) = [entry for entry in logs if entry["event"] == "auth.totp_clock_skew"]
    assert (line["log_level"], line["surface"], line["kind"], line["offset_steps"]) == (
        "warning",
        "login",
        BEHIND,
        -3,
    )
    rendered = repr((logs, events.written))
    assert code not in rendered and SECRET.hex() not in rendered and repr(SECRET) not in rendered


@pytest.mark.parametrize("exc", [RuntimeError("db down"), TimeoutError()])
async def test_a_failing_sink_is_logged_by_class_and_never_raised(exc: Exception) -> None:
    before = _counter(BEHIND)
    with structlog.testing.capture_logs() as logs:
        await _report(RecordingSystemEvents(fail_with=exc), _code_at(-3))
    assert _counter(BEHIND) == before + 1  # the metric does not need the sink
    (line,) = [e for e in logs if e["event"] == "auth.totp_clock_skew_event_failed"]
    assert line["error"] == type(exc).__name__ and "db down" not in repr(logs)


async def test_a_stalled_sink_is_cut_off_by_the_timeout() -> None:
    reporter = TotpSkewReporter(_Stalls(), timeout_s=0.0)  # a deadline already due: no real wait
    with structlog.testing.capture_logs() as logs:
        async with asyncio.timeout(5):  # a missing timeout in the reporter fails here, not hangs
            await reporter.report_rejection([SECRET], _code_at(-3), unix_time=NOW, surface="login")
    errors = [e["error"] for e in logs if e["event"] == "auth.totp_clock_skew_event_failed"]
    assert errors == ["TimeoutError"]


async def test_cancellation_is_never_swallowed() -> None:
    events = RecordingSystemEvents(fail_with=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await _report(events, _code_at(-3))


# -- the metric --------------------------------------------------------------------------------


def test_the_skew_counter_is_catalogued_and_served_on_the_scraped_registry_with_env() -> None:
    spec = next(s for s in live_specs() if s.name == "auth_totp_clock_skew_total")
    assert (spec.kind, spec.labels, spec.exported) == ("counter", ("kind",), True)
    assert AUTH_EXPORTED_NAMES <= {s.name for s in live_specs() if s.exported}
    registry = CollectorRegistry()
    collector = export_auth_metrics(registry, env="demo")
    try:
        auth_totp_clock_skew_total.labels(kind=BEHIND).inc(0)
        text = generate_latest(registry).decode()
    finally:
        collector.close()
    assert 'auth_totp_clock_skew_total{env="demo",kind="authenticator_behind"}' in text
