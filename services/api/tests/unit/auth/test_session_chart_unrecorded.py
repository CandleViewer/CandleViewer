"""#5512 (C-2.9, B16.7): `SessionChart` never returns quietly from an event it had to record but
can no longer.

A must-record event (one whose B16 transition writes an audit record) that a chart past its end
(`elevation.dead`) holds, or one of `_MUST_REACH` whose step changes nothing because the chart is
already past the state it must reach, raises `SessionChartUnrecorded`, and the chart is dropped, to
be rebuilt from the session's row on its next use. `SessionChart.revoke` drops the chart however
its record ends, in a bounded `try/finally`. The stale chart here is one revoked over a live row.
Over the real B16 chart (factory, gateway, bindings) with a recording sink; `LoopClock` moves the
loop's clock, no network, no sleeps.
"""

from __future__ import annotations

import ast
import asyncio
import re
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.api.users import CHART_DROP_TIMEOUT_S
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.session_chart import (
    _MUST_REACH,
    _MUST_RECORD,
    CHART_STOP_TIMEOUT_S,
    SessionChart,
    SessionChartError,
    SessionChartUnrecorded,
    to_us,
)
from candleviewer.auth.session_service import OWNER_REVOKE_AUDIT_TIMEOUT_S
from candleviewer.statechart.bindings import b16_session
from candleviewer.statechart.config import CV_EVENT_SCHEMAS
from candleviewer.statechart.registry import Registry
from tests.conftest import RecordingAuditSink

from .session_fakes import LoopClock
from .test_step_up import _T0, _session, _setup

_CATALOGUE = Path(__file__).resolve().parents[5] / "docs" / "plan" / "28-statechart-catalogue.md"
_TICKED = re.compile(r"`([^`]+)`")
_LATER_US = to_us(_T0 + timedelta(minutes=5))
#: What each must-record event carries when `StepUpService` sends it.
_PAYLOADS: dict[str, dict[str, Any]] = {
    "STEP_UP_OK": {"action_class": "keys", "elevated_until_us": _LATER_US},
    "ACTION_REQUEST": {"action_class": "keys", "now_us": to_us(_T0)},
    "STEP_UP_FAILED": {"action_class": "keys", "now_us": to_us(_T0)},
}


async def _stale(chart: SessionChart, row: SessionRecord) -> None:
    """B16 records a revocation the row never takes: the chart is revoked over a live row."""
    await chart.record(row, _T0, "REVOKE", reason="admin")
    assert chart.in_state(str(row.id), "revoked") and row.revoked_at is None


@pytest.mark.parametrize("event", sorted(_PAYLOADS))
async def test_send_raises_when_a_must_record_event_is_deferred(
    event: str, b16_audit: RecordingAuditSink
) -> None:
    row, chart = _session(uuid.uuid4()), SessionChart()
    try:
        await _stale(chart, row)
        mark = len(b16_audit.calls)
        with pytest.raises(SessionChartUnrecorded) as raised:
            await chart.record(row, _T0, event, **_PAYLOADS[event])
        assert (raised.value.event, raised.value.reason) == (event, "deferred")
        assert isinstance(raised.value, SessionChartError)  # every caller's existing arm
        assert b16_audit.calls[mark:] == []
        assert chart.interpreter(str(row.id)) is None  # dropped, never kept out of step
    finally:
        await chart.stop()


@pytest.mark.parametrize("event", sorted(_PAYLOADS))
async def test_a_held_event_behind_a_concurrent_revoke_raises(
    event: str, b16_audit: RecordingAuditSink
) -> None:
    """The hold check reads the held chart's state from its receipt: the event the revoked chart
    holds raises, the revoke returns, and the revocation is the only record."""
    row, chart = _session(uuid.uuid4()), SessionChart()
    try:
        await chart.record(row, _T0, "REQUEST", replay=True)  # built from the row
        revoked, held = await asyncio.gather(
            chart.revoke(row, _T0, "admin"),
            chart.record(row, _T0, event, **_PAYLOADS[event]),
            return_exceptions=True,
        )
        assert revoked is None and isinstance(held, SessionChartUnrecorded)
        assert (held.event, held.reason) == (event, "deferred")
        assert b16_audit.actions() == ["auth.session_revoked"]
    finally:
        await chart.stop()


