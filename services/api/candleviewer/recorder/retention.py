"""`RetentionManager` — policy resolution, dry-run preview, reaper and purge (E16-T06).

Resolution order (`21-database-schema.md` §3.6.3):
  pinned symbol -> infinite; symbol policy; default policy; §7 stream default; hard default.
  A cold partition of a family-split stream then takes §7's per-family horizon
  (`family_policy`: `bars` partitions with `family=time` keep forever).
A policy with `applies_to_pinned` overrides the pin only when the caller holds the
step-up scope (checked server-side; `RetentionStepUpRequired` maps to a 403 problem).

Safety properties (each re-checked immediately before every delete, never only at plan time):
- the pin check is the FIRST predicate (§6);
- a hot (QuestDB) DAY partition holds every symbol, so it is dropped only when every symbol
  in it is past its hot horizon AND the roll-off watermark proves it archived — else it is
  kept and alerted (`retention.not_archived`) — AND each symbol's rows on the day still equal
  its verified cold manifest — else it is kept and CRITICAL `archive.verification_failed`
  is raised, whether the mismatch is found while planning or right before the drop;
- a partition under an active replay/backtest lease is skipped and retried next pass;
- every deletion writes `data.deleted` write-ahead (C-2.9); the pass writes `retention.run`.

Resumable: `run_nightly` persists the plan and per-unit progress in an atomic checkpoint.
Order per unit: audit -> checkpoint `pending` -> delete -> checkpoint `done`. A resumed run
deletes a `pending` unit without re-auditing; the only duplicate-audit window is a crash
between the audit and the `pending` write, and both records carry the same `deletion_id`.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final, Literal, Protocol, cast

import structlog

from candleviewer.observability.metrics import Counter, Gauge, Histogram
from candleviewer.recorder.retention_defaults import (
    FAMILY_DEFAULTS,
    STREAM_DEFAULTS,
    STREAM_ROW_FAMILIES,
)
from candleviewer.storage.cold.observability import SystemEventSink
from candleviewer.storage.cold.watermarks import RollOffWatermark
from candleviewer.storage.models import StreamKind

#: Hard default (§3.6.3). Provisional values from E16-K01 (`e16-storage-measurement.md` §5):
#: `CV_RECORDER_HOT_DAYS`=7, `CV_RECORDER_RETENTION_DAYS`=30 — re-validate after the live
#: 7-day re-measure (#1778 A); composition passes the settings values.
HARD_DEFAULT_DAYS: Final = 30
HARD_DEFAULT_HOT_DAYS: Final = 7
US_PER_DAY: Final = 86_400_000_000
#: Ingest-lag ceiling above which the reaper yields (ticket "Off-peak").
INGEST_LAG_YIELD_S: Final = 1.0
SYSTEM_ACTOR: Final = "system:retention"

_KNOWN_STREAMS: Final = frozenset(k.value for k in StreamKind)
Source = Literal[
    "pinned",
    "symbol",
    "default",
    "stream_default",
    "family_default",
    "hard_default",
    "unknown_stream",
]
Tier = Literal["hot", "cold"]
Reason = Literal[
    "pinned", "leased", "hot_window", "not_archived", "archive_mismatch", "shared_partition"
]
PlanMode = Literal["policy", "purge"]
#: Holds an operator must act on; alerted whether found at plan time or at delete time.
_ALERTED: Final[frozenset[Reason]] = frozenset({"not_archived", "archive_mismatch"})

retention_deleted_bytes_total = Counter(
    "retention_deleted_bytes_total", "Bytes deleted by retention.", ["symbol", "stream"]
)
retention_deleted_rows_total = Counter("retention_deleted_rows_total", "Rows deleted by retention.")
retention_protected_total = Counter(
    "retention_protected_total", "Partitions protected from deletion.", ["reason"]
)
retention_run_duration_seconds = Histogram(
    "retention_run_duration_seconds", "Wall time of one retention pass."
)
retention_last_success_timestamp = Gauge(
    "retention_last_success_timestamp", "Unix time of the last successful retention pass."
)


def logger() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(__name__))


class RetentionStepUpRequired(PermissionError):
    """`applies_to_pinned` used without the elevated step-up scope (-> 403)."""


class RetentionBusy(RuntimeError):
    """Another retention pass / purge holds the volume lock (`retention_busy`)."""

    code = "retention_busy"


class CheckpointCorrupt(ValueError):
    """The reaper checkpoint is unreadable: fail closed (nothing is deleted)."""

    code = "retention_checkpoint_corrupt"


@dataclass(frozen=True, slots=True)
class PolicyRow:
    symbol: str | None  # None = default policy
    stream: str
    hot_days: int
    total_days: int | None  # None = infinite
    applies_to_pinned: bool = False


@dataclass(frozen=True, slots=True)
class EffectivePolicy:
    symbol: str
    stream: str
    hot_days: int | None
    total_days: int | None  # None = keep forever
    source: Source


def resolve_policy(
    symbol: str,
    stream: str,
    *,
    pinned: bool,
    policies: Mapping[tuple[str | None, str], PolicyRow],
    elevated: bool,
    hard_default: tuple[int, int] = (HARD_DEFAULT_HOT_DAYS, HARD_DEFAULT_DAYS),
) -> EffectivePolicy:
    """Pure §3.6.3 resolution. The pin check comes first."""
    sym = policies.get((symbol, stream))
    if pinned:
        if sym is not None and sym.applies_to_pinned:
            if not elevated:
                raise RetentionStepUpRequired(symbol)
            return EffectivePolicy(symbol, stream, sym.hot_days, sym.total_days, "symbol")
        return EffectivePolicy(symbol, stream, None, None, "pinned")
    if sym is not None:
        return EffectivePolicy(symbol, stream, sym.hot_days, sym.total_days, "symbol")
    dflt = policies.get((None, stream))
    if dflt is not None:
        return EffectivePolicy(symbol, stream, dflt.hot_days, dflt.total_days, "default")
    seeded = STREAM_DEFAULTS.get(stream)
    if seeded is not None:  # §7 matrix default for this stream (review H1)
        return EffectivePolicy(symbol, stream, seeded[0], seeded[1], "stream_default")
    if stream in _KNOWN_STREAMS:  # a known stream missing from §7 (none today)
        hot, total = hard_default
        return EffectivePolicy(symbol, stream, hot, total, "hard_default")
    # Unknown stream: fail toward retaining (never the 30-day hard default).
    return EffectivePolicy(symbol, stream, None, None, "unknown_stream")


def partition_family(key: str) -> str | None:
    """`<f>` of a cold partition key's `family=<f>` segment (`bars/family=time/...`, 21 §5.1)."""
    for segment in key.split("/"):
        name, sep, value = segment.partition("=")
        if sep and name == "family":
            return value
    return None


