"""A rig for the order submission pipeline (E29-T04 #913): `OrderSubmission` over the real B1
facade and the command port's rig (`command_rig`: a demo and a live `FakeTradingPort` routed by
environment, the in-memory stores), with recording doubles of its other ports. Shared by
`test_submit.py` and `test_submit_perf.py`."""

from __future__ import annotations

import asyncio
import json
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from prometheus_client import generate_latest

from candleviewer.accounts.errors import AccountNotFoundError
from candleviewer.accounts.profiles import AccountProfile
from candleviewer.accounts.trade_group_repository import TradeGroupRepository
from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import AccountId, Px, Symbol
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.commands import SUBMIT_TIMEOUT_S
from candleviewer.oms.fakes import InMemoryOrderStore, InMemorySubmissionStore
from candleviewer.oms.idempotency import AnchorService
from candleviewer.oms.order_link_allocator import OrderLinkIdAllocator, OrderLinkLookup
from candleviewer.oms.order_machine import OrderMachinePorts, OrderMachines
from candleviewer.oms.order_steps import OrderStepWriter
from candleviewer.oms.ports import (
    SizedOrder,
    SizingRequest,
    StopOffset,
    SubmissionPorts,
    SubmitActor,
)
from candleviewer.oms.repository import (
    ExecutionRepository,
    IdempotencyAnchorRepository,
    OrderEventRepository,
    SubmissionRepository,
)
from candleviewer.oms.routing import TradingRouter
from candleviewer.oms.submit import (
    OrderRequest,
    OrderSubmission,
    SubmissionDeps,
    SubmitContext,
    SubmitOutcome,
)
from candleviewer.oms.validator import Validator
from candleviewer.risk.models import RiskDecision
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.plugins import InMemoryMachineEventSink
from candleviewer.statechart.registry import Registry
from candleviewer.storage.repositories.trade_groups import (
    GroupPatch,
    LegPatch,
    LegStatus,
    TradeGroupLegRow,
    TradeGroupRow,
    TradeGroupStore,
    TradeGroupStoreStaleError,
)
from tests.unit.oms import command_rig as cr
from tests.unit.oms.order_rig import Pager, Publish

REGISTRY = Registry()
SYMBOL = cr.SYMBOL
USER = UUID("3a7c1e2d-5b40-4c6f-8e9a-1b2c3d4e5f60")
KEY = UUID("9b2f7c1e-4d3a-4f6b-8a0c-5e1d2c3b4a59")
SHA = "c0ffee" + "ab" * 29
REQUEST_ID = UUID("6f1d2c3b-4a59-4e68-8f7a-9b0c1d2e3f40")
SESSION = UUID("5e551011-0000-4000-8000-000000000002")
REFERENCE = Decimal("60000")
STOP = cr.STOP
TAKE_PROFIT = Decimal("64000")
QTY = Decimal("0.010")
ACTOR = SubmitActor(user_id=USER, role="owner", session_id=SESSION, ip="100.64.0.7")
_PROFILES = Path(__file__).resolve().parents[2] / "fixtures" / "profiles"


def instrument(**over: object) -> Instrument:
    base: dict[str, object] = {
        "symbol": SYMBOL, "base_coin": "BTC", "quote_coin": "USDT", "settle_coin": "USDT",
        "status": "trading", "contract_type": "linear_perpetual", "launch_time": 0,
        "tick_size": Decimal("0.1"), "price_scale": 1, "min_price": Decimal("0.1"),
        "max_price": Decimal("999999"), "qty_step": Decimal("0.001"),
        "min_order_qty": Decimal("0.001"), "max_order_qty": Decimal("100"),
        "max_mkt_order_qty": Decimal("50"), "min_notional": Decimal("5"),
        "max_leverage": Decimal("100"), "min_leverage": Decimal("1"),
        "leverage_step": Decimal("0.01"), "funding_interval_min": 480,
        "upper_funding_rate": Decimal("0.00375"), "lower_funding_rate": Decimal("-0.00375"),
        "copy_trading": False, "metadata_version": 1, "fetched_at": 0,
    }  # fmt: skip
    return Instrument.model_validate(base | over)


