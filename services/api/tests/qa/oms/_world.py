"""The E29-Q02 conformance world (#1147, C4a): the OMS as `create_app()` composes it, driven as a
client drives it. The RBAC pack's real app (`build_world`, no network, C-13.5) holds the OMS runtime
(`OmsRuntime`: its order lane inline on the one loop every request runs on, a `FakeTradingPort` for
its venue, `InMemoryOrderStore` for its stores, a fake clock), the app's own `orders`, `executions`
and machine-state topics, and OMS reads over the runtime's own rows. A test places, amends and
cancels as the Owner, reads the frames a `/ws` client is sent, delivers the venue's private pushes
(derived in-test from the corpus's docs transcriptions and read by the adapter's own parser:
derived, not evidence, the 2026-10-28 ruling Q1) and holds a venue answer at a door to put an event
inside it.

The shape is E29-X02's `tests/security/oms/_world.py` (#982, #5715), whose role matrix, seeded
final orders and scope cells stay X02's. This world adds what a lifecycle needs: a catalogue and a
quote so a create is admitted, a private stream fed by the venue's port, reads that follow the
runtime's rows, and the REST, WS and push helpers. When #5715 merges one of the two takes the
other's place.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final, cast

import httpx
import pytest
from anyio.from_thread import start_blocking_portal

import candleviewer.app as appmod
from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.models import (
    AccountRef,
    FeeRate,
    PlaceOrderRequest,
    RiskLimitTier,
    Wallet,
)
from candleviewer.exchange.bybit import private_parse as pp
from candleviewer.exchange.bybit.private_stream import REQUIRED_OPS
from candleviewer.oms.fakes import InMemoryOrderStore
from candleviewer.oms.reads import OmsReads
from candleviewer.oms_wiring import GroupStores, OmsStores
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.storage.repositories.accounts import AccountScope, GrantScope
from candleviewer.storage.repositories.orders import OrderRow, settle_accounts
from candleviewer.storage.repositories.trading_accounts import TradingAccountRow
from tests.contract.rbac.rbac_harness import GRANTED, World, bearer, build_world, user_id_of
from tests.unit.api import oms_reads_world as rw
from tests.unit.exchange.bybit._private import linear_execution, linear_order, push
from tests.unit.oms import command_rig as cr
from tests.unit.oms import submit_rig as sr
from tests.unit.oms import test_oms_runtime as rt

ACCOUNT: Final = AccountId(GRANTED)
KEY: Final = uuid.UUID(cr.KEYS["demo"])  # the account's active key
REF: Final = AccountRef(account_id=ACCOUNT, uid="1001", environment="demo", key_ref=str(KEY))
#: The symbols the world lists: a test that leaves an order unresolved keeps its position key, so
#: it has a symbol of its own.
SYMBOLS: Final = (sr.SYMBOL, "ETHUSDT", "SOLUSDT")
T0_US: Final = int(rt.T0.timestamp()) * 1_000_000  # the facade's clock, as the venue stamps it
#: The topics the adapter subscribes, each by the neutral topic its parser reads it as.
_TOPIC: Final = {pp.TOPICS[topic]: topic for ops in REQUIRED_OPS for topic in ops}
ORDERS, FILLS = _TOPIC["order"], _TOPIC["execution"]
_MARK: Final = {"kind": "notice", "severity": "info", "message": "marker", "reason": "qa.marker"}
_BODY: Final = {
    "exchange_account_id": str(ACCOUNT), "symbol": sr.SYMBOL, "side": "buy", "order_type": "limit",
    "price": "60000", "sizing": {"mode": "fixed_qty", "qty": "0.010"},
    "stop_loss": {"unit": "price", "value": "58000"},
}  # fmt: skip


class Listed(dict[str, Any]):
    """The catalogue's snapshot: its instruments, and each one's lowest risk-limit tier."""

    def risk_limit_tiers(self, symbol: str) -> tuple[RiskLimitTier, ...] | None:
        tier = RiskLimitTier(
            tier_id=1, risk_limit_value=Decimal(2_000_000), initial_margin_rate=Decimal("0.01"),
            maintenance_margin_rate=Decimal("0.005"), max_leverage=Decimal(100),
        )  # fmt: skip
        return (tier,) if symbol in self else None


class Groups(sr.Groups):
    """The trade-group store as the runtime reads it here: no open group, no anchor."""

    async def list_open_groups(self) -> tuple[()]:
        return ()

    async def find_anchor(self, *_args: Any) -> None:
        return None


@dataclass
class Venue(rt.Venue):
    """The runtime's venue: its lane port holds the size step's figures (24 Sec.9.3.6, a wallet and
    a fee rate) and is the source of the account's private stream."""

    def port(self, env: str) -> rt.Port:
        port = rt.Port(environment=cast(Any, env), now_us=lambda: T0_US)
        cash, none = Decimal(100_000), Decimal(0)
        port.set_wallet(Wallet(
            account_id=ACCOUNT, equity=cash, wallet_balance=cash, available_to_withdraw=None,
            available_margin=cash, used_margin=none, unrealised_pnl=none, cum_realised_pnl=none,
            account_im_rate=none, account_mm_rate=none, updated_at=T0_US,
        ))  # fmt: skip
        for symbol in SYMBOLS:
            taker = Decimal("0.00055")
            port.set_fee_rate(ACCOUNT, FeeRate(
                symbol=symbol, maker=Decimal("0.0002"), taker=taker, fetched_at=T0_US
            ))  # fmt: skip
        return port

    async def open_private_stream(self, account: AccountRef, *, clock_offset_ms: Any = None) -> Any:
        return await self.ports[-1].subscribe_private(account)


