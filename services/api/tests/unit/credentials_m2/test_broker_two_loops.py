"""M2 signing from two event loops on two threads (#913 L3b; C-2.7, C-2.9, C-2.18, C-12.6), over one
guarded KEK, DEK cache, fence and touch window. Waits are bounded; nothing sleeps; fixed vectors."""

from __future__ import annotations

import asyncio
import gc
import hashlib
import hmac
import sys
import threading
import weakref
from collections.abc import Awaitable, Callable, Iterator
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import structlog

from candleviewer.exchange.base.models import CancelOrderRequest
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.secrets import KEY_ID_SLOT, Secret, _envelope, _kek, broker, candidate, service
from candleviewer.secrets.errors import CredentialUnavailable, KekUnavailable, SigningLoopMismatch
from candleviewer.secrets.store import InMemoryCredentialStore, InMemoryExportKeyStore
from tests._corpus import rest
from tests._signing import fake_capability
from tests.unit.credentials_m2 import _vectors as v
from tests.unit.credentials_m2._service_fakes import _ctx, _Src, _svc
from tests.unit.exchange.bybit._trading import Venue, account
from tests.unit.exchange.bybit.test_rate_limit_two_loops import JOIN_S, _cancel, _Loop, _on, _spawn

MSG = (b"1700000000000", KEY_ID_SLOT, b"5000", b'{"category":"linear"}')
BORROWED, FAILED = "security.credential_borrowed", "security.credential_sign_failed"
SECRET_2 = "testsecret-" + "y" * 24  # a second fixed vector, never a real secret


def _mac(secret: str = v.API_SECRET, data: bytes = b"") -> str:
    data = data or b"".join(v.API_KEY.encode() if p is KEY_ID_SLOT else p for p in MSG)
    return hmac.new(secret.encode(), data, hashlib.sha256).hexdigest()


class _Owned:
    """`_guard` as a plain non-reentrant lock that knows its holder."""

    def __init__(self) -> None:
        self._lock, self.owner = threading.Lock(), 0

    def acquire(self) -> None:
        self._lock.acquire()
        self.owner = threading.get_ident()

    def release(self, *_: object) -> None:
        self.owner = 0
        self._lock.release()

    __enter__, __exit__ = acquire, release

    def here(self) -> bool:
        return self.owner == threading.get_ident()


class _Side:
    """A loop's store and sink over shared rows, logging each call; `park(what)` holds the next."""

    def __init__(self, name: str, rows: Any, rig: _Rig, loop: asyncio.AbstractEventLoop) -> None:
        self.name, self.rows, self.rig, self.loop = name, rows, rig, weakref.ref(loop)
        self.fail, self.parks = False, dict[str, tuple[threading.Event, asyncio.Event]]()

    def __getattr__(self, name: str) -> Any:  # the boot's and `store()`'s calls
        return getattr(self.rows, name)

    def park(self, what: str) -> threading.Event:
        self.parks[what] = (threading.Event(), asyncio.Event())
        return self.parks[what][0]

    def release(self, what: str) -> None:
        self.loop().call_soon_threadsafe(self.parks.pop(what)[1].set)

    async def seen(self, what: str) -> None:
        self.rig.log.append((self.name, what))
        if asyncio.get_running_loop() is not self.loop() or self.rig.guard.here():
            self.rig.misses.append(f"{self.name}: {what}")
        if (park := self.parks.get(what)) is not None:
            park[0].set()
            await park[1].wait()

    async def get(self, key_id: UUID, env_name: str) -> Any:
        await self.seen("get")
        return await self.rows.get(key_id, env_name)

    async def touch_last_used(self, key_id: UUID) -> None:
        await self.seen("touch")

    async def __call__(self, action: str, fields: dict[str, str]) -> None:
        await self.seen(f"{action}:{fields['reason']}" if action == FAILED else action)
        if self.fail:
            raise RuntimeError("audit down")


async def _no_pool() -> None:
    """The dispose of a side's pool: the sides share in-memory rows, so there is none."""


async def _stored(broker: Any, secret: str = v.API_SECRET) -> Any:
    meta = await broker.store(
        "demo", v.ACCOUNT, "main", Secret(v.API_KEY), Secret(secret), v.SNAPSHOT
    )
    broker._store.activate(meta.key_id)
    return meta.key_id


