"""#906 D3b (E28-T02): a profile save's measures. `FAILURE_RULES`, the refusal counter's closed
label set, is the union of B1's and B2's named rule sets and `schema` (C-16.5), the audited reasons
among them; `SaveMeasures.bound` binds every child of the three series once, before any save, so a
save binds none (the observability contract's rule 3)."""

from __future__ import annotations

from candleviewer.accounts.profile_input import FIRST_PASS_RULES, SCHEMA_RULES
from candleviewer.accounts.profile_validator import SECOND_PASS_RULES
from candleviewer.api.profile_writes import FAILURE_RULES, SAVE_RESULTS, SaveMeasures
from candleviewer.audit.actions import PROFILE_SAVE_REFUSED_REASONS
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import register_r0

_SERIES = (
    "cv_profile_saves_total",
    "cv_profile_validation_failures_total",
    "cv_profile_save_seconds",
)


def test_failure_rules_are_the_contracts_named_rules_and_schema() -> None:
    assert FAILURE_RULES == SCHEMA_RULES | FIRST_PASS_RULES | SECOND_PASS_RULES | {"schema"}
    assert len(FAILURE_RULES) == 18 and PROFILE_SAVE_REFUSED_REASONS < FAILURE_RULES
    assert len(SAVE_RESULTS) == len(set(SAVE_RESULTS)) == 6


def test_the_measures_bind_every_child_once_and_a_save_binds_none() -> None:
    metrics = Metrics("demo")
    register_r0(metrics)
    measures = SaveMeasures.bound(metrics, clock=lambda: 0.0)
    bound = [metrics.get(name).series_count for name in _SERIES]
    measures.record(422, ["int_type", "max_leverage", "max_leverage"], 0.5)
    measures.record(500, ["a defect"], 0.5)
    get = metrics.registry.get_sample_value
    assert (bound, [metrics.get(name).series_count for name in _SERIES]) == ([6, 18, 1],) * 2
    counted = [get(_SERIES[1], {"env": "demo", "rule": r}) for r in ("max_leverage", "schema")]
    assert (counted, get(f"{_SERIES[2]}_count", {"env": "demo"})) == ([1.0, 1.0], 1.0)
