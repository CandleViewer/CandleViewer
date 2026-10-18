"""E42-T04 S7 (#965): AC1 end to end on the deployed app (SR-029; in-process, no network).

`create_app()` on the real backend with nothing injected but the test clock (#2086), so the
composition root builds the disable service itself and the test pins the arguments of
`build_user_disable_service` at its call site. Only the SQL edges are faked: the rows behind the
S3 store's statements, the identity and scope reads (O5: only an `active` user holds a
permission) and the rule store, under the app's own rule manager and B9 charts. The session,
step-up and B16 services are the real ones. Manager M has two sessions, a socket on each, an armed
rule and a frozen grant with a cap; a refresh of a third session of M has claimed it and waits to
mint (#2911). The Owner disables M, once. Postgres: `test_user_disable_route_pg.py`.
"""

from __future__ import annotations

import asyncio
import functools
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.websockets import WebSocketDisconnect

import candleviewer.app as appmod
from candleviewer.auth.envelope import TotpEncryptor
from candleviewer.auth.errors import UserDisabled
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import SessionRecord, UserStatus
from candleviewer.auth.session_service import SessionService
from candleviewer.auth.step_up import StepUpService
from candleviewer.rules.manager import InMemoryRuleStore
from candleviewer.settings import Settings
from candleviewer.storage.repositories import owner_floor_sqlalchemy as floor
from candleviewer.storage.repositories import user_lifecycle_sqlalchemy as lifecycle
from candleviewer.storage.repositories.identity_sqlalchemy import SqlAlchemyIdentityProvider
from candleviewer.storage.repositories.scope_sqlalchemy import SqlAlchemyScopeSource
from candleviewer.storage.repositories.sessions_sqlalchemy import SqlAlchemySessionRepository
from candleviewer.ws.gateway import make_ws_router
from candleviewer.ws.revocation import CLOSE_USER_DISABLED
from tests.contract.rbac.rbac_harness import _AuditSink, load_contract, role_permissions
from tests.csrf_helpers import csrf_headers
from tests.rules.test_rules_manager import _active_hash, _ir
from tests.security.auth.test_disable_user_drill import _ORIGIN, _auth_ws, _Clock, _recv
from tests.unit.auth.auth_fakes import FakeUserRepository
from tests.unit.auth.mfa_fakes import FakeMfaRepository
from tests.unit.auth.session_fakes import FakeSessionRepository
from tests.unit.test_user_cascade_wiring import _actor

_OWNER, _M = uuid.UUID(int=0x5701), uuid.UUID(int=0x5702)
_ACCOUNT = uuid.UUID(int=0x57A)  # M's grant: frozen, with a cap (O4)
_CODES = role_permissions(load_contract())
_GUARD_S = 5.0  # bounds every wait on the app's loop: a regression fails instead of hanging
_BYE = ("bye", "user_disabled", False, CLOSE_USER_DISABLED, CLOSE_USER_DISABLED)
_DISARMED = ("disarmed", "disarmed")  # `disabled_reason` and the B9 leaf
_Write = Callable[[], Awaitable[object]]


