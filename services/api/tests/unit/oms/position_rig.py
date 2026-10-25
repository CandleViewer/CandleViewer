"""The position projection's test rig (E29-T05 #848, S5b): one recording double for every port of
`PositionProjection` (the facade's two methods, both stores, the readings, the counts and the
pager; S5c's recorded stops and order rows, empty unless a test scripts them). The tests run on
`VirtualTimeLoop` (`audit_waits`), whose clock is the projection's monotonic one: a scripted
`cost` passes fake seconds, a `hang` waits until a bound cuts it, and an await with no bound
raises `VirtualClockDeadlock` instead of hanging. No network, no sleeps."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.models import Position
from candleviewer.oms.ports import PositionKey, ProtectionReading
from candleviewer.oms.positions import PositionProjection
from candleviewer.oms.push_mapping import ForProtection, reading
from candleviewer.storage.repositories.orders import OrderRow
from candleviewer.storage.repositories.positions import (
    FutureDatedPositionError,
    NewPositionSnapshot,
    PositionRow,
    PositionSnapshotRow,
    PositionState,
)
from candleviewer.storage.repositories.recorded_stops import InForce, RecordedStopRow

ACCOUNT = AccountId(UUID(int=0xA))
OTHER = AccountId(UUID(int=0xB))
NOW_US = 1_760_000_000_000_000
WALL = datetime(2025, 10, 9, 12, tzinfo=UTC)


def position(**over: Any) -> Position:
    """An open long with no stop (an `SL_LOST` row) unless `over` says otherwise."""
    values: dict[str, Any] = {
        "account_id": ACCOUNT, "symbol": "BTCUSDT", "position_idx": 0, "side": "buy",
        "qty": Decimal("0.4"), "avg_entry_price": Decimal("61000.5"),
        "mark_price": Decimal("61010"), "liq_price": Decimal("50000"), "leverage": Decimal("10"),
        "unrealised_pnl": Decimal("4.2"), "cum_realised_pnl": Decimal("-1.25"),
        "take_profit": None, "stop_loss": None, "trailing_stop_distance": None,
        "updated_at": NOW_US + 123_456,
    }  # fmt: skip
    return Position(**(values | over))


def routed(p: Position) -> ForProtection:
    return ForProtection(PositionKey(p.account_id, p.symbol, p.position_idx), reading(p))


@dataclass
class Rig:
    """Scripted answers by port name; `upserts` are consumed one per upsert ("applied", "stale"
    or "dated"; "applied" once spent), `took` one per push (True once spent), `push_errors` one
    per delivery. `raises` and `hang` script any port's failure, `cost` its fake seconds,
    `yields` a one-turn pause."""

    ids: tuple[UUID, ...] = ()
    upserts: list[str] = field(default_factory=list)
    took: list[bool] = field(default_factory=list)
    push_errors: list[BaseException] = field(default_factory=list)
    raises: dict[str, BaseException] = field(default_factory=dict)
    hang: set[str] = field(default_factory=set)
    yields: set[str] = field(default_factory=set)  # one loop turn: a zero bound cuts them
    cost: dict[str, float] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    pushed: list[tuple[UUID, str, dict[str, Any]]] = field(default_factory=list)
    states: list[PositionState] = field(default_factory=list)
    snaps: list[NewPositionSnapshot] = field(default_factory=list)
    handed: list[tuple[PositionKey, ProtectionReading]] = field(default_factory=list)
    counts: list[str] = field(default_factory=list)
    pages: list[str] = field(default_factory=list)
    live: tuple[RecordedStopRow, ...] = ()
    stalled: asyncio.Event = field(default_factory=asyncio.Event)
    made: PositionProjection | None = None

    async def take(self, p: Position | None = None, *, account: UUID = ACCOUNT, **kw: Any) -> float:
        """One `take`, on the rig's projection (a new one when `kw` names ports); the fake
        seconds it took."""
        p = p or position()
        if kw or self.made is None:
            self.made = self.projection(**kw)
        loop = asyncio.get_running_loop()
        began = loop.time()
        await self.made.take(AccountId(account), p, routed(p))
        return loop.time() - began

    async def reapply(self) -> None:
        assert self.made is not None
        await self.made.reapply(ACCOUNT)

    def projection(self, **kw: Any) -> PositionProjection:
        ports = dict.fromkeys(("orders", "positions", "snapshots", "readings"), self)
        ports |= dict.fromkeys(("counts", "pager", "stops", "order_rows"), self)
        loop = asyncio.get_running_loop()
        clocks = {"monotonic": loop.time, "now": lambda: WALL}
        return PositionProjection(**(ports | clocks | kw))

    async def _hit(self, name: str) -> None:
        self.calls.append(name)
        if name in self.yields:
            await asyncio.sleep(0)
        if name in self.cost:
            await asyncio.sleep(self.cost[name])
        if name in self.hang:
            self.stalled.set()
            await asyncio.Event().wait()
        if name in self.raises:
            raise self.raises[name]

    def protecting(self, key: PositionKey) -> tuple[UUID, ...]:
        self.calls.append("protecting")
        if "protecting" in self.raises:
            raise self.raises["protecting"]
        return self.ids

    async def push_protection(
        self, account_id: UUID, order_id: UUID, event: str, payload: Any
    ) -> bool:
        self.pushed.append((order_id, event, dict(payload)))
        await self._hit("push")
        if self.push_errors:
            raise self.push_errors.pop(0)
        return self.took.pop(0) if self.took else True

    async def upsert(self, state: PositionState) -> PositionRow:
        self.states.append(state)
        await self._hit("upsert")
        answer = self.upserts.pop(0) if self.upserts else "applied"
        if answer == "dated":
            raise FutureDatedPositionError
        values = {f.name: getattr(state, f.name) for f in fields(state)}
        if answer == "stale":  # the stored row is later
            values["exchange_updated_ts"] = datetime(2099, 1, 1, tzinfo=UTC)
        now = datetime(2025, 10, 9, tzinfo=UTC)
        return PositionRow(**values, id=UUID(int=1), recv_ts=now, updated_at=now)

    async def append(self, snapshot: NewPositionSnapshot) -> PositionSnapshotRow:
        self.snaps.append(snapshot)
        await self._hit("append")
        values = {f.name: getattr(snapshot, f.name) for f in fields(snapshot)}
        return PositionSnapshotRow(**values, id=1, snap_ts=datetime(2025, 10, 9, tzinfo=UTC))

    async def take_reading(self, key: PositionKey, value: ProtectionReading) -> None:
        self.handed.append((key, value))
        await self._hit("take_reading")

    async def live_for_key(
        self, account_id: UUID, symbol: str, position_idx: int
    ) -> tuple[RecordedStopRow, ...]:
        await self._hit("live_for_key")
        return self.live

    async def put_in_force(self, account_id: UUID, rows: Any, *, in_force: Any, at: Any) -> InForce:
        await self._hit("put_in_force")
        return InForce(replaced=(), in_force=tuple(rows))

    async def end(self, account_id: UUID, rows: Any, *, at: Any) -> tuple[RecordedStopRow, ...]:
        await self._hit("end")
        return tuple(rows)

    async def get(self, account_id: UUID, order_id: UUID) -> OrderRow | None:
        await self._hit("get")
        return None

    def count(self, outcome: str) -> None:
        self.counts.append(outcome)
        if "count" in self.raises:
            raise self.raises["count"]

    def raise_alert(self, severity: str, summary: str, *, machine_kind: str) -> None:
        assert (severity, machine_kind) == ("page", "oms.positions")
        self.pages.append(summary)
        if "page" in self.raises:
            raise self.raises["page"]


def stamp(us: int) -> datetime:
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=us)