def profile(account_id: AccountId = cr.ACCOUNT, **over: Any) -> AccountProfile:
    """The `fixed_qty` fixture profile as the account's default, trading BTCUSDT."""
    raw = json.loads((_PROFILES / "fixed_qty.json").read_text(encoding="utf-8"))
    raw |= {"account_id": str(account_id), "is_default": True}
    return AccountProfile.model_validate(raw | over)


def entry(**over: Any) -> OrderRequest:
    """A limit buy entry of 0.010 BTCUSDT at 60000 with its stop at 58000 and its take-profit at
    64000, on the demo account."""
    base = OrderRequest(
        account_id=cr.ACCOUNT,
        symbol=SYMBOL,
        side="buy",
        order_type="limit",
        sizing=SizingRequest(mode="fixed_qty", qty=QTY),
        price=REFERENCE,
        stop_loss=StopOffset(unit="price", value=STOP),
        take_profit=StopOffset(unit="price", value=TAKE_PROFIT),
    )
    return replace(base, **over)


def flatten(**over: Any) -> OrderRequest:
    """A reduce-only market sell that flattens part of the account's long position."""
    base: dict[str, Any] = {
        "side": "sell", "order_type": "market", "price": None, "reduce_only": True,
        "intent": "flatten", "stop_loss": None, "take_profit": None,
    }  # fmt: skip
    return entry(**(base | over))


def context(**over: Any) -> SubmitContext:
    base = SubmitContext(actor=ACTOR, client_ref=KEY, request_sha256=SHA, request_id=REQUEST_ID)
    return replace(base, **over)


@dataclass
class Instruments:
    """`Instruments` over the instruments a test seeds; `refuse` raises instead."""

    listed: dict[str, Instrument] = field(default_factory=lambda: {SYMBOL: instrument()})
    refuse: BaseException | None = None

    async def instrument(self, symbol: Symbol) -> Instrument | None:
        await asyncio.sleep(0)
        if self.refuse is not None:
            raise self.refuse
        return self.listed.get(symbol)


@dataclass
class Prices:
    """`ReferencePrices` answering one price for every symbol; `refuse` raises instead."""

    price: Px | None = REFERENCE
    refuse: BaseException | None = None
    asked: list[str] = field(default_factory=list)

    async def reference_price(self, symbol: Symbol) -> Px | None:
        self.asked.append(symbol)
        await asyncio.sleep(0)
        if self.refuse is not None:
            raise self.refuse
        return self.price


@dataclass
class Profiles:
    """`Profiles` over the profiles a test seeds, the account's default under `None`; an account
    with none is `AccountNotFoundError`, as the cache answers it; `refuse` raises instead."""

    held: dict[tuple[UUID, UUID | None], AccountProfile] = field(
        default_factory=lambda: {(cr.ACCOUNT, None): profile()}
    )
    refuse: BaseException | None = None

    async def get_effective_profile(
        self, account_id: UUID, profile_id: UUID | None = None
    ) -> AccountProfile:
        await asyncio.sleep(0)
        if self.refuse is not None:
            raise self.refuse
        found = self.held.get((account_id, profile_id))
        if found is None:
            raise AccountNotFoundError("profile")
        return found


class Groups:
    """The trade-group store's two compare-and-sets (`update_leg`, `update_group`) over the
    in-memory order store's groups, which its first persists write, for `TradeGroupRepository`;
    `refuse` raises instead. The other methods are not the pipeline's."""

    def __init__(self, store: InMemoryOrderStore) -> None:
        self._store = store
        self.refuse: BaseException | None = None
        self.updates: list[tuple[str, object]] = []

    async def update_leg(
        self,
        group_id: UUID,
        leg_id: UUID,
        patch: LegPatch,
        *,
        expected_status: LegStatus | None = None,
    ) -> TradeGroupLegRow | None:
        await asyncio.sleep(0)
        if self.refuse is not None:
            raise self.refuse
        record = self._store._groups.get(group_id)
        leg = None if record is None else next((g for g in record.legs if g.id == leg_id), None)
        if record is None or leg is None:
            return None
        if expected_status is not None and leg.status != expected_status:
            raise TradeGroupStoreStaleError("stale")
        moved = replace(leg, **cast(dict[str, Any], patch.changes()))
        legs = tuple(moved if g.id == leg_id else g for g in record.legs)
        self._store._groups[group_id] = replace(record, legs=legs)
        self.updates.append(("leg", patch))
        return moved

    async def update_group(
        self,
        group_id: UUID,
        patch: GroupPatch,
        *,
        expected_status: str | None = None,
    ) -> TradeGroupRow | None:
        await asyncio.sleep(0)
        if self.refuse is not None:
            raise self.refuse
        record = self._store._groups.get(group_id)
        if record is None:
            return None
        if expected_status is not None and record.group.status != expected_status:
            raise TradeGroupStoreStaleError("stale")
        moved = replace(record.group, **cast(dict[str, Any], patch.changes()))
        self._store._groups[group_id] = replace(record, group=moved)
        self.updates.append(("group", patch))
        return moved


