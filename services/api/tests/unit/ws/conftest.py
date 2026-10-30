"""Per-test isolation for `tests/unit/ws` (#5084)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from candleviewer.ws.upstream import cv_ws_upstream_consumers_in_use


@pytest.fixture(autouse=True)
def _fresh_upstream_consumers_gauge() -> Iterator[None]:
    """Drop every `cv_ws_upstream_consumers_in_use` series a test leaves behind. The gauge is
    process-global and a lease that is never released keeps its series: the `probe` family of
    `test_the_floor_follows_the_bar_series_a_topic_names_not_its_family` (test_subscriptions.py)
    reached the label audit of test_ws_metrics_session_labels.py, which reads every series."""
    yield
    cv_ws_upstream_consumers_in_use.clear()