@dataclass
class Runtime(rt.World):
    """`test_oms_runtime`'s world, its catalogue and quote composed and the account streamed."""

    def __post_init__(self) -> None:
        super().__post_init__()
        quote = SimpleNamespace(
            bid1_price=Decimal("59999"), ask1_price=Decimal("60001"), last_price=Decimal("60000")
        )
        tickers = SimpleNamespace(
            latest=lambda _symbol: quote, is_stale=lambda _symbol: False,
            acquire=lambda _consumer, _symbol: None, release=lambda _consumer, _symbol: None,
        )  # fmt: skip
        catalogue = Listed({s: sr.instrument(symbol=s, base_coin=s[:-4]) for s in SYMBOLS})
        self.ingestion = SimpleNamespace(
            clock=self.health, tickers=tickers, clock_offset_ms=rt._unread,
            instruments=SimpleNamespace(snapshot=lambda: catalogue),
            clock_offset_snapshot_ms=lambda: None,
        )  # fmt: skip

    def stores(self) -> OmsStores:
        return replace(super().stores(), groups=cast(GroupStores, Groups(self.store)))


class _Live(list[Any]):
    """A row list the runtime's tables fill afresh on each read."""

    def __init__(self, rows: Callable[[], list[Any]]) -> None:
        super().__init__()
        self._rows = rows

    def __iter__(self) -> Iterator[Any]:
        return iter(self._rows())


class Reads(rw.Store):
    """The read store of `oms_reads_world` over the runtime's own rows (orders, executions and
    event chains as they stand), the one account demo."""

    def __init__(self, store: InMemoryOrderStore) -> None:
        super().__init__()
        self.orders = _Live(lambda: [(row, None) for row in store._orders.values()])
        self.fills = _Live(lambda: [(fill, None) for fill in store._fills.values()])
        chains = SimpleNamespace(
            get=lambda order_id, default: (
                [e.fresh() for e in store._events.get(order_id, ())] or default
            )
        )
        self.events = cast(Any, chains)

    def _reach(self, scope: AccountScope, env: str, requested: Any) -> set[uuid.UUID]:
        live = [ACCOUNT] if env == "demo" else []
        if isinstance(scope, GrantScope):
            live = [a for a in live if a in scope.account_ids]
        return set(settle_accounts(live, tuple(requested)))

    def _viewable(self, scope: AccountScope, env: str, account: uuid.UUID) -> bool:
        return env == "demo" and account == ACCOUNT


@dataclass
class Door:
    """A venue answer held (`OmsWorld.hold`): each call that reaches it waits until it is opened."""

    world: OmsWorld
    method: str
    gate: asyncio.Event = field(default_factory=asyncio.Event)
    arrived: threading.Event = field(default_factory=threading.Event)
    requests: list[Any] = field(default_factory=list)

    def open(self) -> None:
        self.world.call(self.gate.set)


