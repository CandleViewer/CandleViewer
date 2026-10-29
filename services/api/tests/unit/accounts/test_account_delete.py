"""#898 B3c (E27-S04): the account delete behind `deleteExchangeAccount`. One write switches the
account off with `account.deleted` written ahead and the hold placed in its hook; then the delete's
hold, every live key destroyed, the soft delete, the WS revoke, the disarm and the bounded close.
A fault after each step leaves the account held and switched off, and once the destroys ran no key
is lent (R6), with M2's real destroyer in the last tests. One ordered log; no I/O, no sleeps."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from candleviewer.accounts.errors import (
    AccountConflictError,
    AccountsError,
    KeyDestroyFailedError,
)
from candleviewer.accounts.key_standing import KeyStandings
from candleviewer.accounts.lifecycle import AccountLifecycle, WriteAhead
from candleviewer.accounts.models import ApiKeyMetadata, ExchangeAccount, KeyStatus
from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.errors import PrivateStreamCloseOverran
from candleviewer.secrets import CredentialUnavailable, mint_key_destroyer
from candleviewer.secrets.secret import Secret
from candleviewer.secrets.store import InMemoryCredentialStore
from candleviewer.storage.repositories.accounts import ExchangeAccountPatch, OwnerScope
from tests.unit.accounts._fakes import FakeClock, key_row
from tests.unit.accounts.test_exposure_read import ACCOUNT, key
from tests.unit.credentials_m2._helpers import _borrow
from tests.unit.credentials_m2._service_fakes import _ctx, _Src, _svc
from tests.unit.credentials_m2._vectors import API_KEY, API_SECRET, KEK_V1, SNAPSHOT, AuditLog

OWNER = OwnerScope(UUID(int=77))
ACTOR = UUID(int=78)
AT = datetime(2026, 10, 28, 12, tzinfo=UTC)
K1, K2, K3 = UUID(int=1), UUID(int=2), UUID(int=3)
#: The ruled order (R6, ruling item 4): the switch-off in one write (its hold in the hook, then its
#: record, then the commit), the delete's hold, each live key destroyed, the soft delete, then the
#: WS revoke, the disarm and the close of each destroyed key, last.
ORDER = [
    "cas", "hold:account_disabled", "record", "committed", "hold:account_deleted", "counted",
    "keys", f"destroy:{K1}", f"destroy:{K2}", "soft_delete", "ws", "disarm", f"close:{K1}",
    f"close:{K2}",
]  # fmt: skip


class World:
    """Every port of the delete, logging into one ordered `log`; `faults` names the call that
    raises next. `destroyer` may be M2's real one (`keys` then lists its stored keys)."""

    def __init__(self, enabled: bool = True) -> None:
        self.account = ACCOUNT.model_copy(update={"is_enabled": enabled})
        self.keys: tuple[ApiKeyMetadata, ...] = (
            key(K1), key(K2, KeyStatus.ROTATING), key(K3, KeyStatus.REVOKED)
        )  # fmt: skip
        self.log: list[str] = []
        self.faults: dict[str, BaseException] = {}
        self.deleted = False
        self.held: dict[UUID, str] = {}
        self.destroyer: Any = self

    def _hit(self, name: str) -> None:
        self.log.append(name)
        if name in self.faults:
            raise self.faults.pop(name)

    async def get_account(self, scope: Any, account_id: UUID) -> ExchangeAccount:
        return self.account

    async def list_keys(self, scope: OwnerScope, account_id: UUID) -> tuple[ApiKeyMetadata, ...]:
        self._hit("keys")
        return self.keys

    async def update_account(
        self, scope: OwnerScope, account_id: UUID, patch: ExchangeAccountPatch, *,
        if_match: datetime | None = None, expect_enabled: bool | None = None,
        write_ahead: WriteAhead | None = None,
    ) -> ExchangeAccount:  # fmt: skip
        self._hit("cas")
        assert (scope, account_id, patch) == (OWNER, ACCOUNT.id, ExchangeAccountPatch(
            is_enabled=False))  # fmt: skip
        assert (if_match, expect_enabled) == (None, None)
        written = self.account.model_copy(update={"is_enabled": False})
        if write_ahead is not None:
            await write_ahead(written)  # raising here rolls the write back
        if "commit" in self.faults:
            self._hit("commit")
        self.account = written
        self.log.append("committed")
        return written

    async def soft_delete_account(self, scope: OwnerScope, account_id: UUID) -> None:
        self._hit("soft_delete")
        self.deleted = True

    def hold(self, account_id: UUID, reason: str) -> None:
        self.log.append(f"hold:{reason}")
        self.held[account_id] = reason

    def release(self, account_id: UUID) -> bool:
        self.log.append("release")
        return self.held.pop(account_id, None) == "account_disabled"

    def revoke(self, account_id: UUID, key_id: UUID) -> None:
        raise AssertionError("a delete holds the account, it revokes no single key")

    async def account_revoked(self, account_id: UUID, reason: str) -> int:
        assert reason == "account_disabled"
        self._hit("ws")
        return 1

    async def disarm(
        self, account_id: UUID, *, lifecycle: str, actor: UUID, role: str, at: datetime
    ) -> object:
        assert (lifecycle, actor, role, at) == ("account_deleted", ACTOR, "owner", AT)
        self._hit("disarm")
        return None

    async def close_private_streams(self, key_ref: str, *, reason: str) -> tuple[UUID, ...]:
        assert reason == "key_revoked"  # permanent: a deleted account's keys never reopen
        self._hit(f"close:{key_ref}")
        return ()

    def reopen_private_streams(self, key_ref: str, *, reason: str) -> bool:
        raise AssertionError("a delete lifts nothing")

    async def destroy(
        self, account_id: UUID, key_id: UUID, *, actor_user_id: str, actor_role: str
    ) -> None:
        assert (account_id, actor_user_id, actor_role) == (ACCOUNT.id, str(ACTOR), "owner")
        self._hit(f"destroy:{key_id}")

    def lifecycle(self) -> AccountLifecycle:
        return AccountLifecycle(
            self, self, self, self, self, clock=lambda: AT, destroyer=self.destroyer,
            count_deleted=lambda reason: self.log.append("counted"),
        )  # fmt: skip

    async def delete(self) -> None:
        async def record(stored: ExchangeAccount) -> None:
            assert stored.is_enabled is False
            self._hit("record")

        await self.lifecycle().delete(
            OWNER, self.account, write_ahead=record, reason="flat", actor=ACTOR, role="owner"
        )