class _Rows(FakeSessionRepository):
    """The rows behind the SQL edges: `sessions` (the fake), `users.status` (its
    `user_statuses`), roles and grants. Once `park` is set, a mint waits for it: a refresh has
    claimed its session and has not minted the successor yet."""

    def __init__(self) -> None:
        super().__init__()
        self.roles = {_OWNER: frozenset({"owner"}), _M: frozenset({"manager"})}
        cap = {"frozen": True, "frozen_reason": "drawdown", "max_daily_loss_usd": Decimal(250)}
        self.grants: dict[tuple[uuid.UUID, uuid.UUID], dict[str, Any]] = {
            (_M, _ACCOUNT): {"can_view": True, "can_trade": True, **cap}
        }
        self.statements: list[Any] = []
        self.park: asyncio.Event | None = None
        self.parked = asyncio.Event()

    def status(self, user: object) -> UserStatus | None:
        return self._user_status(str(user))

    async def create_session(self, session: SessionRecord) -> SessionRecord | None:
        if self.park is not None:
            self.parked.set()
            await self.park.wait()
        return await super().create_session(session)

    async def user(self, user_id: str) -> dict[str, Any]:  # `SqlAlchemyIdentityProvider.user`
        uid, status = uuid.UUID(user_id), self.status(user_id)
        if status is None or uid not in self.roles:
            raise LookupError(user_id)
        name = f"u{uid.hex[-4:]}"
        named = {"id": user_id, "username": name, "email": f"{name}@example.invalid"}
        return named | {"roles": sorted(self.roles[uid]), "status": status.value}

    async def session_info(self, user_id: str) -> dict[str, Any]:
        uid = uuid.UUID(user_id)
        viewed = [str(acct) for acct, view, _ in await self.load_grants(uid) if view]
        return {"permissions": sorted(await self.load_permissions(uid)), "account_scope": viewed}

    async def load_grants(self, owner: uuid.UUID) -> list[tuple[uuid.UUID, bool, bool]]:
        rows = self.grants.items()
        return [(acct, g["can_view"], g["frozen"]) for (user, acct), g in rows if user == owner]

    async def load_permissions(self, owner: uuid.UUID) -> frozenset[str]:
        """O5: a user who is not `active` holds no permission, whatever their roles."""
        if self.status(owner) is not UserStatus.ACTIVE:
            return frozenset()
        return frozenset().union(*(_CODES[role] for role in self.roles.get(owner, ())))

    def _owners(self, stmt: Any) -> list[tuple[Any, ...]]:
        owners = [u for u, r in self.roles.items() if "owner" in r]
        active = [(u,) for u in owners if self.status(u) is UserStatus.ACTIVE]
        return active if stmt is floor.LOCK_OWNERS else [(len(active),)]

    def _read(
        self, stmt: Any, user: uuid.UUID, params: dict[str, Any], writes: list[_Write]
    ) -> Any:
        """One statement of the S3 store's disable about `user`; its writes land at the commit.
        Any other statement fails the test: no DELETE, for one, is modelled."""
        if stmt is floor.LOCK_USER:
            status = self.status(user)
            return [] if status is None else [(status.value,)]
        if stmt is floor.ROLES:
            return [SimpleNamespace(_mapping={"roles": sorted(self.roles[user])})]
        if stmt is lifecycle._DISABLE:
            writes.append(functools.partial(self._set_status, user, UserStatus.DISABLED))
            return []
        if stmt is lifecycle._LIVE_GRANTS:
            live = sorted((acct, g) for (u, acct), g in self.grants.items() if u == user)
            return [(acct, g["can_trade"]) for acct, g in live if g["can_view"]]
        if stmt is lifecycle._REVOKE_GRANTS:
            for acct in params["revoked"]:
                writes.append(functools.partial(self._soft_revoke, (user, uuid.UUID(acct))))
            return []
        raise AssertionError(f"a statement this world does not model: {stmt}")

    async def _set_status(self, user: uuid.UUID, status: UserStatus) -> None:
        self.user_statuses[str(user)] = status

    async def _soft_revoke(self, key: Any) -> None:
        self.grants[key] |= {"can_view": False, "can_trade": False}

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        """The S3 store's unit of work over these rows."""
        writes: list[_Write] = []

        async def execute(stmt: Any, params: dict[str, Any] | None = None) -> Any:
            self.statements.append(stmt)
            p = params or {}
            if stmt in (floor.LOCK_OWNERS, floor.COUNT_OWNERS, floor.CONSTRAINTS_NOW):
                rows: Any = [] if stmt is floor.CONSTRAINTS_NOW else self._owners(stmt)
            elif stmt is lifecycle._REVOKE_SESSIONS:  # the rows live when the statement runs
                live = await self.find_live_by_user(p["id"])
                for s in live:
                    revoke = functools.partial(self.revoke, str(s.id))
                    writes.append(functools.partial(revoke, reason=p["reason"], now=p["now"]))
                rows = [(s.id,) for s in live]
            else:
                rows = self._read(stmt, uuid.UUID(p["id"]), p, writes)
            return SimpleNamespace(
                first=lambda: rows[0] if rows else None,
                all=lambda: rows,
                scalar_one=lambda: rows[0][0],
            )

        async def commit() -> None:
            for write in writes:
                await write()

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)