@dataclass
class ReadOnly:
    """The read-only gate (`validator.ReadOnlyCheck`)."""

    is_read_only: bool = False
    reason_code: str | None = None
    reason_text: str | None = None


@dataclass
class Sleeps:
    """The pipeline's sleep: each wait is recorded, never slept; `then` runs at each one."""

    waits: list[float] = field(default_factory=list)
    then: Callable[[], Awaitable[None]] | None = None

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)
        if self.then is not None:
            await self.then()
        await asyncio.sleep(0)


@dataclass
class Risk:
    """The interim risk gate, recording the order it was asked about (SR-E29-04)."""

    inner: Any
    seen: list[SizedOrder] = field(default_factory=list)

    def check(self, order: SizedOrder, *, profile: AccountProfile | None) -> RiskDecision:
        self.seen.append(order)
        decision: RiskDecision = self.inner.check(order, profile=profile)
        return decision


class FlakyLookup:
    """An `OrderLinkLookup` over the order store that answers "free" for the next `lies` ids it is
    asked about, whatever the store holds: the race rule 5's check cannot see (24 Sec.8.3)."""

    def __init__(self, store: InMemoryOrderStore, *, lies: int = 0) -> None:
        self._store = store
        self.lies = lies
        self.asked: list[str] = []

    async def exists(self, order_link_id: str) -> bool:
        self.asked.append(order_link_id)
        if self.lies > 0:
            self.lies -= 1
            return False
        return await self._store.link_id_taken(order_link_id)


@dataclass
class SubmitRig:
    """The pipeline and every double it was built over (`build_rig`)."""

    pipeline: OrderSubmission
    machines: OrderMachines
    port: cr.Rig
    instruments: Instruments
    prices: Prices
    profiles: Profiles
    groups: Groups
    read_only: ReadOnly
    sleeps: Sleeps
    risk: Risk
    lookup: FlakyLookup
    metrics: Metrics
    pager: Pager
    submissions: InMemorySubmissionStore
    #: Another pipeline over the same parts, with other keywords.
    make: Callable[..., OrderSubmission]

    @property
    def store(self) -> InMemoryOrderStore:
        return self.port.store

    def calls(self) -> list[str]:
        return [call.method for call in (*self.port.demo.calls, *self.port.live.calls)]

    async def submit(
        self, request: OrderRequest | None = None, ctx: SubmitContext | None = None
    ) -> SubmitOutcome:
        return await self.pipeline.submit(request or entry(), ctx or context())

    async def quiet(self) -> None:
        """Until the facade's turns settled every step an invoke's answer brought."""
        for _ in range(4):
            for _ in range(32):
                await asyncio.sleep(0)
            await self.machines.idle()

    def written(self) -> tuple[int, int, int, int]:
        """The orders, anchors, groups and recorded stops the store holds."""
        store = self.store
        return (len(store._orders), len(store._anchors), len(store._groups), len(store._stops))

    def records(self, action: str | None = None) -> list[cr.AnyRecord]:
        """The audit records written, in order, of `action` when given."""
        written = [record for record, _sent in self.port.audits.written]
        return [r for r in written if action is None or r.action == action]

    def count(self, name: str, **labels: str) -> float:
        lines = generate_latest(self.metrics.registry).decode().splitlines()
        wanted = [f'{key}="{value}"' for key, value in labels.items()]
        return sum(
            float(line.rsplit(" ", 1)[1])
            for line in lines
            if line.startswith(name + "{") and all(w in line for w in wanted)
        )


