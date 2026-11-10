"""Reconciliation's step-5 stop writer (E29-T06 #914 PR 2b; 24-internal-schemas.md Sec.8.5 step 5,
Sec.8.8 rules 4 to 6; BQ-9; C-2.6). `RecordedStopWriter` is the pass's `ProtectiveStops`: it puts
the record in force on a position over the exchange's `trading-stop`, which the adapter sends on the
`critical` lane, through E29-T04's pieces (the position read, the stop gate, the keyed audit), and
derives what it sends from its own read, never from the pass's:

* **attach** (rule 4, a missing stop): the record's trigger, where the writer's read still shows
  the position open on the record's side with no stop and the trigger can still be placed (below
  the mark for a long, above it for a short, rule 3); audited `sl.attached` with the reason
  `record_in_force` ahead of the send (C-2.9). A read that shows the position flat, reversed (the
  record is the other side's) or protected sends nothing (`not_looser`: not naked on its side); a
  trigger the market is through, or a gate that holds the key, sends nothing (`not_sent`), which
  the pass pages, the fallback being E32-T02's.
* **restore** (a looser Full-mode stop set outside the OMS): the record's trigger, where the
  writer's read still shows the position open on the record's side, its stop looser than the
  record; audited `sl.modified` with both values and the reason `reconcile_restore` ahead of the
  send. A read that shows it flat, reversed or no longer looser sends nothing (`not_looser`).

Each send keeps the take-profit the read shows (24 Sec.8.9: one call writes both sides). The
record in force is the stop it sends, so no new record is written: its terms already say what is
in force. Nothing here is gated by the order-entry gate, the standing or a flag: a stop attach or
restore tightens protection (C-2.6, 24 Sec.8.10). Logs carry ids, the symbol and the outcome,
never a price (C-12.6).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Mapping
from decimal import Decimal
from typing import Any, Final, Literal, Protocol

import structlog

from candleviewer.exchange.base.models import AccountRef, Position, TradingStopRequest
from candleviewer.storage.repositories.recorded_stops import RecordedStopRow

from .errors import StopRequestPending
from .ports import KeyedRecord, PositionKey, StopRequestGate, SubmitAudit
from .push_mapping import money_text
from .reconciler import StopWrite
from .routing import read_position
from .stop_ratchet import loosens
from .stop_shown import position_state

__all__ = ["ATTACH_REASON", "RESTORE_REASON", "RecordedStopWriter"]

#: 24 Sec.8.8 rule 4's reason for the attach of the record in force, and the restore's.
ATTACH_REASON: Final = "record_in_force"
RESTORE_REASON: Final = "reconcile_restore"
#: Each read, the gate's wait and the send (C-2.18); the pass bounds the whole call at 30 s.
READ_TIMEOUT_S: Final = 5.0
GATE_WAIT_S: Final = 2.0
SEND_TIMEOUT_S: Final = 10.0
_SL_ATTACHED: Final = "sl.attached"
_SL_MODIFIED: Final = "sl.modified"
_POSITION_IDX: Final[Mapping[int, Literal[0, 1, 2]]] = {0: 0, 1: 1, 2: 2}


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class StopPorts(Protocol):
    """The account's environment's trading port: its position read and its `trading-stop`."""

    async def positions(self, account: AccountRef) -> Any: ...

    async def set_trading_stop(self, req: TradingStopRequest) -> Any: ...


class StopRouter(Protocol):
    """`routing.TradingRouter.port_for`."""

    def port_for(self, environment: Any) -> Any: ...


def _stop(position: Position) -> Decimal | None:
    """The position's own stop, where it shows one above zero (a venue `0` is none)."""
    stop = position.stop_loss
    return stop if stop is not None and stop > 0 else None


def _placeable(position: Position, trigger: Decimal) -> bool:
    """24 Sec.8.8 rule 3: the market is not through the trigger, on the mark price the venue
    triggers a stop on (`sl_trigger_by` mark): below it for a long, above it for a short."""
    mark = position.mark_price
    if mark is None or mark <= 0:
        return False  # unread: never sent blind
    return trigger < mark if position.side == "buy" else trigger > mark


