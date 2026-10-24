"""The stop-request gate that resolves what it refuses (E29-T04 #913 S3-H H3; 21-database-schema.md
Sec.3.3.11, 24-internal-schemas.md Sec.8.4 "The pipeline's own rules", 20-architecture.md Sec.6.2
and Sec.12.1).

`ResolvingStopGate` is the runtime's one `StopRequestGate`, asked before an entry's first persist
(`submit.py`) and before `attach_stop` records its request (`commands.py`). `clear(key, wait_s=)`
reads the key's rows waiting for the complete read (`RecordedStopRepository.waiting_for_key`),
within `STOP_GATE_READ_TIMEOUT_S` (a read that fails or is late is `StoreUnavailable`); with none,
the key is clear. Otherwise it joins the key's resolution (`StopResolver.resolve_key`, a task the
gate owns) or starts one: one per key, at most `MAX_RESOLUTIONS` in the process, the last kept for
an attach (C-2.18; a reserve, as C-12.7 keeps one). An entry that finds the others taken, or its
key cooling, is refused without asking the venue; an attach (`wait_s` above zero) may take the kept
slot and is never held by the cooldown. It waits up to `wait_s` (an entry not at all: 409 at once,
`Retry-After: 5`, the read running on for its retry) and returns once the resolution has ended and
a fresh read lists nothing; else `StopRequestPending(5)`. A resolution that cleared nothing, failed
or not, cools its key for `STOP_REQUEST_RETRY_AFTER_S` on the injected monotonic clock.

Each decision counts `oms_stop_resolutions_total{outcome}`, a read that decided nothing
`read_failed`; each stop-loss voided `entry_filled_stop_absent` on its open position pages (C-2.6).
A key `held_for_reconciliation` logs `oms_stop_request_held` once per hold, and pages once per hold
for a `restore` request (E29-T06's) or a hold through `WAITING_ENTRY` whose read shows the position
open with no stop at all (a C-2.6 exposure only E29-T06's pass clears); a hold ends once its key is
found clear or held no more. Pages name ids only.

The startup floor (Q7): every unanswered row created before the runtime started (`started_at`, from
the database's clock) waits whatever its age: each read passes `bound_s = min(bound, now - start)`,
at least zero, with its own `now`, so the cutoff is `max(now - bound, start)` and no app-versus-
database skew files a live writer's row as waiting. Until the start is known, `clear` is
`StoreUnavailable`. `aclose()` cancels and awaits every resolution the gate runs.
"""

from __future__ import annotations

import asyncio
import math
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from functools import partial
from types import MappingProxyType
from typing import Any, Final

import structlog

from candleviewer.domain.primitives import Environment
from candleviewer.exchange.base.ports import TradingPort
from candleviewer.observability import spawn
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.statechart.plugins import LogPager, Pager
from candleviewer.storage.errors import StorageError
from candleviewer.storage.repositories.orders import OrderStoreError
from candleviewer.storage.repositories.recorded_stops import FillPosition, RecordedStopRow

from .errors import StopRequestPending, StoreUnavailable
from .ports import (
    STOP_GATE_READ_TIMEOUT_S,
    STOP_REQUEST_RETRY_AFTER_S,
    KeyedRecord,
    PositionKey,
    SubmitAudit,
    TradingAccounts,
)
from .repository import RecordedStopRepository
from .stop_resolution import (
    FILL_PAGE,
    RESTORE_HELD,
    RequestDecision,
    StopResolver,
    VoidReason,
    VoidWriteAhead,
)

__all__ = [
    "MAX_HOLDS", "MAX_RESOLUTIONS", "RESOLUTIONS_METRIC", "RESOLUTION_TIMEOUT_S",
    "ResolvingStopGate", "StopVoidAudit",
]  # fmt: skip

