"""In-memory fakes for the `RetentionManager` tests (E16-T06). No I/O, injected clock."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

from candleviewer.recorder.retention import (
    US_PER_DAY,
    ColdPartition,
    HotDay,
    MemoryCheckpoint,
    PolicyRow,
    RetentionConfig,
    RetentionManager,
    day_key,
)
from candleviewer.storage.cold.watermarks import RollOffWatermark
from candleviewer.storage.models import StreamKind

NOW = datetime(2026, 10, 20, 2, 15, tzinfo=UTC)
NOW_US = int(NOW.timestamp() * 1_000_000)
TODAY = NOW_US - NOW_US % US_PER_DAY
T = StreamKind.TRADES


def day(n_ago: int) -> int:
    return TODAY - n_ago * US_PER_DAY


class Crash(BaseException):
    """Simulated process death (propagates out of the pass)."""


@dataclass
class World:
    """Hot: stream -> day -> {symbol: rows}. Cold: (symbol, stream) -> {key: (start, rows)}."""

    hot: dict[StreamKind, dict[int, dict[str, int]]] = field(default_factory=dict)
    cold: dict[tuple[str, StreamKind], dict[str, tuple[int, int]]] = field(default_factory=dict)
    pinned: set[str] = field(default_factory=set)
    policies: dict[tuple[str | None, str], PolicyRow] = field(default_factory=dict)
    archived: dict[tuple[str, StreamKind], int] = field(default_factory=dict)
    leases: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    audit: list[tuple[str, dict[str, str | int]]] = field(default_factory=list)
    events: list[tuple[str, str]] = field(default_factory=list)
    deletes: list[str] = field(default_factory=list)
    crash_on_delete: int | None = None  # crash on the N-th delete (1-based), before it happens
    fail_audit: bool = False
    lock_free: bool = True
    late_rows: dict[tuple[str, int], int] = field(default_factory=dict)
    cold_override: dict[tuple[str, int], int | None] = field(default_factory=dict)

    def add_cold(self, symbol: str, stream: StreamKind, n_ago: int, rows: int = 100) -> str:
        key = f"{stream.value}/symbol={symbol}/dt={day_key(day(n_ago))}"
        self.cold.setdefault((symbol, stream), {})[key] = (day(n_ago), rows)
        return key

    def add_hot(self, stream: StreamKind, n_ago: int, rows: Mapping[str, int]) -> None:
        self.hot.setdefault(stream, {})[day(n_ago)] = dict(rows)

    def volume(self) -> tuple[int, int]:
        """(partition count, total rows) across both tiers — the "data volume"."""
        hot = [n for d in self.hot.values() for r in d.values() for n in r.values()]
        cold = [r for parts in self.cold.values() for _, r in parts.values()]
        return len(hot) + len(cold), sum(hot) + sum(cold)

    def data_deleted(self) -> list[dict[str, str | int]]:
        """Write-ahead intent records (one per deletion)."""
        return [d for a, d in self.audit if a == "data.deleted" and d.get("phase") == "intent"]

    def data_deleted_phase(self, phase: str) -> list[dict[str, str | int]]:
        return [d for a, d in self.audit if a == "data.deleted" and d.get("phase") == phase]


class FakeHot:
    def __init__(self, w: World) -> None:
        self.w = w

    async def days(self, stream: StreamKind, before_us: int) -> list[HotDay]:
        return [
            HotDay(d, dict(rows), 1000 * sum(rows.values()))
            for d, rows in sorted(self.w.hot.get(stream, {}).items())
            if d + US_PER_DAY <= before_us
        ]

    async def drop_day(self, stream: StreamKind, day_start_us: int) -> bool:
        self.w.deletes.append(f"hot:{stream.value}:{day_start_us}")
        if self.w.crash_on_delete is not None and len(self.w.deletes) >= self.w.crash_on_delete:
            self.w.crash_on_delete = None
            raise Crash("killed")
        return self.w.hot.get(stream, {}).pop(day_start_us, None) is not None


class FakeCold:
    def __init__(self, w: World) -> None:
        self.w = w

    async def partitions(self, symbol: str, stream: StreamKind) -> list[ColdPartition]:
        return [
            ColdPartition(k, s, s + US_PER_DAY, r, 1000 * r)
            for k, (s, r) in sorted(self.w.cold.get((symbol, stream), {}).items())
        ]

    async def delete(self, symbol: str, stream: StreamKind, key: str) -> bool:
        self.w.deletes.append(f"cold:{key}")
        if self.w.crash_on_delete is not None and len(self.w.deletes) >= self.w.crash_on_delete:
            self.w.crash_on_delete = None
            raise Crash("killed")
        return self.w.cold.get((symbol, stream), {}).pop(key, None) is not None


class FakeFacts:
    def __init__(self, w: World) -> None:
        self.w = w

    async def symbols(self) -> list[str]:
        syms = {s for (s, _) in self.w.cold} | {
            s for d in self.w.hot.values() for r in d.values() for s in r
        }
        return sorted(syms)

    async def pinned(self) -> set[str]:
        return set(self.w.pinned)

    async def policies(self) -> Mapping[tuple[str | None, str], PolicyRow]:
        return dict(self.w.policies)


class FakeMarks:
    def __init__(self, w: World) -> None:
        self.w = w

    async def get(self, symbol: str, stream: StreamKind) -> RollOffWatermark:
        return RollOffWatermark(symbol, stream, self.w.archived.get((symbol, stream), 0))


class FakeVerifier:
    """Cold manifest rows default to "exactly what is hot" (archived); `cold_override` and
    `late_rows` simulate a mismatch (late/backfilled rows) or a missing manifest."""

    def __init__(self, w: World) -> None:
        self.w = w

    async def hot_rows(self, stream: StreamKind, day_start_us: int) -> Mapping[str, int]:
        rows = dict(self.w.hot.get(stream, {}).get(day_start_us, {}))
        for (sym, d), extra in self.w.late_rows.items():
            if d == day_start_us:
                rows[sym] = rows.get(sym, 0) + extra
        return rows

    async def cold_rows(self, symbol: str, stream: StreamKind, day_start_us: int) -> int | None:
        if (symbol, day_start_us) in self.w.cold_override:
            return self.w.cold_override[(symbol, day_start_us)]
        return self.w.hot.get(stream, {}).get(day_start_us, {}).get(symbol)


class FakeAudit:
    def __init__(self, w: World) -> None:
        self.w = w

    async def write(self, action: str, detail: dict[str, str | int]) -> None:
        if self.w.fail_audit:
            raise RuntimeError("audit down")
        self.w.audit.append((action, dict(detail)))


class FakeEvents:
    def __init__(self, w: World) -> None:
        self.w = w

    async def emit(self, severity: str, code: str, detail: dict[str, str | int]) -> None:
        self.w.events.append((severity, code))


class FakeLock:
    def __init__(self, w: World) -> None:
        self.w = w

    @asynccontextmanager
    async def hold(self, volume: str) -> AsyncIterator[bool]:
        yield self.w.lock_free


def manager(
    w: World, ckpt: MemoryCheckpoint | None = None, config: RetentionConfig | None = None
) -> RetentionManager:
    """`config` replaces the default (trades only, 7 d / 30 d hard default) for a test that needs
    other streams; pass it here rather than poking the manager's private `_cfg`."""

    async def lease(symbol: str, lo: int, hi: int) -> str | None:
        for a, b in w.leases.get(symbol, []):
            if a < hi and b > lo:
                return "replay-1"
        return None

    async def no_sleep(_s: float) -> None:
        return None

    return RetentionManager(
        hot=FakeHot(w),
        cold=FakeCold(w),
        facts=FakeFacts(w),
        verifier=FakeVerifier(w),
        watermarks=FakeMarks(w),
        audit=FakeAudit(w),
        events=FakeEvents(w),
        lock=FakeLock(w),
        checkpoint=ckpt or MemoryCheckpoint(),
        lease=lease,
        config=config or RetentionConfig(hot_streams=(T,), cold_streams=(T,), hard_default=(7, 30)),
        clock=lambda: NOW,
        sleep=no_sleep,
    )
