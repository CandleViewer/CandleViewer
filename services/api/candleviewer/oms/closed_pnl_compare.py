"""The closed-PnL comparison (E29-S06 #981 slice 5c; 24 Sec.8.13 "Divergent" and "The divergence
record", Sec.15.5 `pnl.divergence_detected`).

`compared` is the verdict on one item the delta set's composition wrote (the orchestrator's ruling
Q2 of 2026-11-04, 23:45Z): compared only when both figures exist, the item settled with the
venue's `closed_pnl`, its `local_net` present, its closes closing exactly the record's `qty` and
the walk's average entry within the relative tolerance of the venue's `avg_entry_price`.
Otherwise nothing is compared, and the flag and the pair it recorded stay. It is divergent when
`|local_net - closed_pnl|` is strictly greater than both the relative bound, `tolerance_rel x
|closed_pnl|`, so against a venue figure of 0 any difference passes it, and the absolute floor
(PROPOSED, 0.01 USDT: a sub-cent close is not divergent). Exact arithmetic, `Inexact` trapped.

`ClosedPnlComparer.compare` acts on the verdicts of one pass:

- **Within the bound:** a flagged item is cleared, its pair kept; nothing is written.
- **Divergent, its pair recorded already:** no record; an item unflagged meanwhile is flagged. A
  pair this process wrote last for the record counts as recorded, so a flag whose write failed
  after its record is retried alone, never with a second record; after a restart the stored pair
  alone decides, which can repeat the record once (24 Sec.8.13).
- **Divergent, a new pair:** the record is written and awaited durable (C-2.9), then counted in
  `oms_closed_pnl_divergence_total` and logged at WARNING with the account and the record, then
  the item is flagged with its pair (`mark_divergent`). The write is its own await, never inside a
  store call, so no store transaction and no account lock is held across the WAL's `fsync`.
- **Venue missing:** an item the venue never settled whose `closed_at` left the reach (24
  Sec.8.13 "The sync") is recorded with the same action and the reason `closed_pnl_venue_missing`,
  `closed_pnl` and `difference` null, never flagged (the table's `cpr_pair` flags settled rows).

The volume is bounded (the orchestrator's ruling Q6 of 2026-11-05): at most `EMIT_LIMIT` records
an account a pass, at most `PAIR_LIMIT` records written for one record id in this process, whatever
their pairs, and no record
while the writer reports strain (`DivergenceWriter.strained`, the order audit's priority). A
record held back by the pass cap or the strain, or whose write or flag failed, is owed: the
caller compares it again at its next pass, at most `RETRY_LIMIT` an account, past which it is
dropped. Each case is counted in `oms_closed_pnl_divergence_withheld_total{reason}` and logged at
WARNING once a pass with its count. Logs carry ids, reasons and counts only, never a figure
(C-12.6); the record's after-state carries the figures (class P1, 24 Sec.15.5). A flag's write
that meets no settled row (it returns False) is logged at WARNING with the ids and not owed.

The wall time a pass spends here is bounded, not budgeted: at most `EMIT_LIMIT` writes, and one
flag's write for each item compared (the composition's at most `COMPOSE_LIMIT` orders), each within
`CALL_TIMEOUT_S`. A writer and a store that both hang can so cost one account's pass minutes, on the
sync's one task, which delays the other accounts' reads by as much.
"""

from __future__ import annotations

import asyncio
from collections import Counter, OrderedDict
from collections.abc import Awaitable, Iterable
from dataclasses import dataclass, field
from decimal import Context, Decimal, DivisionByZero, Inexact, InvalidOperation, Overflow
from typing import Any, Final, Literal, Protocol, cast
from uuid import UUID

import structlog

from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.storage.repositories.closed_pnl import ClosedPnlRecordRow

from .closed_pnl_compose import Composed

#: The record's reasons (24 Sec.15.5): a divergent comparison, and a venue figure still missing.
Reason = Literal["closed_pnl_divergence", "closed_pnl_venue_missing"]
DIVERGENCE: Final[Reason] = "closed_pnl_divergence"
VENUE_MISSING: Final[Reason] = "closed_pnl_venue_missing"
#: The tolerances' bounds (20 Sec.7.2): each above 0, the relative at most 0.001, the floor 1 USDT.
REL_MAX: Final = Decimal("0.001")
FLOOR_MAX: Final = Decimal(1)
#: Q6, PROPOSED: records an account a pass, records a record id, record ids remembered.
EMIT_LIMIT: Final = 32
PAIR_LIMIT: Final = 8
PAIR_MEMORY: Final = 16_384
RETRY_LIMIT: Final = 256  # owed comparisons an account (Q3), past which one is dropped
CALL_TIMEOUT_S: Final = 5.0  # a record's write, a flag's write (C-2.18)
DIVERGENCE_TOTAL: Final = "oms_closed_pnl_divergence_total"
WITHHELD_TOTAL: Final = "oms_closed_pnl_divergence_withheld_total"
Withheld = Literal["pass_cap", "pair_limit", "backpressure", "retry_dropped"]
WITHHELD: Final[tuple[Withheld, ...]] = ("pass_cap", "pair_limit", "backpressure", "retry_dropped")
_EXACT: Final = Context(prec=400, traps=[InvalidOperation, DivisionByZero, Overflow, Inexact])


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Tolerance:
    """The detection settings, checked again here as the settings check them: each a finite
    `Decimal` above 0, `rel` at most `REL_MAX` and `floor` at most `FLOOR_MAX`."""

    rel: Decimal
    floor: Decimal

    def __post_init__(self) -> None:
        for value, top in ((self.rel, REL_MAX), (self.floor, FLOOR_MAX)):
            if not (isinstance(value, Decimal) and value.is_finite() and 0 < value <= top):
                raise ValueError("a closed-PnL tolerance is a finite Decimal within its bounds")


