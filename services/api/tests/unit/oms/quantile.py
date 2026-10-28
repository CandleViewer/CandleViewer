"""The one quantile the order lane's timing tests read (#913 L1d-3): the p95s of
`test_order_lane_isolation` and the p50s and p99s of `test_order_lane_stream_hop`."""

from __future__ import annotations

from collections.abc import Iterable


def quantile(samples: Iterable[float], q: float) -> float:
    """The `q` quantile of `samples`, the lower nearest rank: the sorted samples' entry at
    `int(q * (n - 1))`. Empty `samples` raise `IndexError`, so a caller asserts its count first."""
    ordered = sorted(samples)
    return ordered[int(q * (len(ordered) - 1))]
