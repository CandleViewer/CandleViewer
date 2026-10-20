"""E17-X02 resource limits over the raw client (#415 slice d1; threat model `E17-ws-gateway.md` §7).

Each limit is written out as `23-ws-protocol.md` §3.6 and §16.2 state it, so a constant changed in
the code cannot move the number under test. Each refusal is checked whole (reply, close, metric and
audit row, as §4.3, §5.2 and §10.2 document them) on the fake clock, under both subprotocols:
the 200-subscription, 40-symbol and 16-`bars.*` caps through a socket (WS-D04); the default 8
sockets per user and 20 first `auth`s a minute through `create_app`, each spent over several
sessions of one user because both limits are per user, not per session, and not shared with another
user (AC-15); 300 frames a minute (AC-11); and AC-29 (D4b). No OMS path writes audit yet, so
AC-29's order-class record is `orders.submit`, written by the test through the `AuditWriter` that
takes the flood's denial records: that test measures the writer (real WAL, in-memory store), not an
OMS path or a latency.
"""

from __future__ import annotations

import asyncio
import functools
import json
import uuid
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from pathlib import Path
from typing import Any, NamedTuple

import msgpack
import pytest

from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.audit.query import AuditQueryService
from candleviewer.audit.writer import AuditWriter
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.models import MintedSession
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode
from candleviewer.ws.gateway import GatewayHub, make_ws_router
from candleviewer.ws.lifecycle import CONNECT_RATE_MESSAGE
from tests.contract.ws._harness import WIRE_SUBPROTOCOL, Client, current_offer, current_wire
from tests.contract.ws._support import Clock
from tests.security.auth import _stack
from tests.security.auth._stack import ORIGIN, Grants, Stack, open_stack
from tests.security.ws._raw import SOURCE, RawWorld, authenticated, delta, raw_connect
from tests.unit.audit.audit_fakes import FakeAuditRepository
from tests.unit.auth.auth_fakes import make_user
from tests.unit.ws._seq_support import ACC_A

SUBS, SYMBOLS, BARS = 200, 40, 16
SOCKETS, CONNECTS, FRAMES = 8, 20, 300  # per user; per user a minute; per socket a minute
SESSIONS = 3  # of the one user whose sockets and connects AC-15 counts, taking turns
BUDGET = 20  # `ws.subscribe.denied` records one connection writes in a minute (§4.3)
MINUTE = 60  # seconds
CLOSED, DENIED = "ws.connection.closed", "ws.subscribe.denied"
_INERT = "unused"  # a stored-hash placeholder: no password is checked here


def _reply(world: RawWorld, *results: dict[str, Any]) -> dict[str, Any]:
    return {"t": "sub_ok", "id": "s", "ts": world.clock.wall_ms(), "p": {"results": list(results)}}


def _refusal(ch: str, message: str) -> dict[str, Any]:
    """A topic a cap refuses: `subscription_limit`, retryable (§10.2); the socket stays open."""
    error = {"code": "subscription_limit", "message": message, "retryable": True}
    return {"ch": ch, "ok": False, "error": error}


def _bye(ts: int, reason: str, message: str, **extra: Any) -> dict[str, Any]:
    """The `bye` of a `4429` close (§4.4): code, reason and message, `reconnect: true`."""
    p = {"code": 4429, "reason": reason, "message": message, "reconnect": True, **extra}
    return {"t": "bye", "ts": ts, "p": p}


def _closed(
    user: uuid.UUID, session: uuid.UUID, connection: str, ip: str, reason: str
) -> dict[str, Any]:
    """The `ws.connection.closed` row of an authenticated socket's end (§4.3): `info`, no token."""
    return {
        "action": CLOSED,
        "actor_label": "ws",
        "actor_user_id": user,
        "actor_ip": ip,
        "session_id": str(session),
        "object_kind": "ws_connection",
        "object_id": connection,
        "outcome": AuditOutcome.SUCCESS,
        "severity": Severity.INFO,
        "reason": reason,
    }