def build_rig(
    *,
    lies: int = 0,
    audit_timeout_s: float = 0.5,
    risk: Any = None,
    submit_timeout_s: float = SUBMIT_TIMEOUT_S,
    **pipeline_kwargs: Any,
) -> SubmitRig:
    """The pipeline over a fresh command-port rig and the real B1 facade; the caller stops the
    facade (`rigged`). The store holds each account the rig trades with in its environment
    (D-2B1-02), so `trg_tgl_env` refuses a leg outside its group's environment as on Postgres.
    `submit_timeout_s` is the command port's deadline on a `place`, which the pipeline's
    `place_wait_s` must outlast (D-2B2-01)."""
    port = cr.build_rig(submit_timeout_s=submit_timeout_s)
    store = port.store
    submissions = InMemorySubmissionStore(store, audit_timeout_s=audit_timeout_s)
    for account in (cr.ref(), cr.ref(cr.LIVE_ACCOUNT, "live")):  # the command rig's accounts
        submissions.seed_account(account)  # C-2.11
    writer = OrderStepWriter(
        port.orders,
        ExecutionRepository(store.executions),
        clock=lambda: cr.EPOCH + timedelta(microseconds=port.now.us),
        submissions=SubmissionRepository(submissions),
    )
    events = OrderEventRepository(store)
    pager = Pager()
    facade_ports = OrderMachinePorts(
        writer, port.orders, port.port, port.audits, Publish(), port.notices,
        InMemoryMachineEventSink(), events,
    )  # fmt: skip
    metrics = Metrics("dev")
    machines = OrderMachines(
        facade_ports, metrics=metrics, pager=pager, now_us=port.now, registry=REGISTRY
    )

    def now() -> datetime:
        return cr.EPOCH + timedelta(microseconds=port.now.us)

    ports = SubmissionPorts.interim(now=now)
    recording = Risk(risk if risk is not None else ports.risk_gate)
    ports = replace(ports, risk_gate=recording)
    instruments, prices, profiles = Instruments(), Prices(), Profiles()
    groups = Groups(store)
    read_only, sleeps = ReadOnly(), Sleeps()
    lookup = FlakyLookup(store, lies=lies)
    deps = SubmissionDeps(
        accounts=port.accounts,
        instruments=instruments,
        prices=prices,
        profiles=profiles,
        switches=port.switches,
        gate=port.gate,  # the command port's: the runtime has one gate
        audit=port.audits,
        groups=TradeGroupRepository(cast(TradeGroupStore, groups)),
    )
    make = partial(
        OrderSubmission,
        ports,
        deps,
        machines=machines,
        commands=port.port,
        allocator=OrderLinkIdAllocator(cast(OrderLinkLookup, lookup)),
        validator=Validator(read_only_gate=read_only),
        router=TradingRouter({"demo": port.demo, "live": port.live}, lane_waits=cr.LANE_WAITS),
        anchors=AnchorService(IdempotencyAnchorRepository(store.anchors), clock=now, timeout_s=2.0),
        clock_halt=port.halt,
        metrics=metrics,
        now=now,
        monotonic=port.monotonic,
        sleep=sleeps,
        pager=pager,
    )
    pipeline = make(**pipeline_kwargs)
    return SubmitRig(
        pipeline, machines, port, instruments, prices, profiles, groups, read_only, sleeps,
        recording, lookup, metrics, pager, submissions, make,
    )  # fmt: skip


@asynccontextmanager
async def rigged(**kwargs: Any) -> AsyncIterator[SubmitRig]:
    """A rig whose facade is stopped afterwards, with B1's command attempts its own (one facade
    per process)."""
    saved = b01._ATTEMPTS
    b01._ATTEMPTS = OrderedDict()
    rig = build_rig(**kwargs)
    try:
        yield rig
    finally:
        await rig.machines.stop()
        b01._ATTEMPTS = saved