def family_policy(eff: EffectivePolicy, key: str) -> EffectivePolicy:
    """§7 per-family horizon for one cold partition of a family-split stream (review round 4).

    The stream-wide horizon (a `bars` policy row, or the §7 `bars` default) covers only the
    families §7 gives that row (`tick/volume/range/renko/delta`); no policy row can name a
    family until E16-T08. `bars_time` keeps forever, and so does any other or missing family
    (fail toward retaining): the result is never shorter than the stream-wide horizon."""
    covered = STREAM_ROW_FAMILIES.get(eff.stream)
    family = partition_family(key)
    if covered is None or eff.total_days is None or family in covered:
        return eff
    hot, total = FAMILY_DEFAULTS.get((eff.stream, family or ""), (None, None))
    if total is not None and total <= eff.total_days:
        return eff
    return EffectivePolicy(eff.symbol, eff.stream, hot, total, "family_default")


# -- plan -------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PruneItem:
    """One deletion unit. Hot: a QuestDB DAY partition of `stream` (all `symbols`).
    Cold: one Parquet partition directory of `(symbols[0], stream)`, named by `key`."""

    tier: Tier
    stream: str
    symbols: tuple[str, ...]
    key: str
    start_us: int
    end_us: int
    rows: int
    bytes: int

    @property
    def deletion_id(self) -> str:
        raw = f"{self.tier}|{self.stream}|{','.join(self.symbols)}|{self.key}|{self.start_us}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def detail(self) -> dict[str, str | int]:
        return {
            "deletion_id": self.deletion_id,
            "tier": self.tier,
            "symbol": ",".join(self.symbols),
            "stream": self.stream,
            "partition": self.key,
            "range_start_us": self.start_us,
            "range_end_us": self.end_us,
            "rows": self.rows,
            "bytes": self.bytes,
        }


@dataclass(frozen=True, slots=True)
class Protected:
    item: PruneItem
    reason: Reason
    info: str = ""


@dataclass(frozen=True, slots=True)
class StreamSummary:
    """Per `(symbol, stream)`: the date range and size that would be deleted."""

    symbol: str
    stream: str
    from_us: int
    to_us: int
    rows: int
    bytes: int


@dataclass(frozen=True, slots=True)
class PrunePlan:
    created_us: int
    items: tuple[PruneItem, ...]
    protected: tuple[Protected, ...]
    #: `policy`: nightly/preview horizons; `purge`: an explicit owner window (E16-T06 purge).
    mode: PlanMode = "policy"
    #: Only a purge with `include_pinned` (step-up) may touch pinned data.
    allow_pinned: bool = False

    @property
    def plan_id(self) -> str:
        ids = ",".join(i.deletion_id for i in self.items)
        raw = f"{self.mode}|{self.created_us}|{int(self.allow_pinned)}|{ids}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    @property
    def total_bytes(self) -> int:
        return sum(i.bytes for i in self.items)

    @property
    def total_gb(self) -> Decimal:
        return (Decimal(self.total_bytes) / Decimal(1024**3)).quantize(Decimal("0.001"))

    @property
    def total_rows(self) -> int:
        return sum(i.rows for i in self.items)

    def summary(self) -> list[StreamSummary]:
        acc: dict[tuple[str, str], list[PruneItem]] = {}
        for i in self.items:
            for sym in i.symbols:
                acc.setdefault((sym, i.stream), []).append(i)
        return [
            StreamSummary(
                sym,
                stream,
                min(i.start_us for i in its),
                max(i.end_us for i in its),
                sum(i.rows for i in its),
                sum(i.bytes for i in its),
            )
            for (sym, stream), its in sorted(acc.items())
        ]


