"""E17-X02 AC-13 and AC-14 (#415, threat model `E17-ws-gateway.md` §5, §7): a withdrawn grant's
queued frames are dropped before `permission_change` (23-ws-protocol.md §9.5). M1 holds A and B and
the owner withdraws B (the grant store, then the registry's notice) while B's snapshot and deltas
are queued behind a parked writer, while a `sub` awaits its upstream, during the first `auth` and
during an in-place re-`auth`: with the backpressure flag off (today's default) and on, under both
subprotocols. Each test asserts what the AC-13 and AC-14 rows of the threat model's §7 list: the
announcing frames in order, each `revoked` stamped at the withdrawal on the fake clock
(`0 <= ts - at_ms <= 1000`), and no `snap` or `d` naming B from the withdrawal on.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from functools import partial
from typing import Any

import pytest

from candleviewer.ws import gateway
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.upstream import UpstreamRefs
from tests.contract.ws._harness import Client
from tests.security.ws._raw import (
    RawWorld,
    answers,
    authenticated,
    delta,
    naming,
    publish,
    raw_connect,
    topic,
)
from tests.unit.ws._seq_support import ACC_A, ACC_B

ACC_C = uuid.UUID(int=0xC)
BARRIER = "ticker.BTCUSDT"  # the topic `flushed` reads its barrier through
_DATA = {"snap", "d"}
_FLAGS = {"flag-off": None, "flag-on": BackpressureConfig()}
_FLAG = pytest.mark.parametrize("flag", _FLAGS.values(), ids=_FLAGS)


class Held:
    """Parks the gateway's writer in the next frame it sends: what is queued meanwhile waits."""

    def __init__(self, world: RawWorld, monkeypatch: pytest.MonkeyPatch) -> None:
        self.world, self.parked = world, threading.Event()
        self._go, self._armed = asyncio.Event(), False
        send = gateway._Connection.send_payload

        async def held(conn: Any, payload: str | bytes) -> None:
            if self._armed:
                self._armed = False
                self.parked.set()
                await self._go.wait()
            await send(conn, payload)

        monkeypatch.setattr(gateway._Connection, "send_payload", held)

    def hold(self, c: Client, frame: dict[str, Any]) -> None:
        """Send `frame`; the writer parks in the first frame it sends after this, the `sub_ok` of a
        `sub`. Whatever is pushed behind that frame (the snapshot, then deltas), in however many
        turns of the loop, is queued, not sent. One hold per `Held`: after a `release` the event the
        writer waits on stays set, so a second would not park."""
        assert not self.parked.is_set(), "a Held holds once"
        self._armed = True
        c.send(frame)
        assert self.parked.wait(5.0)

    def release(self) -> None:
        self.world.call(self._go.set)


def flushed(c: Client) -> None:
    """Returns once every frame queued for `c` so far has been received, read through the snapshot
    of a topic it subscribes to now: the normal lane is FIFO and the new snapshot is its last frame
    (the priority lane's `pong` would overtake a normal-lane frame, with the flag on)."""
    c.send({"t": "sub", "id": "barrier", "p": {"topics": [{"ch": BARRIER}]}})
    while (frame := c.recv())["t"] != "snap" or frame["ch"] != BARRIER:
        pass
    c.send({"t": "unsub", "id": "barrier", "p": {"topics": [BARRIER]}})
    c.next_of("unsub_ok")


def since(c: Client, mark: int) -> list[dict[str, Any]]:
    """What `c` received from `mark` on, its own barrier and the `ping` and `pong` frames aside."""
    skip = {"ping", "pong"}
    return [
        f
        for f in c.seen[mark:]
        if f["t"] not in skip and f.get("id") != "barrier" and f.get("ch") != BARRIER
    ]


def _announced(got: list[dict[str, Any]], at_ms: int) -> None:
    """`got` is everything received from the withdrawal on. It holds a `permission_change` (A alone)
    and `revoked` frames; each `revoked` is stamped at the withdrawal on the fake clock, `0 <= ts -
    at_ms <= 1000`; and no `snap` or `d` anywhere in `got` names B, so none follows the first
    `permission_change`."""
    kinds = [f["t"] for f in got]
    assert "permission_change" in kinds
    assert got[kinds.index("permission_change")]["p"]["account_scope"] == [str(ACC_A)]
    revoked = [f for f in got if f["t"] == "revoked"]
    assert revoked and all(0 <= f["ts"] - at_ms <= 1000 for f in revoked)
    assert naming([f for f in got if f["t"] in _DATA], ACC_B) == []


