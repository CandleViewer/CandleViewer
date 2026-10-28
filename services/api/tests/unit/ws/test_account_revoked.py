"""#898 B3b1 (E27-S04; 23 §9.5): an account's last signable key revoked, or the account disabled,
ends or narrows its subscriptions on every socket.

`ConnectionRegistry.account_revoked(account, reason)` sends each socket that names the account
`permission_change` first, then one `revoked` per subscription in `ch` order: a subscription that
named only that account ends (`resubscribe_allowed: false`), one that names others too narrows
(`removed_accounts`, `resubscribe_allowed: true`) and keeps them. It covers the six account-scoped
families; a socket that does not name the account gets nothing. The reason is `key_revoked` or
`account_disabled`, a closed set: another is refused before anything changes. The
`ws.subscription.revoked` rows follow the sends. Pure asyncio over the registry, no socket.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

import pytest

from candleviewer.auth.generated_permissions import Permission
from candleviewer.ws.permissions import ConnectionAuthz
from candleviewer.ws.revocation import ACCOUNT_REVOKED_REASONS
from candleviewer.ws_wiring import KillSwitchView, WsEvents
from tests.unit.ws.test_revocation_fanout import USER, _principal, _revoked_rows, _Sink, _World

A, B = uuid.UUID(int=0xA), uuid.UUID(int=0xB)
PEER = uuid.UUID(int=0x2825)
READ = frozenset(
    {
        Permission.ORDERS_READ,
        Permission.POSITIONS_READ,
        Permission.EXECUTIONS_READ,
        Permission.ACCOUNTS_READ,
        Permission.RULES_READ,
        Permission.MARKETDATA_READ,
    }
)
#: 23 §9.5: the account-scoped families an account revocation reaches (B4 adds `machines.*`).
FAMILIES = ("executions", "orders", "positions", "rules", "trade_groups", "wallet")


def _on(ch: str, *accounts: uuid.UUID) -> dict[str, Any]:
    return {"ch": ch, "opts": {"exchange_account_ids": [str(a) for a in accounts]}}


def _world() -> _World:
    world = _World(_Sink())
    world.principals[USER] = _principal(USER, READ, A, B)
    world.principals[PEER] = _principal(PEER, READ, A)
    return world


def _shown(frame: dict[str, Any]) -> tuple[Any, ...]:
    if frame["t"] != "revoked":
        return (frame["t"],)
    p = frame["p"]
    return (frame["ch"], p["reason"], p.get("removed_accounts"), p["resubscribe_allowed"])


@pytest.mark.parametrize("reason", sorted(ACCOUNT_REVOKED_REASONS))
async def test_a_single_account_subscription_ends_and_a_multi_account_one_narrows(
    reason: Any,
) -> None:
    world = _world()
    authz = world.connect(
        USER, [_on("positions", A, B), _on("orders", B), _on("wallet", B), _on("rules", A)]
    )
    assert await world.registry.account_revoked(B, reason) == 1
    assert [_shown(f) for f in world.frames[0]] == [
        ("permission_change",),
        ("orders", reason, [str(B)], False),
        ("positions", reason, [str(B)], True),
        ("wallet", reason, [str(B)], False),
    ]
    held = {s.ch: s.accounts for s in authz.by_id.values()}
    assert held == {"positions": frozenset({A}), "rules": frozenset({A})}
    narrowed = next(s for s in authz.by_id.values() if s.ch == "positions")
    assert narrowed.effective["exchange_account_ids"] == [str(A)]


async def test_permission_change_comes_first_and_names_the_sockets_identity() -> None:
    world = _world()
    world.connect(USER, [_on("orders", B)])
    await world.registry.account_revoked(B, "key_revoked")
    first, revoked = world.frames[0]
    assert first["t"] == "permission_change" and first["p"]["user_id"] == str(USER)
    assert revoked["t"] == "revoked" and revoked["p"]["sub_id"]


async def test_every_account_scoped_family_is_reached() -> None:
    world = _world()
    authz = world.connect(USER, [_on(ch, B) for ch in FAMILIES])
    await world.registry.account_revoked(B, "account_disabled")
    assert [f["ch"] for f in world.revoked()[0]] == list(FAMILIES)
    assert authz.by_id == {}


async def test_a_socket_that_does_not_name_the_account_gets_nothing() -> None:
    world = _world()
    world.connect(USER, [_on("orders", A), "trades.BTCUSDT"])
    world.connect(PEER, [_on("positions", A)])
    assert await world.registry.account_revoked(B, "account_disabled") == 0
    assert world.frames == [[], []] and world.sink.rows == []


async def test_each_socket_naming_the_account_gets_its_frames_and_its_rows_follow() -> None:
    world = _world()
    world.connect(USER, [_on("orders", B)])
    world.connect(USER, [_on("executions", A, B)])
    world.connect(PEER, [_on("orders", A)])
    assert await world.registry.account_revoked(B, "key_revoked") == 2
    assert world.frames[2] == []
    assert world.sink.rows == _revoked_rows(world)
    assert [row["reason"] for row in world.sink.rows] == ["key_revoked", "key_revoked"]


@pytest.mark.parametrize("reason", ["account_scope_changed", "user_disabled", "permission_revoked"])
async def test_a_reason_outside_the_closed_set_is_refused_before_anything_changes(
    reason: str,
) -> None:
    world = _world()
    authz = world.connect(USER, [_on("orders", B)])
    with pytest.raises(ValueError):
        await world.registry.account_revoked(B, cast(Any, reason))
    with pytest.raises(ValueError):
        authz.revoke_account(B, cast(Any, reason), 42)
    assert world.frames == [[]] and len(authz.by_id) == 1


async def test_a_socket_whose_send_fails_is_evicted_and_the_others_still_get_theirs() -> None:
    world = _world()

    async def broken(_frame: dict[str, Any]) -> None:
        raise OSError("socket gone")

    world.connect(USER, [_on("orders", B)], send=broken)
    world.connect(USER, [_on("wallet", B)])
    assert await world.registry.account_revoked(B, "account_disabled") == 2
    assert world.closed == [0] and [f["ch"] for f in world.revoked()[1]] == ["wallet"]


async def test_a_socket_whose_change_raises_is_evicted_before_any_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _world()
    poisoned = world.connect(USER, [_on("orders", B)])
    world.connect(USER, [_on("wallet", B)])

    def fault(*_args: Any) -> list[dict[str, Any]]:
        raise RuntimeError("half changed")

    monkeypatch.setattr(poisoned, "revoke_account", fault)
    assert await world.registry.account_revoked(B, "account_disabled") == 1
    assert world.closed == [0] and world.frames[0] == []
    assert [f["ch"] for f in world.revoked()[1]] == ["wallet"]


async def test_the_ws_events_entry_point_reaches_the_registry() -> None:
    world = _world()
    world.connect(USER, [_on("orders", B)])
    events = WsEvents(world.registry, cast(Any, None), KillSwitchView())
    assert await events.account_revoked(B, "key_revoked") == 1
    assert isinstance(world.sockets[0], ConnectionAuthz) and world.sockets[0].by_id == {}