async def test_a_hold_in_a_state_the_chart_leaves_again_returns_and_keeps_the_chart(
    b16_audit: RecordingAuditSink,
) -> None:
    """`readonly_downgrade` holds `ACTION_REQUEST` until `READONLY_EXPIRED` leaves it; that hold
    returns and keeps the chart, unchanged by #5512. A held `STEP_UP_OK` raises in any state."""
    row = _session(uuid.uuid4()).model_copy(
        update={"step_up_failures": 3, "readonly_until": _T0 + timedelta(minutes=5)}
    )
    chart = SessionChart()
    try:
        await chart.record(row, _T0, "REQUEST", replay=True)  # hydrated: three strikes
        assert chart.in_state(str(row.id), "readonly_downgrade")
        await chart.record(row, _T0, "ACTION_REQUEST", **_PAYLOADS["ACTION_REQUEST"])
        assert chart.in_state(str(row.id), "readonly_downgrade") and b16_audit.calls == []
    finally:
        await chart.stop()


async def test_a_step_up_ok_held_in_readonly_downgrade_raises_and_drops_the_chart(
    b16_audit: RecordingAuditSink,
) -> None:
    """The step-up's arm for it ends the grant (`StepUpUnrecorded`, `503`)."""
    row = _session(uuid.uuid4()).model_copy(
        update={"step_up_failures": 3, "readonly_until": _T0 + timedelta(minutes=5)}
    )
    chart = SessionChart()
    try:
        await chart.record(row, _T0, "REQUEST", replay=True)  # hydrated: three strikes
        assert chart.in_state(str(row.id), "readonly_downgrade")
        with pytest.raises(SessionChartUnrecorded) as raised:
            await chart.record(row, _T0, "STEP_UP_OK", **_PAYLOADS["STEP_UP_OK"])
        assert (raised.value.event, raised.value.reason) == ("STEP_UP_OK", "deferred")
        assert b16_audit.calls == [] and chart.interpreter(str(row.id)) is None
    finally:
        await chart.stop()


@pytest.mark.parametrize("event", ["REVOKE", "LOGOUT", "ABSOLUTE_DEADLINE"])
async def test_send_raises_when_the_state_an_event_must_reach_was_already_held(
    event: str, b16_audit: RecordingAuditSink
) -> None:
    """The step changes nothing, so the state's entry, which writes the record, never runs."""
    row, chart = _session(uuid.uuid4()), SessionChart()
    try:
        await _stale(chart, row)
        mark = len(b16_audit.calls)
        with pytest.raises(SessionChartUnrecorded) as raised:
            await chart.record(row, _T0, event, reason="admin")
        assert (raised.value.event, raised.value.reason) == (event, "unchanged")
        assert b16_audit.calls[mark:] == []
        assert chart.interpreter(str(row.id)) is None
    finally:
        await chart.stop()


async def test_an_idle_lock_on_a_stale_chart_raises_and_the_retry_records_it(
    b16_audit: RecordingAuditSink,
) -> None:
    """The lock a live row shows is sent to a chart that has not recorded it, whatever its state:
    a stale chart refuses it loudly and is dropped, and the next read records the lock."""
    row, chart = _session(uuid.uuid4()), SessionChart()
    sid = str(row.id)
    locked = row.model_copy(update={"last_seen_at": _T0 - timedelta(minutes=16)})
    assert locked.is_idle_locked(now=_T0)
    try:
        await _stale(chart, row)
        mark = len(b16_audit.calls)
        with pytest.raises(SessionChartUnrecorded) as raised:
            await chart.observe(locked, _T0)
        assert (raised.value.event, raised.value.reason) == ("IDLE_DEADLINE", "unchanged")
        assert b16_audit.calls[mark:] == [] and chart.interpreter(sid) is None
        await chart.observe(locked, _T0)
        assert chart.in_state(sid, "idle_locked")
        assert b16_audit.actions()[mark:] == ["auth.idle_locked"]
    finally:
        await chart.stop()


