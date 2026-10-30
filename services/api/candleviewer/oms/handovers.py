"""The OMS's hand-overs to the next reconciliation pass (E29-T06 #914 PR 1; 24 Sec.8.3 rule 7,
Sec.8.5 steps 2, 3c and 3d; 21 Sec.3.3.12).

`StoreHandovers` serves the two ports the writers of `oms_handovers` take, `OrderHandovers` (a
lookup of the command port, E29-T04) and `ExecutionHandovers` (the private-stream consumer,
E29-T05), over the `OmsHandoverStore`, one instance per writer, its `source` the writer's. It keeps
the normalised order or execution as its JSON record, under the account the port names, and
refuses a record that names another account (C-2.11). Every refusal is the ports'
`HandoverUnavailable`, logged at ERROR and never silent: a record of another account, the store
full at its bound (21 Sec.3.3.12's overflow policy), an outage, a refused statement, or a store
that does not answer within `HANDOVER_TIMEOUT_S`. The callers log and count it (24 Sec.8.12
step 4); cancellation passes through.

The pass reads the entries back as their models (`waiting_orders`, `waiting_executions`), each
with its id, and an execution with its empty reads and decision (24 Sec.8.5 step 3d). An entry
that no longer reads as its model is logged and answered by its id alone (`HandoverRead.unreadable`,
never its record), for the report's `errors` (`handover_unreadable`, a standing item), so one row
never ends the read (BQ-18) and none is skipped silently. `decide` and `prune` are the store's, for
the account.

Not bound: `NoHandoverStore` stays the one production binding until E29-T06's wiring replaces it,
so nothing here runs in production yet.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, TypeVar

import structlog
from pydantic import ValidationError

from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.models import Execution, Order
from candleviewer.storage.errors import StorageQueryFailed, StorageTierUnavailable
from candleviewer.storage.repositories.oms_handovers import (
    HandoverKind,
    HandoverSource,
    HandoverStoreFull,
    NewHandover,
    OmsHandoverStore,
)
from candleviewer.storage.repositories.orders import OrderConstraintError

from .errors import HandoverUnavailable

#: Seconds each store call may take, the OMS statement cap's default (`CV_OMS_STATEMENT_TIMEOUT_MS`,
#: 2 s): past it the call is `HandoverUnavailable`, as the pool wait is outside that cap (C-2.18).
HANDOVER_TIMEOUT_S: Final = 2.0
#: The store's failures, each a `HandoverUnavailable` here, never chained (C-12.6).
_STORE_FAILURES: Final = (
    StorageTierUnavailable,
    StorageQueryFailed,
    OrderConstraintError,
    TimeoutError,
)
_T = TypeVar("_T")


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class HandoverRead[E]:
    """What a read of the account's hand-overs answers: the entries that read as their model, and
    the ids of those that do not (24 Sec.8.5, `handover_unreadable`), which stay in the table."""

    entries: tuple[E, ...]
    unreadable: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class WaitingOrder:
    """An order handed to the pass (24 Sec.8.5 step 3c), with its entry's id for the prune."""

    entry_id: int
    order: Order


@dataclass(frozen=True, slots=True)
class WaitingExecution:
    """An execution handed to the pass (24 Sec.8.5 steps 2 and 3d): its entry's id, the completed
    reads of its order that found none and when the first did, and whether it is decided as
    unpaired, so the pass lists it without reading its order again."""

    entry_id: int
    execution: Execution
    empty_reads: int
    first_empty_read_at: datetime | None
    decided: bool


