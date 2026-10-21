"""#3085 S7: the view-as guard over the whole contract (22-api-openapi.yaml "View-as session").
Every declared operation a viewing session calls with a state-changing method is refused
`view_as_read_only`, except the viewer's own operations and the registered protective writes; the
`*:read` writes are refused too (the method decides, not the effect). And leaving view-as passes
the read-only downgrade as well (Q5). The harness is the unit tests' (`test_view_as_gate.py`)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from candleviewer.api.step_up import make_read_only_guard
from candleviewer.api.view_as_guard import make_view_as_guard
from candleviewer.api.view_as_policy import OWN_OPERATIONS, PROTECTIVE_WRITES
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.view_as import ViewAsState
from tests.csrf_helpers import csrf_headers
from tests.security.auth import _stack
from tests.security.auth._stack import open_stack
from tests.unit.api.test_view_as_gate import _declared, _Gate, _path, _spec

_SAFE = frozenset({"GET", "HEAD", "OPTIONS"})
#: The write-method operations that need only a `*:read` permission (22 "Read-only").
_READ_WRITES = frozenset(
    {
        "previewTradeGroup",
        "validateRule",
        "compileRule",
        "testApiKey",
        "verifyAuditChain",
        "createSupportBundle",
    }
)


def _operation_ids() -> dict[str, tuple[str, str]]:
    return {
        operation["operationId"]: (method.upper(), template)
        for template, item in _spec()["paths"].items()
        for method, operation in item.items()
        if isinstance(operation, dict) and "operationId" in operation
    }


async def test_every_write_refused_except_own_and_protective() -> None:
    gate = _Gate()
    record = await gate.rig.viewing()
    writes = sorted(op for op in _declared() if op[0] not in _SAFE and op not in OWN_OPERATIONS)
    protective = {operation for operation, _ in PROTECTIVE_WRITES.values()}
    assert {_operation_ids()[i] for i in _READ_WRITES} <= set(writes)
    assert protective <= set(writes)  # refused while their handlers are unregistered
    refused: list[tuple[str, str]] = []
    for method, template in writes:
        response = await gate.call(method, _path(template), record)
        if (response.status_code, response.json().get("code")) == (403, "view_as_read_only"):
            refused.append((method, template))
    assert refused == writes and gate.seen == []
    gate.protective.register("amendOrder")
    method, template = PROTECTIVE_WRITES["amendOrder"][0]
    assert (await gate.call(method, _path(template), record)).status_code == 200


async def test_delete_allowed_during_session_read_only() -> None:
    """In the read-only downgrade, leaving view-as passes both guards: the view-as guard passes an
    own operation, and the read-only guard exempts it as it exempts logout."""
    gate = _Gate()
    record = await gate.rig.viewing()
    gate.auth.step_up.read_only.add(str(record.id))
    seen: list[str] = []
    app = FastAPI()

    @app.api_route("/{path:path}", methods=["DELETE", "POST"])
    async def route(request: Request, path: str) -> JSONResponse:
        seen.append(f"{request.method} /{path}")
        return JSONResponse({"ok": True})

    app.middleware("http")(make_read_only_guard(gate.auth))  # inner, as in `create_app`
    guard: Any = make_view_as_guard(
        gate.auth,
        views=lambda: gate.rig.service,
        refusals=lambda: gate.refusals,
        protective=gate.protective,
        operations=_declared(),
        clock=gate.rig.clock,
    )
    app.middleware("http")(guard)
    headers = {"Authorization": f"Bearer {record.id}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        left = await client.delete("/auth/session/view-as", headers=headers)
        refused = await client.post("/orders", headers=headers)
    assert left.status_code == 200 and seen == ["DELETE /auth/session/view-as"]
    assert (refused.status_code, refused.json()["code"]) == (403, "session_read_only")


def test_the_app_as_production_builds_it_serves_a_viewing_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`create_app()` with no auth clock, as `main.py` builds it: an own operation passes, a
    viewing session's write is refused with one record, and nothing answers 500."""

    async def may_view(_self: Any, _user_id: str) -> dict[str, Any]:
        return {"permissions": [Permission.USERS_WRITE.value], "account_scope": []}

    monkeypatch.setattr(_stack.Identity, "session_info", may_view)
    with open_stack(monkeypatch, auth_clock=None) as s:
        assert s.state.view_as is not None  # the real service, as on the SQL backend
        uid, _ = s.add_user("ana")
        target, _ = s.add_user("bo")
        minted = s.call(s.auth.sessions.mint, str(uid))
        headers = {"Authorization": f"Bearer {minted.access_token}"}
        headers |= csrf_headers(s.state.csrf_codec, minted.session_id)
        assert s.client.get("/auth/session", headers=headers).status_code == 200
        store = s.auth.view_as_store
        record = store.sessions[str(minted.session_id)]
        state = ViewAsState.start(uuid.uuid4(), target, now=datetime.now(UTC))
        store.sessions[str(record.id)] = record.model_copy(update={"view_as": state})
        calls: list[str] = []
        real = s.state.view_as_refusals.refuse_operation

        async def counted(*args: Any, **kwargs: Any) -> None:
            calls.append(kwargs["method"])
            await real(*args, **kwargs)

        monkeypatch.setattr(s.state.view_as_refusals, "refuse_operation", counted)
        refused = s.client.post("/orders", headers=headers, json={})
        assert (refused.status_code, refused.json()["code"]) == (403, "view_as_read_only")
        assert calls == ["POST"]
        assert s.client.get("/auth/session", headers=headers).status_code == 200  # own
        assert s.client.post("/auth/logout", headers=headers).status_code == 204
