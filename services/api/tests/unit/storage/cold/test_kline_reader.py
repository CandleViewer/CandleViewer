"""Cold-tier kline reader: Parquet read-through, bounded scan, path safety, timeout (#2048)."""

from __future__ import annotations

import asyncio
import dataclasses
import math
import random
import shutil
import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from duckdb.sqltypes import BIGINT
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import example, given
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.api.market import MarketDataPrincipal, make_market_router
from candleviewer.ingestion.kline_coverage import Range
from candleviewer.ingestion.kline_read import KlineReadService
from candleviewer.observability.context import thread_future
from candleviewer.storage.cold import kline_reader as kr
from candleviewer.storage.cold.kline_reader import (
    ColdKlineReadTimeout,
    ColdKlineRow,
    ParquetKlineReader,
    months_between,
)
from candleviewer.storage.cold.layout import DatasetNotRegistered, DatasetRegistry
from candleviewer.storage.cold.manifest import ManifestEntry, ManifestStore, sha256_of
from candleviewer.storage.cold.observability import LoggingSystemEventSink
from candleviewer.storage.cold.scrub import scrub_all
from candleviewer.storage.models import StreamKind
from tests.unit.storage.cold._helpers import quarantine_before_next_read

MIN = 60_000_000
H = 60 * MIN


def _us(y: int, m: int, d: int = 1) -> int:
    return int(datetime(y, m, d, tzinfo=UTC).timestamp() * 1_000_000)


def _write(
    root: Path,
    ym: str,
    tss: list[int],
    symbol: str = "BTCUSDT",
    iv: str = "60",
    *,
    name: str = "part-0000.parquet",
) -> Path:
    n = len(tss)
    table = pa.table(
        {
            "ts": pa.array(tss, type=pa.timestamp("us", tz="UTC")),
            "open": [100.5] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "volume": [1.0] * n,
            "turnover": [100.0] * n,
            "confirmed": [True] * n,
            "source": ["ws"] * n,
        }
    )
    return _write_table(root, ym, table, symbol, iv, name=name)


def _write_table(
    root: Path,
    ym: str,
    table: pa.Table,
    symbol: str = "BTCUSDT",
    iv: str = "60",
    *,
    name: str = "part-0000.parquet",
) -> Path:
    """One part file plus its manifest entry (`append_reconciled`), as the exporter leaves it."""
    paths = DatasetRegistry(root).resolve_partition(
        StreamKind.KLINES, partition_values={"symbol": symbol, "interval": iv, "ym": ym}
    )
    paths.partition_dir.mkdir(parents=True, exist_ok=True)
    f = paths.partition_dir / name
    pq.write_table(table, f)
    ManifestStore(paths.manifests_dir).append_reconciled(
        paths.partition_dir,
        paths.root,
        ManifestEntry(
            file=f.name,
            sha256=sha256_of(f),
            row_count=table.num_rows,
            source_table="klines",
            export_run_id="r",
            exported_at_us=0,
        ),
    )
    return f


class _Hot:
    def __init__(self, rows: list[ColdKlineRow] | None = None) -> None:
        self.rows = rows or []

    async def read_klines(
        self, sym: str, interval: str, rng: Range, tier: str = "auto", limit: int | None = None
    ) -> list[ColdKlineRow]:
        return [r for r in self.rows if rng.start_us <= r.ts_us < rng.end_us]


def _svc(cold: ParquetKlineReader, boundary: int, hot: _Hot | None = None) -> KlineReadService:
    return KlineReadService(hot or _Hot(), cold=cold, hot_boundary_us=lambda: boundary)


async def test_cold_only_window_served_from_parquet(tmp_path: Path) -> None:
    t0 = _us(2026, 3)
    _write(tmp_path, "2026-03", [t0 + i * H for i in range(5)])
    svc = _svc(ParquetKlineReader(DatasetRegistry(tmp_path)), _us(2026, 6))
    res = await svc.read("BTCUSDT", "60", Range(t0, t0 + 10 * H), limit=3)
    assert [r.ts_us for r in res.rows] == [t0 + 2 * H, t0 + 3 * H, t0 + 4 * H]
    assert res.sources == ["parquet"]
    assert res.rows[0].open == "100.5"


async def test_hot_wins_overlap(tmp_path: Path) -> None:
    t0 = _us(2026, 3)
    _write(tmp_path, "2026-03", [t0, t0 + H])
    hot_row = ColdKlineRow(t0 + H, "1", "1", "1", "1", "1", "1", True, "ws")
    svc = _svc(ParquetKlineReader(DatasetRegistry(tmp_path)), t0 + H, _Hot([hot_row]))
    res = await svc.read("BTCUSDT", "60", Range(t0, t0 + 3 * H))
    by_ts = {r.ts_us: r for r in res.rows}
    assert by_ts[t0 + H].open == "1"  # hot value, not the cold twin (100.5)
    assert sorted(res.sources) == ["parquet", "questdb"]
    assert len(res.rows) == 2


async def test_parquet_not_claimed_without_cold_rows(tmp_path: Path) -> None:
    _write(tmp_path, "2026-03", [_us(2026, 3)])
    svc = _svc(ParquetKlineReader(DatasetRegistry(tmp_path)), _us(2026, 9))
    res = await svc.read("BTCUSDT", "60", Range(_us(2026, 5), _us(2026, 5, 2)))
    assert res.sources == []


def test_months_between_prunes_to_window() -> None:
    assert months_between(_us(2026, 1, 31), _us(2026, 3, 2)) == ["2026-01", "2026-02", "2026-03"]
    assert months_between(_us(2026, 3), _us(2026, 4)) == ["2026-03"]
    assert months_between(5, 5) == []


async def test_only_matching_partitions_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for ym in ("2026-02", "2026-03", "2026-04"):
        _write(tmp_path, ym, [_us(int(ym[:4]), int(ym[5:]))])
    reg = DatasetRegistry(tmp_path)
    seen: list[str] = []
    orig = reg.resolve_partition

    def spy(stream: StreamKind, *, partition_values: dict[str, str]) -> Any:
        seen.append(partition_values["ym"])
        return orig(stream, partition_values=partition_values)

    monkeypatch.setattr(reg, "resolve_partition", spy)
    rows = await ParquetKlineReader(reg)("BTCUSDT", "60", Range(_us(2026, 3), _us(2026, 3, 20)))
    assert seen == ["2026-03"]
    assert len(rows) == 1