class RecordedStopWriter:
    """`reconciler.ProtectiveStops` (module docstring)."""

    def __init__(self, *, router: StopRouter, gate: StopRequestGate, audit: SubmitAudit) -> None:
        self._router, self._gate, self._audit = router, gate, audit

    async def attach_recorded(
        self, account: AccountRef, position: Position, record: RecordedStopRow, *, pass_id: str
    ) -> StopWrite:
        port, key = self._router.port_for(account.environment), _key(account, position)
        read = await self._bounded(
            read_position(port, account, position.symbol, position.position_idx), READ_TIMEOUT_S
        )
        if read is None or position_state(record, read) != "open" or _stop(read) is not None:
            return self._done(key, "attach", "not_looser")  # flat, reversed or protected now
        if not _placeable(read, record.trigger_price):
            return self._done(key, "attach", "not_sent")  # the fallback is E32-T02's (rule 3)
        if not await self._cleared(key):
            return self._done(key, "attach", "not_sent")
        await self._record(
            _SL_ATTACHED, ATTACH_REASON, account, record, pass_id,
            {"stop_loss": money_text(record.trigger_price)},
        )  # fmt: skip
        return await self._send(port, account, read, record, key, "attach")

    async def restore_recorded(
        self, account: AccountRef, position: Position, record: RecordedStopRow, *, pass_id: str
    ) -> StopWrite:
        port, key = self._router.port_for(account.environment), _key(account, position)
        read = await self._bounded(
            read_position(port, account, position.symbol, position.position_idx), READ_TIMEOUT_S
        )
        shown = None if read is None or position_state(record, read) != "open" else _stop(read)
        if read is None or shown is None:
            return self._done(key, "restore", "not_looser")  # flat or reversed, or naked now
        if not loosens(record.position_side, record.trigger_price, shown):
            return self._done(key, "restore", "not_looser")  # no longer looser: left as it is
        if not await self._cleared(key):
            return self._done(key, "restore", "not_sent")
        detail = {"stop_loss_before": money_text(shown)}
        detail["stop_loss"] = money_text(record.trigger_price)
        await self._record(_SL_MODIFIED, RESTORE_REASON, account, record, pass_id, detail)
        return await self._send(port, account, read, record, key, "restore")

    async def _cleared(self, key: PositionKey) -> bool:
        """The stop gate's clearance for a protective request (21 Sec.3.3.11): it waits a moment
        for a complete read that holds the key, and is never held by a cooldown."""
        try:
            await self._bounded(
                self._gate.clear(key, wait_s=GATE_WAIT_S, protective=True), READ_TIMEOUT_S
            )
        except (StopRequestPending, TimeoutError):
            return False
        return True

    async def _record(
        self,
        action: str,
        reason: str,
        account: AccountRef,
        record: RecordedStopRow,
        pass_id: str,
        terms: Mapping[str, str],
    ) -> None:
        """The write's record, ahead of its send (C-2.9), keyed per pass so a repeat writes once;
        a record that is not written raises, and nothing is sent."""
        detail: dict[str, str | None] = {
            "symbol": record.symbol, "position_idx": str(record.position_idx),
            "pass_id": pass_id, "source": "reconcile", **terms,
        }  # fmt: skip
        keyed = KeyedRecord(
            action, f"{reason}:{record.id}:{pass_id}", account.account_id, "recorded_stop",
            record.id, "success", "warning", reason, None, detail,
        )  # fmt: skip
        await self._bounded(self._audit.write(keyed), READ_TIMEOUT_S)

    async def _send(
        self,
        port: StopPorts,
        account: AccountRef,
        read: Position,
        record: RecordedStopRow,
        key: PositionKey,
        what: str,
    ) -> StopWrite:
        take_profit = read.take_profit if read.take_profit and read.take_profit > 0 else None
        # Always a Full-mode request (`tpsl_mode`, its default): the pass restores only
        # a Full record (`reconciler._plan_stop`) but attaches any record in force, and a Partial
        # record attached as Full covers the whole position, more never less (C-2.6). The
        # Partial-mode attach and restore are E45-T01's carry (`partial_mode_restore`, BQ-2).
        request = TradingStopRequest(
            account=account, symbol=read.symbol, position_idx=_POSITION_IDX[read.position_idx],
            stop_loss=record.trigger_price, take_profit=take_profit,
        )  # fmt: skip
        ack = await self._bounded(port.set_trading_stop(request), SEND_TIMEOUT_S)
        return self._done(key, what, "sent" if ack.ok else "refused")

    @staticmethod
    def _done(key: PositionKey, what: str, outcome: StopWrite) -> StopWrite:
        _log().info(
            "reconcile_stop_write", account_id=str(key.account_id), symbol=key.symbol,
            position_idx=key.position_idx, write=what, outcome=outcome,
        )  # fmt: skip
        return outcome

    @staticmethod
    async def _bounded[T](call: Awaitable[T], seconds: float) -> T:
        async with asyncio.timeout(seconds):
            return await call


def _key(account: AccountRef, position: Position) -> PositionKey:
    return PositionKey(account.account_id, position.symbol, position.position_idx)
