"""Provider contract tests (E02-T13, #5181): `getSettings` and `updateSettings` over HTTP, through
the real `create_app()` (the RBAC pack's world: identity, sessions and the settings store faked,
no network, C-13.5). Every answer validates against the schema 22 declares for its status, the 200
bodies round-trip through the generated `Settings`, and the edge guards the routes rely on run for
real: CSRF on the write (SR-041), the view-as guard (#3085), RBAC per role, and `settings.change`
in the world's audit sink. `GET /me/preferences` answers what `GET /settings` answers.

`updateSettings` declares the shared `401` (E02-T13's contract commit). A write with no session at
all is refused by CSRF first (`403 csrf_token_invalid`, which the matrix reads as its `401`); an
expired access token whose live session the SR-041 pair is bound to passes CSRF and reaches the
route's `401`, asserted here in the declared shape."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.auth.csrf import CSRF_HEADER
from candleviewer.auth.errors import SessionNotFound
from tests.contract.rbac.rbac_harness import (
    ACTORS,
    World,
    bearer,
    bearer_viewing,
    build_world,
    session_id_of,
    session_record,
    user_id_of,
)
from tests.openapi_helpers import deref
from tests.unit.storage.fakes_user_settings import FakeUserSettings
from tests.unit.storage.user_settings_contract import noop

_SPEC: Any = load_openapi_spec()
_PATH = "/settings"
_ROLES = ACTORS[:4]
#: Every status the routes answer in this world, per operation.
_ANSWERED = {
    "get": {"200", "401", "403", "422", "503"},
    "patch": {"200", "401", "403", "422", "503"},
}


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


async def test_patch_settings_an_expired_access_token_with_its_csrf_pair_is_401(
    world: World, store: FakeUserSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `401` `updateSettings` declares. The access token has expired and its session lives, so
    the CSRF guard still finds the session the pair is bound to (`peek_access_token` reads it past
    the token's TTL, as the session service does) and lets the write through to the route, where
    authentication fails: `401 unauthenticated`, nothing written, no record."""
    await _seed(store, "owner", {"appearance.theme": "dark"})
    sessions = world.app.state.app_context.auth.sessions

    async def peek(token: str) -> Any:
        return session_record(token)

    async def authenticate(token: str, **_kw: Any) -> Any:
        raise SessionNotFound("access token expired")

    monkeypatch.setattr(sessions, "peek_access_token", peek)
    monkeypatch.setattr(sessions, "authenticate_access_token", authenticate)
    resp = _patch(world, {"appearance": {"theme": "light"}}, bearer("owner"))
    body = _conforms("patch", resp)
    assert (resp.status_code, body["code"]) == (401, "unauthenticated")
    assert body["detail"] == "No verified session for this request."  # the route's own
    assert _values(store, "owner") == {"appearance.theme": "dark"}
    assert not [r for r in world.audit.records if r["action"] == "settings.change"]


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


async def test_settings_a_target_user_query_is_422_and_a_refused_patch_changes_nothing(
    world: World, store: FakeUserSettings
) -> None:
    """SR-026: neither operation declares a query parameter, so `?user_id=<other>` is refused
    `422` after the permission check, with no record, and the other user's settings untouched."""
    await _seed(store, "owner", {"appearance.theme": "dark"})
    await _seed(store, "manager_with_grant", {"appearance.theme": "light"})
    other = {"user_id": str(user_id_of("manager_with_grant"))}
    sent = {"appearance": {"theme": "neon"}}  # never judged: the query is refused first
    reads = world.client.get(_PATH, params=other, headers=bearer("owner"))
    writes = world.client.patch(_PATH, params=other, json=sent, headers=bearer("owner"))
    for method, resp in (("get", reads), ("patch", writes)):
        body = _conforms(method, resp)
        assert (resp.status_code, body["code"]) == (422, "validation_failed")
        assert [e["rule"] for e in body["errors"]] == ["target_user_not_accepted"]
    assert _values(store, "owner") == {"appearance.theme": "dark"}
    assert _values(store, "manager_with_grant") == {"appearance.theme": "light"}
    assert world.audit.records == []


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


async def test_settings_and_preferences_answer_a_viewer_the_webhook_url_masked(
    world: World, store: FakeUserSettings
) -> None:
    """Q3, as ruled: the target reads its own webhook URL in full; the Owner viewing as the target
    reads it masked, on both aliases, through the real view-as guard and session resolvers."""
    url = "https://canary-u@hooks.example.test:8443/T000/canary-p?k=canary-q#canary-f"
    await _seed(store, "manager_with_grant", {"notifications.webhook_url": url})
    own = _conforms("get", _get(world, bearer("manager_with_grant")))
    assert own["notifications"] == {"webhook_url": url}
    viewing = bearer_viewing("manager_with_grant")
    viewed = _conforms("get", _get(world, viewing))
    preferences = world.client.get("/me/preferences", headers=viewing)
    assert (preferences.status_code, preferences.json()) == (200, viewed)
    assert viewed == {**own, "notifications": {"webhook_url": "https://hooks.example.test/…"}}


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
