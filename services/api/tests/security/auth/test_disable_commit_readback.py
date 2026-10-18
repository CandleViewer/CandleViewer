"""#3445 (#2710 option C, R5) on the deployed app: `DELETE /users/{userId}` whose COMMIT applies
its writes, then raises. `test_disable_user_e2e.py`'s world, with the real session, step-up and B16
services; only the commit is faulted, and the read-back's statement is modelled on the rows."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from candleviewer.storage.repositories import user_lifecycle_sqlalchemy as lifecycle
from tests.security.auth import test_disable_user_e2e as e2e
from tests.security.auth.test_disable_user_drill import _auth_ws

_PATH = f"/users/{e2e._M}?acknowledge_unknown_positions=true"


class _Lost(e2e._Rows):
    """The world's rows, whose first COMMIT applies its writes, then raises. `fault`, if set, is
    raised by the statement after it, the read-back's first, once."""

    def __init__(self, fault: Exception | None = None) -> None:
        super().__init__()
        self.fault, self.lost, self.armed = fault, False, False

    def _read(self, stmt: Any, user: uuid.UUID, params: dict[str, Any], writes: list[Any]) -> Any:
        armed, self.armed = self.armed, False
        if armed and self.fault is not None:
            raise self.fault
        if stmt is lifecycle._REVOKED_AT:  # the read-back's sessions: this instant, this reason
            ended = (params["at"], params["reason"])
            mine = [s for s in self.sessions.values() if s.user_id == user]
            return [(s.id,) for s in mine if (s.revoked_at, s.revoked_reason) == ended]
        return super()._read(stmt, user, params, writes)

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async with super().unit_of_work() as uow:

            async def commit() -> None:
                await uow.commit()  # every write lands
                if not self.lost:
                    self.lost = self.armed = True
                    raise OSError("commit lost")

            yield SimpleNamespace(session=uow.session, commit=commit)


def _run(rows: _Lost, deletes: int) -> SimpleNamespace:
    """M's two sessions, a socket on each; the Owner's DELETEs of M; then what each saw."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(e2e, "_Rows", lambda: rows)  # `_world` builds its rows by this name
        with e2e._world() as (w, app, client):
            portal = client.portal
            assert portal is not None  # inside the client's `with`
            run, sessions = portal.call, app.state.app_context.auth.sessions
            headers = e2e._owner_headers(app, run, w, str(e2e._OWNER))
            w.a, w.b = run(sessions.mint, str(e2e._M)), run(sessions.mint, str(e2e._M))
            with (
                client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws_a,
                client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws_b,
            ):
                pairs = ((ws_a, w.a), (ws_b, w.b))
                w.auth = [_auth_ws(ws, s.access_token)["t"] for ws, s in pairs]
                w.answers = [client.delete(_PATH, headers=headers) for _ in range(deletes)]
                w.ended = [e2e._ended(ws) for ws in (ws_a, ws_b)]
            w.records = list(app.state.app_context.audit.writer.records)
    return w


def _checks(w: SimpleNamespace) -> tuple[list[Any], list[str]]:
    """Every socket got `bye user_disabled` and 4403 (§9.5); the `users.disable` records' outcome
    and reason; the sessions B16 REVOKE recorded (`auth.session_revoked`, R5)."""
    for bye, code in w.ended:
        p = bye["p"]
        assert (bye["t"], p["reason"], p["reconnect"], p["code"], code) == e2e._BYE
    records = [
        (r["action"], r.get("outcome"), r.get("reason"), r.get("session_id")) for r in w.records
    ]
    disables = [r[1:3] for r in records if r[0] == "users.disable"]
    return disables, sorted(r[3] for r in records if r[0] == "auth.session_revoked")


def test_lost_commit_read_back_revokes_each_session_once_and_closes_every_socket() -> None:
    """AC1, AC2: the read-back finds M disabled, so the DELETE answers 204 after the steps: every
    socket of M closed, one B16 REVOKE per session, and the trail `success`, `outcome_unknown`,
    then the recovered `success`, ahead of every step's record; none updated or deleted."""
    w = _run(_Lost(), deletes=1)
    assert w.auth == ["auth_ok"] * 2 and [r.status_code for r in w.answers] == [204]
    disables, revoked = _checks(w)
    recovered = ("success", "recovered_after_commit_error")
    assert disables == [("success", None), ("failure", "outcome_unknown"), recovered]
    assert revoked == sorted(str(s.session_id) for s in (w.a, w.b))
    actions = [r["action"] for r in w.records]
    last_disable = max(i for i, action in enumerate(actions) if action == "users.disable")
    assert last_disable < actions.index("auth.session_revoked")


def test_failed_read_back_is_503_outcome_unknown_and_the_repeat_is_the_noop() -> None:
    """AC5: the read-back fails, so the DELETE answers 503 `store_unavailable`, `outcome_unknown`
    last, no step. The repeat is AC5's no-op 204: no record, every socket of M closed by the
    per-user close, but no B16 REVOKE for either session (UL1-R1 (R5))."""
    w = _run(_Lost(OSError("read-back refused")), deletes=2)
    first, repeat = w.answers
    assert (first.status_code, first.json()["code"]) == (503, "store_unavailable")
    assert repeat.status_code == 204
    disables, revoked = _checks(w)
    assert disables == [("success", None), ("failure", "outcome_unknown")] and revoked == []
