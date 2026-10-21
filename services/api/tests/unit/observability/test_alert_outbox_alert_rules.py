"""#1016 (E40-T04): the `AlertOutboxBacklog` and `AlertOutboxDeadLettered` tickets.

`infra/prometheus/tests/system_alerts.test.yml` (promtool, run by CI) proves when each fires, how
long the second is held and what stays silent. These pins tie the rules to the series the
catalogue declares and the app wires, and to what promtool does not read: Alertmanager's routes,
the 07 section 9 entries and their log lines, the drill matrix. No PromQL is evaluated.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from prometheus_client import generate_latest

from candleviewer.alerts import dispatcher
from candleviewer.alerts.outbox import TOPIC_ALERT_DELIVER
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.settings import Settings
from tests.unit.observability.test_auth_backstop_alert_rules import (
    _quiet_hours_minutes,
    _route_for,
    _rule,
    _runbook_section,
)

_ROOT = Path(__file__).resolve().parents[5]
_GUARDS = _ROOT / "infra" / "prometheus" / "alerts" / "metric_guards.yml"
_PROMTOOL = _ROOT / "infra" / "prometheus" / "tests" / "system_alerts.test.yml"
_MATRIX = _ROOT / "qa" / "plans" / "e04-alert-drill-matrix.md"
_BACKLOG, _DEAD = "AlertOutboxBacklog", "AlertOutboxDeadLettered"
TICKETS = (_BACKLOG, _DEAD)
_DEPTH_SERIES, _DEAD_SERIES = "cv_outbox_depth", "cv_outbox_dead_total"
#: What each runbook entry tells the reader to look for: the dispatcher's log events.
LOG_LINES = {
    _BACKLOG: ("alert_dispatch_poll_failed", "alert_dispatch_failed", "alert_outbox_depth_failed"),
    _DEAD: ("alert_adapter_error", "alert_dispatch_failed"),
}


def test_the_backlog_ticket_reads_the_alert_deliver_depth_over_100_for_5_minutes() -> None:
    rule = _rule(_BACKLOG)
    assert rule["expr"] == f'max by (env) ({_DEPTH_SERIES}{{topic="{TOPIC_ALERT_DELIVER}"}}) > 100'
    assert rule["for"] == "5m"
    assert "keep_firing_for" not in rule  # a condition, as PublicWsDown: no hold after it clears


def test_the_dead_letter_ticket_reads_any_increase_and_is_held_past_the_mute() -> None:
    """An event, and Alertmanager never sends a ticket that fires and resolves inside the quiet
    hours, so it is held past them as the WS any-event tickets are."""
    rule = _rule(_DEAD)
    read = f'increase({_DEAD_SERIES}{{topic="{TOPIC_ALERT_DELIVER}"}}[15m])'
    assert rule["expr"] == f"sum by (env) ({read}) > 0"
    hold = re.fullmatch(r"(\d+)h(\d+)m", rule["keep_firing_for"])
    assert rule["for"] == "0m"
    assert hold and int(hold[1]) * 60 + int(hold[2]) > _quiet_hours_minutes() >= 9 * 60


@pytest.mark.parametrize("name", TICKETS)
def test_each_is_a_ticket_of_the_alerts_component_routed_muted_in_quiet_hours(name: str) -> None:
    """The alert record is already committed and an alert never places an order, so the next
    working session is soon enough (07-release-and-prr.md section 9)."""
    rule = _rule(name)
    assert rule["labels"] == {"severity": "ticket", "component": "alerts"}
    assert set(rule["annotations"]) == {"summary", "runbook_url"}
    route = _route_for({**rule["labels"], "alertname": name, "env": "live"})
    assert route["receiver"] == "ticket" and route["mute_time_intervals"] == ["quiet_hours"]


@pytest.mark.parametrize("name", TICKETS)
def test_each_links_a_runbook_entry_that_names_the_logs_the_dispatcher_writes(name: str) -> None:
    rule, anchor = _rule(name), f"alert-{name.lower()}"
    assert rule["annotations"]["runbook_url"] == f"docs/plan/07-release-and-prr.md#{anchor}"
    section = _runbook_section(rule)
    assert section.startswith(f'<a id="{anchor}"></a>\n\n### {name}\n')
    assert "Ticket" in section and ("keep_firing_for" in section) == (name == _DEAD)
    source = Path(dispatcher.__file__).read_text(encoding="utf-8")
    for line in LOG_LINES[name]:
        assert line in section and f'"{line}"' in source, line


def test_the_series_are_catalogued_and_the_catalogue_names_each_ticket() -> None:
    by_name = {s.name: s for s in CATALOGUE}
    for series, kind, name in [
        (_DEPTH_SERIES, "gauge", _BACKLOG),
        (_DEAD_SERIES, "counter", _DEAD),
    ]:
        spec = by_name[series]
        assert (spec.kind, spec.labels, spec.owner_epic) == (kind, ("topic",), "E40")
        assert name in spec.alert, series


def test_the_dispatcher_wiring_registers_what_the_catalogue_declares_and_binds_both_at_zero() -> (
    None
):
    """A series created by its first dead row gives `increase()` nothing to subtract, and the
    gauge is read before its first sample: `create_app` builds the dispatcher with both bound."""
    from candleviewer.app import _alert_dispatcher

    facade = Metrics("dev")
    _alert_dispatcher(None, facade, False)  # type: ignore[arg-type]  # pg is lazy
    text = generate_latest(facade.registry).decode()
    for spec in (s for s in CATALOGUE if s.name in {_DEPTH_SERIES, _DEAD_SERIES}):
        declared = facade._decls[spec.name]
        assert (declared.kind, declared.labels, declared.max_series) == (
            spec.kind, spec.labels, spec.max_series
        ), spec.name  # fmt: skip
        assert f'{spec.name}{{env="dev",topic="{TOPIC_ALERT_DELIVER}"}} 0.0' in text, spec.name


def test_no_absent_guard_stands_while_the_dispatcher_is_off_by_default() -> None:
    """Both series exist only where `alerts_evaluator_enabled` builds the dispatcher (C-4.13), so
    a guard would fire for good wherever it is off. When that default flips, add them."""
    doc = yaml.safe_load(_GUARDS.read_text(encoding="utf-8"))
    guarded = {r["expr"] for g in doc["groups"] for r in g["rules"]}
    assert Settings().alerts_evaluator_enabled is False
    assert not {f"absent({_DEPTH_SERIES})", f"absent({_DEAD_SERIES})"} & guarded


def test_promtool_has_a_firing_and_a_silent_case_for_each_ticket_and_the_edges() -> None:
    doc = yaml.safe_load(_PROMTOOL.read_text(encoding="utf-8"))
    checks: list[dict[str, Any]] = [c for t in doc["tests"] for c in t["alert_rule_test"]]
    seen = {(c["alertname"], c["eval_time"], bool(c["exp_alerts"])) for c in checks}
    assert {(n, fires) for n, _, fires in seen if n in TICKETS} == {
        (name, fires) for name in TICKETS for fires in (True, False)
    }
    assert {(_BACKLOG, "4m", False), (_BACKLOG, "6m", True)} <= seen  # the 5 m `for`
    assert (_BACKLOG, "20m", False) in seen  # a cleared backlog is not held
    assert {(_DEAD, "9h49m", True), (_DEAD, "9h52m", False), (_DEAD, "30m", False)} <= seen


def test_the_drill_matrix_has_a_row_for_each_ticket_with_its_runbook_and_hold() -> None:
    matrix = _MATRIX.read_text(encoding="utf-8")
    for name, hold in ((_BACKLOG, "5m"), (_DEAD, "0m")):
        runbook = f"docs/plan/07-release-and-prr.md#alert-{name.lower()}"
        assert re.search(rf"^\| {name} \| ticket \| {hold} \| `{runbook}` \|", matrix, re.M), name
