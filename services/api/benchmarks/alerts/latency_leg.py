"""E40-Q02 latency leg: the production `AlertEvaluator` over the E40-K01 corpus and tick stream.

Same 500 alerts x 20 symbols and the same seeded random walk as `harness.run_option`, but the
evaluator is the shipped `candleviewer.alerts.evaluator.AlertEvaluator` and the store is any
`FiringStore`: `SqliteFiringStore` here (local, development only) or the real Postgres
`SqlAlchemyAlertFiringStore` (the CI integration test). One sample per committed firing:
`perf_counter` when `record_firing` returned minus `perf_counter` when `process()` was called for
the tick that met the condition, so a sample is an upper bound on "condition met -> row committed"
(it includes the snapshot build and every earlier firing of the same tick). Storm summaries are
not samples. ``python -m benchmarks.alerts.latency_leg [ticks]`` prints the sqlite row.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import random
import sqlite3
import sys
import time
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import structlog

from benchmarks.alerts.harness import SYMBOLS, Clock, TickSource, corpus
from candleviewer.alerts.compiler import AlertCompiler
from candleviewer.alerts.evaluator import AlertEvaluator, AlertMetrics, AlertTick
from candleviewer.alerts.owners import OwnerGate
from candleviewer.alerts.ports import AlertRecord, FiringStore, MetricChildLike
from candleviewer.rules.vocabulary import default_registry

#: The ticket's budget for condition met -> `alert_deliveries` committed.
BUDGET_P95_S = 1.0
BUDGET_P99_S = 2.0


def alert_ir(cond: dict[str, Any]) -> dict[str, Any]:
    """A K01 corpus condition as an `AlertConditionIr` (the symbol rides on the metric ref)."""
    return {"ir_version": 1, "trigger": {"type": "on_price_update"}, "conditions": cond}


@dataclass(frozen=True, slots=True)
class LegAlert:
    """One leg alert: satisfies `AlertRecord` (every_time, no cooldown, in_app only)."""

    id: str
    owner_user_id: str
    name: str
    symbol: str | None
    condition_ir: dict[str, Any]
    condition_hash: str
    enabled: bool = True
    trigger_mode: str = "every_time"
    cooldown_seconds: int = 0
    snoozed_until: datetime | None = None
    expires_at: datetime | None = None
    severity: str = "info"
    channels: tuple[str, ...] = ("in_app",)
    message_template: str = ""
    last_fired_at: datetime | None = None


def leg_alerts(n_alerts: int = 500, n_distinct: int = 500, seed: int = 1) -> list[LegAlert]:
    """The K01 Q1 corpus as alert rows; ids and owners are placeholders the store may replace."""
    comp = AlertCompiler(default_registry())
    out = []
    for i, cond in enumerate(corpus(n_alerts, n_distinct, seed)):
        ir = alert_ir(cond)
        out.append(LegAlert(id=f"a{i:04d}", owner_user_id=f"u{i:04d}", name=f"leg-{i}",
                            symbol=cond["left"]["symbol"], condition_ir=ir,
                            condition_hash=comp.compile(ir).condition_hash))  # fmt: skip
    return out


class _Everyone:
    """`OwnerDirectory` for the local leg: every owner is active."""

    async def active_users(self, user_ids: Collection[str]) -> frozenset[str]:
        return frozenset(user_ids)


def everyone() -> OwnerGate:
    return OwnerGate(_Everyone())


class SqliteFiringStore:
    """In-memory sqlite stand-in: deliveries + outbox rows + the alert counters, ONE commit."""

    def __init__(self, alerts: Sequence[LegAlert]) -> None:
        self.rows = {a.id: a for a in alerts}
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(
            "create table a(id text primary key, fire_count int default 0, last_fired text);"
            "create table d(id integer primary key, alert text, channel text, status text,"
            " context text);"
            "create table o(delivery int unique);"
        )
        self.db.executemany("insert into a(id) values (?)", [(a,) for a in self.rows])
        self.db.commit()

    async def load_live(self) -> list[LegAlert]:
        return [a for a in self.rows.values() if a.enabled]

    async def get(self, alert_id: str) -> LegAlert | None:
        return self.rows.get(alert_id)

    async def record_firing(self, *, alert_id: str, user_id: str, channels: Sequence[str],
                            status: str, title: str, body: str, context: dict[str, Any],
                            fired_at: datetime, once: bool, bump: bool,
                            disarm_reason: str | None = None) -> list[int] | None:  # fmt: skip
        if bump:
            self.db.execute("update a set fire_count = fire_count + 1, last_fired = ? "
                            "where id = ?", (fired_at.isoformat(), alert_id))  # fmt: skip
        ids = []
        ctx = json.dumps(context, sort_keys=True, default=str)
        for ch in channels:
            cur = self.db.execute("insert into d(alert, channel, status, context) "
                                  "values (?, ?, ?, ?)", (alert_id, ch, status, ctx))  # fmt: skip
            did = int(cur.lastrowid or 0)
            ids.append(did)
            if status == "queued":
                self.db.execute("insert into o values (?)", (did,))
        self.db.commit()
        return ids

    def count(self, status: str | None = None) -> int:
        if status is None:
            return int(self.db.execute("select count(*) from d").fetchone()[0])
        q = "select count(*) from d where status = ?"
        return int(self.db.execute(q, (status,)).fetchone()[0])


class TimedStore:
    """Wraps a `FiringStore`; one latency sample per committed firing (not storm summaries)."""

    def __init__(self, inner: FiringStore, perf: Callable[[], float] = time.perf_counter) -> None:
        self._inner, self._perf = inner, perf
        self.tick_start = 0.0
        self.samples_s: list[float] = []
        self.statuses: dict[str, int] = {}

    async def load_live(self) -> Sequence[AlertRecord]:
        return await self._inner.load_live()

    async def get(self, alert_id: str) -> AlertRecord | None:
        return await self._inner.get(alert_id)

    async def record_firing(self, **kw: Any) -> list[int] | None:
        ids = await self._inner.record_firing(**kw)
        if ids is not None and not kw["context"].get("storm_summary"):
            self.samples_s.append(self._perf() - self.tick_start)
            self.statuses[kw["status"]] = self.statuses.get(kw["status"], 0) + len(ids)
        return ids


class _Child:
    def __init__(self) -> None:
        self.v = 0.0
        self.obs: list[float] = []

    def inc(self, amount: float = 1) -> None:
        self.v += amount

    def set(self, value: float) -> None:
        self.v = value

    def observe(self, amount: float) -> None:
        self.obs.append(amount)


@dataclass
class LegResult:
    store: str
    ticks: int
    alerts: int
    subscriptions: int = 0
    samples_s: list[float] = field(default_factory=list)
    statuses: dict[str, int] = field(default_factory=dict)
    eval_hist_count: int = 0
    wall_s: float = 0.0

    def pct(self, p: float) -> float:
        xs = sorted(self.samples_s)
        # Nearest-rank: the value at 1-based rank ceil(p * n).
        return xs[min(len(xs) - 1, max(0, math.ceil(p * len(xs)) - 1))] if xs else 0.0

    def row(self) -> dict[str, Any]:
        return {
            "store": self.store, "ticks": self.ticks, "alerts": self.alerts,
            "subscriptions": self.subscriptions, "committed_firings": len(self.samples_s),
            "statuses": dict(sorted(self.statuses.items())),
            "p50_ms": round(self.pct(0.5) * 1000, 3), "p95_ms": round(self.pct(0.95) * 1000, 3),
            "p99_ms": round(self.pct(0.99) * 1000, 3), "max_ms": round(self.pct(1.0) * 1000, 3),
            "budget_p95_ms": BUDGET_P95_S * 1000, "budget_p99_ms": BUDGET_P99_S * 1000,
            "wall_s": round(self.wall_s, 3),
        }  # fmt: skip


async def run_leg(
    store: FiringStore, *, name: str, ticks: int, owners: OwnerGate, seed: int = 7
) -> LegResult:
    """Drive the K01 tick stream (seeded walk, 5 ms of exchange time a tick) through the real
    evaluator, one `process()` per tick, in order. Storm/cooldown gates stay at their defaults."""
    clk = Clock()
    src = TickSource(clk, seed)
    timed = TimedStore(store)
    children: dict[tuple[str, tuple[str, ...]], _Child] = {}

    def sink(n: str, labels: tuple[str, ...]) -> MetricChildLike:
        return children.setdefault((n, labels), _Child())

    ev = AlertEvaluator(timed, src, owners=owners, metrics=AlertMetrics(sink), clock=clk)
    await ev.warm_up()
    res = LegResult(name, ticks, len(ev.alerts), subscriptions=len(ev.subscriptions))
    rng = random.Random(seed)  # the symbol order, as in harness.run_option
    w0 = time.perf_counter()
    for _ in range(ticks):
        sym = SYMBOLS[rng.randrange(len(SYMBOLS))]
        clk.t += 5
        src.step(sym)
        timed.tick_start = time.perf_counter()
        await ev.process(AlertTick("on_price_update", clk.t, sym))
    await ev.flush_storms(force=True)
    res.wall_s = time.perf_counter() - w0
    res.samples_s, res.statuses = timed.samples_s, timed.statuses
    hist = children.get(("cv_alert_eval_latency_seconds", ()))
    res.eval_hist_count = 0 if hist is None else len(hist.obs)
    return res


def main(ticks: int = 20_000) -> dict[str, Any]:
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))
    alerts = leg_alerts()
    res = asyncio.run(run_leg(SqliteFiringStore(alerts), name="sqlite-memory", ticks=ticks,
                              owners=everyone()))  # fmt: skip
    return res.row()


if __name__ == "__main__":
    print(json.dumps(main(int(sys.argv[1]) if len(sys.argv) > 1 else 20_000), indent=2))