#: A value pair: the local net figure and the venue's.
Pair = tuple[Decimal, Decimal]


@dataclass(frozen=True, slots=True)
class Verdict:
    """A comparison: the pair compared and their signed difference, local - venue."""

    divergent: bool
    local_net: Decimal
    closed_pnl: Decimal
    difference: Decimal

    @property
    def pair(self) -> Pair:
        return self.local_net, self.closed_pnl


def compared(
    row: ClosedPnlRecordRow, local_net: Decimal | None, avg_entry: Decimal | None,
    closed: Decimal | None, tolerance: Tolerance,
) -> Verdict | None:  # fmt: skip
    """The verdict on a composed item (module docstring), None when it is not compared."""
    venue, entry = row.closed_pnl, row.avg_entry_price
    if row.settled_at is None or venue is None or local_net is None:
        return None
    if closed is None or closed != row.qty or avg_entry is None or entry is None:
        return None
    if _EXACT.abs(_EXACT.subtract(avg_entry, entry)) > _EXACT.multiply(tolerance.rel, entry):
        return None  # the stored fills do not account for the record
    difference = _EXACT.subtract(local_net, venue)
    size = _EXACT.abs(difference)
    bound = _EXACT.multiply(tolerance.rel, _EXACT.abs(venue))
    return Verdict(size > bound and size > tolerance.floor, local_net, venue, difference)


def after_state(
    row: ClosedPnlRecordRow, local_net: Decimal | None, difference: Decimal | None,
    tolerance: Tolerance,
) -> dict[str, str | None]:  # fmt: skip
    """The record's after-state (24 Sec.15.5): the record's account, symbol and venue order id and
    the figures as text, a missing one null; the tolerance and its floor."""

    def text(value: Decimal | None) -> str | None:
        return None if value is None else str(value)

    return {
        "account_id": str(row.exchange_account_id), "symbol": row.symbol,
        "exchange_order_id": row.exchange_order_id, "closed_pnl": text(row.closed_pnl),
        "local_net_pnl": text(local_net), "gross_pnl": text(row.gross_pnl),
        "fee_pnl": text(row.fee_pnl), "funding_pnl": text(row.funding_pnl),
        "difference": text(difference), "tolerance": str(tolerance.rel),
        "tolerance_floor": str(tolerance.floor),
    }  # fmt: skip


@dataclass(frozen=True, slots=True)
class DivergenceRecord:
    """One `pnl.divergence_detected`: its object the record, its reason and its after-state."""

    record_id: UUID
    reason: Reason
    after_state: dict[str, str | None]


class DivergenceWriter(Protocol):
    """The root's adapter over the order lane's audit writer (`oms_closed_pnl_wiring`)."""

    def strained(self) -> bool:
        """Whether the writer reports an append failure or a deep buffer: no record then."""

    async def write(self, record: DivergenceRecord) -> None:
        """Durable or it raises (C-2.9)."""


class DivergenceMarks(Protocol):  # `closed_pnl.ClosedPnlStore`'s two writes of the flag
    async def mark_divergent(
        self, account_id: UUID, record_id: UUID, local_net: Decimal, closed_pnl: Decimal
    ) -> bool: ...
    async def clear_divergent(self, account_id: UUID, record_id: UUID) -> bool: ...


#: What a pass owes, by venue order id: None to compose and compare again, or the row of a venue
#: figure missing, to record again.
Owed = dict[str, ClosedPnlRecordRow | None]


@dataclass
class _Pass:
    account_id: UUID
    emitted: int = 0
    owed: Owed = field(default_factory=dict)
    withheld: Counter[Withheld] = field(default_factory=Counter)


async def _bounded[T](call: Awaitable[T]) -> T:
    async with asyncio.timeout(CALL_TIMEOUT_S):
        return await call


def _local(row: ClosedPnlRecordRow) -> Decimal | None:
    parts = (row.gross_pnl, row.fee_pnl, row.funding_pnl)
    if None in parts:
        return None
    gross, fee, funding = cast(tuple[Decimal, Decimal, Decimal], parts)
    return _EXACT.add(_EXACT.add(gross, fee), funding)


