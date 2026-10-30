"""The position writes' OMS side (E29-T07 #915; 22 `closePosition`, `reversePosition` and
`closeAllPositions`, as amended by #5013; 21 Sec.3.3.10, 24 Sec.8.3 rule 1 and Sec.15.5).

The orders these routes send go through the submission pipeline (`oms.submit`) as `placeOrder`'s
do, with no pipeline step changed: the anchor's operation and ref ride on `SubmitContext`. This
module holds what the pipeline does not:

* **The orders' terms.** `close_request` is the reduce-only order of the opposite side, intent
  `flatten`, sized by the request's `fixed_qty` (a percent of the position's size, the whole size
  at 100 %, floored to the lot step by the pipeline); `entry_request` is a reversal's entry on the
  closed side's opposite, sized by the profile (C-12.5), its native stop the profile's (C-2.6).
  `reversal_refs(key)` names a reversal's two anchors, `uuid5(key, "close")` and
  `uuid5(key, "open")` (21 Sec.3.3.10).
* **The native-stop pre-check** (`PositionWrites.entry_stop_ready`): a reversal is refused before
  anything is sent when the account's effective profile cannot give its entry a stop. A profile
  always carries one (`ap_native_sl`), so the account must have a default profile; one that cannot
  be read is 503 `store_unavailable`, never an entry without a stop.
* **The fill wait** (`await_fill`): a reversal's close is confirmed filled by B1's own state, set
  from the execution, read on the plain view (`OrderMachines.settled`, never an interpreter,
  C-2.20), up to a deadline on the injected monotonic clock. A close still unfilled or partly
  filled at the deadline ends the reversal with no entry sent.
* **The Partial-mode sweep** (`sweep_after_close`, 22 `closePosition` at 100 %): the venue's
  flatten ends the position's own Full-mode stop; the closed size's Partial-mode conditionals are
  cancelled here, and only once the close is filled and the venue reads the position flat (C-2.6:
  never the protection of a position still open), and only those live before the fill was awaited:
  a stop placed after the close is never swept. Each cancel is recorded ahead
  (`position.closed`, reason `partial_stop_cancelled`) and never sent unrecorded. The sweep runs
  as a task the service tracks (C-2.18: at most `max_sweeps` at once), cancelled at `aclose`.

Every await is bounded. Logs carry ids, codes and state names, never a price, a size, the key or
the fingerprint (C-12.6).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Literal, Protocol
from uuid import UUID, uuid5

import structlog

from candleviewer.accounts.errors import AccountNotFoundError, ProfileUnavailableError
from candleviewer.domain.primitives import AccountId, Environment, Side, Symbol
from candleviewer.exchange.base.errors import ExchangeError, TransportError
from candleviewer.exchange.base.models import AccountRef, CancelOrderRequest, OrderAck, Position
from candleviewer.observability import spawn
from candleviewer.oms.errors import (
    RULE_NATIVE_STOP_REQUIRED,
    EnvironmentMismatch,
    FieldError,
    OrderInvalid,
    StoreUnavailable,
)
from candleviewer.oms.ports import (
    OrderType,
    Profiles,
    RequestRecord,
    SizingRequest,
    SubmitActor,
    SubmitAudit,
    TradingAccounts,
)
from candleviewer.oms.submit import OrderRequest
from candleviewer.storage.errors import StorageError
from candleviewer.storage.repositories.orders import TimeInForce
from candleviewer.storage.repositories.positions import PositionRow
from candleviewer.storage.repositories.recorded_stops import RecordedStopRow

__all__ = [
    "CLOSE_ACTION", "FLATTEN_ACTION", "MAX_SWEEPS", "REVERSE_ACTION", "REVERSE_WAIT_S",
    "SWEEP_WAIT_S", "CloseFill", "CloseTerms", "PositionWrites", "PositionWritesDeps",
    "close_request", "entry_request", "is_full_close", "reversal_refs",
]  # fmt: skip

#: 24 Sec.15.5 (ruling BQ-5): a close's record, a reversal's, and a close-all's per account.
CLOSE_ACTION: Final = "position.closed"
REVERSE_ACTION: Final = "position.reversed"
FLATTEN_ACTION: Final = "position.flattened"
#: A reversal's bounded wait for its close's fill, measured from the first request (22).
REVERSE_WAIT_S: Final = 2.0
#: How long a full close's sweep waits for the fill before it leaves the stops alone.
SWEEP_WAIT_S: Final = 10.0
#: Sweeps in flight at once (C-2.18); one more is not started, logged, and the venue's flatten
#: and reconciliation are left to end the conditionals.
MAX_SWEEPS: Final = 64
_STORE_TIMEOUT_S: Final = 5.0
_CALL_TIMEOUT_S: Final = 10.0
_HUNDRED: Final = Decimal(100)
_FINAL_UNFILLED: Final = frozenset({"cancelled", "rejected", "expired", "killed"})
#: A position's index on the other side in hedge mode; one-way stays 0.
_OTHER_IDX: Final[Mapping[int, Literal[0, 1, 2]]] = {0: 0, 1: 2, 2: 1}
_NO_STOP: Final = "The account's profile cannot give the entry a native stop, so nothing was sent."

CloseFill = Literal["filled", "partially_filled", "unfilled"]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class CloseTerms:
    """22 `ClosePositionRequest` once read: exactly one of `pct` and `qty` (the route checks)."""

    order_type: OrderType
    price: Decimal | None = None
    pct: Decimal | None = None
    qty: Decimal | None = None
    time_in_force: TimeInForce = "GTC"


def reversal_refs(key: UUID) -> tuple[UUID, UUID]:
    """A reversal's two anchors' refs (21 Sec.3.3.10): the close's, then the entry's."""
    return uuid5(key, "close"), uuid5(key, "open")


def _closing_side(row: PositionRow) -> Side:
    """The side that reduces the position: a long's is a sell."""
    if row.side == "Buy":
        return "sell"
    if row.side == "Sell":
        return "buy"
    raise ValueError("a flat position has no side to close")


