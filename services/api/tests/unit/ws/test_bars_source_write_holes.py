"""#5396 (23 §13 `snapMeta.coverage_holes`, 24 §19.81): a `bars` snapshot names the closed bars the
server did not store, from its oldest bar on and not among the bars it sends, in either encoding
and on every chunk; the render cache refreshes when the series' holes change."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import orjson
import pytest

from candleviewer.bars.emit import BarEmission
from candleviewer.bars.limits import MAX_COVERAGE_HOLES_WS
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.reader import BarTail
from candleviewer.bars.rows import tape_row_checksum
from candleviewer.bars.series_store import SeriesStore
from candleviewer.bars.write_holes import HoleKey, WriteHoleLedger
from candleviewer.ws.bars_source import BarsSnapshotSource
from candleviewer.ws.sequencing import OWNER_META_MAX_BYTES, SnapshotBody, TopicEmitter
from tests.unit.ws._seq_support import validate
from tests.unit.ws.test_bars_source import CH, GEN, SPEC, STEP, SYM, T0, H, _bar, _build, _sub, _up

#: A price no other bar here has: the amended version of a bar, whose write was lost.
AMENDED = "200.25"


def _key(i: int, gen: int = GEN, *, version: Bar | None = None) -> HoleKey:
    """Bar `i`'s key; `version`: the bar whose write was lost (its checksum), else unknown."""
    checksum = None if version is None else tape_row_checksum(version, SPEC, gen)
    return HoleKey(SYM, H, "time", "5m", gen, i, T0 + i * STEP, T0 + (i + 1) * STEP, checksum)


async def _store(*closed: int, forming: int | None = None) -> SeriesStore:
    """A held series: the closed bars `closed` (a stored tail may miss some), a forming bar."""
    store = SeriesStore()
    await store.ensure(SYM, SPEC)
    ups = [_up("close", i) for i in closed] + (
        [_up("open", forming)] if forming is not None else []
    )
    await store.emit(BarEmission(SPEC, GEN, ups))
    return store


async def _reloaded(tmp_path: Path, *lost: int, amended: bool = False) -> WriteHoleLedger:
    """A ledger read back from the journal an earlier process wrote; `amended`: the losses are
    of each bar's amended version (`AMENDED`, a known checksum), else of an unknown one."""
    earlier = WriteHoleLedger(tmp_path)
    earlier.lost([_key(i, version=_bar(i, px=AMENDED) if amended else None) for i in lost],
                 "shutdown")  # fmt: skip
    await earlier.flush()
    ledger = WriteHoleLedger(tmp_path)
    assert await ledger.load() == "ok"
    return ledger


def _src(store: SeriesStore, ledger: WriteHoleLedger | None) -> BarsSnapshotSource:
    return BarsSnapshotSource(store, lambda s: (1, 3), holes=ledger)


def _hole(i: int) -> dict[str, int]:
    return {"start_us": T0 + i * STEP, "end_us": T0 + (i + 1) * STEP}


@pytest.mark.parametrize("encoding", ["structured", "binary"])
async def test_after_a_reload_the_snapshot_names_the_hole_in_either_encoding(
    tmp_path: Path, encoding: str
) -> None:
    src = _src(await _store(0, 2, 3, forming=4), await _reloaded(tmp_path, 1))
    out: list[dict[str, Any]] = []
    emitter = TopicEmitter(
        out.append, connection_id="c", wall_ms=lambda: 1, clock=lambda: 0.0, source=src
    )
    assert emitter.snapshot(_sub(encoding=encoding), "initial")
    (frame,) = out
    validate(frame)  # 23 §13 `snapMeta`
    assert frame["meta"]["coverage_holes"] == [_hole(1)]


async def test_every_chunk_of_a_chunked_snapshot_carries_the_holes(tmp_path: Path) -> None:
    src = _src(await _store(*range(0, 40), *range(41, 60), forming=60),
               await _reloaded(tmp_path, 40))  # fmt: skip
    out: list[dict[str, Any]] = []
    emitter = TopicEmitter(
        out.append, connection_id="c", wall_ms=lambda: 1, clock=lambda: 0.0, source=src,
        max_frame_bytes=4_000,
    )  # fmt: skip
    assert emitter.snapshot(_sub(encoding="structured", history=100), "initial")
    assert len(out) > 1
    for frame in out:
        validate(frame)
        assert frame["meta"]["coverage_holes"] == [_hole(40)]


async def test_a_held_bar_of_an_unknown_lost_version_suppresses_nothing(tmp_path: Path) -> None:
    ledger = await _reloaded(tmp_path, 1)  # the version lost is unknown: nothing can prove it
    body = _build(_src(await _store(0, 1, 2, forming=3), ledger), _sub())
    assert body.meta["coverage_holes"] == [_hole(1)]
    body = _build(_src(await _store(0, 1, 2, forming=3), None), _sub())
    assert "coverage_holes" not in body.meta  # no ledger: no key


