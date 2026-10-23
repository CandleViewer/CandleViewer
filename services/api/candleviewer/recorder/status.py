"""`RecordingStatusCache`: the recording status that `GET /recording/status` serves and the
`recorder` WS topic carries (E16-T08, #492; 22 `getRecordingStatus`, 23 §6.2.2), computed once a
second for every reader.

One supervised task reads the bound runtime's `status()`, the disk budget's last `report()` and
`effective_level`, and the policy in force, then renders the REST body twice: the Owner's, and the
R-I2 view everyone else reads (ruling Q6; `control.restricted_view`). A read never computes: it
takes the last body, or `None` before the first (503). Until a runtime is bound (#2188), the status
is `not_deployed` and names nothing only a runtime knows (no rows, rates or policy). A computation
that fails keeps the last snapshot, and `recorder_status_cache_age_seconds` shows its age. The
restricted view carries no `position_open` and no endpoint, so no path character either."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, Protocol

import structlog

from candleviewer.observability import spawn
from candleviewer.recorder import control as rc
from candleviewer.recorder.budget import RECORDED_TIERS, BudgetConfig
from candleviewer.recorder.metrics import recorder_status_cache_age_seconds
from candleviewer.recorder.models import DiskPressureLevel, StorageUsage

if TYPE_CHECKING:
    from candleviewer.recorder.policy import PolicyConfig

#: One computation a second: the `recorder` topic's 1 000 ms cadence (23 §6.2).
REFRESH_S: Final = 1.0
#: A runtime status read slower than this fails its pass; the last snapshot is kept.
STATUS_TIMEOUT_S: Final = 0.5
_HALT: Final = int(DiskPressureLevel.HALT)
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
_MS: Final = timedelta(milliseconds=1)
#: Per-symbol fields sent as they are, once the runtime knows them.
_PLAIN: Final = ("lag_ms", "rows_last_hour", "dropped_messages", "resyncs_last_hour", "lingering")


class StatusSource(Protocol):
    """The bound runtime's `RecordingControl.status`."""

    async def status(self) -> rc.ControlStatus: ...


class Budget(Protocol):
    """What is read of `DiskBudget`."""

    @property
    def config(self) -> BudgetConfig: ...
    @property
    def effective_level(self) -> DiskPressureLevel: ...
    @property
    def accelerate_retention(self) -> bool: ...
    @property
    def recording_refused(self) -> bool: ...
    def report(self) -> StorageUsage | None: ...


@dataclass(frozen=True, slots=True)
class StatusSnapshot:
    """One second's status: `status` is `None` until a runtime is bound, `restricted` holds its
    entries in the R-I2 view, and `policy` and `storage` are `None` when nothing gives them."""

    generated_at: datetime
    status: rc.ControlStatus | None
    restricted: tuple[rc.RecordedEntry, ...]
    policy: dict[str, int | bool] | None
    storage: dict[str, Any] | None
    #: The REST body: the Owner's, then the restricted one.
    bodies: tuple[dict[str, Any], dict[str, Any]] = field(repr=False)


def iso(at: datetime) -> str:
    """RFC 3339 in UTC with `Z`, to the millisecond when it has a fraction (22's examples)."""
    spec = "milliseconds" if at.microsecond else "seconds"
    return at.astimezone(UTC).isoformat(timespec=spec).replace("+00:00", "Z")


def epoch_ms(at: datetime) -> int:
    return (at - _EPOCH) // _MS


def policy_settings(policy: PolicyConfig, budget: BudgetConfig) -> dict[str, int | bool]:
    """`RecorderPolicySettings`: integers within the contract's bounds (hand-off item 3). A delay
    rounds up, so a client never counts down to before the server acts."""

    def pct(value: int) -> int:
        return min(100, max(1, value))

    return {
        "autostart_delay_s": max(0, math.ceil(policy.autostart_delay_s)),
        "autostop_grace_s": max(0, math.ceil(policy.autostop_grace_s)),
        "max_symbols": max(1, policy.max_symbols),
        "warn_pct": pct(budget.warn_pct),
        "autostop_pct": pct(budget.autostop_pct),
        "halt_pct": pct(budget.halt_pct),
        "autorecord_enabled": policy.autorecord_enabled,
    }


def storage_view(budget: Budget) -> dict[str, Any]:
    """The WS `storage` object. `level` is the effective step (3 exactly when the write gate is
    closed, a refused volume too), never the ladder's own (hand-off item 5); the measured fields
    join once the budget has a report."""
    level = int(budget.effective_level)
    closed = level == _HALT
    reason = ("volume_refused" if budget.recording_refused else "disk_halt") if closed else None
    out: dict[str, Any] = {"level": level, "write_gate": "closed" if closed else "open"}
    out |= {"write_gate_reason": reason, "accelerate_retention": budget.accelerate_retention}
    if (report := budget.report()) is not None:
        full = report.projected_full_at
        out |= {
            "disk_free_bytes": report.disk_free_bytes,
            "daily_growth_bytes": report.daily_growth_bytes,
            "cap_bytes": report.cap_bytes,
            "used_bytes": sum(t.used_bytes for t in report.tiers if t.tier in RECORDED_TIERS),
            "projected_full_at_ms": None if full is None else epoch_ms(full),
        }
    return out


