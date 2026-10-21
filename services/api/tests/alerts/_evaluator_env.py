"""In-memory fakes for the E40-T03 evaluator tests (no DB, no network, fake clock)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from typing import Any

from candleviewer.alerts.compiler import AlertCompiler
from candleviewer.alerts.evaluator import AlertEvaluator, AlertMetrics
from candleviewer.alerts.gating import StormSuppressor
from candleviewer.rules.evaluator import MetricValue, metric_key
from candleviewer.rules.ir.models import MetricRef
from candleviewer.rules.vocabulary import default_registry
from tests.alerts._owners_env import allow

COMPILER = AlertCompiler(default_registry())
T0 = 1_790_000_000_000  # ms, exchange time


def ir(op: str = "gt", const: int = 65000, trigger: str = "on_price_update",
       metric: str = "price", **trig: Any) -> dict[str, Any]:  # fmt: skip
    return {
        "ir_version": 1,
        "trigger": {"type": trigger, **trig},
        "conditions": {"node_id": "c1", "op": op, "left": {"metric": metric},
                       "right": {"const": const}},
    }  # fmt: skip


@dataclass(frozen=True)
class Row:
    id: str
    owner_user_id: str = "u1"
    name: str = "a"
    symbol: str | None = "BTCUSDT"
    condition_ir: dict[str, Any] = field(default_factory=ir)
    condition_hash: str = ""
    enabled: bool = True
    trigger_mode: str = "every_time"
    cooldown_seconds: int = 0
    snoozed_until: datetime | None = None
    expires_at: datetime | None = None
    severity: str = "info"
    channels: tuple[str, ...] = ("in_app",)
    message_template: str = ""
    last_fired_at: datetime | None = None
    last_bar_open_ms: int | None = None


def row(id: str, **kw: Any) -> Row:
    r = Row(id, **kw)
    return replace(r, condition_hash=COMPILER.compile(r.condition_ir).condition_hash)


@dataclass
class Delivery:
    id: int
    alert_id: str
    user_id: str
    channel: str
    status: str
    title: str
    context: dict[str, Any]


class FakeStore:
    """Mimics the one-transaction firing semantics incl. the `once` conditional update."""

    def __init__(self, *rows: Row) -> None:
        self.rows = {r.id: r for r in rows}
        self.deliveries: list[Delivery] = []
        self.outbox: list[int] = []
        self.fire_count: dict[str, int] = {}

    async def load_live(self) -> list[Row]:
        return [r for r in self.rows.values() if r.enabled]

    async def get(self, alert_id: str) -> Row | None:
        return self.rows.get(alert_id)

    async def record_firing(self, *, alert_id: str, user_id: str, channels: Sequence[str],
                            status: str, title: str, body: str, context: dict[str, Any],
                            fired_at: datetime, once: bool, bump: bool,
                            disable: bool = False) -> list[int] | None:  # fmt: skip
        r = self.rows[alert_id]
        if once or disable:
            if not r.enabled:
                return None
            r = replace(r, enabled=False)
        if bump:
            r = replace(r, last_fired_at=fired_at)
        if context.get("bar_open_ms") is not None:
            r = replace(r, last_bar_open_ms=int(context["bar_open_ms"]))
            self.fire_count[alert_id] = self.fire_count.get(alert_id, 0) + 1
        self.rows[alert_id] = r
        ids = []
        for ch in channels:
            d = Delivery(len(self.deliveries) + 1, alert_id, user_id, ch, status, title, context)
            self.deliveries.append(d)
            ids.append(d.id)
            if status == "queued":
                self.outbox.append(d.id)
        return ids


class Source:
    def __init__(self) -> None:
        self.values: dict[str, MetricValue] = {}

    def set(self, metric: str, value: Any, ts: int, reason: str | None = None) -> None:
        v = None if value is None else Decimal(value)
        self.values[metric_key(MetricRef(metric=metric))] = MetricValue(v, ts, 0, reason)

    def read(self, ref: MetricRef) -> MetricValue:
        return self.values.get(metric_key(ref)) or MetricValue(None, 0, 0, "warmup")


class Clock:
    def __init__(self, now: int = T0) -> None:
        self.now = now

    def __call__(self) -> int:
        return self.now


class Counter:
    def __init__(self) -> None:
        self.v = 0.0

    def inc(self, amount: float = 1) -> None:
        self.v += amount

    def set(self, value: float) -> None:
        self.v = value

    def observe(self, amount: float) -> None:
        self.v += 1


class Metrics:
    def __init__(self) -> None:
        self.c: dict[tuple[str, tuple[str, ...]], Counter] = {}

    def __call__(self, name: str, labels: tuple[str, ...]) -> Counter:
        return self.c.setdefault((name, labels), Counter())

    def get(self, name: str, *labels: str) -> float:
        c = self.c.get((name, labels))
        return 0.0 if c is None else c.v


def make(*rows: Row, **kw: Any) -> tuple[AlertEvaluator, FakeStore, Source, Clock, Metrics]:
    store, src, clock, m = FakeStore(*rows), Source(), Clock(), Metrics()
    kw.setdefault("storm", StormSuppressor())
    kw.setdefault("owners", allow())
    ev = AlertEvaluator(store, src, metrics=AlertMetrics(m), clock=clock, **kw)
    return ev, store, src, clock, m
