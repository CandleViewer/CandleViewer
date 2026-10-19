"""#837 (E27-T04): the `AccountDown` page and the `KeyRotationWarn` and `KeyRotationOverdue` tickets
(`infra/prometheus/alerts/accounts.yml`). Promtool (CI runs the generated
`infra/prometheus/tests/system_alerts.test.yml`) proves when each fires and how long it is held;
these pins tie each rule to what the code sets (the health pairs and the key-age notices that
`account_health_wiring` binds), to its `absent()` guard and to its route. No PromQL runs."""

from __future__ import annotations

import pytest

from candleviewer.account_health_wiring import HEALTH_SERIES, NOTICE_STATES
from candleviewer.accounts.health import HealthState
from candleviewer.accounts.key_age import RotationState
from tests.unit.observability.test_auth_backstop_alert_rules import _route_for, _rule

_GAUGE = 'cv_account_health_state{state="down",reason="no_success"}'
_MOVES = 'increase(cv_account_health_transitions_total{state="down"}[5m])'


def test_account_down_pages_an_account_that_was_up_and_never_one_that_never_connected() -> None:
    rule = _rule("AccountDown")
    assert rule["expr"] == f"max by (env) ({_GAUGE}) > 0 or sum by (env) ({_MOVES}) > 0"
    assert (HealthState.DOWN, "no_success") in HEALTH_SERIES  # the reason of a lapse into down
    assert (HealthState.DOWN, "never_connected") in HEALTH_SERIES  # read by no rule
    page = {"severity": "page", "component": "account_health"}
    assert (rule["for"], rule["labels"]) == ("0m", page)
    route = _route_for({**rule["labels"], "alertname": "AccountDown", "env": "live"})
    assert route["receiver"] == "page" and "mute_time_intervals" not in route


@pytest.mark.parametrize(
    ("name", "state"),
    [("KeyRotationWarn", RotationState.WARN), ("KeyRotationOverdue", RotationState.OVERDUE)],
)
def test_a_key_rotation_ticket_reads_its_notices_and_is_held_past_the_mute(
    name: str, state: RotationState
) -> None:
    rule = _rule(name)
    notices = f'cv_key_rotation_notices_total{{state="{state}"}}'
    assert state in NOTICE_STATES
    assert rule["expr"] == f"sum by (env) (increase({notices}[15m])) > 0"
    assert (rule["for"], rule["keep_firing_for"]) == ("0m", "9h30m")
    assert rule["labels"] == {"severity": "ticket", "component": "key_rotation"}
    route = _route_for({**rule["labels"], "alertname": name, "env": "live"})
    assert route["receiver"] == "ticket"


@pytest.mark.parametrize(
    "series",
    [
        "cv_account_health_state",
        "cv_account_health_transitions_total",
        "cv_key_rotation_notices_total",
    ],
)
def test_every_series_an_account_rule_reads_has_an_absent_guard(series: str) -> None:
    guard = "ExpectedMetricMissing" + "".join(part.title() for part in series.split("_"))
    rule = _rule(guard)
    assert (rule["expr"], rule["labels"]["severity"]) == (f"absent({series})", "ticket")