def _fill(c: Client, topics: list[str]) -> None:
    for i in range(0, len(topics), 50):  # 50 to a frame, the most one holds
        assert all(r["ok"] for r in c.sub(*topics[i : i + 50])["p"]["results"])


#: cap -> what fills it, the topic that no longer fits, another of its family, the refusal's text
_CAPS: dict[str, tuple[list[str], str, str, str]] = {
    "200-subscriptions": (
        [f"footprint.BTCUSDT.tick.{n}" for n in range(1, SUBS + 1)],
        "trades.BTCUSDT",
        "trades.ETHUSDT",
        "200 subscriptions reached.",
    ),
    "40-symbols": (
        [f"trades.S{n:02d}USDT" for n in range(SYMBOLS)],
        "trades.S40USDT",
        "trades.S41USDT",
        "40 symbols per connection reached.",
    ),
    "16-bars": (
        [f"bars.BTCUSDT.tick.{100 + n}" for n in range(BARS)],
        "bars.BTCUSDT.tick.200",
        "bars.BTCUSDT.tick.201",
        "At most 16 bars subscriptions per connection.",
    ),
}


@pytest.mark.parametrize(("held", "over", "again", "text"), _CAPS.values(), ids=_CAPS.keys())
def test_x02_ws_d04_a_full_cap_refuses_the_next_topic_and_the_socket_keeps_serving(
    world: RawWorld, held: list[str], over: str, again: str, text: str
) -> None:
    world.registry.services.audit = world.audit  # production's wiring: a refusal it audits shows
    refused = delta("cv_ws_subscribe_total", topic=over.split(".")[0], result="subscription_limit")
    with raw_connect(world) as c:
        authenticated(c, world.login("alice"))
        _fill(c, held)
        assert c.sub(over) == _reply(world, _refusal(over, text))
        c.send({"t": "unsub", "id": "u", "p": {"topics": [held[-1]]}})  # one slot frees ...
        c.next_of("unsub_ok")
        assert [r["ok"] for r in c.sub(over)["p"]["results"]] == [True]  # ... and takes one topic
        assert c.sub(again) == _reply(world, _refusal(again, text))  # so the cap held exactly
        c.send({"t": "ping", "id": "p"})
        c.next_of("pong")  # still served
    assert refused() == 2
    assert "bye" not in {f["t"] for f in c.seen}  # nothing closed the socket
    assert world.audit.of(DENIED) == []  # a public topic's refusal is answered and counted only


def test_x02_ws_d04_a_private_topic_refused_at_the_cap_is_one_audited_denial(
    world: RawWorld,
) -> None:
    world.registry.services.audit = world.audit
    login = world.login("alice")
    orders = {"ch": "orders", "opts": {"exchange_account_ids": [str(ACC_A)]}}
    with raw_connect(world) as c:
        authenticated(c, login)
        _fill(c, _CAPS["200-subscriptions"][0])
        assert c.sub(orders) == _reply(world, _refusal("orders", "200 subscriptions reached."))
    assert world.audit.of(DENIED) == [
        {
            "action": DENIED,
            "actor_label": "ws",
            "actor_user_id": login.user_id,
            "object_kind": "ws_topic",
            "object_id": "orders",
            "outcome": AuditOutcome.DENIED,
            "severity": Severity.WARNING,
            "reason": "subscription_limit",
            **world.named_by(login),  # E17-R-16: the row names its socket
        }
    ]


def _user(stack: Stack, name: str) -> uuid.UUID:
    """A user with a confirmed TOTP method, so that the gateway admits its sessions (#2295)."""
    user = uuid.uuid5(uuid.NAMESPACE_OID, name)
    record = make_user(password_hash=_INERT, username=name, email=f"{name}@x.test")
    stack.users.add(record.model_copy(update={"id": user}))
    return user


def _session(stack: Stack, user: uuid.UUID) -> MintedSession:
    """One more live session of `user`, with its own id and token, as another sign-in gives (a
    refresh rotates to a successor with a new id too); the gateway keys both limits on the user,
    so a socket may carry any of them."""
    minted: MintedSession = stack.call(stack.auth.sessions.mint, str(user))
    return minted


