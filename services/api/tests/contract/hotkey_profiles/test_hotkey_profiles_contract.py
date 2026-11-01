"""E10-T05 (#5211): the five `/settings/hotkeys*` operations and `getMyKeymap` through the real
app (session, CSRF, the view-as guard, RBAC, the router over an in-memory store) answer only what
22-api-openapi.yaml documents: each status a documented one, each body valid against its schema,
each problem with its catalogued `code`, each `ETag` a `HotkeyProfileETag` and each
`Hotkey-Bindings-Rewritten` a `HotkeyBindingsRewritten`. A Manager's probe of the Owner's profile
is the 404 of a missing one, audited `rbac.denied`; a view reads the target's profiles and keymap
and writes nothing; the app counts each 409 and 422 in `hotkey_profile_refusals_total`. Not
reached here: `401` on a write (with no session the CSRF guard answers first, `403
csrf_token_invalid`; the router tests check the route's `401`), `403` on the list (every role
holds `settings:read`) and the list's declared `404`, which 22 says is never answered."""

from __future__ import annotations

from collections.abc import Iterator
from functools import cache
from typing import Any

import httpx
import pytest
from jsonschema import Draft202012Validator
from referencing import Registry
from referencing.jsonschema import DRAFT202012

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.storage.repositories.hotkey_profiles import MAX_PROFILES
from tests.contract.rbac.rbac_harness import (
    World,
    bearer,
    bearer_viewing,
    build_world,
    user_id_of,
)
from tests.hotkey_profiles._fake_store import FakeHotkeyProfileStore
from tests.hotkey_profiles._hotkey_env import FOOTPRINT, MISSING, SCALPING, tag

SPEC: dict[str, Any] = load_openapi_spec()
CODES = {e["code"]: e["status"] for e in SPEC["x-error-codes"]}
OPS = {
    op["operationId"]: (method.upper(), path)
    for path, item in SPEC["paths"].items()
    if path.startswith("/settings/hotkeys") or path == "/me/keymap"
    for method, op in item.items() if method in ("get", "put", "post", "delete")
}  # fmt: skip
_BASE = "urn:cv:22-api-openapi"
_REGISTRY: Registry[Any] = Registry().with_resource(_BASE, DRAFT202012.create_resource(SPEC))
_HUGE = b"{" + b" " * (64 * 1024) + b"}"  # past 22's 64 KiB
#: The two headers these routes answer with a string schema; `Retry-After` (an integer) is the
#: shared 503's, as every route answers it.
_OWN_HEADERS = frozenset({"ETag", "Hotkey-Bindings-Rewritten"})
_PAIR = {"name": "Pair", "bindings": [
    {"action": "chart.footprint_toggle", "keys": "Alt+Q", "scope": "chart"},
    {"action": "chart.undo", "keys": "Alt+Q", "scope": "chart"},
]}  # fmt: skip
_ARMED = {"name": "Armed", "bindings": [
    {"action": "ticket.submit", "keys": "Ctrl+Enter", "scope": "ticket", "requires_arm": False},
]}  # fmt: skip


@cache
def _validator(pointer: str) -> Draft202012Validator:
    schema = {"$ref": f"{_BASE}#{pointer}"}
    checker = Draft202012Validator.FORMAT_CHECKER
    return Draft202012Validator(schema, registry=_REGISTRY, format_checker=checker)


def _invalid(pointer: str, doc: Any) -> list[str]:
    return sorted(e.message for e in _validator(pointer).iter_errors(doc))