@dataclass(frozen=True, slots=True)
class PruneScope:
    """`symbols`/`streams` None = all. `policies` overrides the stored set (what-if preview,
    e.g. "shorten trades to 7 d" — the plan states the exact bytes and range first)."""

    symbols: tuple[str, ...] | None = None
    streams: tuple[str, ...] | None = None
    policies: Mapping[tuple[str | None, str], PolicyRow] | None = None


@dataclass(slots=True)
class RunReport:
    dry_run: bool
    deleted: list[PruneItem] = field(default_factory=list)
    #: Held at delete time (the re-check found a blocker after planning).
    skipped: list[Protected] = field(default_factory=list)
    failed: list[tuple[PruneItem, str]] = field(default_factory=list)
    resumed: bool = False
    next_run_us: int | None = None
    #: Held at plan time (never became an item); empty for a resumed checkpointed plan.
    protected: list[Protected] = field(default_factory=list)

    @property
    def freed_bytes(self) -> int:
        return sum(i.bytes for i in self.deleted)


# -- ports ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HotDay:
    start_us: int
    rows_by_symbol: Mapping[str, int]
    bytes: int


@dataclass(frozen=True, slots=True)
class ColdPartition:
    key: str  # partition dir relative to the cold root (closed charset)
    start_us: int
    end_us: int
    rows: int
    bytes: int


class HotStore(Protocol):
    async def days(self, stream: StreamKind, before_us: int) -> list[HotDay]: ...

    async def drop_day(self, stream: StreamKind, day_start_us: int) -> bool:
        """Drop the DAY partition; False if it no longer exists (idempotent)."""
        ...


class ColdStore(Protocol):
    async def partitions(self, symbol: str, stream: StreamKind) -> list[ColdPartition]: ...

    async def delete(self, symbol: str, stream: StreamKind, key: str) -> bool:
        """Delete the partition dir + manifest under the partition lock (with containment
        check); False if it no longer exists (idempotent)."""
        ...


class Facts(Protocol):
    async def symbols(self) -> list[str]: ...

    async def pinned(self) -> set[str]: ...

    async def policies(self) -> Mapping[tuple[str | None, str], PolicyRow]: ...


class Watermarks(Protocol):
    async def get(self, symbol: str, stream: StreamKind) -> RollOffWatermark: ...


class ArchiveVerifier(Protocol):
    """Read at delete time (review H2): current hot rows per symbol for the day, and the rows
    the cold manifest holds for each symbol's day. Dropping requires an exact match."""

    async def hot_rows(self, stream: StreamKind, day_start_us: int) -> Mapping[str, int]: ...

    async def cold_rows(self, symbol: str, stream: StreamKind, day_start_us: int) -> int | None:
        """Manifest row count for the day; None if no verified manifest exists."""
        ...


#: (symbol, lo_us, hi_us) -> id of an active replay/backtest lease overlapping it, else None.
LeaseCheck = Callable[[str, int, int], Awaitable[str | None]]


class AuditPort(Protocol):
    async def write(self, action: str, detail: dict[str, str | int]) -> None: ...


class RunLock(Protocol):
    def hold(self, volume: str) -> AbstractAsyncContextManager[bool]: ...


class Checkpoint(Protocol):
    """Atomic, single-writer progress document (`None` = no unfinished run)."""

    async def load(self) -> dict[str, object] | None: ...

    async def save(self, doc: dict[str, object]) -> None: ...

    async def clear(self) -> None: ...


async def _no_lease(symbol: str, lo: int, hi: int) -> None:
    return None


def _utc_now() -> datetime:
    return datetime.now(UTC)


async def _real_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


@dataclass(frozen=True, slots=True)
class RetentionConfig:
    hot_streams: tuple[StreamKind, ...] = (
        StreamKind.TRADES,
        StreamKind.ORDERBOOK_DELTA,
        StreamKind.TICKERS,
        StreamKind.LIQUIDATIONS,
    )
    cold_streams: tuple[StreamKind, ...] = tuple(StreamKind)
    hard_default: tuple[int, int] = (HARD_DEFAULT_HOT_DAYS, HARD_DEFAULT_DAYS)
    #: Bound on one delete (C-2.18); the cold adapter adds its own lock timeout.
    op_timeout_s: float = 300.0
    interval_s: float = 24 * 3600.0
    max_lag_wait_s: float = 300.0
    volume: str = "retention:recorder"


