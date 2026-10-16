"""E17-S03 acceptance scenarios: snapshot+delta sequencing, resync triggers, chunking, replay vs
live separation (`23-ws-protocol.md` §3.3, §3.6, §7, §11). Every emitted frame is validated
against the §13-§15 schemas by `Conn.push`."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from decimal import Decimal
from typing import Any, get_args

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.auth.generated_permissions import Permission
from candleviewer.bars.errors import SpecCapExceeded
from candleviewer.bars.models import BarSpec
from candleviewer.ws.binary import (
    BOOK_DELTA,
    FLAG_PARTIAL,
    FLAG_REPLAY,
    FOOTPRINT,
    HEATMAP_COLUMN,
    Frame,
    FrameEncodeError,
    decode_b64,
    encode,
)
from candleviewer.ws.permissions import Subscription, VersionedSnapshot, handle_sub
from candleviewer.ws.sequencing import (
    HEATMAP_SNAPSHOT_MAX_COLUMNS,
    MAX_OUTBOUND_FRAME_BYTES,
    RESYNC_MAX_PER_WINDOW,
    SNAP_REASONS,
    SequencingHub,
    SnapReason,
    SnapshotBody,
    SnapshotCache,
    UpstreamBookGuard,
    b64_budget,
    book_window,
    cap_heatmap,
    causal_sort,
    cv_ws_resync_total,
    split_frame,
    split_structured,
    window_delta,
)
from candleviewer.ws.upstream import UpstreamRefs
from tests._corpus import frames as corpus_frames
from tests.unit.ws._seq_support import _BUNDLE, ACC_A, ACC_B, PERMS, USER, Book, Conn, Source

RS = "bb000000-0000-4000-8000-000000000001"


def _book_source(symbol: str = "BTCUSDT", levels: int = 60) -> Source:
    src = Source()
    book = Book(symbol)
    book.apply(
        [[f"{100 - i}.0", "1.000"] for i in range(levels)],
        [[f"{101 + i}.0", "2.000"] for i in range(levels)],
    )
    src.books[symbol] = book
    return src


def _resync_count(reason: str) -> float:
    return cv_ws_resync_total.labels(reason=reason)._value.get()


class RefClient:
    """§7.1 client obligations: tracks last_seq, discards on a gap, never patches across one."""

    def __init__(self) -> None:
        self.bids: dict[str, str] = {}
        self.asks: dict[str, str] = {}
        self.last: int | None = None
        self.gaps = 0
        self.price_scale: int | None = None

    def feed(self, frame: dict[str, Any]) -> None:
        if frame["t"] == "snap":
            if frame["s"] is None:
                return
            self.bids = {p: s for p, s in frame["p"]["bids"]}
            self.asks = {p: s for p, s in frame["p"]["asks"]}
            self.price_scale = frame["p"]["price_scale"]
            self.last = frame["s"]
        elif frame["t"] == "d":
            if self.last is None or frame["s"] != self.last + 1:
                self.gaps += 1
                self.last = None
                return
            self.last = frame["s"]
            for side, levels in ((self.bids, frame["p"]["bids"]), (self.asks, frame["p"]["asks"])):
                for p, s in levels:
                    if Decimal(s) == 0:
                        side.pop(p, None)
                    else:
                        side[p] = s


# -- Scenario: snapshot precedes deltas and the sequence is unbroken ---------------------------


def test_snap_precedes_deltas_with_universal_fields_and_contiguous_sequence() -> None:
    src = _book_source()
    conn = Conn(src)
    result, sub = conn.sub({"ch": "book.BTCUSDT.50", "opts": {"encoding": "structured"}})
    assert result["snapshot_pending"] is True
    for i in range(5):
        assert conn.emitter.delta(sub, {"symbol": "BTCUSDT", "bids": [[f"{i}.5", "1"]], "asks": []})
    out = conn.take()
    snap = out[0]
    assert snap["t"] == "snap" and snap["meta"] == {"reason": "initial", "source": "live"}
    assert len(snap["p"]["bids"]) == 50 and len(snap["p"]["asks"]) == 50
    assert {"price_scale", "qty_scale", "stale"} <= set(snap["p"])
    assert [f["s"] for f in out] == list(range(snap["s"], snap["s"] + 6))
    assert all(f["t"] == "d" for f in out[1:])


def test_delta_before_snapshot_is_suppressed() -> None:
    src = Source()
    src.unavailable.add("BTCUSDT")  # the snapshot cannot be built yet
    conn = Conn(src)
    _, sub = conn.sub("book.BTCUSDT.50")
    assert conn.take() == [] and sub.snapshot_pending
    assert conn.emitter.delta(sub, {"symbol": "BTCUSDT", "bids": [], "asks": []}) is False
    assert sub.seq == 0


def test_binary_snapshot_carries_scales_and_replay_flag_only_on_replay() -> None:
    src = _book_source()
    conn = Conn(src)
    _, live = conn.sub("book.BTCUSDT.50")
    _, replay = conn.sub("book.BTCUSDT.50", replay_session_id=RS)
    live_snap, replay_snap = conn.take()
    for f in (live_snap, replay_snap):
        assert f["e"] == "b64"
        frame = decode_b64(f["p"])
        assert (frame.price_scale, frame.qty_scale, len(frame.records)) == (1, 3, 100)
    assert decode_b64(live_snap["p"]).flags & FLAG_REPLAY == 0
    assert decode_b64(replay_snap["p"]).flags & FLAG_REPLAY
    assert replay_snap["rs"] == RS and replay_snap["meta"]["source"] == "replay"
    assert "rs" not in live_snap and live is not replay


# -- Scenario: applying deltas reproduces server state exactly (recorded fixture) --------------


def _corpus_run(rel: str, depth: int) -> tuple[RefClient, Book, Conn, list[dict[str, Any]]]:
    symbol = json.loads(corpus_frames(rel)[0])["data"]["s"]
    src = Source()
    book = Book(symbol)
    src.books[symbol] = book
    hub = SequencingHub()
    conn = Conn(src)
    hub.register(conn.authz, conn.emitter)
    guard = UpstreamBookGuard()
    client = RefClient()
    sub = None
    prev: tuple[dict[str, str], dict[str, str]] = ({}, {})
    log: list[dict[str, Any]] = []
    for raw in corpus_frames(rel):
        msg = json.loads(raw)
        data = msg["data"]
        snapshot = msg["type"] == "snapshot"
        verdict = guard.observe(symbol, data["u"], snapshot=snapshot)
        if verdict == "desync":
            src.unavailable.add(symbol)
            hub.upstream_desync(symbol)
            continue
        if verdict == "drop":
            continue
        reconnect = snapshot and sub is not None and symbol not in src.unavailable
        book.apply(data["b"], data["a"], reset=snapshot)
        src.gen += 1
        if sub is None:
            _, sub = conn.sub({"ch": f"book.{symbol}.{depth}", "opts": {"encoding": "structured"}})
        elif snapshot:
            src.unavailable.discard(symbol)
            if reconnect:
                hub.upstream_reconnect(symbol)
            else:
                hub.flush_pending()
        else:
            new = (
                book_window(book.bids, depth, descending=True),
                book_window(book.asks, depth, descending=False),
            )
            body = {
                "symbol": symbol,
                "bids": window_delta(prev[0], new[0]),
                "asks": window_delta(prev[1], new[1]),
            }
            hub.publish(sub.ch, body)
        if not sub.snapshot_pending:
            prev = book.top(depth)
        for f in conn.take():
            log.append(f)
            client.feed(f)
    return client, book, conn, log


def test_recorded_fixture_deltas_reproduce_server_book_including_evictions() -> None:
    client, book, _, log = _corpus_run("ws/orderbook_BTCUSDT.jsonl", 50)
    # 5 398 recorded deltas: u=2..2700 applied, the u=2700->2706 gap holds the topic until the
    # rebuild snapshot at line 4001, then 1 399 more apply - none across the gap.
    assert sum(1 for f in log if f["t"] == "d") == 2699 + 1399
    reasons = [f["meta"]["reason"] for f in log if f["t"] == "snap"]
    assert reasons == ["initial", "upstream_desync"]
    assert client.gaps == 0
    bids, asks = book.top(50)
    assert (client.bids, client.asks) == (bids, asks)
    assert len(client.bids) == 50 and len(client.asks) == 50
    # deletions at size 0 and depth-window evictions both travelled on the wire
    assert any(s == "0" for f in log if f["t"] == "d" for _, s in f["p"]["bids"] + f["p"]["asks"])


def test_window_delta_evicts_levels_pushed_out_of_depth() -> None:
    prev = {"100": "1", "99": "1"}
    new = book_window({"101": "2", "100": "1", "99": "1"}, 2, descending=True)
    assert sorted(window_delta(prev, new)) == [["101", "2"], ["99", "0"]]


# -- Scenario: upstream desync produces a snapshot, never a gap --------------------------------


def test_upstream_gap_emits_desync_snap_and_no_delta_crosses_it() -> None:
    before = _resync_count("upstream_desync")
    client, _book, _, log = _corpus_run("ws/gap_orderbook_ETHUSDT.jsonl", 50)
    assert (
        _resync_count("upstream_desync") == before
    )  # fixture has no rebuild snapshot after the gap
    # the gap at u=30->34 leaves the subscription pending: no delta after it reaches the client
    last_d = max(i for i, f in enumerate(log) if f["t"] == "d")
    assert all(f["t"] != "d" for f in log[last_d + 1 :])
    assert client.gaps == 0
    assert sum(1 for f in log if f["t"] == "d") == 29  # u=2..30 only


def test_upstream_desync_snap_carries_reason_previous_seq_and_counts() -> None:
    src = _book_source()
    hub = SequencingHub()
    conn = Conn(src)
    hub.register(conn.authz, conn.emitter)
    _, sub = conn.sub("book.BTCUSDT.50")
    hub.publish(sub.ch, {"symbol": "BTCUSDT", "bids": [], "asks": []})
    src.bodies["trades"] = SnapshotBody({"symbol": "BTCUSDT", "trades": []})
    _, trades = conn.sub("trades.BTCUSDT")
    conn.take()
    before = _resync_count("upstream_desync")
    assert hub.upstream_desync("BTCUSDT") == 1  # book only; trades untouched
    (snap,) = conn.take()
    assert snap["meta"] == {"reason": "upstream_desync", "source": "live", "previous_seq": 2}
    assert snap["s"] == 3 and trades.seq == 1
    assert _resync_count("upstream_desync") == before + 1


def test_desync_while_book_rebuilding_holds_deltas_until_rebuilt() -> None:
    src = _book_source()
    hub = SequencingHub()
    conn = Conn(src)
    hub.register(conn.authz, conn.emitter)
    _, sub = conn.sub("book.BTCUSDT.50")
    conn.take()
    src.unavailable.add("BTCUSDT")
    assert hub.upstream_desync("BTCUSDT") == 0 and sub.snapshot_pending
    assert hub.publish(sub.ch, {"symbol": "BTCUSDT", "bids": [], "asks": []}) == 0
    src.unavailable.clear()
    assert hub.flush_pending() == 1
    (snap,) = conn.take()
    assert snap["meta"]["reason"] == "upstream_desync" and snap["s"] == 2


@pytest.mark.parametrize(
    ("u_seq", "verdicts"),
    [
        ((1, 2, 3), ["apply", "apply", "apply"]),
        ((1, 2, 2), ["apply", "apply", "drop"]),  # duplicate
        ((1, 3, 2), ["apply", "desync", "drop"]),  # out of order -> gap
        ((1, 2, 5, 6), ["apply", "apply", "desync", "drop"]),  # gap, then hold until snapshot
    ],
)
def test_upstream_guard_classifies_gap_out_of_order_and_duplicate(
    u_seq: tuple[int, ...], verdicts: list[str]
) -> None:
    guard = UpstreamBookGuard()
    got = [guard.observe("X", u, snapshot=i == 0) for i, u in enumerate(u_seq)]
    assert got == verdicts
    assert guard.observe("X", 50, snapshot=True) == "apply"
    assert guard.observe("X", 51, snapshot=False) == "apply"
    guard.forget("X")
    assert guard.observe("X", 52, snapshot=False) == "drop"


# -- Scenario: no `snap` before `sub_ok`; only the ladder sends `backpressure` (#2831) ---------


def _hub_book(
    *, unavailable: bool = False, replay: bool = False
) -> tuple[SequencingHub, Conn, Subscription, Source]:
    src = _book_source()
    if unavailable:
        src.unavailable.add("BTCUSDT")
    hub, conn = SequencingHub(), Conn(src)
    hub.register(conn.authz, conn.emitter)
    _, sub = conn.sub("book.BTCUSDT.50", replay_session_id=RS if replay else None)
    conn.take()
    return hub, conn, sub, src


def _hold(sub: Subscription) -> None:
    sub.snapshot_pending, sub.pending_reason = True, "backpressure"  # as the ladder drops it


@pytest.mark.parametrize(
    ("first", "second", "kept"),
    [
        ("initial", "upstream_reconnect", "initial"),
        ("upstream_desync", "upstream_reconnect", "upstream_desync"),
        ("initial", "upstream_desync", "initial"),  # an attach is never counted as a resync
        ("client_resync", "upstream_desync", "upstream_desync"),  # an incident is never hidden
        ("reconfigure", "replay_seek", "reconfigure"),
    ],
)
def test_resnapshot_keeps_an_already_pending_reason(first: str, second: str, kept: str) -> None:
    hub, conn, sub, src = _hub_book(unavailable=first == "initial", replay=second == "replay_seek")
    if first != "initial":  # settled: `first` pends it, as nothing can be built yet
        src.unavailable.add("BTCUSDT")
        assert hub.resnapshot(lambda s: s is sub, first) == 0
    trigger = getattr(hub, second)  # the hub trigger named for the reason
    assert trigger(RS if second == "replay_seek" else "BTCUSDT") == 0
    assert sub.pending_reason == kept
    src.unavailable.clear()
    incidents = _resync_count("upstream_desync")
    assert hub.flush_pending() == 1
    (snap,) = conn.take()
    assert snap["meta"]["reason"] == kept
    assert _resync_count("upstream_desync") == incidents + (kept == "upstream_desync")


def test_resnapshot_never_sends_a_backpressure_pended_snapshot() -> None:
    hub, conn, sub, src = _hub_book()
    with pytest.raises(ValueError, match="only the overflow ladder"):
        hub.resnapshot(lambda s: True, "backpressure")
    _hold(sub)
    assert hub.upstream_reconnect("BTCUSDT") == 0
    assert (conn.take(), sub.pending_reason) == ([], "backpressure")
    builds = src.builds
    assert conn.emitter.snapshot(sub, "backpressure")  # what the ladder's `drain` sends
    assert (src.builds, conn.take()[0]["meta"]["reason"]) == (builds + 1, "backpressure")


def test_resnapshot_upstream_desync_never_displaces_a_backpressure_hold() -> None:
    hub, conn, sub, _ = _hub_book()
    _hold(sub)
    assert hub.upstream_desync("BTCUSDT") == 0  # an incident, yet the ladder still owns the hold
    assert (conn.take(), sub.pending_reason) == ([], "backpressure")


def test_emitter_flush_pending_skips_backpressure() -> None:
    hub, conn, held, src = _hub_book()
    src.bodies["trades"] = SnapshotBody({"symbol": "BTCUSDT", "trades": []})
    _, other = conn.sub("trades.BTCUSDT")
    conn.take()
    _hold(held)
    other.snapshot_pending, other.pending_reason = True, "upstream_reconnect"
    assert conn.emitter.flush_pending([held, other]) == 1 and hub.flush_pending() == 0
    assert [f["ch"] for f in conn.take()] == ["trades.BTCUSDT"] and held.snapshot_pending


def test_client_resync_of_a_backpressure_pended_topic_waits_for_drain() -> None:
    _, conn, sub, _ = _hub_book()
    _hold(sub)
    for i in range(5):
        conn.clock.now = float(i)
        _resync(conn, sub.ch)
    assert (conn.take(), sub.pending_reason, len(sub.resyncs)) == ([], "backpressure", 5)
    assert conn.emitter.snapshot(sub, "backpressure")  # the ladder's `drain`
    conn.clock.now = 60.0  # the first resync ages out of the window
    _resync(conn, sub.ch)  # settled again: answered at once
    _resync(conn, sub.ch)  # the four held ones left in the window still count
    out = conn.take()
    assert [f["t"] for f in out] == ["snap", "snap", "err", "revoked"]
    assert [f["meta"]["reason"] for f in out[:2]] == ["backpressure", "client_resync"]


class _CappedBars:
    async def register(
        self, spec: BarSpec, symbol: str, consumer: str, user: str | None = None
    ) -> None:
        raise SpecCapExceeded("per_user", 8, 8)

    def release(self, spec_hash: str, symbol: str, consumer: str) -> None:
        pass


class _DownSink:
    async def open(self, key: Any) -> None:
        raise RuntimeError("upstream down")

    async def drop(self, key: Any) -> None:
        pass


async def test_sub_ok_announces_only_the_topics_it_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = Conn(_book_source())
    conn.authz.services.bars = _CappedBars()
    admitted: list[Subscription] = []
    admit = conn.authz.admit

    def spy(entry: Any, **kw: Any) -> tuple[dict[str, Any], Subscription | None]:
        result, sub = admit(entry, **kw)
        admitted.extend([sub] if sub is not None else [])
        return result, sub

    monkeypatch.setattr(conn.authz, "admit", spy)
    replies: list[tuple[list[bool], list[bool]]] = []

    async def send(frame: dict[str, Any]) -> None:
        replies.append(([r["ok"] for r in frame["p"]["results"]], [s.announced for s in admitted]))

    topics = ["bars.BTCUSDT.time.5", "book.BTCUSDT.50"]
    await handle_sub(conn.authz, {"t": "sub", "p": {"topics": topics}}, send)
    assert replies == [([False, True], [False, False])]  # nothing announced before `sub_ok`
    assert [s.announced for s in admitted] == [False, True]  # the refused one never


async def test_a_raising_subscribe_upstream_never_snapshots_the_unacknowledged_topic() -> None:
    hub, conn = SequencingHub(), Conn(_book_source())
    hub.register(conn.authz, conn.emitter)
    conn.authz.services.upstream = UpstreamRefs(_DownSink())
    sent: list[dict[str, Any]] = []

    async def send(frame: dict[str, Any]) -> None:
        sent.append(frame)

    with pytest.raises(RuntimeError, match="upstream down"):  # the gateway closes 1011
        await handle_sub(conn.authz, {"t": "sub", "p": {"topics": ["book.BTCUSDT.50"]}}, send)
    assert (sent, hub.flush_pending(), conn.take()) == ([], 0, [])
    assert [s.announced for s in conn.authz.by_id.values()] == [False]


# -- Scenario: a client resyncing in a loop is stopped -----------------------------------------


def _resync(conn: Conn, ch: str, **p: Any) -> None:
    frame = {"t": "resync", "id": "c-90", "ch": ch, "p": {"reason": "sequence_gap", **p}}
    conn.emitter.client_resync(conn.authz, frame)


def test_client_resync_answers_snap_and_sixth_in_a_minute_revokes() -> None:
    src = _book_source()
    conn = Conn(src)
    _, sub = conn.sub("book.BTCUSDT.50")
    conn.take()
    for i in range(5):
        conn.clock.now = float(i)
        _resync(conn, sub.ch, last_seq=1)
        (snap,) = conn.take()
        assert snap["meta"]["reason"] == "client_resync" and snap["s"] == i + 2
    conn.clock.now = 59.0
    _resync(conn, sub.ch)
    err, revoked = conn.take()
    assert (err["t"], err["p"]["code"], err["ch"]) == ("err", "resync_rate_limited", sub.ch)
    assert (revoked["t"], revoked["p"]["reason"]) == ("revoked", "resync_rate_limited")
    assert conn.authz.find(sub.ch) is None


def test_client_resync_window_slides_after_a_minute() -> None:
    conn = Conn(_book_source())
    _, sub = conn.sub("book.BTCUSDT.50")
    for i in range(5):
        conn.clock.now = float(i)
        _resync(conn, sub.ch)
    conn.clock.now = 60.0  # the first one aged out
    conn.take()
    _resync(conn, sub.ch)
    assert [f["t"] for f in conn.take()] == ["snap"]


@pytest.mark.parametrize(
    ("ch", "p", "code"),
    [
        ("book.BTCUSDT.50", {"reason": "bogus"}, "frame_malformed"),
        ("book.BTCUSDT.50", {"reason": "manual", "last_seq": "x"}, "frame_malformed"),
        ("trades.ETHUSDT", {"reason": "manual"}, "not_subscribed"),
        (None, {"reason": "manual"}, "frame_malformed"),
    ],
)
def test_client_resync_rejects_malformed_and_unknown(ch: Any, p: Any, code: str) -> None:
    conn = Conn(_book_source())
    conn.sub("book.BTCUSDT.50")
    conn.take()
    conn.emitter.client_resync(conn.authz, {"t": "resync", "id": "c-1", "ch": ch, "p": p})
    (err,) = conn.take()
    assert (err["p"]["code"], err.get("ch")) == (code, ch)  # a topic name is echoed, none is not


@pytest.mark.parametrize(
    "ch",
    [
        pytest.param("Bad Topic", id="bad-name"),
        pytest.param("t" * 10_000, id="10000-chars"),
        pytest.param("book.BTCUSDT.50\n", id="trailing-newline"),
        pytest.param(5, id="int"),
        pytest.param({"a": 1}, id="object"),
    ],
)
def test_client_resync_with_a_non_topic_ch_is_refused_without_echoing_it(ch: Any) -> None:
    """#2572: the envelope `ch` is a topic name (§13.1), so a `resync` whose `ch` is not one gets
    `err invalid_options` (`field: ch`) and no `ch`. It takes no snapshot, spends none of the
    five-per-minute budget, and never revokes the subscription, however often it is repeated."""
    conn = Conn(_book_source())
    _, sub = conn.sub("book.BTCUSDT.50")
    conn.take()
    for _ in range(RESYNC_MAX_PER_WINDOW + 1):
        frame = {"t": "resync", "id": "c-1", "ch": ch, "p": {"reason": "manual"}}
        conn.emitter.client_resync(conn.authz, frame)
    errs = conn.take()
    assert [(e["t"], e["id"], e["p"]["code"], e["p"]["field"]) for e in errs] == (
        [("err", "c-1", "invalid_options", "ch")] * (RESYNC_MAX_PER_WINDOW + 1)
    )
    assert all("ch" not in e and len(json.dumps(e)) < 400 for e in errs)  # nothing is reflected
    assert not sub.resyncs and conn.authz.find(sub.ch) is sub
    _resync(conn, sub.ch)
    assert [f["t"] for f in conn.take()] == ["snap"]


# -- Scenario: a state-identity change re-snapshots --------------------------------------------


def test_instrument_revision_resnapshots_with_new_price_scale() -> None:
    src = _book_source()
    hub = SequencingHub()
    conn = Conn(src)
    hub.register(conn.authz, conn.emitter)
    _, _sub = conn.sub({"ch": "book.BTCUSDT.50", "opts": {"encoding": "structured"}})
    old = conn.take()[0]
    src.books["BTCUSDT"].scale = 2
    src.gen += 1
    assert hub.instrument_revision("BTCUSDT") == 1
    (snap,) = conn.take()
    assert snap["meta"]["reason"] == "instrument_revision"
    assert (old["p"]["price_scale"], snap["p"]["price_scale"]) == (1, 2)
    assert snap["meta"]["previous_seq"] == old["s"]


def test_reconfigure_ctl_resnapshots_without_reusing_sequence() -> None:
    src = Source()
    src.bodies["heatmap"] = SnapshotBody(
        {"symbol": "BTCUSDT", "time_bucket_ms": 500, "columns": []}, estimated=True
    )
    conn = Conn(src)
    _, sub = conn.sub("heatmap.BTCUSDT")
    conn.emitter.delta(sub, {"symbol": "BTCUSDT", "time_bucket_ms": 500, "columns": []})
    conn.take()
    conn.authz.ctl("heatmap.BTCUSDT", {"time_bucket_ms": 1000})
    conn.emitter.flush_pending([sub])
    (snap,) = conn.take()
    assert snap["meta"] == {"reason": "reconfigure", "source": "live", "previous_seq": 2}
    assert snap["s"] == 3 and snap["p"]["estimated"] is True


def test_upstream_reconnect_and_replay_seek_reasons() -> None:
    src = _book_source()
    hub = SequencingHub()
    conn = Conn(src)
    hub.register(conn.authz, conn.emitter)
    _, _live = conn.sub("book.BTCUSDT.50")
    _, _replay = conn.sub("book.BTCUSDT.50", replay_session_id=RS)
    conn.take()
    assert hub.upstream_reconnect("BTCUSDT") == 1
    assert hub.replay_seek(RS) == 1
    a, b = conn.take()
    assert (a["meta"]["reason"], "rs" in a) == ("upstream_reconnect", False)
    assert (b["meta"]["reason"], b["rs"]) == ("replay_seek", RS)
    with pytest.raises(ValueError, match="unknown snap reason"):
        hub.resnapshot(lambda s: True, "nope")  # type: ignore[arg-type]  # the guard under test
    hub.unregister(conn.authz)
    assert len(hub) == 0
    assert set(SNAP_REASONS) >= {"initial", "client_resync"}


def test_hub_has_no_backpressure_trigger() -> None:
    """#2830: the hub's `backpressure` trigger matched subscriptions by equality, so it could
    re-snapshot another connection's equal one. It is retired, not fixed: the overflow ladder's
    `drain` (`ws/outbound.py`) is the only sender of `backpressure` snapshots."""
    assert not hasattr(SequencingHub, "backpressure")


def test_snap_reasons_are_the_schema_enum_in_order() -> None:
    """`SNAP_REASONS` and the `SnapReason` literal are hand-written copies of the §13
    `snapMeta.reason` enum (§7.4). A reason added to the contract and missed here fails in this
    test, not in `resnapshot()` at runtime."""
    common = json.loads(_BUNDLE.read_text(encoding="utf-8"))["schemas"]
    enum = common["cv://ws/v1/common.schema.json"]["$defs"]["snapMeta"]["properties"]["reason"]
    assert list(SNAP_REASONS) == enum["enum"]
    assert list(get_args(SnapReason)) == enum["enum"]


# -- Scenario: large snapshots are chunked, not truncated --------------------------------------


def _footprint_body(cells_per_bar: int, bars: int) -> SnapshotBody:
    groups = tuple(
        ((0, b, b * 1000, 1), tuple((p, 1, 2, 3, 0) for p in range(cells_per_bar)))
        for b in range(bars)
    )
    structured = {
        "symbol": "BTCUSDT",
        "bar_type": "time",
        "param": "1",
        "bars": [
            {
                "generation": 0,
                "index": b,
                "t_ms": 1_789_000_000_000 + b,
                "cells": [
                    {"price": f"{p}.0", "bid_volume": "1", "ask_volume": "2"}
                    for p in range(cells_per_bar)
                ],
            }
            for b in range(bars)
        ],
    }
    return SnapshotBody(structured, (Frame(FOOTPRINT, groups=groups),), qty_scale=3)


def test_footprint_snapshot_over_4mib_is_chunked_with_one_sequence_number() -> None:
    src = Source()
    src.bodies["footprint"] = _footprint_body(cells_per_bar=2000, bars=70)  # ~4.6 MiB raw
    assert len(encode(src.bodies["footprint"].parts[0])) > MAX_OUTBOUND_FRAME_BYTES
    conn = Conn(src)
    _, sub = conn.sub({"ch": "footprint.BTCUSDT.time.1", "opts": {"encoding": "binary"}})
    out = conn.take()
    assert len(out) >= 2
    assert len({f["id"] for f in out}) == 1
    assert [f["s"] for f in out] == [None] * (len(out) - 1) + [1] and sub.seq == 1
    flags = [decode_b64(f["p"]).flags & FLAG_PARTIAL for f in out]
    assert all(flags[:-1]) and not flags[-1]
    assert all(len(json.dumps(f, separators=(",", ":"))) <= MAX_OUTBOUND_FRAME_BYTES for f in out)
    groups = [g for f in out for g in decode_b64(f["p"]).groups or ()]
    assert len(groups) == 70  # nothing truncated
    # the next delta continues the one-number snapshot
    conn.emitter.delta(sub, {"symbol": "BTCUSDT", "bar_type": "time", "param": "1", "bars": []})
    assert conn.take()[0]["s"] == 2


def test_structured_snapshot_over_limit_is_chunked_and_each_chunk_validates() -> None:
    src = Source()
    src.bodies["footprint"] = _footprint_body(cells_per_bar=50, bars=40)
    conn = Conn(src, max_frame_bytes=20_000)
    _, _sub = conn.sub({"ch": "footprint.BTCUSDT.time.1", "opts": {"encoding": "structured"}})
    out = conn.take()  # each chunk passed the footprint payload schema in Conn.push
    assert len(out) > 1 and out[-1]["s"] == 1 and all(f["s"] is None for f in out[:-1])
    assert sum(len(f["p"]["bars"]) for f in out) == 40
    assert all(len(json.dumps(f, separators=(",", ":"))) <= 20_000 for f in out)


@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_split_frame_boundary_at_exactly_the_limit(delta: int) -> None:
    rec = (0, 1, 1)
    whole = Frame(BOOK_DELTA, records=(rec,) * 100)
    size = len(encode(whole))
    parts = split_frame(whole, size + delta)
    assert len(parts) == (2 if delta < 0 else 1)
    assert sum(len(p.records) for p in parts) == 100
    assert all(len(encode(p)) <= size + delta for p in parts)


def test_split_frame_rejects_unsplittable_units() -> None:
    with pytest.raises(FrameEncodeError):
        split_frame(Frame(BOOK_DELTA, records=((0, 1, 1),) * 2), 30)
    col = Frame(HEATMAP_COLUMN, records=((1, 1),) * 10, prefix=(0, 1, 1))
    assert split_frame(col, 10_000) == [col]
    with pytest.raises(FrameEncodeError):
        split_frame(col, 50)
    with pytest.raises(FrameEncodeError):
        split_structured({"bars": [{"x": "y" * 100}]}, 50)
    assert b64_budget(100, 200) == 0


# -- Scenario: heatmap 2 000-column cap ---------------------------------------------------------


def test_heatmap_snapshot_keeps_most_recent_2000_columns() -> None:
    cols = [
        {"t_ms": i, "price_min": "1", "price_step": "1", "bids": [], "asks": []}
        for i in range(2500)
    ]
    parts = tuple(Frame(HEATMAP_COLUMN, records=(), prefix=(i, 1, 1)) for i in range(2500))
    body = cap_heatmap(SnapshotBody({"symbol": "BTCUSDT", "columns": cols}, parts))
    assert len(body.structured["columns"]) == HEATMAP_SNAPSHOT_MAX_COLUMNS
    assert body.structured["columns"][0]["t_ms"] == 500
    assert len(body.parts) == HEATMAP_SNAPSHOT_MAX_COLUMNS and body.parts[0].prefix == (500, 1, 1)


# -- Scenario: attaching without a snapshot is only allowed when provable -----------------------


def test_snapshot_false_unprovable_forces_snapshot() -> None:
    src = _book_source()
    src.covered_from_ts = 1_789_132_000_000
    conn = Conn(src)
    entry = {"ch": "book.BTCUSDT.50", "opts": {"from_seq": 0, "from_ts_ms": 1_789_000_000_000}}
    result, _sub = conn.sub(entry, snapshot=False)
    assert result["snapshot_forced"] is True and result["snapshot_pending"] is True
    assert [f["t"] for f in conn.take()] == ["snap"]


def test_snapshot_false_provable_attaches_to_deltas_only() -> None:
    src = _book_source()
    src.covered_from_ts = 1_789_132_000_000
    conn = Conn(src)
    entry = {"ch": "book.BTCUSDT.50", "opts": {"from_seq": 0, "from_ts_ms": 1_789_132_000_001}}
    result, sub = conn.sub(entry, snapshot=False)
    assert "snapshot_forced" not in result and result["snapshot_pending"] is False
    assert conn.take() == []
    assert conn.emitter.delta(sub, {"symbol": "BTCUSDT", "bids": [], "asks": []})


# -- Scenario: private topic causal order holds ------------------------------------------------


def test_private_frames_follow_causal_order_and_account_scope() -> None:
    hub = SequencingHub()
    conn_a = Conn(Source(), ACC_A)
    conn_b = Conn(Source(), ACC_B)
    for c in (conn_a, conn_b):
        hub.register(c.authz, c.emitter)
        for fam in ("trade_groups", "positions", "orders", "executions"):
            acc = str(ACC_A if c is conn_a else ACC_B)
            _, sub = c.authz.admit({"ch": fam, "opts": {"exchange_account_ids": [acc]}})
            assert sub is not None
            sub.snapshot_pending = False
    sent = hub.publish_private(
        ACC_A,
        [
            ("trade_groups", {"trade_groups": []}),
            ("positions", {"positions": []}),
            ("orders", {"orders": []}),
            ("executions", {"executions": []}),
        ],
    )
    assert sent == 4
    assert [f["ch"] for f in conn_a.take()] == ["executions", "orders", "positions", "trade_groups"]
    assert conn_b.take() == []  # other account's subscriptions never see it
    assert [c for c, _ in causal_sort([("x", 1), ("orders", 2)])] == ["orders", "x"]


def test_private_snapshots_are_never_shared_across_subscriptions() -> None:
    src = Source()
    src.bodies["orders"] = SnapshotBody({"orders": []})
    cache = SnapshotCache()
    a = Conn(src, ACC_A, cache=cache)
    b = Conn(src, ACC_A, cache=cache)
    a.sub({"ch": "orders", "opts": {"exchange_account_ids": [str(ACC_A)]}})
    b.sub({"ch": "orders", "opts": {"exchange_account_ids": [str(ACC_A)]}})
    assert src.builds == 2 and len(cache) == 0
    pa, pb = a.take()[0]["p"], b.take()[0]["p"]
    assert pa == pb and pa is not pb


def test_public_snapshot_built_once_per_topic_generation() -> None:
    src = _book_source()
    cache = SnapshotCache(maxsize=1)
    conns = [Conn(src, cache=cache) for _ in range(5)]
    for c in conns:
        c.sub("book.BTCUSDT.50")
    assert src.builds == 1
    conns[0].sub("book.BTCUSDT.200")  # evicts the 50-depth entry (bound 1)
    assert src.builds == 2 and len(cache) == 1
    src.gen += 1
    conns[1].emitter.client_resync(
        conns[1].authz, {"t": "resync", "ch": "book.BTCUSDT.50", "p": {"reason": "manual"}}
    )
    assert src.builds == 3


def test_pause_and_resume_do_not_split_the_public_snapshot_cache() -> None:
    """`paused` gates deltas, not the rendered state (#2517): at one generation, a resumed
    subscription and a fresh one share the cached snapshot."""
    src = _book_source()
    cache = SnapshotCache()
    a, b = Conn(src, cache=cache), Conn(src, cache=cache)
    _, sub = a.sub("book.BTCUSDT.50")
    a.authz.ctl("book.BTCUSDT.50", {"paused": True})
    a.authz.ctl("book.BTCUSDT.50", {"paused": False})
    assert a.emitter.flush_pending([sub]) == 1
    b.sub("book.BTCUSDT.50")
    assert src.builds == 1 and len(cache) == 1


# -- Scenario: coalescing does not look like loss ----------------------------------------------


def test_coalesced_delta_consumes_one_sequence_number() -> None:
    conn = Conn(_book_source())
    _, sub = conn.sub({"ch": "book.BTCUSDT.50", "opts": {"encoding": "structured"}})
    conn.take()
    conn.emitter.delta(sub, {"symbol": "BTCUSDT", "bids": [], "asks": []}, coalesced_count=50)
    (d,) = conn.take()
    assert (d["s"], d["p"]["coalesced"], d["p"]["coalesced_count"]) == (2, True, 50)


def test_binary_coalesced_and_replay_delta_flags() -> None:
    conn = Conn(_book_source())
    _, sub = conn.sub("book.BTCUSDT.50", replay_session_id=RS)
    conn.take()
    part = Frame(BOOK_DELTA, records=((0, 1, 1),))
    conn.emitter.delta(sub, part=part, coalesced_count=3, ts_ms=1_700_000_000_000)
    (d,) = conn.take()
    flags = decode_b64(d["p"]).flags
    assert flags & FLAG_REPLAY and flags & 0b0010
    assert (d["ts"], d["rs"]) == (1_700_000_000_000, RS) and d["wt"] == 1_789_132_262_000


def test_paused_subscription_emits_nothing_and_does_not_advance() -> None:
    conn = Conn(_book_source())
    _, sub = conn.sub("book.BTCUSDT.50")
    sub.effective["paused"] = True
    assert conn.emitter.delta(sub, {"symbol": "BTCUSDT", "bids": [], "asks": []}) is False
    assert sub.seq == 1


# -- Replay vs live separation (WS-T09) ---------------------------------------------------------


def test_replay_and_live_have_separate_sequence_domains_and_routing() -> None:
    src = _book_source()
    hub = SequencingHub()
    conn = Conn(src)
    hub.register(conn.authz, conn.emitter)
    _, live = conn.sub("book.BTCUSDT.50")
    _, replay = conn.sub("book.BTCUSDT.50", replay_session_id=RS)
    conn.take()
    body = {"symbol": "BTCUSDT", "bids": [], "asks": []}
    for _ in range(3):
        hub.publish(live.ch, body)
    hub.publish(live.ch, body, replay_session_id=RS)
    out = conn.take()
    assert [("rs" in f, f["s"]) for f in out] == [(False, 2), (False, 3), (False, 4), (True, 2)]
    assert (live.seq, replay.seq) == (4, 2)
    other = str(uuid.UUID(int=7))
    assert hub.publish(live.ch, body, replay_session_id=other) == 0


# -- Property: sequence monotonicity per subscription ------------------------------------------

_OPS = st.lists(
    st.tuples(
        st.sampled_from(["d", "resync", "desync", "coalesced"]),
        st.sampled_from(["book.BTCUSDT.50", "book.ETHUSDT.50", "trades.BTCUSDT"]),
    ),
    max_size=60,
)


@settings(max_examples=60, deadline=None, derandomize=True)
@given(ops=_OPS)
def test_property_sequence_contiguous_per_subscription(ops: list[tuple[str, str]]) -> None:
    src = _book_source()
    eth = Book("ETHUSDT")
    eth.apply([["1.0", "1"]], [["2.0", "1"]])
    src.books["ETHUSDT"] = eth
    src.bodies["trades"] = SnapshotBody({"symbol": "BTCUSDT", "trades": []})
    hub = SequencingHub()
    conn = Conn(src)
    hub.register(conn.authz, conn.emitter)
    subs = {ch: conn.sub(ch)[1] for ch in ("book.BTCUSDT.50", "book.ETHUSDT.50", "trades.BTCUSDT")}
    for i, (op, ch) in enumerate(ops):
        conn.clock.now = float(i * 20)  # stays under the resync rate limit
        sym = ch.split(".")[1]
        body: dict[str, Any] = (
            {"symbol": sym, "trades": []}
            if ch.startswith("trades")
            else {"symbol": sym, "bids": [], "asks": []}
        )
        if op == "d":
            hub.publish(ch, body)
        elif op == "coalesced":
            hub.publish(ch, body, coalesced_count=7)
        elif op == "resync":
            conn.emitter.client_resync(
                conn.authz, {"t": "resync", "ch": ch, "p": {"reason": "manual"}}
            )
        else:
            hub.upstream_desync(sym)
    last: dict[str, int] = {}
    for f in conn.take():
        if f["t"] not in {"snap", "d"}:
            continue
        if f["t"] == "snap":
            prev = last.get(f["ch"])
            assert prev is None or f["meta"]["previous_seq"] == prev
        else:
            assert f["s"] == last[f["ch"]] + 1
        assert f["ch"] not in last or f["s"] == last[f["ch"]] + 1
        last[f["ch"]] = f["s"]
    assert last == {ch: s.seq for ch, s in subs.items()}


# -- Scenario: account-less private topics reach their own scope (#2398) ----------------------

_OTHER_USER = uuid.UUID(int=0x200)
_ALERT = {
    "deliveries": [
        {
            "id": 1,
            "alert_id": "00000000-0000-4000-8000-0000000000aa",
            "channel": "in_app",
            "status": "queued",
            "message": "m",
            "fired_at_ms": 1,
        }
    ]
}
_RECORDER = {"overall": "healthy", "symbols": []}


def _scoped(hub: SequencingHub, ch: str, user: uuid.UUID = USER) -> Conn:
    """A connection of `user`, subscribed to the account-less `ch`, with its snapshot taken."""
    src = Source()
    src.bodies["alerts"] = SnapshotBody({"deliveries": []})
    src.bodies["recorder"] = SnapshotBody({"overall": "healthy", "symbols": []})
    conn = Conn(src)
    perms = PERMS | {Permission.ALERTS_READ, Permission.RECORDING_READ}
    conn.authz.principal = replace(conn.authz.principal, user_id=user, permissions=perms)
    hub.register(conn.authz, conn.emitter)
    conn.sub(ch)
    assert [f["t"] for f in conn.take()] == ["snap"]
    return conn


def test_alerts_delta_reaches_only_the_owning_users_connections() -> None:
    hub = SequencingHub()
    mine, theirs = _scoped(hub, "alerts"), _scoped(hub, "alerts", _OTHER_USER)
    assert hub.publish("alerts", _ALERT, user=USER) == 1
    (delta,) = mine.take()
    assert (delta["t"], delta["s"], delta["p"]["deliveries"]) == ("d", 2, _ALERT["deliveries"])
    assert theirs.take() == []  # another user's alert never crosses over


def test_alerts_delta_naming_no_owner_reaches_nobody() -> None:
    hub = SequencingHub()
    conn = _scoped(hub, "alerts")
    assert hub.publish("alerts", _ALERT) == 0  # fail closed
    assert hub.publish("alerts", _ALERT, account=ACC_A) == 0  # an account is not an owner
    assert conn.take() == []


def test_recorder_delta_reaches_every_subscription() -> None:
    hub = SequencingHub()
    first, second = _scoped(hub, "recorder"), _scoped(hub, "recorder", _OTHER_USER)
    assert hub.publish("recorder", _RECORDER) == 2
    assert [f["t"] for f in first.take() + second.take()] == ["d", "d"]


def test_permission_loss_revokes_account_less_subscriptions_and_their_deltas() -> None:
    """§9.5 for subscriptions that hold no accounts: re-evaluation revokes them."""
    hub = SequencingHub()
    alerts, recorder = _scoped(hub, "alerts"), _scoped(hub, "recorder")
    for conn in (alerts, recorder):
        new = replace(conn.authz.principal, permissions=PERMS)
        frames = conn.authz.apply_snapshot(VersionedSnapshot(new, conn.authz.version + 1), 9)
        assert frames is not None
        assert [(f["t"], f["p"]["reason"]) for f in frames[1:]] == [
            ("revoked", "permission_revoked")
        ]
    assert hub.publish("alerts", _ALERT, user=USER) == 0
    assert hub.publish("recorder", _RECORDER) == 0


def test_private_delta_needs_the_permission_even_before_reevaluation() -> None:
    """#2521 review: a principal swapped in without its subscriptions being removed (a
    re-evaluation that stopped part-way) gets no private delta for a permission it lacks."""
    hub = SequencingHub()
    alerts, recorder = _scoped(hub, "alerts"), _scoped(hub, "recorder")
    positions = Conn(Source(), ACC_A)
    hub.register(positions.authz, positions.emitter)
    _, sub = positions.authz.admit(
        {"ch": "positions", "opts": {"exchange_account_ids": [str(ACC_A)]}}
    )
    assert sub is not None
    sub.snapshot_pending = False
    for conn in (alerts, recorder, positions):
        principal = conn.authz.principal
        lost = {Permission.ALERTS_READ, Permission.RECORDING_READ, Permission.POSITIONS_READ}
        conn.authz.principal = replace(principal, permissions=principal.permissions - lost)
    assert hub.publish("alerts", _ALERT, user=USER) == 0
    assert hub.publish("recorder", _RECORDER) == 0
    assert hub.publish("positions", {"positions": []}, account=ACC_A) == 0


def test_account_scoped_delta_is_not_widened_by_a_user() -> None:
    hub = SequencingHub()
    conn = Conn(Source(), ACC_A)
    hub.register(conn.authz, conn.emitter)
    _, sub = conn.authz.admit({"ch": "positions", "opts": {"exchange_account_ids": [str(ACC_A)]}})
    assert sub is not None
    sub.snapshot_pending = False
    assert hub.publish("positions", {"positions": []}, user=USER) == 0  # no account: nobody
    assert hub.publish("positions", {"positions": []}, account=ACC_B, user=USER) == 0
    assert hub.publish("positions", {"positions": []}, account=ACC_A) == 1
