"""An account's disable, re-enable, relabel (E27-S04 B3b2, #898; 22 `updateExchangeAccount`) and
delete (B3c; 22 `deleteExchangeAccount`), 24 §8.4.1 and §14.2 rule 13.

An M13 module (C-3.1): the store is the accounts repository, and the effects that follow a disable
are ports the composition root binds (the key standing, the WS revoke, the rule disarm and the
private-stream close). The route decides RBAC, the `422`s, the `404`, the `412`, the step-up and
the exposure first; this module stores the change and carries out its effects, in this order:

- **Disable.** One compare-and-set (`is_enabled` true to false, the tag when the caller sent one)
  whose write-ahead hook places the standing hold, then writes `account.disabled`, both in its
  transaction before the commit (C-2.9): a commit that fails releases the hold, and a cancellation
  keeps it and propagates (no shield, no unowned task; the retry completes the disable). The stored
  disable is counted right after the commit. Then the WS revoke (`account_disabled`), then the rule
  disarm, then the bounded close of each signable key's private streams. An overrun of a close
  (`PrivateStreamCloseOverran`) is raised, never caught here: the route answers it (24 rule 13).
  The order leaves only the close pending after an overrun, never a subscription or an armed rule.
- **Repeat.** A disable of an account already disabled (or that a concurrent disable stored first:
  the compare-and-set misses, ruling 6) stores nothing and writes no record, and completes the
  effects still pending, each idempotent: the hold, the WS revoke, the disarm and the close. So a
  retry after an overrun or a crash finishes the disable.
- **Re-enable.** Each signable key's `account_disabled` tombstone is lifted first, so the stream
  consumer's next refresh subscribes with no defect (the 16:11Z addendum); then the
  compare-and-set (false to true) with `account.updated` written ahead; then the hold's release. A
  write that fails (a stale tag, a label conflict, the store) closes each key again with
  `account_disabled`, so a row that stays disabled never keeps lifted keys. A repeat stores
  nothing and writes no record.
- **Relabel.** The compare-and-set alone, with `account.updated` written ahead; no effect follows.
- **Delete.** The route holds the account's lock (`AccountLocks`) and has decided the step-up and
  the exposure. One write switches the account off (`is_enabled` false) whose write-ahead hook
  places the `account_disabled` hold, then writes `account.deleted`, both before the commit; a
  commit that fails releases that hold only when the account was enabled (a disable's own hold
  stands). After the commit the hold becomes `account_deleted`, which nothing releases, and the
  delete is counted. Then every key not revoked yet is destroyed through M2 (`KeyDestroyer`:
  fenced, recorded, revoked), and only then is the account soft-deleted (#898 R6: a crash in
  between leaves a disabled account with no key M2 lends, never a deleted one with a live key; M2's
  read also refuses a key of a deleted account). Then the WS revoke (`account_disabled`), the rule
  disarm (`account_deleted`) and the bounded close of each destroyed key's streams (`key_revoked`,
  permanent). Every key's close is asked for before an overrun is raised for the route to answer
  (round-1 F1); the account is deleted by then, so its retry is a `404` while the close runs on.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from candleviewer.accounts.errors import AccountUnchangedError, KeyDestroyFailedError
from candleviewer.accounts.locks import AccountLocks
from candleviewer.accounts.models import ApiKeyMetadata, ExchangeAccount, KeyStatus
from candleviewer.storage.repositories.accounts import (
    AccountScope,
    ExchangeAccountPatch,
    OwnerScope,
)

__all__ = [
    "AccountLifecycle",
    "Changed",
    "DeleteReason",
    "DisableReason",
    "Disarmer",
    "KeyDestroyerPort",
    "LifecycleStore",
    "Standings",
    "Streams",
    "Subscriptions",
    "WriteAhead",
]

#: Why a stored disable went ahead (`cv_account_disabled_total{reason}`): a flat account, the
#: `leave_positions` choice, a `flatten_first` flatten that left it flat, or a dead account.
type DisableReason = Literal["flat", "leave_positions", "flattened", "dead"]
type WriteAhead = Callable[[ExchangeAccount], Awaitable[None]]
type HoldReason = Literal["account_disabled", "account_deleted"]
#: Why a stored delete went ahead (`cv_account_deleted_total{reason}`).
type DeleteReason = Literal["flat", "flattened"]
#: The WS revoke's reasons (23 §9.5): an account switched off, or its last signable key revoked.
type RevokeReason = Literal["account_disabled", "key_revoked"]
type DisarmLifecycle = Literal["account_disabled", "account_deleted", "key_revoked"]
type CloseReason = Literal["account_disabled", "key_revoked"]
_SIGNABLE = frozenset({KeyStatus.ACTIVE, KeyStatus.ROTATING})
_REVOKED = KeyStatus.REVOKED


class LifecycleStore(Protocol):
    """`AccountsRepository`'s calls here."""

    async def get_account(self, scope: AccountScope, account_id: UUID) -> ExchangeAccount: ...

    async def list_keys(
        self, scope: OwnerScope, account_id: UUID
    ) -> tuple[ApiKeyMetadata, ...]: ...

    async def update_account(
        self,
        scope: OwnerScope,
        account_id: UUID,
        patch: ExchangeAccountPatch,
        *,
        if_match: datetime | None = None,
        expect_enabled: bool | None = None,
        write_ahead: WriteAhead | None = None,
    ) -> ExchangeAccount: ...

    async def soft_delete_account(self, scope: OwnerScope, account_id: UUID) -> None: ...


