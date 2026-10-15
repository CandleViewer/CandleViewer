"""E09-X02 observability per abuse case (#2144, #298 "Observability"): which audit row, which
metric and which alert each defended attack leaves, asserted in-process through the real
`create_app()` stack (fixed clock, in-memory fakes, no network).

`ALERTING` below is the catalogue's alert column (docs/security/abuse-cases/e09-auth.md,
"Observability per case"): change both together. "Scraped" means served on the app registry
Prometheus scrapes; a series that moves only on the process-default registry is invisible to
Prometheus, so no alert can ever see it. Asserted absences are recorded observations (gaps),
not desired behaviour: when one is closed, update this file and the catalogue together.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from prometheus_client import REGISTRY

from candleviewer.api.sessions import REFRESH_COOKIE
from candleviewer.auth.csrf import CSRF_COOKIE, CSRF_HEADER
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.login_service import LOCKOUT_THRESHOLD
from candleviewer.auth.mfa_service import CHALLENGE_ATTEMPT_CAP

from ._stack import INVITE_PW, PW, Stack

_ALERT_RULES = Path(__file__).resolve().parents[5] / "infra" / "prometheus" / "alerts"
_METRIC = re.compile(r"[a-z_][a-z0-9_]*")

#: metric -> the alert rules whose `expr` reads it. Empty: no alert can fire on that signal.
ALERTING: dict[str, set[str]] = {
    "auth_csrf_refused_total": {"CsrfRefusalsHigh", "CsrfRefusalAuditUnavailable"},
    "auth_session_fixation_attempts_total": set(),
    "auth_refresh_reuse_total": set(),
    "auth_step_up_failures_total": set(),
    "users_invites_rejected_total": set(),
    "cv_ws_auth_failures_total": set(),
    "cv_ws_closes_total": {"WsOriginRefusalsHigh"},  # only reason="origin_forbidden" (#2276)
    "cv_ws_revoked_total": set(),
    "cv_ws_subscribe_total": set(),
    # SR-125 metrics that are alerted but never emitted: only the absent() guard can fire.
    "auth_login_failures_total": {
        "AuthLoginFailureSpike",
        "ExpectedMetricMissingAuthLoginFailuresTotal",
    },
    "auth_lockouts_total": {"AuthLockouts", "ExpectedMetricMissingAuthLockoutsTotal"},
    "authz_denied_total": {"AuthzDeniedSpike", "ExpectedMetricMissingAuthzDeniedTotal"},
}


def in_process(name: str, **labels: str) -> float:
    """A sample on the process-default registry, where module-level series land unscraped."""
    return float(REGISTRY.get_sample_value(name, labels) or 0.0)


def _alerts_reading(metric: str) -> set[str]:
    found: set[str] = set()
    for path in sorted(_ALERT_RULES.glob("*.yml")):
        for group in yaml.safe_load(path.read_text(encoding="utf-8"))["groups"]:
            for rule in group["rules"]:
                if "alert" in rule and metric in _METRIC.findall(str(rule["expr"])):
                    found.add(str(rule["alert"]))
    return found


def test_obs_alert_rules_read_exactly_the_recorded_signals() -> None:
    assert {metric: _alerts_reading(metric) for metric in ALERTING} == ALERTING


def _value(field: Any, default: str) -> Any:
    return default if field is None else getattr(field, "value", field)


def _rows(stack: Stack, action: str) -> list[tuple[Any, Any, Any]]:
    """(reason, outcome, severity) per row, with the writer's defaults for omitted fields."""
    return [
        (r.get("reason"), _value(r.get("outcome"), "success"), _value(r.get("severity"), "info"))
        for r in stack.audit.of(action)
    ]


def test_obs_credential_stuffing_and_lockout_leave_audit_rows_but_no_metric(
    stack: Stack,
) -> None:  # AC-CRED-03/04/05, AC-ENUM-01/02
    stack.add_user("victim")
    wrong = {"identifier": "victim", "password": "wrong-guess-1"}
    tries = LOCKOUT_THRESHOLD + 1
    codes = [stack.client.post("/auth/login", json=wrong).status_code for _ in range(tries)]
    ghost = stack.client.post("/auth/login", json={"identifier": "ghost", "password": "x"})
    assert codes == [401] * LOCKOUT_THRESHOLD + [423] and ghost.status_code == 401
    assert _rows(stack, "auth.login_failed") == [(None, "failure", "info")] * tries  # uniform
    assert _rows(stack, "auth.account_locked") == [(None, "denied", "warning")]
    assert stack.scraped("auth_login_failures_total") == 0.0  # planned, never emitted
    assert stack.scraped("auth_lockouts_total") == 0.0


def test_obs_mfa_guessing_and_recovery_misuse_leave_mfa_failed_rows_only(stack: Stack) -> None:
    # AC-MFA-01..07
    _, seed = stack.add_user("victim")
    login = {"identifier": "victim", "password": PW}
    token = stack.client.post("/auth/login", json=login).json()["mfa_token"]
    valid = {stack.code(seed, step) for step in (-1, 0, 1)}
    guess = next(c for c in (f"{i:06d}" for i in range(10)) if c not in valid)
    for code in [guess] * CHALLENGE_ATTEMPT_CAP + [stack.code(seed)]:  # locked: even the real one
        body = {"mfa_token": token, "method": "totp", "code": code}
        assert stack.client.post("/auth/mfa/verify", json=body).status_code == 401
    recovery = {"mfa_token": token, "recovery_code": "zzzz-zzzz-zzzz"}
    assert stack.client.post("/auth/mfa/recovery", json=recovery).status_code == 401
    expected = [(None, "failure", "info")] * (CHALLENGE_ATTEMPT_CAP + 2)
    assert _rows(stack, "auth.mfa_failed") == expected
    assert stack.audit.of("auth.mfa_verified") == []