def _delegate(target: Any, name: str) -> Callable[..., Any]:
    return lambda _self, *args, **kwargs: getattr(target, name)(*args, **kwargs)


def _settings() -> Settings:
    return Settings(
        storage_backend="real",
        allowed_origins=_ORIGIN,
        auth_pepper=SecretStr("test-pepper"),
        auth_totp_key_hex=SecretStr("11" * 32),
        auth_recovery_hmac_key_hex=SecretStr("22" * 32),
        auth_csrf_key_hex=SecretStr("33" * 32),
    )


async def _armed_rule(manager: Any, m: str) -> str:
    """An armed rule of M, armed as the S5 tests arm one (`test_user_cascade_wiring.py`)."""
    actor = _actor(uuid.UUID(m))
    rid = str((await manager.create(_ir(name="m-rule"), actor))["id"])
    await manager.set_mode(rid, "simulate", actor, "sim-m")
    await manager.record_simulation(rid, await _active_hash(manager, rid), 5, 0)
    await manager.set_mode(rid, "armed", actor, "arm-m")
    return rid


def _ended(ws: Any) -> tuple[dict[str, Any], int]:
    """The socket's last frame and its close code."""
    bye = _recv(ws)
    with pytest.raises(WebSocketDisconnect) as close:
        _recv(ws)
    return bye, close.value.code


def scenario(app: Any, client: TestClient, w: SimpleNamespace, owner: str, m: str) -> None:
    """AC1's actions on the deployed app, then what each actor saw, on `w`: `w.repo` is the
    session repository (its mint parks while `w.repo.park` is set) and `w.rules` the rule store
    the app's engine is bound to. Shared with the Postgres variant."""
    portal, ctx = client.portal, app.state.app_context
    assert portal is not None  # inside the client's `with`
    run, sessions = portal.call, ctx.auth.sessions
    run(ctx.rules.start, ctx)
    mine, w.a, w.b, w.c = (run(sessions.mint, u) for u in (owner, m, m, m))
    until = w.clock.now + timedelta(minutes=5)  # the step-up the Owner made
    run(w.repo.update_step_up_state, str(mine.session_id), lambda _: ({"users": until}, 0, None))
    w.rule = run(_armed_rule, ctx.rules.manager(), m)
    headers = {"Authorization": f"Bearer {mine.access_token}"}
    headers |= csrf_headers(app.state.csrf_codec, mine.session_id)

    def rest(minted: Any) -> int:  # M's next REST call on that session
        bearer = {"Authorization": f"Bearer {minted.access_token}"}
        return int(client.get("/auth/session", headers=bearer).status_code)

    w.before = [rest(s) for s in (w.a, w.b, w.c)]
    w.repo.park = park = asyncio.Event()
    refresh = portal.start_task_soon(sessions.refresh, w.c.refresh_token)
    try:
        with (
            client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws_a,
            client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws_b,
        ):
            w.auth = [_auth_ws(ws, s.access_token)["t"] for ws, s in ((ws_a, w.a), (ws_b, w.b))]
            run(functools.partial(asyncio.wait_for, w.repo.parked.wait(), _GUARD_S))  # claimed
            w.unacked = client.delete(f"/users/{m}", headers=headers)
            w.action_at = w.clock.now
            path = f"/users/{m}?acknowledge_unknown_positions=true"
            w.disabled = client.delete(path, headers=headers)
            w.ended = [_ended(ws_a), _ended(ws_b)]
    finally:
        run(park.set)  # the claimed refresh mints its successor after the disable
    w.refresh_error = refresh.exception(timeout=_GUARD_S)
    w.after = [rest(s) for s in (w.a, w.b, w.c)]
    w.live = run(w.repo.find_live_by_user, m)
    w.rows_after = [run(w.repo.find_by_id, str(s.session_id)) for s in (w.a, w.b, w.c)]
    w.rule_row = run(w.rules.get, w.rule)
    w.leaf = ctx.rules.manager().lifecycle.leaf(w.rule)
    w.records = list(ctx.audit.writer.records)


