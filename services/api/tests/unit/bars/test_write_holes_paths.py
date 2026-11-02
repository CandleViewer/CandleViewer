"""#5396: the write path hands every closed bar's terminal outcome to the write-hole ledger: the
writer's (stored, `permanent`, `transient_exhausted`, `shutdown`) and `WriterSink`'s
(`sink_timeout`, `refused`), which re-raises."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path

import pytest

from candleviewer.bars.emit import BarEmission, EmitRouter, WriterSink
from candleviewer.bars.metrics import bars_write_holes_total
from candleviewer.bars.models import Bar, BarSpec, BarUpdate
from candleviewer.bars.write_holes import WriteHoleLedger
from candleviewer.bars.writer import MAX_ATTEMPTS, BarBufferFull, BarWriter
from tests.unit.bars.test_bars_persistence import SPEC, _bar, _SlowSink

T0 = 1_700_000_000_000_000
W = 300_000_000  # SPEC's 5 minutes, µs


def _bars(*indexes: int) -> list[Bar]:
    return [_bar(index=i, open_time=T0 + i * W, close_time=T0 + (i + 1) * W - 1) for i in indexes]


def _metric(reason: str) -> float:
    value: float = bars_write_holes_total.labels(reason=reason)._value.get()
    return value


def _spans(ledger: WriteHoleLedger) -> list[tuple[int, int]]:
    return ledger.holes_for("BTCUSDT", SPEC.spec_hash, 0, 2**62, [])


async def _no_sleep(_: float) -> None:
    return None


class _Failing:
    """Raises `exc` on every write until `heal()`, then stores."""

    def __init__(self, exc: Exception) -> None:
        self.exc: Exception | None = exc
        self.calls = 0
        self.rows: list[dict[str, object]] = []

    async def write_rows(self, t: str, rows: list[dict[str, object]], k: str) -> None:
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        self.rows.extend(rows)


@pytest.mark.asyncio
async def test_writer_permanent_failure_records_one_hole(tmp_path: Path) -> None:
    ledger = WriteHoleLedger(tmp_path)
    before = _metric("permanent")
    w = BarWriter(_Failing(ValueError("bad row")), sleep=_no_sleep, holes=ledger)
    await w.start()
    await w.submit(_bars(1), SPEC, generation=7)
    assert await w.stop() == 0
    (rec,) = ledger.pending()
    assert (rec.reason, rec.generation, rec.first_index, rec.count) == ("permanent", 7, 1, 1)
    assert _spans(ledger) == [(T0 + W, T0 + 2 * W)]
    assert _metric("permanent") == before + 1


@pytest.mark.asyncio
async def test_writer_exhausted_retries_record_one_hole_and_count_one(tmp_path: Path) -> None:
    ledger = WriteHoleLedger(tmp_path)
    before = _metric("transient_exhausted")
    sink = _Failing(ConnectionError("down"))
    w = BarWriter(sink, sleep=_no_sleep, holes=ledger)
    await w.start()
    await w.submit(_bars(2), SPEC, generation=7)
    await w.stop()
    assert sink.calls == MAX_ATTEMPTS  # one record for every attempt of the batch
    assert [(r.reason, r.count) for r in ledger.pending()] == [("transient_exhausted", 1)]
    assert _metric("transient_exhausted") == before + 1


@pytest.mark.asyncio
async def test_writer_stop_with_queued_rows_records_shutdown_holes(tmp_path: Path) -> None:
    ledger = WriteHoleLedger(tmp_path)
    before = _metric("shutdown")
    w = BarWriter(_SlowSink(), batch_rows=1, holes=ledger)  # never released
    await w.start()
    await w.submit(_bars(0, 1, 2), SPEC, generation=7)
    assert await w.stop(timeout_s=0.01) == 3  # one in flight, two queued
    assert [(r.first_index, r.last_index, r.reason) for r in ledger.pending()] == [
        (0, 2, "shutdown")
    ]
    assert _metric("shutdown") == before + 3 and w.depth == 0


@pytest.mark.asyncio
async def test_writer_later_success_clears_the_hole(tmp_path: Path) -> None:
    ledger = WriteHoleLedger(tmp_path)
    sink = _Failing(ValueError("bad row"))
    w = BarWriter(sink, sleep=_no_sleep, holes=ledger)
    await w.start()
    await w.submit(_bars(1, 2), SPEC, generation=7)
    await w.stop()
    assert _spans(ledger) == [(T0 + W, T0 + 3 * W)]
    sink.exc = None
    await w.start()
    await w.submit(_bars(1), SPEC, generation=7)  # e.g. an amended close of bar 1
    await w.stop()
    assert _spans(ledger) == [(T0 + 2 * W, T0 + 3 * W)]


@pytest.mark.asyncio
async def test_writer_success_without_a_ledger_still_stores(tmp_path: Path) -> None:
    sink = _Failing(ValueError("x"))
    sink.exc = None
    w = BarWriter(sink)
    await w.start()
    await w.submit(_bars(1), SPEC, generation=7)
    assert await w.stop() == 0 and len(sink.rows) == 1


# -- WriterSink ---------------------------------------------------------------------------------


class _Writer:
    """A `BarSubmitter` that raises `exc`, or hangs when `exc` is None."""

    def __init__(self, exc: BaseException | None) -> None:
        self.exc = exc

    async def submit(
        self, bars: Sequence[Bar], spec: BarSpec, *, source: str = "tape", generation: int
    ) -> None:
        if self.exc is not None:
            raise self.exc
        await asyncio.Event().wait()


def _closes(*indexes: int) -> list[BarUpdate]:
    return [BarUpdate(kind="close", bar=b) for b in _bars(*indexes)]


@pytest.mark.asyncio
async def test_writer_sink_router_timeout_records_sink_timeout_holes(tmp_path: Path) -> None:
    ledger = WriteHoleLedger(tmp_path)
    before = _metric("sink_timeout")
    router = EmitRouter([WriterSink(_Writer(None), holes=ledger)], timeout_s=0)
    await router.emit(SPEC, _closes(4, 5), 7)  # the router absorbs its own timeout
    assert router.timed_out
    assert [(r.first_index, r.last_index, r.reason) for r in ledger.pending()] == [
        (4, 5, "sink_timeout")
    ]
    assert _metric("sink_timeout") == before + 2


@pytest.mark.asyncio
async def test_writer_sink_cancellation_is_recorded_and_re_raised(tmp_path: Path) -> None:
    ledger = WriteHoleLedger(tmp_path)
    sink = WriterSink(_Writer(asyncio.CancelledError()), holes=ledger)
    with pytest.raises(asyncio.CancelledError):
        await sink.emit(BarEmission(SPEC, 7, _closes(1)))
    assert [r.reason for r in ledger.pending()] == ["sink_timeout"]


@pytest.mark.asyncio
async def test_writer_sink_refusal_is_recorded_and_re_raised(tmp_path: Path) -> None:
    ledger = WriteHoleLedger(tmp_path)
    before = _metric("refused")
    sink = WriterSink(_Writer(BarBufferFull("full")), holes=ledger)
    with pytest.raises(BarBufferFull):
        await sink.emit(BarEmission(SPEC, 7, _closes(1)))
    assert [r.reason for r in ledger.pending()] == ["refused"]
    assert _metric("refused") == before + 1


@pytest.mark.asyncio
async def test_writer_sink_forming_bars_and_no_ledger_record_nothing(tmp_path: Path) -> None:
    ledger = WriteHoleLedger(tmp_path)
    (bar,) = _bars(1)
    forming = BarUpdate(kind="update", bar=bar.model_copy(update={"closed": False}))
    await WriterSink(_Writer(BarBufferFull("full")), holes=ledger).emit(
        BarEmission(SPEC, 7, [forming])
    )
    with pytest.raises(BarBufferFull):
        await WriterSink(_Writer(BarBufferFull("full"))).emit(BarEmission(SPEC, 7, _closes(1)))
    assert ledger.pending() == []
