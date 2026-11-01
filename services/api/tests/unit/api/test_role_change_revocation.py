"""SR-013 (#2101): a change to a user's role set ends every live session of the user (the ruling's
C-1, C-3, C-6 and C-7), on `PUT /users/{userId}/roles` and on `PATCH /users/{userId}` with
`roles`.

Over the real `SessionService`, B16 `SessionChart` and WS `RevocationHub`, with the users routers'
in-memory stores (`test_user_admin_routes`). Each revocation is recorded (`auth.session_revoked`,
reason `role_changed`) inside the change's write-ahead hook, so a refused record rolls the change
back; the rows are revoked after the commit, every member of each rotation family published, then
the role push runs. The target's tokens and refresh tokens are refused afterwards, its sockets
close `4401`; the actor's and a third user's sessions stay; a refused, no-op or failed change ends
nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from candleviewer.admin.lifecycle_metrics import user_lifecycle_steps_total
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.users import make_user_admin_router, make_users_router
from candleviewer.app import _hub_publisher
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.errors import SessionRevoked
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import MintedSession
from candleviewer.auth.owner_floor import assert_owner_floor
from candleviewer.auth.session_chart import SessionChart
from candleviewer.auth.session_service import SessionService
from candleviewer.statechart.bindings import b16_session
from candleviewer.ws.revocation import RevocationHub
from tests.conftest import RecordingAuditSink
from tests.unit.api.test_user_admin_routes import (
    _T0,
    CALLER,
    M,
    _Auth,
    _Emitter,
    _Log,
    _principal,
    _Rows,
    _Sessions,
    _StepUp,
    _Store,
    _user,
)

THIRD = uuid.uuid4()
_SPEC = load_openapi_spec()
_Hook = Callable[[], Awaitable[None]]


def _steps(outcome: str) -> float:  # the session revoke's `cv_user_lifecycle_steps_total`, a delta
    sample = user_lifecycle_steps_total.labels(step="session_revoke", outcome=outcome)
    return float(sample._value.get())


class _RoleStore:
    """`UserRoleStore` in memory, as the SQL store runs it: under its "lock" the owner floor, the
    write-ahead `audit` with the roles read under the lock, then the commit; nothing changes when
    either raises. `at_commit` runs where the commit lands, after the hook."""

    def __init__(self, log: _Log, roles: dict[uuid.UUID, frozenset[str]]) -> None:
        self.log, self.roles = log, roles
        self.at_commit: _Hook | None = None

    async def get_roles(self, user_id: uuid.UUID) -> frozenset[str] | None:
        return self.roles.get(user_id)

    async def get_status(self, user_id: uuid.UUID) -> str | None:
        return "active" if user_id in self.roles else None

    async def count_active_owners(self) -> int:
        return sum("owner" in held for held in self.roles.values())

    async def apply_roles(
        self,
        user_id: uuid.UUID,
        roles: frozenset[str],
        *,
        actor: uuid.UUID,
        audit: Callable[[frozenset[str]], Awaitable[None]],
    ) -> bool:
        if user_id not in self.roles:
            return False
        before = self.roles[user_id]
        owners = await self.count_active_owners()
        assert_owner_floor(current_roles=before, new_roles=roles, active_owner_count=owners)
        await audit(before)
        if self.at_commit is not None:
            await self.at_commit()
        self.roles[user_id] = roles
        self.log.append("commit")
        return True


class _AdminStore(_Store):
    """The PATCH store, with the same `at_commit` seam just ahead of its commit."""

    at_commit: _Hook | None = None

    async def update_user(self, user_id: uuid.UUID, patch: Any, **kw: Any) -> Any:
        audit = kw.pop("audit")

        async def hooked(change: Any) -> None:
            await audit(change)
            if self.at_commit is not None:
                await self.at_commit()

        return await super().update_user(user_id, patch, audit=hooked, **kw)


@dataclass
class _World:
    """One app serving one of the two role routes, its stores and the session world."""

    route: str
    client: TestClient
    log: _Log
    emitter: _Emitter
    rows: _Rows
    sessions: _Sessions
    closed: dict[str, tuple[str, int]]
    pushed: list[uuid.UUID]
    live_at_push: list[set[str]]  # the pushed user's live sessions as the push runs
    hub: RevocationHub
    set_at_commit: Callable[[_Hook | None], None]
    roles_of: Callable[[uuid.UUID], frozenset[str]]
    set_roles: Callable[[uuid.UUID, frozenset[str]], None]

    def change(self, target: uuid.UUID, roles: list[str]) -> Any:
        if self.route == "put":
            return self.client.put(f"/users/{target}/roles", json={"roles": roles})
        return self.client.patch(f"/users/{target}", json={"roles": roles})

    async def mint(self, user: uuid.UUID) -> MintedSession:
        """A live session of *user*, with a socket on it."""
        minted = await self.sessions.mint(str(user))
        self.socket(str(minted.session_id))
        return minted

    def socket(self, session_id: str) -> None:
        async def close(frame: dict[str, Any], code: int) -> None:
            self.closed[session_id] = (frame["p"]["reason"], code)

        self.hub.register(session_id, close)

    def live(self, user: uuid.UUID) -> set[str]:
        return {
            str(s.id) for s in self.rows.sessions.values() if s.user_id == user and not s.revoked_at
        }


def _world(b16: RecordingAuditSink, route: str, role: str = "owner") -> _World:
    log = _Log()
    emitter, rows, hub = _Emitter(log), _Rows(log, b16), RevocationHub()
    sessions = _Sessions(rows, Hasher(), clock=lambda: _T0, publish_revocation=_hub_publisher(hub))
    auth = _Auth(sessions, _StepUp(log, elevated=True, chart=SessionChart()))
    closed: dict[str, tuple[str, int]] = {}
    pushed: list[uuid.UUID] = []
    live_at_push: list[set[str]] = []

    async def roles_changed(user_id: uuid.UUID) -> None:
        pushed.append(user_id)
        rows_of = [s for s in rows.sessions.values() if s.user_id == user_id]
        live_at_push.append({str(s.id) for s in rows_of if not s.revoked_at})

    notifier = SimpleNamespace(roles_changed=roles_changed)
    principal = _principal(role, _SPEC)
    app = FastAPI()
    if route == "put":
        store = _RoleStore(
            log,
            {
                CALLER: frozenset({"owner"}),
                M: frozenset({"manager"}),
                THIRD: frozenset({"manager"}),
            },
        )
        resolver = SimpleNamespace(resolve=lambda request: principal)
        app.include_router(
            make_users_router(store, emitter, resolver, notifier, auth=cast(Any, auth))
        )

        def set_put(hook: _Hook | None) -> None:
            store.at_commit = hook

        set_at_commit, roles_of, set_roles = (
            set_put,
            store.roles.__getitem__,
            store.roles.__setitem__,
        )
    else:
        admin = _AdminStore(
            log, _user(CALLER, ("owner",)), _user(M, ("manager",)), _user(THIRD, ("manager",))
        )
        resolver = SimpleNamespace(resolve=lambda request: principal)
        app.include_router(
            make_user_admin_router(admin, emitter, resolver, notifier, auth=cast(Any, auth))
        )

        def set_patch(hook: _Hook | None) -> None:
            admin.at_commit = hook

        def roles_patch(user: uuid.UUID) -> frozenset[str]:
            return frozenset(admin.users[user]["roles"])

        def seed_patch(user: uuid.UUID, roles: frozenset[str]) -> None:
            admin.users[user]["roles"] = sorted(roles)

        set_at_commit, roles_of, set_roles = set_patch, roles_patch, seed_patch
    client = TestClient(app, headers={"Authorization": "Bearer tok"}, raise_server_exceptions=False)
    return _World(
        route,
        client,
        log,
        emitter,
        rows,
        sessions,
        closed,
        pushed,
        live_at_push,
        hub,
        set_at_commit,
        roles_of,
        set_roles,
    )


ROUTES = pytest.mark.parametrize("route", ["put", "patch"])


@ROUTES
async def test_a_role_change_ends_every_session_of_the_target(
    b16_audit: RecordingAuditSink, route: str
) -> None:
    """Fails on `main`: the target's tokens and refresh tokens kept working after the change, and
    no socket closed. Both sessions now refuse both, and every socket closes `4401`, the one still
    on a session a refresh rotated out too (C-3: the family publish, 23 :472)."""
    w = _world(b16_audit, route)
    first, second = await w.mint(M), await w.mint(M)
    refreshed = await w.sessions.refresh(first.refresh_token)  # `first` rotated out, its socket
    w.socket(str(refreshed.minted.session_id))  # stays on it until a re-`auth`; the new one too

    r = w.change(M, ["viewer"])

    assert r.status_code == 200, r.text
    assert w.live(M) == set()
    for token in (refreshed.minted.access_token, second.access_token):
        with pytest.raises(SessionRevoked):
            await SessionService.authenticate_access_token(w.sessions, token)
    for refresh in (refreshed.minted.refresh_token, second.refresh_token):
        with pytest.raises(SessionRevoked):
            await w.sessions.refresh(refresh)
    ended = {str(first.session_id), str(second.session_id), str(refreshed.minted.session_id)}
    assert w.closed == dict.fromkeys(ended, ("session_revoked", 4401))
    reasons = {str(s.id): s.revoked_reason for s in w.rows.sessions.values()}
    assert reasons.pop(str(first.session_id)) == "rotated"  # the refresh's, not this change's
    assert set(reasons.values()) == {"role_changed"}


@ROUTES
async def test_a_role_change_records_each_revocation_ahead_and_revokes_after_the_commit(
    b16_audit: RecordingAuditSink, route: str
) -> None:
    """C-7: at the commit both records are written and both rows still live; then the rows are
    revoked, before the role push (C-6)."""
    w = _world(b16_audit, route)
    sessions = {str((await w.mint(M)).session_id) for _ in range(2)}
    seen: dict[str, Any] = {}

    async def at_commit() -> None:
        seen["recorded"] = [
            c["session_id"] for c in b16_audit.calls if c["action"] == "auth.session_revoked"
        ]
        seen["live"] = w.live(M)

    w.set_at_commit(at_commit)
    r = w.change(M, ["viewer"])

    assert r.status_code == 200, r.text
    assert set(seen["recorded"]) == sessions and seen["live"] == sessions
    revoked = [c for c in b16_audit.calls if c["action"] == "auth.session_revoked"]
    assert {c["reason"] for c in revoked} == {"role_changed"} and len(revoked) == 2
    assert all(c["actor_user_id"] == str(M) for c in revoked)  # B16 names the session's user
    assert (w.pushed, w.live_at_push) == ([M], [set()])  # C-6: revoked, then pushed


@ROUTES
async def test_a_refused_revocation_record_rolls_the_change_back_with_503(
    route: str,
) -> None:
    """C-7: the record is written inside the hook, so the change falls with a refused one."""

    class _Refusing(RecordingAuditSink):
        async def emit(self, action: str, **kwargs: Any) -> None:
            if action == "auth.session_revoked":
                raise AuditUnavailable("WAL unwritable")
            await super().emit(action, **kwargs)

    sink = _Refusing()
    b16_session.set_audit_sink(sink)
    try:
        w = _world(sink, route)
        mine = await w.mint(M)
        r = w.change(M, ["viewer"])
    finally:
        b16_session.set_audit_sink(None)

    assert (r.status_code, r.json()["code"]) == (503, "audit_unavailable")
    assert w.roles_of(M) == frozenset({"manager"})
    assert w.live(M) == {str(mine.session_id)} and not w.closed
    assert "commit" not in w.log


@ROUTES
async def test_a_store_failure_after_the_commit_is_503_store_unavailable_and_counted(
    b16_audit: RecordingAuditSink, route: str
) -> None:
    """C-7: the roles stand; the answer names the per-session `DELETE` as the repair, the step
    is counted and logged, and the role push still runs."""
    w = _world(b16_audit, route)
    await w.mint(M)

    async def down(*_a: Any, **_k: Any) -> Any:
        raise ConnectionRefusedError(111, "database down")  # an outage (an OSError)

    w.rows.revoke_all_for_user = down  # type: ignore[method-assign]  # the revoke's store is down
    failed = _steps("failed")
    with capture_logs() as logs:
        r = w.change(M, ["viewer"])

    assert (r.status_code, r.json()["code"]) == (503, "store_unavailable")
    assert "DELETE /users/{userId}/sessions/{sessionId}" in r.json()["detail"]
    assert w.roles_of(M) == frozenset({"viewer"}) and w.pushed == [M]
    assert _steps("failed") == failed + 1
    (line,) = [e for e in logs if e.get("step") == "session_revoke"]
    assert (line["log_level"], line["outcome"], line["error"]) == (
        "error",
        "failed",
        "ConnectionRefusedError",
    )


@ROUTES
async def test_a_no_op_role_write_ends_no_session(
    b16_audit: RecordingAuditSink, route: str
) -> None:
    """C-1: the same role set again, as a repeat of an applied change is (C-5: the repeat of a
    `200` never re-runs the revoke): nothing recorded, nothing revoked."""
    w = _world(b16_audit, route)
    kept = await w.mint(M)

    r = w.change(M, ["manager"])

    assert r.status_code == 200, r.text
    assert w.live(M) == {str(kept.session_id)} and not w.closed
    assert "auth.session_revoked" not in b16_audit.actions()


@ROUTES
async def test_a_repeated_role_change_ends_no_session_minted_since(
    b16_audit: RecordingAuditSink, route: str
) -> None:
    w = _world(b16_audit, route)
    await w.mint(M)
    assert w.change(M, ["viewer"]).status_code == 200
    again = await w.mint(M)  # the target signs in again, under the new roles

    r = w.change(M, ["viewer"])

    assert r.status_code == 200
    assert w.live(M) == {str(again.session_id)}


@ROUTES
async def test_the_last_owner_floor_409_ends_no_session(
    b16_audit: RecordingAuditSink, route: str
) -> None:
    """C-1: M is the last active owner (the caller's row holds none), so its demotion is
    refused `409` and ends nothing."""
    w = _world(b16_audit, route)
    w.set_roles(CALLER, frozenset({"viewer"}))
    w.set_roles(M, frozenset({"owner"}))
    kept = await w.mint(M)

    r = w.change(M, ["manager"])

    assert (r.status_code, r.json()["code"]) == (409, "conflict")
    assert w.live(M) == {str(kept.session_id)} and not w.closed
    assert "auth.session_revoked" not in b16_audit.actions()


@ROUTES
@pytest.mark.parametrize("role", ["manager", "viewer"])
async def test_a_forbidden_role_is_403_and_ends_no_session(
    b16_audit: RecordingAuditSink, route: str, role: str
) -> None:
    w = _world(b16_audit, route, role=role)
    kept = await w.mint(M)

    r = w.change(M, ["viewer"])

    assert (r.status_code, r.json()["code"]) == (403, "forbidden")
    assert w.live(M) == {str(kept.session_id)} and not w.closed
    assert w.roles_of(M) == frozenset({"manager"})
    assert "auth.session_revoked" not in b16_audit.actions()


@ROUTES
async def test_a_self_target_is_403_and_the_actors_sessions_stay(
    b16_audit: RecordingAuditSink, route: str
) -> None:
    """SR-055: the actor's own sessions are never touched (C-1)."""
    w = _world(b16_audit, route)
    mine = await w.mint(CALLER)

    r = w.change(CALLER, ["manager"])

    assert r.status_code == 403
    assert w.live(CALLER) == {str(mine.session_id)} and not w.closed


@ROUTES
async def test_the_actors_and_a_third_users_sessions_are_untouched(
    b16_audit: RecordingAuditSink, route: str
) -> None:
    """The cross-user case: only the target's sessions end."""
    w = _world(b16_audit, route)
    mine, theirs = await w.mint(CALLER), await w.mint(THIRD)
    await w.mint(M)

    r = w.change(M, ["viewer"])

    assert r.status_code == 200
    assert w.live(CALLER) == {str(mine.session_id)}
    assert w.live(THIRD) == {str(theirs.session_id)}
    assert str(mine.session_id) not in w.closed and str(theirs.session_id) not in w.closed
    assert len(w.closed) == 1  # the target's one socket


@ROUTES
async def test_a_session_minted_after_the_hook_is_revoked_and_recorded_after(
    b16_audit: RecordingAuditSink, route: str
) -> None:
    """A session the hook could not record (a sign-in or a refresh between the hook and the
    commit) is revoked with the rest and recorded after the fact: never under-reported."""
    w = _world(b16_audit, route)
    await w.mint(M)
    late: list[str] = []

    async def at_commit() -> None:
        late.append(str((await w.sessions.mint(str(M))).session_id))

    w.set_at_commit(at_commit)
    r = w.change(M, ["viewer"])

    assert r.status_code == 200, r.text
    assert w.live(M) == set()
    recorded = [c["session_id"] for c in b16_audit.calls if c["action"] == "auth.session_revoked"]
    assert late[0] in recorded and len(recorded) == 2
