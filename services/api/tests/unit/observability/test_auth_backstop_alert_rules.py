"""#3029 (SR-029, SR-125): the `AuthDisabledUserSessionRevoked` ticket and its `absent()` guard.

`infra/prometheus/tests/system_alerts.test.yml` (promtool, run by CI) proves when the rule fires,
how long it is held and that a flat counter stays silent. It cannot prove what the rule says about
itself: the generator reads each rule's labels, so a changed severity or component regenerates
clean, and nothing there reads Alertmanager's routes or the runbook. These pins live here, and not
beside the other alert pins in `infra/alertmanager/tests`, because the `py-tests` lanes collect
`services/api/tests` only. No PromQL is evaluated.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[5]
_ALERTS = _ROOT / "infra" / "prometheus" / "alerts"
_ALERTMANAGER = _ROOT / "infra" / "alertmanager" / "alertmanager.yml"
_COUNTER = "auth_disabled_user_sessions_revoked_total"
_TICKET = "AuthDisabledUserSessionRevoked"
_GUARD = "ExpectedMetricMissingAuthDisabledUserSessionsRevokedTotal"


def _rule(name: str) -> dict[str, Any]:
    for path in sorted(_ALERTS.glob("*.yml")):
        for group in yaml.safe_load(path.read_text(encoding="utf-8"))["groups"]:
            for rule in group["rules"]:
                if rule.get("alert") == name:
                    found: dict[str, Any] = rule
                    return found
    raise AssertionError(f"no alert rule named {name}")


def _alertmanager() -> dict[str, Any]:
    config: dict[str, Any] = yaml.safe_load(_ALERTMANAGER.read_text(encoding="utf-8"))
    return config


def _quiet_hours_minutes() -> int:
    """The time Alertmanager mutes tickets each day (the `quiet_hours` interval)."""
    (muted,) = (t for t in _alertmanager()["time_intervals"] if t["name"] == "quiet_hours")

    def minute(clock: str) -> int:
        hours, minutes = clock.split(":")
        return int(hours) * 60 + int(minutes)

    spans = [span for interval in muted["time_intervals"] for span in interval["times"]]
    return sum(minute(s["end_time"]) - minute(s["start_time"]) for s in spans)


def _route_for(labels: dict[str, str]) -> dict[str, Any]:
    """The child route Alertmanager picks for `labels`: the first whose matchers all hold (none
    sets `continue`), else the root route."""
    config = _alertmanager()
    for route in config["route"]["routes"]:
        assert not route.get("continue", False)
        pairs = [re.fullmatch(r'(\w+)\s*=\s*"([^"]*)"', m) for m in route["matchers"]]
        assert all(p is not None for p in pairs), route["matchers"]  # equality matchers only
        if all(p is not None and labels.get(p[1]) == p[2] for p in pairs):
            return dict(route)
    return dict(config["route"])


def _runbook_section(rule: dict[str, Any]) -> str:
    """The runbook text under a rule's `runbook_url` anchor, up to the next anchor."""
    path, _, anchor = rule["annotations"]["runbook_url"].partition("#")
    text: str = (_ROOT / path).read_text(encoding="utf-8")
    start = text.index(f'<a id="{anchor}"></a>')
    end = text.find('<a id="', start + 1)
    return text[start:] if end == -1 else text[start:end]


def test_the_ticket_reads_the_counter_and_fires_on_any_increase_in_fifteen_minutes() -> None:
    rule = _rule(_TICKET)

    assert rule["expr"] == f"sum by (env) (increase({_COUNTER}[15m])) > 0"
    assert rule["for"] == "0m"


def test_the_alert_is_a_ticket_of_the_auth_component_not_a_page() -> None:
    """The session is already revoked and its request refused when this fires, so the next
    working session is soon enough (07-release-and-prr.md section 9)."""
    assert _rule(_TICKET)["labels"] == {"severity": "ticket", "component": "auth"}


def test_the_ticket_is_held_firing_for_longer_than_the_quiet_hours_mute() -> None:
    """Alertmanager never sends a ticket that fires and resolves inside the mute, so the rule is
    held firing past it (`keep_firing_for`), as the WS any-event tickets are."""
    hold = re.fullmatch(r"(\d+)h(\d+)m", _rule(_TICKET)["keep_firing_for"])

    assert hold and int(hold[1]) * 60 + int(hold[2]) > _quiet_hours_minutes() >= 9 * 60


def test_the_ticket_is_routed_to_the_ticket_receiver_muted_in_quiet_hours() -> None:
    rule = _rule(_TICKET)

    route = _route_for({**rule["labels"], "alertname": _TICKET, "env": "live"})

    assert route["receiver"] == "ticket" and route["mute_time_intervals"] == ["quiet_hours"]


def test_the_ticket_links_a_runbook_section_that_says_it_is_held_and_names_the_log_line() -> None:
    rule = _rule(_TICKET)

    assert rule["annotations"]["runbook_url"] == (
        "docs/plan/07-release-and-prr.md#alert-authdisabledusersessionrevoked"
    )
    section = _runbook_section(rule)
    assert "Ticket." in section and "keep_firing_for" in section
    assert "auth.disabled_user_session_revoked" in section


def test_the_counter_has_an_absent_guard_that_is_a_ticket() -> None:
    """As `AuthRecoveryCodeUsed` has. The counter reads 0 from process start, so the guard stays
    quiet on a healthy idle system and fires only when the series is unscraped."""
    guard = _rule(_GUARD)

    assert guard["expr"] == f"absent({_COUNTER})"
    assert guard["for"] == "15m"
    assert guard["labels"]["severity"] == "ticket"
