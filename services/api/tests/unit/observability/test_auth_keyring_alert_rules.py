"""#2152 (BQ-14, BQ-4): the auth keyring's page and its boot-step ticket (ADR-0009 Amendment 4).
promtool (CI) proves when each fires; these pin what it cannot: expression, hold, labels, the
series M2 exports, the guards, the routes and the runbook, as the audit signing key's do."""

from __future__ import annotations

from candleviewer.secrets import _metrics as m
from candleviewer.secrets.metrics import EXPORTED_NAMES
from tests.unit.observability.test_audit_signing_key_alert_rules import _filed_under
from tests.unit.observability.test_auth_backstop_alert_rules import (
    _route_for,
    _rule,
    _runbook_section,
)

_GAUGE = "cv_auth_keyring_unavailable_state"
_COUNTER = "cv_auth_keyring_boot_failures_total"


def test_the_page_reads_the_gauge_m2_exports_and_its_guard() -> None:
    rule = _rule("AuthKeyringUnavailable")
    assert (rule["expr"], rule["for"]) == (f"max by (env) ({_GAUGE}) == 1", "0m")
    assert rule["labels"] == {"severity": "page", "component": "auth_keyring"}
    assert _GAUGE in EXPORTED_NAMES
    guard = _rule("ExpectedMetricMissingCvAuthKeyringUnavailableState")
    assert (guard["expr"], guard["for"]) == (f"absent({_GAUGE})", "15m")
    assert _route_for(rule["labels"] | {"env": "live"})["receiver"] == "page"
    section = _runbook_section(rule)
    assert "KekUnavailable" in section  # the page it is not
    assert "Never delete MFA material" in section  # BQ-9: never regenerate over material


def test_the_page_is_alone_in_its_component_so_it_hides_no_ticket() -> None:
    """MFA alone is down and trading is up, so the page may stand for long: no ticket shares its
    component, so the `secrets` tickets (the boot step included) stay visible."""
    assert _filed_under("auth_keyring") == ["AuthKeyringUnavailable"]
    assert "AuthKeyringBootStepFailed" in _filed_under("secrets")


def test_the_runbook_names_every_reason_m2_can_page_with() -> None:
    """Each reason the boot can leave MFA unavailable with has its step under the page's anchor."""
    section = _runbook_section(_rule("AuthKeyringUnavailable"))
    reasons = (
        "auth_keyring_missing",
        "auth_keyring_mismatch",
        "auth_keyring_stranded",
        "auth_keyring_store_unavailable",
        "auth_keyring_audit_unavailable",
        "auth_keyring_unopenable",
        "auth_key_not_held",
    )
    assert [r for r in reasons if f"`{r}`" not in section] == []


def test_the_ticket_reads_the_step_m2_binds_and_is_held_past_the_mute() -> None:
    rule = _rule("AuthKeyringBootStepFailed")
    assert rule["expr"] == f"sum by (env, step) (increase({_COUNTER}[15m])) > 0"
    held = (rule["for"], rule["keep_firing_for"], rule["labels"]["severity"])
    assert held == ("0m", "9h30m", "ticket")
    bound = {labels for labels in m.auth_keyring_boot_failures_total._metrics}  # bound at import
    assert bound == {("rewrap",)} and _COUNTER in EXPORTED_NAMES
    assert "secrets.auth_keyring_boot_step_failed" in _runbook_section(rule)


def test_the_ticket_routes_as_a_ticket_muted_in_quiet_hours_and_its_counter_is_guarded() -> None:
    rule = _rule("AuthKeyringBootStepFailed")
    route = _route_for({**rule["labels"], "alertname": rule["alert"], "env": "live"})
    assert route["receiver"] == "ticket" and route["mute_time_intervals"] == ["quiet_hours"]
    guard = _rule("ExpectedMetricMissingCvAuthKeyringBootFailuresTotal")
    assert (guard["expr"], guard["for"]) == (f"absent({_COUNTER})", "15m")
    assert guard["labels"]["severity"] == "ticket"