#: At most this many resolutions run at once, the last kept for an attach (21 Sec.3.3.11).
MAX_RESOLUTIONS: Final = 8
#: One resolution's bound, in seconds: the account's read, the complete read (its venue reads
#: within 15 s) and its writes; past it the read decided nothing.
RESOLUTION_TIMEOUT_S: Final = 30.0
#: The keys whose hold, or cooldown, the gate remembers (C-2.18): past it the oldest is forgotten,
#: and its next resolution announces it again, never silences it.
MAX_HOLDS: Final = 1024
RESOLUTIONS_METRIC: Final = "oms_stop_resolutions_total"
_MODIFIED: Final[Mapping[str, str]] = MappingProxyType(
    {"stop_loss": "sl.modified", "take_profit": "tp.modified"}
)


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class StopVoidAudit:
    """`stop_resolution.VoidAudit` over the OMS's keyed records (`SubmitAudit`): per voided row one
    `sl.modified` (`tp.modified` for a take-profit side) ahead of the commit, with its reason, as
    `system:oms`, ids only, and the `position_state` the store passes for a void that states it
    (`entry_filled_stop_absent`, or an `entry_unseen` page; 21 Sec.3.3.11 "Audit"). Named by reason
    and row: a void retried with another reason is kept too."""

    def __init__(self, audit: SubmitAudit) -> None:
        self._audit = audit

    def hook(self, reason: VoidReason) -> VoidWriteAhead:
        async def write_ahead(
            rows: tuple[RecordedStopRow, ...], position_state: FillPosition | None
        ) -> None:
            for row in rows:
                detail: dict[str, str | None] = {"kind": row.kind, "source": row.source}
                if row.order_id is not None:
                    detail["order_id"] = str(row.order_id)
                if position_state is not None:
                    detail["position_state"] = position_state
                record = KeyedRecord(
                    _MODIFIED[row.kind], f"{reason}:{row.id}", row.exchange_account_id,
                    "recorded_stop", row.id, "success", "warning", reason, None, detail,
                )  # fmt: skip
                await self._audit.write(record)

        return write_ahead