@pytest.mark.parametrize(
    ("sym", "iv"), [("../x", "60"), ("BTCUSDT", "../60"), ("BTC/USDT", "60"), ("..", "60")]
)
async def test_hostile_components_rejected_before_filesystem(
    tmp_path: Path, sym: str, iv: str
) -> None:
    reader = ParquetKlineReader(DatasetRegistry(tmp_path))
    with pytest.raises(DatasetNotRegistered):
        await reader(sym, iv, Range(_us(2026, 3), _us(2026, 4)))


def _client(svc: KlineReadService) -> TestClient:
    class _Resolver:
        def resolve(self, request: object) -> MarketDataPrincipal:
            return MarketDataPrincipal(user_id="u", permissions=frozenset({"marketdata:read"}))

    class _Cache:
        async def read_klines(self, *a: object, **k: object) -> list[object]:
            return []

    app = FastAPI()
    app.include_router(
        make_market_router(
            lambda: _Cache(),  # type: ignore[arg-type,return-value]
            principal_resolver=_Resolver(),
            read_service_provider=lambda: svc,
            symbol_listed=lambda s: s == "BTCUSDT",
        )
    )
    return TestClient(app, client=("127.0.0.1", 50000))


def test_route_traversal_symbol_422_with_no_path_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reg = DatasetRegistry(tmp_path)
    calls: list[str] = []

    def spy(*a: object, **k: object) -> None:
        calls.append("path")

    monkeypatch.setattr(reg, "resolve_partition", spy)
    svc = _svc(ParquetKlineReader(reg), 10**18)
    r = _client(svc).get(
        "/market/klines",
        params={
            "symbol": "../x",
            "interval": "60",
            "from": "2026-03-01T00:00:00Z",
            "to": "2026-03-02T00:00:00Z",
        },
    )
    assert r.status_code == 422
    assert calls == []


async def test_duckdb_timeout_is_typed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    t0 = _us(2026, 3)
    _write(tmp_path, "2026-03", [t0])
    release = threading.Event()

    def slow(*a: object, **k: object) -> list[object]:
        release.wait(2)
        return []

    monkeypatch.setattr(kr, "_read_rows", slow)
    reader = ParquetKlineReader(DatasetRegistry(tmp_path), timeout_s=0.05)
    try:
        with pytest.raises(ColdKlineReadTimeout):
            await reader("BTCUSDT", "60", Range(t0, t0 + MIN))
    finally:
        release.set()


def test_route_maps_cold_timeout_to_503(tmp_path: Path) -> None:
    class _Boom:
        async def __call__(self, *a: object) -> list[ColdKlineRow]:
            raise ColdKlineReadTimeout("slow")

    svc = KlineReadService(_Hot(), cold=_Boom(), hot_boundary_us=lambda: 10**18)
    r = _client(svc).get(
        "/market/klines",
        params={
            "symbol": "BTCUSDT",
            "interval": "60",
            "from": "2026-03-01T00:00:00Z",
            "to": "2026-03-01T01:00:00Z",
        },
    )
    assert r.status_code == 503


async def test_round_trip_through_real_exporter(tmp_path: Path) -> None:
    """Writes via `ColdExporter.export_partition` so an E07 layout change breaks this test."""
    from candleviewer.storage.cold.exporter import ColdExporter
    from candleviewer.storage.models import TimeRange
    from tests.unit.storage.cold._helpers import FakeHotSource

    t0 = _us(2026, 3)
    n = 4
    table = pa.table(
        {
            "ts": pa.array([t0 + i * H for i in range(n)], type=pa.int64()),
            "symbol": ["BTCUSDT"] * n,
            "interval": ["60"] * n,
            "open": [100.5] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "volume": [1.0] * n,
            "turnover": [100.0] * n,
            "confirmed": [True] * n,
            "source": ["rest"] * n,
        }
    )
    reg = DatasetRegistry(tmp_path)
    exporter = ColdExporter(reg, FakeHotSource(table))
    await exporter.export_partition(
        "BTCUSDT",
        StreamKind.KLINES,
        TimeRange(start_us=t0, end_us=_us(2026, 4)),
        partition_extra={"interval": "60", "ym": "2026-03"},
    )
    rows = await ParquetKlineReader(reg)("BTCUSDT", "60", Range(t0, t0 + 10 * H))
    assert [r.ts_us for r in rows] == [t0 + i * H for i in range(n)]
    assert rows[0].open == "100.5"
    assert rows[0].source == "rest"


async def test_missing_optional_columns_do_not_fail(tmp_path: Path) -> None:
    t0 = _us(2026, 3)
    paths = DatasetRegistry(tmp_path).resolve_partition(
        StreamKind.KLINES,
        partition_values={"symbol": "BTCUSDT", "interval": "60", "ym": "2026-03"},
    )
    paths.partition_dir.mkdir(parents=True, exist_ok=True)
    f = paths.partition_dir / "part-0000.parquet"
    pq.write_table(
        pa.table({"ts": pa.array([t0], type=pa.timestamp("us", tz="UTC")), "open": [1.0]}), f
    )
    ManifestStore(paths.manifests_dir).append_reconciled(
        paths.partition_dir,
        paths.root,
        ManifestEntry(f.name, sha256_of(f), 1, "klines", "r", 0),
    )
    [row] = await ParquetKlineReader(DatasetRegistry(tmp_path))("BTCUSDT", "60", Range(t0, t0 + H))
    assert (row.source, row.confirmed, row.close) == ("parquet", True, "0")


async def test_unreadable_parquet_is_typed_error(tmp_path: Path) -> None:
    t0 = _us(2026, 3)
    paths = DatasetRegistry(tmp_path).resolve_partition(
        StreamKind.KLINES,
        partition_values={"symbol": "BTCUSDT", "interval": "60", "ym": "2026-03"},
    )
    paths.partition_dir.mkdir(parents=True, exist_ok=True)
    f = paths.partition_dir / "part-0000.parquet"
    pq.write_table(pa.table({"x": [1]}), f)  # no `ts` column
    ManifestStore(paths.manifests_dir).append_reconciled(
        paths.partition_dir,
        paths.root,
        ManifestEntry(f.name, sha256_of(f), 1, "klines", "r", 0),
    )
    with pytest.raises(kr.ColdKlineReadError):
        await ParquetKlineReader(DatasetRegistry(tmp_path))("BTCUSDT", "60", Range(t0, t0 + H))


