"""E12 bars detection signals (#2294, E12-X01 QA): one test per signal of the threat model's
section 10 that #2294 owns, each driving its BR row's threat path and asserting the series moved.

* BR-10 `bars_stale_build_version_total` (shipped by #1998): a range read of old rows.
* BR-11 `bars_print_rejected_total{reason}`: a print over the SR-E12-15 cap.
* BR-13 `ws_bars_seq_gap_total`: a client-reported gap on a bars topic.
* BR-14 `bars_write_roundtrip_mismatch_total`: a price a DOUBLE cannot hold.
* BR-15 `bars_spec_registry_conflict_total`: two specs on one `spec_hash`.
* BR-16 `parquet_hot_cold_parity_mismatch_total{stream}`: an archive unlike its hot rows.
* BR-34 `bars_write_queue_depth`, `bars_write_saturation_total` (#1998): a stalled sink.
* BR-36 `bars_cold_read_duplicate_inflight_total`: two identical cold reads at once.
* BR-37 `bars_snapshot_write_seconds`, `bars_snapshot_bytes_total`: state blobs written.
* BR-38 `bars_subscribe_snapshot_total{history}`: bars snapshots built, per history bucket.
"""

from __future__ import annotations

import asyncio
import threading
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from prometheus_client import REGISTRY

from candleviewer.bars import spec as spec_module
from candleviewer.bars.activity_builders import VolumeBarBuilder
from candleviewer.bars.errors import BarsError
from candleviewer.bars.models import BarSpec, BuilderState
from candleviewer.bars.reader import BarReader
from candleviewer.bars.renko_builder import RenkoBarBuilder
from candleviewer.bars.rows import bar_row, row_checksum
from candleviewer.bars.spec import SpecRegistry
from candleviewer.bars.state_store import StateStore, StoredState
from candleviewer.bars.writer import BarWriter
from candleviewer.ingestion.kline_coverage import Range
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.storage.cold import kline_reader as kr
from candleviewer.storage.cold.kline_reader import ParquetKlineReader
from candleviewer.storage.cold.layout import DatasetRegistry
from tests.unit.bars._trades import SYM, trade
from tests.unit.bars.test_bars_persistence import SPEC, _bar, _Conn, _settle, _SlowSink
from tests.unit.storage.cold._helpers import FakeHotSource, RecordingSink, day_range, trades_table
from tests.unit.storage.cold.test_kline_page_cache import ON, E, _page
from tests.unit.storage.cold.test_kline_reader import H, _write
from tests.unit.storage.cold.test_rolloff_ops import T, TamperingSource, _archiver
from tests.unit.ws._seq_support import Conn
from tests.unit.ws.test_bars_source import _src, _store, _sub
from tests.unit.ws.test_sequencing import _book_source, _hub_bars, _resync

T0 = 1_700_000_000_000_000


