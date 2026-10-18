"""E27-T04 (#837) W4b helpers: a `wallet` subscriber on the real gateway parts (`ConnectionAuthz`,
`TopicEmitter`, `SequencingHub`), each frame it gets validated against 23-ws-protocol.md §13-§15;
the principals of the scope tests; and the two monitored accounts with the topic on a hub."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from candleviewer.accounts.health import epoch_ms
from candleviewer.accounts.wallet_topic import WalletTopic
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.ws.permissions import ConnectionAuthz, SubscriptionServices
from candleviewer.ws.sequencing import SequencingHub, SnapshotBody, TopicEmitter
from tests.unit.accounts._fakes import FakeClock
from tests.unit.accounts._status_world import StatusWorld
from tests.unit.ws._seq_support import validate

USER = UUID(int=0x100)
READ = frozenset({Permission.ACCOUNTS_READ})


def manager(*grants: UUID, permissions: frozenset[Permission] = READ) -> PrincipalSnapshot:
    rows = tuple(AccountGrant(account, True, False, False) for account in grants)
    return PrincipalSnapshot(USER, frozenset({"manager"}), permissions, rows)


def owner() -> PrincipalSnapshot:
    return PrincipalSnapshot(USER, frozenset({"owner"}), READ)


class Conn:
    """One authenticated socket on `hub`: its subscriptions and the frames it was sent."""

    def __init__(
        self,
        hub: SequencingHub,
        topic: WalletTopic[SnapshotBody],
        principal: PrincipalSnapshot,
        clock: FakeClock,
    ) -> None:
        self.frames: list[dict[str, Any]] = []
        self.authz = ConnectionAuthz(principal, SubscriptionServices(snapshots=topic))
        self._emitter = TopicEmitter(
            self._push,
            connection_id="ws_test",
            wall_ms=lambda: epoch_ms(clock.now()),
            clock=clock.monotonic,
            source=topic,
        )
        hub.register(self.authz, self._emitter)

    def _push(self, frame: dict[str, Any]) -> None:
        validate(frame)
        self.frames.append(frame)

    def sub(self, *accounts: UUID) -> dict[str, Any]:
        """Subscribe to `wallet` for `accounts` and return the `sub_ok` result; a `snap` follows."""
        entry = {"ch": "wallet", "opts": {"exchange_account_ids": [str(a) for a in accounts]}}
        result, sub = self.authz.admit(entry)
        if sub is not None:
            sub.announced = True  # the gateway's `sub_ok` is queued (#2831)
            self._emitter.flush_pending([sub])
        return result

    def take(self) -> list[tuple[str, dict[str, Any]]]:
        """The type and payload of every frame since the last take."""
        frames, self.frames = self.frames, []
        return [(frame["t"], frame["p"]) for frame in frames]


class WalletWorld(StatusWorld):
    """The two monitored accounts, with the topic attached to them on a hub of its own."""

    def __init__(self) -> None:
        super().__init__()
        self.hub = SequencingHub()
        self.topic = WalletTopic(self.hub.publish, SnapshotBody)
        self.topic.attach(self.monitor, self.wallets)

    def conn(self, principal: PrincipalSnapshot) -> Conn:
        return Conn(self.hub, self.topic, principal, self.clock)