class ResolvingStopGate:
    """The runtime's `StopRequestGate` (module docstring)."""

    def __init__(
        self,
        rows: RecordedStopRepository,
        resolver: StopResolver,
        *,
        accounts: TradingAccounts,
        port_for: Callable[[Environment], TradingPort],
        bound_s: float,
        now: Callable[[], datetime],
        monotonic: Callable[[], float],
        metrics: Metrics,
        pager: Pager | None = None,
        started_at: datetime | None = None,
        read_timeout_s: float = STOP_GATE_READ_TIMEOUT_S,
        resolution_timeout_s: float = RESOLUTION_TIMEOUT_S,
        max_resolutions: int = MAX_RESOLUTIONS,
    ) -> None:
        if max_resolutions < 2:
            raise ValueError("the cap keeps one slot for an attach beside the others")
        self._rows, self._resolver, self._accounts = rows, resolver, accounts
        self._port_for, self._bound_s, self._started_at = port_for, bound_s, started_at
        self._now, self._monotonic = now, monotonic
        self._pager: Pager = LogPager() if pager is None else pager
        self._read_timeout_s, self._resolution_timeout_s = read_timeout_s, resolution_timeout_s
        self._max = max_resolutions
        spec = next(spec for spec in CATALOGUE if spec.name == RESOLUTIONS_METRIC)
        counter = metrics.counter(spec.name, spec.help, spec.labels, max_series=spec.max_series)
        self._outcomes = counter
        self._running: dict[PositionKey, asyncio.Task[None]] = {}
        self._cooling: OrderedDict[PositionKey, float] = OrderedDict()
        self._holds: OrderedDict[PositionKey, set[str]] = OrderedDict()
        self._closed = False

    async def clear(self, key: PositionKey, *, wait_s: float = 0.0) -> None:
        """Return when `key` may take a stop request; else `StopRequestPending`, or
        `StoreUnavailable` when its rows cannot be read (module docstring)."""
        if not await self._waiting(key):
            return
        task = self._running.get(key)
        if task is None or task.done():
            task = self._start(key, wait_s > 0)  # an attach waits: it is protective
        if task is not None and wait_s > 0:
            done, _ = await asyncio.wait([task], timeout=wait_s)  # shared: a wait never cancels it
            if done and not await self._waiting(key):
                return
        _log().info("oms_stop_request_waiting", symbol=key.symbol, reading=task is not None)
        raise StopRequestPending(retry_after_s=STOP_REQUEST_RETRY_AFTER_S)

    async def aclose(self) -> None:
        """Cancel and await every resolution (20 Sec.6.2 `stop()`); none starts after."""
        self._closed = True
        tasks = list(self._running.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks)  # their cancellation is their end; the caller's propagates

    def _floor(self, now: datetime) -> float | None:
        start = self._started_at
        if start is None:
            return None
        return max(0.0, min(self._bound_s, (now - start).total_seconds()))

    async def _waiting(self, key: PositionKey) -> bool:
        """Whether a row of `key` waits for the complete read; a key found clear ends its hold."""
        now = self._now()
        bound = self._floor(now)
        try:
            if bound is None:  # nothing is judged before the floor is read: fail closed
                raise StoreUnavailable
            async with asyncio.timeout(self._read_timeout_s):
                rows = await self._rows.waiting_for_key(
                    key.account_id, key.symbol, key.position_idx, now=now, bound_s=bound
                )
        except (TimeoutError, StorageError, OrderStoreError, StoreUnavailable) as exc:
            _log().warning("oms_stop_gate_unavailable", failure=type(exc).__name__)
            raise StoreUnavailable from None
        if not rows:
            self._holds.pop(key, None)
        return bool(rows)

    def _start(self, key: PositionKey, protective: bool) -> asyncio.Task[None] | None:
        """The key's resolution, or None: closed, no slot (an entry leaves the kept one), or an
        entry's key cooling."""
        if self._closed or self._busy() >= self._max - (0 if protective else 1):
            return None
        if not protective and self._cooling.get(key, -math.inf) > self._monotonic():
            return None
        task = spawn(self._resolve(key), name="oms-stop-resolution")
        self._running[key] = task
        task.add_done_callback(partial(self._ended, key))
        return task

    def _busy(self) -> int:
        return sum(not task.done() for task in self._running.values())

    def _ended(self, key: PositionKey, task: asyncio.Task[None]) -> None:
        if self._running.get(key) is task:
            del self._running[key]

    async def _resolve(self, key: PositionKey) -> None:
        decisions: tuple[RequestDecision, ...] | None = None
        try:
            async with asyncio.timeout(self._resolution_timeout_s):
                account = await self._accounts.trading_account(key.account_id)
                port, now = self._port_for(account.environment), self._now()
                decisions = await self._resolver.resolve_key(
                    port, account, key, bound_s=self._floor(now), now=now
                )
        except Exception as exc:  # the task's own end, logged and counted; a cancel goes through
            failure = type(exc).__name__
            _log().warning("oms_stop_resolution_failed", symbol=key.symbol, failure=failure)
        if decisions is None:
            self._outcomes.labels("read_failed").inc()
        else:
            self._announce(key, decisions)
        if decisions is None or (
            decisions and all(m == "kept" for d in decisions for _, m in d.moves)
        ):
            self._cool(key)  # it cleared nothing; one that found nothing waiting cleared the key

    def _cool(self, key: PositionKey) -> None:
        now = self._monotonic()
        while self._cooling and next(iter(self._cooling.values())) <= now:
            self._cooling.popitem(last=False)
        self._cooling.pop(key, None)
        self._cooling[key] = now + STOP_REQUEST_RETRY_AFTER_S
        if len(self._cooling) > MAX_HOLDS:
            self._cooling.popitem(last=False)

    def _announce(self, key: PositionKey, decisions: Sequence[RequestDecision]) -> None:
        """Count each decision, page each void that pages, and announce a hold once."""
        where = f"account {key.account_id} {key.symbol} position_idx {key.position_idx}"
        for decision in decisions:
            self._outcomes.labels(decision.outcome).inc()
            # the read names why it pages (`page_reason`, typed): a filled entry's void or
            # `entry_unseen`; the page carries the read's own text after the reason
            reason = decision.page_reason or "entry_filled_stop_absent"
            what = (decision.page or FILL_PAGE).partition(": ")[2]
            for record_id in decision.pages:
                self._page(f"oms_stop_{reason}: C-2.6 exposure, {where}, {record_id}: {what}")
        held = [d for d in decisions if d.held is not None]
        told = self._holds.pop(key, set())
        if not held:
            return
        self._holds[key] = told
        if len(self._holds) > MAX_HOLDS:
            self._holds.popitem(last=False)
        facts = {
            "held": True,
            "restore": any(d.held == RESTORE_HELD for d in held),
            "exposed": any(d.exposed for d in held),
        }
        new = {fact for fact, met in facts.items() if met} - told
        told |= new
        if "held" in new:
            reasons = sorted({str(d.held) for d in held})
            _log().warning(
                "oms_stop_request_held", account_id=str(key.account_id), symbol=key.symbol,
                position_idx=key.position_idx, reasons=reasons,
            )  # fmt: skip
        if "restore" in new:
            self._page(f"oms_stop_restore_held: held_for_reconciliation, {where}, E29-T06's")
        if "exposed" in new:
            self._page(f"oms_stop_request_held: C-2.6 exposure, held_for_reconciliation, {where} "
                       "open with no stop at all, until E29-T06's pass")  # fmt: skip

    def _page(self, summary: str) -> None:
        try:
            self._pager.raise_alert("page", summary, machine_kind="order")
        except Exception as exc:  # the page is lost, never what it pages on
            _log().critical("oms_pager_failed", summary=summary, failure=type(exc).__name__)
