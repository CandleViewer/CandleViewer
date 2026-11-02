"""Contract (E08-T10, #5111): `POST /instruments/refresh` (`refreshInstruments`) on the real
`create_app` (the RBAC pack's world, a scheduler stand-in on `ctx.ingestion.instruments`).

The `202` validates against 22's schema and its job is the app's one job store's, polled through
`getJob` as `kind: instrument_refresh` (Q4); the request is recorded ahead
(`instruments.refresh.requested`, Q3); every other caller is refused with nothing started; a
write without the SR-041 pair is `403 csrf_token_invalid`; the Owner without the `instruments`
step-up gets `403 step_up_required` naming that class (the ruling of 2026-10-31); and the
operation's contract text names the class the registry gates it with.
"""

from __future__ import annotations

from typing import Any

import jsonschema
import pytest

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.step_up import HANDLER_GATED_ROUTES
from tests.contract.rbac.rbac_harness import World, bearer, build_world

_SPEC: Any = load_openapi_spec()
_OP: dict[str, Any] = _SPEC["paths"]["/instruments/refresh"]["post"]
_PATH = "/instruments/refresh"


class _Refresher:
    """The scheduler's narrow face (`CatalogueRefresher`): running, and never reaching a venue."""

    stopped = False

    def __init__(self) -> None:
        self.calls = 0

    async def refresh_now(self) -> None:
        self.calls += 1


def _world(mp: pytest.MonkeyPatch) -> tuple[World, _Refresher]:
    world = build_world(mp)
    refresher = _Refresher()
    world.app.state.app_context.ingestion.instruments = refresher
    return world, refresher


def _requested(world: World) -> list[dict[str, Any]]:
    return [r for r in world.audit.records if r["action"] == "instruments.refresh.requested"]


def test_the_owner_is_answered_202_with_a_job_the_poll_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world, _refresher = _world(monkeypatch)
    response = world.client.post(_PATH, headers=bearer("owner"))
    assert response.status_code == 202
    schema = _OP["responses"]["202"]["content"]["application/json"]["schema"]
    jsonschema.validate(response.json(), schema, format_checker=jsonschema.FormatChecker())
    job_id = response.json()["job_id"]
    assert world.app.state.admin_jobs.get(job_id).kind == "instrument_refresh"
    polled = world.client.get(f"/admin/jobs/{job_id}", headers=bearer("owner"))
    assert (polled.status_code, polled.json()["kind"]) == (200, "instrument_refresh")
    (record,) = _requested(world)
    assert (record["object_kind"], record["object_id"]) == ("instrument_refresh", job_id)
    assert record["after_state"]["joined"] is False


@pytest.mark.parametrize(
    ("actor", "status", "code"),
    [
        ("manager_with_grant", 403, "forbidden"),
        ("manager_without_grant", 403, "forbidden"),
        ("viewer", 403, "forbidden"),
        # SR-041: an unsafe call with no session is refused by the CSRF guard before any route
        # runs; the route's own 401 is pinned by the unit test (`test_instruments_refresh_route`)
        ("unauthenticated", 403, "csrf_token_invalid"),
    ],
)
def test_every_other_caller_is_refused_and_nothing_starts(
    monkeypatch: pytest.MonkeyPatch, actor: str, status: int, code: str
) -> None:
    world, refresher = _world(monkeypatch)
    response = world.client.post(_PATH, headers=bearer(actor))
    assert (response.status_code, response.json()["code"]) == (status, code)
    assert world.app.state.admin_jobs.held() == 0 and refresher.calls == 0
    assert _requested(world) == []


def test_a_write_without_the_csrf_pair_is_refused_before_the_route_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world, refresher = _world(monkeypatch)
    headers = {"Authorization": bearer("owner")["Authorization"]}  # a bearer is no exemption
    response = world.client.post(_PATH, headers=headers)
    assert (response.status_code, response.json()["code"]) == (403, "csrf_token_invalid")
    assert world.app.state.admin_jobs.held() == 0 and refresher.calls == 0
    assert _requested(world) == []


def test_the_owner_without_the_instruments_step_up_is_challenged_and_nothing_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world, refresher = _world(monkeypatch)
    world.step_up.classes = frozenset({"recorder"})  # elevated, but not for this class
    response = world.client.post(_PATH, headers=bearer("owner"))
    assert response.status_code == 403
    assert (response.json()["code"], response.json()["action_class"]) == (
        "step_up_required",
        "instruments",
    )
    assert world.app.state.admin_jobs.held() == 0 and refresher.calls == 0
    assert _requested(world) == []


def test_the_contract_names_the_class_the_registry_gates_with() -> None:
    text = " ".join(_OP["description"].split())
    assert "`403 step_up_required` with `action_class` set to `instruments`" in text
    assert ("POST", _PATH, "instruments") in HANDLER_GATED_ROUTES
    assert _OP["x-rbac"] == {"permissions": ["instruments:write"], "scope": "none"}
    step_up = _SPEC["paths"]["/auth/step-up"]["post"]["requestBody"]["content"]
    assert (
        "instruments" in step_up["application/json"]["schema"]["properties"]["action_class"]["enum"]
    )
