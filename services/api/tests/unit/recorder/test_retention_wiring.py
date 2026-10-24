"""Unit (E16-T06 review H1/H3/M3): `retention_wiring` composition.

- H3: a build failure (any exception, e.g. a missing seed file in the image) or a non-real
  backend returns `None` — the purge answers 503 — and never raises into `create_app()`.
- M3: `1 <= CV_RECORDER_HOT_DAYS <= CV_RECORDER_RETENTION_DAYS <= 3650` else `None`.
- H1: `PgRetentionFacts.policies()` maps every DB `stream_kind` value (incl. `funding` ->
  `funding_rates`) to its §7 total horizon, and unknown DB streams are dropped (keep forever).
- G7 (#2674): the replay guard (`replay_session_for`, the recorder lease, the cold-tier idle
  guards) keeps data an open session replays, bounded by the session lifetime, and fails closed.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

import candleviewer.retention_wiring as rw
from candleviewer.recorder.retention import resolve_policy
from candleviewer.recorder.retention_defaults import STREAM_DEFAULTS
from candleviewer.settings import Settings
from candleviewer.storage.cold import compactor as compactor_mod
from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.replay_sessions import ReplayState
from candleviewer.storage.retention.ports import Partition
from tests.unit.storage.fakes_replay_sessions import (
    FailingCoveringRead,
    FakeClock,
    FakeReplaySessionRepository,
    open_session,
)


class _Settings:
    def __init__(self, hot: int = 7, total: int = 30, backend: str = "real") -> None:
        self.storage_backend = backend
        self.recorder_hot_days = hot
        self.recorder_retention_days = total


class _Audit:
    async def emit(self, action: str, **kwargs: object) -> None:
        return None


@pytest.mark.parametrize(("hot", "total"), [(0, 30), (31, 30), (7, 3651), (-1, 5)])
def test_invalid_recorder_days_refuse_to_build(hot: int, total: int) -> None:
    built = rw.build_retention_manager(_Settings(hot, total), _Audit(), object())  # type: ignore[arg-type]  # settings/relational stubs: refused before use
    assert built is None


def test_non_real_backend_or_no_db_returns_none() -> None:
    assert rw.build_retention_manager(_Settings(backend="fake"), _Audit(), object()) is None  # type: ignore[arg-type]  # stub
    assert rw.build_retention_manager(_Settings(), _Audit(), None) is None  # type: ignore[arg-type]  # stub


def test_build_failure_never_raises_into_create_app(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object) -> None:
        raise IndexError("seed path parents[5] outside the image")

    monkeypatch.setattr(rw, "_build", boom)
    assert rw.build_retention_manager(_Settings(), _Audit(), object()) is None  # type: ignore[arg-type]  # stub


class _Uow:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.session = self
        self._rows = rows

    async def execute(self, _stmt: object) -> _Uow:
        return self

    def mappings(self) -> _Uow:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows

    async def commit(self) -> None:
        return None


class _Rel:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = [{"action": "archive_parquet", **r} for r in rows]  # the column default

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[_Uow]:
        yield _Uow(self.rows)


#: The DB `stream_kind` enum (21 §2) plus the derived streams it lacks; `funding` is the DB name.
DB_STREAMS = [
    "trades", "orderbook_delta", "orderbook_snapshot", "tickers", "klines", "liquidations",
    "open_interest", "funding", "bars", "footprint_cells", "profiles", "orderflow_metrics",
    "heatmap_cells",
]  # fmt: skip


@pytest.mark.parametrize("db_stream", DB_STREAMS)
async def test_pg_facts_map_every_db_stream_to_its_section7_horizon(db_stream: str) -> None:
    rows = [{"scope": "default", "symbol": None, "stream": db_stream, "retain_days": 3}]
    pol = await rw.PgRetentionFacts(_Rel(rows), _guard()).policies()  # type: ignore[arg-type]  # fake rel
    stream = "funding_rates" if db_stream == "funding" else db_stream
    ((key, row),) = pol.items()
    assert key == (None, stream) and row.hot_days == 3
    assert row.total_days == STREAM_DEFAULTS[stream][1]
    eff = resolve_policy("BTCUSDT", stream, pinned=False, policies=pol, elevated=False)
    assert eff.total_days == STREAM_DEFAULTS[stream][1]  # never the 30-day hard default


async def test_pg_facts_drop_unknown_stream_and_never_shorten_below_hot() -> None:
    rows = [
        {"scope": "default", "symbol": None, "stream": "engine_metrics", "retain_days": 3},
        {"scope": "symbol", "symbol": "BTCUSDT", "stream": "heatmap_cells", "retain_days": 120},
    ]
    pol = await rw.PgRetentionFacts(_Rel(rows), _guard()).policies()  # type: ignore[arg-type]  # fake rel
    assert list(pol) == [("BTCUSDT", "heatmap_cells")]
    assert pol[("BTCUSDT", "heatmap_cells")].total_days == 120  # >= hot window, not 90


# -- G7 (#2674): the replay guard ------------------------------------------------------------

_US = timedelta(microseconds=1)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
LIFE = timedelta(days=1)
RECLAIM = timedelta(seconds=60)  # `CV_REPLAY_RECLAIM_INTERVAL_S`
W0 = datetime(2026, 10, 17, tzinfo=UTC)  # an open session's window: [W0, W1)
W1 = W0 + timedelta(hours=2)


def _us(t: datetime) -> int:
    return (t - _EPOCH) // _US


def _clock() -> FakeClock:
    return FakeClock(W1 + timedelta(hours=1))


def _guard(sessions: Any = None, clock: Any = None, **kw: Any) -> rw.ReplayRetentionGuard:
    sessions = FakeReplaySessionRepository() if sessions is None else sessions
    return rw.ReplayRetentionGuard(
        sessions, max_lifetime=LIFE, reclaim_interval=RECLAIM, clock=clock or _clock(), **kw
    )


def _facts(guard: rw.ReplayRetentionGuard) -> rw.PgRetentionFacts:
    return rw.PgRetentionFacts(cast(Any, _Rel([])), guard)


def _part(symbol: str, stream: StreamKind, lo: datetime = W0, hi: datetime = W1) -> Partition:
    return Partition(symbol, stream, "cold", TimeRange(start_us=_us(lo), end_us=_us(hi)), 1, 1)


def _errors(site: str) -> float:
    return REGISTRY.get_sample_value("replay_retention_guard_errors_total", {"where": site}) or 0.0


@pytest.mark.parametrize("state", sorted(ReplayState))
async def test_guard_keeps_what_every_open_session_replays_never_a_destroyed_one(
    state: ReplayState,
) -> None:
    clock = _clock()
    repo = FakeReplaySessionRepository(clock)
    row = await open_session(repo, state, W0, W1)
    facts = _facts(_guard(repo, clock))
    want = None if state is ReplayState.DESTROYED else row.id  # finished / error: SEEK back
    assert await facts.lease("BTCUSDT", _us(W0), _us(W1)) == want
    assert await facts.replay_session_for(_part("BTCUSDT", StreamKind.TRADES)) == want


async def test_guard_covers_every_symbol_of_a_session_by_stream_and_the_lease_by_symbol() -> None:
    clock = _clock()
    repo = FakeReplaySessionRepository(clock)
    row = await open_session(
        repo, ReplayState.PLAYING, W0, W1, symbols=("BTCUSDT", "ETHUSDT"), streams=("klines",)
    )
    facts = _facts(_guard(repo, clock))
    assert await facts.replay_session_for(_part("ETHUSDT", StreamKind.KLINES)) == row.id
    assert await facts.replay_session_for(_part("ETHUSDT", StreamKind.TRADES)) is None
    assert await facts.replay_session_for(_part("ETHUSDT", StreamKind.BARS)) is None  # derived
    assert await facts.lease("ETHUSDT", _us(W0), _us(W1)) == row.id  # any replayable stream
    assert await facts.lease("SOLUSDT", _us(W0), _us(W1)) is None


@pytest.mark.parametrize(
    ("lo", "hi", "kept"),
    [
        (W0, W1, True),
        (W1 - _US, W1 + timedelta(hours=1), True),
        (W0 - timedelta(days=1), W0 + _US, True),
        (W0 - timedelta(hours=1), W0, False),
        (W1, W1 + timedelta(days=1), False),
    ],
)
async def test_guard_keeps_a_range_only_when_it_overlaps_a_session_window(
    lo: datetime, hi: datetime, kept: bool
) -> None:
    clock = _clock()
    repo = FakeReplaySessionRepository(clock)
    row = await open_session(repo, ReplayState.PAUSED, W0, W1, streams=("trades",))
    facts = _facts(_guard(repo, clock))
    assert await facts.lease("BTCUSDT", _us(lo), _us(hi)) == (row.id if kept else None)
    got = await facts.replay_session_for(_part("BTCUSDT", StreamKind.TRADES, lo, hi))
    assert got == (row.id if kept else None)


async def test_guard_keeps_a_session_until_the_sweep_can_destroy_it() -> None:
    """M2: the sweep destroys a session past its lifetime on its next pass, so the guard keeps it
    for one reclaim interval and a margin beyond the lifetime."""
    clock = _clock()
    repo = FakeReplaySessionRepository(clock)
    row = await open_session(repo, ReplayState.PLAYING, W0, W1)
    facts = _facts(_guard(repo, clock))
    swept = row.created_at + LIFE + RECLAIM + rw.SWEEP_LAG_MARGIN
    for now, want in ((row.created_at + LIFE, row.id), (swept - _US, row.id), (swept, None)):
        clock.now = now
        assert await facts.lease("BTCUSDT", _us(W0), _us(W1)) == want


async def test_guard_keeps_the_snapshot_a_seek_anchor_reads_before_the_session() -> None:
    """M1: a seek anchors on the latest book snapshot up to an hour before its target
    (`replay/merge.py`), so a session starting in the first hour of a day keeps the day before."""
    clock = _clock()
    repo = FakeReplaySessionRepository(clock)
    start = W0 + timedelta(minutes=30)
    row = await open_session(repo, ReplayState.PLAYING, start, W1)
    facts = _facts(_guard(repo, clock))
    snap, day_before = StreamKind.ORDERBOOK_SNAPSHOT, W0 - timedelta(days=1)
    edge = start - timedelta(microseconds=rw.ANCHOR_LOOKBACK_US)
    assert await facts.replay_session_for(_part("BTCUSDT", snap, day_before, W0)) == row.id
    assert await facts.replay_session_for(_part("BTCUSDT", snap, day_before, edge + _US)) == row.id
    assert await facts.replay_session_for(_part("BTCUSDT", snap, day_before, edge)) is None
    assert (
        await facts.replay_session_for(_part("BTCUSDT", StreamKind.TRADES, day_before, W0)) is None
    )
    assert await facts.lease("BTCUSDT", _us(day_before), _us(W0)) == row.id  # via the snapshot
    guard = _guard(repo, clock).partition_guard(Path("/c"), site="compaction")
    assert await guard(Path("/c/orderbook_snapshots/symbol=BTCUSDT/dt=2026-10-16")) == row.id


def test_the_anchor_lookback_is_the_merges() -> None:
    from candleviewer.replay import merge

    assert rw.ANCHOR_LOOKBACK_US == merge.ANCHOR_LOOKBACK_US == 3_600_000_000


async def test_guard_fails_closed_counts_and_logs_ids_only_on_a_read_error() -> None:
    broken = FailingCoveringRead(OSError("driver detail 7f3a"))
    facts = _facts(_guard(broken))
    before = (_errors("lease"), _errors("reaper"))
    with capture_logs() as logs:
        assert await facts.lease("BTCUSDT", _us(W0), _us(W1)) == rw.GUARD_UNVERIFIED
        got = await facts.replay_session_for(_part("BTCUSDT", StreamKind.TRADES))
    assert got == rw.GUARD_UNVERIFIED and broken.calls == 2  # never another stream after it
    assert (_errors("lease"), _errors("reaper")) == (before[0] + 1, before[1] + 1)
    assert [(e["event"], e["where"], e["symbol"], e["error"]) for e in logs] == [
        ("replay_retention_guard_failed_closed", "lease", "BTCUSDT", "OSError"),
        ("replay_retention_guard_failed_closed", "reaper", "BTCUSDT", "OSError"),
    ]
    assert "7f3a" not in repr(logs)


async def test_guard_fails_closed_on_a_read_that_never_answers_or_a_naive_clock() -> None:
    class _Hung:
        async def live_covering(self, *_a: object, **_k: object) -> str | None:
            await asyncio.Event().wait()
            return None

    hung = _guard(_Hung(), timeout_s=0.01)
    assert await hung.covering("BTCUSDT", ("trades",), 0, 1, site="lease") == rw.GUARD_UNVERIFIED
    naive = _guard(clock=lambda: datetime(2026, 10, 17))  # naive: the defect under test
    assert await naive.covering("BTCUSDT", ("trades",), 0, 1, site="lease") == rw.GUARD_UNVERIFIED


async def test_guard_never_swallows_a_cancellation() -> None:
    facts = _facts(_guard(FailingCoveringRead(asyncio.CancelledError())))
    with pytest.raises(asyncio.CancelledError):
        await facts.lease("BTCUSDT", 0, 1)


_OCT, _NOV = datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 11, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    ("rel", "stream", "lo", "hi"),
    [
        ("trades/symbol=BTCUSDT/dt=2026-10-17", "trades", W0, W0 + timedelta(days=1)),
        (
            "orderbook_deltas/symbol=BTCUSDT/dt=2026-10-17/hour=01",
            "orderbook_delta", W0 + timedelta(hours=1), W1,
        ),
        ("klines/symbol=BTCUSDT/interval=1/ym=2026-10", "klines", _OCT, _NOV),
        (
            "funding_rates/symbol=BTCUSDT/y=2026", "funding_rates",
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC),
        ),
    ],
)  # fmt: skip
async def test_cold_guard_reads_the_partitions_symbol_stream_and_range(
    tmp_path: Path, rel: str, stream: str, lo: datetime, hi: datetime
) -> None:
    calls: list[tuple[str, str, datetime, datetime, datetime]] = []

    class _Spy:
        async def live_covering(
            self, symbol: str, stream: str, lo: datetime, hi: datetime, *, created_after: datetime
        ) -> str | None:
            calls.append((symbol, stream, lo, hi, created_after))
            return "s-1"

    clock = _clock()
    guard = _guard(_Spy(), clock).partition_guard(tmp_path, site="compaction")
    assert await guard(tmp_path / rel) == "s-1"
    assert calls == [("BTCUSDT", stream, lo, hi, clock.now - LIFE - RECLAIM - rw.SWEEP_LAG_MARGIN)]


async def test_cold_guard_reads_nothing_for_a_stream_no_session_replays(tmp_path: Path) -> None:
    broken = FailingCoveringRead(OSError())
    guard = _guard(broken).partition_guard(tmp_path, site="compaction")
    assert await guard(tmp_path / "bars/family=time/symbol=BTCUSDT/bar_param=1m/ym=2026-10") is None
    assert broken.calls == 0


@pytest.mark.parametrize(
    "rel",
    ["../trades/symbol=BTCUSDT/dt=2026-10-17", "nonsense/symbol=BTCUSDT/dt=2026-10-17",
     "trades/symbol=BTCUSDT", "trades/dt=2026-10-17", "trades/symbol=BTCUSDT/dt=2026-13-40", ""],
)  # fmt: skip
async def test_cold_guard_keeps_a_partition_whose_path_it_cannot_read(
    tmp_path: Path, rel: str
) -> None:
    before = _errors("downsample")
    guard = _guard().partition_guard(tmp_path / "cold", site="downsample")
    assert await guard(tmp_path / "cold" / rel) == rw.GUARD_UNVERIFIED
    assert _errors("downsample") == before + 1


def _real_settings(tmp_path: Path) -> Settings:
    return Settings(
        parquet_root=str(tmp_path / "parquet"),
        replay_max_lifetime_s=7200.0,
        replay_reclaim_interval_s=120.0,
    )


def test_build_passes_the_replay_lease_bounded_by_the_session_lifetime(tmp_path: Path) -> None:
    built = rw._build(_real_settings(tmp_path), _Audit(), cast(Any, SimpleNamespace(engine=None)))
    facts = built._facts
    assert isinstance(facts, rw.PgRetentionFacts)
    assert built._lease == facts.lease
    assert facts._guard._lifetime == timedelta(hours=2)
    assert facts._guard._reclaim == timedelta(minutes=2)


def test_compaction_is_built_with_the_replay_guard_when_postgres_is_wired(tmp_path: Path) -> None:
    registry = DatasetRegistry(tmp_path)
    settings = _real_settings(tmp_path)
    guarded = rw.build_compactor(settings, cast(Any, SimpleNamespace(engine=None)), registry)
    assert guarded._idle_guard is not compactor_mod._default_idle_guard
    # Without Postgres there are no replay sessions (`_attach_replay_sessions` needs it).
    bare = rw.build_compactor(settings, None, registry)
    assert bare._idle_guard is compactor_mod._default_idle_guard
    assert rw.cold_idle_guard(settings, None, registry.root, site="downsample") is None
