"""Provider contract tests (E02-T13, #5181): `getSettings` and `updateSettings` over HTTP, through
the real `create_app()` (the RBAC pack's world: identity, sessions and the settings store faked,
no network, C-13.5). Every answer validates against the schema 22 declares for its status, the 200
bodies round-trip through the generated `Settings`, and the edge guards the routes rely on run for
real: CSRF on the write (SR-041), the view-as guard (#3085), RBAC per role, and `settings.change`
in the world's audit sink. `GET /me/preferences` answers what `GET /settings` answers.

`updateSettings` omits the shared `401` from its responses although its RBAC row (and the ticket)
answer an unauthenticated caller `401`: here CSRF refuses that write first (`403
csrf_token_invalid`, which the matrix reads as its `401`), and an expired bearer bound to a live
session reaches the route's `401` (`test_user_settings_router.py`). The gap is reported, not
changed: no contract change in E02-T13."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.auth.csrf import CSRF_HEADER
from tests.contract.rbac.rbac_harness import (
    ACTORS,
    World,
    bearer,
    bearer_viewing,
    build_world,
    session_id_of,
    user_id_of,
)
from tests.openapi_helpers import deref
from tests.unit.storage.fakes_user_settings import FakeUserSettings
from tests.unit.storage.user_settings_contract import noop

_SPEC: Any = load_openapi_spec()
_PATH = "/settings"
_ROLES = ACTORS[:4]
#: Every status the routes answer in this world, per operation (`updateSettings`' `401`: above).
_ANSWERED = {"get": {"200", "401", "403", "503"}, "patch": {"200", "403", "422", "503"}}


@pytest.fixture(scope="module")
def world() -> Iterator[World]:
    mp = pytest.MonkeyPatch()
    try:
        yield build_world(mp)
    finally:
        mp.undo()


@pytest.fixture
def store(world: World) -> FakeUserSettings:
    """A fresh store per test, so no override leaks from one test into the next."""
    fresh = FakeUserSettings()
    world.app.state.user_settings_repository = fresh
    world.audit.records.clear()
    return fresh


def _conforms(method: str, resp: Any) -> Any:
    """The answer's status is one the operation declares, and its body that status's schema."""
    status = str(resp.status_code)
    assert status in _SPEC["paths"][_PATH][method]["responses"], f"{method} {status} undeclared"
    content = deref(_SPEC, _SPEC["paths"][_PATH][method]["responses"][status])["content"]
    body = resp.json()
    schema = content[resp.headers["content-type"].split(";")[0]]["schema"]
    Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(body)
    return body


def _get(world: World, headers: dict[str, str]) -> Any:
    return world.client.get(_PATH, headers=headers)


def _patch(world: World, body: object, headers: dict[str, str]) -> Any:
    return world.client.patch(_PATH, json=body, headers=headers)


async def _seed(store: FakeUserSettings, actor: str, patch: dict[str, object]) -> None:
    await store.apply(user_id_of(actor), patch, write_ahead=noop)


def _values(store: FakeUserSettings, actor: str) -> dict[str, object]:
    return {k: row.value for k, row in store.rows.get(user_id_of(actor), {}).items()}


@pytest.mark.parametrize("method", ["get", "patch"])
def test_settings_operations_declare_every_status_the_routes_answer(method: str) -> None:
    declared = set(_SPEC["paths"][_PATH][method]["responses"])
    assert declared >= _ANSWERED[method]
    assert (
        _SPEC["paths"][_PATH][method]["operationId"]
        == {"get": "getSettings", "patch": "updateSettings"}[method]
    )


@pytest.mark.parametrize("actor", _ROLES)
async def test_get_settings_answers_each_role_its_own_settings_in_22s_shape(
    world: World, store: FakeUserSettings, actor: str
) -> None:
    await _seed(store, actor, {"appearance.density": "compact"})
    body = _conforms("get", _get(world, bearer(actor)))
    assert (
        api.Settings.model_validate(body).model_dump(mode="json", by_alias=True, exclude_unset=True)
        == body
    )
    assert body["_meta"]["overridden"] == ["appearance.density"]


@pytest.mark.parametrize("actor", ["owner", "manager_with_grant", "manager_without_grant"])
async def test_patch_settings_merges_writes_ahead_and_answers_what_get_answers(
    world: World, store: FakeUserSettings, actor: str
) -> None:
    await _seed(store, actor, {"appearance.density": "compact", "appearance.theme": "dark"})
    body = _conforms("patch", _patch(world, {"appearance": {"theme": "light"}}, bearer(actor)))
    assert body["appearance"] == {"density": "compact", "theme": "light"}
    assert body == _conforms("get", _get(world, bearer(actor)))
    (record,) = [r for r in world.audit.records if r["action"] == "settings.change"]
    role = "owner" if actor == "owner" else "manager"
    assert (record["actor_label"], record["actor_user_id"], record["session_id"]) == (
        f"user:{role}",
        user_id_of(actor),
        session_id_of(actor),
    )
    assert record["actor_ip"] and record["request_id"] is not None
    assert (record["before_state"], record["after_state"]) == (
        {"appearance.theme": "dark"},
        {"appearance.theme": "light"},
    )


async def test_patch_settings_refuses_an_invalid_patch_422_in_the_problem_shape(
    world: World, store: FakeUserSettings
) -> None:
    await _seed(store, "owner", {"appearance.theme": "dark"})
    body = _conforms("patch", _patch(world, {"appearance": {"theme": "neon"}}, bearer("owner")))
    assert body["code"] == "validation_failed"
    assert _values(store, "owner") == {"appearance.theme": "dark"}


async def test_settings_a_viewer_reads_and_its_write_is_403_and_changes_nothing(
    world: World, store: FakeUserSettings
) -> None:
    await _seed(store, "viewer", {"accessibility.verbosity": "high"})
    assert _conforms("get", _get(world, bearer("viewer")))["accessibility"] == {"verbosity": "high"}
    body = _conforms(
        "patch", _patch(world, {"accessibility": {"verbosity": "low"}}, bearer("viewer"))
    )
    assert body["code"] == "forbidden" and _values(store, "viewer") == {
        "accessibility.verbosity": "high"
    }


async def test_settings_an_unauthenticated_caller_reads_401_and_its_write_is_refused(
    world: World, store: FakeUserSettings
) -> None:
    anon = TestClient(world.app, client=("127.0.9.1", 50000), raise_server_exceptions=False)
    assert (
        _conforms("get", anon.get(_PATH, headers=bearer("unauthenticated")))["code"]
        == "unauthenticated"
    )
    refused = anon.patch(
        _PATH, json={"appearance": {"theme": "light"}}, headers=bearer("unauthenticated")
    )
    assert _conforms("patch", refused)["code"] == "csrf_token_invalid"  # SR-041 decides first
    assert store.rows == {} and store.calls == []


@pytest.mark.parametrize("case", ["missing", "mismatched"])
async def test_patch_settings_without_a_matching_csrf_token_is_403_and_changes_nothing(
    world: World, store: FakeUserSettings, case: str
) -> None:
    await _seed(store, "owner", {"appearance.theme": "dark"})
    headers = bearer("owner")
    if case == "missing":
        del headers[CSRF_HEADER]
    else:
        headers[CSRF_HEADER] = bearer("manager_with_grant")[CSRF_HEADER]  # another session's
    body = _conforms("patch", _patch(world, {"appearance": {"theme": "light"}}, headers))
    assert body["code"] == "csrf_token_invalid"
    assert _values(store, "owner") == {"appearance.theme": "dark"}
    assert not [r for r in world.audit.records if r["action"] == "settings.change"]


async def test_settings_one_user_never_reads_or_writes_another_users(
    world: World, store: FakeUserSettings
) -> None:
    await _seed(store, "owner", {"appearance.theme": "dark", "chart.crosshair_sync": False})
    await _seed(store, "manager_with_grant", {"appearance.density": "compact"})
    owner_before = _conforms("get", _get(world, bearer("owner")))
    _patch(world, {"appearance": {"theme": "light"}}, bearer("manager_with_grant"))
    mine = _conforms("get", _get(world, bearer("manager_with_grant")))
    assert mine["_meta"]["overridden"] == ["appearance.density", "appearance.theme"]
    assert "chart" not in mine and _conforms("get", _get(world, bearer("owner"))) == owner_before


async def test_settings_under_a_view_read_the_target_and_write_nothing(
    world: World, store: FakeUserSettings
) -> None:
    await _seed(store, "owner", {"appearance.theme": "dark"})
    await _seed(store, "manager_with_grant", {"appearance.theme": "light"})
    viewing = bearer_viewing("manager_with_grant")
    target = _conforms("get", _get(world, bearer("manager_with_grant")))
    assert _conforms("get", _get(world, viewing)) == target  # the target's, never the Owner's
    body = _conforms("patch", _patch(world, {"appearance": {"theme": "dark"}}, viewing))
    assert body["code"] == "view_as_read_only"
    assert _values(store, "manager_with_grant") == {"appearance.theme": "light"}
    assert [r["action"] for r in world.audit.records] == ["admin.view_as_refused"]


@pytest.mark.parametrize("actor", _ROLES)
async def test_me_preferences_answers_exactly_what_get_settings_answers(
    world: World, store: FakeUserSettings, actor: str
) -> None:
    await _seed(store, actor, {"appearance.density": "compact", "data.default_depth": 400})
    settings = _conforms("get", _get(world, bearer(actor)))
    preferences = world.client.get("/me/preferences", headers=bearer(actor))
    assert (preferences.status_code, preferences.json()) == (200, settings)


async def test_settings_answer_503_store_unavailable_while_no_store_is_wired(
    world: World, store: FakeUserSettings
) -> None:
    world.app.state.user_settings_repository = None  # the next test's `store` wires one again
    for resp in (
        _get(world, bearer("owner")), _patch(world, {}, bearer("owner")),
        world.client.get("/me/preferences", headers=bearer("owner")),
    ):  # fmt: skip
        assert resp.status_code == 503 and resp.json()["code"] == "store_unavailable"
