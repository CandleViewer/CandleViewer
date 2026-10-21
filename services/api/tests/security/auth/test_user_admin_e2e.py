"""E42-T09 (#2649) end to end on the deployed app (SR-029, R5; in-process, no network).

`create_app()` on the real backend over the SQL-edge fakes of `test_disable_user_e2e.py` (the
same rows, rule engine, B16 charts and WS gateway): a `PATCH` to `disabled` runs the whole
disable cascade exactly as the DELETE does, and an Owner's revoke of one of M's sessions writes
the Owner's `users.session_revoked`, then one `auth.session_revoked` through B16, before the row
changes, and closes that session's socket 4401 before the call returns (0 s on the test clock),
leaving M's other session alone. UL-F11 (UL3-E3, D5) on the same app: a session id resolves only
within its own user on both twins, `/users/{userId}/sessions/{sessionId}` and
`/me/sessions/{sessionId}`, and no typed `/auth/*` body sets `status`, `roles` or `mfa_required`.
Postgres: `tests/integration/admin/test_user_admin_pg.py`.
"""

from __future__ import annotations

import functools
import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.deny_by_default import served_operations
from candleviewer.api.sessions import UnlockBody
from candleviewer.auth.models import UserStatus
from candleviewer.ws.revocation import CLOSE_TOKEN_EXPIRED
from tests.csrf_helpers import csrf_headers
from tests.security.auth.test_disable_user_drill import _auth_ws, _recv
from tests.security.auth.test_disable_user_e2e import (
    _M,
    _OWNER,
    _owner_headers,
    _world,
    rule_disarmed,
    scenario,
    sessions_ended,
)


def patch_disable(client: TestClient, m: str, headers: dict[str, str], *, ack: bool) -> Any:
    """The disable as `PATCH /users/{userId}` to `disabled` (E42-T09)."""
    path = f"/users/{m}" + ("?acknowledge_unknown_positions=true" if ack else "")
    return client.patch(path, json={"status": "disabled"}, headers=headers)


@pytest.fixture(scope="module")
def patched() -> Iterator[SimpleNamespace]:
    with _world() as (w, app, client):
        scenario(app, client, w, str(_OWNER), str(_M), disable=patch_disable)
        yield w


def test_patch_disable_runs_the_whole_disable_cascade(patched: SimpleNamespace) -> None:
    """S11 (SR-029): the outcome is the DELETE's: M's next REST calls get 401, every socket of M
    gets `bye user_disabled` and closes 4403 within 5 s (`sessions_ended`), M's rule is disarmed
    through B9, and exactly one `users.disable` is written (`rule_disarmed`). The answer is the
    `User`, disabled, with its `ETag`."""
    sessions_ended(patched, answer=200)
    rule_disarmed(patched, _OWNER, _M)
    body = patched.disabled.json()
    assert (body["id"], body["status"]) == (str(_M), "disabled")
    assert patched.disabled.headers["etag"].startswith('"')


def test_patch_disable_positions_unknown_409(patched: SimpleNamespace) -> None:
    """AC7 (O2): the deployed position source reports the count unknown, so a PATCH to disabled
    without `acknowledge_unknown_positions=true` is 409 `positions_unknown`, as the DELETE is."""
    unacked = patched.unacked
    assert (unacked.status_code, unacked.json()["code"]) == (409, "positions_unknown")
    assert "source: not_deployed" in unacked.json()["detail"]


def _still_open(ws: Any) -> bool:
    ws.send_json({"t": "ping", "id": "p", "p": {}})
    kind: str = _recv(ws)["t"]
    return kind == "pong"


