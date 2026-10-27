"""#2523 lever 5: `ParquetKlineReader.page`'s byte-bounded LRU of cold pages.

A page is cached under `(symbol, interval, lo_us, hi_us, max_rows)` plus the sorted
`(path, size, mtime_ns, sha256)` of every Parquet file the read resolved, the sha256 its manifest
entry's. Roll-off, import, compaction and purge each add, rewrite or delete a file, so each is a
new key: one test per path here, one per part of a rewritten file's stamp, and a hypothesis
interleaving of writes and reads against a reader with no cache. A quarantined, corrupt or
missing part fails the read even with its page cached. Also pinned: the bound
(`CV_COLD_KLINE_PAGE_CACHE_BYTES`: 0 = off, at most 1 GiB), an entry's cost (with the fixed
allowance for what DuckDB's Arrow export holds), the quarter-bound rule, LRU eviction, empty
pages never cached, `close()` dropping the pages, a hit taking no DuckDB slot, and no
single-flight. The route golden, a miss then a hit, is
`tests/unit/api/test_market_response_columnar.py`.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st
from prometheus_client import REGISTRY
from pydantic import ValidationError

from candleviewer.ingestion.kline_coverage import Range
from candleviewer.settings import Settings
from candleviewer.storage.cold import kline_reader as kr
from candleviewer.storage.cold.kline_reader import (
    ColdKlinePage,
    ColdKlineReadError,
    ParquetKlineReader,
)
from candleviewer.storage.cold.layout import ColdPaths, DatasetRegistry
from candleviewer.storage.cold.manifest import ManifestEntry, ManifestStore, sha256_of
from candleviewer.storage.models import StreamKind
from tests.unit.storage.cold.test_kline_page import _table
from tests.unit.storage.cold.test_kline_reader import MIN, H, _us, _write, _write_table

E = _us(2026, 4)  # a month edge: partition 2026-03 holds the hours before it, 2026-04 the rest
ON = 64 << 20  # the app's default bound: no page here is refused or evicted under it
ALLOWANCE = 384 * 1024  # `kr._PAGE_OVERHEAD_BYTES`: every page's fixed share of the bound
T0 = 10**18  # an mtime_ns the rewrites set, so no test leans on the filesystem's clock


def _series(name: str) -> float:
    return REGISTRY.get_sample_value(f"cv_cold_kline_page_cache_{name}") or 0.0


def _view(got: object) -> object:
    """What a route serves from a cold read: a page's bar JSON and rows; anything else as is."""
    return (got.bars_json(b""), got.rows()) if isinstance(got, ColdKlinePage) else got


async def _page(reader: ParquetKlineReader, window: Range) -> Any:
    return await reader.page("BTCUSDT", "60", window)


def _hours(lo: int, n: int) -> list[int]:
    return [lo + k * H for k in range(n)]


def _hourly(values: Sequence[float], lo: int) -> pa.Table:
    """`_table`'s bars (each price column a rotation of `values`), one an hour from `lo`."""
    return _table([*values], lo).set_column(
        0, "ts", pa.array(_hours(lo, len(values)), pa.timestamp("us", tz="UTC"))
    )


def _paths(root: Path, ym: str) -> ColdPaths:
    return DatasetRegistry(root).resolve_partition(
        StreamKind.KLINES, partition_values={"symbol": "BTCUSDT", "interval": "60", "ym": ym}
    )