class _Rig:
    """M2 started on the serving loop, a key stored, the lane bound to its own `_Side`."""

    def __init__(self, mp: pytest.MonkeyPatch, keys: Any = None, staged: bool = False) -> None:
        self.log, self.misses, self.ios = list[tuple[str, str]](), list[str](), list[Any]()
        real_io, real_open = service._LoopIo, _envelope.open_
        mp.setattr(service, "_LoopIo", lambda *a: self.ios.append(real_io(*a)) or self.ios[-1])
        mp.setattr(service, "_AUDIT_TIMEOUT_S", 60.0)  # a parked record never times out

        def open_(key: Any, blob: bytes, aad: bytes) -> bytearray:
            side = "serving" if asyncio.get_running_loop() is self.serving.loop else "lane"
            self.log.append((side, "open"))
            if not self.guard.here():
                self.misses.append(f"{side}: open outside the guard")
            return real_open(key, blob, aad)

        mp.setattr(_envelope, "open_", open_)
        self.guard, self.serving, self.lane = _Owned(), _Loop(), _Loop()
        rows, loops = InMemoryCredentialStore(), {"serving": self.serving, "lane": self.lane}
        self.sides = {name: _Side(name, rows, self, lp.loop) for name, lp in loops.items()}
        side, srcs = self.sides["serving"], [_Src(v.KEK_V1, 1)]
        if staged:  # a key under v1, then the boot at v2 beside it: a re-wrap has a row
            first = _svc(srcs[0], store=rows)  # never stopped: the KEK test counts each close
            self.serving.run(first.start(_ctx()))
            self.serving.run(_stored(first._require()))
            srcs.insert(0, _Src(v.KEK_V2, 2))
        self.svc = _svc(*srcs, store=side, audit=side, export_keys=keys)
        self.serving.run(self.svc.start(_ctx()))
        self.broker = self.svc._require()
        self.broker._guard, self.broker._clock, self.broker._timeout = (
            self.guard,
            v.FakeClock(),
            60.0,
        )
        for name in ("get", "put", "holds", "flush", "sweep"):  # every DEK cache call: guarded
            mp.setattr(broker._DekCache, name, self._guarded(getattr(broker._DekCache, name)))
        b = self.broker  # and every use of the fence, the touch window and the registry
        b._destroyed = self._owned(set, "add", "__contains__")(b._destroyed)
        b._last_touch = self._owned(dict, "get", "__setitem__")(b._last_touch)
        b._loops = self._owned(set, "add", "discard", "__iter__")(b._loops)
        mp.setattr(broker, "request_signature", self._guarded(broker.request_signature, False))
        mp.setattr(_envelope, "seal", self._guarded(_envelope.seal))  # the seal and its wrap
        self.key_id = self.serving.run(_stored(self.broker))
        self.served = service.mint_borrower(self.svc, "exchange_adapter")
        self.bind = service.mint_loop_signing(self.svc, "exchange_adapter", loop_store=self._store)
        self.signing = self.lane.run(_on(self.bind, self.sides["lane"]))

    def _store(self, _connections: int) -> tuple[_Side, Callable[[], Awaitable[None]]]:
        """M2's factory of the lane's own store: the lane's side, which has no pool to free."""
        return self.sides["lane"], _no_pool

    def _guarded(self, call: Any, held: bool = True) -> Any:
        """`call`, noting a miss unless the guard is held, or for the MAC (`held=False`) not."""
        miss = f"{call.__qualname__} {'outside' if held else 'under'} the guard"
        return lambda *a: (self.guard.here() is held or self.misses.append(miss), call(*a))[1]

    def _owned(self, base: type, *names: str) -> type:
        return type("Owned", (base,), {n: self._guarded(getattr(base, n)) for n in names})

    def __enter__(self) -> _Rig:
        return self

    def __exit__(self, failed: object, *_: object) -> None:
        closed = [lp.close() for lp in (self.serving, self.lane)]
        assert failed or all(closed), "a loop's thread outlived the bound"

    def start(self, on: str, by: str = "", key_id: UUID | None = None) -> Any:
        signer = self.served if (by or on) == "serving" else self.signing.borrower
        coro = signer.sign(key_id or self.key_id, MSG, purpose="sign_rest")
        return (self.serving if on == "serving" else self.lane).start(coro)

    def sign(self, on: str, by: str = "", key_id: UUID | None = None) -> str:
        return str(self.start(on, by, key_id).result(JOIN_S).signature)

    def of(self, side: str) -> list[str]:
        return [what for name, what in self.log if name == side and what != "touch"]


