"""#3363: with the flag off, the hub's flush and publish fan-outs contain what one connection's
`TopicEmitter` raises, as #3262 did for its re-snapshot (`23-ws-protocol.md` §7.1, §7.4, §10.1).
Every other connection is still served; a `snap` that a flush or a waking publish cannot build
or queue stays pending with its reason; a `d` that raises leaves its subscription, only that
one, pending an `upstream_desync` `snap`, counted as a malformed update, so its client gets that
`snap`, never a `d` across the update it lost; a waking publish (`machines.*`) sends that `snap`
at once, an entity's last publish included. A connection's `on_rebuild` that raises is
contained too, and a failure that repeats logs one line an interval, `orders` and `executions`
aside. A cancellation is never contained. Flag on, the sink is a `ConnectionPipeline`, which
contains these itself (`test_pipeline_pacing.py`, `test_resnapshot_containment.py`).
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from typing import Any, Final

import pytest
from structlog.testing import capture_logs
from structlog.typing import EventDict

from candleviewer.ws import sequencing
from candleviewer.ws.binary import BOOK_DELTA, Frame
from candleviewer.ws.machines import MachineEntity, MachineStateRegistry
from candleviewer.ws.metrics import cv_ws_malformed_updates_total
from candleviewer.ws.permissions import Subscription
from candleviewer.ws.sequencing import SequencingHub, SnapReason, SnapshotBody, cv_ws_resync_total
from candleviewer.ws.topics import FAMILIES
from tests.unit.ws._seq_support import ACC_A, Book, Clock, Conn, Source
from tests.unit.ws.test_machines import OID, ON_A, _attach, _payload
from tests.unit.ws.test_pipeline_outbound import _BOOK, _MARK, _counter
from tests.unit.ws.test_pipeline_pacing import _raises
from tests.unit.ws.test_resnapshot_containment import (
    _BOOK_ENTRY,
    _ORDERS,
    _cancelled,
    _dead_on,
    _lookup_fails,
)

_SITES = pytest.mark.parametrize("site", ["flush", "wake", "delta"])
_ENTRIES = pytest.mark.parametrize("entry", [_BOOK_ENTRY, _ORDERS], ids=["book", "orders"])
_BODIES: dict[str, dict[str, Any]] = {
    _BOOK: {"symbol": "BTCUSDT", "bids": [], "asks": []},
    "orders": {"orders": []},
}
#: A private family that is not `never_throttled` (only `orders` and `executions` are).
_POSITIONS = {"ch": "positions", "opts": {"exchange_account_ids": [str(ACC_A)]}}
#: Every `never_throttled` family, read from the registry so a third one is flagged as added.
_NEVER_THROTTLED: Final = sorted(f.family for f in FAMILIES.values() if f.never_throttled)
_HELD: Final[SnapReason] = "upstream_reconnect"  # what a flushed or woken one awaits here
_Pair = list[tuple[Conn, Subscription]]


def _pair(hub: SequencingHub, entry: Any = _BOOK_ENTRY, second: Any = None) -> _Pair:
    """Two flag-off connections on `hub`, subscribed to `entry` (the second to `second`, if
    given), each with its first `snap` sent."""
    pairs = []
    for e in (entry, second or entry):
        source = Source()
        source.books["BTCUSDT"] = Book("BTCUSDT")
        source.books["BTCUSDT"].apply([["100", "1"]], [])
        source.bodies["orders"] = SnapshotBody({"orders": []})
        source.bodies["positions"] = SnapshotBody({"positions": []})
        conn = Conn(source)
        hub.register(conn.authz, conn.emitter)
        _, sub = conn.sub(e)
        conn.take()
        pairs.append((conn, sub))
    return pairs


def _machines(hub: SequencingHub) -> tuple[MachineStateRegistry, MachineEntity, _Pair]:
    """Two flag-off connections subscribed to one `order` entity of a registry that fans out
    through `hub` (§6.4), each with its first `snap` sent."""
    registry, order = MachineStateRegistry(hub=hub), MachineEntity("order", OID, ON_A)
    registry.publish(order, _payload())
    pairs: _Pair = []
    for _ in range(2):
        conn = Conn(Source())
        _attach(conn, registry, hub)
        _, sub = conn.sub(order.ch)
        conn.take()
        pairs.append((conn, sub))
    return registry, order, pairs


def _d_raises(
    conn: Conn, mp: pytest.MonkeyPatch, otherwise: Callable[..., Any] | None = None
) -> None:
    """`conn` raises in its push for a `d`, and sends every other frame (or runs `otherwise`)."""
    push = otherwise or conn.emitter.push
    mp.setattr(conn.emitter, "push", lambda f: _raises() if f["t"] == "d" else push(f))


def _arm(
    site: str, pairs: _Pair, raiser: Callable[..., Any], mp: pytest.MonkeyPatch, via: str = ""
) -> None:
    """The first connection raises at `site`, in its push for a `d`; for a flush or a wake, both
    subscriptions pending with their cached snapshot gone, in its build or (`via` "push") its push.
    """
    bad = pairs[0][0]
    if site != "delta":
        for conn, sub in pairs:
            sub.snapshot_pending, sub.pending_reason = True, _HELD
            conn.emitter.cache.invalidate(sub.ch)
    if site == "delta" or via == "push":
        mp.setattr(bad.emitter, "push", raiser)
    else:
        mp.setattr(bad.emitter.source, "build", raiser)


def _fan_out(hub: SequencingHub, site: str, ch: str = _BOOK, **kw: Any) -> int:
    if site == "flush":
        return hub.flush_pending()
    return hub.publish(ch, _BODIES[ch], account=ACC_A, wake=site == "wake", **kw)


def _lines(logs: list[EventDict], site: str) -> list[tuple[str, str, str]]:
    """Each failure line of `site`: family, error class and level, with a connection id."""
    event = "ws delta failed" if site == "delta" else "ws snapshot failed"
    assert all("connection_id" in e for e in logs if e["event"] == event)
    return [(e["family"], e["error"], e["log_level"]) for e in logs if e["event"] == event]


def _seen(conn: Conn) -> list[tuple[str, int, str | None]]:
    return [(f["t"], f["s"], f.get("meta", {}).get("reason")) for f in conn.take()]


@_ENTRIES
@_SITES
@pytest.mark.parametrize(
    ("raiser", "error"), [(_raises, "RuntimeError"), (_lookup_fails, "KeyError")], ids=["rt", "key"]
)
def test_a_raising_connection_is_contained_and_the_other_is_served(
    site: str, entry: Any, raiser: Callable[..., Any], error: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first connection raises (any `Exception`); the second still gets its `snap` (a flush,
    a wake) or its `d` with the next `s`. The first stays pending, with its reason after a failed
    `snap` or for an `upstream_desync` one after a failed `d`, which alone counts as a malformed
    update. Logged once by family and error class (`error` for `orders`); the next flush sends it
    that `snap`."""
    hub, held = SequencingHub(), "upstream_desync" if site == "delta" else _HELD
    pairs = _pair(hub, entry)
    (bad, bs), (good, _) = pairs
    family = bs.topic.family.family
    malformed = _counter(cv_ws_malformed_updates_total, topic=family)
    _arm(site, pairs, raiser, monkeypatch)
    with capture_logs() as logs:
        assert _fan_out(hub, site, bs.ch) == 1
    assert _seen(good) == [("d", 2, None) if site == "delta" else ("snap", 2, _HELD)]
    assert (bad.take(), bs.snapshot_pending, bs.pending_reason) == ([], True, held)
    level = "error" if bs.ch == "orders" else "warning"
    assert _lines(logs, site) == [(family, error, level)] and _MARK not in repr(logs)
    assert _counter(cv_ws_malformed_updates_total, topic=family) == malformed + (site == "delta")
    monkeypatch.undo()
    assert hub.flush_pending() == 1
    assert [reason for _, _, reason in _seen(bad)] == [held]