async def test_a_delete_runs_every_step_in_the_ruled_order() -> None:
    world = World()
    await world.delete()
    assert world.log == ORDER
    assert world.held == {ACCOUNT.id: "account_deleted"} and world.deleted


async def test_a_delete_of_a_disabled_account_still_switches_it_off_and_records_it() -> None:
    world = World(enabled=False)
    await world.delete()
    assert world.log == ORDER


#: Each step a fault can follow, after the commit: the account is held for good and switched off;
#: once the destroys ran, no key is live; it is never soft-deleted before every destroy ran.
_AFTER_THE_COMMIT = ["keys", f"destroy:{K1}", f"destroy:{K2}", "soft_delete", "ws", "disarm",
                     f"close:{K1}", f"close:{K2}"]  # fmt: skip


@pytest.mark.parametrize("step", _AFTER_THE_COMMIT)
async def test_a_fault_at_each_step_after_the_commit_leaves_the_account_held_and_off(
    step: str,
) -> None:
    world = World()
    world.faults[step] = RuntimeError("down") if "destroy" not in step else ValueError("m2")
    with pytest.raises((RuntimeError, KeyDestroyFailedError)):
        await world.delete()
    assert world.account.is_enabled is False and world.held == {ACCOUNT.id: "account_deleted"}
    reached = ORDER.index(step)  # a close's fault never skips a later key's close (round-1 F1)
    assert world.log == (ORDER if step.startswith("close:") else ORDER[: reached + 1])
    destroyed = [s for s in world.log if s.startswith("destroy:")]
    assert world.deleted is (reached > ORDER.index("soft_delete"))
    if world.deleted:
        assert destroyed == [f"destroy:{K1}", f"destroy:{K2}"]  # R6: every key first


@pytest.mark.parametrize("step", ["record", "commit"])
async def test_a_switch_off_that_does_not_commit_changes_nothing_and_releases_its_hold(
    step: str,
) -> None:
    world = World()
    world.faults[step] = AccountConflictError("x") if step == "commit" else RuntimeError("audit")
    with pytest.raises((AccountConflictError, RuntimeError)):
        await world.delete()
    assert world.account.is_enabled is True and world.held == {} and not world.deleted
    assert world.log[-1] == "release" and "keys" not in world.log


async def test_a_switch_off_of_a_disabled_account_that_fails_keeps_the_disables_hold() -> None:
    """Its disable's hold stands: the release is for a hold this delete placed on an enabled
    account only."""
    world = World(enabled=False)
    world.held[ACCOUNT.id] = "account_disabled"
    world.faults["record"] = RuntimeError("audit")
    with pytest.raises(RuntimeError):
        await world.delete()
    assert world.held == {ACCOUNT.id: "account_disabled"} and "release" not in world.log


async def test_m2s_failure_is_key_destroy_failed_with_none_of_its_text() -> None:
    world = World()
    world.faults[f"destroy:{K2}"] = CredentialUnavailable("credential_unavailable")
    with pytest.raises(KeyDestroyFailedError) as caught:
        await world.delete()
    assert "credential" not in str(caught.value) and caught.value.__cause__ is None
    assert isinstance(caught.value, AccountsError) and not world.deleted


