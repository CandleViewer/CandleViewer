"""#492 S4 provider contract: `listRetentionPolicies` and `setRetentionPolicies` through the real
`create_app()` (the RBAC pack's world, so the real step-up guard). Bodies validate against the
schema 22 declares for their status; every status the routes answer is declared; the examples
validate. The PUT always needs the `recorder` step-up, path-gated (`403 step_up_required`); with
it the Owner and a Manager replace the set, while a Viewer gets 403 and an `rbac.denied` record."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from candleviewer.api.contract_conformance import load_openapi_spec
from tests.contract._admin_support import example_cases, validate_example
from tests.contract.rbac.rbac_harness import World, bearer, build_world
from tests.unit.api.test_recording_retention import _item, _Store, _whole

_SPEC: Any = load_openapi_spec()
_PATH = "/recording/retention-policies"
_ANSWERED = {"get": ("200", "401", "403", "503"),
             "put": ("200", "401", "403", "409", "422", "503")}  # fmt: skip
_CASES = [(m, s) for m in _ANSWERED for s in _ANSWERED[m]]
_EXAMPLES = example_cases([(_PATH, "get"), (_PATH, "put")])
_PROBLEMS = {"401": "Unauthorized", "403": "Forbidden", "409": "Conflict"}
_PROBLEMS |= {"422": "UnprocessableEntity", "503": "ServiceUnavailable"}
_OK = "/paths/~1recording~1retention-policies/{}/responses/200/content/application~1json/schema"


@pytest.fixture(scope="module")
def world() -> Iterator[World]:
    mp = pytest.MonkeyPatch()
    try:
        w = build_world(mp)
        mp.setattr(w.app.state, "retention_policies", _Store([]), raising=False)
        yield w
    finally:
        mp.undo()


@pytest.fixture
def store(world: World) -> _Store:
    world.step_up.elevated = True
    world.audit.records.clear()
    fresh = _Store([])
    fresh.seed("trades", 30)
    world.app.state.retention_policies = fresh
    return fresh


def _put(world: World, actor: str, items: Any, **params: Any) -> Any:
    return world.client.put(
        _PATH, json={"items": _whole(items)}, params=params, headers=bearer(actor)
    )


@pytest.mark.parametrize(("case", "pointer", "value"), _EXAMPLES, ids=[c[0] for c in _EXAMPLES])
def test_every_documented_example_validates(case: str, pointer: str, value: Any) -> None:
    validate_example(pointer, value)


@pytest.mark.parametrize(("method", "status"), _CASES)
def test_the_operation_declares_every_status_the_route_answers(method: str, status: str) -> None:
    assert status in _SPEC["paths"][_PATH][method]["responses"]


def test_a_put_without_the_recorder_step_up_is_refused_before_the_handler(
    world: World, store: _Store
) -> None:
    world.step_up.elevated = False
    resp = _put(world, "owner", [_item(days=60)])
    assert (resp.status_code, resp.json()["code"]) == (403, "step_up_required")
    assert store.replaced == 0


@pytest.mark.parametrize("actor", ["owner", "manager_with_grant"])
def test_with_the_step_up_the_owner_and_a_manager_replace_the_set(
    world: World, store: _Store, actor: str
) -> None:
    resp = _put(world, actor, [_item(days=60)])
    assert resp.status_code == 200 and store.replaced == 1
    validate_example(_OK.format("put"), resp.json())
    listed = world.client.get(_PATH, headers=bearer("viewer"))
    assert listed.status_code == 200 and listed.json() == resp.json()
    validate_example(_OK.format("get"), listed.json())
    assert [r["action"] for r in world.audit.records] == ["retention.change"]


def test_a_viewer_with_the_step_up_gets_403_and_an_rbac_denied_record(
    world: World, store: _Store
) -> None:
    resp = _put(world, "viewer", [_item(days=60)])
    assert (resp.status_code, resp.json()["code"]) == (403, "forbidden")
    assert [r["action"] for r in world.audit.records] == ["rbac.denied"]
    assert store.replaced == 0


def test_each_problem_body_is_its_declared_response(world: World, store: _Store) -> None:
    answers = {
        "401": world.client.get(_PATH, headers=bearer("unauthenticated")),
        "403": _put(world, "viewer", [_item()]),
        "409": _put(world, "owner", [_item()], apply_now="true"),  # the scheduler is off
        "422": _put(world, "owner", [_item(action="pin")]),
    }
    world.app.state.retention_policies = None  # no store: 503
    answers["503"] = world.client.get(_PATH, headers=bearer("owner"))
    for status, resp in answers.items():
        assert (str(resp.status_code), resp.headers["content-type"]) == (
            status, "application/problem+json")  # fmt: skip
        response = f"/components/responses/{_PROBLEMS[status]}/content/application~1problem+json"
        validate_example(f"{response}/schema", resp.json())
    assert store.replaced == 0