@_ENTRIES
def test_a_failed_d_is_followed_by_its_snap_never_by_a_d(
    entry: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7.1: the failing subscription is refused every `d` until its `upstream_desync` `snap` (an
    incident, §7.4: counted), which follows the `s` the failed `d` took; then its `d`s resume.
    The other connection's `s` never breaks."""
    hub = SequencingHub()
    pairs = _pair(hub, entry)
    (bad, bs), (good, _) = pairs
    _arm("delta", pairs, _raises, monkeypatch)
    assert _fan_out(hub, "delta", bs.ch) == 1
    monkeypatch.undo()
    desyncs = _counter(cv_ws_resync_total, reason="upstream_desync")
    assert _fan_out(hub, "delta", bs.ch) == 1  # still pending: refused
    assert hub.flush_pending() == 1
    assert _fan_out(hub, "delta", bs.ch) == 2
    assert _seen(bad) == [("snap", 3, "upstream_desync"), ("d", 4, None)]
    assert [s for _, s, _ in _seen(good)] == [2, 3, 4]
    assert _counter(cv_ws_resync_total, reason="upstream_desync") == desyncs + 1


def test_a_raising_flush_spares_its_connections_other_subscriptions_and_every_on_rebuild(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Contained per subscription, not per connection: the failing connection's other pending
    subscription still gets its `snap`, and `on_rebuild` (E17-T03's hook) still tells every
    connection, the failing one too, what the flush named."""
    hub = SequencingHub()
    pairs = _pair(hub)
    (bad, bs), (good, gs) = pairs
    _, orders = bad.sub(_ORDERS)
    bad.take()
    source = bad.emitter.source
    assert isinstance(source, Source)
    build = source.build
    _arm("flush", pairs, lambda sub: _raises() if sub is bs else build(sub), monkeypatch)
    orders.snapshot_pending, orders.pending_reason = True, _HELD
    told: list[list[Subscription]] = []
    for conn, _ in pairs:
        conn.emitter.on_rebuild = told.append
    assert hub.flush_pending() == 2
    assert [(f["ch"], f["meta"]["reason"]) for f in bad.take()] == [("orders", _HELD)]
    assert [f["ch"] for f in good.take()] == [_BOOK]
    assert told == [[bs, orders], [gs]] and bs.snapshot_pending


def test_a_d_its_encoder_refuses_is_contained_with_a_meta_the_server_does_not_own() -> None:
    """The production shape: every bars `d` carries a `meta` (`include_delta`), and a binary part
    its encoder refuses raises `FrameEncodeError`, a `ValueError`. Neither reaches the caller: the
    binary subscriber awaits its `upstream_desync` `snap`, the structured one gets that `d`."""
    hub = SequencingHub()
    binary = {"ch": _BOOK, "opts": {"encoding": "binary"}}
    (bad, bs), (good, _) = _pair(hub, binary, _BOOK_ENTRY)
    part = Frame(BOOK_DELTA, records=((0, 2**80, 1),), price_scale=1, qty_scale=3)  # too wide
    with capture_logs() as logs:
        assert _fan_out(hub, "delta", part=part, meta={"include_delta": False}) == 1
    assert [(f["s"], f["meta"]) for f in good.take()] == [(2, {"include_delta": False})]
    assert (bad.take(), bs.snapshot_pending, bs.pending_reason) == ([], True, "upstream_desync")
    assert _lines(logs, "delta") == [("book", "FrameEncodeError", "warning")]


def test_a_failed_d_is_contained_to_its_subscription_not_its_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failing connection's other subscription keeps streaming: its `orders` `d`s go on with
    contiguous `s` while its `book` awaits the `snap`."""
    hub = SequencingHub()
    (bad, book), _ = _pair(hub)
    _, orders = bad.sub(_ORDERS)
    bad.take()
    push = bad.emitter.push
    monkeypatch.setattr(bad.emitter, "push", lambda f: _raises() if f["ch"] == _BOOK else push(f))
    for ch in (_BOOK, "orders", _BOOK, "orders"):
        _fan_out(hub, "delta", ch)
    assert (book.snapshot_pending, orders.snapshot_pending) == (True, False)
    assert [(f["ch"], f["s"]) for f in bad.take()] == [("orders", 2), ("orders", 3)]


def test_a_failed_d_of_a_waking_publish_gets_its_snap_at_once_even_for_the_last_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registry stores a payload before it fans it out, so a `snap` built after a failed `d`
    holds it (§6.4). An entity's last publish (`terminal`) has no later one to wake the
    subscription, so that publish sends the `snap` itself: `upstream_desync`, after the `s` the
    failed `d` took, with no `d` before it. The other connection gets its `d`."""
    hub = SequencingHub()
    registry, order, ((bad, bs), (good, _)) = _machines(hub)
    _d_raises(bad, monkeypatch)
    desyncs = _counter(cv_ws_resync_total, reason="upstream_desync")
    assert registry.terminal(order, _payload(state="filled"))
    assert not registry.publish(order, _payload())  # the entity's last: nothing wakes it later
    meta = {"reason": "upstream_desync", "source": "live", "previous_seq": 2}
    assert [(f["t"], f["s"], f["meta"], f["p"]["state"]) for f in bad.take()] == [
        ("snap", 3, meta, "filled")
    ]
    assert [(f["t"], f["s"], f["p"]["state"]) for f in good.take()] == [("d", 2, "filled")]
    assert (bs.snapshot_pending, bs.seq) == (False, 3)
    assert _counter(cv_ws_resync_total, reason="upstream_desync") == desyncs + 1


@pytest.mark.parametrize("wake", [True, False], ids=["wake", "plain"])
def test_only_a_waking_publish_sends_the_snap_of_its_failed_d_at_once(
    wake: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A publish whose source may not hold the update yet (`bars.*`, which retries at its next
    emission) leaves the `snap` pending: one built now could miss that update. A waking publish
    counts the `snap` it sends."""
    hub = SequencingHub()
    (bad, bs), _ = _pair(hub)
    _d_raises(bad, monkeypatch)
    assert hub.publish(_BOOK, _BODIES[_BOOK], account=ACC_A, wake=wake) == (2 if wake else 1)
    assert [(f["t"], f["s"]) for f in bad.take()] == ([("snap", 3)] if wake else [])
    assert (bs.snapshot_pending, bs.seq) == ((False, 3) if wake else (True, 2))


def test_the_snap_after_a_failed_waking_d_is_that_subscriptions_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Contained per subscription, as a wake's `snap` is: the failing connection's other pending
    subscription (its `orders`) waits for its own flush."""
    hub = SequencingHub()
    (bad, book), _ = _pair(hub)
    _, orders = bad.sub(_ORDERS)
    bad.take()
    orders.snapshot_pending, orders.pending_reason = True, _HELD
    _d_raises(bad, monkeypatch)
    assert hub.publish(_BOOK, _BODIES[_BOOK], account=ACC_A, wake=True) == 2
    assert [(f["ch"], f["t"]) for f in bad.take()] == [(_BOOK, "snap")]
    assert (book.snapshot_pending, orders.snapshot_pending) == (False, True)


@pytest.mark.parametrize(
    ("raiser", "error"), [(_raises, "RuntimeError"), (_lookup_fails, "KeyError")], ids=["rt", "key"]
)
def test_a_snap_that_raises_after_a_failed_waking_d_stays_pending_and_is_logged(
    raiser: Callable[..., Any], error: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Contained like any wake's `snap` (`_snapshot_failed`): the connection's push raises for the
    `d` and for the `snap` after it, so it stays pending `upstream_desync` with the `s` that `snap`
    took, one `ws delta failed` and one `ws snapshot failed` are logged at `warning` (`machines`
    is private but not `never_throttled`), and the other connection still gets its `d`. The next
    flush sends the `snap`."""
    hub = SequencingHub()
    registry, order, ((bad, bs), (good, _)) = _machines(hub)
    monkeypatch.setattr(bad.emitter, "push", raiser)
    with capture_logs() as logs:
        assert registry.terminal(order, _payload(state="filled"))
    failed = [(e["event"], e["family"], e["error"], e["log_level"]) for e in logs]
    assert failed == [
        ("ws delta failed", "machines", error, "warning"),
        ("ws snapshot failed", "machines", error, "warning"),
    ]
    assert (bad.take(), bs.snapshot_pending, bs.pending_reason, bs.seq) == (
        [],
        True,
        "upstream_desync",
        3,
    )
    assert [(f["t"], f["s"]) for f in good.take()] == [("d", 2)]
    monkeypatch.undo()
    assert hub.flush_pending() == 1
    assert [(f["t"], f["s"], f["meta"]["previous_seq"]) for f in bad.take()] == [("snap", 4, 3)]


@pytest.mark.parametrize("site", ["flush", "wake"])
def test_a_snap_whose_push_raises_stays_pending_and_takes_no_d(
    site: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`TopicEmitter.snapshot` clears the mark before it queues its frames: a push that raises
    there leaves the subscription pending again, with its reason and the `s` the `snap` took, so
    the next `d` is refused and the next flush sends the `snap`."""
    hub = SequencingHub()
    pairs = _pair(hub)
    (bad, bs), _ = pairs
    _arm(site, pairs, _raises, monkeypatch, via="push")
    assert _fan_out(hub, site) == 1
    assert (bs.snapshot_pending, bs.pending_reason, bs.seq) == (True, _HELD, 2)
    monkeypatch.undo()
    assert (_fan_out(hub, "delta"), bad.take()) == (1, [])
    assert hub.flush_pending() == 1
    assert _seen(bad) == [("snap", 3, _HELD)]


def test_a_failure_that_repeats_logs_once_an_interval_with_a_count_but_orders_every_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A build that keeps failing (as the bars retry runs on every emission) logs at most one
    `warning` per (event, family) per `FAILURE_LOG_INTERVAL_S` on the hub's clock, the next one
    counting those held back (`suppressed`); another event of that family has its own interval,
    and so has another family: `positions` (private, but not `never_throttled`) fails the same
    event in the same interval and still logs its own line, once. `orders` logs each failure, at
    `error`, as flag on logs each of its closes."""
    clock = Clock()
    hub = SequencingHub(clock=clock)
    (bad, book), (good, _) = _pair(hub)
    _, orders = bad.sub(_ORDERS)
    _, positions = bad.sub(_POSITIONS)
    bad.take()
    for sub in (book, orders, positions):
        sub.snapshot_pending, sub.pending_reason = True, _HELD
    bad.emitter.cache.invalidate(_BOOK)
    monkeypatch.setattr(bad.emitter.source, "build", _raises)
    monkeypatch.setattr(good.emitter, "push", _raises)
    with capture_logs() as logs:
        for _ in range(3):
            hub.flush_pending()
        _fan_out(hub, "delta")  # the other connection's book `d` fails: a separate event
        clock.now += sequencing.FAILURE_LOG_INTERVAL_S
        hub.flush_pending()
    lines = [(e["event"], e["family"], e["log_level"], e.get("suppressed")) for e in logs]
    snap, orders_line = ("ws snapshot failed", "book", "warning"), ("ws snapshot failed", "orders")
    positions_line = ("ws snapshot failed", "positions", "warning")
    assert lines == [
        (*snap, 0), (*orders_line, "error", None), (*positions_line, 0),
        (*orders_line, "error", None), (*orders_line, "error", None),
        ("ws delta failed", "book", "warning", 0),
        (*snap, 2), (*orders_line, "error", None), (*positions_line, 2),
    ]  # fmt: skip


def test_the_log_window_is_fixed_so_a_failure_that_repeats_is_never_starved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The interval runs from the line that opened it, whatever it holds back: a build that fails
    every 0.7 s (of a 1 s interval) logs at t = 0 and at t = 1.4, with `suppressed` 0, then 1 (the
    failure at 0.7), and the failure at 2.1 falls in the window the second line opened, to 2.4. A
    window that each held-back failure pushed out would log once, at t = 0, and never again; one
    that began where the last ended, not at the line, would end at 2.0 and log again at t = 2.1."""
    clock = Clock()
    hub = SequencingHub(clock=clock)
    (bad, book), _ = _pair(hub)
    book.snapshot_pending, book.pending_reason = True, _HELD
    bad.emitter.cache.invalidate(_BOOK)
    monkeypatch.setattr(bad.emitter.source, "build", _raises)
    every = 0.7 * sequencing.FAILURE_LOG_INTERVAL_S  # no step on a window's edge: 1.0, 2.0, 2.4
    lines: list[tuple[float, int]] = []
    with capture_logs() as logs:
        for step in range(4):  # t = 0, 0.7, 1.4, 2.1
            clock.now, seen = step * every, len(logs)
            hub.flush_pending()
            failed = [e for e in logs[seen:] if e["event"] == "ws snapshot failed"]
            lines += [(round(clock.now, 1), e["suppressed"]) for e in failed]
    assert lines == [(0.0, 0), (round(2 * every, 1), 1)]


@pytest.mark.parametrize("family", _NEVER_THROTTLED)
def test_a_never_throttled_family_logs_every_failure_at_error_and_holds_none_back(
    family: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`orders` is not the only family the interval spares: each `never_throttled` one, as the
    registry has it, logs every failure at `error` with no `suppressed`, three in one instant
    leaving three lines."""
    hub, source = SequencingHub(clock=Clock()), Source()
    source.bodies[family] = SnapshotBody({family: []})
    conn = Conn(source)
    hub.register(conn.authz, conn.emitter)
    # A family with other admission options fails `Conn.sub`'s assert here, on purpose: flagged.
    _, sub = conn.sub({"ch": family, "opts": {"exchange_account_ids": [str(ACC_A)]}})
    conn.take()
    sub.snapshot_pending, sub.pending_reason = True, _HELD
    conn.emitter.cache.invalidate(sub.ch)
    monkeypatch.setattr(source, "build", _raises)
    with capture_logs() as logs:
        for _ in range(3):
            hub.flush_pending()
    lines = [(e["event"], e["family"], e["log_level"], "suppressed" in e) for e in logs]
    assert lines == [("ws snapshot failed", family, "error", False)] * 3


def test_the_log_interval_is_a_second_and_the_default_clock_is_the_monotonic_one() -> None:
    """§10.1 says "a second" (the flag-on classify interval), and the app builds `SequencingHub()`
    with no clock: a wall clock steps, so the default is `time.monotonic`."""
    assert sequencing.FAILURE_LOG_INTERVAL_S == 1.0
    assert SequencingHub()._clock is time.monotonic


@pytest.mark.parametrize("raiser", [_lookup_fails, _cancelled], ids=["error", "cancel"])
def test_a_raising_on_rebuild_is_contained_to_its_connection(raiser: Callable[..., Any]) -> None:
    """A connection's `on_rebuild` (E17-T03's hook) that raises is logged, by connection and
    error class, and every other connection is still flushed and told. A cancellation from it
    is never contained: it leaves the flush there."""
    hub, cancelled = SequencingHub(), raiser is _cancelled
    (bad, _), (good, gs) = _pair(hub)
    told: list[list[Subscription]] = []
    bad.emitter.on_rebuild, good.emitter.on_rebuild = raiser, told.append
    with capture_logs() as logs:
        with pytest.raises(asyncio.CancelledError) if cancelled else contextlib.nullcontext():
            assert hub.flush_pending() == 0
    assert told == ([] if cancelled else [[gs]])
    failed = [(e["event"], e["error"], e["log_level"], "family" in e) for e in logs]
    assert failed == ([] if cancelled else [("ws rebuild failed", "KeyError", "warning", False)])


@_SITES
@pytest.mark.parametrize("raised", [RuntimeError, asyncio.CancelledError], ids=["error", "cancel"])
def test_a_failing_log_line_never_stops_the_fanout(
    site: str, raised: type[BaseException], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure's log line raising changes nothing: the other connection is still served and
    the failing subscription is pending, as above. A cancellation from it is never swallowed: it
    leaves the fan-out there, the failing subscription already pending, marked again before the
    line for a `snap` whose push raised."""
    hub, cancelled = SequencingHub(), raised is asyncio.CancelledError
    pairs = _pair(hub)
    (_, bs), (good, _) = pairs
    _arm(site, pairs, _raises, monkeypatch, via="push")
    event = "ws delta failed" if site == "delta" else "ws snapshot failed"
    with capture_logs(processors=[_dead_on(event, raised)]):
        with pytest.raises(raised) if cancelled else contextlib.nullcontext():
            assert _fan_out(hub, site) == 1
    assert len(good.take()) == (0 if cancelled else 1)
    held = "upstream_desync" if site == "delta" else _HELD
    assert (bs.snapshot_pending, bs.pending_reason) == (True, held)


@_SITES
def test_a_cancellation_from_a_connection_is_never_contained(
    site: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each guard takes an `Exception`, never a cancellation: one the first connection raises
    leaves the fan-out there, and the second gets nothing. Flushed or woken, both stay pending
    with their reason; a `d` marks neither, and the first one's `s` is taken."""
    hub = SequencingHub()
    pairs = _pair(hub)
    (bad, bs), (good, gs) = pairs
    _arm(site, pairs, _cancelled, monkeypatch)
    with pytest.raises(asyncio.CancelledError):
        _fan_out(hub, site)
    assert (bad.take(), good.take()) == ([], [])
    pending = (True, _HELD) if site != "delta" else (False, "initial")
    assert [(s.snapshot_pending, s.pending_reason) for s in (bs, gs)] == [pending] * 2
    assert (bs.seq, gs.seq) == (2 if site == "delta" else 1, 1)


def test_a_cancellation_from_the_snap_after_a_failed_waking_d_is_never_contained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The `d` raises an `Exception`, which is contained; the `snap` sent after it a cancellation,
    which leaves the fan-out there: the other connection gets nothing."""
    hub = SequencingHub()
    registry, order, ((bad, _), (good, _)) = _machines(hub)
    _d_raises(bad, monkeypatch, otherwise=_cancelled)
    with pytest.raises(asyncio.CancelledError):
        registry.terminal(order, _payload(state="filled"))
    assert (bad.take(), good.take()) == ([], [])


def test_a_pending_reason_stays_and_a_server_owned_meta_key_is_the_callers_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A subscription already pending takes no `d`, so one that raises there (any `Exception`)
    lost nothing and keeps its reason, logged once. A `meta` naming a key the server owns is the
    caller's own error, not a connection's: it still reaches the caller, before any `s` is taken
    (`test_sequencing_meta.py`)."""
    hub = SequencingHub()
    (bad, waiting), (good, live) = _pair(hub)
    waiting.snapshot_pending, waiting.pending_reason = True, "reconfigure"
    monkeypatch.setattr(bad.emitter, "delta", lambda *_, **__: _lookup_fails())
    with capture_logs() as logs:
        assert _fan_out(hub, "delta") == 1
    assert (waiting.snapshot_pending, waiting.pending_reason) == (True, "reconfigure")
    assert _lines(logs, "delta") == [("book", "KeyError", "warning")]
    monkeypatch.undo()
    with pytest.raises(ValueError, match="server-owned"):
        _fan_out(hub, "delta", meta={"reason": "initial"})
    assert ([s for _, s, _ in _seen(good)], live.seq) == ([2], 2)