# -- manager ----------------------------------------------------------------------------------


def day_key(day_start_us: int) -> str:
    return datetime.fromtimestamp(day_start_us / 1_000_000, tz=UTC).strftime("%Y-%m-%d")


def _ckpt_item(i: PruneItem) -> dict[str, object]:
    return {
        "tier": i.tier, "stream": i.stream, "symbols": list(i.symbols), "key": i.key,
        "start_us": i.start_us, "end_us": i.end_us, "rows": i.rows, "bytes": i.bytes,
    }  # fmt: skip


def _item_from(raw: object) -> PruneItem:
    if not isinstance(raw, dict):
        raise CheckpointCorrupt("item is not an object")
    try:
        tier = raw["tier"]
        if tier not in ("hot", "cold"):
            raise CheckpointCorrupt("bad tier")
        nums = [raw[k] for k in ("start_us", "end_us", "rows", "bytes")]
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in nums):
            raise CheckpointCorrupt("bad numbers")
        syms = raw["symbols"]
        if not isinstance(syms, list) or not all(isinstance(s, str) for s in syms):
            raise CheckpointCorrupt("bad symbols")
        return PruneItem(
            cast(Tier, tier), str(raw["stream"]), tuple(syms), str(raw["key"]),
            int(nums[0]), int(nums[1]), int(nums[2]), int(nums[3]),
        )  # fmt: skip
    except KeyError as exc:
        raise CheckpointCorrupt("missing field") from exc


