"""Wire mapping, Bar/BarUpdate models and densify (E12-T01)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from candleviewer.bars.errors import BarsError, BarSpecError, SyntheticBarPersistError
from candleviewer.bars.models import Bar, BarBuilder, BarSpec, BarUpdate, BuilderState
from candleviewer.bars.series import BarSeries, assert_persistable
from candleviewer.bars.spec import TIME_INTERVALS, from_wire, is_wire_representable, to_wire

# --- Scenario: Wire round-trip -------------------------------------------------------------

wire_pairs = st.one_of(
    st.tuples(st.just("time"), st.sampled_from(sorted(TIME_INTERVALS))),
    st.tuples(
        st.sampled_from(["tick", "volume", "range", "delta"]),
        st.integers(1, 10**17).map(str),
    ),
    st.tuples(st.just("renko"), st.integers(2, 100_000).map(str)),
)


@given(wire_pairs)
def test_wire_roundtrip_pair_to_spec_to_pair(pair: tuple[str, str]) -> None:
    spec = from_wire(*pair)
    assert to_wire(spec) == pair
    again = from_wire(*to_wire(spec))
    assert again == spec and again.spec_hash == spec.spec_hash


@pytest.mark.parametrize(
    ("bar_type", "param", "spec"),
    [
        ("time", "5", BarSpec(kind="time", interval_ms=300_000)),
        ("time", "D", BarSpec(kind="time", interval_ms=86_400_000)),
        ("tick", "1000", BarSpec(kind="tick", tick_count=1000)),
        ("volume", "50", BarSpec(kind="volume", volume_threshold=Decimal("50.00"))),
        ("range", "40", BarSpec(kind="range", range_ticks=40)),
        ("delta", "25", BarSpec(kind="delta", delta_threshold=Decimal(25))),
        ("renko", "30", BarSpec(kind="renko", range_ticks=30)),
    ],
)
def test_wire_roundtrip_every_kind(bar_type: str, param: str, spec: BarSpec) -> None:
    assert from_wire(bar_type, param) == spec
    assert to_wire(spec) == (bar_type, param)
    assert from_wire(*to_wire(spec)).spec_hash == spec.spec_hash


@pytest.mark.parametrize("param", ["1.5", "BTC.USDT", ".", "5."])
def test_wire_param_with_dot_rejected(param: str) -> None:
    with pytest.raises(BarSpecError, match="must not contain a dot"):
        from_wire("volume", param)


@pytest.mark.parametrize(
    ("bar_type", "param", "match"),
    [
        ("pnf", "10:3", "Point-and-figure"),
        ("heikin_ashi", "5", "Heikin-Ashi"),
        ("candles", "5", "not a supported bar type"),
        ("time", "M", "not a supported time interval"),
        ("time", "7", "not a supported time interval"),
        ("renko", "atr:14", "ATR bricks are not available yet"),
        ("renko", "1", "between 2 and 100000"),
        ("renko", "100001", "between 2 and 100000"),
        ("tick", "0", "positive whole number"),
        ("tick", "01", "positive whole number"),
        ("tick", "-5", "positive whole number"),
        ("volume", "1e3", "positive whole number"),
        ("range", "1" * 25, "at most 24"),
        ("tick", "1:2", "positive whole number"),
        # #3555: `$` also matches before a final newline, so `match` took the first one as 5
        ("tick", "5\n", "positive whole number"),
        ("tick", "5\r\n", "positive whole number"),
    ],
)
def test_wire_invalid_pairs_rejected_with_sentence(bar_type: str, param: str, match: str) -> None:
    with pytest.raises(BarSpecError, match=match) as exc:
        from_wire(bar_type, param)
    assert str(exc.value).endswith(".")


@pytest.mark.parametrize(
    ("spec", "match"),
    [
        (BarSpec(kind="time", interval_ms=60_000, price_source="mark"), "price_source"),
        (BarSpec(kind="renko", range_ticks=3, renko_wick=True), "renko_wick"),
        (BarSpec(kind="time", interval_ms=1234), "no wire interval code"),
        (BarSpec(kind="volume", volume_threshold=Decimal("0.5")), "volume_threshold"),
        (BarSpec(kind="delta", delta_threshold=Decimal("2.5")), "delta_threshold"),
        (BarSpec(kind="volume", volume_threshold=Decimal(10) ** 30), "at most 24"),
    ],
)
def test_to_wire_unrepresentable_specs_raise(spec: BarSpec, match: str) -> None:
    with pytest.raises(BarSpecError, match=match):
        to_wire(spec)
    assert not is_wire_representable(spec)


# --- Bar / BarUpdate / BuilderState --------------------------------------------------------

H = "a" * 64


def make_bar(index: int, open_time: int, close: str = "100", **kw: object) -> Bar:
    fields: dict[str, object] = {
        "spec_hash": H,
        "symbol": "BTCUSDT",
        "index": index,
        "open_time": open_time,
        "close_time": open_time + 60_000_000,
        "open": Decimal("100"),
        "high": Decimal("101"),
        "low": Decimal("99"),
        "close": Decimal(close),
        "volume": Decimal("3"),
        "buy_volume": Decimal("2"),
        "sell_volume": Decimal("1"),
        "delta": Decimal("1"),
        "min_delta": Decimal("-1"),
        "max_delta": Decimal("2"),
        "trade_count": 4,
        "turnover": Decimal("300"),
        "vwap": Decimal("100"),
        "closed": True,
        "partial": False,
        "gap_before": False,
    }
    fields.update(kw)
    return Bar.model_validate(fields)


def test_bar_full_field_set_and_update() -> None:
    bar = make_bar(0, 0)
    assert bar.synthetic is False
    upd = BarUpdate(kind="close", bar=bar)
    assert BarUpdate.model_validate_json(upd.model_dump_json()) == upd


def test_bar_rejects_bad_spec_hash_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        make_bar(0, 0, spec_hash="nothex")
    with pytest.raises(ValidationError):
        make_bar(0, 0, amended=True)


def test_builder_state_envelope_and_protocol_declaration() -> None:
    st_ = BuilderState(spec_hash=H, symbol="BTCUSDT", state_version=1, blob=b"\x80")
    assert st_.blob == b"\x80"
    assert {"on_trade", "on_clock", "snapshot", "restore"} <= set(dir(BarBuilder))


# --- Scenario: densify never leaks ---------------------------------------------------------

SPEC_1M = BarSpec(kind="time", interval_ms=60_000)
STEP = 60_000_000


def test_densify_fills_gaps_with_flat_synthetic_bars() -> None:
    series = BarSeries(
        SPEC_1M, [make_bar(5, 0, close="105"), make_bar(6, 3 * STEP, gap_before=True)]
    )
    dense = series.densify()
    assert len(series) == 2 and len(dense) == 4
    fillers = list(dense)[1:3]
    for i, f in enumerate(fillers, start=1):
        assert f.synthetic is True and f.volume == 0 and f.trade_count == 0
        assert f.open == f.high == f.low == f.close == f.vwap == Decimal("105")
        assert f.open_time == i * STEP
    assert [b.index for b in dense] == [5, 5, 5, 6]
    assert [b.open_time for b in dense] == [0, STEP, 2 * STEP, 3 * STEP]


def test_densify_synthetic_bars_refused_by_persistence_guard() -> None:
    dense = BarSeries(SPEC_1M, [make_bar(0, 0), make_bar(1, 2 * STEP)]).densify()
    real, synthetic, last = list(dense)
    assert assert_persistable(real) is real
    with pytest.raises(SyntheticBarPersistError, match="must not be persisted"):
        assert_persistable(synthetic)
    assert assert_persistable(last).gap_before is False


def test_densify_contiguous_and_empty_series_unchanged() -> None:
    contiguous = BarSeries(SPEC_1M, [make_bar(0, 0), make_bar(1, STEP)])
    assert list(contiguous.densify()) == list(contiguous)
    empty = BarSeries(SPEC_1M, [])
    assert len(empty.densify()) == 0


def test_densify_rejects_non_time_specs() -> None:
    with pytest.raises(BarsError, match="time bars only"):
        BarSeries(BarSpec(kind="tick", tick_count=5), []).densify()


def test_densify_leaves_real_bars_untouched() -> None:
    r1, r2 = make_bar(5, 0, close="105"), make_bar(6, 3 * STEP, gap_before=True)
    dense = list(BarSeries(SPEC_1M, [r1, r2]).densify())
    assert dense[0] is r1 and dense[3] is r2
    assert (dense[3].index, dense[3].gap_before) == (6, True)
    assert [b.synthetic for b in dense] == [False, True, True, False]
    with pytest.raises(SyntheticBarPersistError):
        assert_persistable(dense[1])


def test_spec_rejects_over_precise_decimal_and_hash_does_not_round() -> None:
    with pytest.raises(ValidationError, match="significant digits"):
        BarSpec(kind="volume", volume_threshold=Decimal("1." + "0" * 10 + "1" * 20))
    ok = BarSpec(kind="volume", volume_threshold=Decimal("1." + "1" * 27))
    assert "1" * 27 in ok.spec_hash or ok.spec_hash
    from candleviewer.bars.spec import dec_str

    assert dec_str(Decimal("1." + "1" * 40)) == "1." + "1" * 40
