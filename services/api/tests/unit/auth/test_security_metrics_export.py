"""SR-125 (#2117): `auth_lockouts_total`, `authz_denied_total` and `auth_stepup_failures_total`
are catalogued `live`, served on the scraped registry with `env`, present from process start
(the `ExpectedMetricMissing*` guards are `absent(<name>)` rules) and label-bounded.

E09-X02 observability gaps (#2319): the session, invite and login-failure series that used to move
only on the process-default registry are served the same way."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from prometheus_client import REGISTRY, CollectorRegistry, generate_latest
from prometheus_client.parser import text_string_to_metric_families

from candleviewer.app import create_app
from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.metrics import (
    AUTH_EXPORTED_NAMES,
    LOGIN_FAILURE_METHODS,
    export_auth_metrics,
    normalise_permission,
)
from candleviewer.auth.models import MfaMethodKind
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.settings import Environment, Settings

SECURITY_SERIES = ("auth_lockouts_total", "authz_denied_total", "auth_stepup_failures_total")
#: #2319: series now served on the scraped registry, with their catalogue labels.
OBSERVABILITY_SERIES = {
    "auth_login_failures_total": ("method",),
    "auth_refresh_reuse_total": (),
    "auth_session_revocations_total": ("reason",),
    "auth_readonly_downgrades_total": (),
    "users_invites_rejected_total": ("reason",),
    "auth_session_revoke_denied_total": (),
}
_SPECS = {spec.name: spec for spec in CATALOGUE}
_API_ROOT = Path(__file__).resolve().parents[3]
_FRESH_PROCESS_PROBE = """
import json
from prometheus_client import REGISTRY
from candleviewer.auth.metrics import LOGIN_FAILURE_METHODS
read = REGISTRY.get_sample_value
series = {m: read("auth_login_failures_total", {"method": m}) for m in LOGIN_FAILURE_METHODS}
print(json.dumps(series))
"""


def test_catalogue_declares_the_three_security_series_live_and_exported() -> None:
    for name in SECURITY_SERIES:
        spec = _SPECS[name]
        assert (spec.kind, spec.status, spec.exported) == ("counter", "live", True), name
        assert name in AUTH_EXPORTED_NAMES, name
    assert _SPECS["authz_denied_total"].labels == ("permission",)
    assert _SPECS["auth_lockouts_total"].labels == ()
    assert _SPECS["auth_stepup_failures_total"].labels == ()


def test_catalogue_bound_for_authz_denied_covers_the_permission_vocabulary_and_other() -> None:
    assert len(Permission) + 1 <= _SPECS["authz_denied_total"].max_series


def test_normalise_permission_passes_the_vocabulary_through() -> None:
    assert {normalise_permission(p) for p in Permission} == {p.value for p in Permission}


def test_normalise_permission_clamps_everything_else_to_other() -> None:
    for hostile in ("", "users:write ", "USERS:WRITE", "x" * 500, "users:*", "../etc/passwd"):
        assert normalise_permission(hostile) == "other", hostile


def test_every_permission_series_exists_before_the_first_denial() -> None:
    for value in (*(p.value for p in Permission), "other"):
        sample = REGISTRY.get_sample_value("authz_denied_total", {"permission": value})
        assert sample is not None, value


def test_label_less_series_exist_before_the_first_event() -> None:
    assert REGISTRY.get_sample_value("auth_lockouts_total") is not None
    assert REGISTRY.get_sample_value("auth_stepup_failures_total") is not None


def test_export_serves_the_three_series_with_the_env_label() -> None:
    metrics = Metrics("demo")
    collector = export_auth_metrics(metrics.registry, env="demo")
    try:
        text = generate_latest(metrics.registry).decode()
    finally:
        collector.close()
    families = {f.name: f for f in text_string_to_metric_families(text)}
    for name in SECURITY_SERIES:
        family = families[name.removesuffix("_total")]
        assert family.samples, name
        assert all(s.labels["env"] == "demo" for s in family.samples), name
        assert f"# HELP {name} " in text, name
    assert 'authz_denied_total{env="demo",permission="users:write"} ' in text
    assert 'authz_denied_total{env="demo",permission="other"} ' in text
    assert 'auth_lockouts_total{env="demo"} ' in text


def test_create_app_serves_the_three_series_on_the_scraped_registry() -> None:
    app = create_app(Settings(environment=Environment.DEMO))
    text = generate_latest(app.state.app_context.metrics).decode()
    for name in SECURITY_SERIES:
        samples = [ln for ln in text.splitlines() if ln.startswith(f"{name}{{")]
        assert samples and all('env="demo"' in ln for ln in samples), name


def test_create_app_serves_the_observability_series_on_the_scraped_registry() -> None:
    app = create_app(Settings(environment=Environment.DEMO))
    text = generate_latest(app.state.app_context.metrics).decode()
    for name in OBSERVABILITY_SERIES:
        assert f"# HELP {name} " in text, name


def test_catalogue_declares_the_observability_series_live_and_exported() -> None:
    for name, labels in OBSERVABILITY_SERIES.items():
        spec = _SPECS[name]
        assert (spec.kind, spec.status, spec.exported) == ("counter", "live", True), name
        assert (spec.labels, name in AUTH_EXPORTED_NAMES) == (labels, True), name
    assert len(LOGIN_FAILURE_METHODS) <= _SPECS["auth_login_failures_total"].max_series


def test_login_failure_methods_are_the_password_factor_and_every_mfa_method() -> None:
    assert set(LOGIN_FAILURE_METHODS) == {"password", *(m.value for m in MfaMethodKind)}


def test_every_login_failure_method_is_a_zero_in_a_process_that_has_seen_no_failure() -> None:
    # `ExpectedMetricMissingAuthLoginFailuresTotal` is `absent(auth_login_failures_total)`, and the
    # first failure must be a visible 0 -> 1. In this process other tests have already bound the
    # series, so they are read in a fresh interpreter (hermetic: only the package root on the path).
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["PYTHONPATH"] = str(_API_ROOT)
    probe = subprocess.run(  # noqa: S603 -- fixed argv, no shell (#2319)
        [sys.executable, "-c", _FRESH_PROCESS_PROBE],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=_API_ROOT,
        env=env,
        check=True,
    )
    series = json.loads(probe.stdout.strip().splitlines()[-1])
    assert series == {method: 0.0 for method in LOGIN_FAILURE_METHODS}


def test_export_serves_the_login_failure_methods_and_the_label_less_series_with_env() -> None:
    metrics = Metrics("demo")
    collector = export_auth_metrics(metrics.registry, env="demo")
    try:
        text = generate_latest(metrics.registry).decode()
    finally:
        collector.close()
    for method in LOGIN_FAILURE_METHODS:
        assert f'auth_login_failures_total{{env="demo",method="{method}"}} ' in text
    for name in ("auth_refresh_reuse_total", "auth_session_revoke_denied_total"):
        assert f'{name}{{env="demo"}} ' in text, name


def test_the_retired_step_up_counter_is_gone_and_its_catalogue_twin_remains() -> None:
    # #2319 item 1: `auth_step_up_failures_total{action_class}` duplicated the scraped
    # `auth_stepup_failures_total`; two near-identical names, one of them unscraped, is a trap.
    families = {family.name for family in REGISTRY.collect()}
    assert "auth_step_up_failures" not in families and "auth_stepup_failures" in families


def test_the_process_local_session_gauge_is_not_exported() -> None:
    # #2319 item 1, accepted decision: `auth_sessions_active` drifts (it never drops on expiry or
    # rotation, and a restarted process drives it negative), so it must not be scraped as truth.
    assert "auth_sessions_active" not in AUTH_EXPORTED_NAMES | _SPECS.keys()


#: The audit rows `/auth` writes beside an `auth_login_failures_total` increment. Each is proven to
#: move the counter, and `auth.account_locked` not to, in `unit/api/test_auth_login_failures.py`.
_COUNTED_ROWS = frozenset({"auth.login_failed", "auth.mfa_failed", "auth.recovery_codes_exhausted"})


def test_login_failures_catalogue_text_names_exactly_the_audit_rows_it_counts() -> None:
    # #2319 review: dashboard and alert authors read the catalogue, so it must say what the runbook
    # says (docs/ops/runbooks/auth-rbac.md): one per row the /auth routes write beside the
    # increment, `auth.recovery_codes_exhausted` included, and the WS gateway's own
    # `auth.login_failed` rows (`ws_auth_failed`) are `cv_ws_auth_failures_total`'s.
    text = _SPECS["auth_login_failures_total"].help
    assert {t for t in re.findall(r"[a-z_]+\.[a-z_]+", text) if t in AUDIT_ACTIONS} == _COUNTED_ROWS
    assert "cv_ws_auth_failures_total" in text and "cv_ws_auth_failures_total" in _SPECS


#: #3415 (SR-029, E09-S03): the one revoke-to-close latency series.
_LATENCY = "auth_revocation_latency_seconds"


def test_create_app_serves_the_revocation_latency_with_no_identifier_label() -> None:
    app = create_app(Settings(environment=Environment.DEMO))
    text = generate_latest(app.state.app_context.metrics).decode()
    family = {f.name: f for f in text_string_to_metric_families(text)}[_LATENCY]
    assert family.type == "histogram" and family.samples
    assert {label for sample in family.samples for label in sample.labels} == {"env", "le"}


async def test_a_disabled_users_socket_closed_by_the_deployed_hub_is_one_scraped_sample() -> None:
    """The AC: a user with an open socket is disabled, the deployed hub closes the socket, and
    the histogram on the scraped registry gains one observation."""
    app = create_app(Settings(environment=Environment.DEMO))
    scraped: CollectorRegistry = app.state.app_context.metrics
    closes: list[int] = []

    async def socket(frame: dict[str, object], code: int) -> None:
        closes.append(code)

    def observed() -> float | None:
        return scraped.get_sample_value(f"{_LATENCY}_count", {"env": "demo"})

    app.state.revocation_hub.register("s1", socket)
    before = observed()
    await app.state.revocation_hub.revoke("s1", "user_disabled")
    assert before is not None and (closes, observed()) == ([4403], before + 1)


def test_the_revoke_to_close_latency_has_one_name_catalogued_and_exported() -> None:
    # `create_app`'s module has imported the hub (`ws/revocation.py`), the series' one writer.
    assert "ws_session_revocation_close_seconds" not in {f.name for f in REGISTRY.collect()}
    spec = _SPECS[_LATENCY]
    assert (spec.kind, spec.labels, spec.status, spec.exported) == ("histogram", (), "live", True)
    assert _LATENCY in AUTH_EXPORTED_NAMES
    assert spec.buckets is not None and 5.0 in spec.buckets  # SR-029's line is a bucket edge
