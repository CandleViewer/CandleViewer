"""#3415 (SR-029, E09-S03): the `AuthRevocationLatencyHigh` ticket and its `absent()` guard.

`infra/prometheus/tests/system_alerts.test.yml` (promtool, run by CI) proves when the rule fires and
how long it is held. These pins tie it to the catalogued series, Alertmanager's routes and the
runbook, which promtool does not read (`test_auth_backstop_alert_rules.py`). No PromQL is evaluated.
"""

from __future__ import annotations

import re

from candleviewer.observability.metrics_catalogue import CATALOGUE
from tests.unit.observability.test_auth_backstop_alert_rules import (
    _quiet_hours_minutes,
    _route_for,
    _rule,
    _runbook_section,
)

_SERIES = "auth_revocation_latency_seconds"
_TICKET = "AuthRevocationLatencyHigh"


def test_the_ticket_reads_the_p99_of_the_catalogued_series_above_its_5_s_bucket_edge() -> None:
    """A p99 above 5 s is decided exactly only while 5 s is a bucket edge of the series."""
    rule, spec = _rule(_TICKET), next(s for s in CATALOGUE if s.name == _SERIES)

    assert rule["expr"] == (
        f"histogram_quantile(0.99, sum by (env, le) (rate({_SERIES}_bucket[15m]))) > 5"
    )
    assert rule["for"] == "0m" and spec.buckets is not None and 5.0 in spec.buckets


def test_the_ticket_is_an_auth_ticket_held_past_the_quiet_hours_mute() -> None:
    rule = _rule(_TICKET)
    hold = re.fullmatch(r"(\d+)h(\d+)m", rule["keep_firing_for"])
    route = _route_for({**rule["labels"], "alertname": _TICKET, "env": "live"})

    assert rule["labels"] == {"severity": "ticket", "component": "auth"}
    assert hold and int(hold[1]) * 60 + int(hold[2]) > _quiet_hours_minutes()
    assert route["receiver"] == "ticket" and route["mute_time_intervals"] == ["quiet_hours"]


def test_the_runbook_names_the_series_and_an_absent_guard_watches_it() -> None:
    section = _runbook_section(_rule(_TICKET))
    guard = _rule("ExpectedMetricMissingAuthRevocationLatencySecondsBucket")

    assert "Ticket." in section and "keep_firing_for" in section and _SERIES in section
    assert (guard["expr"], guard["labels"]["severity"]) == (f"absent({_SERIES}_bucket)", "ticket")
