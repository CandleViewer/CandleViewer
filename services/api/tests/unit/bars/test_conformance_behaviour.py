"""E12-Q02 behaviour tests over the live `BarBuilderSet`: streaming == batch, build_version
rebuilds, late / duplicate / regressing prints (24-internal-schemas.md §3.3), and Hypothesis
properties that hold for any tape. Reuses the E12-T04 generator and comparator.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from itertools import pairwise

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from prometheus_client import REGISTRY

from bench.bar_conformance import runner as cf
from bench.bar_determinism import comparator, generator, tapes
from bench.bar_determinism.generator import TICK, GenConfig
from candleviewer.bars import rows
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.ingestion.trade_stream import DedupeRing

SPECS = cf.live_cases()
SYM = "BTCUSDT"


def lines_for(
    tape: list[TradeEvent], chunk: int, specs: dict[str, BarSpec]
) -> dict[str, list[str]]:
    got = asyncio.run(cf.run_set(tape, specs, SYM, chunk=chunk))
    return {k: cf.lines(v) for k, v in got.items()}


def _equal(a: dict[str, list[str]], b: dict[str, list[str]]) -> None:
    assert a.keys() == b.keys()
    for k in a:
        diffs = comparator.compare_lines(a[k], b[k])
        assert not diffs, f"{k}:\n{comparator.render(diffs)}"


def _updates_equal(tape: list[TradeEvent]) -> None:
    """The FULL emitted update sequence (kind, amended, bar) must be identical for every
    trade-driven kind: the lane applies one trade at a time whatever the publish burst size.
    Time bars are compared on final bars only: their `close` updates are emitted by the clock
    tick, which the runner drives once per burst, so bursts legitimately differ in WHEN a bar
    closes (never in its content)."""
    one = asyncio.run(cf.run_full(tape, SPECS, SYM, chunk=1))[1]
    many = asyncio.run(cf.run_full(tape, SPECS, SYM, chunk=10_000))[1]
    for label, spec in SPECS.items():
        if spec.kind != "time":
            assert one[label] == many[label], f"{label}: update sequence differs"


def test_streaming_equals_batch_on_dense_prefix() -> None:
    """PR lane: first 3k prints of btcusdt-2026-09-01, 1-trade vs 10 000-trade chunks."""
    tape = tapes.read_tape("btcusdt-2026-09-01")[:3_000]
    _equal(lines_for(tape, 1, SPECS), lines_for(tape, 10_000, SPECS))
    _updates_equal(tape)


@pytest.mark.harness
def test_streaming_equals_batch_full_btcusdt_day() -> None:
    tape = tapes.read_tape("btcusdt-2026-09-01")
    one = lines_for(tape, 1, SPECS)
    _equal(one, lines_for(tape, 10_000, SPECS))
    _updates_equal(tape)
    for label in SPECS:  # and both equal the committed golden, close timestamps included
        assert not comparator.compare_lines(cf.read_golden("btcusdt-2026-09-01", label), one[label])


def test_rebuild_twice_identical_and_build_version_bump_keeps_bars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tape = tapes.read_tape("edge-ticks")
    spec = SPECS["vol:50"]
    first, again = lines_for(tape, 500, {"v": spec}), lines_for(tape, 500, {"v": spec})
    _equal(first, again)
    v0 = rows.BUILD_VERSIONS["volume"]
    row0 = rows.bar_row(_bars(tape, spec)[0], spec, generation=0)
    monkeypatch.setitem(rows.BUILD_VERSIONS, "volume", v0 + 1)
    _equal(first, lines_for(tape, 500, {"v": spec}))  # identical bars ...
    row1 = rows.bar_row(_bars(tape, spec)[0], spec, generation=0)
    assert (row0["build_version"], row1["build_version"]) == (v0, v0 + 1)  # ... new version tag
    assert {k: v for k, v in row0.items() if k not in ("build_version", "row_checksum")} == {
        k: v for k, v in row1.items() if k not in ("build_version", "row_checksum")
    }


def _bars(tape: list[TradeEvent], spec: BarSpec) -> list[Bar]:
    return asyncio.run(cf.run_set(tape, {"x": spec}, SYM, chunk=500))["x"]


# -- late / duplicate / regression (§3.3) ---------------------------------------------------


def _t(ts_s: float, px: str = "100", qty: str = "1", seq: int = 0, tid: str | None = None):  # type: ignore[no-untyped-def]
    side = "buy"
    return tapes.event(
        seq,
        1_800_000_000_000_000 + int(ts_s * 1e6),
        Decimal(px),
        Decimal(qty),
        side,
        SYM,
        tid or f"t{seq}",
    )


def _dropped(reason: str) -> float:
    v = REGISTRY.get_sample_value(
        "bars_late_trade_dropped_total", {"symbol": SYM, "reason": reason}
    )
    return float(v or 0.0)


def _full(tape: list[TradeEvent], spec: BarSpec) -> list[cf.Update]:
    return asyncio.run(cf.run_full(tape, {"x": spec}, SYM, chunk=500))[1]["x"]


def test_late_print_after_close_within_window_amends_the_closed_bar() -> None:
    """§3.3c: applied to the historical bar and re-emitted as `close` with `amended=True`."""
    spec = SPECS["time:1"]
    tape = [_t(10, seq=0), _t(70, seq=1), _t(110, seq=2), _t(20, "105", "2", seq=3)]
    bars = _bars(tape, spec)
    assert [b.volume for b in bars[:2]] == [Decimal(3), Decimal(2)]  # late 2 landed in closed bar 0
    assert bars[0].high == Decimal(105) and bars[0].closed
    kind, amended, row = _full(tape, spec)[-1]  # the late print's own emission
    assert (kind, amended) == ("close", True)
    assert json.loads(row)["index"] == "0" and json.loads(row)["high"] == "105"


def test_late_print_beyond_60s_window_is_dropped_and_counted_late_window() -> None:
    spec = SPECS["time:1"]
    tape = [_t(10, seq=0), _t(70, seq=1), _t(400, seq=2), _t(20, "105", "2", seq=3)]
    before = (_dropped("late_window"), _dropped("empty_interval"))
    bars = _bars(tape, spec)
    assert bars[0].volume == Decimal(1) and bars[0].high == Decimal(100)
    assert sum(b.volume for b in bars) == Decimal(3)  # the dropped qty is not in any bar
    assert _dropped("late_window") - before[0] == 1
    assert _dropped("empty_interval") == before[1]
    assert not any(a for _, a, _ in _full(tape, spec))  # nothing re-emitted as amended


def test_late_print_into_empty_interval_is_dropped_and_counted_empty_interval() -> None:
    spec = SPECS["time:1"]
    tape = [
        _t(10, seq=0),
        _t(150, seq=1),
        _t(100, "105", "2", seq=2),
    ]  # min 1: empty, in window
    before = (_dropped("late_window"), _dropped("empty_interval"))
    bars = _bars(tape, spec)
    assert [b.volume for b in bars] == [Decimal(1), Decimal(1)] and bars[1].gap_before
    assert _dropped("empty_interval") - before[1] == 1
    assert _dropped("late_window") == before[0]


def test_gap_tape_backfill_older_than_the_window_is_dropped_as_late_window() -> None:
    """btcusdt-2026-09-02-gap (§3.3c): 80 backfilled prints arrive ~650 s after their event
    time, far outside the 60 s amend window, so each is dropped and counted `late_window`;
    the hole itself leaves empty intervals (`gap_before`). Compared with the same tape minus
    the backfill (identical seed, hole only) the delta is exactly 80 and the bars are equal."""
    tape = tapes.read_tape("btcusdt-2026-09-02-gap")
    seed = int(tapes.TAPES["btcusdt-2026-09-02-gap"].build()[1]["seed"])
    backfill = {f"{seed:x}-{q:x}" for q in range(20_000, 20_080)}
    assert sum(t.trade_id in backfill for t in tape) == 80
    hole_only = [t for t in tape if t.trade_id not in backfill]
    spec = SPECS["time:1"]
    c0 = _dropped("late_window")
    hole = _bars(hole_only, spec)
    c1 = _dropped("late_window")
    full = _bars(tape, spec)
    c2 = _dropped("late_window")
    assert (c2 - c1) - (c1 - c0) == 80
    assert cf.lines(full) == cf.lines(hole)  # dropped, so no bar changes
    assert sum(b.gap_before for b in full) > 0


def test_duplicate_trade_id_is_not_suppressed_by_builders_but_by_the_upstream_ring() -> None:
    """§3.3 tick note: duplicate suppression is upstream (`TradeStream` DedupeRing); the
    builder set counts every print it is given."""
    d1, d2 = _t(10, seq=0, tid="same"), _t(11, seq=1, tid="same")
    assert sum(b.volume for b in _bars([d1, d2], SPECS["time:1"])) == Decimal(2)
    ring = DedupeRing()
    kept = [t for t in (d1, d2) if ring.add(t.trade_id)]
    assert sum(b.volume for b in _bars(kept, SPECS["time:1"])) == Decimal(1)


def test_timestamp_regression_inside_open_bar_orders_by_event_time() -> None:
    spec = SPECS["time:1"]
    bars = _bars([_t(40, "101", seq=0), _t(20, "99", seq=1), _t(50, "102", seq=2)], spec)
    assert len(bars) == 1
    assert (bars[0].open, bars[0].close, bars[0].low, bars[0].high) == (
        Decimal(99),
        Decimal(102),
        Decimal(99),
        Decimal(102),
    )


def test_timestamp_regression_in_activity_bars_joins_the_open_bar() -> None:
    bars = _bars([_t(10, seq=0), _t(900, seq=1), _t(20, "103", seq=2)], SPECS["tick:100"])
    assert len(bars) == 1 and bars[0].trade_count == 3  # closed activity bars are final


# -- exact-threshold / overshoot (AC edge case) ---------------------------------------------


def test_exact_fill_closes_without_empty_successor_and_overshoot_conserves_volume() -> None:
    tape = tapes.read_tape("edge-ticks")[:4]  # 20 + 30 (exact fill), 150.003 overshoot, 49.997
    bars = _bars(tape, SPECS["vol:50"])
    assert [b.volume for b in bars] == [Decimal(50)] * 4 + [Decimal(50)]
    assert all(b.volume > 0 for b in bars)  # no empty successor after the exact fill
    assert sum(b.volume for b in bars) == sum((t.qty for t in tape), Decimal(0))
    assert not bars[-1].closed or bars[-1].volume == Decimal(50)


# -- properties over arbitrary generated tapes ----------------------------------------------

_CFG = st.builds(
    GenConfig,
    seed=st.integers(0, 10_000),
    n=st.integers(50, 600),
    threshold_lots=st.just(40),
    jump_ticks=st.integers(5, 60),
    p_late=st.just(0.0),
    p_duplicate=st.just(0.0),
    p_exact=st.just(0.03),
    p_huge=st.just(0.01),
)
_NON_TIME = {k: v for k, v in SPECS.items() if v.kind != "time"}


@settings(max_examples=20, deadline=None)
@given(_CFG)
def test_properties_hold_for_arbitrary_tapes(cfg: GenConfig) -> None:
    tape = generator.generate(cfg)
    specs = {
        **SPECS,
        "vol:2": BarSpec(kind="volume", volume_threshold=Decimal(2)),
        # Generated sizes are ~0.02, so delta:500 never closes here; a small threshold makes the
        # first-crossing assertion below fire (non-vacuous).
        "delta:0.05": BarSpec(kind="delta", delta_threshold=Decimal("0.05")),
    }
    got = asyncio.run(cf.run_set(tape, specs, SYM, chunk=300))
    total = sum((t.qty for t in tape), Decimal(0))
    for label, bars in got.items():
        spec = specs[label]
        for b in bars:
            assert b.low <= b.open <= b.high and b.low <= b.close <= b.high, label
            assert b.close_time >= b.open_time, label  # close_t populated on every kind
        assert sum(1 for b in bars if not b.closed) <= 1, label
        if any(not b.closed for b in bars):
            assert not bars[-1].closed, label  # the single non-confirm bar is the tail
        if spec.kind in ("time",):
            assert all(x.open_time <= y.open_time for x, y in pairwise(bars)), label
        if spec.kind in ("volume", "tick", "range", "delta"):
            assert sum(b.volume for b in bars) == total, label  # Σv conservation
        if spec.kind == "range":
            width = spec.range_ticks * TICK  # type: ignore[operator]
            assert all(b.high - b.low < width for b in bars if not b.closed), label
        if spec.kind == "renko":
            brick = spec.range_ticks * TICK  # type: ignore[operator]
            assert all(b.high - b.low == brick for b in bars if b.closed), label
        if spec.kind == "delta":
            thr = Decimal(spec.param_value)
            assert all(abs(b.delta) >= thr for b in bars if b.closed), label
            # first-crossing: replay the in-order tape; each bar must end exactly where |delta|
            # first reaches the threshold (a builder closing one print late fails here).
            run, n, want = Decimal(0), 0, []
            for t in tape:
                run += t.qty if t.side == "buy" else -t.qty
                n += 1
                if abs(run) >= thr:
                    want.append((n, run))
                    run, n = Decimal(0), 0
            got_closed = [(b.trade_count, b.delta) for b in bars if b.closed]
            assert got_closed == want, label
            if label == "delta:0.05":
                assert want, "first-crossing check must fire (non-vacuous)"