@dataclass
class Socket:
    """One signed-in `/ws` connection of the Owner."""

    world: OmsWorld
    ws: Any

    def recv(self) -> dict[str, Any]:
        """The next frame, pings answered; one that never comes fails at the suite's bound."""
        while (frame := self.ws.receive_json())["t"] == "ping":
            self.ws.send_json({"t": "pong", "id": frame["id"]})
        return cast(dict[str, Any], frame)

    def sub(self, ch: str) -> dict[str, Any]:
        """Subscribed to `ch`, its snapshot read and returned: a frame published before it is
        lost to a subscription still `snapshot_pending`."""
        scope = (
            {} if ch.startswith("machines.") else {"opts": {"exchange_account_ids": [str(ACCOUNT)]}}
        )
        self.ws.send_json({"t": "sub", "id": ch, "p": {"topics": [{"ch": ch, **scope}]}})
        while not ((frame := self.recv())["t"] == "snap" and frame.get("ch") == ch):
            assert frame["t"] in ("sub_ok", "snap", "d"), frame
        return cast(dict[str, Any], frame["p"])

    def drain(self) -> list[dict[str, Any]]:
        """Every frame sent so far: those up to a marker broadcast now, twice over, so a frame
        still queued behind the first marker's priority lane is read too."""
        frames: list[dict[str, Any]] = []
        for _ in range(2):
            self.world.call(self.world.app.state.ws_hub.broadcast_system, _MARK)
            while (frame := self.recv()).get("p") != _MARK:
                frames.append(frame)
        return frames

    def until(self, done: Callable[[list[dict[str, Any]]], bool]) -> list[dict[str, Any]]:
        """Every frame until `done` holds of those read, and those sent with it."""
        frames: list[dict[str, Any]] = []
        while not done(frames):
            frames.append(self.recv())
        return [*frames, *self.drain()]