async def test_an_overrun_is_raised_after_the_soft_delete_never_caught_here() -> None:
    """Raised only after every key's close was asked for (round-1 F1): one key's overrun never
    skips a later key's close, which no retry of the deleted account would reach."""
    world = World()
    world.faults[f"close:{K1}"] = PrivateStreamCloseOverran((AccountId(ACCOUNT.id),))
    with pytest.raises(PrivateStreamCloseOverran):
        await world.delete()
    assert world.deleted and world.log[-2:] == [f"close:{K1}", f"close:{K2}"]


async def test_when_every_close_overruns_the_first_overrun_is_raised_after_all() -> None:
    world = World()
    first = PrivateStreamCloseOverran((AccountId(ACCOUNT.id),))
    world.faults[f"close:{K1}"] = first
    world.faults[f"close:{K2}"] = PrivateStreamCloseOverran((AccountId(ACCOUNT.id),))
    with pytest.raises(PrivateStreamCloseOverran) as caught:
        await world.delete()
    assert caught.value is first and world.log[-2:] == [f"close:{K1}", f"close:{K2}"]


async def test_no_destroyer_wired_refuses_before_anything() -> None:
    world = World()
    world.destroyer = None
    with pytest.raises(KeyDestroyFailedError):
        await world.delete()
    assert world.log == []


async def test_the_delete_hold_disables_the_order_gate_and_closes_the_account_for_good() -> None:
    """With the real standing: the hold refuses the account's orders synchronously and keeps a new
    WS `sub` out, and no re-enable's `release` lifts a delete's hold."""
    clock = FakeClock()
    standings = KeyStandings(None, interval_s=3600.0, stale_after_s=600.0, clock=clock)
    standings.observe([key_row(ACCOUNT.id, key=K1)])
    world = World()
    life = AccountLifecycle(world, standings, world, world, world, clock=lambda: AT,
                            destroyer=world)  # fmt: skip

    async def record(_stored: ExchangeAccount) -> None:
        return None

    await life.delete(OWNER, world.account, write_ahead=record, reason="flat", actor=ACTOR,
                      role="owner")  # fmt: skip
    standing = standings.standing(ACCOUNT.id)
    assert standing is not None and standing.disabled_reason is not None
    assert standings.closed(ACCOUNT.id) and standings.release(ACCOUNT.id) is False
    assert standings.closed(ACCOUNT.id)


# -- R6 with M2's real destroyer ----------------------------------------------------------------


async def _m2_world() -> tuple[World, Any, list[UUID]]:
    """M2 started over an in-memory store, two keys stored and lent once (their DEKs cached), and
    a delete world whose keys are those two and whose destroyer is M2's own mint."""
    store, audit = InMemoryCredentialStore(), AuditLog()
    svc = _svc(_Src(KEK_V1, 1), store=store, audit=audit)
    await svc.start(_ctx())
    broker, ids = svc._require(), []
    for i in range(2):
        meta = await broker.store(
            "demo", ACCOUNT.id, f"k{i}", Secret(API_KEY), Secret(API_SECRET), SNAPSHOT
        )
        store.activate(meta.key_id)
        assert await _borrow(broker, meta.key_id) == (API_KEY, API_SECRET)
        ids.append(meta.key_id)
    world = World()
    world.keys = tuple(key(i) for i in ids)
    world.destroyer = mint_key_destroyer(svc)
    return world, broker, ids


async def test_an_interrupted_delete_leaves_no_borrowable_key() -> None:
    """R6: a crash at the soft delete (after every destroy) leaves the account switched off, held,
    not deleted, and every key refused by M2, its row revoked."""
    world, broker, ids = await _m2_world()
    world.faults["soft_delete"] = RuntimeError("killed")
    with pytest.raises(RuntimeError):
        await world.delete()
    assert not world.deleted and world.account.is_enabled is False
    for key_id in ids:
        with pytest.raises(CredentialUnavailable, match=r"^credential_unavailable$"):
            await _borrow(broker, key_id)


async def test_a_delete_crashing_between_its_destroys_leaves_the_rest_to_its_retry() -> None:
    """A crash after the first destroy: that key is refused at once; the second still signs until
    the retry destroys it, while the hold refuses the account's orders (the residual stated)."""
    world, broker, ids = await _m2_world()
    world.log.clear()

    async def killed(account_id: UUID, key_id: UUID, **_kw: str) -> None:
        raise RuntimeError("killed")

    real = world.destroyer
    calls = 0

    class Once:
        async def destroy(self, account_id: UUID, key_id: UUID, **kw: str) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                await killed(account_id, key_id)
            await real.destroy(account_id, key_id, **kw)

    world.destroyer = Once()
    with pytest.raises(KeyDestroyFailedError):
        await world.delete()
    with pytest.raises(CredentialUnavailable):
        await _borrow(broker, ids[0])
    assert await _borrow(broker, ids[1]) == (API_KEY, API_SECRET)
    assert world.held == {ACCOUNT.id: "account_deleted"} and not world.deleted