@pytest.fixture
def rig(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Rig]:
    with _Rig(monkeypatch) as r:
        yield r
        assert r.misses == []  # each spied call ran on its loop, under the guard or not


async def _drained() -> None:
    await asyncio.gather(*(t for t in asyncio.all_tasks() if t is not asyncio.current_task()))


@pytest.mark.parametrize("same", [True, False], ids=["same-key", "two-keys"])
def test_both_loops_sign_at_once_each_through_its_own_store_and_sink(rig: _Rig, same: bool) -> None:
    other = rig.key_id if same else rig.serving.run(_stored(rig.broker, SECRET_2))
    barrier = threading.Barrier(2, timeout=JOIN_S)

    async def sign(signer: Any, key_id: UUID) -> str:
        barrier.wait()  # both loops start together
        return str((await signer.sign(key_id, MSG, purpose="sign_rest")).signature)

    runs = [
        rig.serving.start(sign(rig.served, rig.key_id)),
        rig.lane.start(sign(rig.signing.borrower, other)),
    ]
    assert [run.result(JOIN_S) for run in runs] == [_mac(), _mac() if same else _mac(SECRET_2)]
    for side in ("serving", "lane"):  # written ahead (C-2.9)
        signing = rig.of(side)[rig.of(side).index("get") :]
        assert signing[:2] == ["get", BORROWED] and set(signing[2:]) == {"open"}
    for on in ("lane", "serving"):  # in turn, whichever loop won the race: the window holds
        rig.sign(on)
    for lp in (rig.serving, rig.lane):
        lp.run(_drained())
    touched = [entry for entry in rig.log if entry[1] == "touch"]  # one window for every loop
    assert len(touched) == (1 if same else 2)


def test_a_failing_lane_sink_refuses_the_signing_before_anything_is_decrypted(rig: _Rig) -> None:
    rig.sides["lane"].fail = True
    with pytest.raises(CredentialUnavailable, match=r"^audit_unavailable$"):
        rig.sign("lane")
    assert rig.of("lane") == ["get", BORROWED]


def test_the_lanes_write_is_a_lane_task_that_its_close_cancels_and_awaits(rig: _Rig) -> None:
    stalled = rig.sides["lane"].park("touch")
    rig.sign("lane")
    assert stalled.wait(JOIN_S)
    (write,) = rig.ios[0].touches.values()
    assert write.get_loop() is rig.lane.loop and rig.broker._touches == {}
    rig.lane.run(rig.signing.aclose())
    assert write.cancelled() and rig.ios[0].touches == {}


def test_a_kek_dropped_from_a_third_thread_fails_both_loops_closed_before_any_io(rig: _Rig) -> None:
    rig.sign("lane")
    cached, logged = rig.broker._cache._items[rig.key_id][1], len(rig.log)
    rig.broker.drop_kek()
    for on in ("serving", "lane"):
        with pytest.raises(KekUnavailable):
            rig.sign(on)
    assert (any(cached), rig.log[logged:]) == (False, [])


def test_a_kek_dropped_during_the_lanes_record_refuses_it_and_closes_the_record(rig: _Rig) -> None:
    parked, signing = rig.sides["lane"].park(BORROWED), rig.start("lane")
    assert parked.wait(JOIN_S)
    rig.broker.drop_kek()
    rig.sides["lane"].release(BORROWED)
    with pytest.raises(KekUnavailable):
        signing.result(JOIN_S)
    assert rig.of("lane") == ["get", BORROWED, f"{FAILED}:kek_unavailable"]


