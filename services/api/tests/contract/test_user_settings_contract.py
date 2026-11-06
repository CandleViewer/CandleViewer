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

import json
import re
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.user_settings_models import MAX_BODY_BYTES
from candleviewer.auth.csrf import CSRF_HEADER
from candleviewer.auth.errors import SessionNotFound
from candleviewer.orderflow import limits as L
from tests.contract._admin_support import ROOT
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
#: E22-S02 (#715): 22 `Settings.bigtrade`'s three leaves, each a symbol-keyed map.
_BIGTRADE: Any = deref(_SPEC, _SPEC["components"]["schemas"]["Settings"]["properties"]["bigtrade"])
_LEAF: Any = {name: deref(_SPEC, leaf) for name, leaf in _BIGTRADE["properties"].items()}


def _upper_bounds(pattern: str) -> list[int]:
    """Each `{m,n}` quantifier's `n`, in order: the longest run the pattern lets through."""
    return [int(n) for n in re.findall(r"\{\d+,(\d+)\}", pattern)]


def _worst_symbols() -> list[str]:
    """`maxProperties` distinct keys of the longest `Symbol` each leaf's `then` admits."""
    (count,) = {leaf["maxProperties"] for leaf in _LEAF.values()}
    (pattern,) = {leaf["then"]["propertyNames"]["pattern"] for leaf in _LEAF.values()}
    (width,) = _upper_bounds(pattern)
    return [f"{i:0{width}d}USDT" for i in range(count)]


def _worst_value(name: str) -> object:
    """The longest JSON value the leaf's `additionalProperties` admits, read off 22."""
    member = _LEAF[name]["additionalProperties"]
    if "enum" in member:
        return max(member["enum"], key=len)
    if member["type"] == "integer":
        return max(member["minimum"], member["maximum"], key=lambda n: len(str(n)))
    whole, fraction = _upper_bounds(member["pattern"])
    return f"{'9' * whole}.{'9' * fraction}"


_WORST_SYMBOLS = _worst_symbols()
_WORST_VALUE: dict[str, object] = {name: _worst_value(name) for name in _LEAF}
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


def test_the_worst_case_bigtrade_map_is_the_largest_22_admits_at_limits_cap() -> None:
    """The worst case below is read off 22, never typed in: `maxProperties` keys, each the longest
    `Symbol`, and each leaf's longest value, the decimal one at its `maxLength`, so a looser
    pattern or a larger cap grows it. The cap is `limits.py`'s (SR-E22-11)."""
    (pattern,) = {leaf["then"]["propertyNames"]["pattern"] for leaf in _LEAF.values()}
    assert len(set(_WORST_SYMBOLS)) == len(_WORST_SYMBOLS) == L.THRESHOLD_SYMBOLS_PER_USER_MAX
    assert all(re.fullmatch(pattern, key) for key in _WORST_SYMBOLS)
    value = _LEAF["threshold_value"]["additionalProperties"]
    assert re.fullmatch(value["pattern"], str(_WORST_VALUE["threshold_value"]))
    assert len(str(_WORST_VALUE["threshold_value"])) == value["maxLength"]


@pytest.mark.parametrize("leaf", sorted(_WORST_VALUE))
async def test_patch_settings_a_worst_case_200_symbol_bigtrade_leaf_fits_the_16_kib_body(
    world: World, store: FakeUserSettings, leaf: str
) -> None:
    """The client sends a `bigtrade` leaf's full symbol map (22 `Settings.bigtrade`): at the
    200-symbol cap and the longest key and value, with JSON's default spacing, it fits under the
    body cap, is stored whole, and 22's `maxProperties` refuses a 201st symbol."""
    worst = dict.fromkeys(_WORST_SYMBOLS, _WORST_VALUE[leaf])
    raw = json.dumps({"bigtrade": {leaf: worst}}).encode()
    assert MAX_BODY_BYTES == 16 * 1024  # the 16 KiB 22's `Settings.bigtrade` promises
    assert len(raw) <= MAX_BODY_BYTES
    headers = {**bearer("owner"), "content-type": "application/json"}
    body = _conforms("patch", world.client.patch(_PATH, content=raw, headers=headers))
    assert body["bigtrade"] == {leaf: worst}
    assert _values(store, "owner") == {f"bigtrade.{leaf}": worst}
    over = {**worst, "BTCUSDT": _WORST_VALUE[leaf]}
    refused = _conforms("patch", _patch(world, {"bigtrade": {leaf: over}}, bearer("owner")))
    assert refused["code"] == "validation_failed"
    assert _values(store, "owner") == {f"bigtrade.{leaf}": worst}