async def test_a_send_the_chart_records_returns_as_before(b16_audit: RecordingAuditSink) -> None:
    """Not deferred: an internal arm that only records (its receipt changes nothing), a step that
    moves a region, the lock and the revocation each write their record and return."""
    row, chart = _session(uuid.uuid4()), SessionChart()
    sid = str(row.id)
    locked = row.model_copy(update={"last_seen_at": _T0 - timedelta(minutes=16)})
    try:
        await chart.record(row, _T0, "ACTION_REQUEST", **_PAYLOADS["ACTION_REQUEST"])
        await chart.record(row, _T0, "STEP_UP_OK", **_PAYLOADS["STEP_UP_OK"])
        assert chart.in_state(sid, "elevated")
        await chart.observe(locked, _T0)
        await chart.revoke(locked, _T0, "admin")
        assert chart.interpreter(sid) is None
    finally:
        await chart.stop()
    assert b16_audit.actions() == [
        "auth.step_up_required",
        "auth.step_up_granted",
        "auth.idle_locked",
        "auth.session_revoked",
    ]


@pytest.mark.parametrize(
    ("event", "payload"),
    [
        ("REQUEST", {"replay": True}),
        ("STEP_UP_OK", {"replay": True, **_PAYLOADS["STEP_UP_OK"]}),
        ("ELEVATION_DEADLINE", {}),
        ("READONLY_EXPIRED", {}),
    ],
)
async def test_a_deferred_event_that_records_nothing_returns_and_keeps_the_chart(
    event: str, payload: dict[str, Any], b16_audit: RecordingAuditSink
) -> None:
    """A replay (hydration, already recorded when it happened) and an event no transition records
    stay quiet when held: no record is due for them."""
    row, chart = _session(uuid.uuid4()), SessionChart()
    try:
        await _stale(chart, row)
        await chart.record(row, _T0, event, **payload)
        assert chart.in_state(str(row.id), "revoked")
        assert b16_audit.actions() == ["auth.session_revoked"]
    finally:
        await chart.stop()


async def test_a_challenge_on_a_stale_chart_raises_and_the_next_one_records(
    b16_audit: RecordingAuditSink,
) -> None:
    """`step_up_required`: `StepUpService.record_pending` fails loudly with nothing recorded, and
    the chart, dropped, is rebuilt from the row for the next challenge."""
    svc, _clock, _seed, _user, sessions = await _setup()
    try:
        await _stale(svc.chart, sessions.sessions["s1"])
        mark = len(b16_audit.calls)
        with pytest.raises(SessionChartUnrecorded):
            await svc.record_pending("s1", "keys")
        assert b16_audit.calls[mark:] == []
        await svc.record_pending("s1", "keys")
        assert b16_audit.actions()[mark:] == ["auth.step_up_required"]
    finally:
        await svc.stop()


# -- the must-record set, against the catalogue's B16 tables -------------------------------------


def _rows(text: str, heading: str) -> list[list[str]]:
    """The cells of each row of the table under *heading* (B16.2 or B16.3), header and rule
    dropped."""
    lines = text[text.index(heading) :].splitlines()[1:]
    table: list[list[str]] = []
    for line in lines:
        if line.startswith("### "):
            break
        if line.startswith("|"):
            table.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return table[2:]


def _writers() -> set[str]:
    """The B16 actions that write an audit record: each binding whose body calls `_emit`."""
    tree = ast.parse(Path(b16_session.__file__).read_text(encoding="utf-8"))
    return {
        fn.name
        for fn in tree.body
        if isinstance(fn, ast.AsyncFunctionDef)
        and any(
            isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_emit"
            for node in ast.walk(fn)
        )
    } & set(b16_session.ACTIONS)


