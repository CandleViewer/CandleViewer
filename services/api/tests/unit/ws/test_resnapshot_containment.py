"""#3262: the hub's re-snapshot of a topic (`23-ws-protocol.md` §7.4) contains a build that raises
to its subscription, flag on and off, so the fan-out reaches every other connection (§10.1); and a
fail-closed close never waits on its log line. Flag on, a connection's sink is its
`ConnectionPipeline` (`_routed`); flag off, its `TopicEmitter`.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from functools import partial
from typing import Any, NamedTuple

import pytest
from structlog.testing import capture_logs
from structlog.typing import EventDict, Processor, WrappedLogger

from candleviewer.audit.models import Severity
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.metrics import cv_ws_malformed_updates_total
from candleviewer.ws.permissions import Subscription
from candleviewer.ws.pipeline import ConnectionPipeline
from candleviewer.ws.sequencing import SequencingHub, SnapshotBody, cv_ws_resync_total
from tests.unit.ws._seq_support import ACC_A, Book, Conn, Source
from tests.unit.ws.test_pipeline_outbound import (
    _BOOK,
    _DEADLINE_S,
    _MARK,
    _closes,
    _counter,
    _d,
    _pipe,
    _queued,
    _Rig,
    _rows,
    _Wire,
)
from tests.unit.ws.test_pipeline_pacing import _raises, _routed

RS = "bb000000-0000-4000-8000-000000000001"
_FLAG = pytest.mark.parametrize("flag_on", [True, False], ids=["flag_on", "flag_off"])
_BOOK_ENTRY = {"ch": _BOOK, "opts": {"encoding": "structured"}}
_ORDERS = {"ch": "orders", "opts": {"exchange_account_ids": [str(ACC_A)], "symbols": ["BTCUSDT"]}}
_FAILED = "ws snapshot failed"


class _Side(NamedTuple):
    """One connection on the hub: its snapshot source, its one subscription, what it was sent
    since the last look and, flag on, its pipeline and the closes it asked for."""

    source: Source
    sub: Subscription
    sent: Callable[[], list[dict[str, Any]]]
    pipe: ConnectionPipeline | None
    asked: list[str]


def _side(hub: SequencingHub, flag_on: bool, entry: Any, rs: str | None = None) -> _Side:
    """A connection registered on `hub`, subscribed to `entry` with its first `snap` taken."""
    pipe: ConnectionPipeline | None = None
    asked: list[str] = []
    if flag_on:
        pipe, asked, conn = _routed(hub)
    else:
        src = Source()
        src.books["BTCUSDT"] = Book("BTCUSDT")
        src.books["BTCUSDT"].apply([["100", "1"]], [])
        conn = Conn(src)
        hub.register(conn.authz, conn.emitter)
    source = conn.emitter.source
    assert isinstance(source, Source)
    source.bodies["orders"] = SnapshotBody({"orders": []})
    _, sub = conn.sub(entry, replay_session_id=rs)
    sent: Callable[[], list[dict[str, Any]]] = conn.take
    if pipe is not None:
        sent = partial(_queued, pipe)
    sent()
    return _Side(source, sub, sent, pipe, asked)


def _failures(logs: list[EventDict]) -> list[tuple[str, str, str]]:
    """Each `ws snapshot failed` line: family, error class and level, with a connection id."""
    assert all("connection_id" in e for e in logs if e["event"] == _FAILED)
    return [(e["family"], e["error"], e["log_level"]) for e in logs if e["event"] == _FAILED]


def _counts(reason: str) -> tuple[float, float]:
    """`book`'s malformed-update count, and the re-snapshots counted under `reason`."""
    malformed = _counter(cv_ws_malformed_updates_total, topic="book")
    return malformed, _counter(cv_ws_resync_total, reason=reason)


def _lookup_fails(*_: Any) -> Any:
    """A build that raises other than `_raises` does: the containment takes any `Exception`."""
    raise KeyError(_MARK)


def _cancelled(*_: Any) -> Any:
    """A build that is cancelled: no guard may contain it (a cancellation is never swallowed)."""
    raise asyncio.CancelledError


