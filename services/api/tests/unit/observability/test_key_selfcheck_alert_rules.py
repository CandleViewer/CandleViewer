"""#836 slice 2c2: the key self-check's pages and SR-034 tickets. promtool (CI) proves when each
fires; these pin what it cannot: expression, hold, labels, series, guards, routes and runbook."""

from __future__ import annotations

import re

import pytest

from candleviewer.observability.metrics_catalogue import CATALOGUE
from tests.unit.observability.test_auth_backstop_alert_rules import (
    _route_for,
    _rule,
    _runbook_section,
)

_MIN = "min by (env) (cv_key_soonest_expiry_seconds)"
_LATCHED = "max by (env) (cv_key_selfcheck_latch_state) > 0"
_FAILING = "max by (env) (cv_keys_failing_policy) > 0"
_PAGE, _TICKET = ("0m", "page"), ("10m", "ticket")
_LATCH, _EXP = "keyselfchecklatched", "keyexpiring"
#: alert -> (expression, `for`, severity, runbook anchor).
RULES = {
    "KeySelfCheckFailed": (
        "max by (env, rule) (cv_keys_failing_policy) > 0", *_PAGE, "keyselfcheckfailed"
    ),
    "KeySelfCheckLatched": (f"{_LATCHED} unless on (env) {_FAILING}", *_PAGE, _LATCH),
    "KeySelfCheckRunMissed": (
        "sum by (env) (increase(cv_key_selfcheck_missed_runs_total[2h])) > 0", *_PAGE, _LATCH
    ),
    "KeyExpiringWithin14Days": (f"{_MIN} < 14 * 86400 and {_MIN} >= 7 * 86400", *_TICKET, _EXP),
    "KeyExpiringWithin7Days": (f"{_MIN} < 7 * 86400 and {_MIN} >= 86400", *_TICKET, _EXP),
    "KeyExpiringWithin1Day": (f"{_MIN} < 86400 and {_MIN} > 0", *_TICKET, _EXP),
}  # fmt: skip
_COMPONENT = {"page": "key_selfcheck", "ticket": "key_expiry"}


@pytest.mark.parametrize("name", RULES)
def test_each_rule_has_its_expression_hold_labels_route_and_runbook(name: str) -> None:
    expr, hold, severity, anchor = RULES[name]
    rule = _rule(name)
    assert (rule["expr"], rule["for"]) == (expr, hold)
    assert rule["labels"] == {"severity": severity, "component": _COMPONENT[severity]}
    route = _route_for({**rule["labels"], "alertname": name, "env": "live"})
    assert (route["receiver"], "mute_time_intervals" in route) == (severity, severity == "ticket")
    assert rule["annotations"]["runbook_url"] == f"docs/plan/07-release-and-prr.md#alert-{anchor}"
    assert name in _runbook_section(rule)


@pytest.mark.parametrize("name", RULES)
def test_each_rule_reads_live_key_series_and_each_page_series_has_an_absent_guard(
    name: str,
) -> None:
    expr, _hold, severity, _anchor = RULES[name]
    read = set(re.findall(r"\bcv_keys?_\w+", expr))
    assert read and read <= {s.name for s in CATALOGUE if s.status == "live"}
    for series in read if severity == "page" else ():
        guard = _rule("ExpectedMetricMissing" + "".join(w.title() for w in series.split("_")))
        assert (guard["expr"], guard["for"]) == (f"absent({series})", "15m")
