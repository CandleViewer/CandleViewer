"""The rule action executor's metrics (E35-T09; `20-architecture.md` §12.1, BQ-8 of #5000).

`rule_actions_total{type,result}`, `rule_action_duration_seconds{type}`,
`rule_actions_blocked_total{reason}`, `rule_dispatch_reread_failed_total{reason}`,
`rule_records_shed_total{kind}`, and, since E35-T10, `rule_circuit_breaker_trips_total` and
`rule_autodisarm_total`, registered from their catalogue entries over the app's metrics
facade (idempotent: `register_r0` declares the same). Every label is checked against its closed set
before any series is touched, so no value outside it ever makes a series; no label names a rule,
an account, a user or a value. Unbound (no facade), it counts nothing, as the sinks discard.
"""

from __future__ import annotations

from typing import Final, Literal, get_args

from candleviewer.observability.metrics import BoundedMetric, Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.rules.executor.results import BLOCKED_BY, OUTCOMES, ActionResult, BlockedBy
from candleviewer.rules.ir.models import ActionType

#: Why check 1's read failed (`rule_dispatch_reread_failed_total{reason}`).
RereadFailure = Literal["timeout", "store_error"]
#: The record-only job the full audit queue shed (`rule_records_shed_total{kind}`).
ShedKind = Literal["refused_fire", "scope_denial"]
_TYPES: Final = frozenset(get_args(ActionType))
#: The refusals of a fire whole off the tick, each action counted as a `blocked` result where it
#: is refused: a full queue's (`backpressure`), and a fire dropped from its rule's lane by the
#: circuit breaker or the kill-switch hook (E35-T10).
_WHOLE: Final = frozenset({"backpressure", "circuit_breaker", "kill_switch"})
_SERIES: Final = (
    "rule_actions_total", "rule_action_duration_seconds", "rule_actions_blocked_total",
    "rule_dispatch_reread_failed_total", "rule_records_shed_total",
    "rule_circuit_breaker_trips_total", "rule_autodisarm_total",
)  # fmt: skip


def _closed(value: str, allowed: frozenset[str] | tuple[str, ...], label: str) -> str:
    if value not in allowed:
        raise ValueError(f"{label} outside its closed set")  # never echoes the value
    return value


class ExecutorMetrics:
    """The executor's series; `None` for the facade counts nothing."""

    def __init__(self, metrics: Metrics | None = None) -> None:
        self._series: dict[str, BoundedMetric] = {}
        if metrics is None:
            return
        specs = {spec.name: spec for spec in CATALOGUE if spec.name in _SERIES}
        for name in _SERIES:
            spec = specs[name]
            if spec.kind == "histogram" and spec.buckets is not None:  # as `register_r0` does
                self._series[name] = metrics.histogram(
                    name, spec.help, spec.labels, buckets=spec.buckets, max_series=spec.max_series
                )
            else:
                self._series[name] = metrics.counter(
                    name, spec.help, spec.labels, max_series=spec.max_series
                )

    def result(self, result: ActionResult) -> None:
        """One action's result: by type and outcome, its duration unless it is `skipped` (never
        attempted, so never timed), and its `blocked_by` (24 §11.9), which a `skipped` result
        after a stop never has."""
        action_type = _closed(result.action_type, _TYPES, "type")
        outcome = _closed(result.outcome, OUTCOMES, "result")
        reason = (
            None if result.blocked_by is None else _closed(result.blocked_by, BLOCKED_BY, "reason")
        )
        if not self._series:
            return
        self._series["rule_actions_total"].labels(action_type, outcome).inc()
        if outcome != "skipped":
            seconds = result.duration_us / 1_000_000
            self._series["rule_action_duration_seconds"].labels(action_type).observe(seconds)
        if reason is not None:
            self._series["rule_actions_blocked_total"].labels(reason).inc()

    def refused(self, action_type: str, reason: BlockedBy) -> None:
        """An action refused before it had a result of its own: a fire the full queue refused or
        one dropped from its lane (`_WHOLE`, counted as a `blocked` result too), or an action the
        tick's scope gate refused (`scope`: no fire, so no result; 20 §12.1)."""
        checked = _closed(reason, BLOCKED_BY, "reason")
        if reason in _WHOLE:
            counted = _closed(action_type, _TYPES, "type")
            if self._series:
                self._series["rule_actions_total"].labels(counted, "blocked").inc()
        if self._series:
            self._series["rule_actions_blocked_total"].labels(checked).inc()

    def reread_failed(self, reason: RereadFailure) -> None:
        checked = _closed(reason, get_args(RereadFailure), "reason")
        if self._series:
            self._series["rule_dispatch_reread_failed_total"].labels(checked).inc()

    def shed(self, kind: ShedKind) -> None:
        checked = _closed(kind, get_args(ShedKind), "kind")
        if self._series:
            self._series["rule_records_shed_total"].labels(checked).inc()

    def tripped(self) -> None:
        """One trip of a rule's circuit breaker (24 §11.7): every trip, never deduplicated."""
        if self._series:
            self._series["rule_circuit_breaker_trips_total"].child().inc()

    def autodisarmed(self) -> None:
        """One rule disarmed after repeated scope or permission refusals (24 §11.5, BQ-10)."""
        if self._series:
            self._series["rule_autodisarm_total"].child().inc()