@pytest.fixture
def scans(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """One entry per `_read_page` call: a DuckDB scan, so a read the cache did not serve."""
    calls: list[int] = []
    real = kr._read_page

    def spy(*a: Any) -> Any:
        calls.append(1)
        return real(*a)

    monkeypatch.setattr(kr, "_read_page", spy)
    return calls


async def test_a_repeated_read_is_one_scan_and_the_same_page(
    tmp_path: Path, scans: list[int]
) -> None:
    _write(tmp_path, "2026-03", _hours(E - 24 * H, 24))
    reader = ParquetKlineReader(DatasetRegistry(tmp_path), page_cache_bytes=ON)
    before = {name: _series(name) for name in ("hits_total", "misses_total", "bytes")}
    first = await _page(reader, Range(E - 24 * H, E))
    assert await _page(reader, Range(E - 24 * H, E)) is first and len(scans) == 1
    assert _series("misses_total") - before["misses_total"] == 1
    assert _series("hits_total") - before["hits_total"] == 1
    assert _series("bytes") - before["bytes"] == kr._page_cost(first) == reader._pages.held
    reader.close()


@pytest.mark.parametrize("bound", [None, 0], ids=["default", "zero"])
async def test_the_reader_default_and_a_zero_bound_cache_nothing(
    tmp_path: Path, scans: list[int], bound: int | None
) -> None:
    _write(tmp_path, "2026-03", [E - H])
    registry = DatasetRegistry(tmp_path)
    if bound is None:
        reader = ParquetKlineReader(registry)
    else:
        reader = ParquetKlineReader(registry, page_cache_bytes=bound)
    counted = (_series("hits_total"), _series("misses_total"))
    for _ in range(2):
        assert isinstance(await _page(reader, Range(E - H, E)), ColdKlinePage)
    assert len(scans) == 2 and (_series("hits_total"), _series("misses_total")) == counted
    reader.close()


async def test_a_hit_is_served_before_the_duckdb_slots(tmp_path: Path) -> None:
    _write(tmp_path, "2026-03", [E - H])
    reader = ParquetKlineReader(DatasetRegistry(tmp_path), page_cache_bytes=ON)
    page = await _page(reader, Range(E - H, E))
    async with reader._sem, reader._sem, asyncio.timeout(5):  # both slots held elsewhere
        assert await _page(reader, Range(E - H, E)) is page
    reader.close()


async def test_rows_of_a_page_that_cannot_be_emitted_are_never_cached(
    tmp_path: Path, scans: list[int]
) -> None:
    _write_table(tmp_path, "2026-03", _table([1.0, 2.0], E - H, open=pa.array(["1.5", "2"])))
    reader = ParquetKlineReader(DatasetRegistry(tmp_path), page_cache_bytes=ON)
    for _ in range(2):
        assert isinstance(await _page(reader, Range(E - H, E)), list)
    assert len(scans) == 2 and reader._pages.held == 0
    reader.close()


async def test_an_empty_page_is_never_cached(tmp_path: Path, scans: list[int]) -> None:
    """A window its files hold no bar of reads a 0-row page: it would cost the allowance and
    serve nothing, so every read of it scans."""
    _write(tmp_path, "2026-03", _hours(E - 24 * H, 12))  # no bar in the last 12 hours
    reader = ParquetKlineReader(DatasetRegistry(tmp_path), page_cache_bytes=ON)
    for _ in range(2):
        page = await _page(reader, Range(E - 6 * H, E))
        assert isinstance(page, ColdKlinePage) and len(page) == 0
    assert len(scans) == 2 and (reader._pages.held, len(reader._pages._entries)) == (0, 0)
    reader.close()


@pytest.mark.parametrize("bars", [0, 1, 7])
async def test_an_entry_costs_its_table_its_bar_json_and_a_fixed_allowance(
    tmp_path: Path, bars: int
) -> None:
    """The allowance covers what DuckDB's Arrow export holds beyond `table.nbytes` (337 to
    378 KB a page on the fixture lake), so the bound caps what the pages really hold."""
    _write_table(tmp_path, "2026-03", _table([1.5, 1e-07, None, 2.25, 3.0, 4.5, 6.0], E - H))
    reader = ParquetKlineReader(DatasetRegistry(tmp_path))
    page = await _page(reader, Range(E - H + (7 - bars) * MIN, E))  # the newest `bars` bars
    assert isinstance(page, ColdKlinePage) and len(page) == bars
    assert kr._PAGE_OVERHEAD_BYTES == ALLOWANCE
    assert kr._page_cost(page) == page.table.nbytes + len(page.bars_json(b"")) + ALLOWANCE
    reader.close()


async def test_one_bar_pages_hold_no_more_than_the_bound(tmp_path: Path) -> None:
    """However small a page, it costs the allowance, so at most `bound // ALLOWANCE` pages are
    held and their cost stays within the bound."""
    _write(tmp_path, "2026-03", _hours(E - 24 * H, 24))
    bound = 8 * ALLOWANCE
    reader = ParquetKlineReader(DatasetRegistry(tmp_path), page_cache_bytes=bound)
    gauge = _series("bytes")
    for k in range(24):  # 24 one-bar windows, each its own key
        assert len(await _page(reader, Range(E - (k + 1) * H, E - k * H))) == 1
    assert 0 < len(reader._pages._entries) <= bound // ALLOWANCE
    assert reader._pages.held == _series("bytes") - gauge <= bound
    reader.close()


async def _assert_fresh_after(root: Path, window: Range, write: Callable[[], object]) -> None:
    """Cache the window's page (a miss, then a hit), `write`, then read it again: the bytes are a
    fresh read's, never the cached page's."""
    cached = ParquetKlineReader(DatasetRegistry(root), page_cache_bytes=ON)
    fresh = ParquetKlineReader(DatasetRegistry(root))
    stale = await _page(cached, window)
    assert await _page(cached, window) is stale
    write()
    assert _view(await _page(cached, window)) == _view(await _page(fresh, window)) != _view(stale)
    cached.close()
    fresh.close()


async def test_a_file_added_to_the_window_is_read(tmp_path: Path) -> None:
    _write(tmp_path, "2026-03", _hours(E - 24 * H, 12))

    def add() -> None:
        _write(tmp_path, "2026-03", _hours(E - 12 * H, 12), name="part-0001.parquet")

    await _assert_fresh_after(tmp_path, Range(E - 24 * H, E), add)


async def test_a_file_rewritten_in_place_is_read(tmp_path: Path) -> None:
    """The rewrite lands later, as a write does (its mtime moves on), with another size and
    checksum; rewrites that keep part of that stamp are pinned below. One that keeps a file's
    size, `mtime_ns` and manifest checksum is the one blind spot."""
    f = _write(tmp_path, "2026-03", _hours(E - 12 * H, 12))

    def rewrite() -> None:
        mtime = f.stat().st_mtime_ns + 1_000_000_000
        _write_table(tmp_path, "2026-03", _hourly([7.5] * 12, E - 12 * H))
        os.utime(f, ns=(mtime, mtime))

    await _assert_fresh_after(tmp_path, Range(E - 24 * H, E), rewrite)


def _write_plain(root: Path, values: Sequence[float], mtime_ns: int) -> Path:
    """2026-03's `part-0000`, the hours before `E`, with no compression or dictionary, so a
    rewrite with as many other values keeps its size. Its manifest entry is recorded as the
    exporter records it (the file's sha256), then its mtime is set to `mtime_ns`."""
    paths = _paths(root, "2026-03")
    paths.partition_dir.mkdir(parents=True, exist_ok=True)
    f = paths.partition_dir / "part-0000.parquet"
    table = _hourly(values, E - len(values) * H)
    pq.write_table(table, f, compression="none", use_dictionary=False)
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
    os.utime(f, ns=(mtime_ns, mtime_ns))
    return f


@pytest.mark.parametrize(
    ("bars", "mtime_ns"),
    [(12, T0 + 1_000_000_000), (13, T0), (12, T0)],
    ids=["same-size", "same-mtime", "same-size-and-mtime"],
)
async def test_a_rewrite_keeping_part_of_the_files_stamp_is_read(
    tmp_path: Path, bars: int, mtime_ns: int
) -> None:
    """Every part of a file's stamp is in the key: a rewrite that keeps the size is told by its
    mtime, one that keeps the mtime by its size, one that keeps both by its manifest sha256."""
    f = _write_plain(tmp_path, [1.5] * 12, T0)
    size = f.stat().st_size

    def rewrite() -> None:
        _write_plain(tmp_path, [2.5] * bars, mtime_ns)
        stamp = f.stat()
        assert (stamp.st_size == size, stamp.st_mtime_ns) == (bars == 12, mtime_ns)

    await _assert_fresh_after(tmp_path, Range(E - 24 * H, E), rewrite)


def _delete(root: Path, ym: str, name: str) -> None:
    """What compaction and purge do to one part: drop its manifest entry, then the file."""
    paths = _paths(root, ym)
    store = ManifestStore(paths.manifests_dir)
    kept = [e for e in store.read(paths.partition_dir, paths.root) if e.file != name]
    store.write(paths.partition_dir, paths.root, kept)
    (paths.partition_dir / name).unlink()


async def test_a_file_deleted_from_the_window_is_no_longer_read(tmp_path: Path) -> None:
    _write(tmp_path, "2026-03", _hours(E - 24 * H, 12))
    _write(tmp_path, "2026-03", _hours(E - 12 * H, 12), name="part-0001.parquet")
    await _assert_fresh_after(
        tmp_path, Range(E - 24 * H, E), lambda: _delete(tmp_path, "2026-03", "part-0001.parquet")
    )


async def test_a_roll_off_across_the_window_edge_is_read(tmp_path: Path) -> None:
    """The window spans the month edge; roll-off writes the next month's first part, whose
    bars run past the window's end."""
    _write(tmp_path, "2026-03", _hours(E - 12 * H, 12))
    await _assert_fresh_after(
        tmp_path, Range(E - 6 * H, E + 6 * H), lambda: _write(tmp_path, "2026-04", _hours(E, 12))
    )


def _quarantine(root: Path, part: Path) -> None:
    """A scrub, or another read's verification, took the part out (`ManifestStore.quarantine`)."""
    paths = _paths(root, "2026-03")
    ManifestStore(paths.manifests_dir).quarantine(paths.partition_dir, paths.root, part.name)


def _corrupt(root: Path, part: Path) -> None:
    """Its bytes change under its manifest entry, and its mtime moves on."""
    mtime = part.stat().st_mtime_ns + 1_000_000_000
    pq.write_table(_hourly([9.5], E - H), part)
    os.utime(part, ns=(mtime, mtime))


def _vanish(root: Path, part: Path) -> None:
    """The manifest still names the part, but its file is gone."""
    part.unlink()


@pytest.mark.parametrize(
    "damage", [_quarantine, _corrupt, _vanish], ids=["quarantined", "corrupt", "missing"]
)
async def test_a_cached_page_is_never_served_over_a_damaged_part(
    tmp_path: Path, damage: Callable[[Path, Path], None]
) -> None:
    """The manifest and every file's stamp are read before the cache is, so a quarantined part,
    a part whose checksum no longer matches, or a missing one fails the read (a 503)."""
    _write(tmp_path, "2026-03", _hours(E - 24 * H, 12))
    part = _write(tmp_path, "2026-03", _hours(E - 12 * H, 12), name="part-0001.parquet")
    reader = ParquetKlineReader(DatasetRegistry(tmp_path), page_cache_bytes=ON)
    page = await _page(reader, Range(E - 24 * H, E))
    assert await _page(reader, Range(E - 24 * H, E)) is page
    damage(tmp_path, part)
    with pytest.raises(ColdKlineReadError):
        await _page(reader, Range(E - 24 * H, E))
    reader.close()


async def test_a_page_over_a_quarter_of_the_bound_is_never_cached(tmp_path: Path) -> None:
    _write(tmp_path, "2026-03", _hours(E - 24 * H, 24))
    probe = ParquetKlineReader(DatasetRegistry(tmp_path))
    cost = kr._page_cost(await _page(probe, Range(E - 24 * H, E)))
    probe.close()
    for bound, cached in ((4 * cost, True), (4 * cost - 1, False)):
        reader = ParquetKlineReader(DatasetRegistry(tmp_path), page_cache_bytes=bound)
        first = await _page(reader, Range(E - 24 * H, E))
        assert (await _page(reader, Range(E - 24 * H, E)) is first) is cached
        assert reader._pages.held == (cost if cached else 0)
        reader.close()


async def test_the_bound_evicts_the_least_recently_used_page(
    tmp_path: Path, scans: list[int]
) -> None:
    _write(tmp_path, "2026-03", _hours(E - 50 * H, 50))
    a, b, c, d, e = (Range(E - (k + 1) * 10 * H, E - k * 10 * H) for k in range(5))
    probe = ParquetKlineReader(DatasetRegistry(tmp_path))
    (cost,) = {kr._page_cost(await _page(probe, w)) for w in (a, b, c, d, e)}  # equal pages
    probe.close()
    scans.clear()
    reader = ParquetKlineReader(DatasetRegistry(tmp_path), page_cache_bytes=4 * cost)
    evicted, held = _series("evictions_total"), _series("bytes")
    for w in (a, b, c, d, a, e):  # `a` is read again before `e`: `b` is the least recently used
        await _page(reader, w)
    assert len(scans) == 5 and reader._pages.held == 4 * cost
    assert (_series("evictions_total") - evicted, _series("bytes") - held) == (1, 4 * cost)
    await _page(reader, a)
    assert len(scans) == 5
    await _page(reader, b)
    assert len(scans) == 6
    reader.close()


async def test_close_drops_the_pages_and_takes_their_cost_off_the_gauge(
    tmp_path: Path, scans: list[int]
) -> None:
    _write(tmp_path, "2026-03", _hours(E - 24 * H, 24))
    reader = ParquetKlineReader(DatasetRegistry(tmp_path), page_cache_bytes=ON)
    gauge = _series("bytes")
    for window in (Range(E - 24 * H, E - 12 * H), Range(E - 12 * H, E)):
        await _page(reader, window)
    assert _series("bytes") - gauge == reader._pages.held > 0
    reader.close()
    assert (reader._pages.held, len(reader._pages._entries), _series("bytes")) == (0, 0, gauge)
    await _page(reader, Range(E - 12 * H, E))  # read again after `close()`: a miss, scanned
    assert len(scans) == 3
    reader.close()


async def test_concurrent_misses_on_one_key_each_scan_and_the_page_is_held_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "2026-03", [E - H])
    both = threading.Barrier(2, timeout=5)  # each scan waits for the other: no single-flight
    real = kr._read_page

    def gate(*a: Any) -> Any:
        both.wait()
        return real(*a)

    monkeypatch.setattr(kr, "_read_page", gate)
    reader = ParquetKlineReader(DatasetRegistry(tmp_path), page_cache_bytes=ON)
    held = _series("bytes")
    pages = await asyncio.gather(*(_page(reader, Range(E - H, E)) for _ in range(2)))
    assert _view(pages[0]) == _view(pages[1])
    assert reader._pages.held == kr._page_cost(pages[0]) == _series("bytes") - held
    hit = await _page(reader, Range(E - H, E))
    assert any(hit is p for p in pages)  # the first store won
    reader.close()