def is_full_close(row: PositionRow, terms: CloseTerms) -> bool:
    """Whether the close takes the whole position (22: the venue's flatten, the sweep)."""
    if terms.pct is not None:
        return terms.pct == _HUNDRED
    return terms.qty is not None and terms.qty == row.size


def close_request(row: PositionRow, terms: CloseTerms) -> OrderRequest:
    """The close: reduce-only, the opposite side, intent `flatten`, on the position's own index;
    a percent of the size, the whole size at 100 % (the pipeline floors it to the lot step)."""
    if terms.pct is not None:
        qty = row.size if terms.pct == _HUNDRED else row.size * terms.pct / _HUNDRED
    elif terms.qty is not None:
        qty = terms.qty
    else:
        raise ValueError("a close names a percent or a quantity")
    return OrderRequest(
        account_id=AccountId(row.exchange_account_id), symbol=Symbol(row.symbol),
        side=_closing_side(row), order_type=terms.order_type,
        sizing=SizingRequest("fixed_qty", qty), intent="flatten", price=terms.price,
        time_in_force=terms.time_in_force, reduce_only=True, position_idx=row.position_idx,
    )  # fmt: skip


def entry_request(row: PositionRow, order_type: OrderType, price: Decimal | None) -> OrderRequest:
    """A reversal's entry: the closing side, sized by the profile (C-12.5), its stop the
    profile's (C-2.6, none named here); in hedge mode on the other index."""
    return OrderRequest(
        account_id=AccountId(row.exchange_account_id), symbol=Symbol(row.symbol),
        side=_closing_side(row), order_type=order_type, sizing=SizingRequest("profile"),
        intent="entry", price=price, position_idx=_OTHER_IDX[row.position_idx],
    )  # fmt: skip


class OrderStates(Protocol):
    """B1's facade as the fill wait reads it: the plain view, never an interpreter."""

    def state(self, order_id: UUID) -> tuple[str, str] | None: ...

    async def settled(
        self, account_id: UUID, order_id: UUID, *, leaving: str, timeout_s: float
    ) -> str: ...


class LiveStops(Protocol):
    async def live_for_key(
        self, account_id: UUID, symbol: str, position_idx: int
    ) -> tuple[RecordedStopRow, ...]: ...


class SweepPort(Protocol):
    """The trading port's two calls the sweep makes, on the account's own environment."""

    async def positions(self, account: AccountRef) -> Sequence[Position]: ...

    async def cancel_order(self, req: CancelOrderRequest) -> OrderAck: ...


@dataclass(frozen=True, slots=True)
class PositionWritesDeps:
    """The service's collaborators, each the instance the pipeline was built with."""

    accounts: TradingAccounts
    profiles: Profiles
    machines: OrderStates
    stops: LiveStops
    ports: Callable[[Environment], SweepPort]
    audit: SubmitAudit
    environment: Environment