def _open(stack: Stack, es: ExitStack, token: str) -> tuple[Client, str]:
    """A socket that said `hello` and sent `auth` (its next frame is the answer), and its id."""
    headers = {"origin": ORIGIN}
    ws = es.enter_context(stack.client.websocket_connect("/ws", current_offer(), headers=headers))
    assert ws.accepted_subprotocol == WIRE_SUBPROTOCOL[current_wire()]
    c = Client(ws, conform=False)
    c.send({"t": "hello", "id": "h", "p": {"client": "raw"}})
    connection_id = str(c.recv()["p"]["connection_id"])
    c.send({"t": "auth", "id": "a", "p": {"access_token": token}})
    return c, connection_id


async def _turn() -> None:
    """One turn of the app loop."""


def _settled(stack: Stack, done: Callable[[], bool]) -> None:
    """Turns of the app loop, bounded, until the handlers' teardown rows have landed."""
    for _ in range(1_000):
        if done():
            return
        stack.call(_turn)
    pytest.fail("the close rows did not land")


class Deployed(NamedTuple):
    stack: Stack
    mono: Clock  # the gateway's monotonic clock: the idle order and the connect window


@pytest.fixture
def deployed(wire: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Deployed]:
    """`create_app` with its default settings and real sessions (E09-X02's stack), under `wire`.
    `create_app` takes no clock, so the stack's `make_ws_router` is wrapped to hand the gateway
    ours."""
    mono = Clock()
    monkeypatch.setattr(_stack, "make_ws_router", functools.partial(make_ws_router, clock=mono))
    with open_stack(monkeypatch, snapshot_loader=Grants().load) as stack:
        yield Deployed(stack, mono)


def _ping_all(opened: list[tuple[Client, str]], *, but: int) -> None:
    """A `ping` to every socket but `opened[but]`, each answered with its `pong`."""
    for n, (c, _) in enumerate(opened):
        if n != but:
            c.send({"t": "ping", "id": "p"})
            c.next_of("pong")


@pytest.mark.parametrize("idle", [1, SOCKETS - 1], ids=["second", "last-of-eight"])
def test_x02_ac_15_the_ninth_socket_of_a_user_closes_the_oldest_idle_one_across_sessions(
    deployed: Deployed, idle: int
) -> None:
    """AC-15, the socket cap: eight sockets of one user, three sessions of it in turn, are all
    heard from again after they open but one. That one is the oldest idle, not the oldest opened.
    The ninth socket, of the third session, closes it: its whole `bye` and 4429, its metric and
    its close row, with its own session. The other eight, the first one among them, are served.
    So is a socket of a second user that opened before them all and was never heard from again:
    the oldest idle of every live socket, yet not counted among the first user's eight."""
    stack, mono = deployed
    hub = stack.state.ws_hub
    assert (hub.max_per_user, GatewayHub().max_per_user) == (SOCKETS, SOCKETS)
    user = _user(stack, "alice")
    sessions = [_session(stack, user) for _ in range(SESSIONS)]
    bob = _session(stack, _user(stack, "bob"))
    wall = int(stack.clock.now.timestamp() * 1000)
    evicted = delta("cv_ws_closes_total", reason="too_many_connections")
    opened: list[tuple[Client, str]] = []
    with ExitStack() as es:
        mono.now = 0.0  # the second user's one socket opens first, and is not heard from again
        other = _open(stack, es, bob.access_token)
        assert other[0].recv()["t"] == "auth_ok"
        for n in range(SOCKETS):  # eight sockets a second apart, the sessions in turn
            mono.now = float(n)
            opened.append(_open(stack, es, sessions[n % SESSIONS].access_token))
            assert opened[n][0].recv()["t"] == "auth_ok"
        mono.now = SOCKETS - 0.5  # every socket but `idle` is heard from again, after all opened
        _ping_all(opened, but=idle)
        mono.now = float(SOCKETS)  # the ninth, of the third session
        opened.append(_open(stack, es, sessions[SOCKETS % SESSIONS].access_token))
        assert opened[SOCKETS][0].recv()["t"] == "auth_ok"
        text = "Connection limit per user exceeded; oldest idle closed."
        assert opened[idle][0].bye_then_close() == (_bye(wall, "too_many_connections", text), 4429)
        _ping_all([*opened, other], but=idle)  # the eight left, and the second user's
    gone = opened[idle][1]
    _settled(stack, lambda: len(stack.audit.of(CLOSED)) == SOCKETS + 2)  # alice's nine, bob's one
    rows = [r for r in stack.audit.of(CLOSED) if r["reason"] == "too_many_connections"]
    assert (evicted(), len(rows)) == (1, 1)  # exactly one socket went, by the metric and the rows
    row = {k: v for k, v in rows[0].items() if k != "request_id"}  # the one field that differs
    session = sessions[idle % SESSIONS].session_id
    assert row == _closed(user, session, gone, "127.0.0.1", "too_many_connections")


