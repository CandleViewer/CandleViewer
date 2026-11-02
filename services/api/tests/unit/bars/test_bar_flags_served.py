"""#5396 PR B (24 §19.81, 21 §4.8): the bar flags reach the store and both wires, the row checksum
covers them from 0008, and REST names the build provenance of the bars it serves.

`gap_before` is a discontinuity (a quiet interval), `tape_gap` the recorded-tape data-loss marker
(ruling 2 on #5396). Each surface carries the value the builder set: the stored row, a range read,
a tail read, the REST bar, the WS item and its kind-4 twin.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.api.market_response import bars_provenance, serialize_bar
from candleviewer.bars.kline_rows import KLINE_SOURCE, kline_row
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.reader import BarReader, StoredBar, stored_bar
from candleviewer.bars.rows import (
    _CHECKSUM_FIELDS,
    BUILD_VERSIONS,
    FLAG_COLUMNS,
    bar_row,
    row_checksum,
)
from candleviewer.bars.time_builder import TimeBarBuilder
from candleviewer.exchange.base.models import KlineEvent
from candleviewer.ws.bars_wire import bar_item, bars_frames, covering_scales, item_bar
from candleviewer.ws.binary import decode, encode
from candleviewer.ws.cvwb_vectors import structured
from tests.unit.bars._trades import SYM, closes, trade, us

SPEC = BarSpec(kind="time", interval_ms=60_000)
GEN = 7
T0 = us("10:00:00")
MIN = 60_000_000
FLAGS = ("gap_before", "partial", "tape_gap")


def _bar(i: int = 0, **flags: bool) -> Bar:
    t = T0 + i * MIN
    return Bar.model_validate(
        dict(
            spec_hash=SPEC.spec_hash, symbol=SYM, index=i, open_time=t, close_time=t + MIN - 1,
            open=Decimal("100.5"), high=Decimal("101"), low=Decimal("100"),
            close=Decimal("100.25"), volume=Decimal("2"), buy_volume=Decimal("1.5"),
            sell_volume=Decimal("0.5"), delta=Decimal("1"), min_delta=Decimal("-0.25"),
            max_delta=Decimal("1.25"), trade_count=5, turnover=Decimal("201"),
            vwap=Decimal("100.5"), closed=True,
            **{"gap_before": False, "partial": False, **flags},
        )
    )  # fmt: skip


class _Conn:
    """A store that answers every statement with `rows` (the tail's table bound: none)."""

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        return [] if sql.startswith("SELECT ts FROM") else self.rows


async def _no_rebuild(*_args: object) -> None:
    return None


def _reader(rows: list[dict[str, object]]) -> BarReader:
    return BarReader(_Conn(rows), _no_rebuild, now_us=lambda: T0 + 10 * MIN)


def _flags_of(source: object) -> tuple[bool, ...]:
    """`(gap_before, partial, tape_gap)` of a row, an item or a bar: absent reads false."""
    if isinstance(source, dict):
        return tuple(source.get(name) is True for name in FLAGS)
    return tuple(getattr(source, name) is True for name in FLAGS)


async def _surfaces(bar: Bar) -> dict[str, tuple[bool, ...]]:
    """The flags `bar` carries on every surface: stored row, range read + REST bar, tail read,
    WS item, and the kind-4 record decoded by the reference decoder."""
    row = bar_row(bar, SPEC, generation=GEN)
    page = await _reader([row]).read_bars(SYM, SPEC, T0, T0 + 10 * MIN, 10)
    (read,) = page.rows
    tail = await _reader([row]).read_tail(SYM, SPEC, 1)
    ((_, tail_bar),) = tail.bars
    item = bar_item(bar, generation=GEN, bar_kind="time", include_delta=False)
    ps, qs = covering_scales([bar], price_scale=0, qty_scale=0)
    (frame,) = bars_frames([bar], generation=GEN, include_delta=False, price_scale=ps,
                           qty_scale=qs)  # fmt: skip
    (decoded,) = structured(decode(encode(frame)))["bars"]
    return {
        "row": _flags_of(row),
        "rest": _flags_of(serialize_bar(stored_bar(read), include_delta=True)),
        "tail": _flags_of(tail_bar),
        "ws_item": _flags_of(item),
        "ws_binary": _flags_of(decoded),
        "item_bar": _flags_of(item_bar(item, include_delta=False)),
    }


# -- AC1 (ruling 2): a tape gap and a quiet interval, end to end ----------------------------------


async def test_bar_flags_a_tape_gapped_bar_carries_tape_gap_on_every_surface() -> None:
    """#5396 AC1 as ruled: a bar built with a tape gap before it carries `tape_gap = true` in the
    stored row, the REST bar and the WS item, JSON and binary; it is no discontinuity."""
    got = await _surfaces(_bar(tape_gap=True))
    assert set(got.values()) == {(False, False, True)}, got


async def test_bar_flags_a_quiet_interval_sets_only_gap_before() -> None:
    """A minute with no print before a time bar is a discontinuity, not data loss: the builder's
    bar after it carries `gap_before` alone, and so does every surface."""
    builder = TimeBarBuilder(SPEC, SYM)
    updates = [*builder.on_trade(trade(us("10:00:01"), seq=1)),
               *builder.on_trade(trade(us("10:02:05"), seq=2)),
               *builder.on_clock(us("10:03:00"))]  # fmt: skip
    first, after = closes(updates)
    assert (first.partial, first.gap_before, first.tape_gap) == (True, False, False)
    assert (after.partial, after.gap_before, after.tape_gap) == (False, True, False)
    got = await _surfaces(after)
    assert set(got.values()) == {(True, False, False)}, got


@settings(max_examples=40, deadline=None)
@given(flags=st.tuples(st.booleans(), st.booleans(), st.booleans()))
async def test_bar_flags_round_trip_is_identity(flags: tuple[bool, bool, bool]) -> None:
    """Property: build -> row -> read -> REST / tail / WS (both forms) keeps every flag as set."""
    got = await _surfaces(_bar(**dict(zip(FLAGS, flags, strict=True))))
    assert set(got.values()) == {flags}, got


def test_bar_flags_a_clear_flag_is_absent_on_both_wires() -> None:
    """Absent reads false (22 `Bar`, 23 §14.3): an unflagged bar's REST bar and WS item are the
    bytes they were before the flags."""
    bar = _bar()
    rest = serialize_bar(stored_bar(bar_row(bar, SPEC, generation=GEN)), include_delta=False)
    item = bar_item(bar, generation=GEN, bar_kind="time", include_delta=False)
    assert not set(FLAGS) & (set(rest) | set(item))


def test_bar_flags_a_kline_row_carries_no_marker() -> None:
    """A bar not built from the tape (`kline` source) is `false` in all three."""
    row = bar_row(_bar(tape_gap=True, gap_before=True), SPEC, generation=GEN)
    row["source"] = KLINE_SOURCE
    assert _flags_of(stored_bar(row)) == (False, False, False)


# -- the checksum (ruling 4) ----------------------------------------------------------------------


def _pre_0008_checksum(row: dict[str, object]) -> int:
    """The checksum as written before 0008: the value columns alone, no flag (`rows` at 0003)."""
    blob = "\x1f".join(f"{k}={row.get(k)!r}" for k in _CHECKSUM_FIELDS)
    return int.from_bytes(hashlib.sha256(blob.encode()).digest()[:8], "big") & 0x7FFF_FFFF_FFFF_FFFF


def test_bar_flags_checksum_of_a_pre_0008_row_is_unchanged() -> None:
    """A row written before 0008 has no flag column (it reads `false`), and a row written with
    every flag false: both verify against the checksum they were written with."""
    row = bar_row(_bar(), SPEC, generation=GEN)
    old = {k: v for k, v in row.items() if k not in FLAG_COLUMNS and k != "row_checksum"}
    assert row_checksum(old) == _pre_0008_checksum(old) == row["row_checksum"]
    assert row_checksum({**old, **dict.fromkeys(FLAG_COLUMNS, False)}) == row["row_checksum"]


@pytest.mark.parametrize("flag", FLAGS)
def test_bar_flags_checksum_covers_a_set_flag(flag: str) -> None:
    """A set flag is appended (`name=True`): its checksum differs from the unflagged row's."""
    plain = bar_row(_bar(), SPEC, generation=GEN)
    flagged = bar_row(_bar(**{flag: True}), SPEC, generation=GEN)
    assert flagged["row_checksum"] != plain["row_checksum"]


@pytest.mark.parametrize("flag", FLAGS)
@pytest.mark.parametrize("written", [False, True])
async def test_bar_flags_an_edited_flag_fails_verification(flag: str, written: bool) -> None:
    """Clearing a written flag, or setting one, after the write is an integrity event: the read
    withholds the row (SR-E12-11)."""
    row = bar_row(_bar(**{flag: written}), SPEC, generation=GEN)
    row[flag] = not written
    page = await _reader([row]).read_bars(SYM, SPEC, T0, T0 + 10 * MIN, 10)
    assert (page.rows, page.dropped) == ([], 1)


# -- REST provenance (ruling 5) -------------------------------------------------------------------


def _stored(version: int | None) -> object:
    row = bar_row(_bar(), SPEC, generation=GEN)
    row["build_version"] = version
    return stored_bar(row)


@pytest.mark.parametrize(
    ("versions", "want"),
    [
        ([2, 2], {"build_version": 2, "stale_build": False}),
        ([1, 2], {"build_version": 1, "stale_build": True}),
        ([None, 2], {"build_version": 2, "stale_build": True}),
        ([None, None], {"stale_build": True}),
        ([0, 2], {"build_version": 2, "stale_build": True}),
        ([], {"build_version": 2, "stale_build": False}),
    ],
    ids=["current", "old", "null-and-current", "all-null", "zero-is-unknown", "no-bar"],
)
def test_bar_flags_provenance_names_the_lowest_build_and_stale(
    versions: list[int | None], want: dict[str, object]
) -> None:
    """`build_version` is the lowest recorded among the bars served (NULL out of the minimum,
    absent when none records one, the running version when none is served); `stale_build` is
    true for a bar below the running version or with no recorded one."""
    meta = bars_provenance([_stored(v) for v in versions], spec_hash=SPEC.spec_hash, running=2)
    assert meta == {"spec_hash": SPEC.spec_hash, **want}


def _kline(start: int = T0) -> StoredBar:
    """A stored exchange kline as the reader serves it: `source=kline`, yet a build_version."""
    event = KlineEvent.model_validate(
        dict(
            event_id="00000000-0000-7000-8000-000000000001", ts_event=start, ts_ingest=start,
            source="backfill", symbol=SYM, interval="1", start=start, end=start + MIN - 1,
            open="100", high="101", low="99", close="100.5", volume="10", turnover="1000",
            confirmed=True,
        )
    )  # fmt: skip
    return stored_bar(kline_row(event, SPEC))


_RUNNING = BUILD_VERSIONS["time"] + 1


def _prov(rows: list[object]) -> dict[str, object]:
    return bars_provenance(rows, spec_hash=SPEC.spec_hash, running=_RUNNING)


def test_bar_flags_provenance_a_klines_only_page_carries_the_running_build() -> None:
    """22 `BarsMeta`: an exchange kline is no built bar, though its row records a build_version
    (below `running` here): a klines-only page is `running` and not stale."""
    rows = [_kline(T0), _kline(T0 + MIN)]
    assert [r.build_version for r in rows] == [BUILD_VERSIONS["time"]] * 2
    assert _prov(rows) == {
        "spec_hash": SPEC.spec_hash, "build_version": _RUNNING, "stale_build": False
    }  # fmt: skip


@pytest.mark.parametrize(
    ("built", "want", "stale"),
    [(_RUNNING, _RUNNING, False), (_RUNNING - 1, _RUNNING - 1, True)],
    ids=["built-current", "built-old"],
)
def test_bar_flags_provenance_a_mixed_page_counts_only_the_built_bars(
    built: int, want: int, stale: bool
) -> None:
    """Kline rows (older build) beside a built row: only the built row sets the provenance."""
    row = bar_row(_bar(), SPEC, generation=GEN)
    row["build_version"] = built
    meta = _prov([_kline(T0), stored_bar(row), _kline(T0 + MIN)])
    assert (meta["build_version"], meta["stale_build"]) == (want, stale)


async def test_bar_flags_a_null_build_version_is_stale_on_the_range_and_tail_reads() -> None:
    """Ruling 5: a NULL `build_version` is unknown provenance on every read path, the tail too."""
    row = bar_row(_bar(), SPEC, generation=GEN)
    row["build_version"] = None
    row["row_checksum"] = row_checksum(row)
    page = await _reader([row]).read_bars(SYM, SPEC, T0, T0 + 10 * MIN, 10)
    tail = await _reader([row]).read_tail(SYM, SPEC, 1)
    assert (page.stale, tail.stale_build, tail.unknown_builds) == (True, True, 1)
    assert list(tail.builds.values()) == [None]
    assert stored_bar(page.rows[0]).build_version is None


def test_bar_flags_golden_row_names_tape_gap_only_when_true() -> None:
    """The determinism golden row (`bench.bar_determinism.comparator`) names `tape_gap` only when
    true, as the wires do: a golden written before the field stays byte-identical, and a bar that
    sets it is a field difference."""
    from bench.bar_determinism import comparator

    assert "tape_gap" not in comparator.row(_bar())
    assert comparator.row(_bar(tape_gap=True))["tape_gap"] == "true"
    (diff,) = comparator.compare([_bar()], [_bar(tape_gap=True)])
    assert (diff.field, diff.expected, diff.actual) == ("tape_gap", "false", "true")