async def test_duplicate_ts_deduped_before_limit(tmp_path: Path) -> None:
    t0 = _us(2026, 3)
    _write(tmp_path, "2026-03", [t0, t0, t0, t0 + H])
    rows = await ParquetKlineReader(DatasetRegistry(tmp_path), max_rows=2)(
        "BTCUSDT", "60", Range(t0, t0 + 2 * H)
    )
    assert [r.ts_us for r in rows] == [t0, t0 + H]


async def test_concurrent_reads_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    t0 = _us(2026, 3)
    _write(tmp_path, "2026-03", [t0])
    lock = threading.Lock()
    live = 0
    peak = 0

    def fake(*a: object, **k: object) -> list[ColdKlineRow]:
        nonlocal live, peak
        with lock:
            live += 1
            peak = max(peak, live)
        threading.Event().wait(0.05)
        with lock:
            live -= 1
        return []

    monkeypatch.setattr(kr, "_read_rows", fake)
    reader = ParquetKlineReader(DatasetRegistry(tmp_path), max_concurrency=2, timeout_s=5)
    await asyncio.gather(*[reader("BTCUSDT", "60", Range(t0, t0 + H)) for _ in range(6)])
    assert peak == 2


def _first_part(root: Path) -> Path:
    return next(root.rglob("part-0000.parquet"))


async def test_checksum_mismatch_fails_read_with_typed_error(tmp_path: Path) -> None:
    t0 = _us(2026, 3)
    _write(tmp_path, "2026-03", [t0])
    f = _first_part(tmp_path)
    f.write_bytes(f.read_bytes() + b"x")  # corrupt after manifesting
    with pytest.raises(kr.ColdKlineReadError):
        await ParquetKlineReader(DatasetRegistry(tmp_path))("BTCUSDT", "60", Range(t0, t0 + H))


async def test_unmanifested_file_is_ignored(tmp_path: Path) -> None:
    t0 = _us(2026, 3)
    _write(tmp_path, "2026-03", [t0])
    part = _first_part(tmp_path).parent
    pq.write_table(
        pa.table({"ts": pa.array([t0 + H], type=pa.timestamp("us", tz="UTC")), "open": [9.0]}),
        part / "part-0001.parquet",
    )
    rows = await ParquetKlineReader(DatasetRegistry(tmp_path))(
        "BTCUSDT", "60", Range(t0, t0 + 3 * H)
    )
    assert [r.ts_us for r in rows] == [t0]


async def test_window_straddling_boundary_merges_cold_and_hot(tmp_path: Path) -> None:
    t0 = _us(2026, 3)
    _write(tmp_path, "2026-03", [t0, t0 + H])
    hot = _Hot([ColdKlineRow(t0 + 2 * H, "1", "1", "1", "1", "1", "1", True, "ws")])
    svc = _svc(ParquetKlineReader(DatasetRegistry(tmp_path)), t0 + 2 * H, hot)
    res = await svc.read("BTCUSDT", "60", Range(t0, t0 + 3 * H))
    assert [r.ts_us for r in res.rows] == [t0, t0 + H, t0 + 2 * H]
    assert sorted(res.sources) == ["parquet", "questdb"]