def test_the_owner_revokes_one_of_ms_sessions() -> None:
    """S12: M has two sessions, a socket on each. The Owner revokes one: one `users.session_revoked`
    naming the Owner, then one `auth.session_revoked` for it, both written before its row is
    revoked (R5, the second through B16 REVOKE); its socket gets
    `bye session_revoked` and closes 4401 before the DELETE returns, with the test clock still at
    the instant of the call (well within 5 s); its next REST call is 401. M's other session, its
    socket included, is untouched, and no answer carries token material."""
    with _world() as (w, app, client):
        portal = client.portal
        assert portal is not None  # inside the client's `with`
        run, ctx = portal.call, app.state.app_context
        headers = _owner_headers(app, run, w, str(_OWNER))
        kept, ended = (run(ctx.auth.sessions.mint, str(_M)) for _ in range(2))
        records = ctx.audit.writer.records
        revoke, ahead = w.repo.revoke, list[int]()

        async def counted(session_id: str, **kwargs: Any) -> Any:
            ahead.append(sum(r["action"] == "auth.session_revoked" for r in records))
            return await revoke(session_id, **kwargs)

        w.repo.revoke = counted
        listed = client.get(f"/users/{_M}/sessions", headers=headers)
        with (
            client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws_kept,
            client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws_ended,
        ):
            assert _auth_ws(ws_kept, kept.access_token)["t"] == "auth_ok"
            assert _auth_ws(ws_ended, ended.access_token)["t"] == "auth_ok"
            started = w.clock.now
            gone = client.delete(f"/users/{_M}/sessions/{ended.session_id}", headers=headers)
            bye = _recv(ws_ended)
            with pytest.raises(WebSocketDisconnect) as close:
                _recv(ws_ended)
            assert _still_open(ws_kept)
        assert w.clock.now == started  # the close came before the call returned: 0 s elapsed
        rest = [
            client.get(
                "/auth/session", headers={"Authorization": f"Bearer {s.access_token}"}
            ).status_code
            for s in (kept, ended)
        ]
    assert listed.status_code == 200
    assert {i["id"] for i in listed.json()["items"]} == {
        str(kept.session_id),
        str(ended.session_id),
    }
    assert gone.status_code == 204 and gone.content == b""
    assert (bye["t"], bye["p"]["reason"], close.value.code) == (
        "bye",
        "session_revoked",
        CLOSE_TOKEN_EXPIRED,
    )
    assert rest == [200, 401]
    (record,) = [r for r in records if r["action"] == "auth.session_revoked"]
    assert (record["session_id"], record["reason"]) == (str(ended.session_id), "admin")
    assert ahead == [1]  # written before the row was revoked
    (owner,) = [r for r in records if r["action"] == "users.session_revoked"]
    assert str(owner["actor_user_id"]) == str(_OWNER) and owner["reason"] == "admin"
    assert (owner["object_kind"], owner["object_id"]) == ("session", str(ended.session_id))
    assert owner["after_state"]["user_id"] == str(_M)
    assert records.index(owner) < records.index(record)  # the Owner's record, ahead of B16's
    for minted in (kept, ended):  # no token material in any answer
        for secret in (minted.access_token, minted.refresh_token):
            assert secret not in listed.text and secret not in gone.text
    assert uuid.UUID(record["session_id"]) == ended.session_id


def _bearer(app: Any, minted: Any) -> dict[str, str]:
    """M's own full session, as the browser presents it: its bearer and SR-041 token."""
    bearer = {"Authorization": f"Bearer {minted.access_token}"}
    return bearer | csrf_headers(app.state.csrf_codec, minted.session_id)


def test_other_users_session_404_on_both_paths() -> None:
    """UL-F11 (UL3-E3, D5): `test_other_users_session_404`'s ids on the deployed app, through both
    twins. Through M's admin path the Owner names another user's session (one of the Owner's
    own), an unknown id and an ended session of M; through `/me/sessions` M names the same three.
    Each is one 404 (`not_found` on the admin path): no session is revoked, recorded as revoked
    or closed, so every live session still answers its next REST call."""
    with _world() as (w, app, client):
        portal = client.portal
        assert portal is not None  # inside the client's `with`
        run, ctx = portal.call, app.state.app_context
        sessions = ctx.auth.sessions
        owner = _owner_headers(app, run, w, str(_OWNER))
        theirs, mine, ended = (run(sessions.mint, u) for u in (str(_OWNER), str(_M), str(_M)))
        run(functools.partial(sessions.revoke, str(ended.session_id), reason="logout"))
        published, records = len(w.published), ctx.audit.writer.records
        ids = (theirs.session_id, uuid.uuid4(), ended.session_id)
        admin = [client.delete(f"/users/{_M}/sessions/{sid}", headers=owner) for sid in ids]
        own = [client.delete(f"/me/sessions/{sid}", headers=_bearer(app, mine)) for sid in ids]
        rest = [
            client.get("/auth/session", headers={"Authorization": f"Bearer {s.access_token}"})
            for s in (theirs, mine)
        ]
        revoked = [r["action"] for r in records if r["action"].endswith("session_revoked")]
    assert [(r.status_code, r.json()["code"]) for r in admin] == [(404, "not_found")] * 3
    assert [r.status_code for r in own] == [404] * 3
    assert revoked == [] and len(w.published) == published  # nothing revoked, nothing closed
    assert [r.status_code for r in rest] == [200, 200]


