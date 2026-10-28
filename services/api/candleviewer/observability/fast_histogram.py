"""`FastHistogram`: a lock-free histogram for an asyncio hot path, exposed exactly as a
`prometheus_client` `Histogram` (E17-T06, #571).

Moved here from `ws/metrics.py` (#571 audit): its scrape adapter, `_Exposition`, depends on the
library's metric family and sample types, and `candleviewer.observability` is the one package that
may import `prometheus_client` (import-linter E04-T03, semgrep `cv-obs-no-prometheus-import`). The
WS send-path series that use it are declared in `ws/metrics.py`, which says why they sample.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterable, Mapping, Sequence
from itertools import accumulate, pairwise
from math import isfinite

from prometheus_client.metrics_core import Metric

from candleviewer.observability.metrics import CollectorRegistry, Histogram, check_label_names

#: One child's scrape reading: cumulative bucket counts (the last, `+Inf`, is the count), sum.
Reading = tuple[tuple[float, ...], float]


class FastHistogramChild:
    """One series of a `FastHistogram`: the per-bucket counts (not cumulative; the last bucket is
    `+Inf`) and then the sum, in one list.

    Only the event loop observes; a scrape may run on another thread (`/metrics` is a sync route).
    `reading()` copies the list in one C call that no other thread can interleave under the GIL,
    so a scrape sees every bucket and the sum from one instant: the count (the `+Inf` bucket) can
    be one observation ahead of the sum, the one the loop is midway through, which Prometheus
    tolerates. Nothing is torn or lost: one writer, atomic slot stores, immutable numbers.
    """

    __slots__ = ("_bounds", "_cells")

    def __init__(self, bounds: tuple[float, ...]) -> None:
        self._bounds = bounds
        self._cells: list[float] = [0] * (len(bounds) + 1) + [0.0]

    def observe(self, value: float, weight: int = 1) -> None:
        """Count `value` `weight` times in the first bucket whose bound is >= it (Prometheus `le`;
        past the last bound, `+Inf`) and add `value * weight` to the sum: one bisect and two
        increments, with no lock, label lookup or object built. A call site that observes one
        event in N passes `weight=N`, so the counts and the sum estimate the whole stream and the
        exposition stays a valid histogram. `weight` is a positive int (not checked, for speed);
        NaN is out of domain."""
        cells = self._cells
        cells[bisect_left(self._bounds, value)] += weight
        cells[-1] += value * weight

    def reading(self) -> Reading:
        """This series for a scrape: (cumulative bucket counts, ending with `+Inf`; the sum)."""
        *counts, total = tuple(self._cells)  # the one-step copy the class doc relies on
        return tuple(accumulate(counts)), total


class FastHistogram:
    """A histogram for the WS hot path, exposed exactly as a `prometheus_client` `Histogram`.

    Every child (one per closed label set, or the one series when there are no labels) is bound
    here and none is ever added, so `labels()` is a lookup. The scrape side is an `_Exposition` on
    `registry` (None: the library's default, where `export_ws_metrics()` re-exports from).

    Why the send path samples: #571 caps its instrumentation at 2 % of the fan-out path, and a
    frame there costs 10-55 us. Measured in situ, an `observe` is ~0.25 us and a clock read ~0.07
    us, so observing three series and stamping every frame would cost 1.0-2.5 us, 2-25 % of it.
    The three per-frame series (`cv_ws_fanout_seconds`, `cv_ws_frame_encode_seconds`,
    `cv_ws_frame_bytes`) therefore observe one frame in `SAMPLE_EVERY`, chosen by a counter and
    never at random, with `weight=SAMPLE_EVERY`; the clock reads that only feed a skipped
    observation are skipped too. Rates are right for a long-lived subscription, and a count is
    a lower bound within `SAMPLE_EVERY - 1` frames of it (its first 31 frames are never
    observed); the quantiles are those of a systematic sample, unbiased unless the stream a
    counter walks has a period that divides `SAMPLE_EVERY`. So no counter is shared by
    connections or kinds (eight subscribers fed in turn by one would always sample the same
    one): the counter is the subscription's own `s`, the hub stamps the frame it selects, and
    the encoder and the writer observe the frames it stamped.
    """

    def __init__(
        self,
        name: str,
        documentation: str,
        *,
        buckets: Sequence[float],
        labelnames: Sequence[str] = (),
        label_values: Iterable[Sequence[str]] = (),
        registry: CollectorRegistry | None = None,
    ) -> None:
        bounds = tuple(float(b) for b in buckets)
        if not bounds or not all(map(isfinite, bounds)) or any(a >= b for a, b in pairwise(bounds)):
            raise ValueError(f"{name}: buckets must be finite and ascending; +Inf is implicit")
        check_label_names(name, labelnames)
        keys = tuple(tuple(v) for v in label_values) or ((),)
        if len(set(keys)) != len(keys) or any(len(k) != len(labelnames) for k in keys):
            raise ValueError(f"{name}: label_values must be distinct, one value per label name")
        self.name = name
        self.buckets = bounds
        self.labelnames = tuple(labelnames)
        #: The closed label sets, in binding order (the exposition's series order).
        self.label_values = keys
        self._children = {key: FastHistogramChild(bounds) for key in keys}
        self._exposition = _Exposition.serve(self, documentation, registry)

    def labels(self, *values: str) -> FastHistogramChild:
        """The child bound for `values` (none: the unlabelled series). KeyError outside the
        closed set: no child is created after construction."""
        return self._children[values]

    def readings(self) -> dict[tuple[str, ...], Reading]:
        """Every child's reading for one scrape, each taken once."""
        return {key: child.reading() for key, child in self._children.items()}

    def sample_value(
        self, name: str, labels: Mapping[str, str], readings: Mapping[tuple[str, ...], Reading]
    ) -> float | None:
        """The value of one exposition sample from `readings`; None keeps the library's own
        (`_created`)."""
        cumulative, total = readings[tuple(labels.get(n, "") for n in self.labelnames)]
        suffix = name.removeprefix(self.name)
        if suffix == "_bucket":
            return float(cumulative[bisect_left(self.buckets, float(labels["le"]))])
        if suffix == "_count":
            return float(cumulative[-1])
        if suffix == "_sum":
            return float(total)
        return None


class _Exposition(Histogram):
    """The scrape side of one `FastHistogram`: a facade `Histogram` that nothing observes.

    The adapter is a `Histogram` with the fast one's name, help, labels and buckets. `collect()`
    takes the library's own family (sample names, `le` strings, order, `_created`, all at zero)
    and swaps in the fast values: the exposition is a `Histogram`'s, byte for byte. It replaces
    each `Sample` with `_replace`, which ties it to the library's sample type; it lives here, in
    the module that owns the `prometheus_client` coupling (#571), where a library upgrade that
    changes that type fails `test_fast_histogram.py`'s byte-for-byte exposition test, not a
    scrape in production.
    """

    #: Bound by `serve()` once the template children exist; None only while it builds them.
    fast: FastHistogram | None = None

    @classmethod
    def serve(
        cls, fast: FastHistogram, documentation: str, registry: CollectorRegistry | None
    ) -> _Exposition:
        names, buckets = fast.labelnames, fast.buckets
        if registry is None:  # the library default: no handle to it is importable here
            out = cls(fast.name, documentation, names, buckets=buckets)
        else:
            out = cls(fast.name, documentation, names, buckets=buckets, registry=registry)
        for key in fast.label_values:
            if key:
                out.labels(*key)
        out.fast = fast
        return out

    def collect(self) -> list[Metric]:
        families = list(super().collect())
        fast = self.fast
        if fast is None:  # scraped while `serve()` builds it: nothing is observed yet
            return families
        readings = fast.readings()
        for family in families:
            samples = []
            for s in family.samples:
                value = fast.sample_value(s.name, s.labels, readings)
                samples.append(s if value is None else s._replace(value=value))
            family.samples = samples
        return families