def test_obs_refresh_token_reuse_is_a_critical_row_and_its_metric_is_not_scraped(
    stack: Stack,
) -> None:  # AC-SES-03
    _, seed = stack.add_user("victim")
    signed_in = stack.sign_in("victim", seed)
    stolen = {"refresh_token": signed_in.cookies.get(REFRESH_COOKIE)}
    csrf = {CSRF_HEADER: str(signed_in.cookies.get(CSRF_COOKIE))}  # its cookie is in the jar
    reuse = in_process("auth_refresh_reuse_total")
    assert stack.client.post("/auth/refresh", headers=csrf, json=stolen).status_code == 200
    assert stack.client.post("/auth/refresh", json=stolen).status_code == 401  # the replay
    assert _rows(stack, "auth.refresh_reuse_detected") == [("rotation_reuse", "denied", "critical")]
    assert in_process("auth_refresh_reuse_total") - reuse == 1
    assert stack.scraped("auth_refresh_reuse_total") == 0.0  # not exported: no alert possible


def test_obs_csrf_refusals_are_audited_scraped_and_alertable_but_an_idor_probe_is_silent(
    stack: Stack,
) -> None:  # AC-CSRF-01/02/04/05 through the real middleware
    _, seed = stack.add_user("victim")
    victim = stack.sign_in("victim", seed)
    foreign = {
        "Cookie": f"{REFRESH_COOKIE}={victim.cookies.get(REFRESH_COOKIE)}",
        "Origin": "https://evil.example",
    }
    before = stack.scraped("auth_csrf_refused_total")
    stack.client.cookies.clear()
    assert stack.client.post("/auth/refresh", headers=foreign).status_code == 403
    assert stack.client.post("/auth/logout").status_code == 403  # cookie-only, no token pair
    assert _rows(stack, "auth.csrf_refused") == [
        ("cross_origin", "denied", "warning"),
        ("missing", "denied", "warning"),
    ]
    assert stack.scraped("auth_csrf_refused_total") - before == 2
    attacker, _ = stack.principal("mallory", "viewer")
    session_id = stack.call(
        stack.auth.sessions.authenticate_access_token, victim.json()["tokens"]["access_token"]
    ).id
    recorded = len(stack.audit.records)
    probe = stack.client.delete(f"/me/sessions/{session_id}", headers=attacker)
    assert probe.status_code == 404  # defended (victim session intact) ...
    assert len(stack.audit.records) == recorded  # ... but invisible: no row, no metric


def test_obs_rbac_denial_is_audited_but_its_planned_metric_is_never_emitted(
    stack: Stack,
) -> None:  # AC-AUTHZ-01/07 over HTTP (U19)
    manager, seed = stack.principal("manny", "manager")
    body = {"email": "x@example.com", "username": "xavier", "roles": ["viewer"]}
    assert stack.client.post("/users", headers=manager, json=body).status_code == 403
    assert stack.step_up(manager, seed).status_code == 200
    denied = stack.client.post("/users", headers=manager, json=body)
    assert (denied.status_code, denied.json()["code"]) == (403, "forbidden")
    ((reason, outcome, severity),) = _rows(stack, "rbac.denied")
    assert reason.startswith(f"{denied.json()['reason']}:users:write")  # names permission
    assert (outcome, severity) == ("denied", "warning")
    assert stack.scraped("authz_denied_total") == 0.0  # AuthzDeniedSpike can never fire


def test_obs_step_up_failure_is_audited_and_metered_but_not_scraped(stack: Stack) -> None:
    # AC-STEP-01..04 (U18)
    owner, _ = stack.principal("owner", "owner", Permission.USERS_WRITE)
    body = {"email": "x@example.com", "username": "xavier", "roles": ["viewer"]}
    assert stack.client.post("/users", headers=owner, json=body).status_code == 403
    before = in_process("auth_step_up_failures_total", action_class="users")
    wrong = {"code": "000000", "password": "wrong"}
    assert stack.client.post("/auth/step-up", headers=owner, json=wrong).status_code == 401
    ((reason, outcome, severity),) = _rows(stack, "auth.step_up_failed")
    assert reason.startswith("users:") and (outcome, severity) == ("failure", "error")
    assert in_process("auth_step_up_failures_total", action_class="users") - before == 1
    assert stack.scraped("auth_step_up_failures_total") == 0.0


def test_obs_invite_guessing_and_role_tamper_are_audited_metric_in_process_only(
    stack: Stack,
) -> None:  # AC-INV-01..04
    guessed = "g" * 43
    before = in_process("users_invites_rejected_total", reason="unknown")
    assert stack.client.get(f"/invites/{guessed}").status_code == 404
    tamper = {"password": INVITE_PW, "role": "owner"}
    assert stack.client.post(f"/invites/{guessed}", json=tamper).status_code == 403
    assert _rows(stack, "users.invite_rejected") == [
        ("unknown", "denied", "info"),
        ("role_tamper", "denied", "warning"),
    ]
    assert in_process("users_invites_rejected_total", reason="unknown") - before == 1
    assert stack.scraped("users_invites_rejected_total") == 0.0