#: SR-026, D5 (UL3-E3): the admin-only `User` fields that no self-service body may set.
_ADMIN_FIELDS: dict[str, Any] = {"status": "active", "roles": ["owner"], "mfa_required": False}
#: Each typed `/auth/*` write the app serves (a contract operation with a request body) and its
#: answer to `_ADMIN_FIELDS` on M's own full session. A declared model refuses them before its
#: handler runs (FastAPI's 422 `validation_failed`, each `extra_forbidden`); refresh and logout
#: refuse keys outside their closed sets (422); a step-up body otherwise whole is 400
#: `validation_failed` for them alone, before any factor is checked. Unlock answers M's unlocked
#: session `409` before any body is read; the one it reads, `UnlockBody`, is closed (below).
_SELF_SERVICE_WRITES: dict[tuple[str, str], int] = {
    ("POST", "/auth/login"): 422,
    ("POST", "/auth/logout"): 422,
    ("POST", "/auth/mfa/enroll"): 422,
    ("POST", "/auth/mfa/enroll/confirm"): 422,
    ("POST", "/auth/mfa/recovery"): 422,
    ("POST", "/auth/mfa/verify"): 422,
    ("POST", "/auth/refresh"): 422,
    ("POST", "/auth/step-up"): 400,
    ("POST", "/auth/unlock"): 409,
}
#: The writes whose 422 is FastAPI's, naming each refused field.
_DECLARED: tuple[str, ...] = ("/auth/login", "/auth/mfa/enroll", "/auth/mfa/enroll/confirm")
_DECLARED += ("/auth/mfa/recovery", "/auth/mfa/verify")


def test_self_service_never_sets_admin_fields() -> None:
    """UL-F11 (UL3-E3, SR-026, D5), S10: `status`, `roles` and `mfa_required` in the body of
    each typed `/auth/*` write of the deployed app are refused on M's own session, and M's user,
    roles and grants are untouched: no statement of the user stores runs and no user or role
    record is written. Unlock's closed body refuses them as well. `PATCH /me/preferences`
    (`not_mounted`) owes the other half once the ticket that mounts it serves it."""
    spec: dict[str, Any] = load_openapi_spec()
    typed = {
        (method.upper(), path)
        for path, item in spec["paths"].items()
        if path.startswith("/auth/")
        for method, op in item.items()
        if isinstance(op, dict) and "requestBody" in op
    }
    with _world() as (w, app, client):
        portal = client.portal
        assert portal is not None  # inside the client's `with`
        run, ctx = portal.call, app.state.app_context
        writes = sorted(typed & served_operations(app))
        headers = _bearer(app, run(ctx.auth.sessions.mint, str(_M)))
        whole = {"code": "000000", "password": "x"}  # step-up: only the extra members are wrong
        answers = {
            (method, path): client.request(
                method,
                path,
                json=(whole if path == "/auth/step-up" else {}) | _ADMIN_FIELDS,
                headers=headers,
            )
            for method, path in writes
        }
        actions = [r["action"] for r in ctx.audit.writer.records]
    assert set(writes) == set(_SELF_SERVICE_WRITES)  # a new typed write is classified here first
    assert {key: r.status_code for key, r in answers.items()} == _SELF_SERVICE_WRITES
    for path in _DECLARED:
        errors = answers["POST", path].json()["errors"]
        refused = {e["field"] for e in errors if e["rule"] == "extra_forbidden"}
        assert refused == {f"body.{name}" for name in _ADMIN_FIELDS}, path
    for path in ("/auth/logout", "/auth/refresh"):
        assert answers["POST", path].json()["detail"] == "unexpected fields in body", path
    step_up = answers["POST", "/auth/step-up"].json()
    assert step_up["code"] == "validation_failed"  # the members are refused, never named
    assert [(e["field"], e["rule"]) for e in step_up["errors"]] == [("body", "extra_forbidden")] * 3
    assert w.repo.statements == []  # no user, role or grant statement ran
    assert (w.repo.status(_M), w.repo.roles[_M]) == (UserStatus.ACTIVE, frozenset({"manager"}))
    assert not [a for a in actions if a.partition(".")[0] in ("users", "roles", "grants")]
    with pytest.raises(ValidationError) as unlock:
        UnlockBody.model_validate({"password": "x", **_ADMIN_FIELDS})
    extra = {str(e["loc"][0]) for e in unlock.value.errors() if e["type"] == "extra_forbidden"}
    assert extra == set(_ADMIN_FIELDS)