class StoreHandovers:
    """`OrderHandovers` and `ExecutionHandovers` over `oms_handovers` (module docstring)."""

    def __init__(
        self,
        store: OmsHandoverStore,
        *,
        source: HandoverSource,
        timeout_s: float = HANDOVER_TIMEOUT_S,
    ) -> None:
        if (
            isinstance(timeout_s, bool)
            or not isinstance(timeout_s, int | float)
            or not math.isfinite(timeout_s)
            or timeout_s <= 0
        ):
            raise ValueError("timeout_s must be a finite number of seconds above zero")
        self._store, self._source, self._timeout_s = store, source, float(timeout_s)

    async def hand_over_order(self, account_id: AccountId, order: Order) -> None:
        """Keep *order* for the next pass, or raise `HandoverUnavailable`."""
        record = order.model_dump(mode="json")
        await self._append(account_id, "order", record, order.exchange_order_id, None, False)

    async def hand_over_execution(
        self, account_id: AccountId, execution: Execution, *, empty_read: bool = False
    ) -> None:
        """Keep *execution* for the next pass, an empty read of its order counted, or raise
        `HandoverUnavailable`."""
        record = execution.model_dump(mode="json")
        keys = (execution.exchange_order_id, execution.exec_id)
        await self._append(account_id, "execution", record, *keys, empty_read)

    async def waiting_orders(self, account_id: AccountId) -> HandoverRead[WaitingOrder]:
        rows = await self._call(account_id, "order", self._store.pending(account_id, "order"))
        out: list[WaitingOrder] = []
        unreadable: list[int] = []
        for row in rows:
            try:
                out.append(WaitingOrder(row.id, Order.model_validate(dict(row.record))))
            except ValidationError:
                _unreadable(account_id, row.id, unreadable)
        return HandoverRead(tuple(out), tuple(unreadable))

    async def waiting_executions(self, account_id: AccountId) -> HandoverRead[WaitingExecution]:
        kind: HandoverKind = "execution"
        rows = await self._call(account_id, kind, self._store.pending(account_id, kind))
        out: list[WaitingExecution] = []
        unreadable: list[int] = []
        for row in rows:
            try:
                execution = Execution.model_validate(dict(row.record))
            except ValidationError:
                _unreadable(account_id, row.id, unreadable)
                continue
            decided = row.decided_at is not None
            entry = WaitingExecution(
                row.id, execution, row.empty_reads, row.first_empty_read_at, decided=decided
            )
            out.append(entry)
        return HandoverRead(tuple(out), tuple(unreadable))

    async def decide(self, account_id: AccountId, exec_id: str) -> bool:
        return await self._call(account_id, "execution", self._store.decide(account_id, exec_id))

    async def prune(self, account_id: AccountId, entry_ids: Collection[int]) -> int:
        ids = tuple(entry_ids)
        return await self._call(account_id, "entries", self._store.prune(account_id, ids))

    async def _append(
        self,
        account_id: AccountId,
        kind: HandoverKind,
        record: dict[str, Any],
        exchange_order_id: str,
        exec_id: str | None,
        empty_read: bool,
    ) -> None:
        if record.get("account_id") != str(account_id):
            self._refused(account_id, kind, "other_account")
            raise HandoverUnavailable("the record names another account (C-2.11)")
        try:
            entry = NewHandover(
                exchange_account_id=account_id,
                kind=kind,
                exchange_order_id=exchange_order_id,
                exec_id=exec_id,
                source=self._source,
                record=record,
                empty_read=empty_read,
            )
        except ValueError:
            self._refused(account_id, kind, "malformed")
            raise HandoverUnavailable("the record is not one the table can hold") from None
        await self._call(account_id, kind, self._store.append(entry))

    async def _call(self, account_id: AccountId, kind: str, call: Awaitable[_T]) -> _T:
        try:
            async with asyncio.timeout(self._timeout_s):
                return await call
        except HandoverStoreFull:
            self._refused(account_id, kind, "store_full")
            raise HandoverUnavailable("the account holds the most hand-overs it may") from None
        except _STORE_FAILURES as exc:
            self._refused(account_id, kind, "store_unavailable", failure=type(exc).__name__)
            raise HandoverUnavailable("the hand-over store did not answer") from None

    @staticmethod
    def _refused(account_id: AccountId, kind: str, reason: str, **detail: str) -> None:
        _log().error(
            "oms_handover_refused", account_id=str(account_id), kind=kind, reason=reason, **detail
        )


def _unreadable(account_id: AccountId, entry_id: int, into: list[int]) -> None:
    """An entry that no longer reads as its model: logged and answered by its id (BQ-18)."""
    _log().error("oms_handover_unreadable", account_id=str(account_id), entry_id=entry_id)
    into.append(entry_id)
