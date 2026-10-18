"""#836 slice 2b4 composition guard: the deployed `create_app()` on the real backend serves
`createApiKey` with the import `wire_key_import` builds over the bundle's M2 candidate capability,
the one audit handle M2's sink writes through and the settings' egress IP and rotation windows,
and hands the lifespan that import's runtime to drain (`app.state.key_imports`). Slice 2b6 serves
`testApiKey` on the test `wire_key_test` builds over the self-check the boot assertion runs and that
import's reads. The fake backend serves both routes with neither. `create_app` does no I/O: no
store and no network is touched."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

import pytest
from pydantic import SecretStr

import candleviewer.app as appmod
from candleviewer.accounts.key_age import KeyRotationPolicy
from candleviewer.settings import Environment, Settings

EGRESS = "203.0.113.7"
_SPIED = ("_build_secrets", "wire_key_import", "make_exchange_keys_router", "wire_key_test")
Backend = Literal["fake", "real"]


def _settings(backend: Backend) -> Settings:
    windows: dict[str, Any] = {"CV_KEY_ROTATION_POLICY_DAYS": 60, "CV_KEY_ROTATION_WARN_DAYS": 7}
    return Settings(
        storage_backend=backend, environment=Environment.TESTNET, egress_ip=EGRESS,
        auth_pepper=SecretStr("test-pepper"), auth_totp_key_hex=SecretStr("11" * 32),
        auth_recovery_hmac_key_hex=SecretStr("22" * 32), auth_csrf_key_hex=SecretStr("33" * 32),
        **windows,  # not the default 90/14
    )  # fmt: skip


def _spy(seen: dict[str, Any], name: str, real: Callable[..., Any]) -> Callable[..., Any]:
    def call(*args: Any, **kwargs: Any) -> Any:
        seen[name] = (args, kwargs, out := real(*args, **kwargs))
        return out

    return call


def _deployed(mp: pytest.MonkeyPatch, backend: Backend) -> tuple[Any, dict[str, Any]]:
    """`create_app` with nothing injected; each spied call's arguments and result are kept."""
    seen: dict[str, Any] = {}
    for name in _SPIED:
        mp.setattr(appmod, name, _spy(seen, name, getattr(appmod, name)))
    return appmod.create_app(_settings(backend)), seen


def test_the_real_backend_serves_create_api_key_on_the_import_it_wires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, seen = _deployed(monkeypatch, "real")
    ctx = app.state.app_context
    (_, m2_audit), _, bundle = seen["_build_secrets"]
    (wired_on, keys, flow_audit), _, imports = seen["wire_key_import"]
    (served, route_audit, resolver), named, _ = seen["make_exchange_keys_router"]
    assert m2_audit is ctx.audit is flow_audit._audit is route_audit._audit  # one audit handle
    assert wired_on is ctx and keys is bundle.candidate_keys is imports.flow._candidates._keys
    assert served is imports is app.state.key_imports  # the lifespan drains what the route runs
    assert (named["egress_ip"], named["rotation"]) == (EGRESS, KeyRotationPolicy(60, 7))
    assert resolver is not None  # the owner resolver: a call is judged, never a 501
    (tested_on, job, reads_of), _, tests = seen["wire_key_test"]
    assert tested_on is ctx and job is ctx.accounts._selfcheck and reads_of is imports
    assert named["tests"] is tests is not None  # decision 11: the job that boots enforces a test


def test_the_fake_backend_serves_create_api_key_with_no_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, seen = _deployed(monkeypatch, "fake")
    assert seen["make_exchange_keys_router"][0][0] is None and app.state.key_imports is None
    assert seen["make_exchange_keys_router"][1]["tests"] is None