async def test_cursor_taken_before_thread_and_only_it_interrupted_on_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N4 with one shared instance (#2523 lever 2): the read's cursor exists before the worker
    thread starts, and the timeout interrupts that cursor, never the shared instance."""
    t0 = _us(2026, 3)
    _write(tmp_path, "2026-03", [t0])
    events: list[str] = []
    real = kr.duckdb.connect

    class _Cur:
        def __init__(self, inner: duckdb.DuckDBPyConnection) -> None:
            self.inner = inner

        def interrupt(self) -> None:
            events.append("interrupt:cursor")

        def __getattr__(self, name: str) -> Any:
            return getattr(self.inner, name)

    class _Con:
        def __init__(self) -> None:
            self.inner = real(":memory:")

        def cursor(self) -> _Cur:
            events.append("cursor")
            return _Cur(self.inner.cursor())

        def interrupt(self) -> None:
            events.append("interrupt:instance")

        def __getattr__(self, name: str) -> Any:
            return getattr(self.inner, name)

    def fake_connect(*a: object, **k: object) -> _Con:
        events.append("connect")
        return _Con()

    release = threading.Event()
    handed: list[object] = []

    def slow(cur: object, *a: object) -> list[object]:
        handed.append(cur)
        events.append("thread")
        release.wait(2)
        return []

    monkeypatch.setattr(kr.duckdb, "connect", fake_connect)
    monkeypatch.setattr(kr, "_read_rows", slow)
    reader = ParquetKlineReader(DatasetRegistry(tmp_path), timeout_s=0.05)
    try:
        with pytest.raises(ColdKlineReadTimeout):
            await reader("BTCUSDT", "60", Range(t0, t0 + H))
    finally:
        release.set()
    assert events[:2] == ["connect", "cursor"]
    assert "thread" in events
    assert "interrupt:cursor" in events
    assert "interrupt:instance" not in events
    assert [type(c) for c in handed] == [_Cur]


def _connects(monkeypatch: pytest.MonkeyPatch) -> list[duckdb.DuckDBPyConnection]:
    """Every instance the reader opens, through the `kr.duckdb.connect` seam."""
    made: list[duckdb.DuckDBPyConnection] = []
    real = duckdb.connect

    def connect(*a: Any, **k: Any) -> duckdb.DuckDBPyConnection:
        con = real(*a, **k)
        made.append(con)
        return con

    monkeypatch.setattr(duckdb, "connect", connect)  # the module `kr.duckdb` names
    return made


async def test_reads_share_one_instance_and_the_worker_closes_its_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    t0 = _us(2026, 3)
    _write(tmp_path, "2026-03", [t0, t0 + H])
    made = _connects(monkeypatch)
    real_read = kr._read_rows
    loop_thread = threading.get_ident()
    closed_on: list[int] = []

    class _Cur:
        def __init__(self, inner: duckdb.DuckDBPyConnection) -> None:
            self.inner = inner

        def close(self) -> None:
            closed_on.append(threading.get_ident())
            self.inner.close()

        def __getattr__(self, name: str) -> Any:
            return getattr(self.inner, name)

    def spy(cur: duckdb.DuckDBPyConnection, *a: Any) -> list[ColdKlineRow]:
        return real_read(cast(duckdb.DuckDBPyConnection, _Cur(cur)), *a)  # duck-typed spy

    monkeypatch.setattr(kr, "_read_rows", spy)
    reader = ParquetKlineReader(DatasetRegistry(tmp_path))
    for _ in range(3):
        rows = await reader("BTCUSDT", "60", Range(t0, t0 + 2 * H))
        assert [r.ts_us for r in rows] == [t0, t0 + H]
    assert len(made) == 1  # one shared instance, opened lazily on the first read
    assert len(closed_on) == 3
    assert loop_thread not in closed_on  # N4: each worker closed its own cursor
    assert reader._db is not None
    assert reader._db.users == 0
    assert made[0].execute("SELECT 1").fetchall() == [(1,)]  # the instance itself stays open
    reader.close()
    with pytest.raises(duckdb.ConnectionException):
        made[0].execute("SELECT 1")


async def test_concurrent_real_reads_bounded_on_the_shared_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    t0 = _us(2026, 3)
    _write(tmp_path, "2026-03", [t0 + i * H for i in range(24)])
    made = _connects(monkeypatch)
    reader = ParquetKlineReader(DatasetRegistry(tmp_path), max_concurrency=2)
    peak = 0
    real_cursor = reader._cursor

    def counting() -> tuple[Any, duckdb.DuckDBPyConnection]:
        nonlocal peak
        db, cur = real_cursor()
        peak = max(peak, db.users)
        return db, cur

    monkeypatch.setattr(reader, "_cursor", counting)
    results = await asyncio.gather(
        *[reader("BTCUSDT", "60", Range(t0, t0 + 24 * H)) for _ in range(8)]
    )
    assert all(len(r) == 24 for r in results)
    assert peak <= 2
    assert len(made) == 1
    assert reader._db is not None
    assert reader._db.users == 0


def _worker_futures(monkeypatch: pytest.MonkeyPatch) -> list[asyncio.Future[Any]]:
    """Every worker future the reader starts, through the `kr.thread_future` seam."""
    futs: list[asyncio.Future[Any]] = []
    real = thread_future

    def spy(*a: Any) -> asyncio.Future[Any]:
        fut: asyncio.Future[Any] = real(*a)
        futs.append(fut)
        return fut

    monkeypatch.setattr(kr, "thread_future", spy)
    return futs


def _timeouts(monkeypatch: pytest.MonkeyPatch) -> list[asyncio.Timeout]:
    """Every `asyncio.timeout` the reader enters, so a test can fire one when it chooses."""
    made: list[asyncio.Timeout] = []

    class _Asyncio:
        def __getattr__(self, name: str) -> Any:
            return getattr(asyncio, name)

        def timeout(self, delay: float | None) -> asyncio.Timeout:
            t = asyncio.timeout(delay)
            made.append(t)
            return t

    monkeypatch.setattr(kr, "asyncio", _Asyncio())  # `kr`'s name only, not the module
    return made


async def test_timeout_interrupts_only_its_own_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read A is inside DuckDB (held by a UDF gate) while read B times out on the same shared
    instance: B's query is interrupted, A's finishes with its rows, the instance stays.

    B's deadline fires only once a UDF inside B's query has run, and that UDF holds B's query
    until the interrupt has reached B's cursor: an interrupt landing before a query starts is
    dropped by DuckDB, so neither may race B's thread start."""
    t0 = _us(2026, 3)
    _write(tmp_path, "2026-03", [t0])
    made = _connects(monkeypatch)
    deadlines = _timeouts(monkeypatch)
    real_read = kr._read_rows
    loop = asyncio.get_running_loop()
    a_inside = asyncio.Event()
    a_go = threading.Event()
    b_inside = asyncio.Event()
    b_started = threading.Event()
    interrupted = threading.Event()
    b_done = threading.Event()
    outcome: dict[str, str] = {}

    class _Cur:
        def __init__(self, inner: duckdb.DuckDBPyConnection) -> None:
            self.inner = inner

        def interrupt(self) -> None:
            self.inner.interrupt()
            interrupted.set()

        def __getattr__(self, name: str) -> Any:
            return getattr(self.inner, name)

    def gate(x: int) -> int:
        loop.call_soon_threadsafe(a_inside.set)
        a_go.wait(10)
        return x

    def b_running(x: int) -> int:
        if not b_started.is_set():
            b_started.set()
            loop.call_soon_threadsafe(b_inside.set)
        if not interrupted.wait(5):
            raise RuntimeError("no interrupt reached read B's cursor")
        return x

    def fake(cur: duckdb.DuckDBPyConnection, files: list[str], lo: int, *a: Any) -> Any:
        if lo == t0:  # read A
            cur.create_function("cv_gate_2523", gate, [BIGINT], BIGINT)
            outcome["a"] = str(cur.execute("SELECT cv_gate_2523(1)").fetchall())
            return real_read(cur, files, lo, *a)
        try:  # read B: runs until its own timeout interrupts it
            cur.create_function("cv_b_running_2523", b_running, [BIGINT], BIGINT)
            cur.execute(
                "SELECT count(*) FROM range(10000000000) t(i) WHERE cv_b_running_2523(i) % 7 = 3"
            ).fetchall()
            outcome["b"] = "completed"
        except duckdb.InterruptException as exc:
            outcome["b"] = "interrupted"
            raise kr.ColdKlineReadError("interrupted") from exc
        except duckdb.Error:
            outcome["b"] = "failed"
            raise
        finally:
            cur.close()
            b_done.set()
        return []

    monkeypatch.setattr(kr, "_read_rows", fake)
    reader = ParquetKlineReader(DatasetRegistry(tmp_path), timeout_s=30)
    real_cursor = reader._cursor

    def wrapped() -> tuple[Any, duckdb.DuckDBPyConnection]:
        db, cur = real_cursor()
        return db, cast(duckdb.DuckDBPyConnection, _Cur(cur))  # duck-typed spy

    monkeypatch.setattr(reader, "_cursor", wrapped)
    read_a = asyncio.create_task(reader("BTCUSDT", "60", Range(t0, t0 + H)))
    await a_inside.wait()
    try:
        read_b = asyncio.create_task(reader("BTCUSDT", "60", Range(t0 + 1, t0 + H)))
        await b_inside.wait()  # B's query is running inside DuckDB
        assert len(deadlines) == 2
        deadlines[1].reschedule(loop.time())  # fire B's deadline now; A's stays at 30 s
        with pytest.raises(ColdKlineReadTimeout):
            await read_b
        assert await asyncio.to_thread(b_done.wait, 10)
    finally:
        a_go.set()
    rows = await read_a
    assert outcome == {"a": "[(1,)]", "b": "interrupted"}
    assert [r.ts_us for r in rows] == [t0]
    assert len(made) == 1  # an interrupt is not a broken instance: nothing retired
    assert reader._db is not None
    assert reader._db.users == 0


async def test_cancelled_read_keeps_its_instance_until_the_worker_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancelled caller (or loop teardown) leaves its worker thread inside DuckDB: the read
    stays counted, so retiring the instance cannot close it under that worker."""
    t0 = _us(2026, 3)
    _write(tmp_path, "2026-03", [t0])
    made = _connects(monkeypatch)
    futs = _worker_futures(monkeypatch)
    real_read = kr._read_rows
    loop = asyncio.get_running_loop()
    inside = asyncio.Event()
    go = threading.Event()

    def gate(x: int) -> int:
        loop.call_soon_threadsafe(inside.set)
        go.wait(10)
        return x

    def held(cur: duckdb.DuckDBPyConnection, *a: Any) -> list[ColdKlineRow]:
        cur.create_function("cv_hold_2523", gate, [BIGINT], BIGINT)
        cur.execute("SELECT cv_hold_2523(1)").fetchall()
        return real_read(cur, *a)

    monkeypatch.setattr(kr, "_read_rows", held)
    reader = ParquetKlineReader(DatasetRegistry(tmp_path))
    read = asyncio.create_task(reader("BTCUSDT", "60", Range(t0, t0 + H)))
    try:
        await inside.wait()
        read.cancel()
        with pytest.raises(asyncio.CancelledError):
            await read
        db = reader._db
        assert db is not None
        assert db.users == 1  # the worker is still inside DuckDB
        reader.close()  # retire it under the live worker
        assert made[0].execute("SELECT 1").fetchall() == [(1,)]
    finally:
        go.set()
    await asyncio.wait(futs)  # `_release` was registered first, so it has run
    assert [r.ts_us for r in futs[0].result()] == [t0]  # the worker finished its read intact
    assert db.users == 0
    with pytest.raises(duckdb.ConnectionException):  # closed once its last read returned
        made[0].execute("SELECT 1")


async def test_timeout_racing_the_worker_closing_its_cursor_is_still_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`interrupt()` on a cursor the worker just closed raises ConnectionException; the
    caller still gets the typed timeout."""
    t0 = _us(2026, 3)
    _write(tmp_path, "2026-03", [t0])
    release = threading.Event()

    class _Cur:
        def __init__(self, inner: duckdb.DuckDBPyConnection) -> None:
            self.inner = inner

        def interrupt(self) -> None:
            self.inner.close()  # the worker closed it just as the deadline fired
            self.inner.interrupt()  # raises duckdb.ConnectionException

        def __getattr__(self, name: str) -> Any:
            return getattr(self.inner, name)

    def waits(cur: object, *a: object) -> list[object]:
        release.wait(10)
        return []

    monkeypatch.setattr(kr, "_read_rows", waits)
    reader = ParquetKlineReader(DatasetRegistry(tmp_path), timeout_s=0.05)
    real_cursor = reader._cursor

    def wrapped() -> tuple[Any, duckdb.DuckDBPyConnection]:
        db, cur = real_cursor()
        return db, cast(duckdb.DuckDBPyConnection, _Cur(cur))  # duck-typed spy

    monkeypatch.setattr(reader, "_cursor", wrapped)
    try:
        with pytest.raises(ColdKlineReadTimeout):
            await reader("BTCUSDT", "60", Range(t0, t0 + H))
    finally:
        release.set()


async def test_a_timed_out_reads_late_failure_is_logged_at_debug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    t0 = _us(2026, 3)
    _write(tmp_path, "2026-03", [t0])
    futs = _worker_futures(monkeypatch)
    release = threading.Event()

    def fails_late(cur: duckdb.DuckDBPyConnection, *a: object) -> list[object]:
        release.wait(10)
        cur.close()
        raise kr.ColdKlineReadError("interrupted") from duckdb.InterruptException("stop")

    monkeypatch.setattr(kr, "_read_rows", fails_late)
    reader = ParquetKlineReader(DatasetRegistry(tmp_path), timeout_s=0.05)
    with capture_logs() as logs:
        try:
            with pytest.raises(ColdKlineReadTimeout):
                await reader("BTCUSDT", "60", Range(t0, t0 + H))
        finally:
            release.set()
        await asyncio.wait(futs)
    late = [e for e in logs if e["event"] == "cold_kline_read_late_failure"]
    assert late == [
        {
            "event": "cold_kline_read_late_failure",
            "log_level": "debug",
            "error": "ColdKlineReadError",
            "cause": "InterruptException",
        }
    ]
    assert reader._db is not None  # our own interrupt's failure retires nothing


async def test_broken_shared_instance_is_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    t0 = _us(2026, 3)
    _write(tmp_path, "2026-03", [t0])
    made = _connects(monkeypatch)
    reader = ParquetKlineReader(DatasetRegistry(tmp_path))
    assert [r.ts_us for r in await reader("BTCUSDT", "60", Range(t0, t0 + H))] == [t0]
    made[0].close()  # the shared connection breaks under the reader: cursor() now fails
    assert [r.ts_us for r in await reader("BTCUSDT", "60", Range(t0, t0 + H))] == [t0]
    assert len(made) == 2
    assert reader._db is not None
    assert reader._db.con is made[1]


async def test_failed_read_retires_the_instance_and_the_next_read_gets_a_fresh_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    t0 = _us(2026, 3)
    _write(tmp_path, "2026-03", [t0])
    made = _connects(monkeypatch)
    real_read = kr._read_rows

    def poisoned(cur: duckdb.DuckDBPyConnection, *a: object) -> list[object]:
        cur.close()
        raise kr.ColdKlineReadError("boom") from duckdb.FatalException("database invalidated")

    monkeypatch.setattr(kr, "_read_rows", poisoned)
    reader = ParquetKlineReader(DatasetRegistry(tmp_path))
    with pytest.raises(kr.ColdKlineReadError):
        await reader("BTCUSDT", "60", Range(t0, t0 + H))
    assert reader._db is None
    with pytest.raises(duckdb.ConnectionException):  # retired with no reader left: closed
        made[0].execute("SELECT 1")
    monkeypatch.setattr(kr, "_read_rows", real_read)
    assert [r.ts_us for r in await reader("BTCUSDT", "60", Range(t0, t0 + H))] == [t0]
    assert len(made) == 2


async def test_retired_instance_closes_only_after_its_in_flight_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Closing an instance closes its cursors, so `close()` during a read must wait for it."""
    t0 = _us(2026, 3)
    _write(tmp_path, "2026-03", [t0])
    made = _connects(monkeypatch)
    real_read = kr._read_rows
    loop = asyncio.get_running_loop()
    inside = asyncio.Event()
    go = threading.Event()

    def held(cur: duckdb.DuckDBPyConnection, *a: Any) -> list[ColdKlineRow]:
        loop.call_soon_threadsafe(inside.set)
        go.wait(10)
        return real_read(cur, *a)

    monkeypatch.setattr(kr, "_read_rows", held)
    reader = ParquetKlineReader(DatasetRegistry(tmp_path))
    read = asyncio.create_task(reader("BTCUSDT", "60", Range(t0, t0 + H)))
    await inside.wait()
    reader.close()
    assert made[0].execute("SELECT 1").fetchall() == [(1,)]  # still open for the read
    go.set()
    assert [r.ts_us for r in await read] == [t0]
    with pytest.raises(duckdb.ConnectionException):
        made[0].execute("SELECT 1")
    reader.close()  # idempotent with no instance


async def test_late_failure_on_a_retired_instance_leaves_its_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    t0 = _us(2026, 3)
    _write(tmp_path, "2026-03", [t0])
    made = _connects(monkeypatch)
    real_read = kr._read_rows
    loop = asyncio.get_running_loop()
    inside = asyncio.Event()
    go = threading.Event()

    def held_then_fails(cur: duckdb.DuckDBPyConnection, *a: Any) -> list[ColdKlineRow]:
        loop.call_soon_threadsafe(inside.set)
        go.wait(10)
        cur.close()
        raise kr.ColdKlineReadError("boom")

    monkeypatch.setattr(kr, "_read_rows", held_then_fails)
    reader = ParquetKlineReader(DatasetRegistry(tmp_path))
    first = asyncio.create_task(reader("BTCUSDT", "60", Range(t0, t0 + H)))
    await inside.wait()
    reader.close()
    monkeypatch.setattr(kr, "_read_rows", real_read)
    assert [r.ts_us for r in await reader("BTCUSDT", "60", Range(t0, t0 + H))] == [t0]
    go.set()
    with pytest.raises(kr.ColdKlineReadError):
        await first
    assert reader._db is not None
    assert reader._db.con is made[1]  # the replacement survives the old instance's failure
    with pytest.raises(duckdb.ConnectionException):
        made[0].execute("SELECT 1")


async def test_both_cursor_attempts_failing_is_a_typed_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    t0 = _us(2026, 3)
    _write(tmp_path, "2026-03", [t0])
    real = duckdb.connect

    def closed(*a: Any, **k: Any) -> duckdb.DuckDBPyConnection:
        con = real(*a, **k)
        con.close()
        return con

    monkeypatch.setattr(duckdb, "connect", closed)
    reader = ParquetKlineReader(DatasetRegistry(tmp_path))
    with pytest.raises(kr.ColdKlineReadError):
        await reader("BTCUSDT", "60", Range(t0, t0 + H))
    assert reader._db is None


# #3477 (C-2.14): a month that lost a part to quarantine is refused, never served partly.


def _mirror(root: Path, ym: str = "2026-03") -> Path:
    """Where `ManifestStore.quarantine` moves the month's bad parts."""
    return root / "_quarantine" / "klines" / "symbol=BTCUSDT" / "interval=60" / f"ym={ym}"


async def _lose_a_part(root: Path) -> tuple[int, Range]:
    """Two manifested parts in 2026-03; the second goes bad, and the read that finds it
    quarantines it."""
    t0 = _us(2026, 3)
    _write(root, "2026-03", [t0])
    bad = _write(root, "2026-03", [t0 + H], name="part-0001.parquet")
    bad.write_bytes(bad.read_bytes() + b"x")
    window = Range(t0, t0 + 3 * H)
    with pytest.raises(kr.ColdKlineReadError, match="failed verification"):
        await ParquetKlineReader(DatasetRegistry(root))("BTCUSDT", "60", window)
    assert _mirror(root).is_dir()
    return t0, window


async def test_a_month_that_lost_a_part_refuses_every_later_read(tmp_path: Path) -> None:
    """The manifest no longer names the quarantined part, so serving the rest would serve the
    month partly. The refusal names no path."""
    _, window = await _lose_a_part(tmp_path)

    for _ in range(2):
        with pytest.raises(kr.ColdKlineReadError, match="quarantined part") as err:
            await ParquetKlineReader(DatasetRegistry(tmp_path))("BTCUSDT", "60", window)
        assert "/" not in str(err.value)
        assert err.value.__cause__ is None and err.value.__context__ is None


async def test_a_reader_that_verified_the_month_refuses_it_once_the_scrub_quarantines_a_part(
    tmp_path: Path,
) -> None:
    """The weekly scrub quarantines without any read: the parts that remain verified in the
    reader's cache must not be served as the whole month."""
    t0 = _us(2026, 3)
    _write(tmp_path, "2026-03", [t0])
    second = _write(tmp_path, "2026-03", [t0 + H], name="part-0001.parquet")
    reader = ParquetKlineReader(DatasetRegistry(tmp_path))
    window = Range(t0, t0 + 3 * H)
    assert [r.ts_us for r in await reader("BTCUSDT", "60", window)] == [t0, t0 + H]
    second.write_bytes(second.read_bytes() + b"x")
    assert await scrub_all(DatasetRegistry(tmp_path), LoggingSystemEventSink()) == 1

    with pytest.raises(kr.ColdKlineReadError, match="quarantined part"):
        await reader("BTCUSDT", "60", window)


async def test_clearing_the_quarantine_after_a_re_export_restores_the_month(
    tmp_path: Path,
) -> None:
    t0, window = await _lose_a_part(tmp_path)
    _write(tmp_path, "2026-03", [t0 + H], name="part-0002.parquet")  # the re-export
    with pytest.raises(kr.ColdKlineReadError, match="quarantined part"):  # until cleared by hand
        await ParquetKlineReader(DatasetRegistry(tmp_path))("BTCUSDT", "60", window)

    shutil.rmtree(_mirror(tmp_path))  # the runbook's last step

    rows = await ParquetKlineReader(DatasetRegistry(tmp_path))("BTCUSDT", "60", window)
    assert [r.ts_us for r in rows] == [t0, t0 + H]


async def test_a_quarantine_in_one_month_leaves_the_other_months_served(tmp_path: Path) -> None:
    await _lose_a_part(tmp_path)
    april = _us(2026, 4)
    _write(tmp_path, "2026-04", [april])

    rows = await ParquetKlineReader(DatasetRegistry(tmp_path))(
        "BTCUSDT", "60", Range(april, april + H)
    )

    assert [r.ts_us for r in rows] == [april]


async def test_a_month_whose_only_part_went_missing_refuses_rather_than_reading_empty(
    tmp_path: Path,
) -> None:
    """A part found missing is quarantined by its manifest entry alone: nothing moves, the
    manifest is left empty and the mirror is an empty directory. The month must not then read
    as one with no bars."""
    t0 = _us(2026, 3)
    _write(tmp_path, "2026-03", [t0]).unlink()
    window = Range(t0, t0 + H)
    with pytest.raises(kr.ColdKlineReadError, match="failed verification"):
        await ParquetKlineReader(DatasetRegistry(tmp_path))("BTCUSDT", "60", window)
    assert not any(_mirror(tmp_path).iterdir())

    with pytest.raises(kr.ColdKlineReadError, match="quarantined part"):
        await ParquetKlineReader(DatasetRegistry(tmp_path))("BTCUSDT", "60", window)


async def test_a_quarantine_landing_just_before_the_manifest_read_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`quarantine` marks the partition before it shrinks the manifest, and the reader reads the
    manifest before it looks for the mark, so no interleaving serves the month partly."""
    t0 = _us(2026, 3)
    _write(tmp_path, "2026-03", [t0])
    _write(tmp_path, "2026-03", [t0 + H], name="part-0001.parquet")
    quarantine_before_next_read(monkeypatch, "part-0001.parquet")

    with pytest.raises(kr.ColdKlineReadError, match="quarantined part"):
        await ParquetKlineReader(DatasetRegistry(tmp_path))("BTCUSDT", "60", Range(t0, t0 + 3 * H))


async def test_a_month_that_cannot_be_listed_is_refused_typed_naming_no_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    t0 = _us(2026, 3)
    _write(tmp_path, "2026-03", [t0])

    def denied(self: ManifestStore, partition_dir: Path, cold_root: Path) -> object:
        raise PermissionError(13, "Permission denied", str(partition_dir))

    monkeypatch.setattr(ManifestStore, "read", denied)

    with pytest.raises(kr.ColdKlineReadError, match="could not be listed") as err:
        await ParquetKlineReader(DatasetRegistry(tmp_path))("BTCUSDT", "60", Range(t0, t0 + H))
    assert str(tmp_path) not in str(err.value)
    assert err.value.__cause__ is None and err.value.__suppress_context__


async def test_a_month_retention_removed_reads_empty_though_its_quarantine_stays(
    tmp_path: Path,
) -> None:
    """Retention deletes a partition and its manifest, never `_quarantine/`: with no manifest
    left there is nothing to serve partly, so the month reads empty rather than refusing forever."""
    _, window = await _lose_a_part(tmp_path)
    shutil.rmtree(tmp_path / "klines" / "symbol=BTCUSDT" / "interval=60" / "ym=2026-03")
    next((tmp_path / "_manifests" / "klines").rglob("ym=2026-03.json")).unlink()
    assert _mirror(tmp_path).is_dir()

    assert await ParquetKlineReader(DatasetRegistry(tmp_path))("BTCUSDT", "60", window) == []


def test_the_route_answers_503_for_a_month_that_lost_a_part(tmp_path: Path) -> None:
    t0 = _us(2026, 3)
    _write(tmp_path, "2026-03", [t0])
    lost = _write(tmp_path, "2026-03", [t0 + H], name="part-0001.parquet")
    store = ManifestStore(tmp_path / "_manifests")
    store.quarantine(lost.parent, tmp_path, lost.name)  # as verification does
    svc = _svc(ParquetKlineReader(DatasetRegistry(tmp_path)), _us(2026, 6))

    r = _client(svc).get(
        "/market/klines",
        params={
            "symbol": "BTCUSDT",
            "interval": "60",
            "from": "2026-03-01T00:00:00Z",
            "to": "2026-03-01T03:00:00Z",
        },
    )

    assert r.status_code == 503
    assert str(tmp_path) not in r.text


# --- #2523: the row build is byte-identical to the pre-fix construction ---------------------


def _old_num(value: object) -> str:
    """The pre-#2523 `_num`, kept verbatim as the reference."""
    return format(Decimal(repr(value)), "f") if isinstance(value, float) else str(value)


@given(st.floats(allow_nan=False, allow_infinity=False))
@example(0.0)
@example(-0.0)
@example(5e-324)  # smallest subnormal
@example(-2.225073858507201e-308)  # largest negative subnormal
@example(2.2250738585072014e-308)  # smallest normal
@example(1e-05)  # repr switches to exponent form below 1e-4
@example(0.0001)
@example(1e16)  # and at or above 1e16
@example(9999999999999998.0)
@example(-1.5e300)
@example(1.7976931348623157e308)
@example(100.5)
@example(60123.4)
def test_num_matches_the_decimal_text_for_every_finite_float(value: float) -> None:
    assert kr._num(value) == format(Decimal(repr(value)), "f")


@pytest.mark.parametrize(
    ("value", "text"), [(math.inf, "Infinity"), (-math.inf, "-Infinity"), (math.nan, "NaN")]
)
def test_num_non_finite_takes_the_decimal_path(value: float, text: str) -> None:
    # `repr` would give "inf"/"nan": only the Decimal path yields the pre-#2523 text.
    assert kr._num(value) == _old_num(value) == text


@pytest.mark.parametrize("value", ["0", 7, True, None, Decimal("1.50")])
def test_num_non_float_is_its_str(value: object) -> None:
    assert kr._num(value) == _old_num(value) == str(value)


def _old_read_rows(
    con: duckdb.DuckDBPyConnection, files: list[str], lo: int, hi: int, max_rows: int
) -> list[ColdKlineRow]:
    """The pre-#2523 `_read_rows` (tz-aware `ts`, per-row dicts, Decimal `_num`)."""
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    con.execute("SET TimeZone = 'UTC'")
    table = con.execute(
        "SELECT * FROM read_parquet($files, hive_partitioning = false, union_by_name = true) "
        "WHERE ts >= make_timestamptz($lo::BIGINT) AND ts < make_timestamptz($hi::BIGINT) "
        "QUALIFY row_number() OVER (PARTITION BY ts ORDER BY ts) = 1 "
        "ORDER BY ts DESC LIMIT $n",
        {"files": files, "lo": lo, "hi": hi, "n": max_rows},
    ).to_arrow_table()
    con.close()
    out = [
        ColdKlineRow(
            ts_us=(r["ts"] - epoch) // timedelta(microseconds=1),
            open=_old_num(r.get("open", "0")),
            high=_old_num(r.get("high", "0")),
            low=_old_num(r.get("low", "0")),
            close=_old_num(r.get("close", "0")),
            volume=_old_num(r.get("volume", "0")),
            turnover=_old_num(r.get("turnover", "0")),
            confirmed=bool(r.get("confirmed", True)),
            source=str(r.get("source") or "parquet"),
        )
        for r in table.to_pylist()
    ]
    out.sort(key=lambda x: x.ts_us)
    return out


def _seeded_value(rng: random.Random) -> float:
    pick = rng.randrange(6)
    if pick == 0:
        return round(rng.uniform(1, 100_000), rng.randrange(0, 5))
    if pick == 1:
        return rng.uniform(0, 1e-4) * rng.choice((1.0, -1.0))  # exponent-form repr
    if pick == 2:
        return rng.uniform(1e16, 1e20)
    if pick == 3:
        return rng.choice((0.0, -0.0, 5e-324, math.inf, -math.inf, math.nan))
    return rng.uniform(-1e6, 1e6)


def _seeded_columns(rng: random.Random, tss: list[int], names: tuple[str, ...]) -> pa.Table:
    cols: dict[str, Any] = {"ts": pa.array(tss, type=pa.timestamp("us", tz="UTC"))}
    for name in names:
        if name == "confirmed":
            cols[name] = [rng.random() < 0.9 for _ in tss]
        elif name == "source":
            cols[name] = [rng.choice(("ws", "rest", "", "tape")) for _ in tss]
        else:
            cols[name] = [_seeded_value(rng) for _ in tss]
    return pa.table(cols)


def _part_files(root: Path) -> list[str]:
    return sorted(p.as_posix() for p in root.rglob("part-*.parquet"))


_ALL = ("open", "high", "low", "close", "volume", "turnover", "confirmed", "source")


@pytest.mark.parametrize("seed", [2523, 7, 11])
@pytest.mark.parametrize("max_rows", [5_100, 150])
async def test_read_rows_are_identical_to_the_pre_2523_construction(
    tmp_path: Path, seed: int, max_rows: int
) -> None:
    """Seeded window over three parts: a full-schema part with exponent forms, -0.0,
    subnormals, inf/nan and empty sources; a part missing `turnover`/`source` (union_by_name
    nulls); and a duplicate of part 0's first rows (dedupe before LIMIT)."""
    rng = random.Random(seed)  # noqa: S311 - seeded, reproducible test data
    t0 = _us(2026, 3)
    full = _seeded_columns(rng, [t0 + i * MIN for i in range(400)], _ALL)
    _write_table(tmp_path, "2026-03", full)
    partial = _seeded_columns(rng, [t0 + (400 + i) * MIN for i in range(200)], _ALL[:5])
    _write_table(tmp_path, "2026-03", partial, name="part-0001.parquet")
    _write_table(tmp_path, "2026-03", full.slice(0, 50), name="part-0002.parquet")
    files = _part_files(tmp_path)
    lo, hi = t0 + 10 * MIN, t0 + 590 * MIN

    def con() -> duckdb.DuckDBPyConnection:
        return duckdb.connect(":memory:")

    got = kr._read_rows(con(), files, lo, hi, max_rows)
    want = _old_read_rows(con(), files, lo, hi, max_rows)

    assert len(got) == min(580, max_rows)
    assert [dataclasses.astuple(r) for r in got] == [dataclasses.astuple(r) for r in want]
    assert all(type(r.ts_us) is int for r in got)
    read = await ParquetKlineReader(DatasetRegistry(tmp_path), max_rows=max_rows)(
        "BTCUSDT", "60", Range(lo, hi)
    )
    assert read == want


async def test_read_rows_columns_no_file_carries_default_like_before(tmp_path: Path) -> None:
    t0 = _us(2026, 3)
    rng = random.Random(1)  # noqa: S311 - seeded, reproducible test data
    table = _seeded_columns(rng, [t0 + i * MIN for i in range(30)], ("open",))
    _write_table(tmp_path, "2026-03", table)
    files = _part_files(tmp_path)

    got = kr._read_rows(duckdb.connect(":memory:"), files, t0, t0 + H, 5_100)

    assert got == _old_read_rows(duckdb.connect(":memory:"), files, t0, t0 + H, 5_100)
    assert {(r.close, r.turnover, r.confirmed, r.source) for r in got} == {
        ("0", "0", True, "parquet")
    }
