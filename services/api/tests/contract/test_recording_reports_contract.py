"""#492 S3 provider contract: `listRecordingSessions` and `getStorageUsage` through the real
`create_app()` (the RBAC pack's world). Bodies validate against the schema 22 declares for their
status; every status the routes answer is declared; the examples validate; no non-Owner body
carries a path (E16-FR-06, `test_recorder_dto_rejects_path_chars`)."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

import pytest

from candleviewer.api.contract_conformance import load_openapi_spec
from tests.contract._admin_support import example_cases, validate_example
from tests.contract.rbac.rbac_harness import World, bearer, build_world
from tests.unit.api.test_recording_reports import _Budget, _recorder, _Sessions, _usage

_SPEC: Any = load_openapi_spec()
_SESSIONS, _STORAGE = "/recording/sessions", "/recording/storage"
_ANSWERED = {_SESSIONS: ("200", "400", "401", "403", "503"),
             _STORAGE: ("200", "401", "403", "503")}  # fmt: skip
_CASES = [(p, s) for p in _ANSWERED for s in _ANSWERED[p]]
_EXAMPLES = example_cases([(_SESSIONS, "get"), (_STORAGE, "get")])
_PROBLEMS = {"400": "BadRequest", "401": "Unauthorized", "503": "ServiceUnavailable"}
_ROLES = ["owner", "manager_with_grant", "manager_without_grant", "viewer"]


def _ok(path: str) -> str:
    return f"/paths/{path.replace('/', '~1')}/get/responses/200/content/application~1json/schema"


@pytest.fixture(scope="module")
def world() -> Iterator[World]:
    mp = pytest.MonkeyPatch()
    try:
        w, sessions = build_world(mp), _Sessions()
        sessions.add("BTCUSDT", 3, ended=1)
        sessions.add("BTCUSDT", 1)
        sessions.add("XRPUSDT", 2, reason="position_open")
        sessions.add("ETHUSDT", 2, env="live")
        mp.setattr(w.app.state, "recording_control", _recorder(), raising=False)
        mp.setattr(w.app.state, "recording_sessions", sessions, raising=False)
        mp.setattr(w.app.state, "disk_budget", _Budget(_usage()), raising=False)
        yield w
    finally:
        mp.undo()


@pytest.mark.parametrize(("case", "pointer", "value"), _EXAMPLES, ids=[c[0] for c in _EXAMPLES])
def test_every_documented_example_validates(case: str, pointer: str, value: Any) -> None:
    validate_example(pointer, value)


@pytest.mark.parametrize(("path", "status"), _CASES)
def test_the_operation_declares_every_status_the_route_answers(path: str, status: str) -> None:
    assert status in _SPEC["paths"][path]["get"]["responses"]


@pytest.mark.parametrize("actor", _ROLES)
def test_each_body_validates_and_no_non_owner_one_carries_a_path(world: World, actor: str) -> None:
    sessions = world.client.get(_SESSIONS, headers=bearer(actor))
    storage = world.client.get(_STORAGE, headers=bearer(actor))
    assert (sessions.status_code, storage.status_code) == (200, 200)
    validate_example(_ok(_SESSIONS), sessions.json())
    validate_example(_ok(_STORAGE), storage.json())
    shown = {item["symbol"] for item in sessions.json()["items"]}
    assert shown == ({"BTCUSDT", "XRPUSDT"} if actor == "owner" else {"BTCUSDT"})
    pathish = re.search(r'[/\\]|"[A-Za-z]:', json.dumps([sessions.json(), storage.json()]))
    assert actor == "owner" or pathish is None


def test_each_problem_body_is_its_declared_response(world: World) -> None:
    owner = bearer("owner")
    answers = {
        "400": world.client.get(_SESSIONS, params={"cursor": "x"}, headers=owner),
        "401": world.client.get(_STORAGE, headers=bearer("unauthenticated")),
    }
    budget = world.app.state.disk_budget
    world.app.state.disk_budget = _Budget(None)  # before the first sample: 503
    answers["503"] = world.client.get(_STORAGE, headers=owner)
    world.app.state.disk_budget = budget
    held = world.app.state.recording_sessions
    world.app.state.recording_sessions = None  # no session store: the same declared 503
    no_store = world.client.get(_SESSIONS, headers=owner)
    world.app.state.recording_sessions = held
    assert (no_store.status_code, no_store.json()["code"]) == (503, "store_unavailable")
    for status, resp in answers.items():
        assert (str(resp.status_code), resp.headers["content-type"]) == (
            status, "application/problem+json")  # fmt: skip
        response = f"/components/responses/{_PROBLEMS[status]}/content/application~1problem+json"
        validate_example(f"{response}/schema", resp.json())
