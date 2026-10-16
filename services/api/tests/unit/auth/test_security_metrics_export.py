"""SR-125 (#2117): `auth_lockouts_total`, `authz_denied_total` and `auth_stepup_failures_total`
are catalogued `live`, served on the scraped registry with `env`, present from process start
(the `ExpectedMetricMissing*` guards are `absent(<name>)` rules) and label-bounded."""

from __future__ import annotations

from prometheus_client import REGISTRY, generate_latest
from prometheus_client.parser import text_string_to_metric_families

from candleviewer.app import create_app
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.metrics import (
    AUTH_EXPORTED_NAMES,
    ENROLMENT_ONLY_ROLES,
    ENROLMENT_OUTCOMES,
    export_auth_metrics,
    normalise_permission,
    normalise_reason,
    normalise_role,
)
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.settings import Environment, Settings

SECURITY_SERIES = ("auth_lockouts_total", "authz_denied_total", "auth_stepup_failures_total")
_SPECS = {spec.name: spec for spec in CATALOGUE}
#: #2295 (U33 monitoring): each enrolment counter with its one label and closed value set.
_ENROLMENT_SERIES = {
    "auth_enrolment_only_sessions_total": ("role", ENROLMENT_ONLY_ROLES),
    "auth_enrolments_total": ("outcome", ENROLMENT_OUTCOMES),
}


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


def test_enrolment_series_are_catalogued_exported_and_bound_from_process_start() -> None:
    for name, (label, values) in _ENROLMENT_SERIES.items():
        spec = _SPECS[name]
        assert (spec.kind, spec.status, spec.exported) == ("counter", "live", True), name
        assert (spec.labels, spec.max_series) == ((label,), len(values)), name
        assert name in AUTH_EXPORTED_NAMES, name
        for value in values:
            assert REGISTRY.get_sample_value(name, {label: value}) is not None, (name, value)


def test_normalise_role_keeps_the_highest_system_role_and_clamps_the_rest() -> None:
    assert normalise_role(["viewer", "owner"]) == "owner"
    assert normalise_role(("viewer", "manager")) == "manager"
    assert normalise_role(["viewer"]) == "viewer"
    for hostile in ([], ["admin"], ["OWNER"], ["owner "], ["x" * 500]):
        assert normalise_role(hostile) == "other", hostile


def test_a_confirmed_enrolment_is_its_own_revocation_reason_not_other() -> None:
    assert normalise_reason("mfa_enrolled") == "mfa_enrolled"
