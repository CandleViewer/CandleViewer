"""The position projection and the protection readings (E29-T05 #848, S5b; 24-internal-schemas.md
Sec.8.12, 21-database-schema.md Sec.3.3.7 "Writes"). Plain code on the hot-path contract (C-2.20):
`PositionProjection.take` is the private-stream consumer's `PositionRows` seam. One position row
upserts `positions` and, when it applied, appends a `ws_push` snapshot; its protection reading
goes to each live order that protects the position (the facade's `push_protection`), and to
`ProtectionReadings` when none took it, never dropped (C-2.6). A row dated ahead of the clock is
refused by the store: it gives no reading until it applies, so it is logged, counted, paged once
and held, then applied again at the account's next row (or `reapply`, on the clock's re-sync).

**The recorded stops (S5c; 24 Sec.8.8 rule 6, 21 Sec.3.3.11).** An applied row is a complete read
the OMS applies, so it puts in force each pending Full-mode record it shows (the latest per kind;
never a trail, a Partial side or a `restore` row, which is E29-T06's complete read's) and ends
the records it shows flat: only a row whose side it shows
flat, answered (in force, or pending with `answered_at`), bound to its stop's order and not released
(so that order's pushes and fills pair through the binding, `ix_rs_exch_id`; an unbound record
stays live and matchable for a fired stop whose order push comes later, and `after_bind` ends it
once S6 binds it), and, for a pending entry's attach, whose entry filled and rests no more (a read
that fails keeps it). A row open on the record's side never ends it (C-2.6), and neither does a
position older than the record (SEC-S5C-01): one dated more than the store's `MAX_FUTURE_SKEW`
before the record's `in_force_at` (else `answered_at`, else `created_at`) cannot show a reduction
since its write (24 Sec.8.8 rule 6). A lost compare-and-set reads the key again,
`MAX_RECORD_ATTEMPTS` in all; nothing acts on a refused write. `after_bind` decides with the key's
last APPLIED row, which a failed or refused push, or a gap in the stream, leaves behind the
exchange: the E29-T06 carry is that a complete REST read applied through the projection refreshes
it (or runs the hook itself), else `after_bind` decides on a stale push after every reconnect.

**Episodes.** A lost stop no live order took and `ProtectionReadings` refused pages P1 once per
episode; the episode ends when a reading of the position is handed on (an order took it, or
`ProtectionReadings` did) or at its next `SL_OBSERVED`, and `REPAGE_AFTER` more takes of the key
that hand nothing on page it again, so an episode never hides a lasting failure.
`oldest_unhanded_age_s` reads the oldest key whose reading is owed (unhanded, held or evicted) for
readiness.

**The Partial-mode residual** (#4413): a stop held only by a Partial-mode order is not on the
position row, so its reading is `SL_LOST`: a live order in `sl_present` records it, and a position
no live order protects pages through `NoPositionProtection` once per episode, until E32-T02's B8
reads the orders.

**Bounds (C-2.18).** Every await is bounded on the monotonic clock: each store call and the
fallback `take_reading` by `PORT_TIMEOUT_S`; the readings by ONE `PUSH_TIMEOUT_S` deadline across
every protecting order's push; the fallback never draws on that deadline, so a hung push cannot
starve it. The held rows' re-apply shares ONE `REAPPLY_BOUND_S` deadline, every call of it inside;
a row whose reads that deadline ends is held again for a later take, never handed on as unprotected.
The record hook and the snapshot share ONE `AFTER_BOUND_S` deadline, the hook capped at
`RECORD_BOUND_S` of it, so the snapshot keeps the rest. The worst case of one `take` is
`TAKE_BUDGET_S` = re-apply 4 s + upsert 5 s + readings 30 s + fallback 5 s + hook and snapshot
5 s = 49 s, under the consumer's own 50 s bound on `take`. It raises
nothing but `CancelledError`, which would end the account's stream as a defect. Logs carry ids,
the symbol, a kind and an outcome only: never a price, a size or a PnL (C-12.6)."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal, Protocol
from uuid import UUID

import structlog

from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.models import Position
from candleviewer.storage.repositories.orders import OPEN_STATES, OrderRow
from candleviewer.storage.repositories.positions import (
    MAX_FUTURE_SKEW,
    FutureDatedPositionError,
    NewPositionSnapshot,
    PositionRow,
    PositionSnapshotRow,
    PositionState,
)
from candleviewer.storage.repositories.recorded_stops import (
    InForce,
    RecordedStopRow,
    StaleRecordedStop,
)

from .errors import OrderStepUnknown, ProtectionReadingsUnavailable
from .ports import PositionKey, ProtectionReadings
from .push_mapping import ForProtection, reading_payload
from .stop_shown import full_shows, position_state
from .stream_push import PORT_TIMEOUT_S, PUSH_TIMEOUT_S, Pager

MAX_REFUSED: Final = 256  # future-dated rows held, the latest per key, the oldest evicted
MAX_EPISODES: Final = 4096  # keys with a paged lost stop: the oldest dropped is a repeat page
MAX_REAPPLY_PER_TAKE: Final = 4
REAPPLY_BOUND_S: Final = 4.0  # one deadline across a take's re-applied rows
AFTER_BOUND_S: Final = PORT_TIMEOUT_S  # one deadline for the record hook and the snapshot
RECORD_BOUND_S: Final = 3.0  # the hook's share of it: the snapshot keeps 2 s at least
MAX_RECORD_ATTEMPTS: Final = 3  # reads of a key whose write lost its compare-and-set (C-2.18)
MAX_KEPT: Final = 4096  # the last applied position per key, for `after_bind`
#: Takes of a key that hand nothing on, after its episode's page, before it pages again: a lasting
#: failure pages again within three more rows of the position, and one blip pages once.
REPAGE_AFTER: Final = 3
TAKE_BUDGET_S: Final = (
    REAPPLY_BOUND_S + PORT_TIMEOUT_S + PUSH_TIMEOUT_S + PORT_TIMEOUT_S + AFTER_BOUND_S
)

type Outcome = Literal[
    "foreign_row", "invalid", "applied", "stale", "future_dated", "refused_evicted", "reapplied",
    "store_failed", "push_unknown", "push_failed", "to_protection", "reading_unavailable",
    "reading_failed", "snapshot_failed", "lost_repaged", "record_stale", "record_failed",
    "order_read_failed", "after_bind_unknown", "record_newer_than_read",
]  # fmt: skip
type _Stored = Literal["applied", "stale", "invalid", "failed", "dated"]
#: Where a reading went: `took` (a live order) and `taken` (`ProtectionReadings`) hand it on;
#: `unavailable` and `failed` are a refused or failed fallback; `cut`, the shared deadline.
type _HandOn = Literal["took", "taken", "unavailable", "failed", "cut"]

_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
_SIDES: Final[Mapping[str | None, Literal["Buy", "Sell", "None"]]] = {
    "buy": "Buy", "sell": "Sell", None: "None"
}  # fmt: skip


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class ProtectingOrders(Protocol):  # the facade, structurally
    def protecting(self, key: PositionKey) -> tuple[UUID, ...]: ...

    async def push_protection(
        self, account_id: UUID, order_id: UUID, event: str, payload: Mapping[str, Any]
    ) -> bool: ...


class PositionWrites(Protocol):
    async def upsert(self, state: PositionState) -> PositionRow: ...


class SnapshotWrites(Protocol):
    async def append(self, snapshot: NewPositionSnapshot) -> PositionSnapshotRow: ...


class PositionCounts(Protocol):
    def count(self, outcome: Outcome) -> None: ...  # sync; S8 binds a catalogue series


class RecordedStops(Protocol):  # the recorded stops' M14 facade, structurally; no write-ahead hook
    async def live_for_key(
        self, account_id: UUID, symbol: str, position_idx: int
    ) -> tuple[RecordedStopRow, ...]: ...

    async def put_in_force(
        self, account_id: UUID, rows: Sequence[RecordedStopRow], *,
        in_force: Sequence[RecordedStopRow], at: datetime,
    ) -> InForce: ...  # fmt: skip

    async def end(
        self, account_id: UUID, rows: Sequence[RecordedStopRow], *, at: datetime
    ) -> tuple[RecordedStopRow, ...]: ...


class WallClock(Protocol):
    """The time of each record write (`at`): aware UTC, exchange-synced (S8 binds it). A naive
    time makes the store refuse every write (`require_aware`): counted `record_failed`."""

    def __call__(self) -> datetime: ...


class OrderRows(Protocol):
    async def get(self, account_id: UUID, order_id: UUID) -> OrderRow | None: ...


@dataclass(frozen=True, slots=True)
class _Held:
    position: Position
    route: ForProtection
    stored: bool = False  # its store step decided: only its reading is owed


class PositionProjection:
    def __init__(
        self, *, orders: ProtectingOrders, positions: PositionWrites, snapshots: SnapshotWrites,
        readings: ProtectionReadings, counts: PositionCounts, pager: Pager,
        stops: RecordedStops, order_rows: OrderRows, monotonic: Callable[[], float],
        now: WallClock,
    ) -> None:  # fmt: skip
        self._orders, self._positions, self._snapshots = orders, positions, snapshots
        self._readings, self._counts, self._pager, self._now = readings, counts, pager, monotonic
        self._stops, self._order_rows, self._clock = stops, order_rows, now
        self._held: OrderedDict[PositionKey, _Held] = OrderedDict()
        self._dated: OrderedDict[PositionKey, None] = OrderedDict()  # paged, not yet applied
        #: paged, nothing handed on since: the takes since its last page
        self._lost: OrderedDict[PositionKey, int] = OrderedDict()
        #: whose reading is owed (unhanded, held or evicted), since when (monotonic), oldest first
        self._unhanded: OrderedDict[PositionKey, float] = OrderedDict()
        self._last: OrderedDict[PositionKey, Position] = OrderedDict()  # the last applied row

    async def take(self, account_id: AccountId, position: Position, route: ForProtection) -> None:
        """One position row of the account's stream (24 Sec.8.12), in arrival order."""
        key = route.key
        if key.account_id != account_id or position.account_id != account_id:
            _log().error("position_foreign_row", stream_account_id=str(account_id), **_ids(key))
            self._count("foreign_row")  # defence in depth: the adapter binds rows per account
            return
        self._held.pop(key, None)  # this newer row supersedes a held one
        await self._reapply(account_id, MAX_REAPPLY_PER_TAKE)
        await self._apply(_Held(position, route), None)

    async def reapply(self, account_id: AccountId) -> None:
        """Every held row of the account, oldest first, under one deadline (S8 calls it on the
        clock's re-sync); a row it does not reach stays held."""
        await self._reapply(account_id, MAX_REFUSED)

    async def after_bind(self, key: PositionKey) -> None:
        """S6 calls it after its first bind of a recorded stop of the key: the record hook with
        the last applied position, so a fired Full-mode stop whose flat push came first ends once
        its order is bound. Nothing kept for the key: counted, nothing done. Raises nothing but
        `CancelledError`."""
        last = self._last.get(key)
        if last is None:
            _log().info("position_after_bind_unknown", **_ids(key))
            self._count("after_bind_unknown")
            return
        await self._hooks(last, key, self._now() + RECORD_BOUND_S)

    def last_applied(self, key: PositionKey) -> Position | None:
        """The key's last applied position row, or None when none is kept (S6b sizes a Full-mode
        stop's row whose order shows a quantity of 0 from it, 24 Sec.8.3 rule 7)."""
        return self._last.get(key)

    def oldest_unhanded_age_s(self) -> float:
        """Readiness (S8 binds a gauge and `/readyz`): the age, in seconds, of the oldest key whose
        reading is owed: not handed on, held as future-dated, or evicted from that hold; 0.0 when
        none is."""
        for since in self._unhanded.values():
            return max(self._now() - since, 0.0)
        return 0.0

    async def _reapply(self, account_id: AccountId, most: int) -> None:
        until = self._now() + REAPPLY_BOUND_S
        for key in [k for k in self._held if k.account_id == account_id][:most]:
            if self._now() >= until:
                return
            held = self._held.pop(key, None)
            if held is None:  # a newer row of the key took its place meanwhile
                continue
            try:
                handed = await self._apply(held, until)
            except asyncio.CancelledError:  # a cancel never drops a held row (C-2.6)
                self._held.setdefault(key, held)
                raise
            if handed:
                self._count("reapplied")

    async def _apply(self, held: _Held, until: float | None) -> bool:
        """Steps 3-7 for one row; True once its reading was handed on. A re-applied row whose
        reading was not is held again, its store step kept."""
        key, stored, applied = held.route.key, held.stored, False
        if not stored:
            outcome = await self._store(held.position, key, until)
            if outcome == "dated":  # C2: no reading, no snapshot until it applies
                self._hold(key, held)
                return False
            stored, applied = outcome != "failed", outcome == "applied"
            if applied:
                self._keep(key, held.position)
            if until is not None and self._now() >= until:
                # the shared deadline is spent: no read at zero; the row is held again
                if applied:  # its `ws_push` snapshot is not appended again on the re-apply
                    self._count("snapshot_failed")
                self._hold(key, replace(held, stored=stored))
                return False
        handed = await self._read(held.route, until)
        if applied:  # the hook and the snapshot share one deadline; the hook a part of it
            after = self._now() + self._left(AFTER_BOUND_S, until)
            await self._hooks(held.position, key, min(after, self._now() + RECORD_BOUND_S))
            await self._snapshot(held.position, key, after)
        if until is not None and not handed:
            self._hold(key, replace(held, stored=stored))
        return handed

    async def _store(self, p: Position, key: PositionKey, until: float | None) -> _Stored:
        try:
            state = _state(p)
        except Exception as exc:  # `check_fields`: the reading still goes (C-2.6)
            _log().error("position_invalid", kind=type(exc).__name__, **_ids(key))
            self._count("invalid")
            return "invalid"
        try:
            row = await self._bounded(self._positions.upsert(state), PORT_TIMEOUT_S, until)
        except FutureDatedPositionError:
            _log().error("position_future_dated", **_ids(key))
            self._count("future_dated")
            if key not in self._dated:  # once per key until it applies
                _latch(self._dated, key, None, MAX_REFUSED)
                self._page("a position push is dated ahead of the clock: clock fault")
            return "dated"
        except Exception as exc:  # a failure or the bound: the reading still goes
            _log().error("position_store_failed", kind=type(exc).__name__, **_ids(key))
            self._count("store_failed")
            return "failed"
        if row.exchange_updated_ts != state.exchange_updated_ts:
            self._count("stale")  # B1 judges the reading by exchange time itself (INV-B1-f)
            return "stale"
        self._dated.pop(key, None)
        self._count("applied")
        return "applied"

    async def _read(self, route: ForProtection, until: float | None) -> bool:
        """C3, and the episode: True unless the reading is still owed (a failed fallback, or the
        shared deadline cut it)."""
        key, value = route.key, route.reading
        if value.event == "SL_OBSERVED":  # the episode ends, wherever the reading goes
            self._lost.pop(key, None)
        how = await self._hand_on(route, until)
        if how in ("took", "taken"):  # handed on: the episode ends (the 12:45Z condition)
            self._lost.pop(key, None)
            self._unhanded.pop(key, None)
        else:
            self._owed(key)
            if how != "cut":  # a cut is held for the next take, never paged as a loss
                self._episode(key, value.event)
        return how not in ("failed", "cut")

    async def _hand_on(self, route: ForProtection, until: float | None) -> _HandOn:
        """Each protecting order takes the reading under one deadline; none took it, then
        `ProtectionReadings` under its own bound."""
        key, value = route.key, route.reading
        payload = reading_payload(value)
        deadline = self._now() + self._left(PUSH_TIMEOUT_S, until)
        took = False
        for order_id in self._protecting(key):
            took = await self._push(key, order_id, value.event, payload, deadline) or took
        if took:
            return "took"
        if until is not None and self._now() >= until:
            # the shared re-apply deadline ended the pushes: the reading is owed to a live order,
            # so the row is held again, never handed to `ProtectionReadings` as unprotected
            return "cut"
        self._count("to_protection")
        try:
            await self._bounded(self._readings.take_reading(key, value), PORT_TIMEOUT_S, until)
        except ProtectionReadingsUnavailable:
            _log().error("position_reading_unavailable", reading=value.event, **_ids(key))
            self._count("reading_unavailable")
            return "unavailable"
        except Exception as exc:  # fail closed: a lost stop no one took pages
            _log().error("position_reading_failed", kind=type(exc).__name__, **_ids(key))
            self._count("reading_failed")
            return "failed"
        return "taken"

    def _protecting(self, key: PositionKey) -> tuple[UUID, ...]:
        try:
            return self._orders.protecting(key)
        except Exception as exc:
            _log().error("position_push_failed", kind=type(exc).__name__, **_ids(key))
            self._count("push_failed")
            return ()

    async def _push(
        self, key: PositionKey, order_id: UUID, event: str, payload: Mapping[str, Any],
        deadline: float,
    ) -> bool:  # fmt: skip
        for attempt in (1, 2):  # an unknown outcome is delivered once more (24 Sec.8.12)
            try:
                async with asyncio.timeout(max(deadline - self._now(), 0.0)):
                    return await self._orders.push_protection(
                        key.account_id, order_id, event, payload
                    )
            except OrderStepUnknown:
                if attempt == 2:
                    _log().error("position_push_unknown", order_id=str(order_id), **_ids(key))
                    self._count("push_unknown")
            except Exception as exc:  # refused, illegal, an anomaly, the deadline: not taken
                kind = type(exc).__name__
                _log().error("position_push_failed", kind=kind, order_id=str(order_id), **_ids(key))
                self._count("push_failed")
                return False
        return False

    async def _hooks(self, p: Position, key: PositionKey, until: float) -> None:
        """Step 6 (C4, C5) for an applied position `p` of `key`: a pass over the key's live
        records; a lost compare-and-set reads them again, `MAX_RECORD_ATTEMPTS` in all, then
        leaves them to the next applied row or E29-T06's pass. Raises nothing but
        `CancelledError`."""
        for attempt in range(1, MAX_RECORD_ATTEMPTS + 1):
            try:
                await self._hook_pass(p, key, until)
                return
            except StaleRecordedStop:
                if attempt == MAX_RECORD_ATTEMPTS:
                    _log().warning("position_record_stale", **_ids(key))
                    self._count("record_stale")
            except Exception as exc:  # a store failure, its bound, a `check_*` refusal
                _log().error("position_record_failed", kind=type(exc).__name__, **_ids(key))
                self._count("record_failed")
                return

    async def _hook_pass(self, p: Position, key: PositionKey, until: float) -> None:
        """One fresh read and its decision: the rows `p` shows flat end first, then the pending
        Full rows it shows go in force over the rows in force that are left."""
        account, place = key.account_id, (key.account_id, key.symbol, key.position_idx)
        read = await self._bounded(
            self._stops.live_for_key(account, key.symbol, key.position_idx), PORT_TIMEOUT_S, until
        )
        rows = [r for r in read if (r.exchange_account_id, r.symbol, r.position_idx) == place]
        ending = [r for r in rows if await self._ends(r, p, key, until)]
        if ending:
            await self._bounded(
                self._stops.end(account, ending, at=self._clock()), PORT_TIMEOUT_S, until
            )
        gone = {r.id for r in ending}
        shown = _shown(rows, p)
        if shown:
            seen = [r for r in rows if r.status == "in_force" and r.id not in gone]
            await self._bounded(
                self._stops.put_in_force(account, shown, in_force=seen, at=self._clock()),
                PORT_TIMEOUT_S, until,
            )  # fmt: skip

    async def _ends(self, r: RecordedStopRow, p: Position, key: PositionKey, until: float) -> bool:
        """C5: whether the applied position `p` ends the live record `r`."""
        if position_state(r, p) != "flat":  # (a) open on its side: never ended (C-2.6)
            return False
        if not (r.status == "in_force" or (r.status == "pending" and r.answered_at is not None)):
            return False  # (b) an unanswered row never ends
        if r.exchange_order_id is None or r.released_at is not None:
            return False  # (c) unbound: matchable for a fired stop's later order push
        if _stamp(p) < (r.in_force_at or r.answered_at or r.created_at) - MAX_FUTURE_SKEW:
            _log().warning("position_record_newer_than_read", record_id=str(r.id), **_ids(key))
            self._count("record_newer_than_read")
            return False  # (e) the record postdates the read: it cannot show it flat (C-2.6)
        if r.status == "pending" and r.source == "entry_attach":
            return await self._entry_done(r, key, until)  # (d)
        return True

    async def _entry_done(self, r: RecordedStopRow, key: PositionKey, until: float) -> bool:
        """(d) the entry filled and rests no more (`WAITING_ENTRY` needs a zero count); a read
        that fails, is cut or finds no row decides nothing: the record is kept (fail closed)."""
        if r.order_id is None:
            return False
        try:
            order = await self._bounded(
                self._order_rows.get(key.account_id, r.order_id), PORT_TIMEOUT_S, until
            )
        except Exception as exc:
            kind, order_id = type(exc).__name__, str(r.order_id)
            _log().error("position_order_read_failed", kind=kind, order_id=order_id, **_ids(key))
            self._count("order_read_failed")
            return False
        return order is not None and order.cum_exec_qty > 0 and order.state not in OPEN_STATES

    async def _snapshot(self, p: Position, key: PositionKey, until: float | None) -> None:
        try:
            snap = NewPositionSnapshot(
                exchange_account_id=p.account_id, symbol=p.symbol, size=p.qty, reason="ws_push",
                position_idx=p.position_idx, avg_price=p.avg_entry_price, mark_price=p.mark_price,
                unrealised_pnl=p.unrealised_pnl, cum_realised_pnl=p.cum_realised_pnl,
                liq_price=p.liq_price,
            )  # fmt: skip
            await self._bounded(self._snapshots.append(snap), PORT_TIMEOUT_S, until)
        except Exception as exc:
            _log().error("position_snapshot_failed", kind=type(exc).__name__, **_ids(key))
            self._count("snapshot_failed")

    def _hold(self, key: PositionKey, held: _Held) -> None:
        """Hold `held` for a later take, unless a newer row of the key is held or applied
        (SEC-S5B-06: a re-apply racing a take never puts the older row back)."""
        at, kept, last = held.position.updated_at, self._held.get(key), self._last.get(key)
        if (kept is not None and kept.position.updated_at > at) or (
            last is not None and last.updated_at > at
        ):
            _log().info("position_hold_superseded", **_ids(key))
            return
        self._owed(key)  # an evicted row stays owed: the gauge shows it (SEC-S5B-05)
        self._held.pop(key, None)
        self._held[key] = held
        if len(self._held) > MAX_REFUSED:
            old, _ = self._held.popitem(last=False)
            _log().error("position_refused_evicted", **_ids(old))
            self._count("refused_evicted")

    def _episode(self, key: PositionKey, event: str) -> None:
        """P1 once per episode of a lost stop handed nothing on, and again after `REPAGE_AFTER`
        more such takes of the key."""
        if event != "SL_LOST":
            return
        since = self._lost.get(key)
        if since is not None and since + 1 < REPAGE_AFTER:
            self._lost[key] = since + 1
            return
        if since is not None:
            self._count("lost_repaged")
        _latch(self._lost, key, 0, MAX_EPISODES)
        self._page("a position lost its stop and no machine protects it")

    def _owed(self, key: PositionKey) -> None:
        """The key's reading is owed from now, unless it was already; full, the oldest are kept,
        as the gauge reads the oldest."""
        if key not in self._unhanded and len(self._unhanded) < MAX_EPISODES:
            self._unhanded[key] = self._now()

    def _keep(self, key: PositionKey, p: Position) -> None:
        self._last.pop(key, None)
        self._last[key] = p
        if len(self._last) > MAX_KEPT:
            self._last.popitem(last=False)

    def _left(self, seconds: float, until: float | None) -> float:
        return max(seconds if until is None else min(seconds, until - self._now()), 0.0)

    async def _bounded[T](self, call: Awaitable[T], seconds: float, until: float | None) -> T:
        async with asyncio.timeout(self._left(seconds, until)):
            return await call

    def _count(self, outcome: Outcome) -> None:
        try:
            self._counts.count(outcome)
        except Exception as exc:
            _log().error("position_count_failed", kind=type(exc).__name__, outcome=outcome)

    def _page(self, summary: str) -> None:
        try:
            self._pager.raise_alert("page", summary, machine_kind="oms.positions")
        except Exception as exc:
            _log().error("position_page_failed", kind=type(exc).__name__)


