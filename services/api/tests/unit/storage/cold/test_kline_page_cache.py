"""#2523 lever 5: `ParquetKlineReader.page`'s byte-bounded LRU of cold pages.

A page is cached under `(symbol, interval, lo_us, hi_us, max_rows)` plus the sorted
`(path, size, mtime_ns)` of every Parquet file the read resolved. Roll-off, import, compaction
and purge each add, rewrite or delete a file, so each is a new key: one test per path here and a
hypothesis interleaving of writes and reads against a reader with no cache. Also pinned: the
bound (`CV_COLD_KLINE_PAGE_CACHE_BYTES`, 0 = off), an entry's cost, the quarter-bound rule, LRU
eviction, a hit taking no DuckDB slot, and no single-flight. The route golden, a miss then a hit,
is `tests/unit/api/test_market_response_columnar.py`.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st
from prometheus_client import REGISTRY
from pydantic import ValidationError

from candleviewer.ingestion.kline_coverage import Range
from candleviewer.settings import Settings
from candleviewer.storage.cold import kline_reader as kr
from candleviewer.storage.cold.kline_reader import ColdKlinePage, ParquetKlineReader
from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.cold.manifest import ManifestStore
from candleviewer.storage.models import StreamKind
from tests.unit.storage.cold.test_kline_page import _table
from tests.unit.storage.cold.test_kline_reader import MIN, H, _us, _write, _write_table

E = _us(2026, 4)  # a month edge: partition 2026-03 holds the hours before it, 2026-04 the rest
ON = 1 << 20


def _series(name: str) -> float:
    return REGISTRY.get_sample_value(f"cv_cold_kline_page_cache_{name}") or 0.0


def _view(got: object) -> object:
    """What a route serves from a cold read: a page's bar JSON and rows; anything else as is."""
    return (got.bars_json(b""), got.rows()) if isinstance(got, ColdKlinePage) else got


async def _page(reader: ParquetKlineReader, window: Range) -> Any:
    return await reader.page("BTCUSDT", "60", window)


def _hours(lo: int, n: int) -> list[int]:
    return [lo + k * H for k in range(n)]


def _hourly(values: list[float], lo: int) -> pa.Table:
    """`_table`'s bars (each price column a rotation of `values`), one an hour from `lo`."""
    return _table(values, lo).set_column(
        0, "ts", pa.array(_hours(lo, len(values)), pa.timestamp("us", tz="UTC"))
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


@pytest.mark.parametrize("bound", [{}, {"page_cache_bytes": 0}], ids=["default", "zero"])
async def test_the_reader_default_and_a_zero_bound_cache_nothing(
    tmp_path: Path, scans: list[int], bound: dict[str, int]
) -> None:
    _write(tmp_path, "2026-03", [E - H])
    reader = ParquetKlineReader(DatasetRegistry(tmp_path), **bound)
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


@pytest.mark.parametrize("bars", [0, 1, 7])
async def test_an_entry_costs_its_table_plus_its_bar_json(tmp_path: Path, bars: int) -> None:
    _write_table(tmp_path, "2026-03", _table([1.5, 1e-07, None, 2.25, 3.0, 4.5, 6.0], E - H))
    reader = ParquetKlineReader(DatasetRegistry(tmp_path))
    page = await _page(reader, Range(E - H + (7 - bars) * MIN, E))  # the newest `bars` bars
    assert isinstance(page, ColdKlinePage) and len(page) == bars
    assert kr._page_cost(page) == page.table.nbytes + len(page.bars_json(b""))
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
    """The rewrite lands later, as a write does (its mtime moves on); a rewrite that keeps both
    size and `mtime_ns` is the design note's one blind spot."""
    f = _write(tmp_path, "2026-03", _hours(E - 12 * H, 12))

    def rewrite() -> None:
        mtime = f.stat().st_mtime_ns + 1_000_000_000
        _write_table(tmp_path, "2026-03", _hourly([7.5] * 12, E - 12 * H))
        os.utime(f, ns=(mtime, mtime))

    await _assert_fresh_after(tmp_path, Range(E - 24 * H, E), rewrite)


def _delete(root: Path, ym: str, name: str) -> None:
    """What compaction and purge do to one part: drop its manifest entry, then the file."""
    paths = DatasetRegistry(root).resolve_partition(
        StreamKind.KLINES, partition_values={"symbol": "BTCUSDT", "interval": "60", "ym": ym}
    )
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
    """No `.env` is read: `_env_file` is a pydantic-settings keyword its stubs do not declare."""
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]


def test_the_bound_setting_defaults_to_64_mib_and_zero_turns_the_cache_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _settings().cold_kline_page_cache_bytes == 64 * 1024 * 1024
    monkeypatch.setenv("CV_COLD_KLINE_PAGE_CACHE_BYTES", "0")
    assert _settings().cold_kline_page_cache_bytes == 0
    with pytest.raises(ValidationError):
        _settings(cold_kline_page_cache_bytes=-1)


def test_the_composition_root_hands_the_bound_to_the_cold_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from candleviewer import app as app_module

    seen: list[object] = []
    real = app_module.ParquetKlineReader

    def spy(*a: Any, **k: Any) -> ParquetKlineReader:
        seen.append(k.get("page_cache_bytes"))
        return real(*a, **k)

    monkeypatch.setattr(app_module, "ParquetKlineReader", spy)
    app_module.wire_public_ws(
        app_module.build_app_context(_settings(cold_kline_page_cache_bytes=12_345))
    )
    assert seen == [12_345]