def test_a_destroy_on_the_serving_loop_fences_the_lane_and_cancels_its_write(rig: _Rig) -> None:
    rig.sides["lane"].park("touch")  # the lane's write of the key stalls in flight
    rig.sign("lane")
    (write,) = rig.ios[0].touches.values()
    parked, signing = rig.sides["lane"].park(BORROWED), rig.start("lane")
    assert parked.wait(JOIN_S)
    rig.serving.run(rig.broker.destroy(rig.key_id))
    rig.sides["lane"].release(BORROWED)
    with pytest.raises(CredentialUnavailable, match=r"^credential_unavailable$"):
        signing.result(JOIN_S)
    rig.lane.run(asyncio.wait([write], timeout=JOIN_S))
    assert rig.of("lane")[5:] == ["get", BORROWED, f"{FAILED}:credential_unavailable"]
    assert write.cancelled()


def test_a_flush_on_the_serving_loop_zeroes_the_lanes_dek_and_it_unwraps_again(rig: _Rig) -> None:
    rig.sign("lane")
    cached = rig.broker._cache._items[rig.key_id][1]
    rig.serving.run(_on(rig.broker.flush_cache, rig.key_id))
    assert not any(cached) and rig.key_id not in rig.broker._cache._items
    assert rig.sign("lane") == _mac() and rig.of("lane")[5:].count("open") == 3


@pytest.mark.parametrize(
    ("on", "by", "closed"),
    [("serving", "lane", False), ("lane", "serving", False), ("lane", "lane", True)],
    ids=["lane-borrower-on-serving", "serving-borrower-on-lane", "after-its-close"],
)
def test_a_signing_off_its_ios_loop_is_refused_with_nothing_done(
    rig: _Rig, on: str, by: str, closed: bool
) -> None:
    if closed:
        rig.lane.run(rig.signing.aclose())
    logged, code = len(rig.log), r"^signing_loop_mismatch$"
    with structlog.testing.capture_logs() as logs, pytest.raises(SigningLoopMismatch, match=code):
        rig.sign(on, by)
    assert (rig.log[logged:], rig.broker._touches) == ([], {})
    assert [e["log_level"] for e in logs] == ["warning" if closed else "error"]  # error: wiring


def test_a_close_on_another_loop_is_refused_and_closes_nothing(rig: _Rig) -> None:
    with pytest.raises(SigningLoopMismatch):
        rig.serving.run(rig.signing.aclose())
    assert not rig.ios[0].closed and rig.sign("lane") == _mac()


def test_a_signing_in_flight_at_its_close_writes_nothing_and_leaves_no_io(rig: _Rig) -> None:
    rig.sign("lane", key_id=rig.serving.run(_stored(rig.broker, SECRET_2)))  # registered
    rig.lane.run(_drained())
    parked, signing = rig.sides["lane"].park(BORROWED), rig.start("lane")
    assert parked.wait(JOIN_S)
    rig.lane.run(rig.signing.aclose())
    rig.sides["lane"].release(BORROWED)
    signing.exception(JOIN_S)  # it ends, signed or refused
    rig.lane.run(_drained())
    with rig.guard:  # one write, the first signing's; none registered: left, not rejoined
        assert (rig.log.count(("lane", "touch")), rig.broker._live_loops()) == (1, [])


def test_every_decrypt_runs_under_the_guard_and_no_store_or_sink_call_does(rig: _Rig) -> None:
    for on in ("lane", "serving", "lane"):
        rig.sign(on)
    fresh = broker.CredentialBroker(InMemoryCredentialStore(), v.AuditLog(), v.kek())
    assert type(fresh._guard) is type(threading.Lock())  # plain: never re-entered, never a no-op
    assert rig.log.count(("lane", "open")) == 5


def test_the_serving_close_returns_at_once_while_the_lane_stalls(rig: _Rig) -> None:
    rig.sides["lane"].park("touch")
    rig.sign("lane")
    (write,) = rig.ios[0].touches.values()
    gate = threading.Event()
    blocked = rig.lane.start(_on(gate.wait, JOIN_S))  # the lane's thread does nothing else
    rig.serving.run(rig.broker.aclose())  # bounded by JOIN_S: a wait on the lane would hang
    gate.set()
    rig.lane.run(asyncio.wait([write], timeout=JOIN_S))
    assert blocked.result(JOIN_S) and rig.ios[0].closed and write.cancelled()


