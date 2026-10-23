"""Contract (#3085 S13b; C-6.2, provider side): `startViewAs` answers exactly the statuses
22-api-openapi.yaml declares. Each declared status has a request that reaches it, through the
router behind its admin-area guard (the unit tests' world, `test_view_as_start_route.py`), and an
answer outside the declared set fails. A failure is `application/problem+json` and validates
against its declared response; a `201` validates against `ViewAsContext` and round-trips the
generated model. No network, a fake clock."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import httpx
import pytest

from candleviewer.api._generated import openapi_models as api
from tests.contract._admin_support import SPEC, validate_example
from tests.unit.admin.test_view_as_service import _TARGET, _VIEWER
from tests.unit.api.test_view_as_start_route import _REASON, World, _user, _viewing

_PATH, _METHOD = "/admin/view-as", "post"
_DECLARED = {201, 401, 403, 404, 409, 422, 503}
Send = Callable[[World], Awaitable[httpx.Response]]


def _to(target: UUID) -> dict[str, str]:
    return {"target_user_id": str(target), "reason": _REASON}


async def _started(w: World) -> httpx.Response:
    await w.sign_in()
    return await w.start()


async def _anonymous(w: World) -> httpx.Response:
    return await w.client.post(_PATH, json=_to(_TARGET))


async def _signed_out(w: World) -> httpx.Response:
    minted = await w.sign_in()
    await w.sessions.revoke(str(minted.session_id), reason="logout")  # after the guard's read
    return await w.start()


async def _forbidden(w: World) -> httpx.Response:
    await w.sign_in()
    w.permissions = frozenset()
    return await w.start()


async def _self(w: World) -> httpx.Response:
    await w.sign_in()
    return await w.start(_to(_VIEWER))


async def _owner(w: World) -> httpx.Response:
    await w.sign_in()
    w.users.rows[str(_TARGET)] = _user("bo", roles=("owner",))
    return await w.start()


async def _challenged(w: World) -> httpx.Response:
    await w.sign_in()
    w.auth.step_up.elevated = False
    return await w.start()


async def _unknown(w: World) -> httpx.Response:
    await w.sign_in()
    return await w.start(_to(UUID(int=99)))


async def _active(w: World) -> httpx.Response:
    await w.sign_in()
    await _viewing(w)
    return await w.start()


async def _disabled(w: World) -> httpx.Response:
    await w.sign_in()
    w.users.rows[str(_TARGET)] = _user("bo", status="disabled")
    return await w.start()


async def _invalid(w: World) -> httpx.Response:
    await w.sign_in()
    return await w.start({"target_user_id": str(_TARGET)})


async def _unrecorded(w: World) -> httpx.Response:
    await w.sign_in()
    w.ports.fails["emit"] = ConnectionError("audit WAL unwritable")
    return await w.start()


async def _unwired(w: World) -> httpx.Response:
    await w.sign_in()
    w.service = None
    return await w.start()


#: A request for each declared status, one row per cause: (status, why, send).
_ANSWERS: list[tuple[int, str, Send]] = [
    (201, "started", _started),
    (401, "no session", _anonymous),
    (401, "signed out", _signed_out),
    (403, "no users:write", _forbidden),
    (403, "self", _self),
    (403, "owner target", _owner),
    (403, "step-up", _challenged),
    (404, "unknown", _unknown),
    (409, "active", _active),
    (409, "disabled", _disabled),
    (422, "no reason", _invalid),
    (503, "unrecorded", _unrecorded),
    (503, "unwired", _unwired),
]


def _schema(status: int) -> tuple[str, str]:
    """The JSON pointer of the declared response's schema, and its media type."""
    response = SPEC["paths"][_PATH][_METHOD]["responses"][str(status)]
    pointer = f"/paths/{_PATH.replace('/', '~1')}/{_METHOD}/responses/{status}"
    if "$ref" in response:
        pointer = response["$ref"].removeprefix("#")
        response = SPEC["components"]["responses"][pointer.rsplit("/", 1)[1]]
    (media,) = response["content"]
    return f"{pointer}/content/{media.replace('/', '~1')}/schema", media


def test_the_operation_declares_exactly_these_statuses() -> None:
    operation = SPEC["paths"][_PATH][_METHOD]
    assert operation["operationId"] == "startViewAs"
    assert {int(status) for status in operation["responses"]} == _DECLARED


def test_every_declared_status_has_a_request_that_reaches_it() -> None:
    assert {status for status, *_ in _ANSWERS} == _DECLARED


def _validated(response: httpx.Response) -> dict[str, Any]:
    """The body, once its status is declared and its media type and schema are that response's."""
    assert response.status_code in _DECLARED
    pointer, media = _schema(response.status_code)
    assert response.headers["content-type"].startswith(media)
    body: dict[str, Any] = response.json()
    validate_example(pointer, body)
    return body


def _answers(*, created: bool) -> list[Any]:
    """The 201 when `created`, else every other declared answer: together, all of them."""
    return [
        pytest.param(status, send, id=f"startViewAs-{status}-{why}")
        for status, why, send in _ANSWERS
        if (status == 201) is created
    ]


@pytest.mark.parametrize(("status", "send"), _answers(created=True))
async def test_a_201_is_a_view_as_context_that_round_trips(status: int, send: Send) -> None:
    response = await send(World())
    assert response.status_code == status
    body = _validated(response)
    assert api.ViewAsContext.model_validate(body).model_dump(mode="json") == body


@pytest.mark.parametrize(("status", "send"), _answers(created=False))
async def test_a_refusal_is_a_problem_of_its_declared_response(status: int, send: Send) -> None:
    response = await send(World())
    assert response.status_code == status
    body = _validated(response)
    assert api.Problem.model_validate(body).code == body["code"]
