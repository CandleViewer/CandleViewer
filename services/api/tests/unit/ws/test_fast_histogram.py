"""E17-T06: `FastHistogram`, the lock-free, weighted histogram of the WS send path.

Given the same observations its exposition is a `prometheus_client` `Histogram`'s byte for byte
(the text `/metrics` serves and OpenMetrics, alone and re-exported with `env`), a weighted
observation being the reference fed that value `weight` times. Both sides are built on a frozen
wall clock so their `_created` samples agree.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any, cast
from unittest import mock

import pytest
from hypothesis import given
from hypothesis import strategies as st
from prometheus_client import CollectorRegistry, Histogram, generate_latest
from prometheus_client.openmetrics.exposition import generate_latest as _openmetrics_latest

from candleviewer.observability.metrics import MetricsError, ReexportCollector
from candleviewer.observability.metrics_catalogue import FANOUT_BUCKETS
from candleviewer.ws.metrics import FastHistogram, _Exposition

_CREATED = 1_760_000_000.25
#: The library's OpenMetrics renderer is untyped: it takes a registry and returns bytes.
openmetrics_latest = cast(Callable[[CollectorRegistry], bytes], _openmetrics_latest)
KINDS = ("book_delta", "trades", "json")  # binding order is series order: kept on both sides
#: Bounds exact in binary, and values `k / 1024`: adding a value `weight` times (the reference)
#: and multiplying it by `weight` (the fast side) then give the same sum to the last bit.
_DYADIC = (0.25, 0.5, 1.0, 2.0, 4.0)
#: Bounds that render with an exponent (`4.194304e+06`), the way the send path's size series do.
_BYTES = (64, 256, 1024, 4096, 16384, 65536, 262144, 1048576, 4194304)
_Observations = Sequence[tuple[float, int]]  # (value, weight)


class _Pair:
    """A `FastHistogram` and a reference `Histogram`, alike, each on its own registry."""

    def __init__(self, name: str, buckets: Sequence[float], kinds: Sequence[str] = ()) -> None:
        self.fast_registry, self.ref_registry = CollectorRegistry(), CollectorRegistry()
        names = ("kind",) if kinds else ()
        with mock.patch.object(time, "time", return_value=_CREATED):
            self.fast = FastHistogram(
                name,
                "Help, with a \\ and a\nnewline.",
                buckets=buckets,
                labelnames=names,
                label_values=[(k,) for k in kinds],
                registry=self.fast_registry,
            )
            self.ref = Histogram(
                name,
                "Help, with a \\ and a\nnewline.",
                labelnames=names,
                buckets=buckets,
                registry=self.ref_registry,
            )
            for k in kinds:
                self.ref.labels(k)

    def observe(self, observations: _Observations, *kind: str) -> None:
        """Each value once, with its weight, on the fast side; `weight` times on the reference."""
        ref = self.ref.labels(*kind) if kind else self.ref
        for v, weight in observations:
            self.fast.labels(*kind).observe(v, weight)
            for _ in range(weight):
                ref.observe(v)

    def assert_same_exposition(self) -> bytes:
        text = generate_latest(self.fast_registry)
        assert text == generate_latest(self.ref_registry)
        # The OpenMetrics rendering (not served today) is the library's too, so it agrees as well.
        assert openmetrics_latest(self.fast_registry) == openmetrics_latest(self.ref_registry)
        return text


def _edges(bounds: Sequence[float]) -> list[float]:
    """Every bound, either side of it, zero, a negative value and +Inf."""
    out = [0.0, -1.0, math.inf, bounds[0] / 2, bounds[-1] * 2]
    for b in bounds:
        out += [b, math.nextafter(b, -math.inf), math.nextafter(b, math.inf)]
    return out


def test_exposition_equals_a_histogram_on_and_around_every_bound() -> None:
    pair = _Pair("t_fanout_seconds", FANOUT_BUCKETS)
    pair.observe([(v, 1) for v in _edges(FANOUT_BUCKETS)])
    text = pair.assert_same_exposition().decode()
    # A value equal to a bound counts in that bound's bucket (`le`): 0, -1, half the first bound
    # and the values at, below and above the first two bounds and at and below 0.001 make eleven.
    assert 't_fanout_seconds_bucket{le="0.001"} 11.0\n' in text
    assert 't_fanout_seconds_bucket{le="+Inf"} 41.0\n' in text
    assert "t_fanout_seconds_count 41.0\nt_fanout_seconds_sum +Inf\n" in text
    assert f"t_fanout_seconds_created {_CREATED:.11e}" in text


def test_a_weighted_labelled_exposition_equals_a_histogram_child_for_child() -> None:
    pair = _Pair("t_weighted_bytes", _BYTES, KINDS)
    pair.observe([(64, 32), (65, 32), (4_194_304, 32), (4_194_305, 1), (0, 3)], "book_delta")
    pair.observe([(1, 1), (1_000_000, 32)], "json")  # `trades` stays at zero: served all the same
    text = pair.assert_same_exposition().decode()
    assert 't_weighted_bytes_bucket{kind="book_delta",le="64.0"} 35.0\n' in text
    assert 't_weighted_bytes_bucket{kind="book_delta",le="4.194304e+06"} 99.0\n' in text
    assert 't_weighted_bytes_count{kind="book_delta"} 100.0\n' in text
    assert 't_weighted_bytes_count{kind="trades"} 0.0\n' in text


def test_re_exported_with_env_it_equals_a_re_exported_histogram() -> None:
    pair = _Pair("t_weighted_seconds", _DYADIC, KINDS)
    pair.observe([(0.25, 32), (0.5, 1), (1.0, 3), (2.0, 32), (4.0, 1), (1000.0, 3)], "trades")
    served = []
    for source in (pair.fast_registry, pair.ref_registry):
        target = CollectorRegistry()
        names = frozenset({"t_weighted_seconds"})
        ReexportCollector(target, names=names, const_labels={"env": "demo"}, source=source)
        served.append(generate_latest(target))
    assert served[0] == served[1]
    samples = [ln for ln in served[0].decode().splitlines() if not ln.startswith("#")]
    # Per kind: the buckets and +Inf, then count, sum and created.
    assert len(samples) == 3 * (len(_DYADIC) + 1 + 3)
    assert all('env="demo"' in ln for ln in samples)


_WEIGHTED = st.lists(
    st.tuples(st.integers(-2048, 8192).map(lambda k: k / 1024), st.integers(1, 40)), max_size=30
)
_UNWEIGHTED = st.lists(
    st.tuples(st.one_of(st.sampled_from(_DYADIC), st.floats(-1, 8, allow_nan=False)), st.just(1)),
    max_size=30,
)


@given(st.one_of(_WEIGHTED, _UNWEIGHTED))
def test_any_observations_expose_as_a_histogram_does(observations: _Observations) -> None:
    pair = _Pair("t_any_seconds", _DYADIC)
    pair.observe(observations)
    pair.assert_same_exposition()


def test_a_weight_counts_the_bucket_and_adds_value_times_weight_to_the_sum() -> None:
    child = FastHistogram("t_weight", "h", buckets=(1, 2), registry=CollectorRegistry()).labels()
    child.observe(2.0)  # the weight defaults to one
    child.observe(1.0)
    child.observe(2.5)
    child.observe(0.5, 8)
    assert child.reading() == ((9, 10, 11), 2.0 + 1.0 + 2.5 + 0.5 * 8)  # cumulative, `+Inf` last


def test_labels_are_a_closed_set_bound_at_declaration() -> None:
    fast = _Pair("t_closed_bytes", (64,), KINDS).fast
    assert fast.label_values == (("book_delta",), ("trades",), ("json",))
    assert fast.labels("json") is fast.labels("json")
    with pytest.raises(KeyError):
        fast.labels("bars")
    with pytest.raises(KeyError):
        fast.labels()  # a labelled histogram has no unlabelled series


@pytest.mark.parametrize(
    ("declaration", "error"),
    [
        ({"buckets": ()}, ValueError),
        ({"buckets": (2, 1)}, ValueError),
        ({"buckets": (1, 1)}, ValueError),
        ({"buckets": (1, math.inf)}, ValueError),
        ({"labelnames": ("kind",)}, ValueError),  # a labelled histogram needs its closed set
        ({"labelnames": ("kind",), "label_values": [("a",), ("a",)]}, ValueError),
        ({"labelnames": ("kind",), "label_values": [("a", "b")]}, ValueError),
        ({"labelnames": ("env",), "label_values": [("demo",)]}, MetricsError),  # added on re-export
        ({"labelnames": ("le",), "label_values": [("x",)]}, ValueError),  # reserved by `Histogram`
    ],
)
def test_a_declaration_is_validated(declaration: dict[str, Any], error: type[Exception]) -> None:
    with pytest.raises(error):
        FastHistogram(
            "t_bad", "h", **{"buckets": (1,), **declaration}, registry=CollectorRegistry()
        )


def test_a_scrape_while_the_exposition_is_built_serves_zeros() -> None:
    registry = CollectorRegistry()
    _Exposition("t_early_seconds", "h", buckets=(1,), registry=registry)  # no `serve()` yet
    assert registry.get_sample_value("t_early_seconds_count") == 0.0


def test_a_scrape_sees_buckets_and_sum_from_one_instant() -> None:
    """One writer thread, as on the loop; this thread scrapes meanwhile. Every value is 1.0, so a
    consistent reading has sum == count, or count - 1 while an observation is half done."""
    child = FastHistogram("t_race", "h", buckets=(0.5, 2), registry=CollectorRegistry()).labels()
    n = 20_000

    def write() -> None:
        for _ in range(n):
            child.observe(1.0)

    writer = threading.Thread(target=write)
    readings = []
    writer.start()
    while writer.is_alive():
        readings.append(child.reading())
    writer.join()
    readings.append(child.reading())
    for cumulative, total in readings:
        zero, ones, count = cumulative
        assert zero == 0 and ones == count and count - 1 <= total <= count
    assert readings[-1] == ((0, n, n), float(n))
