"""Contract (E42-T01): the real `create_app` serves the recorder's `DiskBudget` in the `storage`
slice of `GET /admin/overview` and `GET /admin/capacity`, and only there. The budget is the one
`create_app` composes (`app.state.disk_budget`, built by the patched `build_disk_budget` seam of
the RBAC pack's world: identity and backend faked, no network), a real `DiskBudget` over a fake
meter and clock. With no budget, which is the fake backend's case, the slice is `unavailable`;
a stale sample is `unavailable` too. Every body validates against the contract schema and the
generated model."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Any

import jsonschema
import pytest
from pydantic import BaseModel

import candleviewer.app as appmod
from candleviewer.admin_wiring import build_admin_read_models
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.recorder.budget import DiskBudget
from tests.contract.rbac.rbac_harness import bearer, build_world
from tests.unit.admin._disk_fakes import AT, BTC, SIZE, clock, sampled
from tests.unit.recorder._budget_fakes import CAP, GB, TOTAL

_SPEC: Any = load_openapi_spec()
_SCHEMAS = {"/admin/overview": "AdminOverview", "/admin/capacity": "CapacityReport"}
_MODELS: dict[str, type[BaseModel]] = {
    "/admin/overview": api.AdminOverview,
    "/admin/capacity": api.CapacityReport,
}


def _get(
    mp: pytest.MonkeyPatch,
    path: str,
    budget: DiskBudget | None,
    now: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    now = now or clock()
    if budget is not None:  # the fake backend composes none: only then is the seam patched
        mp.setattr(appmod, "build_disk_budget", lambda *_args, **_kwargs: budget)
    # the admin clock is injected, never the wall clock
    mp.setattr(
        appmod,
        "build_admin_read_models",
        lambda cfg, **kw: build_admin_read_models(cfg, now=now, **kw),
    )
    response = build_world(mp).client.get(path, headers=bearer("owner"))
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    ref = {"$ref": f"#/components/schemas/{_SCHEMAS[path]}", "components": _SPEC["components"]}
    jsonschema.validate(body, ref)
    assert _MODELS[path].model_validate(body).model_dump(mode="json", exclude_unset=True) == body
    return body


def test_the_real_app_reports_the_disk_budget_in_the_capacity_storage_slice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    budget = asyncio.run(sampled(measured=True, pinned=frozenset({BTC})))
    storage = _get(monkeypatch, "/admin/capacity", budget)["storage"]
    _, rates = budget.measured_growth()
    assert storage["status"] == "ok" and "detail" not in storage
    assert (storage["used_bytes"], storage["free_bytes"]) == (SIZE, TOTAL // 2)
    assert (storage["projection_basis"], storage["estimated"]) == ("measured", False)
    assert storage["per_symbol"] == [
        {
            "symbol": BTC,
            "used_bytes": SIZE,
            "daily_growth_bytes": rates[BTC],
            "pinned": True,
            "retention_days": None,
        }
    ]
    assert storage["days_until_full"] == round((TOTAL // 2) / rates[BTC], 2)


def test_the_real_app_reports_the_disk_budget_in_the_overview_storage_tile_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _get(monkeypatch, "/admin/overview", asyncio.run(sampled(used=50 * GB)))
    storage = body["storage"]
    assert storage["status"] == "ok"
    assert (storage["used_bytes"], storage["free_bytes"]) == (50 * GB, TOTAL // 2)
    assert storage["days_until_full"] is None  # growth is not measured: the estimate is not shown
    assert (body["recorder"]["status"], body["recorder"]["detail"]) == (
        "unavailable",
        "recorder: no provider wired",  # symbols_recording = 0 would be a guess
    )


@pytest.mark.parametrize("path", ["/admin/overview", "/admin/capacity"])
def test_the_real_app_without_a_disk_budget_has_no_storage_figures(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    storage = _get(monkeypatch, path, None)["storage"]  # the fake backend: no `disk_budget`
    assert storage == {
        "status": "unavailable",
        "detail": "storage: no provider wired",
        "generated_at": AT.strftime("%Y-%m-%dT%H:%M:%SZ"),  # the injected admin clock
    }


@pytest.mark.parametrize("path", ["/admin/overview", "/admin/capacity"])
def test_the_real_app_shows_no_headroom_from_a_stale_sample(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    budget = asyncio.run(sampled(used=CAP, free=0))  # a full disk, sampled over 3 intervals ago
    storage = _get(monkeypatch, path, budget, now=clock(181.0))["storage"]
    assert (storage["status"], storage["detail"]) == (
        "unavailable",
        "storage: disk sample is stale",
    )
    assert set(storage) == {"status", "detail", "generated_at"}  # no stale used / free / days