class RetentionManager:
    """Preview (pure read), audited resumable reaper, and the owner purge (E16-T06)."""

    def __init__(
        self,
        *,
        hot: HotStore,
        cold: ColdStore,
        facts: Facts,
        watermarks: Watermarks,
        audit: AuditPort,
        events: SystemEventSink,
        lock: RunLock,
        checkpoint: Checkpoint,
        verifier: ArchiveVerifier,
        lease: LeaseCheck = _no_lease,
        ingest_lag_s: Callable[[], float] | None = None,
        config: RetentionConfig | None = None,
        clock: Callable[[], datetime] = _utc_now,
        sleep: Callable[[float], Awaitable[None]] = _real_sleep,
    ) -> None:
        self._hot, self._cold, self._facts, self._marks = hot, cold, facts, watermarks
        self._audit, self._events, self._lock, self._ckpt = audit, events, lock, checkpoint
        self._lease, self._lag, self._verify = lease, ingest_lag_s, verifier
        self._cfg = config or RetentionConfig()
        self._clock, self._sleep = clock, sleep

    def _now_us(self) -> int:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("RetentionManager clock must be tz-aware UTC")
        return int(now.timestamp() * 1_000_000)

    def _resolve(
        self,
        symbol: str,
        stream: str,
        policies: Mapping[tuple[str | None, str], PolicyRow],
        *,
        pinned: bool,
    ) -> EffectivePolicy:
        """Policy runs never carry elevation: `applies_to_pinned` is honoured only by the
        step-up purge, so here a pinned symbol always resolves to infinite."""
        try:
            return resolve_policy(
                symbol, stream, pinned=pinned, policies=policies, elevated=False,
                hard_default=self._cfg.hard_default,
            )  # fmt: skip
        except RetentionStepUpRequired:
            return EffectivePolicy(symbol, stream, None, None, "pinned")

    async def resolve(self, symbol: str, stream: str, *, elevated: bool = False) -> EffectivePolicy:
        pinned = symbol in await self._facts.pinned()
        return resolve_policy(
            symbol, stream, pinned=pinned, policies=await self._facts.policies(),
            elevated=elevated, hard_default=self._cfg.hard_default,
        )  # fmt: skip

    async def is_pinned(self, symbol: str) -> bool:
        return symbol in await self._facts.pinned()

    # -- preview ------------------------------------------------------------------------

    async def preview(self, scope: PruneScope | None = None) -> PrunePlan:
        """What the reaper would delete now, and what is protected and why. Never mutates."""
        scope = scope or PruneScope()
        now_us = self._now_us()
        pinned = await self._facts.pinned()
        policies = scope.policies if scope.policies is not None else await self._facts.policies()
        items: list[PruneItem] = []
        protected: list[Protected] = []
        for stream in self._cfg.hot_streams:
            if scope.streams is not None and stream.value not in scope.streams:
                continue
            for day in await self._hot.days(stream, now_us - US_PER_DAY):
                syms = tuple(sorted(s for s, n in day.rows_by_symbol.items() if n > 0))
                if not syms or (scope.symbols is not None and not set(syms) & set(scope.symbols)):
                    continue
                end = day.start_us + US_PER_DAY
                item = PruneItem(
                    "hot", stream.value, syms, day_key(day.start_us), day.start_us, end,
                    sum(day.rows_by_symbol.values()), day.bytes,
                )  # fmt: skip
                # Days inside every symbol's (unpinned) hot window are simply not candidates.
                base = [self._resolve(s, stream.value, policies, pinned=False) for s in syms]
                if all(p.hot_days is None or end > now_us - p.hot_days * US_PER_DAY for p in base):
                    continue
                blocker = await self._hot_blocker(item, stream, pinned, policies, now_us)
                if blocker is None:
                    items.append(item)
                else:
                    protected.append(blocker)
        for symbol in sorted(scope.symbols or await self._facts.symbols()):
            for stream in self._cfg.cold_streams:
                if scope.streams is not None and stream.value not in scope.streams:
                    continue
                is_pinned = symbol in pinned
                eff = self._resolve(symbol, stream.value, policies, pinned=False)
                if eff.total_days is None:
                    continue
                for part in await self._cold.partitions(symbol, stream):
                    # Per partition: a family-split stream keys its §7 horizon by `family=`.
                    total = family_policy(eff, part.key).total_days
                    if total is None or part.end_us > now_us - total * US_PER_DAY:
                        continue
                    item = PruneItem(
                        "cold", stream.value, (symbol,), part.key, part.start_us, part.end_us,
                        part.rows, part.bytes,
                    )  # fmt: skip
                    if is_pinned:  # pin check first (§6)
                        protected.append(Protected(item, "pinned", symbol))
                        continue
                    lease = await self._lease(symbol, part.start_us, part.end_us)
                    if lease is not None:
                        protected.append(Protected(item, "leased", f"lease={lease}"))
                        continue
                    items.append(item)
        for p in protected:
            retention_protected_total.labels(reason=p.reason).inc()
        return PrunePlan(now_us, tuple(items), tuple(protected))

    async def plan_purge(self, symbol: str, before_us: int, *, include_pinned: bool) -> PrunePlan:
        """Owner purge window `[-inf, before_us)` for one symbol: cold partitions wholly
        before `before_us`, and hot DAY partitions only where `symbol` is the sole symbol
        (a shared day is protected as `shared_partition`; it rolls off normally)."""
        now_us = self._now_us()
        pinned = symbol in await self._facts.pinned()
        items: list[PruneItem] = []
        protected: list[Protected] = []

        def gate(item: PruneItem) -> None:
            if pinned and not include_pinned:
                protected.append(Protected(item, "pinned", symbol))
            else:
                items.append(item)

        for stream in self._cfg.hot_streams:
            for day in await self._hot.days(stream, min(before_us, now_us - US_PER_DAY)):
                rows = {s: n for s, n in day.rows_by_symbol.items() if n > 0}
                if symbol not in rows:
                    continue
                item = PruneItem(
                    "hot", stream.value, tuple(sorted(rows)), day_key(day.start_us),
                    day.start_us, day.start_us + US_PER_DAY, sum(rows.values()), day.bytes,
                )  # fmt: skip
                if set(rows) != {symbol}:
                    protected.append(Protected(item, "shared_partition"))
                    continue
                gate(item)
        for stream in self._cfg.cold_streams:
            for part in await self._cold.partitions(symbol, stream):
                if part.end_us > before_us:
                    continue
                gate(
                    PruneItem(
                        "cold",
                        stream.value,
                        (symbol,),
                        part.key,
                        part.start_us,
                        part.end_us,
                        part.rows,
                        part.bytes,
                    )
                )
        return PrunePlan(now_us, tuple(items), tuple(protected), "purge", include_pinned)

    async def _hot_blocker(
        self,
        item: PruneItem,
        stream: StreamKind,
        pinned: set[str],
        policies: Mapping[tuple[str | None, str], PolicyRow],
        now_us: int,
    ) -> Protected | None:
        """Pin first (§6), then every symbol's own hot window, the lease, the watermark, then the
        archive itself: rows on the day NOW, per symbol, must equal the cold manifest's rows."""
        if not item.symbols:  # review H2: an empty symbol list proves nothing -> never drop
            return Protected(item, "not_archived", "no symbols")
        hits = [s for s in item.symbols if s in pinned]
        if hits:
            return Protected(item, "pinned", ",".join(hits))
        for s in item.symbols:
            eff = self._resolve(s, stream.value, policies, pinned=False)
            if eff.hot_days is None or item.end_us > now_us - eff.hot_days * US_PER_DAY:
                return Protected(item, "hot_window", s)
        for s in item.symbols:
            lease = await self._lease(s, item.start_us, item.end_us)
            if lease is not None:
                return Protected(item, "leased", f"lease={lease}")
        for s in item.symbols:
            mark = await self._marks.get(s, stream)
            if mark.archived_through_us < item.end_us:
                return Protected(item, "not_archived", s)
        return await self._archive_blocker(item, stream, pinned)

    async def _archive_blocker(
        self, item: PruneItem, stream: StreamKind, pinned: set[str]
    ) -> Protected | None:
        """Re-read the day's symbols and counts (late / backfilled rows, a new symbol) and
        require each to equal its verified cold manifest; else keep the day (SR-094/099)."""
        now_rows = {s: n for s, n in (await self._verify.hot_rows(stream, item.start_us)).items()}
        live = {s for s, n in now_rows.items() if n > 0}
        if not live:
            return Protected(item, "archive_mismatch", "no rows read back")
        if live - set(item.symbols):
            new = sorted(live - set(item.symbols))
            if set(new) & pinned:
                return Protected(item, "pinned", ",".join(sorted(set(new) & pinned)))
            return Protected(item, "archive_mismatch", "new symbols: " + ",".join(new))
        for s in sorted(live):
            cold = await self._verify.cold_rows(s, stream, item.start_us)
            if cold is None or cold != now_rows[s]:
                return Protected(item, "archive_mismatch", f"{s} hot={now_rows[s]} cold={cold}")
        return None

    # -- execution ----------------------------------------------------------------------

    async def _recheck(self, item: PruneItem, plan: PrunePlan, now_us: int) -> Protected | None:
        """Every blocking predicate again, from current facts, right before the delete."""
        pinned = await self._facts.pinned()
        stream = StreamKind(item.stream)
        if plan.mode == "purge":
            return await self._purge_blocker(item, plan, pinned, stream)
        policies = await self._facts.policies()
        if item.tier == "hot":
            return await self._hot_blocker(item, stream, pinned, policies, now_us)
        symbol = item.symbols[0]
        if symbol in pinned:
            return Protected(item, "pinned", symbol)
        eff = family_policy(self._resolve(symbol, item.stream, policies, pinned=False), item.key)
        if eff.total_days is None or item.end_us > now_us - eff.total_days * US_PER_DAY:
            return Protected(item, "hot_window", "inside total horizon")
        lease = await self._lease(symbol, item.start_us, item.end_us)
        if lease is not None:
            return Protected(item, "leased", f"lease={lease}")
        return None

    async def _purge_blocker(
        self, item: PruneItem, plan: PrunePlan, pinned: set[str], stream: StreamKind
    ) -> Protected | None:
        """Purge re-check (review round 4, 2). A DAY partition holds every symbol, so a hot item
        re-reads who is in the day NOW: rows of another symbol may have landed since
        `plan_purge`. Pin first (§6) over every live symbol (`include_pinned` covers only the
        purged symbol), then refuse a day that is no longer the purged symbol's alone."""
        own = set(item.symbols)
        live: set[str] = set()
        if item.tier == "hot":
            rows = await self._verify.hot_rows(stream, item.start_us)
            live = {s for s, n in rows.items() if n > 0}
        hits = sorted(s for s in own | live if s in pinned)
        blocked = [s for s in hits if s not in own] if plan.allow_pinned else hits
        if blocked:
            return Protected(item, "pinned", ",".join(blocked))
        if live - own:
            return Protected(item, "shared_partition", ",".join(sorted(live - own)))
        for s in item.symbols:
            lease = await self._lease(s, item.start_us, item.end_us)
            if lease is not None:
                return Protected(item, "leased", f"lease={lease}")
        return None

    async def _delete(self, item: PruneItem) -> bool:
        stream = StreamKind(item.stream)
        async with asyncio.timeout(self._cfg.op_timeout_s):
            if item.tier == "hot":
                return await self._hot.drop_day(stream, item.start_us)
            return await self._cold.delete(item.symbols[0], stream, item.key)

    async def _wait_for_lag(self) -> bool:
        """Off-peak guard: yield while ingest lag > 1 s; False if it never recovers."""
        if self._lag is None:
            return True
        waited = 0.0
        while self._lag() > INGEST_LAG_YIELD_S:
            if waited >= self._cfg.max_lag_wait_s:
                return False
            await self._sleep(1.0)
            waited += 1.0
        return True

    async def _hold(self, p: Protected) -> None:
        """Log why an item is held and raise its alert: an archived hot day whose rows no longer
        match the cold manifest is CRITICAL `archive.verification_failed` (as the roll-off
        treats late rows); a day past its window that the roll-off has not archived is WARNING
        `retention.not_archived`."""
        logger().info(
            "retention_skipped",
            reason=p.reason,
            info=p.info,
            tier=p.item.tier,
            stream=p.item.stream,
            part=p.item.key,
        )
        if p.reason == "not_archived":
            await self._events.emit("WARNING", "retention.not_archived", p.item.detail())
        elif p.reason == "archive_mismatch":
            await self._events.emit("CRITICAL", "archive.verification_failed", p.item.detail())

    async def _alert_plan_holds(self, plan: PrunePlan) -> None:
        """Review round 4 (A): a hold found while PLANNING never reaches the delete-time
        re-check, so alert it here — a late-row day is never a silent skip."""
        for p in plan.protected:
            if p.reason in _ALERTED:
                await self._hold(p)

    async def _execute(
        self, plan: PrunePlan, doc: dict[str, object], ckpt: Checkpoint, report: RunReport
    ) -> bool:
        """Delete plan items not yet done. True if the pass reached the end of the plan."""
        done = {str(x) for x in cast(list[object], doc.get("done", []))}
        for item in plan.items:
            did = item.deletion_id
            if did in done:
                continue
            if not await self._wait_for_lag():
                logger().warning("retention_yield_ingest_lag", remaining=len(plan.items))
                return False
            if doc.get("pending") == did and await self._dropped_earlier(item):
                # Review round 4 (3): the earlier attempt's DROP outlived its bounded wait and
                # applied later. The day is gone, so close the trail (`done`); re-checking it
                # would read back an empty day as a false CRITICAL archive mismatch.
                await self._complete(item, plan, doc, done, ckpt, report, applied="earlier")
                continue
            now_us = self._now_us()
            blocker = await self._recheck(item, plan, now_us)
            if blocker is not None:
                report.skipped.append(blocker)
                retention_protected_total.labels(reason=blocker.reason).inc()
                await self._hold(blocker)
                continue
            if doc.get("pending") != did:
                # Write-ahead (C-2.9): the exact range + row count land BEFORE the delete.
                await self._audit.write(
                    "data.deleted",
                    item.detail() | {"actor": SYSTEM_ACTOR, "mode": plan.mode, "phase": "intent"},
                )
                doc["pending"] = did
                await ckpt.save(doc)
            try:
                await self._delete(item)
            except (OSError, TimeoutError, ValueError, RuntimeError) as exc:
                # Class name only: an exception message may carry filesystem paths (review c).
                why = type(exc).__name__
                report.failed.append((item, why))
                logger().error(
                    "retention_delete_failed",
                    error=type(exc).__name__,
                    reason=why,
                    tier=item.tier,
                    stream=item.stream,
                    partition=item.key,
                )
                await self._events.emit(
                    "WARNING",
                    "retention.delete_failed",
                    item.detail() | {"error": type(exc).__name__},
                )
                await self._audit.write(
                    "data.deleted",
                    item.detail() | {"actor": SYSTEM_ACTOR, "phase": "failed", "error": why},
                )
                return False  # keep `pending`: the next pass finishes it (no second intent)
            await self._complete(item, plan, doc, done, ckpt, report)
            await asyncio.sleep(0)  # yield to live ingestion between partitions
        return True

    async def _dropped_earlier(self, item: PruneItem) -> bool:
        """A `pending` hot day that reads back no rows: the earlier attempt dropped it."""
        if item.tier != "hot":
            return False
        rows = await self._verify.hot_rows(StreamKind(item.stream), item.start_us)
        return not any(n > 0 for n in rows.values())

    async def _complete(
        self,
        item: PruneItem,
        plan: PrunePlan,
        doc: dict[str, object],
        done: set[str],
        ckpt: Checkpoint,
        report: RunReport,
        **extra: str | int,
    ) -> None:
        """After-record (review M1): intent + completion both exist, so a crash between the
        two is detectable as an intent without a `done` (ticket security notes)."""
        did = item.deletion_id
        record: dict[str, str | int] = {
            "deletion_id": did, "actor": SYSTEM_ACTOR, "phase": "done", "mode": plan.mode,
        }  # fmt: skip
        record.update(extra)
        await self._audit.write("data.deleted", record)
        done.add(did)
        doc["done"] = sorted(done)
        doc["pending"] = None
        await ckpt.save(doc)
        report.deleted.append(item)
        for sym in item.symbols:
            retention_deleted_bytes_total.labels(symbol=sym, stream=item.stream).inc(
                item.bytes // len(item.symbols)
            )
        retention_deleted_rows_total.inc(item.rows)

    async def _audit_run(self, plan: PrunePlan, report: RunReport, phase: str) -> None:
        await self._audit.write(
            "retention.run",
            {
                "actor": SYSTEM_ACTOR,
                "phase": phase,
                "mode": plan.mode,
                "plan_id": plan.plan_id,
                "dry_run": int(report.dry_run),
                "planned": len(plan.items),
                "planned_bytes": plan.total_bytes,
                "protected": len(plan.protected),
                "deleted": len(report.deleted),
                "freed_bytes": report.freed_bytes,
                "skipped": len(report.skipped),
                "failed": len(report.failed),
                "resumed": int(report.resumed),
            },
        )

    async def run(
        self, plan: PrunePlan, dry_run: bool, *, checkpoint: Checkpoint | None = None
    ) -> RunReport:
        """Execute exactly `plan` (never more): under the volume lock, every unit re-checked.
        `dry_run` deletes nothing and writes only the `retention.run` record."""
        report = RunReport(dry_run=dry_run, protected=list(plan.protected))
        async with self._lock.hold(self._cfg.volume) as got:
            if not got:
                raise RetentionBusy(self._cfg.volume)
            if dry_run:
                await self._audit_run(plan, report, "dry_run")
                return report
            ckpt = checkpoint or MemoryCheckpoint()
            doc = await ckpt.load() or {}
            if doc.get("plan_id") == plan.plan_id:
                report.resumed = True
            else:
                doc = _new_doc(plan)
                await ckpt.save(doc)
            await self._audit_run(plan, report, "start")
            await self._alert_plan_holds(plan)
            finished = await self._execute(plan, doc, ckpt, report)
            if finished:
                await ckpt.clear()
            await self._audit_run(plan, report, "end" if finished else "partial")
            return report

    async def run_nightly(self) -> RunReport:
        """One reaper pass: resume an unfinished plan from the checkpoint, else plan afresh."""
        started = self._now_us()
        async with self._lock.hold(self._cfg.volume) as got:
            if not got:
                logger().info("retention_skipped_locked", volume=self._cfg.volume)
                return RunReport(dry_run=False)
            doc = await self._ckpt.load()
            report = RunReport(dry_run=False)
            if doc is not None:
                plan = _plan_from(doc)
                report.resumed = True
                logger().info("retention_resumed", plan_id=plan.plan_id)
            else:
                plan = await self.preview()
                doc = _new_doc(plan)
                await self._ckpt.save(doc)
                report.protected = list(plan.protected)
            await self._audit_run(plan, report, "start")
            await self._alert_plan_holds(plan)
            finished = await self._execute(plan, doc, self._ckpt, report)
            if finished:
                await self._ckpt.clear()
            await self._audit_run(plan, report, "end" if finished else "partial")
        now = self._now_us()
        retention_run_duration_seconds.observe((now - started) / 1_000_000)
        if finished and not report.failed:
            retention_last_success_timestamp.set(now / 1_000_000)
        report.next_run_us = now + int(self._cfg.interval_s * 1_000_000)
        return report