def _dead_on(event: str, raised: type[BaseException] = RuntimeError) -> Processor:
    """A log processor that raises on `event` alone, as a log sink failing for that line would."""

    def processor(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
        if event_dict["event"] == event:
            raise raised(_MARK)
        return event_dict

    return processor


# -- SequencingHub.resnapshot (§7.4) -------------------------------------------------------------


@_FLAG
@pytest.mark.parametrize(
    ("trigger", "arg"),
    [
        ("upstream_desync", "BTCUSDT"),
        ("upstream_reconnect", "BTCUSDT"),
        ("instrument_revision", "BTCUSDT"),
        ("replay_seek", RS),
    ],
)
def test_a_raising_build_is_contained_and_every_trigger_reaches_the_others(
    flag_on: bool, trigger: str, arg: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7.4, §10.1: the first connection's build raises, the second still gets its `snap`, and
    the first stays open. Flag on, its topic drops to the ladder's `backpressure` snapshot, sent
    at its writer's next turn; flag off, it stays pending with its reason, for the next
    `flush_pending`. Logged once, by family and error class; counted nowhere, as when flushed."""
    hub, rs = SequencingHub(), RS if trigger == "replay_seek" else None
    bad, good = (_side(hub, flag_on, _BOOK_ENTRY, rs) for _ in range(2))
    build, held, counts = bad.source.build, "backpressure" if flag_on else trigger, _counts(trigger)
    monkeypatch.setattr(bad.source, "build", _raises)
    with capture_logs() as logs:
        assert getattr(hub, trigger)(arg) == 1
    assert [(f["t"], f["meta"]["reason"]) for f in good.sent()] == [("snap", trigger)]
    assert (bad.sent(), bad.asked) == ([], [])
    assert (bad.sub.snapshot_pending, bad.sub.pending_reason) == (True, held)
    assert _failures(logs) == [("book", "RuntimeError", "warning")] and _MARK not in repr(logs)
    assert _counts(trigger) == (counts[0], counts[1] + 1)  # the second connection's `snap` alone
    monkeypatch.setattr(bad.source, "build", build)
    if bad.pipe is not None:
        bad.pipe.service(0.0)  # the writer's turn: the ladder's `drain`
    else:
        assert hub.flush_pending() == 1
    assert [(f["t"], f["meta"]["reason"]) for f in bad.sent()] == [("snap", held)]


@_FLAG
async def test_a_raising_orders_build_is_logged_at_error_and_closes_only_with_the_flag_on(
    flag_on: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§10.1: an `orders` re-snapshot whose build raises fails closed with the flag on, closed and
    logged once, at `error`; the other connection gets its `snap`. The flag-off emitter has no
    close path, so the subscription stays pending with its reason, also logged at `error`."""
    hub = SequencingHub()
    bad, good = (_side(hub, flag_on, _ORDERS) for _ in range(2))
    monkeypatch.setattr(bad.source, "build", _lookup_fails)
    with capture_logs() as logs:
        assert hub.instrument_revision("BTCUSDT") == 1
    [snap] = good.sent()
    assert (snap["ch"], snap["meta"]["reason"]) == ("orders", "instrument_revision")
    assert (bad.sent(), bad.asked) == ([], ["internal_error"] if flag_on else [])
    assert (bad.sub.snapshot_pending, bad.sub.pending_reason) == (True, "instrument_revision")
    assert _failures(logs) == [("orders", "KeyError", "error")] and _MARK not in repr(logs)
    if bad.pipe is not None:  # the terminal slot holds that close's `bye` (§8.6)
        assert bad.pipe.terminal is not None
        assert bad.pipe.terminal.bye["p"]["reason"] == "internal_error"


@_FLAG
def test_a_cancelled_build_leaves_the_trigger_and_every_subscription_pending(
    flag_on: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guards take an `Exception`, never a cancellation: one raised by the first connection's
    build leaves the trigger, and both subscriptions stay pending with its reason, unserved and
    unmarked, for the next `flush_pending`."""
    hub = SequencingHub()
    bad, good = (_side(hub, flag_on, _BOOK_ENTRY) for _ in range(2))
    monkeypatch.setattr(bad.source, "build", _cancelled)
    with pytest.raises(asyncio.CancelledError):
        hub.upstream_desync("BTCUSDT")
    pending = [(s.sent(), s.sub.snapshot_pending, s.sub.pending_reason) for s in (bad, good)]
    assert pending == [([], True, "upstream_desync")] * 2 and bad.asked == []


@_FLAG
def test_the_resnapshot_sends_the_reason_already_pending(flag_on: bool) -> None:
    """§7.7 (#2831), on the line the containment moved: a subscription already awaiting its `snap`
    keeps that reason (here `reconfigure`), and the re-snapshot sends it, not its trigger's."""
    hub = SequencingHub()
    side = _side(hub, flag_on, _BOOK_ENTRY)
    side.sub.snapshot_pending, side.sub.pending_reason = True, "reconfigure"
    assert hub.upstream_reconnect("BTCUSDT") == 1
    assert [f["meta"]["reason"] for f in side.sent()] == ["reconfigure"]


@_FLAG
@pytest.mark.parametrize("raised", [RuntimeError, asyncio.CancelledError], ids=["error", "cancel"])
def test_a_failing_log_line_never_stops_the_fanout(
    flag_on: bool, raised: type[BaseException], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `ws snapshot failed` line raising changes nothing: the next connection still gets its
    `snap`, and the failing one is handled as above. A cancellation from it is never swallowed: it
    leaves the trigger, and both subscriptions stay pending with its reason."""
    hub, cancelled = SequencingHub(), raised is asyncio.CancelledError
    bad, good = (_side(hub, flag_on, _BOOK_ENTRY) for _ in range(2))
    monkeypatch.setattr(bad.source, "build", _raises)
    with capture_logs(processors=[_dead_on(_FAILED, raised)]):
        with pytest.raises(raised) if cancelled else contextlib.nullcontext():
            assert hub.upstream_desync("BTCUSDT") == 1
    assert [f["meta"]["reason"] for f in good.sent()] == ([] if cancelled else ["upstream_desync"])
    held = "backpressure" if flag_on and not cancelled else "upstream_desync"
    assert (bad.sub.pending_reason, good.sub.snapshot_pending) == (held, cancelled)


async def test_through_the_gateway_only_the_failing_socket_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag on, end to end (§4.4, §10.1): the socket whose `orders` re-snapshot raises gets `bye
    internal_error` and `1011`, counted and audited once; the other socket gets its `snap`."""
    rig, socks = _Rig(BackpressureConfig()), [_Wire(), _Wire()]
    before = _closes("internal_error")
    async with asyncio.timeout(_DEADLINE_S):
        opened = [await rig.open(sock) for sock in socks]
        for sock in socks:
            await rig.sub(sock, "orders", symbols=["BTCUSDT"])
        authz = opened[0][1].authz
        assert authz is not None
        (failing,) = authz.by_id.values()
        build = rig.source.build
        monkeypatch.setattr(rig.source, "build", lambda s: _raises() if s is failing else build(s))
        assert rig.sequencing.instrument_revision("BTCUSDT") == 1
        [bye], [snap] = await socks[0].next(), await socks[1].next()
        opened[1][0].cancel()
        await asyncio.wait([handler for handler, _ in opened])
    assert (bye["t"], bye["p"]["reason"], socks[0].closed_with) == ("bye", "internal_error", 1011)
    assert (snap["t"], snap["meta"]["reason"]) == ("snap", "instrument_revision")
    assert _closes("internal_error") == before + 1
    closed = [row for row in _rows(rig) if row[1] == "internal_error"]
    assert closed == [("ws.connection.closed", "internal_error", Severity.WARNING)]


# -- ConnectionPipeline.push: the close comes before its log line (§10.1) ------------------------


@pytest.mark.parametrize("raised", [RuntimeError, asyncio.CancelledError], ids=["error", "cancel"])
def test_an_unencodable_frame_closes_before_its_log_line(
    raised: type[BaseException], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An `orders` frame its encoder refuses closes `internal_error` first, so a log line that
    raises skips no close: an error goes no further (never into the fan-out), and a cancellation
    is never swallowed, raised after the close."""
    pipe, asked = _pipe()

    def dead() -> Any:
        raise raised(_MARK)

    monkeypatch.setattr("candleviewer.ws.pipeline._log", dead)
    cancelled = raised is asyncio.CancelledError
    with pytest.raises(raised) if cancelled else contextlib.nullcontext():
        pipe.push(_d("orders", bad={1}))
    assert asked == [("internal_error", None)] and len(pipe.queue) == 0