@_FLAG
@pytest.mark.parametrize("family", ["positions", "orders"])
@pytest.mark.parametrize("named", [(ACC_B,), (ACC_A, ACC_B)], ids=["ended", "narrowed"])
def test_x02_ac_13_a_withdrawn_grants_queued_frames_are_dropped_before_permission_change(
    world: RawWorld,
    flag: BackpressureConfig | None,
    family: str,
    named: tuple[uuid.UUID, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m1, held, kept = world.login("m1", ACC_A, ACC_B), Held(world, monkeypatch), ACC_A in named
    revoked = delta("cv_ws_revoked_total", reason="account_scope_changed")
    withdrawn = delta("cv_ws_overflow_total", reason="withdrawn")  # §9.5: per queued frame purged
    # B's snapshot and two deltas are in the queue at the withdrawal; with the flag on, a throttled
    # family's second delta waits in its pacing window instead, which the change discards uncounted
    queued = 2 if flag and family == "positions" else 3
    with raw_connect(world) as c:
        authenticated(c, m1)
        held.hold(c, {"t": "sub", "id": "s", "p": {"topics": [topic(family, *named)]}})
        assert [publish(world, family, ACC_B) for _ in range(2)] == [1, 1]  # behind the snapshot
        mark, at_ms = len(c.seen), world.clock.wall_ms()
        world.call(partial(world.amended, m1, drop=(ACC_B,)))
        assert withdrawn() == queued  # the frames were queued, and the change purged each of them
        assert [publish(world, family, a) for a in (ACC_B, ACC_A)] == [0, kept]  # B routes nowhere
        held.release()
        flushed(c)
        world.clock.now += 5.0  # a window the old scope left open would close now
        c.send({"t": "ping", "id": "tick"})  # the writer's turn that closes it precedes this pong
        flushed(c)
    got = since(c, mark)
    _announced(got, at_ms)
    kinds = [f["t"] for f in got]
    ahead = got[: kinds.index("permission_change")]  # what is sent before the announcement
    sent = [f for f in ahead if f["t"] in _DATA and f.get("ch") == family]
    assert len(sent) == 0  # of the queued snapshot and two deltas of B, none is sent
    follow = ["snap", "d"] if kept else []  # A's reconfigure snapshot, then its later delta
    assert kinds == ["sub_ok", "permission_change", "revoked", *follow]
    assert got[0]["p"]["results"][0]["ok"] is True  # B was granted: its data was in flight
    end = got[2]
    assert (end["ch"], end["p"]["reason"], end["p"]["removed_accounts"]) == (
        family,
        "account_scope_changed",
        [str(ACC_B)],
    )
    assert end["p"]["resubscribe_allowed"] is kept and revoked() == 1
    if kept:  # the narrowed topic goes on for A, from a new baseline built under the new scope
        snap, later = got[3:]
        assert snap["meta"]["reason"] == "reconfigure"
        assert naming([snap, later], ACC_A) == [snap, later]
    (row,) = world.audit.of("ws.subscription.revoked")
    assert (row["object_id"], row["reason"], row["actor_user_id"]) == (
        family,
        "account_scope_changed",
        m1.user_id,
    )
    assert row["after_state"]["removed_accounts"] == [str(ACC_B)]


class _Gated:
    """The exchange side of the upstream refs: a `book` topic's open waits for the test's `go`."""

    def __init__(self) -> None:
        self.entered, self.go = threading.Event(), asyncio.Event()

    async def open(self, key: Any) -> None:
        if key[1] == "book":
            self.entered.set()
            await self.go.wait()

    async def drop(self, key: Any) -> None: ...


@_FLAG
@pytest.mark.parametrize("named", [(ACC_A, ACC_B), (ACC_B,)], ids=["narrowed", "ended"])
def test_x02_ac_13_a_sub_awaiting_its_upstream_when_b_is_withdrawn_is_served_without_b(
    world: RawWorld, flag: BackpressureConfig | None, named: tuple[uuid.UUID, ...]
) -> None:
    m1, sink = world.login("m1", ACC_A, ACC_B), _Gated()
    world.registry.services.upstream = UpstreamRefs(sink)
    kept = ACC_A in named
    revoked = delta("cv_ws_revoked_total", reason="account_scope_changed")
    with raw_connect(world) as c:
        authenticated(c, m1)
        topics = [topic("positions", *named), {"ch": "book.BTCUSDT.50"}]
        c.send({"t": "sub", "id": "s", "p": {"topics": topics}})
        assert sink.entered.wait(5.0)  # `positions` is admitted; `book` waits in its upstream
        mark, at_ms = len(c.seen), world.clock.wall_ms()
        world.call(partial(world.amended, m1, drop=(ACC_B,)))
        world.call(sink.go.set)
        flushed(c)
        assert [publish(world, "positions", a) for a in (ACC_B, ACC_A)] == [0, kept]
        world.clock.now += 5.0  # past the pacing window the narrowed topic's snapshot opened
        c.send({"t": "ping", "id": "tick"})  # the writer's turn that sends A's delta precedes this
        flushed(c)
    got = since(c, mark)
    _announced(got, at_ms)
    assert [f["t"] for f in got[:4]] == ["permission_change", "revoked", "sub_ok", "snap"]
    end, sub_ok = got[1], got[2]
    assert (end["ch"], end["p"]["resubscribe_allowed"]) == ("positions", kept)
    positions = sub_ok["p"]["results"][0]
    if kept:  # narrowed in place: the reply says A alone
        assert positions["effective"]["exchange_account_ids"] == [str(ACC_A)]
    else:  # ended before its reply: refused, as a `sub` of B is now
        assert positions["error"]["code"] == "account_scope_denied"
    deltas = [f for f in got if f["t"] == "d"]  # the narrowed topic goes on for A: its frame, sent
    assert len(deltas) == (1 if kept else 0) and naming(deltas, ACC_A) == deltas
    assert len(world.audit.of("ws.subscription.revoked")) == 1 and revoked() == 1
    assert world.audit.of("ws.subscribe.denied") == []  # the change's row records it (23 §5.2)


@_FLAG
def test_x02_ac_14_a_grant_withdrawn_during_the_first_auth_is_not_in_its_auth_ok(
    world: RawWorld, flag: BackpressureConfig | None
) -> None:
    m1 = world.login("m1", ACC_A, ACC_B)
    world.races[1] = partial(world.amended, m1, drop=(ACC_B,))  # B is read, then withdrawn
    with raw_connect(world) as c:
        auth_ok = authenticated(c, m1)
        mark = len(c.seen)
        (denied,) = answers(c, topic("orders", ACC_B))
        flushed(c)
    assert [f["t"] for f in since(c, mark)] == ["sub_ok"]  # nothing else was queued: no `revoked`
    assert auth_ok["p"]["account_scope"] == [str(ACC_A)] and world.reads == 2  # read again
    assert denied["error"]["code"] == "account_scope_denied"
    assert world.audit.of("ws.subscription.revoked") == [] and naming(c.seen, ACC_B) == []


@_FLAG
def test_x02_ac_14_a_second_withdrawal_during_the_handshake_recheck_is_in_its_auth_ok(
    world: RawWorld, flag: BackpressureConfig | None
) -> None:
    m1 = world.login("m1", ACC_A, ACC_B, ACC_C)
    handshake = delta("cv_ws_permission_snapshots_refused_total", event="handshake")
    world.races[1] = partial(world.amended, m1, drop=(ACC_B,))  # during the first read
    world.races[2] = partial(world.amended, m1, drop=(ACC_C,))  # during the re-check's read
    with raw_connect(world) as c:
        auth_ok = authenticated(c, m1)
        (denied,) = answers(c, topic("orders", ACC_B, ACC_C))
    assert auth_ok["p"]["account_scope"] == [str(ACC_A)] and world.reads == 3  # read three times
    assert denied["error"]["code"] == "account_scope_denied" and handshake() == 1  # the old read
    assert naming(c.seen, ACC_B) == [] and naming(c.seen, ACC_C) == []
    (row,) = world.audit.of("ws.permission_snapshot.refused")
    assert (row["reason"], row["after_state"]["event"]) == ("stale", "handshake")


@_FLAG
def test_x02_ac_14_a_grant_withdrawn_during_a_reauth_keeps_the_withdrawal(
    world: RawWorld, flag: BackpressureConfig | None
) -> None:
    m1 = world.login("m1", ACC_A, ACC_B)
    stale = delta("cv_ws_permission_snapshots_refused_total", event="reauth")
    revoked = delta("cv_ws_revoked_total", reason="account_scope_changed")
    with raw_connect(world) as c:
        authenticated(c, m1)
        answers(c, topic("positions", ACC_A, ACC_B), topic("orders", ACC_B))
        flushed(c)
        world.races[world.reads + 1] = partial(
            world.amended, m1, drop=(ACC_B,)
        )  # the re-auth's read
        mark, at_ms = len(c.seen), world.clock.wall_ms()
        c.send({"t": "auth", "id": "re", "p": {"access_token": m1.token}})
        flushed(c)
        (denied,) = answers(c, topic("orders", ACC_B))
        assert [publish(world, "positions", a) for a in (ACC_B, ACC_A)] == [0, 1]
        flushed(c)
    got = since(c, mark)
    _announced(got, at_ms)
    kinds = [f["t"] for f in got]
    assert kinds[:4] == ["permission_change", "revoked", "revoked", "auth_ok"]  # the change first
    assert next(f for f in got if f["t"] == "auth_ok")["p"]["account_scope"] == [str(ACC_A)]
    snaps = [f for f in got if f["t"] == "snap"]  # with the flag on, the narrowed one's reset
    assert [f["meta"]["reason"] for f in snaps] == (["reconfigure"] if flag else [])
    assert denied["error"]["code"] == "account_scope_denied" and stale() == 1  # the old read lost
    assert revoked() == 2 and len(world.audit.of("ws.subscription.revoked")) == 2
    (row,) = world.audit.of("ws.permission_snapshot.refused")
    assert (row["reason"], row["after_state"]["event"]) == ("stale", "reauth")
