"""Property tests for the indicator kernels (E13-T02 plan §5; seeded hypothesis, C-13.7).

Generated series hold 1 to 60 bars on a 0.1 price grid in [100, 199.9] (so adjacent prices stay
within a factor of two and their binary64 differences are exact), with flat runs, zero volume
and session or day boundaries; parameters are small. Properties:

- incremental equals full: the value at every bar equals a full recompute of that prefix;
- a restore at a random cut equals an uninterrupted run (the BI-5 analogue);
- feeding in chunks, through a snapshot and a fresh kernel at each boundary, equals one pass;
- every kernel matches the exact reference within 1e-8, with identical `None` positions.
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

from hypothesis import given, seed, settings
from hypothesis import strategies as st

from candleviewer.orderflow.indicators import (
    KERNELS,
    BarInput,
    KernelContext,
    build_kernel,
    compute,
)
from candleviewer.orderflow.indicators.types import ParamValue
from tests.unit.orderflow.indicators._bars import MINUTE, T0, bits
from tests.unit.orderflow.indicators.reference import reference

SEED = 20261019
SOURCES = {name: cls.sources[0] for name, cls in KERNELS.items()}

type Case = tuple[str, dict[str, ParamValue], KernelContext]


@st.composite
def series(draw: st.DrawFn) -> list[BarInput]:
    count = draw(st.integers(1, 60))
    minute = draw(st.integers(0, 3 * 1440))
    price = draw(st.integers(1000, 1999))
    bars: list[BarInput] = []
    for i in range(count):
        if bars and draw(st.integers(0, 4)) == 0:  # a flat run repeats the previous bar
            bars.append(bars[-1]._replace(t=T0 + (minute + i) * MINUTE))
            continue
        close = min(1999, max(1000, price + draw(st.integers(-20, 20))))
        high = min(1999, max(price, close) + draw(st.integers(0, 10)))
        low = max(1000, min(price, close) - draw(st.integers(0, 10)))
        volume = draw(st.sampled_from([0, 1, 250, 37_500]) | st.integers(0, 50_000))
        delta = draw(st.integers(-volume, volume))
        prices = (price / 10, high / 10, low / 10, close / 10)
        t = T0 + (minute + i) * MINUTE
        bars.append(BarInput(t, *prices, volume / 1000, delta / 1000, False))
        price = close
    return bars


@st.composite
def cases(draw: st.DrawFn) -> Case:
    name = draw(st.sampled_from(sorted(KERNELS)))
    params: dict[str, ParamValue]
    if name in ("sma", "ema", "rsi", "atr", "adx"):
        params = {"n": draw(st.integers(1, 20))}
    elif name == "vwap":
        params = {"anchor": "session"}
    elif name == "cvd":
        params = {"anchor": draw(st.sampled_from(["session", "utc_day"]))}
    elif name == "zigzag":
        params = {"depth": draw(st.integers(1, 4)), "deviation_pct": 0}
    else:
        params = {}
    return name, params, KernelContext(draw(st.integers(0, 1439)))


def _full(case: Case, bars: list[BarInput]) -> list[tuple[float | None, ...]]:
    name, params, ctx = case
    return compute(name, bars, params, source=SOURCES[name], context=ctx)


@seed(SEED)
@settings(max_examples=150, deadline=None)
@given(case=cases(), bars=series())
def test_incremental_equals_a_full_recompute_at_every_bar(case: Case, bars: list[BarInput]) -> None:
    incremental = bits(_full(case, bars))
    for i in range(len(bars)):
        assert bits(_full(case, bars[: i + 1]))[-1] == incremental[i]


@seed(SEED)
@settings(max_examples=150, deadline=None)
@given(case=cases(), bars=series(), data=st.data())
def test_restore_at_a_random_cut_equals_an_uninterrupted_run(
    case: Case, bars: list[BarInput], data: st.DataObject
) -> None:
    name, params, ctx = case
    cut = data.draw(st.integers(0, len(bars)))
    first = build_kernel(name, params, source=SOURCES[name], context=ctx)
    head = first.run(bars[:cut])
    second = build_kernel(name, params, source=SOURCES[name], context=ctx)
    second.restore(first.snapshot())
    assert bits(head + second.run(bars[cut:])) == bits(_full(case, bars))


@seed(SEED)
@settings(max_examples=150, deadline=None)
@given(case=cases(), bars=series(), data=st.data())
def test_feeding_in_chunks_through_snapshots_equals_one_pass(
    case: Case, bars: list[BarInput], data: st.DataObject
) -> None:
    name, params, ctx = case
    cuts = sorted(data.draw(st.sets(st.integers(0, len(bars)), max_size=5)))
    out: list[tuple[float | None, ...]] = []
    blob: bytes | None = None
    for start, stop in zip([0, *cuts], [*cuts, len(bars)], strict=True):
        kernel = build_kernel(name, params, source=SOURCES[name], context=ctx)
        if blob is not None:
            kernel.restore(blob)
        out += kernel.run(bars[start:stop])
        blob = kernel.snapshot()
    assert bits(out) == bits(_full(case, bars))


@seed(SEED)
@settings(max_examples=60, deadline=None)
@given(case=cases(), bars=series())
def test_kernels_match_the_exact_reference_to_1e8(case: Case, bars: list[BarInput]) -> None:
    name, params, ctx = case
    for got_row, want_row in zip(
        _full(case, bars), reference(name, bars, params, ctx), strict=True
    ):
        for got, want in zip(got_row, want_row, strict=True):
            assert (got is None) == (want is None)
            if got is not None and want is not None:
                exact = Fraction(want) if isinstance(want, Decimal) else want
                assert abs(Fraction(got) - exact) <= Fraction(1, 10**8) * max(
                    Fraction(1), abs(exact)
                )
