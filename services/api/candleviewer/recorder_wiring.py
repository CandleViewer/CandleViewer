"""Composition of the recorder (#2188 S4b, 20-architecture.md §3.8): the policy, the sessions and
the stream writer under one `RecorderRuntime`, which the lifespan's supervisor starts. A request
never starts it: the tick's records would stamp that request's id. Not a module (C-3.1): the
composition root injects every store, the audit emitter and the adapter's topic vocabulary, so this
file holds no driver. Nothing here does I/O.

* One env feeds the policy, the sessions and the writer, and none has a default (C-2.11, #2726).
* A set change reaches the sessions (with the entry's streams, which the event lacks), then the
  writer, then the bus: a session row exists before the writer attaches its gaps to it.
* The policy awaits its store under its lock, so each call is bounded here (C-2.18).
* With no `DiskBudget` (the fake backend) the write gate and the auto-record refusal read false.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, cast

import psutil
import structlog

from candleviewer.bus.models import Topic
from candleviewer.observability.health_probes import SystemEventWriter
from candleviewer.recorder.budget import DiskBudget
from candleviewer.recorder.control import RecordedRows
from candleviewer.recorder.models import (
    PRIORITY,
    EffectiveEntry,
    RecorderCapRefused,
    RecorderSetChanged,
)
from candleviewer.recorder.policy import (
    AuditSink,
    BusPublisher,
    PolicyConfig,
    RecordedStore,
    RecordingPolicy,
)
from candleviewer.recorder.runtime import RecorderRuntime, RuntimeBounds
from candleviewer.recorder.sessions import (
    Invalidate,
    SessionConfig,
    SessionManager,
    SessionStore,
    TopicResolver,
)
from candleviewer.recorder.writer import (
    DiskGate,
    RecorderStore,
    RowSink,
    SinkFactory,
    Stream,
    StreamWriter,
    writer_config_from_settings,
)
from candleviewer.settings import QUESTDB_PG_DEFAULT_PORT, Settings
from candleviewer.storage.questdb.schemas import ALL_SCHEMAS
from candleviewer.storage.questdb.wiring import LazyPgWire, TcpIlpTransport, build_hot_tier_writer

#: Bound on one call of the policy's store (the sessions and the writer bound their own).
STORE_TIMEOUT_S: Final = 5.0
#: S4a's recommended bounds: a WAL replay of up to 1 GiB, one whole startup, one tick step, the
#: retry's doubling from 1 s to a minute, and N: the warm-up gate closed for 10 minutes.
BOUNDS: Final = RuntimeBounds(
    start_timeout_s=900, startup_timeout_s=120, tick_timeout_s=30, retry_base_s=1, retry_cap_s=60,
    max_attempts=5, gate_closed_alert_s=600,
)  # fmt: skip


def logger() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)  # type: ignore[no-any-return]  # structlog returns Any


def _process_start_us() -> int:
    """When the OS started this process: the end of each crash gap, not the moment of the build."""
    return int(psutil.Process().create_time() * 1_000_000)


@dataclass(frozen=True, slots=True)
class Clocks:
    """Every clock the recorder reads, injected for the tests. `wall_s` serves the policy, the
    sessions and the writer (deadlines and records are wall-clock µs, E16-T02 deviation Q4)."""

    wall_s: Callable[[], float] = time.time
    mono_s: Callable[[], float] = time.monotonic
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    rng: Callable[[], float] = random.SystemRandom().random
    process_start_us: int = field(default_factory=_process_start_us)


SYSTEM: Final = Clocks()


class NoPositionSource:
    """No positions source is deployed (E29-T06 provides one): the startup opens its warm-up gate
    on none, logs it and reports it in health (Q1). A source is built for one env, as this is."""

    def __init__(self, env: str) -> None:
        self.env = env

    async def open_positions(self) -> None:
        return None


async def _no_b11_restore() -> None:
    """No snapshot source yet (#2701, `statechart_persistence` is `None`): a restart resumes the
    rows, not the charts' own state."""
    logger().warning("recorder_b11_restore_not_wired")


class BoundedStore:
    """The policy's store with each call bounded: `RecordedStore`'s members all are, so a new one
    is too. A call that outlives `timeout_s` raises `TimeoutError`, leaving the lock to the next."""

    def __init__(self, store: RecordedStore, timeout_s: float) -> None:
        self._store, self._timeout_s = store, timeout_s

    def __getattr__(self, name: str) -> Callable[..., Awaitable[Any]]:
        call = getattr(self._store, name)

        async def bounded(*args: Any, **kwargs: Any) -> Any:
            async with asyncio.timeout(self._timeout_s):
                return await call(*args, **kwargs)

        return bounded


class _FanOut:
    """The policy's bus: a set change goes to the sessions, the writer, then the bus. The two are
    bound once the policy exists, whose gate and entries they read."""

    sessions: SessionManager
    writer: StreamWriter
    entries: Callable[[], Mapping[str, EffectiveEntry]]

    def __init__(self, bus: BusPublisher) -> None:
        self._bus = bus

    async def publish(self, topic: Topic, event: RecorderSetChanged | RecorderCapRefused) -> None:
        if isinstance(event, RecorderSetChanged):
            entry = self.entries().get(event.symbol)  # the event carries no streams: the entry does
            try:  # a failing store must not leave the symbol on paper only: the tick heals it
                await self.sessions.on_set_changed(event, entry.streams if entry else ())
            except Exception as exc:  # never a CancelledError
                logger().error("recorder_fanout_sessions_failed", symbol=event.symbol,
                               error=type(exc).__name__)  # fmt: skip
            self.writer.on_set_changed(event)
        await self._bus.publish(topic, event)


@dataclass(frozen=True, slots=True)
class ComposedRecorder:
    """#492's `RecorderWiring` (policy, rows, budget, env) and the parts the runtime runs."""

    policy: RecordingPolicy
    rows: RecordedRows
    budget: DiskBudget | None
    env: str
    sessions: SessionManager
    writer: StreamWriter
    runtime: RecorderRuntime
    on_ready: Callable[[], Awaitable[None]]


def policy_config(settings: Settings) -> PolicyConfig:
    """The one `PolicyConfig`: the policy runs with it and #492's control reads it, so the two
    cannot drift (a NULL retention read as a raise would fail open, SEC-m1)."""
    return PolicyConfig(
        autostart_delay_s=float(settings.recorder_autostart_delay_s),
        autostop_grace_s=float(settings.recorder_autostop_grace_s),
        autorecord_enabled=settings.recorder_autorecord_enabled,
        max_symbols=settings.recorder_max_symbols,
        default_retention_days=settings.recorder_retention_days,
    )


def questdb_sinks(settings: Settings) -> SinkFactory:
    """One ILP writer per stream, each with its own wire for the readiness probe: a stalled stream
    never delays another. Nothing connects before a lane's first flush."""
    ilp_host, _, ilp_port = settings.questdb_ilp.partition(":")
    pg_host, _, pg_port = settings.questdb_pg.partition(":")

    def sink(_stream: Stream) -> RowSink:
        wire = LazyPgWire(
            pg_host, int(pg_port or QUESTDB_PG_DEFAULT_PORT), settings.questdb_pg_user,
            settings.questdb_pg_password.get_secret_value(), name="storage",
        )  # fmt: skip
        return build_hot_tier_writer(
            TcpIlpTransport(ilp_host, int(ilp_port or 9009)), ALL_SCHEMAS, wire
        )

    return sink


def _disk(budget: DiskBudget | None) -> tuple[Callable[[], bool], Callable[[], bool]]:
    """`(halted, refuses_auto_record)`: the budget's flags, read per row and per start."""
    if budget is None:
        return (lambda: False), (lambda: False)
    return (lambda: budget.halted), (lambda: budget.refuses_auto_record)


def build_recorder(
    settings: Settings,
    config: PolicyConfig,
    *,
    recorded: RecordedStore,
    sessions: SessionStore,
    counters: RecorderStore,
    rows: RecordedRows,
    audit: AuditSink,
    bus: BusPublisher,
    budget: DiskBudget | None,
    invalidate: Invalidate,
    topics: TopicResolver,
    sinks: SinkFactory,
    events: SystemEventWriter,
    clocks: Clocks = SYSTEM,
    bounds: RuntimeBounds = BOUNDS,
    restore_b11: Callable[[], Awaitable[None]] = _no_b11_restore,
) -> ComposedRecorder:
    """The recorder for `settings.environment`, its runtime not started (the supervisor does)."""
    env = settings.environment.value
    halted, refuses = _disk(budget)

    def wall_us() -> int:
        return int(clocks.wall_s() * 1_000_000)

    fan_out = _FanOut(bus)
    policy = RecordingPolicy(
        bus=fan_out, audit=audit, env=env, now=clocks.wall_s, disk_refuses=refuses,
        recorded=cast(RecordedStore, BoundedStore(recorded, STORE_TIMEOUT_S)), config=config,
    )  # fmt: skip
    manager = SessionManager(
        sessions, now_us=wall_us, audit=audit, config=SessionConfig(env=env),
        invalidate=invalidate, topics=topics,
    )  # fmt: skip
    writer = StreamWriter(
        sinks, counters, events, writer_config_from_settings(settings),
        clock=clocks.mono_s, wall_clock_us=wall_us,
        disk_gate=DiskGate(halted=halted, position_open=policy.position_open),
    )  # fmt: skip
    fan_out.sessions, fan_out.writer, fan_out.entries = manager, writer, policy.effective_set
    policy.observe_states(manager.on_b11_state)

    async def open_missing() -> None:
        """Open the session of each effective symbol that has none, with the entry's streams: a
        restored chart published nothing (S3a findings 1 and 2) and a fan-out whose sessions step
        failed left one open (SEC-B1). A symbol that fails is logged and starves no other."""
        for symbol, entry in policy.effective_set().items():
            if manager.live_session(symbol) is not None:
                continue
            try:
                # mirrors policy.py `_publish` (~1103) and `_entry` (~1136): no helper exists
                event = RecorderSetChanged(
                    symbol=symbol, change="added", reason=entry.reason, reasons=entry.reasons,
                    priority=PRIORITY[entry.reason], auto_evictable=entry.reason != "manual",
                    ts_event=int(clocks.wall_s() * 1e6),
                )  # fmt: skip
                await manager.on_set_changed(event, entry.streams)
            except Exception as exc:
                logger().error("recorder_session_open_failed", symbol=symbol,
                               error=type(exc).__name__)  # fmt: skip

    async def on_ready() -> None:
        """Seed the writer with the restored set, then open what it lacks."""
        writer.seed(list(policy.effective_set()))
        await open_missing()

    runtime = RecorderRuntime(
        policy=policy, sessions=manager, writer=writer, restore_b11=restore_b11,
        seed=NoPositionSource(env), process_start_us=clocks.process_start_us, env=env,
        clock=clocks.mono_s, sleep=clocks.sleep, rng=clocks.rng, bounds=bounds, on_ready=on_ready,
        heal=open_missing,
    )  # fmt: skip
    return ComposedRecorder(policy, rows, budget, env, manager, writer, runtime, on_ready)