@dataclass
class OmsWorld:
    """The world: `pack` is the RBAC pack's app, `oms` the runtime's fakes, `portal` the loop."""

    pack: World
    oms: Runtime
    runtime: Any
    portal: Any
    keys: int = 0
    doors: list[Door] = field(default_factory=list)

    @property
    def app(self) -> Any:
        return self.pack.app

    @property
    def port(self) -> rt.Port:
        return self.oms.venue.ports[-1]

    def call(self, fn: Any, *args: Any) -> Any:
        return self.portal.call(fn, *args)

    def settle(self) -> None:
        """Every turn the runtime's loop and its order lane have in hand, taken."""
        self.call(_settled, self.runtime)

    def reset(self) -> None:
        """Between tests: each door opened, the venue's methods, scripts and holdings undone."""
        for door in self.doors:
            door.open()
            self.port.__dict__.pop(door.method, None)
        self.doors.clear()
        for held in (self.port._scripts, self.port._open, self.port._history):
            self.call(held.clear)
        self.port._positions.clear()
        self.settle()

    # REST, as the Owner
    def rest(
        self, method: str, path: str, body: Any = None, headers: dict[str, str] | None = None
    ) -> httpx.Response:
        sent = {**bearer("owner"), **(headers or {})}
        return cast(httpx.Response, self.pack.client.request(method, path, json=body, headers=sent))

    def key(self) -> dict[str, str]:
        self.keys += 1
        return {"Idempotency-Key": str(uuid.UUID(int=0xC4A0_0000 + self.keys))}

    def place(self, **over: Any) -> httpx.Response:
        return self.rest("POST", "/orders", _BODY | over, self.key())

    def amend(self, order: dict[str, Any], etag: str, **terms: Any) -> httpx.Response:
        return self.rest("PATCH", f"/orders/{order['id']}", terms, {"If-Match": etag, **self.key()})

    def cancel(self, order: dict[str, Any]) -> httpx.Response:
        return self.rest("DELETE", f"/orders/{order['id']}", None, self.key())

    def order(self, order: dict[str, Any]) -> dict[str, Any]:
        """`getOrder` with its events and executions."""
        answer = self.rest("GET", f"/orders/{order['id']}?include_events=true")
        assert answer.status_code == 200, answer.text
        return cast(dict[str, Any], answer.json())

    @contextmanager
    def socket(self, *channels: str) -> Iterator[Socket]:
        with self.pack.client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
            sock = Socket(self, ws)
            ws.send_json({"t": "hello", "id": "h"})
            assert sock.recv()["t"] == "welcome"
            ws.send_json({"t": "auth", "id": "a", "p": {"access_token": "tok-owner"}})
            assert sock.recv()["t"] == "auth_ok"
            for ch in channels:
                sock.sub(ch)
            yield sock

    # the stores
    def row(self, order: dict[str, Any]) -> OrderRow:
        row = self.call(self.oms.store.get, ACCOUNT, uuid.UUID(order["id"]))
        assert row is not None
        return cast(OrderRow, row)

    def chain(self, order: dict[str, Any]) -> list[tuple[str, str, str | None]]:
        """The order's stored `order_events`: kind, source and the state it moved to."""
        events = self.call(self.oms.store.list_for_order, ACCOUNT, uuid.UUID(order["id"]))
        return [(e.kind, e.source, e.to_state) for e in events]

    def fills(self) -> list[str]:
        """The `exec_id` of every execution the store holds."""
        return [x.exec_id for x in self.oms.store._fills.values()]

    # the venue
    def sent(self, method: str) -> list[Any]:
        return [c.request for c in self.port.calls if c.method == method]

    def creates(self, order: dict[str, Any]) -> list[PlaceOrderRequest]:
        """Every create the venue received for the order, each carrying its native stop (C-2.6)."""
        sent = [r for r in self.sent("place_order") if isinstance(r, PlaceOrderRequest)]
        creates = [r for r in sent if r.order_link_id == order["order_link_id"]]
        assert all(create.stop_loss == Decimal(order["stop_loss"]) for create in creates)
        return creates

    def hold(self, method: str) -> Door:
        """The venue's answer to `method` held at a door until it is opened."""
        door, real = Door(self, method), getattr(self.port, method)
        self.doors.append(door)

        async def held(*args: Any, **kwargs: Any) -> Any:
            door.requests.append(args[0])
            door.arrived.set()
            await door.gate.wait()
            return await real(*args, **kwargs)

        setattr(self.port, method, held)
        return door

    @contextmanager
    def pending(self, door: Door, call: Callable[..., Any], *args: Any) -> Iterator[Future[Any]]:
        """`call(*args)`, a REST request, on a thread of its own and parked at `door` until the
        block ends: the venue's answer is held while the test puts an event inside it."""
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(call, *args)
            try:
                assert door.arrived.wait(20), "no call reached the door"
                yield future
            finally:
                door.open()

    def venue_position(self, order: OrderRow, qty: str) -> None:
        """The venue's position of the order's symbol, `qty` of it, holding the stop the create
        attached: what the read-back of the stop finds once the order has filled."""
        held = cr.position(ACCOUNT, qty=qty, stop_loss=order.stop_loss)
        self.port.seed_position(held.model_copy(update={"symbol": order.symbol}))

    def deliver(self, topic: str, *rows: dict[str, Any]) -> None:
        """One frame of `rows` on the account's private stream, as the venue sends it, read by the
        adapter's own parser: each event queued on the stream in order, then settled."""
        pushed = pp.classify(push(topic, *rows, created=T0_US // 1_000))
        assert isinstance(pushed, pp.Push)
        for event in pp.read_push(pushed, REF, now_us=T0_US):
            self.call(self.port.push, event)
        self.settle()

    def fill(
        self, order: dict[str, Any], exec_id: str, qty: str, *, seq: int, **fields: Any
    ) -> None:
        """The venue fills `qty` of the order: its position holds the order's native stop, and the
        fill is pushed on the account's stream."""
        row = self.row(order)
        self.venue_position(row, qty)
        self.deliver(FILLS, fill_row(row, exec_id, qty, seq=seq, **fields))


async def _settled(runtime: Any) -> None:
    parts = runtime._composed()
    for _ in range(4):
        await rt.settle()
        await parts.lane.call(parts.machines.idle())


def _text(value: Decimal) -> str:
    """`value` as the venue writes a number: no exponent, no trailing zeros."""
    return format(value.normalize(), "f")


def fill_row(order: OrderRow, exec_id: str, qty: str, *, seq: int, **fields: Any) -> dict[str, Any]:
    """A trade fill of the stored `order`, `qty` of it at its price, its fee the transcribed taker
    rate of its own value (derived); `fields` replace the row's members."""
    price, rate = order.price or Decimal(0), Decimal("0.00055")
    values: dict[str, Any] = {
        "orderId": order.exchange_order_id, "orderLinkId": order.order_link_id, "seq": seq,
        "execId": exec_id, "execQty": qty, "execPrice": _text(price), "side": order.side,
        "orderQty": _text(order.qty), "orderType": "Limit",
        "execFee": _text(Decimal(qty) * price * rate),
        "feeRate": str(rate), "isMaker": False, "execTime": str(T0_US // 1_000),
    }  # fmt: skip
    return linear_execution(**(values | fields))


def order_row(order: OrderRow, status: str, filled: str = "0", **fields: Any) -> dict[str, Any]:
    """The stored `order` as the stream's order topic shows it at `status`, `filled` of it
    executed (derived)."""
    left = order.qty - Decimal(filled) if status in ("New", "PartiallyFilled") else Decimal(0)
    values: dict[str, Any] = {
        "orderId": order.exchange_order_id, "orderLinkId": order.order_link_id, "side": order.side,
        "orderType": "Limit", "orderStatus": status, "price": _text(order.price or Decimal(0)),
        "timeInForce": "GTC", "qty": _text(order.qty), "cumExecQty": filled, "leavesQty": str(left),
        "createdTime": str(T0_US // 1_000), "updatedTime": str(T0_US // 1_000),
    }  # fmt: skip
    return linear_order(**(values | fields))


async def _until_ready(runtime: Any, oms: rt.World) -> None:
    await runtime.start()
    for flag in oms.flags:  # a fake flag view's first read
        flag.read()
    await asyncio.wait_for(runtime.wait_ready(), 20)


@contextmanager
def oms_world(bars_state_root: Path) -> Iterator[OmsWorld]:
    """The world, its bars builders' state under `bars_state_root` (pytest's temporary directory);
    its patches are undone and its runtime stopped however the caller ends."""
    with pytest.MonkeyPatch.context() as mp, start_blocking_portal() as portal:
        oms = Runtime(
            store=InMemoryOrderStore(lambda: rt.T0), venue=Venue(),
            tracked=rt.Tracked(accounts=frozenset({ACCOUNT})),
        )  # fmt: skip
        oms.accounts.append(TradingAccountRow(ACCOUNT, "demo", REF.uid, False, KEY))
        oms.store.seed_owner(user_id_of("owner"))  # the exit routes' scope, as the pack's Owner
        oms.store._environments[ACCOUNT] = "demo"
        held = sr.profile(ACCOUNT, allowed_symbols=list(SYMBOLS))
        profiles = sr.Profiles(held={(ACCOUNT, None): held, (ACCOUNT, held.profile_id): held})
        built: list[Any] = []

        def runtime(*_a: Any, topics: Any = None, feed: Any = None, **_kw: Any) -> Any:
            over = {} if feed is None else {"feed": feed}
            built.append(oms.runtime(topics=topics, profiles=profiles, **over))
            return built[0]

        mp.setattr(appmod, "build_oms_runtime", runtime)
        reads = OmsReads(rw.ReadStore(Reads(oms.store)), "demo")
        mp.setattr(appmod, "oms_reads", lambda _settings: reads)
        pack = build_world(mp, bars_state_root=bars_state_root)
        pack.client.portal = portal  # one loop for every request: the runtime's (CR-S3C2-01)
        pack.app.state.feature_flags.oms_enabled.value = True  # `trading.oms_enabled`, a read view
        saved, b01._ATTEMPTS = b01._ATTEMPTS, OrderedDict()
        [run] = built
        try:
            portal.call(_until_ready, run, oms)
            yield OmsWorld(pack, oms, run, portal)
        finally:
            portal.call(run.stop)
            b01._ATTEMPTS = saved
            pack.client.portal = None
