"""SR-193 (#2293): `resync`, re-snapshotting `ctl` and `sub` starts draw on one rebuild budget per
connection (`23-ws-protocol.md` §5.2, §5.4, §7.5, §7.7), and on its user's, which all of the
user's connections share (#3476); the limits are §7.5's numbers."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.ws.permissions import (
    ConnectionRegistry,
    SubscriptionServices,
    VersionedSnapshot,
    handle_ctl,
    handle_sub,
)
from candleviewer.ws.sequencing import SequencingHub
from candleviewer.ws.upstream import UpstreamRefs
from tests.unit.ws._seq_support import ACC_A, ACC_B, USER, Clock, Conn
from tests.unit.ws.test_revocation_fanout import _DroppedSeries
from tests.unit.ws.test_sequencing import RS, _book_source, _CappedBars, _hold, _resync

TOPIC, CONNECTION, WINDOW, USER_LIMIT = 5, 400, 60.0, 1600  # 23 §7.5, §16.2
BOOK, HEAT, BARS = "book.BTCUSDT.50", "heatmap.BTCUSDT", "bars.BTCUSDT.time.5"
NOT_TAKEN = "Rebuild budget spent ({} a minute per {}); no snapshot was taken."


def _refused(path: str, scope: str) -> float:
    """One refusal series (bound at import: `test_rebuild_budget.py`)."""
    labels = {"kind": path, "cause": scope}
    return REGISTRY.get_sample_value("cv_ws_rebuild_refused_total", labels) or 0.0


def _ctl(conn: Conn, body: dict[str, Any], ch: str = HEAT) -> dict[str, Any]:
    reply = handle_ctl(conn.authz, {"t": "ctl", "id": "c-7", "ch": ch, "p": body}, 1)
    conn.push(reply)  # schema-checked like every frame the connection sends
    return reply


def _resume(conn: Conn, ch: str = BOOK) -> dict[str, Any]:
    """A pause, then a resume: the resume re-snapshots (§5.4, #2517), the pause does not."""
    _ctl(conn, {"paused": True}, ch)
    return _ctl(conn, {"paused": False}, ch)


async def _asub(conn: Conn, *topics: Any) -> list[dict[str, Any]]:
    """One `sub` frame through `handle_sub`; its results (the `sub_ok` is schema-checked)."""
    sent: list[dict[str, Any]] = []

    async def send(frame: dict[str, Any]) -> None:
        conn.push(frame)
        sent.append(frame)

    entries = [t if isinstance(t, dict) else {"ch": t} for t in topics]
    await handle_sub(conn.authz, {"t": "sub", "p": {"topics": entries}}, send, now_ms=1)
    results: list[dict[str, Any]] = sent[0]["p"]["results"]
    return results


def _sub(conn: Conn, *topics: Any) -> list[dict[str, Any]]:
    return asyncio.run(_asub(conn, *topics))


def test_a_ctl_identity_flip_loop_is_refused_at_the_sixth_and_the_refusal_changes_nothing() -> None:
    src = _book_source()
    src.unavailable.add("BTCUSDT")  # the `initial` snap stays pending: a re-snapshot draws anyway
    conn, drops = Conn(src), list[Any]()
    conn.authz.on_drop = drops.append  # #3193: a re-snapshotting `ctl` drops the old stream
    _, sub = conn.sub(HEAT)
    for body in ({"throttle_ms": 200}, {"paused": False}, {"time_bucket_ms": 500}):
        assert "resnapshot" not in _ctl(conn, body)["p"]  # no re-snapshot: nothing drawn
    for i in range(TOPIC):
        conn.clock.now = float(i)
        assert _ctl(conn, {"time_bucket_ms": (1000, 500)[i % 2]})["p"]["resnapshot"] is True
    kept = (dict(sub.opts), dict(sub.effective), sub.snapshot_pending, sub.pending_reason)
    before = _refused("ctl", "topic")
    conn.clock.now = WINDOW - 1
    with capture_logs() as logs:
        err = _ctl(conn, {"time_bucket_ms": 5000, "throttle_ms": 1000, "paused": True})
        for _ in range(11):  # the line is capped per path: 10, then one `capped`, then none
            _ctl(conn, {"time_bucket_ms": 5000})
        _resync(conn, HEAT)  # another path: its line has its own cap
    lines = [(e["path"], e.get("capped")) for e in logs if e["event"] == "ws resync rate limited"]
    assert lines == [("ctl", None)] * 10 + [("ctl", True), ("resync", None)]
    told = "Rebuild budget spent (5 a minute per topic); nothing was changed."
    assert (err["t"], err["id"], err["ch"]) == ("err", "c-7", HEAT)
    assert (err["p"]["code"], err["p"]["message"]) == ("resync_rate_limited", told)
    assert (dict(sub.opts), dict(sub.effective), sub.snapshot_pending, sub.pending_reason) == kept
    assert (_refused("ctl", "topic"), len(drops)) == (before + 12, TOPIC)  # refusals drop none
    assert conn.authz.find(HEAT) is sub and "resnapshot" not in _ctl(conn, {"throttle_ms": 9})["p"]
    conn.clock.now = WINDOW  # the first flip is a full window old
    assert _ctl(conn, {"time_bucket_ms": 5000})["p"]["resnapshot"] is True


@pytest.mark.parametrize("held", [False, True], ids=["settled", "held-for-backpressure"])
@pytest.mark.parametrize("resumes", [3, 1])
def test_resync_and_a_resuming_ctl_draw_on_one_topic_budget(resumes: int, held: bool) -> None:
    conn = Conn(_book_source())
    _, sub = conn.sub(BOOK)
    conn.take()
    if held:
        _hold(sub)  # the ladder alone sends that snap, yet each request still draws (§7.7)
    for i in range(resumes):
        conn.clock.now = float(i)
        assert _resume(conn)["p"]["resnapshot"] is True
        conn.emitter.flush_pending([sub])  # the gateway's flush after `ctl_ok`
    for _ in range(TOPIC - resumes):
        _resync(conn, BOOK)
    snaps = [f["meta"]["reason"] for f in conn.take() if f["t"] == "snap"]
    own = ["client_resync"] * (TOPIC - resumes)
    assert snaps == ([] if held else ["reconfigure"] * resumes + own)
    before = _refused("resync", "topic")
    _resync(conn, BOOK)  # refused, yet a `ctl` is among the topic's five: not its own loop
    (err,) = conn.take()
    assert (err["t"], err["id"], err["p"]["code"]) == ("err", "c-90", "resync_rate_limited")
    assert err["p"]["message"] == NOT_TAKEN.format(5, "topic")
    assert conn.authz.find(BOOK) is sub and _refused("resync", "topic") == before + 1


def test_a_topic_and_its_replay_session_draw_on_separate_shares() -> None:
    conn, other = Conn(_book_source()), "book.BTCUSDT.050"
    conn.sub(BOOK)
    conn.sub(other)
    conn.sub(BOOK, replay_session_id=RS)
    for _ in range(2):
        _resume(conn, other)
    for ch in (BOOK, other, other, BOOK):
        _resync(conn, ch)  # the last is the topic's sixth draw, three of them resyncs: refused
    answers = [f["t"] for f in conn.take() if f["t"] in ("snap", "err")]
    assert answers[-4:] == ["snap", "snap", "snap", "err"]
    replay = {"t": "resync", "ch": BOOK, "rs": RS, "p": {"reason": "manual"}}  # §7.5 (#3218)
    for _ in range(TOPIC):  # named by its `rs` while the live topic's five are spent
        conn.emitter.client_resync(conn.authz, replay)
    assert [(f["t"], f.get("rs")) for f in conn.take()] == [("snap", RS)] * TOPIC


def test_a_replay_stream_s_ctl_draws_on_its_share_and_a_refused_resync_names_it() -> None:
    """W10, §7.5 (#3218): a `ctl` naming `rs` draws on that replay stream's share. Its refused
    `resync`, with one of the five draws a `ctl`'s, is no loop: the stream continues, and the
    `err` carries its `rs`. The live stream's share is untouched."""
    conn = Conn(_book_source())
    conn.sub(BOOK)
    conn.sub(BOOK, replay_session_id=RS)
    for paused in (True, False):  # the resume draws (§5.4, #2517), the pause does not
        frame = {"t": "ctl", "id": "c-8", "ch": BOOK, "rs": RS, "p": {"paused": paused}}
        conn.push(handle_ctl(conn.authz, frame, 1))
    replay = {"t": "resync", "id": "c-9", "ch": BOOK, "rs": RS, "p": {"reason": "manual"}}
    for _ in range(TOPIC):
        conn.emitter.client_resync(conn.authz, replay)
    _resync(conn, BOOK)
    answers = [(f["t"], f.get("rs")) for f in conn.take() if f["t"] in ("snap", "err")]
    tail = [("snap", RS)] * (TOPIC - 1) + [("err", RS), ("snap", None)]
    assert (answers[-len(tail) :], conn.authz.find(BOOK, RS) is not None) == (tail, True)


def test_the_server_s_own_snapshots_never_draw() -> None:
    hub, conn = SequencingHub(), Conn(_book_source())
    hub.register(conn.authz, conn.emitter)
    _, live = conn.sub(BOOK)
    conn.sub(BOOK, replay_session_id=RS)
    for _ in range(TOPIC + 1):  # more of each than the topic's limit
        hub.upstream_desync("BTCUSDT")
        hub.upstream_reconnect("BTCUSDT")
        hub.instrument_revision("BTCUSDT")
        hub.resnapshot(lambda s: True, "generation_swap")
        hub.replay_seek(RS)
        _hold(live)
        assert conn.emitter.snapshot(live, "backpressure")  # the overflow ladder's `drain`
    rounds = 1 + 1 + 2 + 2 + 1 + 1  # live; live; both; both; replay; live
    assert len([f for f in conn.take() if f["t"] == "snap"]) == 2 + (TOPIC + 1) * rounds
    for _ in range(TOPIC):
        _resync(conn, BOOK)
    assert [f["t"] for f in conn.take()] == ["snap"] * TOPIC  # all five are left


_DEPTHS = (1, 50, 200, 500)  # with `trades`, five topics on each of 40 symbols: the 200 cap
_HELD = [f"book.S{i % 40:02d}USDT.{_DEPTHS[i // 40]}" for i in range(160)]
_HELD += [f"trades.S{i:02d}USDT" for i in range(40)]
_FOREIGN = {"ch": "positions", "opts": {"exchange_account_ids": [str(ACC_B)]}}


@pytest.mark.parametrize(
    ("held", "entry", "code"),
    [
        (40, "trades.S99USDT", "subscription_limit"),  # a 41st symbol
        (200, "ticker.S00USDT", "subscription_limit"),  # a 201st subscription
        (0, _FOREIGN, "account_scope_denied"),
    ],
    ids=["symbol-cap", "subscription-cap", "foreign-account"],
)
def test_the_caps_and_scope_refuse_before_a_spent_budget(held: int, entry: Any, code: str) -> None:
    """§5.2: refusals decided from the entry come first and draw nothing; each says if retryable."""
    authz = Conn(_book_source()).authz
    for ch in _HELD[:held]:
        assert authz.admit(ch)[1] is not None
    for i in range(CONNECTION):  # the connection's limit spent
        authz.rebuilds.take((f"x.S{i:03d}", None), "ctl")
    before, error = _refused("sub", "connection"), authz.admit(entry)[0]["error"]
    assert (error["code"], error["retryable"]) == (code, code == "subscription_limit")
    assert _refused("sub", "connection") == before


def test_unsub_and_sub_churn_of_a_topic_is_refused_at_its_sixth_restart() -> None:
    conn = Conn(_book_source())
    assert [r["ok"] for r in _sub(conn, BOOK)] == [True]  # a first `sub`: the connection's only
    for _ in range(TOPIC):
        conn.authz.unsubscribe(BOOK)
        assert [r["ok"] for r in _sub(conn, BOOK)] == [True]
    conn.authz.unsubscribe(BOOK)
    with capture_logs() as logs:
        refused, other = _sub(conn, BOOK, "trades.ETHUSDT")
    assert (refused["ok"], other["ok"], conn.authz.find(BOOK)) == (False, True, None)
    err, (line,) = refused["error"], [e for e in logs if e["event"] == "ws resync rate limited"]
    assert (err["code"], err["retryable"], line["scope"]) == ("resync_rate_limited", True, "topic")
    assert err["message"] == "Rebuild budget spent (5 a minute per topic); not subscribed."
    conn.clock.now = WINDOW  # its five starts leave the window
    assert [r["ok"] for r in _sub(conn, BOOK)] == [True]


def test_a_spent_connection_refuses_new_topics_resyncs_and_resumes_and_never_revokes() -> None:
    conn, sink = Conn(_book_source()), AsyncMock()
    conn.authz.services.audit = sink
    _sub(conn, BOOK)
    for i in range(CONNECTION - 1):  # with that first `sub`, the connection's 400
        assert conn.authz.rebuilds.take((f"trades.S{i:03d}USDT", None), "ctl") is None
    before = _refused("sub", "connection")
    positions = {"ch": "positions", "opts": {"exchange_account_ids": [str(ACC_A)]}}
    with capture_logs() as logs:
        results = _sub(conn, "trades.ETHUSDT", BOOK, positions, "nope.BTCUSDT")
    codes = [r["error"]["code"] for r in results]
    spent = "resync_rate_limited"
    assert codes == [spent, "duplicate_subscription", spent, "unknown_topic"]
    told = "Rebuild budget spent (400 a minute per connection); not subscribed."
    assert results[0]["error"]["message"] == told and conn.authz.find("trades.ETHUSDT") is None
    assert _refused("sub", "connection") == before + 2  # one per refused entry
    line = {"connection_id": conn.authz.connection_id, "ch": "trades.ETHUSDT", "count": 2}
    assert [e for e in logs if e["event"] == "ws resync rate limited"] == [
        {"event": "ws resync rate limited", "log_level": "warning", **line, "path": "sub"}
        | {"scope": "connection", "limit": CONNECTION, "window_s": WINDOW}
    ]
    # A private topic's refusal, whatever its code, is in the frame's one record (§5.2 Audit).
    (row,) = sink.emit.await_args_list
    denied = (row.args[0], row.kwargs["object_id"], row.kwargs["reason"])
    assert denied == ("ws.subscribe.denied", "positions", "resync_rate_limited")
    paths_before = [_refused(p, "connection") for p in ("resync", "ctl")]
    with capture_logs() as logs:  # the other two paths: refused at the limit, never revoked
        _resync(conn, BOOK)
        messages = [conn.take()[-1]["p"]["message"], _resume(conn)["p"]["message"]]
    spent_400 = "Rebuild budget spent (400 a minute per connection);"
    assert messages == [f"{spent_400} no snapshot was taken.", f"{spent_400} nothing was changed."]
    scopes = {e["path"]: e["scope"] for e in logs if e["event"] == "ws resync rate limited"}
    assert scopes == {"resync": "connection", "ctl": "connection"} and conn.authz.find(BOOK)
    assert [_refused(p, "connection") for p in ("resync", "ctl")] == [n + 1 for n in paths_before]


def test_an_entry_refused_at_the_upstream_step_draws_nothing_and_releases_nothing() -> None:
    conn, bars = Conn(_book_source()), "bars.BTCUSDT.time.5"
    conn.authz.services.bars = _CappedBars()  # its lease is refused: `subscription_limit`
    for i in range(CONNECTION - 2):  # five on the bars topic, the rest elsewhere: room for two
        key = (bars, None) if i < TOPIC else (f"trades.S{i:03d}USDT", None)
        assert conn.authz.rebuilds.take(key, "ctl") is None
    capped, book = _sub(conn, bars, BOOK)
    assert (capped["error"]["code"], book["ok"]) == ("subscription_limit", True)
    conn.authz.services.bars = None  # no lease to take now
    assert [r["ok"] for r in _sub(conn, bars)] == [True]  # still a first `sub`, and with room


def _one_user(n: int, upstream: UpstreamRefs | None = None, limit: int | None = None) -> list[Conn]:
    """#3476: `n` connections of one user, on one process's services and the router's clock."""
    return _connections([USER] * n, upstream, limit)


def _connections(
    users: list[uuid.UUID], upstream: UpstreamRefs | None = None, limit: int | None = None
) -> list[Conn]:
    """A connection of each of `users`, on one process's services and the router's clock."""
    src, clock = _book_source(), Clock()
    refs = UpstreamRefs() if upstream is None else upstream  # an empty one is falsy
    services = SubscriptionServices(upstream=refs, snapshots=src)
    if limit is not None:  # every user's, before any connection reads it
        services.user_rebuilds.limit = limit
    return [Conn(src, clock=clock, services=services, user=user) for user in users]


class _Rows:
    """An audit sink that keeps each row with the frame types `out` held when it came; `block`: the
    action whose write waits until it is cancelled."""

    def __init__(self, out: list[dict[str, Any]] | None = None, block: str | None = None) -> None:
        self.rows: list[tuple[str, dict[str, Any], list[str]]] = []
        self.out, self.block, self.entered = [] if out is None else out, block, asyncio.Event()

    async def emit(self, action: str, **row: Any) -> None:
        if action == self.block:
            self.entered.set()
            await asyncio.Event().wait()
        self.rows.append((action, row, [f["t"] for f in self.out]))


def _spend(conns: list[Conn], draws: int) -> None:
    """`draws` of the user's limit, on `conns` in turn, each up to its connection's limit."""
    for conn in conns:
        for i in range(min(draws, CONNECTION)):
            assert conn.authz.rebuilds.take((f"trades.S{i:03d}USDT", None), "ctl") is None
        draws -= min(draws, CONNECTION)


class _ParkedSink:
    """An upstream whose first `open` waits for `go`: a `sub` entry parked mid-subscribe."""

    def __init__(self) -> None:
        self.entered, self.go = asyncio.Event(), asyncio.Event()

    async def open(self, key: Any) -> None:
        if not self.entered.is_set():  # only the first: any later entry goes straight through
            self.entered.set()
            await self.go.wait()

    async def drop(self, key: Any) -> None:
        pass


async def _park(conn: Conn, ch: str, sink: _ParkedSink) -> asyncio.Task[list[dict[str, Any]]]:
    """`conn`'s `sub` of `ch`, once it waits in its upstream (bounded: 5 s)."""
    task = asyncio.create_task(_asub(conn, ch))
    async with asyncio.timeout(5):
        await sink.entered.wait()
    return task


def test_a_spent_user_refuses_its_other_connections_and_outlives_them() -> None:
    """#3476 (§7.5): four connections spend their user's 1 600 (with a fifth's `sub`); that fifth's
    `bars.*` entry, `resync` (never revoked) and resuming `ctl` are refused for the user. The window
    outlives every connection: one opened after they all close is refused too, until it slides."""
    *others, late, newcomer = _one_user(6)
    registry = ConnectionRegistry(AsyncMock(), lambda: 1, late.authz.services)
    for conn in (*others, late):
        registry.register(conn.authz, AsyncMock())
    assert [r["ok"] for r in _sub(late, BOOK)] == [True]
    _spend(others, USER_LIMIT - 1)
    before = [_refused(path, "user") for path in ("sub", "resync", "ctl")]
    with capture_logs() as logs:
        (refused,) = _sub(late, BARS)
        late.take()
        _resync(late, BOOK)
        frames, resumed = late.take(), _resume(late)
    told, (err,) = "Rebuild budget spent (1600 a minute per user);", frames  # no `revoked`
    error = refused["error"]
    assert (error["code"], error["retryable"]) == ("resync_rate_limited", True)
    assert error["message"] == f"{told} not subscribed."
    assert err["p"]["message"] == f"{told} no snapshot was taken."
    assert resumed["p"]["message"] == f"{told} nothing was changed." and late.authz.find(BOOK)
    spent = [e for e in logs if e["event"] == "ws resync rate limited"]
    assert [(e["path"], e["scope"], e["limit"]) for e in spent] == [
        (path, "user", USER_LIMIT) for path in ("sub", "resync", "ctl")
    ]
    assert [_refused(path, "user") for path in ("sub", "resync", "ctl")] == [n + 1 for n in before]
    for conn in (*others, late):
        registry.unregister(conn.authz)
    registry.register(newcomer.authz, AsyncMock())
    assert [r["ok"] for r in _sub(newcomer, BOOK)] == [False]
    newcomer.clock.now = WINDOW  # every draw was at t = 0: they leave the window
    assert [r["ok"] for r in _sub(newcomer, BOOK, BARS)] == [True, True]
    _resync(newcomer, BOOK)
    assert [f["t"] for f in newcomer.take()][-1] == "snap"
    assert _resume(newcomer)["p"]["resnapshot"] is True


async def test_an_entry_parked_mid_subscribe_holds_its_user_s_last_draw() -> None:
    """#3476: the user one draw short; A's `sub` entry passes the check and waits in its upstream,
    holding that draw, so B's entry is refused for the user. A's start turns its hold into the
    draw: B is refused again, and the user has drawn exactly its limit."""
    sink = _ParkedSink()
    a, b, *others = _one_user(5, UpstreamRefs(sink))
    _spend([*others, a], USER_LIMIT - 1)  # A keeps room for its own
    parked = await _park(a, "trades.BTCUSDT", sink)
    (refused,) = await _asub(b, "trades.ETHUSDT")
    sink.go.set()
    (started,) = await parked
    (again,) = await _asub(b, "trades.ETHUSDT")
    told = "Rebuild budget spent (1600 a minute per user); not subscribed."
    messages = [r.get("error", {}).get("message") for r in (refused, started, again)]
    assert messages == [told, None, told]
    assert [s.rebuild_held for s in a.authz.by_id.values()] == [False]  # started: holds none
    users = a.authz.services.user_rebuilds
    assert (len(users._stamps[USER]), users._held) == (USER_LIMIT, {})


async def test_an_entry_closed_or_refused_mid_subscribe_gives_its_user_s_draw_back() -> None:
    """#3476: an entry waiting in its upstream when its connection ends, whose lease release then
    raises (#2735), and one refused at the upstream step (as above) let their held draw go first
    in `_drop`: neither started, so the user still has that draw."""
    sink = _ParkedSink()
    a, probe, *others = _one_user(6, UpstreamRefs(sink))
    _spend(others, USER_LIMIT - 1)
    a.authz.services.bars = _DroppedSeries(every=True)  # the lease it takes cannot be released
    parked = await _park(a, BARS, sink)
    (entry,) = a.authz.by_id.values()
    held = entry.rebuild_held
    parked.cancel()  # the connection ends: the gateway cancels its handler mid-`sub` ...
    with contextlib.suppress(asyncio.CancelledError):
        await parked
    a.authz.release_all()  # ... and its teardown lets go of what the entry held
    assert (held, entry.rebuild_held) == (True, False)
    probe.authz.services.bars = _CappedBars()  # its lease is refused: `subscription_limit`
    (capped,) = await _asub(probe, BARS)
    assert capped["error"]["code"] == "subscription_limit"
    takes = [probe.authz.rebuilds.take((ch, None), "ctl") for ch in ("x.1", "x.2")]
    assert takes == [None, "user"]  # the user's last draw was still there


async def test_two_users_each_spend_only_their_own_limit_and_get_their_own_record() -> None:
    """C-12.4, #3476: two users on one process's limiter, 4 each. A is spent, with an entry parked
    holding a draw; B's `sub` entry, `resync` and resuming `ctl` pass while A's are refused, and
    each user's first `user` refusal in the window writes that user's own record."""
    sink, rows, other = _ParkedSink(), _Rows(), uuid.UUID(int=0x200)
    a, parker, b = _connections([USER, USER, other], UpstreamRefs(sink), limit=4)
    a.authz.services.audit = rows
    parked = await _park(parker, "trades.BTCUSDT", sink)  # first: the sink parks one `open`
    for conn in (a, b):
        await _asub(conn, BOOK)
    for _ in range(2):
        _resync(a, BOOK)  # A: three draws and the hold, its limit
    answers = []
    for conn in (a, b):
        conn.take()
        (entry,) = await _asub(conn, HEAT)
        _resync(conn, BOOK)
        answers.append((entry["ok"], conn.take()[-1]["t"], _resume(conn)["t"]))
    assert answers == [(False, "err", "err"), (True, "snap", "ctl_ok")]
    assert [r["ok"] for r in await _asub(b, "trades.ETHUSDT")] == [False]  # B's first refusal
    records = [(action, row["actor_user_id"]) for action, row, _ in rows.rows]
    assert records == [("ws.rebuild.refused", USER), ("ws.rebuild.refused", other)]
    sink.go.set()
    await parked


async def test_an_entry_a_revocation_ends_mid_subscribe_never_draws_on_its_user() -> None:
    """#3476, an exact bound: a revocation that ends an entry waiting in its upstream lets its hold
    go; when the wait ends, the entry is refused (#2896) and draws on neither its connection nor
    its user (§5.2: no refused topic draws)."""
    sink = _ParkedSink()
    (conn,) = _one_user(1, UpstreamRefs(sink))
    parked = await _park(conn, "trades.BTCUSDT", sink)
    reader = PrincipalSnapshot(
        USER, frozenset({"manager"}), frozenset({Permission.ORDERS_READ}), ()
    )
    assert conn.authz.apply_snapshot(VersionedSnapshot(reader, 1), 1)  # revokes the entry
    sink.go.set()
    await parked
    users = conn.authz.services.user_rebuilds
    assert (users._stamps, users._held, len(conn.authz.rebuilds._all)) == ({}, {}, 0)