_WINDOWS = (
    Range(E - 24 * H, E),
    Range(E - 9 * H, E + 9 * H),
    Range(E, E + 24 * H),
    Range(E - 24 * H, E + 24 * H),
)
#: `(op, n)`: read window `n % 4`, or write / delete the part of six-hour slot `n` (one part
#: per slot, slots -4..3 around the edge), so no two parts hold the same `ts`.
_OPS = st.tuples(st.sampled_from(("read", "write", "delete")), st.integers(-4, 3))


async def _interleave(ops: list[tuple[str, int]]) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cached = ParquetKlineReader(DatasetRegistry(root), page_cache_bytes=ON)
        fresh = ParquetKlineReader(DatasetRegistry(root))
        parts: dict[int, str] = {}
        try:
            for step, (op, n) in enumerate(ops):
                ym = "2026-03" if n < 0 else "2026-04"
                if op == "read":
                    window = _WINDOWS[n % len(_WINDOWS)]
                    assert _view(await _page(cached, window)) == _view(await _page(fresh, window))
                elif op == "write":  # an add, or a rewrite in place when the slot has a part
                    name = parts.setdefault(n, f"part-{step:04d}.parquet")
                    table = _hourly([float(step + k) for k in range(6)], E + n * 6 * H)
                    f = _write_table(root, ym, table, name=name)
                    os.utime(f, ns=(10**18 + step, 10**18 + step))  # each write lands later
                elif n in parts:
                    _delete(root, ym, parts.pop(n))
        finally:
            cached.close()
            fresh.close()