@dataclass(frozen=True, slots=True)
class _Sweep:
    row: PositionRow
    order_id: UUID
    actor: SubmitActor
    request_id: UUID | None


class PositionWrites:
    """The pre-check, the fill wait, the correlation records and the sweep (module docstring)."""

    def __init__(
        self,
        deps: PositionWritesDeps,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        store_timeout_s: float = _STORE_TIMEOUT_S,
        call_timeout_s: float = _CALL_TIMEOUT_S,
        sweep_wait_s: float = SWEEP_WAIT_S,
        max_sweeps: int = MAX_SWEEPS,
    ) -> None:
        if min(store_timeout_s, call_timeout_s, sweep_wait_s) <= 0 or max_sweeps < 1:
            raise ValueError("every bound is above zero")
        self._deps, self._monotonic = deps, monotonic
        self._store_timeout_s, self._call_timeout_s = store_timeout_s, call_timeout_s
        self._sweep_wait_s, self._max_sweeps = sweep_wait_s, max_sweeps
        self._sweeps: set[asyncio.Task[None]] = set()

    def monotonic(self) -> float:
        """The injected clock every deadline here is measured on."""
        return self._monotonic()

    async def entry_stop_ready(self, account_id: AccountId) -> None:
        """The native-stop pre-check (module docstring): `OrderInvalid` (`native_stop_required`)
        when the account has no default profile, `StoreUnavailable` when it cannot be read."""
        try:
            async with asyncio.timeout(self._store_timeout_s):
                await self._deps.profiles.get_effective_profile(account_id, None)
        except AccountNotFoundError:
            stop = FieldError("stop_loss", RULE_NATIVE_STOP_REQUIRED, _NO_STOP)
            raise OrderInvalid(_NO_STOP, errors=(stop,)) from None
        except (TimeoutError, ProfileUnavailableError, StorageError) as exc:
            _log().warning("oms_reverse_profile_unread", failure=type(exc).__name__)
            raise StoreUnavailable from None

    async def await_fill(self, account_id: UUID, order_id: UUID, *, deadline: float) -> CloseFill:
        """The close's fill by `deadline` (module docstring): `filled` once B1 says so; else
        `partially_filled` when it was seen partly filled, `unfilled` otherwise."""
        seen = self._deps.machines.state(order_id)
        state = "submitting" if seen is None else seen[0]
        partial = False
        while True:
            if state == "filled":
                return "filled"
            partial = partial or state == "partially_filled"
            remaining = deadline - self._monotonic()
            if state in _FINAL_UNFILLED or remaining <= 0:
                break
            try:
                state = await self._deps.machines.settled(
                    account_id, order_id, leaving=state, timeout_s=remaining
                )
            except TimeoutError:
                break
            except Exception as exc:  # unread: never taken for a fill
                _log().warning("oms_close_fill_unread", order_id=str(order_id),
                               failure=type(exc).__name__)  # fmt: skip
                break
        return "partially_filled" if partial else "unfilled"

    async def record(self, record: RequestRecord) -> bool:
        """A correlation record (`position.closed`, `position.reversed`, `position.flattened`),
        written before the answer is returned; False, logged, when it did not land: each order
        the request sent already holds its own write-ahead record (C-2.9)."""
        try:
            async with asyncio.timeout(self._store_timeout_s):
                await self._deps.audit.write(record)
        except Exception as exc:  # the orders are sent and recorded; the answer stands
            _log().error("oms_position_record_unwritten", action=record.action,
                         failure=type(exc).__name__)  # fmt: skip
            return False
        return True

    async def sweep_after_close(
        self, row: PositionRow, order_id: UUID, *, actor: SubmitActor, request_id: UUID | None
    ) -> bool:
        """Start a full close's sweep (module docstring) as a tracked task; False when
        `max_sweeps` are in flight already (nothing started, logged)."""
        if len(self._sweeps) >= self._max_sweeps:
            _log().warning("oms_close_sweep_full", position_id=str(row.id))
            return False
        job = _Sweep(row, order_id, actor, request_id)
        task = spawn(self._sweep(job), name="oms-close-sweep")  # the request's context carried
        self._sweeps.add(task)
        task.add_done_callback(self._swept)
        return True

    def _swept(self, task: asyncio.Task[None]) -> None:
        self._sweeps.discard(task)
        if not task.cancelled() and task.exception() is not None:
            _log().error("oms_close_sweep_failed", failure=type(task.exception()).__name__)

    async def aclose(self) -> None:
        """Cancel the sweeps still in flight and wait for them to end."""
        tasks = list(self._sweeps)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _sweep(self, job: _Sweep) -> None:
        row = job.row
        account_id = AccountId(row.exchange_account_id)
        ids = {"position_id": str(row.id), "order_id": str(job.order_id)}
        # The stops that existed before the close was confirmed: only these are the closed
        # size's. One placed later (a new Partial-mode stop) is never swept (C-2.6).
        before = await self._live_stops(row)
        if before is None:
            _log().info("oms_close_sweep_skipped", **ids, reason="stops_unread")
            return
        deadline = self._monotonic() + self._sweep_wait_s
        fill = await self.await_fill(account_id, job.order_id, deadline=deadline)
        if fill != "filled":
            _log().info("oms_close_sweep_skipped", **ids, reason=fill)
            return
        account = await self._account(account_id)
        port = self._deps.ports(account.environment)
        if not await self._flat(port, account, row):  # C-2.6: never strip an open position
            _log().info("oms_close_sweep_skipped", **ids, reason="position_open")
            return
        live = await self._live_stops(row)
        if live is None:
            _log().info("oms_close_sweep_skipped", **ids, reason="stops_unread")
            return
        existed = {stop.id for stop in before}
        for stop in live:
            if stop.id not in existed:
                continue
            if stop.tpsl_mode == "Partial" and stop.exchange_order_id is not None:
                await self._cancel(port, account, job, stop, stop.exchange_order_id)

    async def _live_stops(self, row: PositionRow) -> tuple[RecordedStopRow, ...] | None:
        """The position key's live recorded stops, or None when they cannot be read in time."""
        try:
            async with asyncio.timeout(self._store_timeout_s):
                return await self._deps.stops.live_for_key(
                    row.exchange_account_id, row.symbol, row.position_idx
                )
        except Exception as exc:  # unread: nothing is cancelled on a guess
            _log().warning("oms_close_sweep_stops_unread", failure=type(exc).__name__)
            return None

    async def _flat(self, port: SweepPort, account: AccountRef, row: PositionRow) -> bool:
        """The venue's own read shows no size on the position's key; unread is not flat."""
        try:
            async with asyncio.timeout(self._call_timeout_s):
                read = await port.positions(account)
        except (TimeoutError, ExchangeError, TransportError) as exc:
            _log().warning("oms_close_sweep_unread", failure=type(exc).__name__)
            return False
        key = (row.symbol, row.position_idx)
        return not any((p.symbol, p.position_idx) == key and p.qty > 0 for p in read)

    async def _cancel(
        self, port: SweepPort, account: AccountRef, job: _Sweep, stop: RecordedStopRow,
        exchange_order_id: str,
    ) -> None:  # fmt: skip
        """One Partial-mode conditional's cancel, recorded ahead; never sent unrecorded."""
        detail: Mapping[str, str | None] = {
            "position_id": str(job.row.id), "close_order_id": str(job.order_id),
            "recorded_stop_id": str(stop.id), "kind": stop.kind,
            "environment": self._deps.environment,
        }  # fmt: skip
        record = RequestRecord(
            CLOSE_ACTION, job.row.exchange_account_id, "position", job.row.id, "success", "info",
            "partial_stop_cancelled", job.actor, detail, job.request_id,
        )  # fmt: skip
        if not await self.record(record):
            return
        cancel = CancelOrderRequest(
            account=account, symbol=Symbol(job.row.symbol), exchange_order_id=exchange_order_id
        )
        try:
            async with asyncio.timeout(self._call_timeout_s):
                await port.cancel_order(cancel)
        except (TimeoutError, ExchangeError, TransportError) as exc:  # gone already, or later
            _log().warning("oms_close_sweep_cancel_failed", recorded_stop_id=str(stop.id),
                           failure=type(exc).__name__)  # fmt: skip

    async def _account(self, account_id: AccountId) -> AccountRef:
        async with asyncio.timeout(self._store_timeout_s):
            account = await self._deps.accounts.trading_account(account_id)
        if account.environment != self._deps.environment:  # C-2.11: never another's port
            raise EnvironmentMismatch(
                order_environment=account.environment, route_environment=self._deps.environment
            )
        return account