def _state(p: Position) -> PositionState:
    """The `positions` row of a pushed position; the stamp from integer microseconds."""
    return PositionState(
        exchange_account_id=p.account_id, symbol=p.symbol, size=p.qty,
        position_idx=p.position_idx, side=_SIDES[p.side], avg_price=p.avg_entry_price,
        leverage=p.leverage, mark_price=p.mark_price, liq_price=p.liq_price,
        unrealised_pnl=p.unrealised_pnl, cum_realised_pnl=p.cum_realised_pnl,
        take_profit=p.take_profit, stop_loss=p.stop_loss, trailing_stop=p.trailing_stop_distance,
        exchange_updated_ts=_stamp(p),
    )  # fmt: skip


def _stamp(p: Position) -> datetime:
    """The position's exchange time, from integer microseconds (`exchange_updated_ts`)."""
    return _EPOCH + timedelta(microseconds=p.updated_at)


#: The sources a position push puts in force (the orchestrator's Q2 ruling, 2026-10-25).
_PUT_SOURCES: Final = frozenset({"entry_attach", "trading_stop"})


def _shown(rows: Sequence[RecordedStopRow], p: Position) -> tuple[RecordedStopRow, ...]:
    """C4: the pending Full rows `p` shows (`full_shows`: never a trail, never a Partial side,
    which S6's materialised row shows), the latest (`created_at`, then `id`) per kind. Only an
    entry's attach and a trading-stop row: a `restore` row's read is E29-T06's complete read."""
    latest: dict[str, RecordedStopRow] = {}
    for r in sorted(rows, key=lambda r: (r.created_at, r.id)):
        if r.status == "pending" and r.source in _PUT_SOURCES and full_shows(r, p):
            latest[r.kind] = r
    return tuple(latest.values())


def _latch[V](keys: OrderedDict[PositionKey, V], key: PositionKey, value: V, cap: int) -> None:
    keys[key] = value
    if len(keys) > cap:
        keys.popitem(last=False)


def _ids(key: PositionKey) -> dict[str, object]:  # ids and the symbol only (C-12.6)
    return {
        "account_id": str(key.account_id), "symbol": key.symbol, "position_idx": key.position_idx
    }  # fmt: skip
