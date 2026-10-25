"""What the harness measures (#843 A4 brief item 5), in memory until the summary is written.

- `Timings`: each port call's latency, and the venue round trips its HTTP exchanges took at the
  `rest_transport` seam (`recorder.RecordingTransport` adds them to the call in flight through a
  context variable), so our overhead is the call's latency minus its round trips: budget #4's
  50 ms share (`06-performance-and-load-standard.md` §5.2). Each round trip is also kept by its
  connection, `cold` (a new one: TCP and TLS) or `warm`, and a create's by its kind, a limit
  opener or a reduce-only close (`rtt_split_ms`, R1C-06); a failed exchange is counted by its
  class (`failed`, R1C-09), so a timeout is never missing from the record. M2's key read and
  fsynced audit append before each signature fall in that overhead (`secrets/broker.py`,
  `audit/writer.py`), and are also timed on their own: `timed_borrower` wraps the borrower the
  adapter is handed and times each `sign` call, by the port call in flight (else by M2's
  purpose): the signing share.
- `ClockOffset`: exchange minus host, from the wallet read's envelope `time` against the
  midpoint of its exchange at the seam; the sample with the smallest round trip wins.
- `StreamMonitor`: the private stream's items in arrival order: latency from the venue's own
  time to local receipt, corrected by the offset; executions seen on the stream against the
  `GET /v5/execution/list` backfill (parity); order state transitions; the stream's statuses;
  and two counts kept apart (`ordering_counts`): a venue reorder, an execution arriving after
  the order transition it caused (23 §S5), and a dropped push, an execution only the backfill
  listed.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections import Counter, defaultdict
from collections.abc import AsyncIterator, Callable, Iterable, Sequence
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Final

from candleviewer.exchange.base.models import (
    Execution,
    FastExecution,
    Order,
    Position,
    PrivateEvent,
    PrivateStreamStatus,
    Wallet,
)
from candleviewer.secrets import CredentialBorrower

if TYPE_CHECKING:
    from uuid import UUID

    from candleviewer.secrets import Purpose, RequestSignature
    from candleviewer.secrets.signing import SigningMessage

#: The call classes the brief names, by REST path; any other path is `other`.
CALL_CLASSES: Final = {
    "/v5/order/create": "create",
    "/v5/order/amend": "amend",
    "/v5/order/cancel": "cancel",
    "/v5/order/cancel-all": "cancel_all",
    "/v5/execution/list": "executions",
    "/v5/order/realtime": "open_orders",
    "/v5/order/history": "order_history",
    "/v5/position/list": "positions",
    "/v5/account/wallet-balance": "wallet",
}


#: The two ordering counts #843 keeps apart, by their record names (`ordering_counts`).
REORDER_COUNT: Final = "venue_reorder_execution_after_its_order_transition"
DROPPED_COUNT: Final = "dropped_push_execution_only_via_backfill"


def call_class(path: str) -> str:
    return CALL_CLASSES.get(path, "other")


def stats(values: Iterable[float], digits: int = 1) -> dict[str, float]:
    """n, p50, p95, p99 (nearest rank), min and max, in the values' unit, rounded to `digits`."""
    ordered = sorted(values)
    if not ordered:
        return {"n": 0}

    def rank(p: float) -> float:
        return round(ordered[max(0, math.ceil(p * len(ordered)) - 1)], digits)

    return {
        "n": len(ordered),
        "p50": rank(0.50),
        "p95": rank(0.95),
        "p99": rank(0.99),
        "min": round(ordered[0], digits),
        "max": round(ordered[-1], digits),
    }


def gap_stats(values: Sequence[float], threshold_s: float) -> dict[str, float]:
    """A distribution of silences (s): n, p50, p95 and max to the ms, and how many were longer
    than `threshold_s` (`over_threshold`)."""
    held = stats(values, digits=3)
    out = {k: held[k] for k in ("n", "p50", "p95", "max") if k in held}
    return out | {"over_threshold": sum(1 for v in values if v > threshold_s)}


@dataclass
class CallRecord:
    """One port call in flight: the round trips (ms) of the exchanges it made."""

    name: str
    rtts_ms: list[float] = field(default_factory=list)


CURRENT: ContextVar[CallRecord | None] = ContextVar("spike_current_call", default=None)