def test_x02_ac_15_the_21st_first_auth_of_a_user_in_a_minute_is_refused_across_sessions(
    deployed: Deployed,
) -> None:
    """AC-15, the connect rate: 20 first `auth`s of one user in a minute, three sessions of it in
    turn, are admitted. The 21st, of the session that has made the fewest (6 of the 20), gets the
    whole `bye` and no `auth_ok`. Another user is admitted at that moment, and the first once the
    wait it was advised has passed."""
    stack, mono = deployed
    hub = stack.state.ws_hub
    assert (hub.connect_rate.limit, GatewayHub().connect_rate.limit) == (CONNECTS, CONNECTS)
    user = _user(stack, "alice")
    sessions = [_session(stack, user) for _ in range(SESSIONS)]
    wall = int(stack.clock.now.timestamp() * 1000)
    limited = delta("cv_ws_connect_rate_limited_total")
    closes = delta("cv_ws_closes_total", reason="client_rate_limited")
    admitted: list[str] = []
    for n in range(CONNECTS):  # a second apart, each socket gone before the next: no cap is near
        mono.now = float(n)
        with ExitStack() as es:
            c, connection_id = _open(stack, es, sessions[n % SESSIONS].access_token)
            assert c.recv()["t"] == "auth_ok"
            admitted.append(connection_id)
    mono.now = float(CONNECTS)  # the 21st: the first of the 20, at 0.0, leaves the window at 60.0
    with ExitStack() as es:
        c, refused = _open(stack, es, sessions[CONNECTS % SESSIONS].access_token)  # in turn
        bye = _bye(wall, "client_rate_limited", CONNECT_RATE_MESSAGE, retry_after_ms=40_000)
        assert c.bye_then_close() == (bye, 4429)
        assert [f["t"] for f in c.seen] == ["welcome", "bye"]  # refused at once: no `auth_ok`
    assert (limited(), closes()) == (1, 1)
    with ExitStack() as es:  # another user is not affected by the refusal
        other = _session(stack, _user(stack, "bob"))
        assert _open(stack, es, other.access_token)[0].recv()["t"] == "auth_ok"
    mono.now += 40.0  # the advised wait: the first connect is now a full window old
    with ExitStack() as es:
        assert _open(stack, es, sessions[0].access_token)[0].recv()["t"] == "auth_ok"
    _settled(stack, lambda: len(stack.audit.of(CLOSED)) == CONNECTS + 2)
    ids = [r["object_id"] for r in stack.audit.of(CLOSED)]
    assert refused not in ids  # it never authenticated: it writes no row
    assert set(admitted) <= set(ids)


