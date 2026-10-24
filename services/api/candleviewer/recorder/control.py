"""`RecordingControl`, the recorder's port for the recording routes and WS topic (E16-T08, #492).
Until a runtime is bound (#2188), only reads exist: `StoredRecordingControl` maps Postgres rows
from the row port `RecordedRows` (M10), and what only a runtime knows (lingering, refusals, size,
rows, lag) stays unset, never guessed. Writes have no implementation yet (503). The restricted
view (`HIDDEN_CAUSES`, `restricted_view`) is defined here once, for the routes and the topic."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, Literal, Protocol

from candleviewer.recorder.models import ORDERBOOK_DEPTHS, Actor

if TYPE_CHECKING:
    from candleviewer.recorder.policy import PolicyConfig

RecordReason = Literal[
    "manual", "chart_open", "position_open", "rule_dependency", "alert_dependency"
]
RecordingState = Literal[
    "idle", "starting", "recording", "degraded", "stopping", "stopped", "error"
]
#: Why the next start (`symbol_cap`, `disk_pressure`) or stop (a trigger) is refused.
Refusal = Literal["symbol_cap", "disk_pressure", "chart_open", "position_open"]
#: Session states whose start is the entry's `started_at` (none while `starting`).
_STARTED: Final = frozenset({"recording", "degraded", "stopping", "stopped", "error"})
#: Restricted refusal parity (R-I2, E16-FR-07, ruling Q6): the causes a restricted view never
#: names, as a reason or as a refusal. Each reads as if it did not hold, so no restricted body
#: differs by which of them holds, or whether one does; the Owner's view names them.
HIDDEN_CAUSES: Final[frozenset[str]] = frozenset({"position_open"})


@dataclass(frozen=True, slots=True)
class RecordedEntry:  # `RecordedSymbol`; `reasons` is never empty, top first
    id: str
    symbol: str
    reasons: tuple[RecordReason, ...]
    state: RecordingState
    pinned: bool = False
    streams: tuple[str, ...] = ()
    depth: int = 200
    started_at: datetime | None = None
    retention_days: int | None = None
    added_by: str | None = None
    lingering: bool | None = None
    linger_until: datetime | None = None
    refusals: tuple[Refusal, ...] = ()  # every cause refusing a start or stop now, top first
    disk_bytes: int | None = None
    rows_last_hour: int | None = None
    lag_ms: int | None = None
    dropped_messages: int | None = None  # the status fields (`RecordingStatus.symbols`)
    resyncs_last_hour: int | None = None
    last_event_at: datetime | None = None

    @property
    def reason(self) -> RecordReason:
        return self.reasons[0]

    @property
    def refusal(self) -> Refusal | None:
        return self.refusals[0] if self.refusals else None


@dataclass(frozen=True, slots=True)
class EntryQuery:  # after `after`, a `(symbol, id)` key, leaving out entries held only by `hidden`
    state: RecordingState | None = None
    reason: RecordReason | None = None
    pinned: bool | None = None
    hidden: frozenset[str] = frozenset()
    after: tuple[str, str] | None = None
    limit: int = 100


@dataclass(frozen=True, slots=True)
class EntryPage:
    items: tuple[RecordedEntry, ...]
    has_more: bool


@dataclass(frozen=True, slots=True)
class EntrySpec:  # an add or an update; `None` keeps a setting (or takes its default)
    streams: tuple[str, ...] | None = None
    depth: int | None = None
    pinned: bool | None = None
    retention_days: int | None = None


@dataclass(frozen=True, slots=True)
class Connection:  # one upstream stream of `RecordingStatus.connections`
    endpoint: str
    state: Literal["connecting", "connected", "degraded", "disconnected"]
    subscribed_topics: int
    connected_since: datetime | None
    reconnects_last_hour: int
    last_ping_ms: int


@dataclass(frozen=True, slots=True)
class ControlStatus:  # a bound runtime's live status, before the R-I2 view
    entries: tuple[RecordedEntry, ...] = ()
    ingest_rate_msgs_per_sec: int = 0
    write_backlog_rows: int = 0
    overall: Literal["healthy", "degraded", "warning", "down"] = "healthy"
    connections: tuple[Connection, ...] = ()
    policy: PolicyConfig | None = None  # the policy it runs with; `None` sends none


class RecordingReads(Protocol):  # a lookup answers `None` for no such entry
    async def list(self, query: EntryQuery) -> EntryPage: ...
    async def get(self, entry_id: str) -> RecordedEntry | None: ...


class RecordingControl(RecordingReads, Protocol):  # `add` also returns the entry it re-added
    # (`None`: it created one). A pin keeps forever; an unpin takes `retention_days` (`None`:
    # the global default). Each write is recorded by the policy ahead of the store (C-2.9).
    async def add(self, symbol: str, spec: EntrySpec,
                  actor: Actor) -> tuple[RecordedEntry, RecordedEntry | None]: ...  # fmt: skip
    # `add` raises the policy's `RecorderInvalidUpdateError` and `RecorderSymbolLimitError`
    # unchanged (the route maps them), where `update` maps its refusals to a port error.
    async def update(self, entry_id: str, spec: EntrySpec,
                     actor: Actor) -> RecordedEntry | None: ...  # fmt: skip
    async def remove(self, entry_id: str, actor: Actor) -> RecordedEntry | None: ...
    async def pin(self, entry_id: str, pinned: bool, actor: Actor, *,
                  retention_days: int | None = None) -> RecordedEntry | None: ...  # fmt: skip
    async def status(self) -> ControlStatus: ...


class RecordedRows(Protocol):  # the row port; `env` comes from settings, never `live` by default
    async def recorded_page(
        self, *, env: str, state: str | None, reason: str | None, pinned: bool | None,
        hidden: tuple[str, ...], after: tuple[str, str] | None, limit: int,
    ) -> list[dict[str, Any]]: ...  # fmt: skip
    async def recorded_row(self, entry_id: str, *, env: str) -> dict[str, Any] | None: ...


def setting_rule(depth: object) -> tuple[str, str]:
    """`(rule, field)` of the policy's `RecorderInvalidUpdateError` for a change naming `depth`:
    the depth's when the table refuses that depth, else the streams'."""
    if depth is not None and (type(depth) is not int or depth not in ORDERBOOK_DEPTHS):
        return "depth_allowed", "depth"
    return "stream_names", "streams"


def restricted_view(entry: RecordedEntry) -> RecordedEntry | None:
    """`entry` as a restricted view shows it: none when hidden causes alone record it, else
    without them, its refusal the strongest visible cause (or none)."""
    reasons = tuple(r for r in entry.reasons if r not in HIDDEN_CAUSES)
    refusals = tuple(r for r in entry.refusals if r not in HIDDEN_CAUSES)
    return replace(entry, reasons=reasons, refusals=refusals) if reasons else None


def entry_from_row(row: Mapping[str, Any]) -> RecordedEntry:
    """A recorded row: its latest session's state (`idle` with none) and, once started, start."""
    state: RecordingState = row["session_state"] or "idle"
    started = row["session_started_at"] if state in _STARTED else None
    return RecordedEntry(
        row["id"], row["symbol"], (row["reason"],), state, row["pinned"], tuple(row["streams"]),
        row["depth"], started, row["retention_days"], row["added_by"],
    )  # fmt: skip


class StoredRecordingControl:
    """The read half over the stored rows of `env`, until a runtime is bound."""

    def __init__(self, rows: RecordedRows, env: str) -> None:
        self._rows, self._env = rows, env

    async def list(self, query: EntryQuery) -> EntryPage:
        q = query
        rows = await self._rows.recorded_page(
            env=self._env, state=q.state, reason=q.reason, pinned=q.pinned,
            hidden=tuple(sorted(q.hidden)), after=q.after, limit=q.limit + 1,
        )  # fmt: skip
        return EntryPage(tuple(map(entry_from_row, rows[: q.limit])), len(rows) > q.limit)

    async def get(self, entry_id: str) -> RecordedEntry | None:
        row = await self._rows.recorded_row(entry_id, env=self._env)
        return None if row is None else entry_from_row(row)