def sessions_ended(w: SimpleNamespace) -> None:
    """AC1 on the sessions, whatever the store under them: within 5 s on the test clock (0 s: no
    timer, no poll) each of M's two sessions is revoked `user_disabled` and refused on its next
    REST call, and each socket gets `bye user_disabled` (`reconnect: false`), then the close 4403
    (§9.5), before the DELETE returns. The refresh that claimed M's third session before the
    disable mints no successor after it (#2911), so M has no live session."""
    assert (w.before, w.auth, w.disabled.status_code) == ([200] * 3, ["auth_ok"] * 2, 204)
    for bye, code in w.ended:
        p = bye["p"]
        assert (bye["t"], p["reason"], p["reconnect"], p["code"], code) == _BYE
    for row in w.rows_after[:2]:
        assert row.revoked_reason == "user_disabled" and row.revoked_at == w.action_at
    assert w.after == [401] * 3 and w.rows_after[2].revoked_reason == "rotated"
    assert isinstance(w.refresh_error, UserDisabled) and w.live == ()


def rule_disarmed(w: SimpleNamespace, owner: uuid.UUID, m: uuid.UUID) -> None:
    """AC1 on the rule and the records: M's armed rule is disarmed through B9 and audited once as
    `rules.disarm` by the acting Owner; `users.disable` is written once with O2's fields; and each
    revoked session is recorded through B16 REVOKE (R5)."""
    assert (w.rule_row.mode, w.rule_row.disabled_reason, w.leaf) == ("disabled", *_DISARMED)
    (disarm,) = [r for r in w.records if r["action"] == "rules.disarm"]
    assert (disarm["object_id"], disarm["actor_user_id"]) == (w.rule, str(owner))
    assert disarm["after_state"]["b9_event"] == "DISARM"
    (record,) = [r for r in w.records if r["action"] == "users.disable"]
    assert (record["actor_user_id"], record["object_id"]) == (owner, str(m))
    after = record["after_state"]
    assert (after["sessions_revoked"], after["positions_decision"]) == (2, "leave")
    revoked = {r["session_id"] for r in w.records if r["action"] == "auth.session_revoked"}
    assert revoked == {str(w.a.session_id), str(w.b.session_id)}


@pytest.fixture(scope="module")
def disabled() -> Iterator[SimpleNamespace]:
    w = SimpleNamespace(repo=_Rows(), rules=InMemoryRuleStore(), clock=_Clock())
    with pytest.MonkeyPatch.context() as mp:
        for name in ("user", "session_info"):
            mp.setattr(SqlAlchemyIdentityProvider, name, _delegate(w.repo, name))
        for name in ("load_grants", "load_permissions"):
            mp.setattr(SqlAlchemyScopeSource, name, _delegate(w.repo, name))
        mp.setattr(SqlAlchemySessionRepository, "find_by_id", _delegate(w.repo, "find_by_id"))
        relational = "candleviewer.user_cascade_wiring.SqlAlchemyRelationalRepository"
        mp.setattr(relational, lambda *_: w.repo)  # the S3 store's unit of work
        mp.setattr(appmod, "PostgresRuleStore", lambda _relational: w.rules)
        with deployed(mp, _settings(), w) as (app, client):
            scenario(app, client, w, str(_OWNER), str(_M))
            yield w