def test_x02_ac_11_300_frames_a_minute_end_the_socket_4429_and_the_window_slides(
    world: RawWorld,
) -> None:
    """AC-11, the minute leg: 300 frames in a minute (`hello` and `auth` among them) fit, the 301st
    is refused, a stamp leaves the window exactly when it is a full minute old, and the second
    refusal ends the socket."""
    errors = delta("cv_ws_errors_total", code="client_rate_limited")
    closes = delta("cv_ws_closes_total", reason="client_rate_limited")

    def ping(c: Client, at: float, name: str) -> dict[str, Any]:
        world.clock.now = at
        c.send({"t": "ping", "id": name})
        return c.recv()

    def pong(name: str) -> dict[str, Any]:
        ms = world.clock.wall_ms()
        return {"t": "pong", "id": name, "ts": ms, "p": {"server_ms": ms}}

    login = world.login("alice")
    with raw_connect(world) as c:
        authenticated(c, login)  # `hello` and `auth`, both at 0.0: two of the 300
        for n in range(FRAMES - 2):  # ten a second: the per-second limit of 30 is never near
            assert ping(c, (n + 2) / 10, f"p{n}") == pong(f"p{n}")
        title = ERROR_META[ErrorCode.CLIENT_RATE_LIMITED].title
        p = {"code": "client_rate_limited", "message": title, "retryable": True, "close": False}
        assert ping(c, 59.9, "over") == {"t": "err", "id": "over", "p": p}  # 59.9 s old: in
        assert (errors(), closes()) == (1, 0)
        assert ping(c, 60.0, "a") == pong("a")  # a full window old: both 0.0 frames have left
        assert ping(c, 60.0, "b") == pong("b")
        c.send({"t": "ping", "id": "c"})  # the 301st again, and the second strike
        text, ms = "Inbound frame rate exceeded.", world.clock.wall_ms()
        assert c.bye_then_close() == (
            _bye(ms, "client_rate_limited", text, retry_after_ms=1000),
            4429,
        )
    assert (errors(), closes()) == (1, 1)
    connection = c.seen[0]["p"]["connection_id"]  # the `welcome`'s
    row = _closed(login.user_id, login.minted.session_id, connection, SOURCE, "client_rate_limited")
    assert world.audit.of(CLOSED) == [row | {"request_id": None}]


def _near_cap_sub(c: Client) -> dict[str, Any]:
    """A `sub` just under the 256 KiB inbound cap, refused whole before any entry is read: 20 000
    bare names on JSON and, as its arrays hold at most 128 entries, 128 names of 2 009 characters
    on MessagePack. (The model's literal 21 842-name frame is `test_ws_s1.py`'s.)"""
    names = ["positions" + "x" * 2_000] * 128 if c.msgpack else ["positions"] * 20_000
    frame = {"t": "sub", "id": "big", "p": {"topics": names}}
    assert 250_000 < len(msgpack.packb(frame) if c.msgpack else json.dumps(frame)) <= 256 * 1024
    return frame


async def _order_write(writer: AuditWriter, n: int) -> None:
    """An order-class record, as an OMS write-ahead would emit it (no OMS path does yet), through
    the writer's WAL into the store. The 2 s bound is a hang guard, not a latency budget."""
    async with asyncio.timeout(2.0):
        await writer.emit(
            "orders.submit", actor_label="oms", object_kind="order", object_id=f"o{n}"
        )
        await writer.flush(2.0)  # and it is in the store, not only in the WAL


class _Sink:
    """The gateway's `AuditSink` over the writer, as the composition root's lazy emitter is."""

    def __init__(self, writer: AuditWriter) -> None:
        self.writer = writer

    async def emit(self, action: str, **kwargs: Any) -> None:
        await self.writer.emit(action, **kwargs)


