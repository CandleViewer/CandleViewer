"""Contract (#3085 S12; C-6.2, provider side): `getViewAs` and `endViewAs` answer exactly the
statuses 22-api-openapi.yaml declares. Each declared status has a request that reaches it, through
the router behind the guards `create_app` puts in front of it (the unit tests' world,
`tests/unit/api/test_view_as_routes.py`), and an answer outside the declared set fails. A failure
is `application/problem+json` and validates against its declared response; a `200` validates
against `ViewAsContext` and round-trips the generated model. No network, a fake clock."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

import httpx
import pytest

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.view_as import PATH
from candleviewer.auth.models import MintedSession
from candleviewer.auth.session_service import MIN_IDLE_TIMEOUT_S
from candleviewer.auth.view_as import ViewAsEndReason
from tests.contract._admin_support import SPEC, validate_example
from tests.unit.admin.test_view_as_service import _at
from tests.unit.api.test_view_as_routes import World

_OPS = {"get": "getViewAs", "delete": "endViewAs"}
_DECLARED = {"get": {200, 204, 401, 403, 503}, "delete": {204, 401, 403, 503}}
Send = Callable[[World], Awaitable[httpx.Response]]


async def _viewing(w: World) -> MintedSession:
    minted = await w.sign_in()
    await w.view(minted)
    return minted


def _signed_out(method: str) -> Send:
    async def send(w: World) -> httpx.Response:
        minted = await w.sign_in()
        await w.sessions.revoke(str(minted.session_id), reason="logout")
        return await w.call(method, minted)

    return send


def _locked(method: str) -> Send:
    async def send(w: World) -> httpx.Response:
        minted = await w.sign_in(idle_timeout_s=MIN_IDLE_TIMEOUT_S)
        w.clock.now = _at(0) + timedelta(seconds=MIN_IDLE_TIMEOUT_S + 1)
        return await w.call(method, minted)

    return send


def _enrolment_only(method: str) -> Send:
    async def send(w: World) -> httpx.Response:
        minted = await w.sign_in()
        w.auth.enrolment_only.add(minted.session_id)
        return await w.call(method, minted)

    return send


def _unwired(method: str) -> Send:
    async def send(w: World) -> httpx.Response:
        w.service = None  # the fake backend
        return await w.call(method, await w.sign_in())

    return send


async def _held(w: World) -> httpx.Response:
    minted = await _viewing(w)
    w.ports.reason = ViewAsEndReason.TARGET_INELIGIBLE
    response = await w.call("GET", minted)
    await w.rig.settled()
    return response


async def _names_unread(w: World) -> httpx.Response:
    minted = await _viewing(w)
    w.names.fails = ConnectionError("users store unreachable")
    return await w.call("GET", minted)


async def _ended(w: World) -> httpx.Response:
    response = await w.call("DELETE", await _viewing(w))
    await w.rig.settled()
    return response


async def _store_down(w: World) -> httpx.Response:
    minted = await _viewing(w)
    w.repo.fails.add("leave_view_as")
    return await w.call("DELETE", minted)


async def _no_csrf(w: World) -> httpx.Response:
    return await w.call("DELETE", await _viewing(w), csrf=False)


async def _live(w: World) -> httpx.Response:
    return await w.call("GET", await _viewing(w))


async def _none(w: World) -> httpx.Response:
    return await w.call("GET", await w.sign_in())


async def _nothing_to_end(w: World) -> httpx.Response:
    return await w.call("DELETE", await w.sign_in())


async def _cleared(w: World) -> httpx.Response:
    """The read after the viewer's own leave: its context is cleared, so none."""
    minted = await _viewing(w)
    await w.call("DELETE", minted)
    return await w.call("GET", minted)


async def _anonymous(w: World) -> httpx.Response:
    return await w.call("GET")


#: Per operation, a request for each status it declares, one row per cause: (status, why, send).
_ANSWERS: dict[str, list[tuple[int, str, Send]]] = {
    "get": [
        (200, "live", _live),
        (200, "held", _held),
        (204, "none", _none),
        (204, "cleared", _cleared),
        (401, "no session", _anonymous),
        (401, "signed out", _signed_out("GET")),
        (401, "idle locked", _locked("GET")),
        (403, "enrolment only", _enrolment_only("GET")),
        (503, "unwired", _unwired("GET")),
        (503, "names unread", _names_unread),
    ],
    "delete": [
        (204, "ended", _ended),
        (204, "nothing to end", _nothing_to_end),
        (401, "signed out", _signed_out("DELETE")),
        (401, "idle locked", _locked("DELETE")),
        (403, "csrf", _no_csrf),
        (403, "enrolment only", _enrolment_only("DELETE")),
        (503, "unwired", _unwired("DELETE")),
        (503, "store down", _store_down),
    ],
}
_CASES = [
    pytest.param(method, status, send, id=f"{_OPS[method]}-{status}-{why}")
    for method, rows in _ANSWERS.items()
    for status, why, send in rows
]


def _schema(method: str, status: int) -> tuple[str, str]:
    """The JSON pointer of the declared response's schema, and its media type."""
    response = SPEC["paths"][PATH][method]["responses"][str(status)]
    pointer = f"/paths/{PATH.replace('/', '~1')}/{method}/responses/{status}"
    if "$ref" in response:
        pointer = response["$ref"].removeprefix("#")
        response = SPEC["components"]["responses"][pointer.rsplit("/", 1)[1]]
    (media,) = response["content"]
    return f"{pointer}/content/{media.replace('/', '~1')}/schema", media


@pytest.mark.parametrize("method", list(_OPS))
def test_the_operation_declares_exactly_these_statuses(method: str) -> None:
    operation = SPEC["paths"][PATH][method]
    assert operation["operationId"] == _OPS[method]
    assert {int(status) for status in operation["responses"]} == _DECLARED[method]


@pytest.mark.parametrize("method", list(_OPS))
def test_every_declared_status_has_a_request_that_reaches_it(method: str) -> None:
    assert {status for status, *_ in _ANSWERS[method]} == _DECLARED[method]


def _validated(method: str, response: httpx.Response) -> dict[str, Any]:
    """The body, once its media type and schema are the declared response's."""
    pointer, media = _schema(method, response.status_code)
    assert response.headers["content-type"].startswith(media)
    body: dict[str, Any] = response.json()
    validate_example(pointer, body)
    return body


def _of(statuses: range) -> list[Any]:
    return [case for case in _CASES if case.values[1] in statuses]


@pytest.mark.parametrize(("method", "status", "send"), _of(range(204, 205)))
async def test_a_204_has_no_body(method: str, status: int, send: Send) -> None:
    response = await send(World())
    assert (response.status_code, response.content) == (204, b"")


@pytest.mark.parametrize(("method", "status", "send"), _of(range(200, 201)))
async def test_a_200_is_a_view_as_context_that_round_trips(
    method: str, status: int, send: Send
) -> None:
    response = await send(World())
    assert response.status_code == 200
    body = _validated(method, response)
    assert api.ViewAsContext.model_validate(body).model_dump(mode="json") == body


@pytest.mark.parametrize(("method", "status", "send"), _of(range(400, 600)))
async def test_a_refusal_is_a_problem_of_its_declared_response(
    method: str, status: int, send: Send
) -> None:
    response = await send(World())
    assert response.status_code == status
    body = _validated(method, response)
    assert api.Problem.model_validate(body).code == body["code"]
