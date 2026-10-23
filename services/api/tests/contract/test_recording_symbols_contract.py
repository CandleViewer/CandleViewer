"""#492 S2 provider contract: `listRecordedSymbols` and `getRecordedSymbol` through the real
`create_app()` (the RBAC pack's world). Bodies validate against the schema 22 declares for their
status; every status the routes answer is declared; the examples validate; no non-Owner body
carries a path (E16-FR-06, `test_recorder_dto_rejects_path_chars`)."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from candleviewer.api.contract_conformance import load_openapi_spec
from tests.contract._admin_support import example_cases, validate_example
from tests.contract.rbac.rbac_harness import World, bearer, build_world
from tests.unit.recorder._control_fakes import NOW, FakeRecorder

_SPEC: Any = load_openapi_spec()
_LIST, _ONE = "/recording/symbols", "/recording/symbols/{recordedSymbolId}"
_ANSWERED = {_LIST: ("200", "400", "401", "403", "503"), _ONE: ("200", "401", "403", "404", "503")}
_CASES = [(p, s) for p in _ANSWERED for s in _ANSWERED[p]]
_EXAMPLES = example_cases([(_LIST, "get"), (_ONE, "get")])
_PROBLEMS = {"400": "BadRequest", "401": "Unauthorized", "404": "NotFound"}
_PROBLEMS["503"] = "ServiceUnavailable"
_ROLES = ["owner", "manager_with_grant", "manager_without_grant", "viewer"]
_USER = str(uuid.uuid4())


def _ok(path: str) -> str:
    return f"/paths/{path.replace('/', '~1')}/get/responses/200/content/application~1json/schema"


@pytest.fixture(scope="module")
def world() -> Iterator[World]:
    mp = pytest.MonkeyPatch()
    try:
        w, fake = build_world(mp), FakeRecorder()
        fake.put("BTCUSDT", pinned=True, started_at=NOW, disk_bytes=10**9, lag_ms=42)
        fake.put("ETHUSDT", "position_open", "chart_open", refusals=("position_open",),
                 lingering=True, linger_until=NOW, streams=("trades", "tickers"))  # fmt: skip
        fake.put("XRPUSDT", "position_open", refusals=("position_open",), added_by=_USER)
        w.app.state.recording_control = fake
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
    listed = world.client.get(_LIST, headers=bearer(actor))
    first = world.client.get(f"{_LIST}/{listed.json()['items'][0]['id']}", headers=bearer(actor))
    assert (listed.status_code, first.status_code) == (200, 200)
    validate_example(_ok(_LIST), listed.json())
    validate_example(_ok(_ONE), first.json())
    assert listed.json()["role_restricted"] is (actor != "owner")
    pathish = re.search(r'[/\\]|"[A-Za-z]:', json.dumps([listed.json(), first.json()]))
    assert actor == "owner" or pathish is None


def test_each_problem_body_is_its_declared_response(world: World) -> None:
    owner, fake = bearer("owner"), world.app.state.recording_control
    answers = {
        "404": world.client.get(f"{_LIST}/{uuid.uuid4()}", headers=owner),
        "400": world.client.get(_LIST, params={"cursor": "x"}, headers=owner),
        "401": world.client.get(_LIST, headers=bearer("unauthenticated")),
    }
    world.app.state.recording_control = None  # no store: 503
    answers["503"] = world.client.get(_LIST, headers=owner)
    world.app.state.recording_control = fake
    for status, resp in answers.items():
        assert (str(resp.status_code), resp.headers["content-type"]) == (
            status, "application/problem+json")  # fmt: skip
        response = f"/components/responses/{_PROBLEMS[status]}/content/application~1problem+json"
        validate_example(f"{response}/schema", resp.json())
