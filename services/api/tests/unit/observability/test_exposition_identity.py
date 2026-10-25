"""#4530: the facade's `generate_latest` renders the scrape at about half the library's cost, and
its output is byte for byte the library's: on the max-cardinality registry the latency test
scrapes, and on families that reach every branch (each metric type, escaped label values and help
text, timestamps, a label name and a metric name outside the legacy set, signed zero, NaN and
infinities, the same label names in a different order)."""

from __future__ import annotations

import inspect
from collections.abc import Iterable

import prometheus_client
from prometheus_client import CollectorRegistry
from prometheus_client.metrics_core import Metric
from prometheus_client.registry import Collector

from candleviewer.observability.metrics import Metrics, generate_latest
from candleviewer.observability.metrics_catalogue import register_r0, registered_specs


def _max_cardinality() -> Metrics:
    metrics = Metrics("dev")  # no process collectors: their values move between two scrapes
    r0 = register_r0(metrics)
    for spec in registered_specs():
        if not spec.labels:
            continue
        for i in range(spec.max_series):
            child = r0[spec.name].labels(*[f"v{i}"] * len(spec.labels))
            if spec.kind == "histogram":
                child.observe(0.01 * i)
            elif spec.kind == "counter":
                child.inc(i)
            else:
                child.set(-i)
    return metrics


class _EveryBranch(Collector):
    def collect(self) -> Iterable[Metric]:
        types = ("counter", "gauge", "histogram", "summary", "info", "stateset")
        for kind in (*types, "gaugehistogram", "unknown"):
            family = Metric(f"cv_{kind}", 'help with \\ a "quote"\nand a newline', kind)
            base = f"cv_{kind}"
            family.add_sample(base, {}, 1.0)
            family.add_sample(base, {"b": 'x"y', "a": "back\\slash"}, -0.0)
            family.add_sample(base, {"a": "new\nline", "b": "plain"}, 0.0)
            family.add_sample(base, {"le": "+Inf", "a": "é"}, float("nan"), timestamp=1.5)
            family.add_sample(base, {"a.dotted": "v"}, float("inf"))
            family.add_sample(base, {"a": "v"}, 12345678.0, timestamp=1700000000.123)
            family.add_sample(base, {"a": "v"}, -float("inf"))
            for suffix in ("_created", "_gsum", "_gcount", "_sum", "_count", "_bucket"):
                family.add_sample(base + suffix, {"a": "v"}, 1e-9)
            yield family
        dotted = Metric("cv.dotted.name", "a name outside the legacy set", "gauge")
        dotted.add_sample("cv.dotted.name", {"x": "1"}, 2.0)
        yield dotted


def test_generate_latest_matches_the_library_at_max_cardinality() -> None:
    registry = _max_cardinality().registry
    assert generate_latest(registry) == prometheus_client.generate_latest(registry)


def test_generate_latest_matches_the_library_on_every_branch() -> None:
    registry = CollectorRegistry()
    registry.register(_EveryBranch())
    ours = generate_latest(registry)
    assert b'b="x\\"y"' in ours and b"-0.0" in ours and b"cv_dotted_name" in ours
    assert ours == prometheus_client.generate_latest(registry)


def test_the_renderer_defaults_to_the_process_registry_as_the_library_does() -> None:
    # by identity: two scrapes of the live process registry differ (its gc counters move)
    default = inspect.signature(generate_latest).parameters["registry"].default
    assert default is prometheus_client.REGISTRY