def _catalogue() -> tuple[set[str], set[str]]:
    """B16.3's events, and those with a transition that writes a record: an action of its own, or
    an entry action of the state it enters (B16.2)."""
    text = _CATALOGUE.read_text(encoding="utf-8")
    entry = {
        _TICKED.findall(state)[0]: set(_TICKED.findall(actions))
        for state, _kind, _tags, actions, *_ in _rows(text, "### B16.2 States")
    }
    writers, events, recorded = _writers(), set[str](), set[str]()
    for _from, event, _guard, target, actions, *_ in _rows(text, "### B16.3 Events"):
        names = set(_TICKED.findall(event))
        ran = set(_TICKED.findall(actions)).union(*(entry[t] for t in _TICKED.findall(target)))
        events |= names
        if ran & writers:
            recorded |= names
    return events, recorded


def _machine() -> set[str]:
    """The same set from the machine JSON (`Registry`): each event with a transition whose own
    actions, or the entry actions of the state it targets, include a recording binding."""
    chart = Registry().get("session")
    nodes: dict[str, dict[str, Any]] = {}  # every state, by its id
    stack = [(str(chart["id"]), chart)]
    while stack:
        path, node = stack.pop()
        nodes[path] = node
        stack += [(f"{path}.{name}", child) for name, child in node.get("states", {}).items()]
    writers, recorded = _writers(), set[str]()
    for node in nodes.values():
        for event, spec in node.get("on", {}).items():
            for arm in spec if isinstance(spec, list) else [spec]:
                target = nodes[arm["target"].removeprefix("#")] if "target" in arm else {}
                if {*arm.get("actions", []), *target.get("entry", [])} & writers:
                    recorded.add(event)
    return recorded


def test_the_must_record_set_is_every_b16_event_with_a_transition_that_writes_a_record() -> None:
    events, recorded = _catalogue()
    assert events == set(CV_EVENT_SCHEMAS["session"])  # the table names every event B16 takes
    assert _MUST_RECORD == recorded
    assert _machine() == recorded  # the machine JSON agrees with the catalogue
    assert {"STEP_UP_OK", "ACTION_REQUEST", "IDLE_DEADLINE", "LOGOUT"} <= _MUST_RECORD
    assert events - _MUST_RECORD == {"ELEVATION_DEADLINE", "READONLY_EXPIRED"}
    assert set(_MUST_REACH) <= _MUST_RECORD


# -- the bounded drop in `revoke` -----------------------------------------------------------------


class _SlowRevocation(RecordingAuditSink):
    """B16's sink: `auth.session_revoked` waits for `release`, as a slow audit writer does."""

    def __init__(self) -> None:
        super().__init__()
        self.parked, self.release = asyncio.Event(), asyncio.Event()

    async def emit(self, action: str, **kwargs: Any) -> None:
        if action == "auth.session_revoked":
            self.parked.set()
            await self.release.wait()
        await super().emit(action, **kwargs)


async def test_a_revoke_cut_short_by_its_bound_drops_the_chart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The caller's bound (here the owner revoke's) expires while the revocation records: the
    chart is dropped before the timeout reaches the caller, and once the writer answers, the
    session's next step-up records on a chart rebuilt from its row."""
    sink, clock = _SlowRevocation(), LoopClock(monkeypatch)
    b16_session.set_audit_sink(sink)
    row, chart = _session(uuid.uuid4()), SessionChart()
    sid = str(row.id)

    async def bounded() -> None:
        async with asyncio.timeout(OWNER_REVOKE_AUDIT_TIMEOUT_S):
            await chart.revoke(row, _T0, "admin")

    try:
        revoking = asyncio.create_task(bounded())
        await asyncio.wait_for(sink.parked.wait(), timeout=5)
        clock.advance(OWNER_REVOKE_AUDIT_TIMEOUT_S)  # the bound expires; the real clock has not
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(revoking, timeout=5)
        assert chart.interpreter(sid) is None
        sink.release.set()  # the writer answers at last
        await chart.record(row, _T0, "STEP_UP_OK", **_PAYLOADS["STEP_UP_OK"])
        assert chart.in_state(sid, "elevated")
        assert sink.actions() == ["auth.step_up_granted"]
    finally:
        await chart.stop()


