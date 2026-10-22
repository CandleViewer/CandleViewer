"""§9.6 (#3085): a viewing socket's scope is its target's, and its actor the viewer.

While the session holds a live context, the `auth` resolves the target's principal: `auth_ok`
carries the session's own `user_id` and `session_id` with the target's roles, permissions and
account scope, and the socket is registered under the target, so the target's own data and role
changes reach it. The viewer acts: the socket's audit rows name the viewer, and its per-user
quotas (rebuilds, indicator instances) are the viewer's, so a viewer cannot spend the target's.
The registry never lets a viewing socket take an Owner's snapshot (a target is never an Owner),
and a disable of the target ends the view (`view_as_expired`), not the viewer (`user_disabled`).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.view_as import ViewAsBinding, ViewAsPhase
from candleviewer.bars.models import BarSpec
from candleviewer.ws.permissions import (
    ConnectionAuthz,
    ConnectionRegistry,
    SubscriptionServices,
    _audit_denials,
)
from tests.unit.ws._auth_rig import DEADLINE_S, LATER, Rig, Sock, bye_of, hang_up, user_of

_VIEWER, _TARGET = user_of("good-1"), user_of("good-9")


def _viewing(rig_kw: dict[str, Any] | None = None) -> Rig:
    binding = ViewAsBinding(
        context_id=uuid.uuid4(), target_user_id=_TARGET, expires_at=LATER, phase=ViewAsPhase.LIVE
    )

    async def view_as(session_id: str) -> ViewAsBinding:
        return binding

    return Rig(options={"view_as": view_as}, **(rig_kw or {}))


async def test_auth_ok_names_the_session_with_the_targets_scope_and_registers_the_target() -> None:
    rig, sock = _viewing(), Sock()
    async with asyncio.timeout(DEADLINE_S):
        handler = await rig.open(sock)
        ok = await rig.auth(sock, "good-1")
        assert ok["t"] == "auth_ok"
        assert (ok["p"]["user_id"], ok["p"]["session_id"]) == (str(_VIEWER), "sess-good-1")
        assert ok["p"]["roles"] == ["viewer"] and ok["p"]["permissions"]  # the target's
        assert set(rig.registry._conns) == {_TARGET}  # the target's changes reach it
        ((authz, _, _),) = rig.registry._conns[_TARGET]
        assert (authz.principal.user_id, authz.actor_user_id) == (_TARGET, _VIEWER)
        hang_up(sock)
        await handler


async def test_a_viewing_sockets_flag_push_is_resolved_for_its_target() -> None:
    """Its flags are its subject's, with the subject's roles, as REST will once S8 resolves
    the subject (plan §1.5): never the viewer's overrides or rollout bucket."""
    rig, sock = _viewing(), Sock()
    async with asyncio.timeout(DEADLINE_S):
        handler = await rig.open(sock)
        assert (await rig.auth(sock, "good-1"))["t"] == "auth_ok"
        ((user_id, roles, _push),) = rig.hub.system_sessions()
        assert (user_id, roles) == (_TARGET, frozenset({"viewer"}))
        hang_up(sock)
        await handler


async def test_a_viewing_sockets_permission_change_names_the_session_as_auth_ok_did() -> None:
    """§9.5: its identity is a subset of `auth_ok`'s, which names the session's own user."""
    rig, sock = _viewing(), Sock()
    async with asyncio.timeout(DEADLINE_S):
        handler = await rig.open(sock)
        assert (await rig.auth(sock, "good-1"))["t"] == "auth_ok"
        await rig.registry.roles_changed(_TARGET)
        change = await sock.sent.get()
        assert (change["t"], change["p"]["user_id"]) == ("permission_change", str(_VIEWER))
        hang_up(sock)
        await handler


async def test_a_disable_of_the_viewed_target_ends_the_view_not_the_viewer() -> None:
    rig, sock = _viewing(), Sock()
    async with asyncio.timeout(DEADLINE_S):
        handler = await rig.open(sock)
        assert (await rig.auth(sock, "good-1"))["t"] == "auth_ok"
        assert await rig.registry.user_disabled(_TARGET) == 1
        assert bye_of(await sock.sent.get()) == ("bye", "view_as_expired", 4403)
        hang_up(sock)
        await handler


async def test_a_target_who_becomes_an_owner_ends_the_view() -> None:
    """§9.6: a target is never an Owner, so the socket never applies an Owner's snapshot."""
    rig, sock = _viewing(), Sock()
    async with asyncio.timeout(DEADLINE_S):
        handler = await rig.open(sock)
        assert (await rig.auth(sock, "good-1"))["t"] == "auth_ok"

        async def promoted(uid: uuid.UUID) -> PrincipalSnapshot:
            return PrincipalSnapshot(uid, frozenset({"owner"}), frozenset(Permission))

        rig.registry._resolve = promoted
        await rig.registry.roles_changed(_TARGET)
        assert bye_of(await sock.sent.get()) == ("bye", "view_as_expired", 4403)
        assert _TARGET not in rig.registry._conns
        hang_up(sock)
        await handler


async def _owner(uid: uuid.UUID) -> PrincipalSnapshot:
    return PrincipalSnapshot(uid, frozenset({"owner"}), frozenset(Permission))