def _new_doc(plan: PrunePlan) -> dict[str, object]:
    return {
        "version": 1,
        "plan_id": plan.plan_id,
        "mode": plan.mode,
        "allow_pinned": plan.allow_pinned,
        "created_us": plan.created_us,
        "items": [_ckpt_item(i) for i in plan.items],
        "done": [],
        "pending": None,
    }


def _plan_from(doc: Mapping[str, object]) -> PrunePlan:
    """Rebuild the checkpointed plan; any inconsistency fails closed (nothing deleted)."""
    try:
        if doc.get("version") != 1:
            raise CheckpointCorrupt("unknown version")
        items = doc["items"]
        created = doc["created_us"]
        mode = doc.get("mode", "policy")
        if not isinstance(items, list) or not isinstance(created, int) or mode != "policy":
            raise CheckpointCorrupt("bad shape")
        plan = PrunePlan(created, tuple(_item_from(r) for r in items), ())
    except KeyError as exc:
        raise CheckpointCorrupt("missing field") from exc
    if plan.plan_id != doc.get("plan_id"):
        raise CheckpointCorrupt("plan id mismatch")
    done, pending = doc.get("done"), doc.get("pending")
    ids = {i.deletion_id for i in plan.items}
    if not isinstance(done, list) or not {str(d) for d in done} <= ids:
        raise CheckpointCorrupt("bad done set")
    if pending is not None and pending not in ids:
        raise CheckpointCorrupt("bad pending")
    return plan


