"""#492 S5 provider contract: `getRecordingStatus` through the real `create_app()` (the RBAC pack's
world). Each role's body validates against `RecordingStatus`; everyone but the Owner reads the R-I2
view, with no `position_open` and no path; every status the route answers is declared, and each
problem body is its declared response. Unbound, the body is `not_deployed`."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.recorder.control_runtime import RuntimeRecordingControl
from candleviewer.recorder.policy import PolicyConfig, RefusalCause, StartRefused
from tests.contract._admin_support import validate_example
from tests.contract.rbac.rbac_harness import World, bearer, build_world
from tests.unit.recorder._control_fakes import EmptyRows, FakeRecorder

_SPEC: Any = load_openapi_spec()
_PATH = "/recording/status"
_OK = "/paths/~1recording~1status/get/responses/200/content/application~1json/schema"
_PROBLEMS = {"401": "Unauthorized", "503": "ServiceUnavailable"}
_ROLES = ["owner", "manager_with_grant", "manager_without_grant", "viewer"]
_BEFORE: dict[str, Any] = {}  # the answer before the first computation


def _refresh(world: World) -> None:
    asyncio.run(world.app.state.ws_runtime.recorder_status.refresh_once())


@pytest.fixture(scope="module")
def world() -> Iterator[World]:
    mp = pytest.MonkeyPatch()
    try:
        w, fake = build_world(mp), FakeRecorder()
        fake.put("BTCUSDT", pinned=True, lag_ms=42, rows_last_hour=10, dropped_messages=0)
        fake.put("ETHUSDT", "position_open", "chart_open", refusals=("position_open", "chart_open"))
        fake.put("XRPUSDT", "position_open", refusals=("position_open",))
        w.app.state.recording_runtime = fake
        _BEFORE["503"] = w.client.get(_PATH, headers=bearer("owner"))
        _refresh(w)
        yield w
    finally:
        mp.undo()


@pytest.mark.parametrize("status", ["200", "401", "403", "503"])
def test_the_operation_declares_every_status_the_route_answers(status: str) -> None:
    assert status in _SPEC["paths"][_PATH]["get"]["responses"]


@pytest.mark.parametrize("actor", _ROLES)
def test_each_body_validates_and_no_non_owner_one_reveals_a_position(
    world: World, actor: str
) -> None:
    resp = world.client.get(_PATH, headers=bearer(actor))
    assert resp.status_code == 200
    body = resp.json()
    validate_example(_OK, body)
    assert body["role_restricted"] is (actor != "owner")
    if actor != "owner":
        text = json.dumps(body)
        assert "position_open" not in text and re.search(r'[/\\]|"[A-Za-z]:', text) is None
        assert [row["symbol"] for row in body["symbols"]] == ["BTCUSDT", "ETHUSDT"]


def test_unbound_the_body_is_not_deployed(world: World) -> None:
    fake = world.app.state.recording_runtime
    world.app.state.recording_runtime = None
    _refresh(world)
    try:
        body = world.client.get(_PATH, headers=bearer("owner")).json()
        validate_example(_OK, body)
        assert (body["overall"], body["symbols"]) == ("not_deployed", [])
    finally:
        world.app.state.recording_runtime = fake
        _refresh(world)


def test_each_problem_body_is_its_declared_response(world: World) -> None:
    answers = {"401": world.client.get(_PATH, headers=bearer("unauthenticated")), **_BEFORE}
    assert set(answers) == set(_PROBLEMS)
    for status, resp in answers.items():
        assert (str(resp.status_code), resp.headers["content-type"]) == (
            status, "application/problem+json")  # fmt: skip
        response = f"/components/responses/{_PROBLEMS[status]}/content/application~1problem+json"
        validate_example(f"{response}/schema", resp.json())


class _RefusingPolicy:
    """The S3c policy surface with nothing recorded and two starts refused at the cap: SOLUSDT's
    chart (the 22 example) and LINKUSDT's position, a cause the R-I2 view hides."""

    def start_refused(self) -> tuple[StartRefused, ...]:
        return (StartRefused("LINKUSDT", "symbol_cap", ("position_open",)),
                StartRefused("SOLUSDT", "symbol_cap", ("chart_open",)))  # fmt: skip

    def start_refusal(self, symbol: str) -> RefusalCause | None:
        return "symbol_cap" if symbol in ("LINKUSDT", "SOLUSDT") else None

    def linger_until(self, symbol: str) -> None:
        return None

    def chart_open(self, symbol: str) -> bool:
        return symbol == "SOLUSDT"

    def position_open(self, symbol: str) -> bool:
        return symbol == "LINKUSDT"


@dataclass(frozen=True)
class _Wiring:
    policy: Any
    rows: Any
    budget: None
    env: str


def test_start_refused_symbols_with_no_row_through_the_bound_runtime(world: World) -> None:
    """Through `create_app()` with the runtime control bound: the Owner's body lists SOLUSDT and
    LINKUSDT, each once, refused for `symbol_cap`; the restricted body only SOLUSDT."""
    fake = world.app.state.recording_runtime
    world.app.state.recording_runtime = RuntimeRecordingControl(
        _Wiring(_RefusingPolicy(), EmptyRows(), None, "demo"), config=PolicyConfig(),
        now=lambda: datetime(2026, 10, 24, tzinfo=UTC),
    )  # fmt: skip
    _refresh(world)
    try:
        bodies = {a: world.client.get(_PATH, headers=bearer(a)).json() for a in _ROLES}
        for body in bodies.values():
            validate_example(_OK, body)
        owner = [(r["symbol"], r["state"], r["refusal"]) for r in bodies["owner"]["symbols"]]
        assert owner == [("LINKUSDT", "idle", "symbol_cap"), ("SOLUSDT", "idle", "symbol_cap")]
        for actor in _ROLES[1:]:
            assert [r["symbol"] for r in bodies[actor]["symbols"]] == ["SOLUSDT"]
            assert "position_open" not in json.dumps(bodies[actor])
    finally:
        world.app.state.recording_runtime = fake
        _refresh(world)