class Standings(Protocol):
    """`KeyStandings.hold`, `.release` and `.revoke` (B3b1)."""

    def hold(self, account_id: UUID, reason: HoldReason) -> None: ...

    def release(self, account_id: UUID) -> bool: ...

    def revoke(self, account_id: UUID, key_id: UUID) -> None: ...


class Subscriptions(Protocol):
    """`WsEvents.account_revoked` (B3b1)."""

    async def account_revoked(self, account_id: UUID, reason: RevokeReason) -> object: ...


class Disarmer(Protocol):
    """`AccountRuleDisarmer.disarm` (B3b1): never raises but a cancellation."""

    async def disarm(
        self,
        account_id: UUID,
        *,
        lifecycle: DisarmLifecycle,
        actor: UUID,
        role: str,
        at: datetime,
    ) -> object: ...


class Streams(Protocol):
    """The adapter's private-stream close and lift for one key (`key_ref`, the key's id)."""

    async def close_private_streams(self, key_ref: str, *, reason: CloseReason) -> object: ...

    def reopen_private_streams(
        self, key_ref: str, *, reason: Literal["account_disabled"]
    ) -> bool: ...


class KeyDestroyerPort(Protocol):
    """M2's `KeyDestroyer` (#898), which the composition root binds: destroys one stored key of one
    account (fenced, `security.credential_destroyed` with the acting user, then revoked), or
    raises; M13 never imports `secrets` (C-3.2)."""

    async def destroy(
        self, account_id: UUID, key_id: UUID, *, actor_user_id: str, actor_role: str
    ) -> None: ...


async def destroy_key(
    destroyer: KeyDestroyerPort, account_id: UUID, key_id: UUID, actor: UUID, role: str
) -> None:
    """`destroyer.destroy`, any failure but a cancellation raised as `KeyDestroyFailedError`: M2's
    codes and text never leave this call (C-12.2)."""
    try:
        await destroyer.destroy(account_id, key_id, actor_user_id=str(actor), actor_role=role)
    except Exception:
        raise KeyDestroyFailedError("a key was not destroyed") from None


@dataclass(frozen=True, slots=True)
class Changed:
    """The account after the request, and whether it was stored (`False`: a repeat, no record)."""

    account: ExchangeAccount
    stored: bool