async def test_a_cut_short_revoke_drops_the_chart_while_another_build_holds_the_chart_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The drop never waits for the chart lock, which another session's build may hold for long:
    the chart is gone as the bound reaches the caller."""
    sink, clock = _SlowRevocation(), LoopClock(monkeypatch)
    b16_session.set_audit_sink(sink)
    row, chart = _session(uuid.uuid4()), SessionChart()

    async def bounded() -> None:
        async with asyncio.timeout(OWNER_REVOKE_AUDIT_TIMEOUT_S):
            await chart.revoke(row, _T0, "admin")

    try:
        revoking = asyncio.create_task(bounded())
        await asyncio.wait_for(sink.parked.wait(), timeout=5)
        async with chart._lock:  # another session's build
            clock.advance(OWNER_REVOKE_AUDIT_TIMEOUT_S)
            await asyncio.wait({revoking}, timeout=5)
            assert revoking.done() and isinstance(revoking.exception(), TimeoutError)
            assert chart.interpreter(str(row.id)) is None
    finally:
        await chart.stop()


@pytest.mark.parametrize("failure", ["raises", "overruns"])
async def test_a_chart_stop_that_fails_or_overruns_is_logged_and_the_revoke_returns(
    failure: str, monkeypatch: pytest.MonkeyPatch, b16_audit: RecordingAuditSink
) -> None:
    """The chart leaves the cache at once and its stop is bounded by `CHART_STOP_TIMEOUT_S`, no
    longer than the role change's drop bound: a stop that raises or overruns is logged with its
    error class and the session id only, and never replaces how the record ended."""
    assert CHART_STOP_TIMEOUT_S <= CHART_DROP_TIMEOUT_S
    clock, entered = LoopClock(monkeypatch), asyncio.Event()
    row, chart = _session(uuid.uuid4()), SessionChart()
    await chart.record(row, _T0, "REQUEST", replay=True)  # built from the row
    interp = chart.interpreter(str(row.id))
    assert interp is not None
    kind = type(interp)
    real_stop = kind.stop

    async def stuck(self: Any) -> None:
        entered.set()
        if failure == "raises":
            raise RuntimeError("the chart cannot be stopped")
        await asyncio.Event().wait()  # only the stop's bound ends this

    monkeypatch.setattr(kind, "stop", stuck)
    try:
        with capture_logs() as logs:
            revoking = asyncio.create_task(chart.revoke(row, _T0, "admin"))
            await asyncio.wait_for(entered.wait(), timeout=5)
            clock.advance(CHART_STOP_TIMEOUT_S)  # the stop's own bound expires
            await asyncio.wait_for(revoking, timeout=2)  # cut at this bound, not a longer one
        assert chart.interpreter(str(row.id)) is None
    finally:
        await real_stop(interp)
        await chart.stop()
    (line,) = [e for e in logs if e["event"] == "auth.session_chart.chart_not_stopped"]
    error = "RuntimeError" if failure == "raises" else "TimeoutError"
    assert line == {
        "event": "auth.session_chart.chart_not_stopped",
        "session_id": str(row.id),
        "error": error,
        "log_level": "error",
    }
    assert b16_audit.actions() == ["auth.session_revoked"]


async def test_a_drop_with_no_chart_cached_leaves_a_build_of_the_same_session_registered(
    monkeypatch: pytest.MonkeyPatch, b16_audit: RecordingAuditSink
) -> None:
    """Nothing is cached while the session's chart is being built, so a drop then leaves the build
    alone: it completes, and its chart records."""
    row, chart = _session(uuid.uuid4()), SessionChart()
    sid, hydrating, release = str(row.id), asyncio.Event(), asyncio.Event()
    hydrate = chart._hydrate

    async def parked(*args: Any) -> None:
        hydrating.set()
        await release.wait()
        await hydrate(*args)

    monkeypatch.setattr(chart, "_hydrate", parked)
    try:
        building = asyncio.create_task(chart.observe(row, _T0))
        await asyncio.wait_for(hydrating.wait(), timeout=5)
        await chart._drop(sid)
        release.set()
        await asyncio.wait_for(building, timeout=5)
        await chart.record(row, _T0, "STEP_UP_OK", **_PAYLOADS["STEP_UP_OK"])
        assert chart.in_state(sid, "elevated")
        assert b16_audit.actions() == ["auth.step_up_granted"]
    finally:
        await chart.stop()