@pytest.mark.parametrize("closed", [True, False], ids=["closed", "leaked"])
def test_a_finished_loop_is_freed_and_leaves_the_registry(rig: _Rig, closed: bool) -> None:
    extra = _Loop()
    side = _Side("extra", rig.sides["lane"].rows, rig, extra.loop)

    def own(_connections: int, store: _Side = side) -> tuple[_Side, Callable[[], Awaitable[None]]]:
        return store, _no_pool  # the extra loop's own side, which has no pool to free

    bind = service.mint_loop_signing(rig.svc, "exchange_adapter", loop_store=own)
    signing = extra.run(_on(bind, side))
    extra.run(signing.borrower.sign(rig.key_id, MSG, purpose="sign_rest"))
    if closed:
        extra.run(signing.aclose())
    assert extra.close()
    gone = weakref.ref(extra.loop)
    del extra, signing, side, bind, own
    rig.ios.clear()
    gc.collect()
    with rig.guard:
        assert (gone(), rig.broker._live_loops()) == (None, [])


@pytest.mark.parametrize("where", ["get", BORROWED])
def test_a_lane_signing_cancelled_in_its_read_or_record_decrypts_nothing(
    rig: _Rig, where: str
) -> None:
    parked = rig.sides["lane"].park(where)
    signing = rig.lane.run(_spawn(rig.signing.borrower.sign(rig.key_id, MSG, purpose="sign_rest")))
    assert parked.wait(JOIN_S) and rig.lane.run(_cancel(signing))
    assert rig.of("lane") == ["get", BORROWED][: 1 + (where == BORROWED)]


def _collected_holding(guard: Any) -> bool:
    """Collects the garbage in a running loop on a thread holding `guard`, as a loop's guarded
    section may: whether that thread ends within the bound (a finaliser taking it would not)."""

    async def collect() -> None:
        with guard:
            gc.collect()

    collector = threading.Thread(target=asyncio.run, args=(collect(),), daemon=True)
    collector.start()
    collector.join(JOIN_S)
    return not collector.is_alive()


@pytest.mark.parametrize("park", ["destroyed", "destroy_failed"])  # the record it is ended in
def test_a_destroy_ended_by_the_collector_on_a_thread_holding_the_guard_takes_no_lock(
    monkeypatch: pytest.MonkeyPatch, park: str
) -> None:
    gc.collect()  # garbage an earlier test left is not this test's to judge
    unraisable: list[object] = []
    monkeypatch.setattr(sys, "unraisablehook", unraisable.append)
    loop, parked = asyncio.new_event_loop(), asyncio.Event()

    async def sink(action: str, fields: dict[str, str]) -> None:
        if action != f"security.credential_{park}":
            raise RuntimeError("audit down")  # the destroy's own record fails: it parks in the next
        parked.set()
        await asyncio.Event().wait()  # this record never lands

    b = broker.CredentialBroker(InMemoryCredentialStore(), v.AuditLog(), v.kek())
    task = loop.create_task(b.destroy(loop.run_until_complete(_stored(b))))
    b._audit_sink = sink
    loop.run_until_complete(parked.wait())
    loop.close()
    del task, loop
    assert (_collected_holding(b._guard), unraisable) == (True, [])


def test_a_boot_ended_by_the_collector_on_a_thread_holding_the_guard_takes_no_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gc.collect()  # garbage an earlier test left is not this test's to judge
    unraisable: list[object] = []
    monkeypatch.setattr(sys, "unraisablehook", unraisable.append)
    loop, parked, keys = asyncio.new_event_loop(), asyncio.Event(), InMemoryExportKeyStore()
    svc = _svc(_Src(v.KEK_V1, 1), export_keys=keys)

    async def active(env: str) -> None:  # none for the KCV's trial; the export key's open parks
        if svc._broker is not None:
            parked.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(keys, "active", active)
    task = loop.create_task(svc.start(_ctx()))
    loop.run_until_complete(parked.wait())
    b = svc._broker
    loop.close()
    del task, loop
    assert (_collected_holding(b._guard), unraisable) == (True, [])
    assert (svc._broker, b._kek) == (None, None)  # unpublished, its KEKs zeroed


