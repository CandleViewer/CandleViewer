"""Cold-tier kline reader: Parquet read-through, bounded scan, path safety, timeout (#2048)."""

from __future__ import annotations

import shutil
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api.market import MarketDataPrincipal, make_market_router
from candleviewer.ingestion.kline_coverage import Range
from candleviewer.ingestion.kline_read import KlineReadService
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
    paths = DatasetRegistry(root).resolve_partition(
        StreamKind.KLINES, partition_values={"symbol": symbol, "interval": iv, "ym": ym}
    )
    paths.partition_dir.mkdir(parents=True, exist_ok=True)
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
    f = paths.partition_dir / name
    pq.write_table(table, f)
    ManifestStore(paths.manifests_dir).append_reconciled(
        paths.partition_dir,
        paths.root,
        ManifestEntry(
            file=f.name,
            sha256=sha256_of(f),
            row_count=n,
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


async def test_connection_created_before_thread_and_interrupted_on_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    t0 = _us(2026, 3)
    _write(tmp_path, "2026-03", [t0])
    events: list[str] = []
    real = kr.duckdb.connect

    class _Con:
        def __init__(self) -> None:
            self.inner = real(":memory:")

        def interrupt(self) -> None:
            events.append("interrupt")

        def __getattr__(self, name: str) -> Any:
            return getattr(self.inner, name)

    def fake_connect(*a: object, **k: object) -> _Con:
        events.append("connect")
        return _Con()

    release = threading.Event()

    def slow(*a: object, **k: object) -> list[object]:
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
    assert events[0] == "connect"
    assert "interrupt" in events


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