@pytest.mark.parametrize("key", ["btcusdt", "", "A" * 2044 + "USDT", "BTCUSDT\r\nX: 1"])
async def test_patch_settings_refuses_a_bigtrade_key_that_is_no_symbol_and_stores_nothing(
    world: World, store: FakeUserSettings, key: str
) -> None:
    """22 `Settings.bigtrade`: each key a `Symbol`, checked by the server (E22-S02, #715)."""
    await _seed(store, "owner", {"bigtrade.threshold_mode": {"BTCUSDT": "notional"}})
    sent = {"bigtrade": {"threshold_mode": {"ETHUSDT": "notional", key: "percentile"}}}
    body = _conforms("patch", _patch(world, sent, bearer("owner")))
    assert body["code"] == "validation_failed"
    assert [(e["field"], e["rule"]) for e in body["errors"]] == [
        ("bigtrade.threshold_mode", "string_pattern_mismatch")  # the key is never echoed
    ]
    assert _values(store, "owner") == {"bigtrade.threshold_mode": {"BTCUSDT": "notional"}}


async def test_patch_settings_a_bigtrade_leaf_replaces_its_whole_symbol_map(
    world: World, store: FakeUserSettings
) -> None:
    """A `PATCH` of an object leaf replaces the object, never merges into it (E02-T13): a symbol
    the client leaves out of the map is gone, so the client sends the full map, one leaf a patch."""
    held = {"BTCUSDT": "250000", "ETHUSDT": "100000"}
    await _seed(store, "owner", {"bigtrade.threshold_value": held})
    sent = {"bigtrade": {"threshold_value": {"SOLUSDT": "5000"}}}
    body = _conforms("patch", _patch(world, sent, bearer("owner")))
    assert body["bigtrade"] == {"threshold_value": {"SOLUSDT": "5000"}}
    assert body == _conforms("get", _get(world, bearer("owner")))
    (record,) = [r for r in world.audit.records if r["action"] == "settings.change"]
    assert (record["before_state"], record["after_state"]) == (
        {"bigtrade.threshold_value": held},
        {"bigtrade.threshold_value": {"SOLUSDT": "5000"}},
    )


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


def test_the_change_log_records_the_bigtrade_settings_and_the_cap_state_as_19_136() -> None:
    """E22-S02 (#715): 24 section 19 logs the contract slice once, under the number the
    orchestrator assigned, and names the deferrals and the web's generated bounds."""
    doc = (ROOT / "docs/plan/24-internal-schemas.md").read_text(encoding="utf-8")
    numbers = [int(n) for n in re.findall(r"^### 19\.(\d+) ", doc, re.MULTILINE)]
    assert numbers.count(136) == 1
    title = r"^### 19\.136 2026-11-04 — .*: the per-symbol big-trade threshold settings .*$"
    heading = re.search(title, doc, re.MULTILINE)
    assert heading is not None and "(E22-S02, #715)" in heading.group(0)
    entry = doc[heading.start() :].split("\n### ", 1)[0]
    assert "This is the number the orchestrator assigned on 2026-11-04 (23:02Z)" in entry
    assert "deferred to #715's store slice" in entry
    assert "a bounds module generated from 22, never from literals" in entry