class ClosedPnlComparer:
    """The comparison and its record over the store of the flag and the writer (module
    docstring); the effective tolerance is logged once, when it is built."""

    def __init__(
        self, *, marks: DivergenceMarks, writer: DivergenceWriter, tolerance: Tolerance,
        metrics: Metrics,
    ) -> None:  # fmt: skip
        self._marks, self._writer, self._tolerance = marks, writer, tolerance
        specs = {spec.name: spec for spec in CATALOGUE}
        total, held = specs[DIVERGENCE_TOTAL], specs[WITHHELD_TOTAL]
        self._total = metrics.counter(total.name, total.help, max_series=total.max_series).child()
        withheld = metrics.counter(held.name, held.help, held.labels, max_series=held.max_series)
        self._withheld = {reason: withheld.labels(reason) for reason in WITHHELD}
        #: by record id: the records written for it in this process, and the last one's pair
        self._pairs: OrderedDict[UUID, tuple[int, Pair | None]] = OrderedDict()
        _log().info("closed_pnl_tolerance", rel=str(tolerance.rel), floor=str(tolerance.floor))

    async def compare(
        self, account_id: UUID, composed: Iterable[Composed], missing: Iterable[ClosedPnlRecordRow]
    ) -> Owed:
        """Compare the items one pass composed and record the venue figures missing (each a row
        not settled whose `closed_at` left the reach): what the pass owes, for the next."""
        p = _Pass(account_id)
        for item in composed:
            await self._one(p, item)
        for row in missing:
            if row.settled_at is None and row.exchange_order_id is not None:
                state = after_state(row, _local(row), None, self._tolerance)
                await self._record(p, row, DivergenceRecord(row.id, VENUE_MISSING, state), None)
        for reason, count in sorted(p.withheld.items()):
            self._withheld[reason].inc(count)
            _log().warning("closed_pnl_divergence_withheld", account_id=str(account_id),
                           reason=reason, records=count)  # fmt: skip
        return p.owed

    async def _one(self, p: _Pass, item: Composed) -> None:
        row = item.row
        verdict = compared(row, item.local_net, item.avg_entry, item.closed, self._tolerance)
        if verdict is None:
            return  # nothing compared: the flag and the pair it recorded stay
        if not verdict.divergent:
            if row.divergent:
                await self._marked(p, row, self._marks.clear_divergent(p.account_id, row.id))
            return
        stored = (row.audited_local_net, row.audited_closed_pnl) == verdict.pair
        written = self._pairs.get(row.id, (0, None))[1] == verdict.pair  # its flag's write failed
        if not (stored or written):
            state = after_state(row, verdict.local_net, verdict.difference, self._tolerance)
            record = DivergenceRecord(row.id, DIVERGENCE, state)
            if not await self._record(p, row, record, verdict.pair):
                return  # unflagged until a later comparison
        elif stored and row.divergent:
            return  # its pair recorded and flagged: nothing to write
        mark = self._marks.mark_divergent(p.account_id, row.id, *verdict.pair)
        await self._marked(p, row, mark)

    async def _record(
        self, p: _Pass, row: ClosedPnlRecordRow, record: DivergenceRecord, pair: Pair | None
    ) -> bool:
        """Write the record, bounded: whether it is durable. Held back, failed, it is owed."""
        venue = cast(str, row.exchange_order_id)
        owed = None if record.reason == DIVERGENCE else row
        written = self._pairs.get(row.id, (0, None))[0]
        if written >= PAIR_LIMIT:
            p.withheld["pair_limit"] += 1
            return False
        if p.emitted >= EMIT_LIMIT or self._writer.strained():
            p.withheld["pass_cap" if p.emitted >= EMIT_LIMIT else "backpressure"] += 1
            self._owe(p, venue, owed)
            return False
        try:
            await _bounded(self._writer.write(record))
        except Exception as exc:  # a cancel propagates
            _log().error("closed_pnl_divergence_unwritten", account_id=str(p.account_id),
                         record_id=str(row.id), kind=type(exc).__name__)  # fmt: skip
            self._owe(p, venue, owed)
            return False
        p.emitted += 1
        self._pairs.pop(row.id, None)
        self._pairs[row.id] = (written + 1, pair)
        while len(self._pairs) > PAIR_MEMORY:
            self._pairs.popitem(last=False)
        self._total.inc()
        _log().warning("closed_pnl_divergence_recorded", account_id=str(p.account_id),
                       record_id=str(row.id), reason=record.reason)  # fmt: skip
        return True

    async def _marked(self, p: _Pass, row: ClosedPnlRecordRow, write: Awaitable[bool]) -> None:
        try:
            met = await _bounded(write)
        except Exception as exc:  # compared again at the next pass; a cancel propagates
            _log().warning("closed_pnl_flag_failed", account_id=str(p.account_id),
                           record_id=str(row.id), kind=type(exc).__name__)  # fmt: skip
            self._owe(p, cast(str, row.exchange_order_id), None)
            return
        if not met:  # no settled row of the account's met it: nothing to retry
            _log().warning("closed_pnl_flag_unmet", account_id=str(p.account_id),
                           record_id=str(row.id))  # fmt: skip

    def _owe(self, p: _Pass, venue: str, row: ClosedPnlRecordRow | None) -> None:
        if venue in p.owed or len(p.owed) < RETRY_LIMIT:
            p.owed[venue] = row
        else:
            p.withheld["retry_dropped"] += 1
