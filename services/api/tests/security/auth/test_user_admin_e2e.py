"""E42-T09 (#2649) end to end on the deployed app (SR-029, R5; in-process, no network).

`create_app()` on the real backend over the SQL-edge fakes of `test_disable_user_e2e.py` (the
same rows, rule engine, B16 charts and WS gateway): a `PATCH` to `disabled` runs the whole
disable cascade exactly as the DELETE does, and an Owner's revoke of one of M's sessions writes
the Owner's `users.session_revoked`, then one `auth.session_revoked` through B16, before the row
changes, and closes that session's socket 4401 before the call returns (0 s on the test clock),
leaving M's other session alone.
Postgres: `tests/integration/admin/test_user_admin_pg.py`.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from candleviewer.ws.revocation import CLOSE_TOKEN_EXPIRED
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