def _resolve(node: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """(its JSON pointer, the node) for a `$ref`; ("", node) for an inline node."""
    if "$ref" not in node:
        return "", node
    target: Any = SPEC
    for part in node["$ref"].removeprefix("#/").split("/"):
        target = target[part]
    return node["$ref"].removeprefix("#"), target


def conforms(op: str, r: httpx.Response) -> None:
    """`r` is an answer `op` documents: its status, its headers' schemas, its body's."""
    method, path = OPS[op]
    responses = SPEC["paths"][path][method.lower()]["responses"]
    where = f"{op} -> {r.status_code}: {r.text[:300]}"
    assert str(r.status_code) in responses, f"undocumented status: {where}"
    pointer, documented = _resolve(responses[str(r.status_code)])
    if not pointer:
        escaped = path.replace("~", "~0").replace("/", "~1")
        pointer = f"/paths/{escaped}/{method.lower()}/responses/{r.status_code}"
    for name, header in documented.get("headers", {}).items():
        if name in _OWN_HEADERS and name in r.headers:  # header values are strings on the wire
            assert not _invalid(_resolve(header)[0] + "/schema", r.headers[name]), where
    if "Hotkey-Bindings-Rewritten" in r.headers:
        assert "Hotkey-Bindings-Rewritten" in documented.get("headers", {}), where
    if "content" not in documented:
        assert r.text == "", where
        return
    media = r.headers["content-type"].split(";")[0]
    assert media in documented["content"], where
    assert not _invalid(f"{pointer}/content/{media.replace('/', '~1')}/schema", r.json()), where
    if media == "application/problem+json":  # `validation_failed` is catalogued 400, served 422
        code = r.json()["code"]
        allowed = {CODES[code]} | ({422} if code == "validation_failed" else set())
        assert r.status_code in allowed, where


@pytest.fixture(scope="module")
def world() -> Iterator[World]:
    mp = pytest.MonkeyPatch()
    try:
        yield build_world(mp)
    finally:
        mp.undo()


@pytest.fixture
def store(world: World) -> FakeHotkeyProfileStore:
    world.audit.records.clear()
    fresh = FakeHotkeyProfileStore()
    world.app.state.hotkey_profiles_repository = fresh
    return fresh


@pytest.fixture
def api(world: World, store: FakeHotkeyProfileStore) -> Any:
    def send(actor: str, op: str, body: Any = None, pid: object = "", **headers: str) -> Any:
        method, path = OPS[op]
        url = path.replace("{hotkeyProfileId}", str(pid))
        sent: dict[str, Any] = {"content": body} if isinstance(body, bytes) else {"json": body}
        auth = bearer_viewing(actor.removeprefix("owner-as-")) if actor.startswith(
            "owner-as-") else bearer(actor)  # fmt: skip
        r = world.client.request(method, url, headers=auth | headers, **sent)
        conforms(op, r)
        return r

    return send


def _records(world: World, action: str) -> list[dict[str, Any]]:
    return [r for r in world.audit.records if r["action"] == action]


def test_list_conforms_at_200_401_and_503_and_never_names_another_users(
    api: Any, world: World
) -> None:
    mine = api("manager_with_grant", "createHotkeyProfile", SCALPING).json()
    assert api("manager_with_grant", "listHotkeyProfiles").json() == {"items": [mine]}
    assert api("owner", "listHotkeyProfiles").json() == {"items": []}  # whatever the role
    unauthenticated = api("unauthenticated", "listHotkeyProfiles")
    world.app.state.hotkey_profiles_repository = None
    down = api("viewer", "listHotkeyProfiles")
    assert [unauthenticated.status_code, down.status_code] == [401, 503]


def test_create_conforms_at_every_reachable_status_and_is_audited_through_the_app(
    api: Any, world: World, store: FakeHotkeyProfileStore
) -> None:
    made = api("manager_with_grant", "createHotkeyProfile", SCALPING)
    (record,) = _records(world, "hotkey_profile.created")
    assert (record["object_id"], record["actor_user_id"]) == (
        made.json()["id"], user_id_of("manager_with_grant"))  # fmt: skip
    assert record["after_state"] == {"name": "Scalping", "binding_count": 1, "is_active": False}
    armed = api("manager_with_grant", "createHotkeyProfile", _ARMED)
    taken = api("manager_with_grant", "createHotkeyProfile", SCALPING | {"name": "SCALPING"})
    clash = api("manager_with_grant", "createHotkeyProfile", _PAIR)
    invalid = api("manager_with_grant", "createHotkeyProfile", SCALPING | {"extra": True})
    viewer = api("viewer", "createHotkeyProfile", SCALPING | {"name": "V"})
    csrf = api("unauthenticated", "createHotkeyProfile", SCALPING | {"name": "U"})
    huge = api("manager_with_grant", "createHotkeyProfile", _HUGE, **{"content-type": "x"})
    for n in range(MAX_PROFILES):
        api("owner", "createHotkeyProfile", {"name": f"P{n}", "bindings": []})
    full = api("owner", "createHotkeyProfile", {"name": "Past the cap", "bindings": []})
    world.app.state.hotkey_profiles_repository = None
    down = api("manager_with_grant", "createHotkeyProfile", SCALPING | {"name": "D"})
    answers = (made, armed, taken, clash, invalid, viewer, csrf, huge, full, down)
    assert [r.status_code for r in answers] == [201, 201, 409, 409, 422, 403, 403, 413, 409, 503]
    assert armed.headers["Hotkey-Bindings-Rewritten"] == "ticket.submit"
    assert "Hotkey-Bindings-Rewritten" not in made.headers
    assert [r.json()["errors"][0]["rule"] for r in (taken, clash, full)] == [
        "name_taken", "binding_conflict", "limit_reached"]  # fmt: skip
    assert csrf.json()["code"] == "csrf_token_invalid"


def test_update_conforms_at_every_reachable_status(api: Any, world: World) -> None:
    made = api("owner", "createHotkeyProfile", SCALPING).json()
    other = api("owner", "createHotkeyProfile", SCALPING | {"name": "Other"}).json()
    new = SCALPING | {"bindings": [FOOTPRINT | {"keys": "Ctrl+Alt+G"}]}
    ok = api("owner", "updateHotkeyProfile", new, made["id"], **tag(made))
    idor = api("manager_with_grant", "updateHotkeyProfile", new, made["id"], **tag(ok.json()))
    missing = api("owner", "updateHotkeyProfile", new, MISSING, **tag(made))
    assert idor.content == missing.content  # a Manager's view of the Owner's profile: none
    probes = [r for r in _records(world, "rbac.denied") if r.get("object_kind") == "hotkey_profile"]
    assert [(r["object_id"], r["reason"]) for r in probes] == [
        (made["id"], "not_owner:settings:write:self")]  # fmt: skip
    answers = [
        api("owner", "updateHotkeyProfile", _HUGE, made["id"], **{"content-type": "x"}),
        ok, idor, missing,
        api("owner", "updateHotkeyProfile", new, made["id"]),  # no If-Match: last write wins
        api("owner", "updateHotkeyProfile", new, made["id"], **tag(made)),  # stale
        api("owner", "updateHotkeyProfile", SCALPING | {"bindings": [{"action": "x.y"}]},
            other["id"]),
        api("owner", "updateHotkeyProfile", SCALPING, other["id"]),  # Scalping is taken
        api("owner", "updateHotkeyProfile", _PAIR, other["id"]),
        api("owner", "updateHotkeyProfile", _ARMED, other["id"]),
        api("viewer", "updateHotkeyProfile", new, made["id"]),
    ]  # fmt: skip
    world.app.state.hotkey_profiles_repository = None
    answers.append(api("owner", "updateHotkeyProfile", new, made["id"]))
    assert [r.status_code for r in answers] == [
        413, 200, 404, 404, 200, 412, 422, 409, 409, 200, 403, 503]  # fmt: skip
    assert answers[5].headers["ETag"] == f'W/"{made["id"]}:3"'  # the 412 names the current one
    assert answers[9].headers["Hotkey-Bindings-Rewritten"] == "ticket.submit"


def test_delete_conforms_at_204_403_404_409_and_503(api: Any, world: World) -> None:
    made = api("owner", "createHotkeyProfile", SCALPING).json()
    active = api("owner", "createHotkeyProfile", SCALPING | {"name": "Active"}).json()
    api("owner", "activateHotkeyProfile", pid=active["id"])
    viewer = api("viewer", "deleteHotkeyProfile", pid=made["id"])
    idor = api("manager_with_grant", "deleteHotkeyProfile", pid=made["id"])
    in_use = api("owner", "deleteHotkeyProfile", pid=active["id"])
    gone = api("owner", "deleteHotkeyProfile", pid=made["id"])
    again = api("owner", "deleteHotkeyProfile", pid=made["id"])
    world.app.state.hotkey_profiles_repository = None
    down = api("owner", "deleteHotkeyProfile", pid=MISSING)
    statuses = [r.status_code for r in (viewer, idor, in_use, gone, again, down)]
    assert statuses == [403, 404, 409, 204, 404, 503]
    assert in_use.json()["errors"][0]["rule"] == "profile_active"
    (deleted,) = _records(world, "hotkey_profile.deleted")
    assert deleted["before_state"] == {"name": "Scalping", "binding_count": 1, "is_active": False}


def test_activate_conforms_at_200_403_404_and_503(api: Any, world: World) -> None:
    one = api("owner", "createHotkeyProfile", SCALPING).json()
    two = api("owner", "createHotkeyProfile", SCALPING | {"name": "Two"}).json()
    first = api("owner", "activateHotkeyProfile", pid=one["id"])
    swap = api("owner", "activateHotkeyProfile", pid=two["id"])
    again = api("owner", "activateHotkeyProfile", pid=two["id"])
    viewer = api("viewer", "activateHotkeyProfile", pid=one["id"])
    idor = api("manager_with_grant", "activateHotkeyProfile", pid=one["id"])
    world.app.state.hotkey_profiles_repository = None
    down = api("owner", "activateHotkeyProfile", pid=one["id"])
    statuses = [r.status_code for r in (first, swap, again, viewer, idor, down)]
    assert statuses == [200, 200, 200, 403, 404, 503]
    assert swap.headers["ETag"] == f'W/"{two["id"]}:1"'
    activated = _records(world, "hotkey_profile.activated")
    assert [r["before_state"]["previous_active_id"] for r in activated] == [None, one["id"]]


def test_the_keymap_answers_the_active_profile_through_the_app(api: Any) -> None:
    assert api("owner", "getMyKeymap").json() == {"bindings": []}
    made = api("owner", "createHotkeyProfile", SCALPING).json()
    api("owner", "activateHotkeyProfile", pid=made["id"])
    keymap = api("owner", "getMyKeymap").json()
    assert keymap == {"hotkey_profile_id": made["id"], "bindings": made["bindings"]}
    assert api("manager_with_grant", "getMyKeymap").json() == {"bindings": []}


def test_a_view_reads_the_targets_profiles_and_keymap_and_writes_nothing(
    api: Any, world: World, store: FakeHotkeyProfileStore
) -> None:
    """BQ-14 through the real guard: the Owner viewing as a Manager reads what the Manager
    reads; every write is the guard's `403 view_as_read_only`, nothing stored."""
    target = "manager_with_grant"
    theirs = api(target, "createHotkeyProfile", SCALPING).json()
    api(target, "activateHotkeyProfile", pid=theirs["id"])
    for op in ("listHotkeyProfiles", "getMyKeymap"):
        assert api(f"owner-as-{target}", op).json() == api(target, op).json()
    rows = dict(store.rows)
    writes = [
        api(f"owner-as-{target}", "createHotkeyProfile", SCALPING | {"name": "Viewer's"}),
        api(f"owner-as-{target}", "updateHotkeyProfile", SCALPING, theirs["id"]),
        api(f"owner-as-{target}", "deleteHotkeyProfile", pid=theirs["id"]),
        api(f"owner-as-{target}", "activateHotkeyProfile", pid=theirs["id"]),
    ]
    assert {(r.status_code, r.json()["code"]) for r in writes} == {(403, "view_as_read_only")}
    assert store.rows == rows


def test_the_app_counts_each_409_and_422_by_code_and_rule(api: Any, world: World) -> None:
    facade = world.app.state.metrics_facade
    before = facade.snapshot(["hotkey_profile_refusals"])
    api("owner", "createHotkeyProfile", SCALPING)
    api("owner", "createHotkeyProfile", SCALPING)  # name taken
    api("owner", "createHotkeyProfile", SCALPING | {"bindings": [{"action": "x"}]})
    after = facade.snapshot(["hotkey_profile_refusals"])
    grown = {k: v - before.get(k, 0.0) for k, v in after.items() if v != before.get(k, 0.0)}
    assert grown == {
        "hotkey_profile_refusals_total{code=conflict,rule=name_taken}": 1.0,
        "hotkey_profile_refusals_total{code=validation_failed,rule=schema}": 1.0,
    }
