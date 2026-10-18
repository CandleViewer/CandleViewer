"""#965 R7 and #2648 R7: the `UserLifecycleStepFailed` and `UserGrantsPushFailed` tickets and the
`absent()` guard of their series. Promtool (`infra/prometheus/tests/system_alerts.test.yml`, run by
CI) proves when each fires and how long it is held; these pins tie the rules to the closed sets of
`admin/lifecycle_metrics.py` and to the route, runbook, drill row and catalogue. No PromQL runs.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from candleviewer.admin.lifecycle_metrics import STEP_OUTCOMES
from candleviewer.observability.metrics_catalogue import CATALOGUE
from tests.unit.observability.test_auth_backstop_alert_rules import (
    _quiet_hours_minutes,
    _route_for,
    _rule,
    _runbook_section,
)

_ROOT = Path(__file__).resolve().parents[5]
_PROMTOOL = _ROOT / "infra" / "prometheus" / "tests" / "system_alerts.test.yml"
_MATRIX = _ROOT / "qa" / "plans" / "e04-alert-drill-matrix.md"
_SERIES, _PUSH = "cv_user_lifecycle_steps_total", "grants_push"
_GUARD = "ExpectedMetricMissingCvUserLifecycleStepsTotal"
#: Each ticket's share of the closed sets: every failed cascade step and closing record for one,
#: the push that failed or timed out for the other; no pair is read by both.
ADMITS = {
    "UserLifecycleStepFailed": {(step, "failed") for step in STEP_OUTCOMES if step != _PUSH},
    "UserGrantsPushFailed": {(_PUSH, "failed"), (_PUSH, "timeout")},
}
LOG_LINE = {"UserLifecycleStepFailed": "users.disable.step", "UserGrantsPushFailed": "access push"}
_SELECTOR = re.compile(rf"sum by \(env\) \(increase\({_SERIES}\{{(.*)\}}\[15m\]\)\) > 0")
_MATCHER = re.compile(r'(step|outcome)(=~|!=|=)"([^"]*)"')
#: The runbook's read for a night event once a Prometheus restart has dropped the hold (element 7).
_NIGHT = re.compile(rf"increase\({_SERIES}\{{([^}}]*)\}}\[10h\]\)")


def _pairs(selector: str) -> set[tuple[str, str]]:
    """The (step, outcome) pairs of the closed sets that a selector's matchers admit."""
    matchers = _MATCHER.findall(selector)
    assert ",".join(f'{k}{op}"{v}"' for k, op, v in matchers) == selector  # nothing else

    def holds(op: str, pattern: str, value: str) -> bool:
        if op == "=~":
            return re.fullmatch(pattern, value) is not None
        return (value == pattern) == (op == "=")

    return {
        (step, outcome)
        for step, outcomes in STEP_OUTCOMES.items()
        for outcome in outcomes
        if all(holds(op, v, {"step": step, "outcome": outcome}[k]) for k, op, v in matchers)
    }


def _admitted(expr: str) -> set[tuple[str, str]]:
    """The pairs that a rule's selector admits."""
    selector = _SELECTOR.fullmatch(expr)
    assert selector is not None, expr
    return _pairs(selector[1])


@pytest.mark.parametrize("name", ADMITS)
def test_the_ticket_reads_exactly_its_share_of_the_closed_sets(name: str) -> None:
    assert _admitted(_rule(name)["expr"]) == ADMITS[name]


@pytest.mark.parametrize("name", ADMITS)
def test_the_runbooks_night_event_read_admits_what_the_ticket_reads(name: str) -> None:
    """Element 7's read stands in for the rule once the hold is gone, so it reads the rule's
    share: a failed grants push never reads as a failed cascade step. (A Markdown table cell
    escapes the `|` of a regex matcher.)"""
    (night,) = _NIGHT.findall(_runbook_section(_rule(name)))
    assert _pairs(night.replace("\\|", "|")) == ADMITS[name]


@pytest.mark.parametrize("name", ADMITS)
def test_the_ticket_fires_at_once_is_held_past_the_mute_and_routes_as_a_ticket(name: str) -> None:
    """The committed change stands and fails closed (O5; the deny-all load), so a ticket of its
    own component; Alertmanager never sends one that fires and resolves inside the quiet-hours
    mute, so each is held past it, as the WS any-event tickets are."""
    rule = _rule(name)
    hold = re.fullmatch(r"(\d+)h(\d+)m", rule["keep_firing_for"])
    assert rule["for"] == "0m"
    assert hold and int(hold[1]) * 60 + int(hold[2]) > _quiet_hours_minutes() >= 9 * 60
    assert rule["labels"] == {"severity": "ticket", "component": "user_lifecycle"}
    route = _route_for({**rule["labels"], "alertname": name, "env": "live"})
    assert route["receiver"] == "ticket" and route["mute_time_intervals"] == ["quiet_hours"]


@pytest.mark.parametrize("name", ADMITS)
def test_the_ticket_links_a_runbook_entry_that_says_it_is_held_and_names_the_log_line(
    name: str,
) -> None:
    rule = _rule(name)
    anchor = f"alert-{name.lower()}"
    assert rule["annotations"]["runbook_url"] == f"docs/plan/07-release-and-prr.md#{anchor}"
    section = _runbook_section(rule)
    assert section.startswith(f'<a id="{anchor}"></a>\n\n### {name}\n')
    assert "Ticket" in section and "keep_firing_for" in section and LOG_LINE[name] in section


def test_the_series_has_an_absent_guard_that_is_a_ticket() -> None:
    """Every value is bound at import, so the guard stays quiet on a healthy idle system and
    fires only when the series is unscraped."""
    guard = _rule(_GUARD)
    assert (guard["expr"], guard["for"]) == (f"absent({_SERIES})", "15m")
    assert guard["labels"]["severity"] == "ticket"


def test_promtool_has_a_firing_and_a_silent_case_for_each_ticket() -> None:
    doc = yaml.safe_load(_PROMTOOL.read_text(encoding="utf-8"))
    checks: list[dict[str, Any]] = [c for t in doc["tests"] for c in t["alert_rule_test"]]
    seen = {(c["alertname"], bool(c["exp_alerts"])) for c in checks if c["alertname"] in ADMITS}
    assert seen == {(name, fires) for name in ADMITS for fires in (True, False)}


def test_the_drill_matrix_and_the_catalogue_name_each_ticket() -> None:
    matrix = _MATRIX.read_text(encoding="utf-8")
    (spec,) = [s for s in CATALOGUE if s.name == _SERIES]
    for name in ADMITS:
        assert re.search(rf"^\| {name} \| ticket \| 0m \|", matrix, re.M), name
        assert name in spec.alert, name