def _row(e: rc.RecordedEntry) -> dict[str, Any]:
    row: dict[str, Any] = {"symbol": e.symbol, "state": e.state}
    row |= {k: v for k in _PLAIN if (v := getattr(e, k)) is not None}
    if e.last_event_at is not None:
        row["last_event_at"] = iso(e.last_event_at)
    if e.linger_until is not None:
        row["linger_until"] = iso(e.linger_until)
    if e.refusal is not None:
        row["refusal"] = e.refusal
    return row


def _link(c: rc.Connection, restricted: bool) -> dict[str, Any]:
    since = None if c.connected_since is None else iso(c.connected_since)
    out = {"state": c.state, "subscribed_topics": c.subscribed_topics, "connected_since": since}
    out |= {"reconnects_last_hour": c.reconnects_last_hour, "last_ping_ms": c.last_ping_ms}
    return out if restricted else {"endpoint": c.endpoint} | out  # an endpoint holds a path


def _body(
    at: datetime,
    status: rc.ControlStatus | None,
    entries: tuple[rc.RecordedEntry, ...],
    policy: dict[str, int | bool] | None,
    restricted: bool,
) -> dict[str, Any]:
    links = () if status is None else status.connections
    body: dict[str, Any] = {
        "overall": "not_deployed" if status is None else status.overall,
        "connections": [_link(c, restricted) for c in links],
        "symbols": [_row(e) for e in entries],
        "generated_at": iso(at),
        "role_restricted": restricted,
    }
    if status is not None:
        body["ingest_rate_msgs_per_sec"] = status.ingest_rate_msgs_per_sec
        body["write_backlog_rows"] = status.write_backlog_rows
    if policy is not None:
        body["policy"] = policy
    return body


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class RecordingStatusCache:
    """Computes the status once a second on one task (`start`/`stop`, which `WsRuntime` drives);
    readers take the last snapshot (see the module docstring)."""

    def __init__(
        self,
        source: Callable[[], StatusSource | None],
        budget: Budget | None,
        *,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        interval_s: float = REFRESH_S,
    ) -> None:
        """`source` gives the bound runtime, `None` until one is; `budget` is `None` on the fake
        backend (no policy, no storage)."""
        self._source, self._budget = source, budget
        self._clock, self._wall, self._sleep, self._interval = clock, wall, sleep, interval_s
        self._snapshot: StatusSnapshot | None = None
        self._at = -math.inf
        self._listeners: list[Callable[[StatusSnapshot], None]] = []
        self._task: asyncio.Task[None] | None = None
        recorder_status_cache_age_seconds.set_function(self.age)  # the cache built last (one app)

    def age(self) -> float:
        """Seconds since the last computation; `+Inf` before the first."""
        return self._clock() - self._at

    def snapshot(self) -> StatusSnapshot | None:
        return self._snapshot

    def body(self, restricted: bool) -> dict[str, Any] | None:
        """The last REST body for the Owner, or (`restricted`) for everyone else."""
        snapshot = self._snapshot
        return None if snapshot is None else snapshot.bodies[restricted]

    def listen(self, listener: Callable[[StatusSnapshot], None]) -> None:
        """Call `listener` with each new snapshot, on the computing task."""
        self._listeners.append(listener)

    async def refresh_once(self) -> None:
        source, budget, status = self._source(), self._budget, None
        if source is not None:
            async with asyncio.timeout(STATUS_TIMEOUT_S):
                status = await source.status()
        entries = () if status is None else status.entries
        restricted = tuple(v for e in entries if (v := rc.restricted_view(e)) is not None)
        policy = None
        if status is not None and status.policy is not None and budget is not None:
            policy = policy_settings(status.policy, budget.config)
        at = self._wall()
        bodies = (
            _body(at, status, entries, policy, False),
            _body(at, status, restricted, policy, True),
        )
        storage = None if budget is None else storage_view(budget)
        snapshot = StatusSnapshot(at, status, restricted, policy, storage, bodies)
        self._snapshot, self._at = snapshot, self._clock()
        for listener in tuple(self._listeners):
            listener(snapshot)

    def start(self) -> None:
        """Start the computing task (idempotent)."""
        if self._task is None:
            self._task = spawn(self._run(), name="recorder-status-cache")

    async def stop(self) -> None:
        """Cancel the task and wait for it (idempotent)."""
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.wait({task})  # never raises; our own cancel is consumed

    async def _run(self) -> None:
        while True:
            try:
                await self.refresh_once()
            except Exception as exc:  # the last snapshot stays; its age shows the gap
                _log().error("recording_status_refresh_failed", error=type(exc).__name__)
            await self._sleep(self._interval)