def test_x02_ac_29_a_read_only_flood_for_a_minute_leaves_the_order_write_landing(
    world: RawWorld, tmp_path: Path
) -> None:
    """AC-29: a principal with market data only (V) sends, each second of a minute, one frame near
    256 KiB and two of 50 private-family topics. The near-cap frame gets one small `err` and no
    record; the other 120 are denied, 20 of them recorded (one record each, never one per topic)
    and the rest counted. Four `orders.submit` records go through the same `AuditWriter`, two while
    the 20 records are being written and two after: each lands in the store within 2 s.

    Measures: the writer's handling of an order-class record during the flood, through its real
    WAL (fsync'd, in `tmp_path`), with one connection's budget spent. Does not measure: an OMS
    path (none writes audit yet: the record is this test's own); latency under load (the 2 s is a
    hang guard, and each of the four is one call made while a flood frame is in flight, not a
    concurrent load); the per-user bound of eight such connections; the Postgres chain trigger
    (the chain checked is the in-memory repository's: no row lost, doubled or reordered); the
    router's own rows (they go to the rig's sink, so the store holds the 24 rows below and no
    `ws.connection.closed`)."""
    world.perms = frozenset({Permission.MARKETDATA_READ})  # V: every private family is refused
    repo = FakeAuditRepository()
    writer = AuditWriter(repo, str(tmp_path / "wal"), clock=world.utc_now, sleep=repo.retry_sleep)
    world.call(writer.start)
    world.registry.services.audit = _Sink(writer)  # the denial records go through the writer too
    world.registry.services.clock = world.clock  # so the denial budget's minute is the fake one
    login = world.login("viewer")
    private = (["orders", "positions", "executions", "wallet"] * 13)[:50]
    denied = {"code": "forbidden", "message": "Missing permission for this topic."}
    denials = [{"ch": ch, "ok": False, "error": denied | {"retryable": False}} for ch in private]
    too_many = {"code": "too_many_topics", "retryable": True, "close": False, "field": "topics"}
    too_many["message"] = "At most 50 topics in one sub; split the request."
    unaudited = delta("cv_ws_subscribe_denied_unaudited_total")
    refused = delta("cv_ws_errors_total", code="too_many_topics")
    reasons = ("error", "timeout", "cancelled", "abandoned")  # the closed set of SR-186
    failed = [delta("cv_ws_audit_failures_total", reason=r) for r in reasons]
    ordered = (0, 9, 30, 59)  # seconds of an order write: in the burst of records, and after it
    try:
        with raw_connect(world) as c:
            authenticated(c, login)
            big = _near_cap_sub(c)
            for second in range(MINUTE):
                world.clock.now = float(second)
                c.send_raw(big)
                err = c.recv()
                assert err == {"t": "err", "id": "big", "p": too_many}
                assert len(json.dumps(err)) < 400  # one small reply
                for k in range(2):  # three frames a second: 180 a minute, inside the 300
                    c.send_raw({"t": "sub", "id": "s", "p": {"topics": private}})
                    if k == 0 and second in ordered:  # meanwhile, an order-class write
                        world.call(_order_write, writer, second)
                    assert c.recv() == _reply(world, *denials)
            c.send({"t": "ping", "id": "z"})
            c.next_of("pong")  # open still, and never rate-limited
        world.call(writer.flush, 2.0)
        verdict = world.call(AuditQueryService(repo).verify)
    finally:
        world.call(writer.stop, 1.0)
    generated = {"id", "record_id", "prev_hash", "entry_hash", "event_ts"}
    rows = [{k: v for k, v in r.items() if v is not None and k not in generated} for r in repo.rows]
    seen = [[ch, "forbidden"] for ch in private[:10]]  # the record lists the first 10 refusals
    named = world.named_by(login)  # E17-R-16: the record names its socket (the one connection)
    after = {"codes": ["forbidden"], "count": 50, "refusals": seen} | named["after_state"]
    row = {"action": DENIED, "actor_label": "ws", "actor_user_id": str(login.user_id)}
    row |= {"object_kind": "ws_topic", "object_id": "orders", "outcome": "denied"}
    row |= {"severity": "warning", "reason": "forbidden", "session_id": named["session_id"]}
    row |= {"after_state": json.dumps(after, sort_keys=True)}
    order = {"actor_label": "oms", "object_kind": "order", "outcome": "success", "severity": "info"}
    orders = [order | {"action": "orders.submit", "object_id": f"o{s}"} for s in ordered]
    assert [r for r in rows if r["action"] == DENIED] == [row] * BUDGET  # one a frame, 20 a minute
    assert [r for r in rows if r["action"] == "orders.submit"] == orders  # each one landed
    assert len(rows) == BUDGET + len(ordered)  # nothing else: no store growth with the flood
    assert (verdict.verified, verdict.entries_checked) == (True, len(rows))  # the fake's chain
    assert (unaudited(), refused(), writer.refused_total) == (2 * MINUTE - BUDGET, MINUTE, 0)
    assert [f() for f in failed] == [0, 0, 0, 0]  # no audit row failed, timed out or was dropped
