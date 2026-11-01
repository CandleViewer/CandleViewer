"""E35-T09 (#5000) slice 2d: the executor's metrics go live (BQ-8; `20-architecture.md` §12.1).

`ExecutorMetrics` over a metrics facade of its own registry: each result by type and outcome with
its duration, the blocked metric only for a result that names a `blocked_by` (and the tick's own
refusals, each once), the closed label sets checked before any series is touched.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE, register_r0
from candleviewer.rules.executor.metrics import ExecutorMetrics
from candleviewer.rules.executor.results import ActionResult, blocked_result, skipped_result
from tests.rules.executor.request_builders import Counted

_IDS: dict[str, Any] = {"account_id": None, "resolved_accounts": (), "dedupe_key": "0" * 64}


def _result(node: str, action_type: str, outcome: Any, micros: int = 0) -> ActionResult:
    return ActionResult(
        node_id=node, action_type=action_type, outcome=outcome, duration_us=micros, **_IDS
    )


def test_every_result_is_counted_by_type_and_outcome_with_its_duration() -> None:
    counted = Counted()
    for result in (
        _result("a1", "place_order", "ok", 2_500), _result("a2", "place_order", "unknown", 500),
        _result("a3", "send_notification", "simulated", 1_000),
        blocked_result(node_id="a4", action_type="cancel_order", reason="unavailable", **_IDS),
    ):  # fmt: skip
        counted.metrics.result(result)
    assert counted.of("rule_actions_total") == {
        ("ok", "place_order"): 1, ("unknown", "place_order"): 1,
        ("simulated", "send_notification"): 1, ("blocked", "cancel_order"): 1,
    }  # fmt: skip
    registry, env = counted.facade.registry, {"env": "demo"}
    place = env | {"type": "place_order"}
    assert registry.get_sample_value("rule_action_duration_seconds_count", place) == 2
    assert registry.get_sample_value("rule_action_duration_seconds_sum", place) == pytest.approx(
        0.003
    )
    assert counted.blocked() == {"unavailable": 1}


def test_the_blocked_metric_never_counts_a_result_without_a_reason() -> None:
    """A `skipped` result after a stop names no `blocked_by` and is never counted in it;
    `mode_changed` is, as are the tick's own refusals, each once: `backpressure` (also a `blocked`
    result by type) and `scope` (no fire, so no result: the blocked metric only, 20 §12.1)."""
    counted = Counted()
    ids = {**_IDS, "node_id": "a1", "action_type": "flatten_position"}
    counted.metrics.result(skipped_result(**ids))
    assert counted.blocked() == {} and counted.of("rule_actions_total") == {
        ("skipped", "flatten_position"): 1
    }
    counted.metrics.result(skipped_result(**ids, reason="mode_changed"))
    counted.metrics.refused("flatten_position", "backpressure")
    counted.metrics.refused("flatten_position", "scope")
    assert counted.blocked() == {"mode_changed": 1, "backpressure": 1, "scope": 1}
    assert counted.of("rule_actions_total")[("blocked", "flatten_position")] == 1


def test_the_executor_series_are_live_with_closed_labels() -> None:
    specs = {s.name: s for s in CATALOGUE}
    expected = {
        "rule_actions_total": (("type", "result"), 150),
        "rule_action_duration_seconds": (("type",), 25),
        "rule_actions_blocked_total": (("reason",), 16),
        "rule_dispatch_reread_failed_total": (("reason",), 2),
        "rule_records_shed_total": (("kind",), 2),
    }  # fmt: skip
    for name, (labels, max_series) in expected.items():
        assert (specs[name].status, specs[name].labels, specs[name].max_series) == (
            "live", labels, max_series,
        )  # fmt: skip
    facade = Metrics("demo")
    register_r0(facade)  # the app registers the live catalogue: the same declarations, no clash
    metrics = ExecutorMetrics(facade)
    before = facade.total_series()
    outside: Any = "outside"  # typed loosely: a value outside each closed set is the subject
    cases: tuple[Callable[[], None], ...] = (
        lambda: metrics.result(_result("a1", "teleport", "ok")),
        lambda: metrics.reread_failed(outside),
        lambda: metrics.shed(outside),
        lambda: metrics.refused("place_order", outside),
    )
    for bad in cases:
        with pytest.raises(ValueError, match="closed set"):
            bad()
    assert facade.total_series() == before  # no series was touched
    ExecutorMetrics().result(_result("a1", "place_order", "ok"))  # unbound: counts nothing
    metrics.reread_failed("timeout")
    metrics.shed("refused_fire")
    reread = {"env": "demo", "reason": "timeout"}
    assert facade.registry.get_sample_value("rule_dispatch_reread_failed_total", reread) == 1
