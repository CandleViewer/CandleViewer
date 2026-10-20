"""#3635 (with #3497; SR-029): the `WsRevocationCloseFailed` ticket and its `absent()` guard.

`infra/prometheus/tests/system_alerts.test.yml` (promtool, run by CI) proves when the rule fires and
how long it is held. These pins tie the rule to the counter the code declares and serves, to
Alertmanager's routes, the 07 section 9 entry and the drill matrix, which promtool does not read
(`test_auth_backstop_alert_rules.py`). No PromQL is evaluated.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from candleviewer.auth.metrics import AUTH_EXPORTED_NAMES
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.ws.revocation import ws_revocation_close_failures_total
from tests.unit.observability.test_auth_backstop_alert_rules import (
    _quiet_hours_minutes,
    _route_for,
    _rule,
    _runbook_section,
)

_ROOT = Path(__file__).resolve().parents[5]
_PRR = _ROOT / "docs" / "plan" / "07-release-and-prr.md"
_PROMTOOL = _ROOT / "infra" / "prometheus" / "tests" / "system_alerts.test.yml"
_MATRIX = _ROOT / "qa" / "plans" / "e04-alert-drill-matrix.md"
_COUNTER = "ws_session_revocation_close_failures_total"
_TICKET = "WsRevocationCloseFailed"
_GUARD = "ExpectedMetricMissingWsSessionRevocationCloseFailuresTotal"
_ANCHOR = "alert-wsrevocationclosefailed"


def test_the_ticket_reads_the_counter_and_fires_on_any_increase_in_fifteen_minutes() -> None:
    rule = _rule(_TICKET)

    assert rule["expr"] == f"sum by (env) (increase({_COUNTER}[15m])) > 0"
    assert rule["for"] == "0m"


def test_the_alert_is_a_ticket_of_the_auth_component_not_a_page() -> None:
    """REST refuses the session (or the disabled user) from the revocation on and orders are REST
    only, so the next working session is soon enough (07-release-and-prr.md section 9)."""
    rule = _rule(_TICKET)

    assert rule["labels"] == {"severity": "ticket", "component": "auth"}
    assert set(rule["annotations"]) == {"summary", "runbook_url"}
    assert rule["annotations"]["runbook_url"] == f"docs/plan/07-release-and-prr.md#{_ANCHOR}"


def test_the_ticket_is_held_firing_for_longer_than_the_quiet_hours_mute() -> None:
    """Alertmanager never sends a ticket that fires and resolves inside the mute, so the rule is
    held firing past it (`keep_firing_for`), as `AuthDisabledUserSessionRevoked` is."""
    hold = re.fullmatch(r"(\d+)h(\d+)m", _rule(_TICKET)["keep_firing_for"])

    assert hold and int(hold[1]) * 60 + int(hold[2]) > _quiet_hours_minutes() >= 9 * 60


def test_the_ticket_is_routed_to_the_ticket_receiver_muted_in_quiet_hours() -> None:
    rule = _rule(_TICKET)

    route = _route_for({**rule["labels"], "alertname": _TICKET, "env": "live"})

    assert route["receiver"] == "ticket" and route["mute_time_intervals"] == ["quiet_hours"]


def test_the_runbook_section_says_the_ticket_is_held_and_names_the_series_and_the_log() -> None:
    rule = _rule(_TICKET)

    assert f'<a id="{_ANCHOR}"></a>' in _PRR.read_text(encoding="utf-8"), "07 section 9 entry"
    section = _runbook_section(rule)
    assert section.startswith(f'<a id="{_ANCHOR}"></a>\n\n### {_TICKET}\n')
    assert "Ticket." in section and "keep_firing_for" in section
    assert _COUNTER in section and "ws revocation close failed" in section


def test_the_counter_has_an_absent_guard_that_is_a_ticket() -> None:
    """The counter is unlabelled and declared at import, so it reads 0 from process start: the
    guard stays quiet on a healthy idle system and fires only when the series is unscraped."""
    guard = _rule(_GUARD)

    assert guard["expr"] == f"absent({_COUNTER})"
    assert guard["for"] == "15m"
    assert guard["labels"] == {"severity": "ticket", "component": "alerting"}
    assert guard["annotations"]["runbook_url"] == (
        "docs/plan/07-release-and-prr.md#alert-expectedmetricmissing"
    )


def test_the_rule_reads_an_unlabelled_counter_that_the_code_declares_and_serves() -> None:
    """A rename of the counter without the rule would leave the ticket reading nothing, and only
    the guard, 15 minutes on, would say so. Unlabelled: it has a sample from import, so the first
    failure after a restart is an increase, and the scraped series carries `env` alone."""
    samples = [
        sample
        for family in ws_revocation_close_failures_total.collect()
        for sample in family.samples
        if sample.name == _COUNTER
    ]

    assert [sample.labels for sample in samples] == [{}]
    assert _COUNTER in AUTH_EXPORTED_NAMES


def test_the_catalogue_entry_of_the_counter_names_the_ticket() -> None:
    spec = next(s for s in CATALOGUE if s.name == _COUNTER)

    assert (spec.kind, spec.status, spec.exported, spec.labels) == ("counter", "live", True, ())
    assert _TICKET in spec.alert


def test_promtool_has_a_firing_a_held_a_resolved_and_a_silent_case_on_the_counter() -> None:
    doc = yaml.safe_load(_PROMTOOL.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = [
        test
        for test in doc["tests"]
        if any(check["alertname"] == _TICKET for check in test["alert_rule_test"])
    ]
    checks = [check for test in cases for check in test["alert_rule_test"]]
    seen = {(check["eval_time"], bool(check["exp_alerts"])) for check in checks}
    series = [s["series"] for test in cases for s in test["input_series"]]

    assert {("6m", True), ("9h49m", True), ("9h52m", False)} <= seen  # fired, held, resolved
    assert any(not fires and at != "9h52m" for at, fires in seen)  # a flat count is silent
    assert series and all(s.startswith(f"{_COUNTER}{{") for s in series)


def test_the_drill_matrix_has_a_row_for_the_ticket_with_its_runbook_and_its_hold() -> None:
    row = re.search(
        rf"^\| {_TICKET} \| ticket \| 0m \| `docs/plan/07-release-and-prr.md#{_ANCHOR}` \|.*$",
        _MATRIX.read_text(encoding="utf-8"),
        re.MULTILINE,
    )

    assert row is not None and "keep_firing_for" in row[0]
