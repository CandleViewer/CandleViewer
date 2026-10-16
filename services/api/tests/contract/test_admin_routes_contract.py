"""Contract (E42-T01): `GET /admin/overview` and `GET /admin/capacity` over HTTP. The RBAC
matrix of the issue (owner 200, manager 403 plus an audit record, viewer 403, unauthenticated
401) with the whole audit record, responses that validate against the contract schema and
round-trip through the generated models, no secret in any response (security notes), and the
fan-out metrics on the real app's `/metrics` (observability)."""

from __future__ import annotations

from typing import Any

import jsonschema
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.observability.redaction import redact_structure
from tests.contract.rbac.rbac_harness import bearer, build_world
from tests.unit.admin._admin_fakes import expected_record
from tests.unit.admin._route_fakes import GB, NOW, Ports, make_app

_SPEC: Any = load_openapi_spec()  # a parsed YAML document, walked untyped
_PATHS = ["/admin/overview", "/admin/capacity"]


def _deref(node: Any) -> Any:
    if isinstance(node, dict):
        if "$ref" in node:
            return _deref(_SPEC["components"]["schemas"][node["$ref"].rsplit("/", 1)[1]])
        return {k: _deref(v) for k, v in node.items() if k != "examples"}
    return [_deref(v) for v in node] if isinstance(node, list) else node


def _schema(path: str) -> Any:
    ok = _SPEC["paths"][path]["get"]["responses"]["200"]
    return _deref(ok["content"]["application/json"]["schema"])


@pytest.mark.parametrize("path", _PATHS, ids=["overview", "capacity"])
@pytest.mark.parametrize(
    ("role", "status", "code"),
    [
        ("owner", 200, None),
        ("manager", 403, "forbidden"),
        ("viewer", 403, "forbidden"),
        ("", 401, "unauthenticated"),
    ],
    ids=["owner", "manager", "viewer", "unauthenticated"],
)
def test_rbac_cell(path: str, role: str, status: int, code: str | None) -> None:
    app, spy = make_app()
    response = TestClient(app).get(path, headers={"x-role": role})
    assert response.status_code == status
    # The whole record, written before the handler or the refusal (write-ahead); none for 401.
    assert spy.records == ([] if status == 401 else [expected_record(role, path)])
    if code is not None:
        assert response.headers["content-type"] == "application/problem+json"
        assert response.json()["code"] == code


@pytest.mark.parametrize(
    ("path", "model"),
    [("/admin/overview", api.AdminOverview), ("/admin/capacity", api.CapacityReport)],
    ids=["overview", "capacity"],
)
def test_the_response_validates_against_the_contract(path: str, model: type[BaseModel]) -> None:
    body = TestClient(make_app()[0]).get(path, headers={"x-role": "owner"}).json()
    jsonschema.validate(body, _schema(path))
    assert model.model_validate(body).model_dump(mode="json", exclude_unset=True) == body
    slices = {k: v for k, v in body.items() if isinstance(v, dict)}
    assert {v["status"] for v in slices.values()} == {"ok"}  # every source answered


_AT = "2026-10-16T00:30:00Z"  # `NOW`, the clock the golden below injects
_OK = {"status": "ok", "generated_at": _AT}
_BTC = {"symbol": "BTCUSDT", "used_bytes": 30 * GB, "daily_growth_bytes": GB, "pinned": True}
_HEALTHY = {
    "/admin/overview": {
        "generated_at": _AT,
        "users": _OK | {"total": 4, "active": 4, "without_mfa": 0},
        "accounts": _OK | {"total": 4, "enabled": 3, "keys_expiring_30d": 1, "keys_invalid": 0},
        "recorder": _OK | {"symbols_recording": 3, "symbols_degraded": 0, "lag_seconds_p99": 0.042},
        "storage": _OK | {"used_bytes": 41 * GB, "free_bytes": 400 * GB, "days_until_full": 187.5},
        "trading": _OK | {"live_enabled": False, "kill_switch_engaged": False, "open_positions": 0},
        "incidents": _OK | {"open": 0},
        "incidents_open": 0,
    },
    "/admin/capacity": {
        "generated_at": _AT,
        "storage": _OK
        | {
            "used_bytes": 41 * GB,
            "free_bytes": 400 * GB,
            "daily_growth_bytes": GB,
            "days_until_full": 400.0,  # 400 GB of headroom at 1 GB a day, retention unbounded
            "per_symbol": [_BTC | {"retention_days": None}],
            "projection_basis": "measured",
            "estimated": False,
        },
        "ingestion": _OK | {"messages_per_sec": 1840.5, "queue_depth": 12, "dropped_last_hour": 0},
        "rate_budget": [
            {
                "exchange_account_id": "00000000-0000-0000-0000-000000000001",
                "label": "main",
                "limit_per_minute": 600,
                "peak_used_per_minute": 450,
                "utilisation_pct": 75.0,
            }
        ],
        "rate_budget_status": _OK,
        "subaccounts": _OK
        | {"tier": "regular", "cap": 5, "used": 3, "tier_source": "recorded", "recorded_at": _AT},
    },
}


@pytest.mark.parametrize("path", _PATHS, ids=["overview", "capacity"])
def test_the_healthy_response_carries_exactly_what_every_source_reported(path: str) -> None:
    response = TestClient(make_app(now=lambda: NOW)[0]).get(path, headers={"x-role": "owner"})
    assert response.json() == _HEALTHY[path]  # the fakes' numbers, slice by slice


@pytest.mark.parametrize("path", _PATHS, ids=["overview", "capacity"])
def test_a_source_timing_out_still_answers_200_within_the_contract(path: str) -> None:
    body = TestClient(make_app(Ports(hang=True))[0]).get(path, headers={"x-role": "owner"}).json()
    jsonschema.validate(body, _schema(path))
    storage = body["storage"]
    assert (storage["status"], storage["detail"]) == ("error", "timed out after 300 ms")
    assert set(storage) == {"status", "detail", "generated_at"}  # unread fields omitted


#: Built by concatenation (as tests/security does) so no scanner sees a credential literal.
_LEAK = "postgresql://cv:" + "hunter2" + "@db/cv api_key=" + "Zq9" + "x" * 20 + "AbCd"


class Leaky(Ports):
    """Every port read fails, with a connection string and a key-shaped value in its message."""

    def __getattribute__(self, name: str) -> Any:
        if name.startswith("__"):
            return object.__getattribute__(self, name)

        async def fail(*_: Any) -> Any:
            raise RuntimeError(_LEAK)

        return fail


@pytest.mark.parametrize("path", _PATHS, ids=["overview", "capacity"])
def test_no_secret_reaches_the_response_when_every_source_leaks_one(path: str) -> None:
    response = TestClient(make_app(Leaky())[0]).get(path, headers={"x-role": "owner"})
    body = response.json()
    assert response.status_code == 200
    assert {v["status"] for v in body.values() if isinstance(v, dict)} == {"error"}  # all failed
    assert not [leak for leak in ("hunter2", "Zq9x", "postgresql") if leak in response.text]
    assert redact_structure(body) == body  # the shared redaction rule set finds nothing
    jsonschema.validate(body, _schema(path))


def test_the_real_app_serves_the_fan_out_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    world = build_world(monkeypatch)  # the RBAC pack's real `create_app` (identity faked)
    assert world.client.get("/admin/overview", headers=bearer("owner")).status_code == 200
    metrics = world.client.get("/metrics").text
    assert 'cv_admin_overview_source_duration_seconds_count{env="demo",source="users"}' in metrics