class Timings:
    """Port latency, venue RTT, our overhead (port minus RTT) and M2's signing time, per call
    class, in ms."""

    def __init__(self, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._monotonic = monotonic
        self.port_ms: defaultdict[str, list[float]] = defaultdict(list)
        self.rtt_ms: defaultdict[str, list[float]] = defaultdict(list)
        self.rtt_split_ms: defaultdict[str, list[float]] = defaultdict(list)
        self.failed_exchanges: Counter[str] = Counter()
        self.overhead_ms: defaultdict[str, list[float]] = defaultdict(list)
        self.signing_ms: defaultdict[str, list[float]] = defaultdict(list)

    @asynccontextmanager
    async def call(self, name: str) -> AsyncIterator[CallRecord]:
        record = CallRecord(name)
        token = CURRENT.set(record)
        started = self._monotonic()
        try:
            yield record
        finally:
            elapsed = (self._monotonic() - started) * 1000
            CURRENT.reset(token)
            self.port_ms[name].append(elapsed)
            if record.rtts_ms:
                self.overhead_ms[name].append(max(0.0, elapsed - sum(record.rtts_ms)))

    def exchanged(
        self, path: str, rtt_ms: float, *, cold: bool = False, kind: str | None = None
    ) -> None:
        """One HTTP exchange at the seam: its RTT by path class, by `class:cold|warm`, by its
        create `kind` (`create_open`, `create_close`) and its `kind:cold|warm`, and on the call
        in flight."""
        name, temperature = call_class(path), "cold" if cold else "warm"
        self.rtt_ms[name].append(rtt_ms)
        for split in (f"{name}:{temperature}", kind, f"{kind}:{temperature}" if kind else None):
            if split is not None:
                self.rtt_split_ms[split].append(rtt_ms)
        record = CURRENT.get()
        if record is not None:
            record.rtts_ms.append(rtt_ms)

    def failed(self, path: str) -> None:
        """An exchange that ended in a transport failure, by path class."""
        self.failed_exchanges[call_class(path)] += 1

    @asynccontextmanager
    async def signing(self, purpose: Purpose) -> AsyncIterator[None]:
        """One M2 `sign` call, timed: a REST signing under the port call in flight, else (the
        stream's `auth`, a port no guard wraps) under M2's purpose."""
        record = CURRENT.get()
        name = record.name if record is not None and purpose == "sign_rest" else purpose
        started = self._monotonic()
        try:
            yield
        finally:
            self.signing_ms[name].append((self._monotonic() - started) * 1000)

    def summary(self) -> dict[str, dict[str, dict[str, float]]]:
        every = [ms for values in self.signing_ms.values() for ms in values]
        signing = {k: stats(v) for k, v in sorted(self.signing_ms.items())}
        names = sorted(set(self.rtt_ms) | set(self.failed_exchanges))
        return {
            "rtt_ms": {
                k: stats(self.rtt_ms.get(k, [])) | {"failed": self.failed_exchanges[k]}
                for k in names
            },
            "rtt_split_ms": {k: stats(v) for k, v in sorted(self.rtt_split_ms.items())},
            "port_ms": {k: stats(v) for k, v in sorted(self.port_ms.items())},
            "overhead_ms": {k: stats(v) for k, v in sorted(self.overhead_ms.items())},
            "signing_ms": signing | {"overall": stats(every)},
        }


def timed_borrower(borrower: CredentialBorrower, timings: Timings) -> CredentialBorrower:
    """`borrower`, each `sign` call timed into `timings` (M2's key read, its fsynced audit append
    and the MAC: the signing share of our overhead). The call goes through unchanged, and what
    it returns is handed back untouched: no signature or key id is read, kept or recorded."""

    async def sign(key_id: UUID, message: SigningMessage, purpose: Purpose) -> RequestSignature:
        async with timings.signing(purpose):
            return await borrower.sign(key_id, message, purpose=purpose)

    return CredentialBorrower(sign)


class ClockOffset:
    """Exchange minus host, ms; `None` until measured (the port then signs on the host's clock
    and the private stream counts no `auth` refusal, G-8b OQ-4)."""

    def __init__(self) -> None:
        self.value: int | None = None
        self.best_rtt_ms: float | None = None
        self.samples = 0

    def read(self) -> int | None:
        return self.value

    def sample(self, sent_wall_ms: float, received_wall_ms: float, venue_ms: int) -> None:
        """One exchange: the venue's `time` against the midpoint of send and reply on the host's
        wall clock. A sample with a shorter round trip replaces the one held."""
        self.samples += 1
        rtt = received_wall_ms - sent_wall_ms
        if self.best_rtt_ms is None or rtt <= self.best_rtt_ms:
            self.best_rtt_ms = rtt
            self.value = round(venue_ms - (sent_wall_ms + received_wall_ms) / 2)

    def reset_best(self) -> None:
        """A re-measure starts afresh, so drift over a long run is followed."""
        self.best_rtt_ms = None


_ZERO = Decimal(0)


class StreamMonitor:
    """The private stream's items, in the order the stream yields them (its arrival order)."""

    def __init__(
        self, offset: ClockOffset, monotonic: Callable[[], float] = time.monotonic
    ) -> None:
        self._offset = offset
        self._monotonic = monotonic
        #: Each outage, from its `down` to the next `resyncing` (seconds): the stream's gaps.
        self.gaps_s: list[float] = []
        self._down_at: float | None = None
        self.kinds: Counter[str] = Counter()
        self.statuses: Counter[str] = Counter()
        self.latency_ms: defaultdict[str, list[float]] = defaultdict(list)
        self.unmeasured = 0
        self.stream_execs: set[str] = set()
        self.fast_execs: set[str] = set()
        self.rest_execs: set[str] = set()
        self.duplicates = 0
        self.after_order = 0
        self.transitions: Counter[str] = Counter()
        self.orders: dict[str, Order] = {}
        self.position: Position | None = None
        self.wallet: Wallet | None = None
        self.live = False
        self.closed = False
        self._cum_exec: defaultdict[str, Decimal] = defaultdict(lambda: _ZERO)
        self._order_filled: defaultdict[str, Decimal] = defaultdict(lambda: _ZERO)
        self._changed = asyncio.Event()

    def observe(self, item: PrivateEvent | PrivateStreamStatus) -> None:
        if isinstance(item, PrivateStreamStatus):
            self.statuses[f"{item.state}:{item.reason}"] += 1
            if item.state == "resyncing":
                self.live = True
                if self._down_at is not None:
                    self.gaps_s.append(self._monotonic() - self._down_at)
                    self._down_at = None
            elif item.state in ("down", "closed"):
                self.live = False
                self.closed = self.closed or item.state == "closed"
                if item.state == "down" and self._down_at is None:
                    self._down_at = self._monotonic()
        else:
            self._event(item)
        self._changed.set()

    def _event(self, event: PrivateEvent) -> None:
        self.kinds[event.kind] += 1
        payload = event.payload
        if isinstance(payload, Execution):
            self._latency("execution", event.ts_ingest, payload.ts_exec)
            self._execution(payload)
        elif isinstance(payload, FastExecution):
            self._latency("execution_fast", event.ts_ingest, payload.ts_exec)
            self.fast_execs.add(payload.exec_id)
        elif isinstance(payload, Order):
            self._latency("order", event.ts_ingest, payload.updated_at)
            self._order(payload)
        elif isinstance(payload, Position):
            self._latency("position", event.ts_ingest, payload.updated_at)
            self.position = payload
        else:
            self._latency("wallet", event.ts_ingest, event.ts_event)
            self.wallet = payload
        self._latency("push", event.ts_ingest, event.ts_event)

    def _latency(self, kind: str, ingest_us: int, venue_us: int | None) -> None:
        offset = self._offset.read()
        if offset is None or venue_us is None:
            self.unmeasured += 1
            return
        self.latency_ms[kind].append(ingest_us / 1000 + offset - venue_us / 1000)

    def _execution(self, fill: Execution) -> None:
        if fill.exec_id in self.stream_execs:
            self.duplicates += 1
            return
        self.stream_execs.add(fill.exec_id)
        order = fill.exchange_order_id
        self._cum_exec[order] += fill.qty
        # 23 §S5: an order event already reported this fill, so the execution came after the
        # order transition it caused.
        if self._order_filled[order] >= self._cum_exec[order]:
            self.after_order += 1

    def _order(self, order: Order) -> None:
        key = order.exchange_order_id
        before = self.orders.get(key)
        previous = "none" if before is None else before.state
        if previous != order.state:
            self.transitions[f"{previous}->{order.state}"] += 1
        self.orders[key] = order
        self._order_filled[key] = max(self._order_filled[key], order.filled_qty)

    def rest_executions(self, fills: Sequence[Execution]) -> None:
        self.rest_execs.update(fill.exec_id for fill in fills)

    async def wait(self, predicate: Callable[[], bool], timeout_s: float) -> bool:
        """Until `predicate()` holds, re-checked on each item; `False` once `timeout_s` passed."""
        try:
            async with asyncio.timeout(timeout_s):
                while not predicate():
                    self._changed.clear()
                    await self._changed.wait()
        except TimeoutError:
            return predicate()
        return True

    def parity(self) -> dict[str, int]:
        stream, rest = self.stream_execs, self.rest_execs
        return {
            "stream": len(stream),
            "rest": len(rest),
            "both": len(stream & rest),
            "rest_only": len(rest - stream),
            "stream_only": len(stream - rest),
            "fast": len(self.fast_execs),
            "fast_only": len(self.fast_execs - stream),
            "duplicates": self.duplicates,
        }

    def ordering_counts(self) -> dict[str, int]:
        """The two counts #843 keeps apart, each answering its own question: a venue reorder
        (S5's execution before its order transition, broken: E29-T05's reorder buffer) and a
        dropped push (an execution only the backfill listed: ADR-0006's reconciliation)."""
        return {
            REORDER_COUNT: self.after_order,
            DROPPED_COUNT: len(self.rest_execs - self.stream_execs),
        }

    def summary(self) -> dict[str, object]:
        return {
            "kinds": dict(sorted(self.kinds.items())),
            "statuses": dict(sorted(self.statuses.items())),
            "latency_ms": {k: stats(v) for k, v in sorted(self.latency_ms.items())},
            "latency_unmeasured": self.unmeasured,
            "gaps": {"count": len(self.gaps_s), "seconds": stats(self.gaps_s)},
            "transitions": dict(sorted(self.transitions.items())),
            "parity": self.parity(),
            "ordering": {
                "execution_after_order": self.after_order,
                "executions": len(self.stream_execs),
                "order_events": self.kinds["order"],
            },
            "ordering_counts": self.ordering_counts(),
        }
