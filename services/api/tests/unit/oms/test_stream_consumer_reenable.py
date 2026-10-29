"""#898 B3b2 (E27-S04; the B3 ruling's 16:11Z addendum): a re-enable lifts the account's
`account_disabled` tombstone before the account counts as enabled again, so the private-stream
consumer's next refresh subscribes it with no `stream_account_defect`. Lifted after, a refresh
landing between the two would meet the tombstone's `AuthError`, count a defect and page.

The real `StreamConsumer` over the consumer test's rig (a ticked refresh, no sleeps), the real
`KeyTombstones` refusing a tombstoned key as the adapter's registry does, and the real
`AccountLifecycle` whose store runs the consumer's refresh the moment the re-enable is stored. No
network."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from candleviewer.accounts.lifecycle import AccountLifecycle
from candleviewer.accounts.models import ApiKeyMetadata, ExchangeAccount
from candleviewer.exchange.base.errors import AuthError
from candleviewer.exchange.base.models import AccountRef
from candleviewer.exchange.base.ports import PrivateStream
from candleviewer.exchange.bybit.private_stream import KeyTombstones
from candleviewer.storage.repositories.accounts import ExchangeAccountPatch, OwnerScope
from tests.unit.accounts.test_exposure_read import ACCOUNT, key
from tests.unit.exchange.bybit._trading import account
from tests.unit.oms.test_stream_consumer import A, Rig, entries

KEY_REF = account(A).key_ref


class _Rig(Rig):
    """The consumer's rig whose stream registry refuses a tombstoned key, as the adapter's does."""

    tombstones: KeyTombstones

    async def subscribe(self, ref: AccountRef) -> PrivateStream:
        if self.tombstones.refuses(ref.key_ref):
            self.log.append(("refused", ref.account_id))
            raise AuthError("the key is closed")
        return await super().subscribe(ref)


class _Ports:
    """The lifecycle's store and adapter over the rig: storing the re-enable puts the account back
    in the streamed set and runs a consumer refresh at once."""

    def __init__(self, rig: _Rig) -> None:
        self.rig, self.account = rig, ACCOUNT.model_copy(update={"is_enabled": False})

    async def get_account(self, scope: Any, account_id: UUID) -> ExchangeAccount:
        return self.account

    async def list_keys(self, scope: OwnerScope, account_id: UUID) -> tuple[ApiKeyMetadata, ...]:
        return (key(UUID(KEY_REF)),)

    async def update_account(
        self, scope: OwnerScope, account_id: UUID, patch: ExchangeAccountPatch, **_kw: Any
    ) -> ExchangeAccount:
        self.account = self.account.model_copy(update={"is_enabled": patch.is_enabled})
        self.rig.streamed = {A}
        await self.rig.refresh()  # the consumer's 15 s refresh lands right after the commit
        return self.account

    def hold(self, account_id: UUID, reason: str) -> None: ...

    def release(self, account_id: UUID) -> bool:
        return True

    async def account_revoked(self, account_id: UUID, reason: str) -> int:
        return 0

    async def disarm(self, account_id: UUID, **_kw: Any) -> None: ...

    async def close_private_streams(self, key_ref: str, *, reason: Any) -> tuple[UUID, ...]:
        self.rig.tombstones.close(key_ref, reason)
        return ()

    def reopen_private_streams(self, key_ref: str, *, reason: Any) -> bool:
        return self.rig.tombstones.lift(key_ref)


async def _record(stored: ExchangeAccount) -> None: ...


async def test_a_re_enable_is_subscribed_on_the_next_refresh_with_no_defect() -> None:
    rig = _Rig(streamed=set())
    rig.tombstones = KeyTombstones()
    ports = _Ports(rig)
    rig.tombstones.close(KEY_REF, "account_disabled")  # the disable's tombstone
    consumer = rig.consumer()
    consumer.start()
    for _ in range(20):  # its first refresh: nothing is streamed yet
        await asyncio.sleep(0)
    try:
        lifecycle = AccountLifecycle(ports, ports, ports, ports, ports)
        done = await lifecycle.enable(
            OwnerScope(UUID(int=1)), ports.account, label=None, if_match=None,
            write_ahead=_record,
        )  # fmt: skip
        await rig.until(lambda: ("subscribe", A) in rig.log)
        assert done.stored and consumer.accounts() == {A}
        assert entries(rig, "refused") == [] and "defect" not in rig.counts and rig.pages == []
    finally:
        await consumer.stop()


async def test_a_disable_closes_the_key_so_a_subscribe_meanwhile_is_refused() -> None:
    """The control: the tombstone the disable leaves does refuse the key's subscribe."""
    rig = _Rig(streamed={A})
    rig.tombstones = KeyTombstones()
    ports = _Ports(rig)
    await ports.close_private_streams(KEY_REF, reason="account_disabled")
    consumer = rig.consumer()
    consumer.start()
    try:
        await rig.until(lambda: "defect" in rig.counts)
        assert entries(rig, "refused") == [("refused", A)]
    finally:
        await consumer.stop()