@contextmanager
def deployed(
    mp: pytest.MonkeyPatch, settings: Settings, w: SimpleNamespace
) -> Iterator[tuple[Any, TestClient]]:
    """`create_app()` with nothing injected but the test clock, its auth module started over
    `w.repo` as `AuthService.start()` starts it, and the audit writer's stand-in. Shared."""
    wall = functools.partial(make_ws_router, wall_ms=lambda: int(w.clock.now.timestamp() * 1e3))
    mp.setattr(appmod, "make_ws_router", wall)  # the gateway's expiry check on the test clock
    app = appmod.create_app(settings, auth_clock=w.clock)
    ctx = app.state.app_context
    ctx.audit._writer = _AuditSink()
    w.published = []

    async def publish(session_id: str, reason: str) -> None:  # the sink `start()` hands it
        w.published.append((session_id, reason))
        await ctx.auth._publish_revocation(session_id, reason)

    ctx.auth._sessions = SessionService(w.repo, Hasher(), clock=w.clock, publish_revocation=publish)
    hasher, mfa, keys = Hasher(), FakeMfaRepository(), TotpEncryptor(bytes(range(32)))
    step_up = StepUpService(mfa, w.repo, keys, FakeUserRepository(), hasher, clock=w.clock)
    ctx.auth._step_up = step_up
    with TestClient(app, client=("127.0.0.1", 50000), headers={"origin": _ORIGIN}) as client:
        assert client.portal is not None
        try:
            yield app, client
        finally:
            client.portal.call(step_up.stop)
            client.portal.call(ctx.rules.stop, 1.0)


def test_rest_401_ws_4403_within_5s(disabled: SimpleNamespace) -> None:
    """AC1, SR-029, US-ADMIN-001 (`sessions_ended`). The bye comes through the cascade's own sink,
    the call site's `publish_revocation`: the session service's sink published nothing, as the
    sweep found no session left live, and the instant on the rows is the call site's `clock`."""
    sessions_ended(disabled)
    assert disabled.published == []


def test_rule_disarmed_audited(disabled: SimpleNamespace) -> None:
    """AC1, SR-029, R5 (`rule_disarmed`)."""
    w = disabled
    rule_disarmed(w, _OWNER, _M)


def test_positions_come_from_the_deployed_source(disabled: SimpleNamespace) -> None:
    """AC7, O2: the record's open-position count comes from the call site's `positions`, the
    deployed source, which reports it unknown: the 409 names that source until acknowledged."""
    w = disabled
    assert (w.unacked.status_code, w.unacked.json()["code"]) == (409, "positions_unknown")
    assert "source: not_deployed" in w.unacked.json()["detail"]
    (record,) = [r for r in w.records if r["action"] == "users.disable"]
    after = record["after_state"]
    assert after["open_position_count"] is None and after["acknowledged_unknown_positions"]


def test_data_retained(disabled: SimpleNamespace) -> None:
    """AC1, O4: nothing of M is deleted. The user row stays (disabled) with its role, the grant
    row stays soft-revoked with its freeze state and cap, every session row stays (two revoked
    `user_disabled`, the claimed one `rotated`, no successor), and the rule stays with its
    versions. The store ran only the statements this world models: no DELETE."""
    w = disabled
    assert w.repo.status(_M) is UserStatus.DISABLED and w.repo.roles[_M] == {"manager"}
    grant = w.repo.grants[(_M, _ACCOUNT)]
    assert (grant["can_view"], grant["can_trade"], grant["frozen"]) == (False, False, True)
    assert (grant["frozen_reason"], grant["max_daily_loss_usd"]) == ("drawdown", Decimal(250))
    mine = {sid for sid, s in w.repo.sessions.items() if s.user_id == _M}
    assert mine == {str(s.session_id) for s in (w.a, w.b, w.c)}
    assert not w.rule_row.deleted and len(w.rule_row.versions) == 1
    assert lifecycle._REVOKE_GRANTS in w.repo.statements
    assert not [s for s in w.repo.statements if re.search(r"\bDELETE\b", str(s), re.I)]