async def test_a_target_already_an_owner_at_the_auth_is_refused_view_as_expired() -> None:
    """The `auth` resolves the target before it registers anything: an Owner ends the view."""
    rig, sock = _viewing(), Sock()
    rig.registry._resolve = _owner
    async with asyncio.timeout(DEADLINE_S):
        handler = await rig.open(sock)
        assert bye_of(await rig.auth(sock, "good-1")) == ("bye", "view_as_expired", 4403)
        assert not rig.registry._conns
        hang_up(sock)
        await handler


def _registered_view(registry: ConnectionRegistry) -> tuple[ConnectionAuthz, list[Any]]:
    principal = PrincipalSnapshot(_TARGET, frozenset({"viewer"}), frozenset())
    authz = ConnectionAuthz(principal, registry.services, viewer_user_id=_VIEWER)
    closes: list[Any] = []

    async def closer(frame: dict[str, Any], code: int) -> None:
        closes.append(bye_of(frame))

    registry.register(authz, None, None, closer)
    return authz, closes


async def test_a_recheck_that_reads_an_owner_target_ends_the_view_instead_of_applying() -> None:
    """SR-189's re-read: the change it catches may be the target's promotion."""
    registry = ConnectionRegistry(_owner, lambda: 0, services=SubscriptionServices())
    authz, closes = _registered_view(registry)
    await registry.roles_changed(uuid.uuid4())  # a change after the socket's own read
    await registry.recheck(authz)
    assert closes == [("bye", "view_as_expired", 4403)] and not registry._conns


async def test_an_applied_owner_snapshot_ends_the_view_and_yields_no_frames() -> None:
    registry = ConnectionRegistry(_owner, lambda: 0, services=SubscriptionServices())
    authz, closes = _registered_view(registry)
    snap = await registry.resolve(_TARGET)
    assert await registry.apply(authz, snap, 0, event="reauth") == []
    assert closes == [("bye", "view_as_expired", 4403)] and not registry._conns


async def test_an_owner_promotion_of_the_users_own_socket_still_applies() -> None:
    rig, sock = Rig(), Sock()
    async with asyncio.timeout(DEADLINE_S):
        handler = await rig.open(sock)
        assert (await rig.auth(sock, "good-9"))["t"] == "auth_ok"

        async def promoted(uid: uuid.UUID) -> PrincipalSnapshot:
            return PrincipalSnapshot(uid, frozenset({"owner"}), frozenset(Permission))

        rig.registry._resolve = promoted
        await rig.registry.roles_changed(_TARGET)
        assert (await sock.sent.get())["t"] == "permission_change"
        hang_up(sock)
        await handler


def test_the_quotas_are_the_actors_and_the_principal_the_targets() -> None:
    principal = PrincipalSnapshot(_TARGET, frozenset({"viewer"}), frozenset())
    viewing = ConnectionAuthz(principal, viewer_user_id=_VIEWER)
    own = ConnectionAuthz(principal)
    assert viewing.rebuilds._user is not None and viewing.rebuilds._user[1] == _VIEWER
    assert (viewing.actor_user_id, own.actor_user_id) == (_VIEWER, _TARGET)


class _Leases:
    """`BarLeases` recording the user each bar lease is charged to."""

    def __init__(self) -> None:
        self.users: list[str | None] = []

    def check(self, spec: BarSpec, symbol: str, user: str | None = None) -> None:
        self.users.append(user)

    async def register(self, *_args: Any, user: str | None = None) -> None:
        self.users.append(user)

    def release(self, spec_hash: str, symbol: str, consumer: str) -> None:
        return None


async def test_a_viewing_sockets_bar_lease_is_charged_to_the_viewer() -> None:
    """The per-user bar and indicator quotas are the viewer's, as the rebuild budget is."""
    leases = _Leases()
    principal = PrincipalSnapshot(
        _TARGET, frozenset({"manager"}), frozenset({Permission.MARKETDATA_READ})
    )
    authz = ConnectionAuthz(principal, SubscriptionServices(bars=leases), viewer_user_id=_VIEWER)
    sub = authz.admit("footprint.BTCUSDT.tick.100")[1]
    assert sub is not None and await authz.subscribe_upstream(sub) is None
    assert leases.users == [str(_VIEWER)]


class _Rows:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def emit(self, action: str, **fields: Any) -> None:
        self.rows.append({"action": action, **fields})


async def test_a_viewing_sockets_audit_rows_name_the_viewer_and_its_session() -> None:
    """§9.6: every record for a socket of the session names the viewer and the viewer's session
    as the actor, never the target."""
    sink = _Rows()
    principal = PrincipalSnapshot(_TARGET, frozenset({"viewer"}), frozenset())
    authz = ConnectionAuthz(principal, SubscriptionServices(audit=sink), viewer_user_id=_VIEWER)
    authz.session_id = "sess-good-1"
    await _audit_denials(authz, [("orders", "forbidden", "missing_permission")])
    (row,) = sink.rows
    assert (row["action"], row["actor_user_id"], row["session_id"]) == (
        "ws.subscribe.denied",
        _VIEWER,
        "sess-good-1",
    )