def test_an_activation_ended_by_the_collector_destroys_nothing_and_takes_no_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gc.collect()  # garbage an earlier test left is not this test's to judge
    unraisable: list[object] = []
    monkeypatch.setattr(sys, "unraisablehook", unraisable.append)
    loop, parked = asyncio.new_event_loop(), asyncio.Event()
    b = broker.CredentialBroker(InMemoryCredentialStore(), v.AuditLog(), v.kek())
    pair = Secret(v.API_KEY), Secret(v.API_SECRET)
    stored = loop.run_until_complete(b.store("demo", v.ACCOUNT, "main", *pair, v.SNAPSHOT))

    async def activate(_: object) -> None:  # a key import's activation, never answered
        parked.set()
        await asyncio.Event().wait()

    task = loop.create_task(candidate._activated(b, stored, activate, ("system", "admin", None)))
    loop.run_until_complete(parked.wait())
    loop.close()
    del task, loop
    assert (_collected_holding(b._guard), unraisable, b._destroyed) == (True, [], set())


def test_no_secret_dek_or_signature_reaches_a_log_an_error_or_a_repr(rig: _Rig) -> None:
    with structlog.testing.capture_logs() as logs:
        signature = rig.sign("lane")
        dek = bytes(rig.broker._cache._items[rig.key_id][1]).hex()
        with pytest.raises(SigningLoopMismatch) as refused:
            rig.sign("serving", "lane")
    shown = f"{logs!r} {refused.value!r} {rig.signing!r} {rig.signing.borrower!r} {rig.ios!r}"
    assert not [s for s in (v.API_KEY, v.API_SECRET, dek, signature) if s in shown]
    assert [(e["event"], e["log_level"]) for e in logs] == [(f"secrets.{refused.value}", "error")]


def test_the_loop_signing_is_minted_for_the_adapter_only_and_never_subclassed() -> None:
    with pytest.raises(ValueError, match="not permitted"):
        service.mint_loop_signing(service.SecretsService(), "oms")
    with pytest.raises(TypeError, match="may not be subclassed"):
        type("Evil", (service.LoopSigning,), {"__module__": "candleviewer.oms.evil"})


def test_a_lane_port_signs_on_the_lane_loop_through_the_lanes_store_and_sink(rig: _Rig) -> None:
    reply, ref = rest("rest/trading-cancel-reply.json"), account(key_ref=str(rig.key_id))
    venue, never = Venue().on("/v5/order/cancel", reply), httpx.MockTransport(Venue().handler)
    adapter = ExchangeBybitService(credentials=rig.served, environment="demo", rest_transport=never)
    cancel = CancelOrderRequest(
        account=ref, symbol="BTCUSDT", exchange_order_id=reply["result"]["orderId"]
    )

    async def on_the_lane() -> bool:
        own = httpx.MockTransport(venue.handler)  # built on the lane's loop, as L1b's root does
        port = adapter.lane_trading_port("demo", credentials=rig.signing.borrower, transport=own)
        with pytest.raises(RuntimeError, match="no private stream"):
            await port.subscribe_private(ref)
        ok = (await port.cancel_order(cancel)).ok
        await port.aclose()
        return ok

    assert rig.lane.run(on_the_lane())
    ((sent,), h) = venue.sent, venue.sent[0].headers
    signed = (h["X-BAPI-TIMESTAMP"] + v.API_KEY + h["X-BAPI-RECV-WINDOW"]).encode() + sent.content
    assert h["X-BAPI-SIGN"] == _mac(data=signed) and rig.of("lane")[:2] == ["get", BORROWED]
    assert rig.of("serving").count("get") == 0


