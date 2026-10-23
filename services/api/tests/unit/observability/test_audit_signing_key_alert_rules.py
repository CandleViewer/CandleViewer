"""#889 S6b-2: the audit export signing key's page and its boot-step ticket (ADR-0039 decision 2;
S6a-2's security F1). promtool (CI) proves when each fires; these pin what it cannot: expression,
hold, labels, the series M2 exports, the guards, the routes and the runbook."""

from __future__ import annotations

import yaml

from candleviewer.secrets import _metrics as m
from candleviewer.secrets.metrics import EXPORTED_NAMES
from tests.unit.observability.test_auth_backstop_alert_rules import (
    _ALERTS,
    _route_for,
    _rule,
    _runbook_section,
)

_GAUGE = "cv_audit_signing_key_unavailable_state"
_COUNTER = "cv_audit_signing_key_boot_failures_total"


def _filed_under(component: str) -> list[str]:
    return [
        rule["alert"]
        for path in sorted(_ALERTS.glob("*.yml"))
        for group in yaml.safe_load(path.read_text(encoding="utf-8"))["groups"]
        for rule in group["rules"]
        if "alert" in rule and rule["labels"]["component"] == component
    ]


def test_the_page_reads_the_gauge_m2_exports_and_its_guard() -> None:
    rule = _rule("AuditSigningKeyUnavailable")
    assert (rule["expr"], rule["for"]) == (f"max by (env) ({_GAUGE}) == 1", "0m")
    assert rule["labels"] == {"severity": "page", "component": "audit_signing"}
    assert _GAUGE in EXPORTED_NAMES
    guard = _rule("ExpectedMetricMissingCvAuditSigningKeyUnavailableState")
    assert (guard["expr"], guard["for"]) == (f"absent({_GAUGE})", "15m")
    assert _route_for(rule["labels"] | {"env": "live"})["receiver"] == "page"
    assert "KekUnavailable" in _runbook_section(rule)  # the page it is not


def test_the_page_is_alone_in_its_component_so_it_hides_no_ticket() -> None:
    """The page-over-ticket rule hides a ticket while a page of its component and env fires, and
    this page may stand for days with trading up (ADR-0039 Q4): no ticket shares its component,
    so the `secrets` tickets (a credential failure, a support bundle's secret, the boot step)
    stay visible."""
    assert _filed_under("audit_signing") == ["AuditSigningKeyUnavailable"]
    assert "AuditSigningKeyBootStepFailed" in _filed_under("secrets")


def test_the_ticket_reads_each_step_m2_binds_and_is_held_past_the_mute() -> None:
    rule = _rule("AuditSigningKeyBootStepFailed")
    assert rule["expr"] == f"sum by (env, step) (increase({_COUNTER}[15m])) > 0"
    held = (rule["for"], rule["keep_firing_for"], rule["labels"]["severity"])
    assert held == ("0m", "9h30m", "ticket")
    bound = {labels for labels in m.export_key_boot_failures_total._metrics}  # bound at import
    assert bound == {("destroy",), ("rewrap",)} and _COUNTER in EXPORTED_NAMES
    assert "secrets.export_key_boot_step_failed" in _runbook_section(rule)


def test_the_ticket_routes_as_a_ticket_muted_in_quiet_hours_and_its_counter_is_guarded() -> None:
    rule = _rule("AuditSigningKeyBootStepFailed")
    route = _route_for({**rule["labels"], "alertname": rule["alert"], "env": "live"})
    assert route["receiver"] == "ticket" and route["mute_time_intervals"] == ["quiet_hours"]
    guard = _rule("ExpectedMetricMissingCvAuditSigningKeyBootFailuresTotal")
    assert (guard["expr"], guard["for"]) == (f"absent({_COUNTER})", "15m")
    assert guard["labels"]["severity"] == "ticket"