class MemoryCheckpoint:
    """Process-local checkpoint (purge jobs and tests)."""

    def __init__(self) -> None:
        self.doc: dict[str, object] | None = None

    async def load(self) -> dict[str, object] | None:
        return None if self.doc is None else dict(self.doc)

    async def save(self, doc: dict[str, object]) -> None:
        self.doc = dict(doc)

    async def clear(self) -> None:
        self.doc = None


class InvalidRetentionPolicy(ValueError):
    """`retention_invalid_policy` (422 at the E16-T08 policy API)."""

    code = "retention_invalid_policy"


#: Derived streams rebuildable from `trades` (§7 notes, SCR-141 "bars can't be deleted before
#: the ticks they came from"): their retention may never exceed the raw-tick retention.
DERIVED_FROM_TRADES: Final = ("bars", "footprint_cells", "profiles", "orderflow_metrics")


def validate_policies(policies: Mapping[tuple[str | None, str], PolicyRow]) -> None:
    """Reject a set where a derived stream outlives `trades` for the same scope (None = forever).
    For the E16-T08 write path; the reaper itself never relies on this."""

    def longer(a: int | None, b: int | None) -> bool:
        return (a is None and b is not None) or (a is not None and b is not None and a > b)

    for (symbol, stream), row in policies.items():
        if stream not in DERIVED_FROM_TRADES:
            continue
        ticks = policies.get((symbol, "trades")) or policies.get((None, "trades"))
        # No trades row: compare against the §7 trades default (review e), never skip.
        tick_total = ticks.total_days if ticks is not None else STREAM_DEFAULTS["trades"][1]
        if longer(row.total_days, tick_total):
            raise InvalidRetentionPolicy(f"{stream} outlives trades for {symbol or 'default'}")