def test_a_lane_port_refuses_the_adapters_borrower_another_environment_and_testnet() -> None:
    own, lane = fake_capability(), fake_capability()
    adapter = ExchangeBybitService(credentials=own, environment="demo")
    with pytest.raises(ValueError, match="own loop's borrower"):
        adapter.lane_trading_port("demo", credentials=own)
    with pytest.raises(ValueError, match="process's environment"):
        adapter.lane_trading_port("live", credentials=lane)
    testnet = ExchangeBybitService(credentials=own, environment="testnet")
    with pytest.raises(ValueError, match="no trading capability record"):
        testnet.lane_trading_port("testnet", credentials=lane)
    raw = httpx.MockTransport(Venue().handler)  # the dev-only account fixture's (#2893)
    fixture = ExchangeBybitService(credentials=own, environment="demo", rest_transport=raw)
    with pytest.raises(RuntimeError, match="transport of its own loop"):  # never httpx's own
        fixture.lane_trading_port("demo", credentials=lane)
    for shared in (raw, fixture._rest_transport):  # no transport is shared across loops
        with pytest.raises(ValueError, match="adapter's transport"):
            fixture.lane_trading_port("demo", credentials=lane, transport=shared)


class _Counted(httpx.AsyncBaseTransport):
    """A lane's own transport that counts its closes and sends nothing."""

    def __init__(self) -> None:
        self.closed = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise AssertionError("nothing is sent")

    async def aclose(self) -> None:
        self.closed += 1


def test_a_lane_ports_transport_outlives_a_retired_client_and_the_ports_close() -> None:
    """Only the root that built the lane's transport closes it: never a client that a key
    rotation retires, nor the port's `aclose`."""

    async def closes() -> int:
        own = _Counted()
        adapter = ExchangeBybitService(credentials=fake_capability(), environment="demo")
        port = adapter.lane_trading_port("demo", credentials=fake_capability(), transport=own)
        await port._client(account(key_ref=str(uuid4())))
        await port._client(account(key_ref=str(uuid4())))  # a new key retires the old client
        await port.aclose()
        return own.closed

    assert asyncio.run(closes()) == 0


def test_the_guard_free_kek_users_and_drop_kek_all_run_on_the_serving_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Boot's export-key custody, its signer and rotator, and the re-wrap use a KEK outside the
    guard; they never overlap a `drop_kek` only because it runs on their thread, the serving
    loop's (`SecretsService.stop`). So every KEK use outside the guard, and every KEK close, is
    on that thread; the lane's signing uses the KEK only under the guard."""
    gc.collect()  # garbage an earlier test left closes no KEK under this test's spies
    uses: list[tuple[str, int, bool]] = []
    held: list[Any] = [lambda: False]
    live, close = _kek.LoadedKek._live_key, _kek.LoadedKek.close

    def note(kind: str) -> None:
        uses.append((kind, threading.get_ident(), held[-1]()))

    monkeypatch.setattr(_kek.LoadedKek, "_live_key", lambda k: (note("use"), live(k))[1])
    monkeypatch.setattr(_kek.LoadedKek, "close", lambda k: (note("close"), close(k))[1])
    keys, mint_rotator = InMemoryExportKeyStore(), service.mint_signing_key_rotator
    with _Rig(monkeypatch, keys, staged=True) as rig:
        held.append(rig.guard.here)
        serving = rig.serving.run(_on(threading.get_ident))
        rig.sign("lane")
        digest, signer = hashlib.sha256(b"an export").digest(), service.mint_export_signer(rig.svc)
        rig.serving.run(signer.sign_audit_export(keys.rows[-1]["key_id"], digest, uuid4(), uuid4()))
        call = {"actor_user_id": uuid4(), "client_ref": uuid4(), "client_body_sha256": "b" * 64}
        rotated = mint_rotator(rig.svc).rotate("scheduled", **call, export_running=lambda: False)
        rewrap = rig.svc.rewrap_deks(2, environment="demo", actor_user_id="o", actor_role="owner")
        assert (rig.serving.run(rotated)[1], rig.serving.run(rewrap).rewrapped) == (False, 1)
        rig.serving.run(rig.svc.stop(1.0))
    free = ("serving: open outside the guard", "seal outside the guard")  # theirs; all else guarded
    assert [miss for miss in rig.misses if not miss.endswith(free)] == []
    unguarded = {thread for kind, thread, guarded in uses if not guarded}
    closes = {(thread, guarded) for kind, thread, guarded in uses if kind == "close"}
    assert (unguarded, closes) == ({serving}, {(serving, True)})