class AccountLifecycle:
    """Stores an account's disable, re-enable or relabel and carries out its effects (module
    docstring). `count` is `cv_account_disabled_total`'s, once per stored disable."""

    def __init__(
        self,
        store: LifecycleStore,
        standings: Standings,
        subscriptions: Subscriptions,
        disarmer: Disarmer,
        streams: Streams,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        count: Callable[[DisableReason], None] = lambda _reason: None,
        destroyer: KeyDestroyerPort | None = None,
        locks: AccountLocks | None = None,
        count_deleted: Callable[[DeleteReason], None] = lambda _reason: None,
    ) -> None:
        self._store, self._standings, self._subscriptions = store, standings, subscriptions
        self._disarmer, self._streams, self._clock, self._count = disarmer, streams, clock, count
        self._destroyer, self._count_deleted = destroyer, count_deleted
        #: The delete's and the revoke's per-account lock (one table, shared with `KeyRevoke`).
        self.locks = AccountLocks() if locks is None else locks

    async def relabel(
        self,
        owner: OwnerScope,
        account_id: UUID,
        label: str,
        *,
        if_match: datetime | None,
        write_ahead: WriteAhead,
    ) -> ExchangeAccount:
        return await self._store.update_account(
            owner, account_id, ExchangeAccountPatch(label=label), if_match=if_match,
            write_ahead=write_ahead,
        )  # fmt: skip

    async def disable(
        self,
        owner: OwnerScope,
        account: ExchangeAccount,
        *,
        label: str | None,
        if_match: datetime | None,
        write_ahead: WriteAhead,
        reason: DisableReason,
        actor: UUID,
        role: str,
    ) -> Changed:
        """Store the disable of `account` (as read before the gate) and carry out its effects; a
        repeat stores nothing and completes them (`complete_disable`)."""
        if not account.is_enabled:
            return await self.complete_disable(owner, account, actor=actor, role=role)
        held = False

        async def holding(stored: ExchangeAccount) -> None:
            nonlocal held  # the hold, placed ahead of the record and the commit
            self._standings.hold(account.id, "account_disabled")
            held = True
            await write_ahead(stored)

        try:
            stored = await self._store.update_account(
                owner, account.id, ExchangeAccountPatch(label=label, is_enabled=False),
                if_match=if_match, expect_enabled=True, write_ahead=holding,
            )  # fmt: skip
        except AccountUnchangedError:  # a concurrent disable stored it first: a repeat
            now = await self._store.get_account(owner, account.id)
            return await self.complete_disable(owner, now, actor=actor, role=role)
        except Exception:  # rolled back, the row still enabled: its hold goes (a cancel keeps it)
            # residual (#898 B3b2, the hold-ownership follow-up): a commit that landed before the
            # driver raised releases a hold over a disabled row until the next tracking read lists
            # it disabled or the 503's retry, a repeat, re-places it.
            if held:
                self._standings.release(account.id)
            raise
        self._count(reason)  # right after the commit: a retry completing it is a repeat
        await self._disable_effects(owner, stored.id, actor, role, held=True)
        return Changed(stored, True)

    async def complete_disable(
        self, owner: OwnerScope, account: ExchangeAccount, *, actor: UUID, role: str
    ) -> Changed:
        """A repeat disable: nothing stored, no record; the effects still pending are done."""
        await self._disable_effects(owner, account.id, actor, role)
        return Changed(account, False)

    async def _disable_effects(
        self, owner: OwnerScope, account_id: UUID, actor: UUID, role: str, *, held: bool = False
    ) -> None:
        if not held:  # a repeat: the hold again (idempotent)
            self._standings.hold(account_id, "account_disabled")
        await self._subscriptions.account_revoked(account_id, "account_disabled")
        await self._disarmer.disarm(
            account_id, lifecycle="account_disabled", actor=actor, role=role, at=self._clock()
        )
        for key in await self._signable(owner, account_id):
            await self._streams.close_private_streams(str(key.id), reason="account_disabled")

    async def enable(
        self,
        owner: OwnerScope,
        account: ExchangeAccount,
        *,
        label: str | None,
        if_match: datetime | None,
        write_ahead: WriteAhead,
    ) -> Changed:
        """Lift the tombstones, store the re-enable, then release the hold; a repeat stores
        nothing and does the lift and the release, both idempotent. A write that fails otherwise
        sets each lifted key's tombstone again and raises its failure."""
        keys = await self._signable(owner, account.id)
        for key in keys:
            self._streams.reopen_private_streams(str(key.id), reason="account_disabled")
        changed = Changed(account, False)
        if not account.is_enabled:
            try:
                stored = await self._store.update_account(
                    owner, account.id, ExchangeAccountPatch(label=label, is_enabled=True),
                    if_match=if_match, expect_enabled=False, write_ahead=write_ahead,
                )  # fmt: skip
                changed = Changed(stored, True)
            except AccountUnchangedError:  # a concurrent re-enable stored it first: a repeat
                changed = Changed(await self._store.get_account(owner, account.id), False)
            except Exception:  # the row stays disabled: so do its keys (round-1 F-2)
                await self._tombstone(keys)
                raise
        self._standings.release(account.id)
        return changed

    async def _tombstone(self, keys: list[ApiKeyMetadata]) -> None:
        """Close each key again with `account_disabled`. The adapter sets the tombstone before
        its close runs, so a close that fails or overruns still leaves the key closed; the
        caller's failure is the one raised."""
        for key in keys:
            with suppress(Exception):
                await self._streams.close_private_streams(str(key.id), reason="account_disabled")

    async def delete(
        self,
        owner: OwnerScope,
        account: ExchangeAccount,
        *,
        write_ahead: WriteAhead,
        reason: DeleteReason,
        actor: UUID,
        role: str,
    ) -> None:
        """Store the delete of `account` (read under the account's lock, after the gate and the
        exposure) and carry out its effects (module docstring). `KeyDestroyFailedError` when a
        key was not destroyed: the account stays switched off and held, not deleted."""
        if self._destroyer is None:
            raise KeyDestroyFailedError("no key destroyer is wired")
        held = False

        async def holding(stored: ExchangeAccount) -> None:
            nonlocal held  # the hold, placed ahead of the record and the commit
            self._standings.hold(account.id, "account_disabled")
            held = True
            await write_ahead(stored)

        try:
            await self._store.update_account(
                owner, account.id, ExchangeAccountPatch(is_enabled=False), write_ahead=holding
            )
        except Exception:  # rolled back: a hold placed for an enabled account goes
            if held and account.is_enabled:
                self._standings.release(account.id)
            raise
        self._standings.hold(account.id, "account_deleted")  # never released
        self._count_deleted(reason)  # right after the commit, once
        keys = [k for k in await self._store.list_keys(owner, account.id) if k.status != _REVOKED]
        for key in keys:  # R6: every live key destroyed before the soft delete
            await destroy_key(self._destroyer, account.id, key.id, actor, role)
        await self._store.soft_delete_account(owner, account.id)
        await self._subscriptions.account_revoked(account.id, "account_disabled")
        await self._disarmer.disarm(
            account.id, lifecycle="account_deleted", actor=actor, role=role, at=self._clock()
        )
        await self._close_every(keys)  # last: an overrun leaves only the close pending

    async def _close_every(self, keys: list[ApiKeyMetadata]) -> None:
        """Close every key's private streams before raising: one key's overrun never skips a
        later key's close (and so its tombstone, set inside the close), since a retry of a deleted
        account is a `404` that never reaches them (round-1 F1). The first failure is raised."""
        failure: Exception | None = None
        for key in keys:
            try:
                await self._streams.close_private_streams(str(key.id), reason="key_revoked")
            except Exception as exc:  # raised after every close was asked for
                failure = failure or exc
        if failure is not None:
            raise failure

    async def _signable(self, owner: OwnerScope, account_id: UUID) -> list[ApiKeyMetadata]:
        keys = await self._store.list_keys(owner, account_id)
        return [key for key in keys if key.status in _SIGNABLE]