def _value(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


async def _no_rebuild(symbol: str, spec_hash: str, lo: int, hi: int) -> None:
    return None


async def test_br10_a_read_of_rows_below_the_build_version_counts_stale() -> None:
    """BR-10: rows an older builder wrote are served as-is and counted; current rows are not."""
    old = bar_row(_bar(), SPEC, generation=0)
    old["build_version"] = 0
    old["row_checksum"] = row_checksum(old)
    fresh = bar_row(_bar(), SPEC, generation=0)
    before = _value("bars_stale_build_version_total")
    page = await BarReader(_Conn([old]), _no_rebuild).read_bars("BTCUSDT", SPEC, 0, 2**55, 10)
    assert page.stale
    assert _value("bars_stale_build_version_total") == before + 1
    await BarReader(_Conn([fresh]), _no_rebuild).read_bars("BTCUSDT", SPEC, 0, 2**55, 10)
    assert _value("bars_stale_build_version_total") == before + 1


def test_br11_a_print_over_the_bar_cap_counts_rejected_by_cap() -> None:
    """BR-11 (SR-E12-15): a pathological print that would close over 1 000 volume bars, or
    complete over 1 000 renko bricks, is refused and counted under its cap."""
    volume = VolumeBarBuilder(BarSpec(kind="volume", volume_threshold=Decimal(1)), SYM)
    renko = RenkoBarBuilder(
        BarSpec(kind="renko", range_ticks=10), SYM, lambda _: Decimal("0.10")
    )  # a brick of 1.0
    before = {r: _value("bars_print_rejected_total", reason=r) for r in ("volume", "renko")}
    with pytest.raises(BarsError, match="would close 1001 volume bars"):
        volume.on_trade(trade(T0, qty="1001", seq=1))
    renko.on_trade(trade(T0, px="100", seq=1))
    with pytest.raises(BarsError, match="would complete 1900 renko bricks"):
        renko.on_trade(trade(T0 + 1, px="2000", seq=2))
    assert _value("bars_print_rejected_total", reason="volume") == before["volume"] + 1
    assert _value("bars_print_rejected_total", reason="renko") == before["renko"] + 1
    volume.on_trade(trade(T0 + 2, qty="1000", seq=2))  # exactly the cap: emitted, not counted
    assert _value("bars_print_rejected_total", reason="volume") == before["volume"] + 1


def test_br13_a_client_sequence_gap_on_a_bars_topic_counts_and_a_book_one_does_not() -> None:
    """BR-13: a client that finds a hole in a `bars` topic's sequence numbers resyncs with
    `sequence_gap`; that is the only signal of a reordered or tampered frame, so it is counted
    for the bars family alone (every family's is in `cv_ws_sequence_gaps_detected_total`)."""
    _, conn, sub = _hub_bars()
    before = _value("ws_bars_seq_gap_total")
    _resync(conn, sub.ch, last_seq=1)
    assert _value("ws_bars_seq_gap_total") == before + 1
    book = Conn(_book_source())
    _, book_sub = book.sub("book.BTCUSDT.50")
    _resync(book, book_sub.ch, last_seq=1)
    assert _value("ws_bars_seq_gap_total") == before + 1


def test_br14_a_price_a_double_cannot_hold_counts_a_roundtrip_mismatch() -> None:
    """BR-14: a price with more digits than a binary64 holds reads back as another price; the
    storage boundary counts it. A price the double holds exactly is not counted."""
    before = _value("bars_write_roundtrip_mismatch_total")
    bar_row(_bar(), SPEC, generation=0)
    assert _value("bars_write_roundtrip_mismatch_total") == before
    lossy = Decimal("100.12345678901234567")
    bar_row(_bar(close=lossy, high=Decimal(101)), SPEC, generation=0)
    assert _value("bars_write_roundtrip_mismatch_total") == before + 1


def test_br15_two_specs_on_one_hash_count_a_conflict_and_keep_the_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BR-15: a `spec_hash` collision (forced here: sha256 has none to find) never replaces the
    registered spec; the insert-only registry counts the conflict."""
    monkeypatch.setattr(spec_module, "compute_spec_hash", lambda _: "a" * 64)
    first, other = BarSpec(kind="tick", tick_count=11), BarSpec(kind="tick", tick_count=12)
    reg = SpecRegistry()
    before = _value("bars_spec_registry_conflict_total")
    reg.register(first)
    reg.register(BarSpec(kind="tick", tick_count=11))  # the same spec again: no conflict
    assert _value("bars_spec_registry_conflict_total") == before
    reg.register(other)
    assert _value("bars_spec_registry_conflict_total") == before + 1
    assert reg.resolve("a" * 64) == first


async def test_br16_an_archive_unlike_its_hot_rows_counts_a_parity_mismatch(
    tmp_path: Path,
) -> None:
    """BR-16: the roll-off read-back finds the Parquet file unlike the QuestDB rows, by content
    (checksum) or by count (the export's own verify); each counts once under its stream."""
    before = _value("parquet_hot_cold_parity_mismatch_total", stream="trades")
    out = await _archiver(
        tmp_path / "a", TamperingSource(trades_table(50)), RecordingSink()
    ).archive_day("BTCUSDT", T, day_range())
    assert not out.verified
    assert _value("parquet_hot_cold_parity_mismatch_total", stream="trades") == before + 1
    short = FakeHotSource(trades_table(50), count_override=51)
    out = await _archiver(tmp_path / "b", short, RecordingSink()).archive_day(
        "BTCUSDT", T, day_range()
    )
    assert not out.verified
    assert _value("parquet_hot_cold_parity_mismatch_total", stream="trades") == before + 2
    good = await _archiver(
        tmp_path / "c", FakeHotSource(trades_table(50)), RecordingSink()
    ).archive_day("BTCUSDT", T, day_range())
    assert good.verified
    assert _value("parquet_hot_cold_parity_mismatch_total", stream="trades") == before + 2


async def test_br34_a_stalled_sink_shows_in_the_buffer_gauge_and_drops_nothing() -> None:
    """BR-34: with the sink stalled, the depth gauge reads the full buffer while producers wait
    (not the value of the last finished batch), each row that found it full is counted, and
    nothing is dropped."""
    sink = _SlowSink()
    w = BarWriter(sink, max_buffered=3, batch_rows=1)
    await w.start()
    failed = sum(
        _value("bars_write_failed_total", reason=r) for r in ("permanent", "transient_exhausted")
    )
    saturated = _value("bars_write_saturation_total")
    bars = [_bar(index=i, open_time=T0 + i) for i in range(12)]
    producer = asyncio.create_task(w.submit(bars, SPEC, generation=0))
    await sink.entered.wait()
    await _settle()
    assert not producer.done()
    assert _value("bars_write_queue_depth") == w.depth == 3
    assert _value("bars_write_saturation_total") > saturated
    sink.gate.set()
    await producer
    assert await w.stop() == 0
    assert len(sink.rows) == 12 and _value("bars_write_queue_depth") == 0
    assert failed == sum(
        _value("bars_write_failed_total", reason=r) for r in ("permanent", "transient_exhausted")
    )


async def test_br36_two_identical_cold_reads_in_flight_count_one_duplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BR-36: no single-flight joins identical cold reads yet, so the second of two identical
    reads in flight together scans again; it is counted. A later read, a cache hit, is not."""
    _write(tmp_path, "2026-03", [E - H])
    both = threading.Barrier(2, timeout=5)  # each scan waits for the other: both in flight
    real = kr._read_page

    def gate(*a: Any) -> Any:
        both.wait()
        return real(*a)

    monkeypatch.setattr(kr, "_read_page", gate)
    reader = ParquetKlineReader(DatasetRegistry(tmp_path), page_cache_bytes=ON)
    before = _value("bars_cold_read_duplicate_inflight_total")
    try:
        await asyncio.gather(*(_page(reader, Range(E - H, E)) for _ in range(2)))
        assert _value("bars_cold_read_duplicate_inflight_total") == before + 1
        await _page(reader, Range(E - H, E))
        assert _value("bars_cold_read_duplicate_inflight_total") == before + 1
    finally:
        reader.close()


async def test_br37_each_state_blob_write_counts_its_bytes_and_its_time(tmp_path: Path) -> None:
    """BR-37: the write amplification of the 60 s snapshots shows as bytes written and the
    seconds of each atomic write (fsync included)."""
    store = StateStore(tmp_path)
    blob = BuilderState(
        spec_hash=SPEC.spec_hash, symbol="BTCUSDT", state_version=1, last_trade_seq=9,
        blob=b'{"k":"' + b"x" * 2048 + b'"}',
    )  # fmt: skip
    written = _value("bars_snapshot_bytes_total")
    writes = _value("bars_snapshot_write_seconds_count")
    for _ in range(3):
        await store.save(StoredState(blob, None, 4))
    size = store.path("BTCUSDT", SPEC.spec_hash).stat().st_size
    assert _value("bars_snapshot_bytes_total") == written + 3 * size
    assert _value("bars_snapshot_write_seconds_count") == writes + 3


@pytest.mark.parametrize(
    ("history", "bucket"),
    [(0, "0"), (1, "1-100"), (100, "1-100"), (101, "101-500"), (500, "101-500"),
     (501, "501-1000"), (1000, "501-1000")],
)  # fmt: skip
async def test_br38_a_bars_snapshot_built_counts_under_its_history_bucket(
    history: int, bucket: str
) -> None:
    """BR-38: every bars snapshot built (a subscribe's first, a resync's, a repair's) counts
    under the bucket of the `history` it asked for, so snapshot storms show by depth."""
    from candleviewer.bars.metrics import HISTORY_BUCKETS

    assert bucket in HISTORY_BUCKETS
    src = _src(await _store(3))
    before = _value("bars_subscribe_snapshot_total", history=bucket)
    for _ in range(2):
        assert src.build(_sub(encoding="structured", history=history)) is not None
    assert _value("bars_subscribe_snapshot_total", history=bucket) == before + 2


#: The series #2294 declares, each served from a module-level collector in the default registry.
_SIGNALS_2294 = (
    "bars_print_rejected_total",
    "bars_write_roundtrip_mismatch_total",
    "bars_spec_registry_conflict_total",
    "bars_snapshot_bytes_total",
    "bars_snapshot_write_seconds",
    "bars_subscribe_snapshot_total",
    "ws_bars_seq_gap_total",
    "bars_cold_read_duplicate_inflight_total",
    "parquet_hot_cold_parity_mismatch_total",
)


@pytest.mark.parametrize("name", _SIGNALS_2294)
def test_detection_signal_serves_the_catalogue_help_word_for_word(name: str) -> None:
    """#2294 review L3: the HELP a scrape serves for each new signal is its catalogue help, so the
    sentence an operator reads on a dashboard is the one the catalogue reviews."""
    (spec,) = [s for s in CATALOGUE if s.name == name]
    family = name.removesuffix("_total")
    (served,) = [f.documentation for f in REGISTRY.collect() if f.name == family]
    assert served == spec.help, f"{name}: served {served!r} != catalogue {spec.help!r}"
