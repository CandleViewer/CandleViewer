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
    export_auth_metrics,
    normalise_permission,
)
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.settings import Environment, Settings

SECURITY_SERIES = ("auth_lockouts_total", "authz_denied_total", "auth_stepup_failures_total")
_SPECS = {spec.name: spec for spec in CATALOGUE}


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