@settings(max_examples=30, deadline=None)
@given(st.lists(_OPS, min_size=1, max_size=12))
@example([("write", -1), ("write", 0), ("read", 1), ("read", 1), ("write", 0), ("read", 1),
          ("delete", -1), ("read", 3), ("read", 1)])  # fmt: skip
def test_an_interleaving_of_writes_and_reads_never_serves_a_stale_page(
    ops: list[tuple[str, int]],
) -> None:
    asyncio.run(_interleave(ops))


def _settings(**kw: int) -> Settings:
    """No `.env` is read."""
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg, arg-type]  # pydantic-settings kwarg


def test_the_bound_setting_defaults_to_64_mib_and_zero_turns_the_cache_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _settings().cold_kline_page_cache_bytes == 64 * 1024 * 1024
    monkeypatch.setenv("CV_COLD_KLINE_PAGE_CACHE_BYTES", "0")
    assert _settings().cold_kline_page_cache_bytes == 0
    with pytest.raises(ValidationError):
        _settings(cold_kline_page_cache_bytes=-1)


def test_the_bound_setting_refuses_more_than_1_gib() -> None:
    """A typo guard, as `CV_REPLAY_READAHEAD_BYTES` has: 1 GiB is accepted, a byte more is not."""
    assert _settings(cold_kline_page_cache_bytes=1 << 30).cold_kline_page_cache_bytes == 1 << 30
    with pytest.raises(ValidationError):
        _settings(cold_kline_page_cache_bytes=(1 << 30) + 1)


def test_the_composition_root_hands_the_bound_to_the_cold_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from candleviewer import app as app_module

    seen: list[object] = []

    def spy(*a: Any, **k: Any) -> ParquetKlineReader:
        seen.append(k.get("page_cache_bytes"))
        return ParquetKlineReader(*a, **k)  # the class `app` imports

    monkeypatch.setattr(app_module, "ParquetKlineReader", spy)
    app_module.wire_public_ws(
        app_module.build_app_context(_settings(cold_kline_page_cache_bytes=12_345))
    )
    assert seen == [12_345]