async def test_a_delivered_bar_that_is_the_lost_version_suppresses_its_hole(
    tmp_path: Path,
) -> None:
    ledger = await _reloaded(tmp_path, 1, amended=True)
    store = SeriesStore()
    await store.ensure(SYM, SPEC)
    ups = [_up("close", 0), _up("close", 1, px=AMENDED), _up("close", 2), _up("open", 3)]
    await store.emit(BarEmission(SPEC, GEN, ups))  # the sink delivered the amend the write lost
    assert "coverage_holes" not in _build(_src(store, ledger), _sub()).meta


async def test_a_delivered_bar_of_another_version_keeps_the_hole(tmp_path: Path) -> None:
    ledger = await _reloaded(tmp_path, 1, amended=True)
    store = await _store(0, 1, 2, forming=3)  # bar 1 as first closed, not the amend lost
    assert _build(_src(store, ledger), _sub()).meta["coverage_holes"] == [_hole(1)]


class _Tail:
    """`TailRead` fake: the stored rows, as `BarsReader.read_tail` hands them to the store."""

    def __init__(self, bars: list[Bar]) -> None:
        self._bars = bars

    async def __call__(self, symbol: str, spec: BarSpec, limit: int) -> BarTail:
        return BarTail([(GEN, b) for b in self._bars])


async def test_a_hydrated_earlier_version_never_hides_a_lost_amend(tmp_path: Path) -> None:
    """C-13.2 regression (#5432 review): after a restart the store hydrates bar 1 from its stored
    row, the version before the amend whose write was lost; the journal kept that loss, so the
    snapshot names it as REST does."""
    ledger = await _reloaded(tmp_path, 1, amended=True)
    store = SeriesStore(_Tail([_bar(0), _bar(1), _bar(2)]))
    await store.ensure(SYM, SPEC)
    latest = store.latest(SYM, H, 10)
    assert latest is not None and [b.index for b in latest.closed] == [0, 1, 2]
    assert _build(_src(store, ledger), _sub()).meta["coverage_holes"] == [_hole(1)]


async def test_only_holes_from_the_oldest_bar_sent_on_are_named(tmp_path: Path) -> None:
    ledger = await _reloaded(tmp_path, 1, 5)
    src = _src(await _store(0, 2, 3, 4, 6, forming=7), ledger)
    assert _build(src, _sub(history=5)).meta["coverage_holes"] == [_hole(5)]  # bars 3..7
    assert _build(src, _sub()).meta["coverage_holes"] == [_hole(1), _hole(5)]
    assert "coverage_holes" not in _build(src, _sub(history=0)).meta  # no bar: no span


async def test_a_new_hole_refreshes_the_render_cache_and_stale_still_negates(
    tmp_path: Path,
) -> None:
    ledger = WriteHoleLedger(tmp_path)
    store = await _store(0, 2, forming=3)
    src, sub = _src(store, ledger), _sub()
    before = src.generation(sub)
    assert before == store.version(SYM, H)  # no hole ever: the store's version alone
    ledger.lost([_key(1)], "refused")
    after = src.generation(sub)
    assert after != before and after > 0
    stale = BarsSnapshotSource(store, lambda s: (1, 3), holes=ledger, stale=lambda *_: True)
    assert stale.generation(sub) == -after
    await ledger.flush()


async def test_the_list_is_capped_and_fits_the_snapshot_meta_bound(tmp_path: Path) -> None:
    ledger = WriteHoleLedger(tmp_path)
    big = 2**61  # 19 digits: the widest value a hole can carry
    lost = [HoleKey(SYM, H, "time", "5m", GEN, 2 * i, big + 2 * i * STEP, big + (2 * i + 1) * STEP)
            for i in range(MAX_COVERAGE_HOLES_WS + 8)]  # fmt: skip
    ledger.lost(lost, "refused")
    store = SeriesStore()
    await store.ensure(SYM, SPEC)
    oldest = _up("close", 0).bar.model_copy(update={"open_time": big - STEP, "close_time": big - 1})
    await store.emit(BarEmission(SPEC, GEN, [_up("close", 0).model_copy(update={"bar": oldest})]))
    body: SnapshotBody = _build(_src(store, ledger), _sub(ch=CH))  # the guard did not refuse it
    holes = body.meta["coverage_holes"]
    assert len(holes) == MAX_COVERAGE_HOLES_WS
    assert holes[0]["start_us"] == big and holes[-1]["end_us"] == lost[-1].end_us
    assert len(orjson.dumps(dict(body.meta))) <= OWNER_META_MAX_BYTES
    await ledger.flush()
