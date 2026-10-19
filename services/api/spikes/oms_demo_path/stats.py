"""Pure measurement maths of the E29-K01 harness: no I/O, no clock.

- `quantiles`: nearest-rank p50/p95/p99.
- `items_from_frame`: one private-stream frame into flat `WsItem`s.
- `check_ordering`: 23-ws-protocol S5. An execution received after the `order` push it caused
  (the first push whose `cumExecQty` covers it) is a violation; E29-T05 then needs a reorder
  buffer keyed on `(ts_exec, seq)`.
- `backfill_only`: executions the REST backfill lists that the stream never delivered.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Final

EXEC_TOPICS: Final = ("execution", "execution.fast")


@dataclass(frozen=True, slots=True)
class Quantiles:
    n: int
    p50: float | None
    p95: float | None
    p99: float | None


def quantiles(values: Iterable[float]) -> Quantiles:
    data = sorted(values)

    def rank(q: int) -> float | None:
        return data[max(0, math.ceil(q / 100 * len(data)) - 1)] if data else None

    return Quantiles(len(data), rank(50), rank(95), rank(99))


@dataclass(frozen=True, slots=True)
class WsItem:
    """One `data` element of a private push. `recv_ms` is the receipt time on the exchange clock
    (local wall clock plus the measured offset); `exch_ms` is `execTime` (executions) or
    `updatedTime`, else the frame's `creationTime`; `qty` is `execQty` or `cumExecQty`."""

    recv_seq: int
    recv_ms: int
    topic: str
    symbol: str
    order_id: str
    link_id: str
    exec_id: str
    status: str
    qty: Decimal | None
    exch_ms: int | None
    seq: int | None


def _int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return int(value) if isinstance(value, str) and value.isascii() and value.isdigit() else None


def as_decimal(value: object) -> Decimal | None:
    try:
        return Decimal(value) if isinstance(value, str) and value else None
    except InvalidOperation:
        return None


def _str(item: Mapping[str, Any], key: str) -> str:
    value = item.get(key)
    return value if isinstance(value, str) else ""


def items_from_frame(frame: Mapping[str, Any], *, recv_seq: int, recv_ms: int) -> list[WsItem]:
    topic, data = frame.get("topic"), frame.get("data")
    if not isinstance(topic, str) or not isinstance(data, list):
        return []
    is_exec = topic in EXEC_TOPICS
    created = _int(frame.get("creationTime"))
    out: list[WsItem] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        stamp = _int(item.get("execTime" if is_exec else "updatedTime"))
        out.append(
            WsItem(
                recv_seq=recv_seq,
                recv_ms=recv_ms,
                topic=topic,
                symbol=_str(item, "symbol"),
                order_id=_str(item, "orderId"),
                link_id=_str(item, "orderLinkId"),
                exec_id=_str(item, "execId"),
                status=_str(item, "orderStatus"),
                qty=as_decimal(item.get("execQty" if is_exec else "cumExecQty")),
                exch_ms=stamp if stamp is not None else created,
                seq=_int(item.get("seq")),
            )
        )
    return out


def latencies(items: Iterable[WsItem]) -> dict[str, Quantiles]:
    """Exchange stamp to local receipt, in ms, per topic."""
    by_topic: dict[str, list[float]] = {}
    for it in items:
        if it.exch_ms is not None:
            by_topic.setdefault(it.topic, []).append(float(it.recv_ms - it.exch_ms))
    return {topic: quantiles(values) for topic, values in sorted(by_topic.items())}


@dataclass(frozen=True, slots=True)
class OrderingReport:
    executions: int
    violations: int
    unmatched: int
    lag_ms: Quantiles


def check_ordering(items: Sequence[WsItem], exec_topic: str) -> OrderingReport:
    """`items` in receipt order. Executions are deduped by `execId` (first receipt) and summed
    per order in `(execTime, seq)` order; each is caused by the first `order` push, in receipt
    order, whose `cumExecQty` reaches the running sum. A push received before its execution is a
    violation (lag = how much later the execution came); no such push is `unmatched`."""
    pushes: dict[str, list[WsItem]] = {}
    execs: dict[str, dict[str, WsItem]] = {}
    for it in items:
        if it.topic == "order" and it.qty is not None:
            pushes.setdefault(it.order_id, []).append(it)
        elif it.topic == exec_topic and it.exec_id and it.order_id and it.qty is not None:
            execs.setdefault(it.order_id, {}).setdefault(it.exec_id, it)
    total = violations = unmatched = 0
    lags: list[float] = []
    for order_id, by_exec in execs.items():
        cumulative = Decimal(0)
        for e in sorted(by_exec.values(), key=lambda x: (x.exch_ms or 0, x.seq or 0, x.recv_seq)):
            total += 1
            cumulative += e.qty or 0
            push = next((p for p in pushes.get(order_id, ()) if (p.qty or 0) >= cumulative), None)
            if push is None:
                unmatched += 1
            elif push.recv_seq < e.recv_seq:
                violations += 1
                lags.append(float(e.recv_ms - push.recv_ms))
    return OrderingReport(total, violations, unmatched, quantiles(lags))


def backfill_only(rest: Mapping[str, str], streamed: Collection[str]) -> dict[str, int]:
    """REST executions (`execId` to `execType`) the stream never delivered, counted by type."""
    missing: dict[str, int] = {}
    for exec_id, exec_type in rest.items():
        if exec_id not in streamed:
            missing[exec_type] = missing.get(exec_type, 0) + 1
    return missing
