"""#898 B3b2 (E27-S04): the account lifecycle behind `updateExchangeAccount` stores the change,
then carries out its effects in the ruled order (hold, WS revoke, disarm, bounded close); a repeat
stores nothing and completes them; a re-enable lifts the tombstones before the account counts as
enabled, then releases the hold. Recording doubles share one ordered log; no I/O, no sleeps."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from candleviewer.accounts.errors import (
    AccountConflictError,
    AccountUnchangedError,
    AccountVersionConflictError,
)
from candleviewer.accounts.lifecycle import AccountLifecycle, WriteAhead
from candleviewer.accounts.models import ApiKeyMetadata, ExchangeAccount, KeyStatus
from candleviewer.exchange.base.errors import PrivateStreamCloseOverran
from candleviewer.storage.repositories.accounts import ExchangeAccountPatch, OwnerScope
from tests.unit.accounts.test_exposure_read import ACCOUNT, key

OWNER = OwnerScope(UUID(int=77))
ACTOR = UUID(int=78)
AT = datetime(2026, 10, 28, 12, tzinfo=UTC)
K1, K2, K3 = UUID(int=1), UUID(int=2), UUID(int=3)
EFFECTS = ["hold", "ws", "disarm", f"close:{K1}", f"close:{K2}"]
#: A stored disable: the hold is placed in the write-ahead hook, ahead of its record and the
#: commit (hpe-worker-2 item 3); the effects after the commit are the rest.
STORED = ["cas", "hold", "record:False", "committed", "ws", "disarm", "keys", *EFFECTS[3:]]


class World:
    """Every port of the lifecycle, logging into one ordered `log`. `faults` names the call that
    raises next; `unchanged` makes the compare-and-set miss as a concurrent change would."""

    def __init__(self, enabled: bool = True) -> None:
        self.account = ACCOUNT.model_copy(update={"is_enabled": enabled})
        self.keys: tuple[ApiKeyMetadata, ...] = (
            key(K1), key(K2, KeyStatus.ROTATING), key(K3, KeyStatus.REVOKED)
        )  # fmt: skip
        self.log: list[str] = []
        self.faults: dict[str, BaseException] = {}
        self.unchanged = False
        self.counted: list[str] = []

    def _hit(self, name: str) -> None:
        self.log.append(name)
        if name in self.faults:
            raise self.faults.pop(name)

    async def get_account(self, scope: Any, account_id: UUID) -> ExchangeAccount:
        self._hit("get")
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
        assert scope == OWNER and account_id == ACCOUNT.id
        if self.unchanged:
            self.account = self.account.model_copy(update={"is_enabled": not expect_enabled})
            raise AccountUnchangedError
        changed = {"label": patch.label} if patch.label is not None else {}
        if patch.is_enabled is not None:
            changed["is_enabled"] = patch.is_enabled
        written = self.account.model_copy(update=changed)
        if write_ahead is not None:
            await write_ahead(written)  # raising here rolls the write back
        if (landed := self.faults.pop("commit", None)) is not None:
            if isinstance(landed, asyncio.CancelledError):  # cancelled as the commit lands
                self.account = written
            raise landed
        self.account = written
        self.log.append("committed")
        return written

    def hold(self, account_id: UUID, reason: str) -> None:
        self._hit("hold")

    def release(self, account_id: UUID) -> bool:
        self._hit("release")
        return True

    async def account_revoked(self, account_id: UUID, reason: str) -> int:
        assert reason == "account_disabled"
        self._hit("ws")
        return 1

    async def disarm(
        self, account_id: UUID, *, lifecycle: str, actor: UUID, role: str, at: datetime
    ) -> object:
        assert (lifecycle, actor, role, at) == ("account_disabled", ACTOR, "owner", AT)
        self._hit("disarm")
        return None

    async def close_private_streams(self, key_ref: str, *, reason: str) -> tuple[UUID, ...]:
        assert reason == "account_disabled"
        self._hit(f"close:{key_ref}")
        return ()

    def reopen_private_streams(self, key_ref: str, *, reason: str) -> bool:
        assert reason == "account_disabled"
        self._hit(f"lift:{key_ref}")
        return True

    def lifecycle(self) -> AccountLifecycle:
        return AccountLifecycle(
            self, self, self, self, self, clock=lambda: AT, count=self.counted.append
        )


async def _record(world: World) -> WriteAhead:
    async def ahead(stored: ExchangeAccount) -> None:
        world.log.append(f"record:{stored.is_enabled}")

    return ahead


async def _disable(world: World, **kw: Any) -> Any:
    return await world.lifecycle().disable(
        OWNER, world.account, label=kw.pop("label", None), if_match=kw.pop("if_match", None),
        write_ahead=kw.pop("write_ahead", await _record(world)), reason="flat", actor=ACTOR,
        role="owner",
    )  # fmt: skip


async def test_a_disable_is_stored_with_its_record_ahead_then_holds_revokes_disarms_and_closes(
) -> None:  # fmt: skip
    world = World()
    done = await _disable(world)
    assert world.log == STORED
    assert done.stored and not done.account.is_enabled and world.counted == ["flat"]


@pytest.mark.parametrize("fault", ["ws", "disarm", "keys", f"close:{K1}", f"close:{K2}"])
async def test_a_fault_after_the_commit_leaves_the_disable_stored_and_a_repeat_completes_it(
    fault: str,
) -> None:
    """The crash or fault between the commit and the effects: the account is disabled and held,
    and the retry, a repeat, does every effect again (each is idempotent) with no record."""
    world = World()
    world.faults[fault] = RuntimeError("fault")
    with pytest.raises(RuntimeError):
        await _disable(world)
    assert "committed" in world.log and world.log.index("hold") < world.log.index("committed")
    assert not world.account.is_enabled
    world.log.clear()
    again = await _disable(world)
    assert world.log == [*EFFECTS[:3], "keys", *EFFECTS[3:]]  # no compare-and-set, no record
    assert not again.stored and world.counted == ["flat"]


async def test_an_overrun_close_is_raised_after_the_hold_the_revoke_and_the_disarm() -> None:
    """Only the close is pending after an overrun (ruling 4); M13 never catches it (M23 does)."""
    world = World()
    world.faults[f"close:{K1}"] = PrivateStreamCloseOverran((ACCOUNT.id,))
    with pytest.raises(PrivateStreamCloseOverran):
        await _disable(world)
    assert world.log[-4:] == ["ws", "disarm", "keys", f"close:{K1}"]


async def test_an_overrun_disable_completed_by_its_retry_is_counted_once() -> None:
    """hpe-worker-2 item 4: the count follows the commit, before any effect, so the overrun's
    `503` has counted it and the retry, a repeat, counts nothing."""
    world = World()
    world.faults[f"close:{K1}"] = PrivateStreamCloseOverran((ACCOUNT.id,))
    with pytest.raises(PrivateStreamCloseOverran):
        await _disable(world)
    assert world.counted == ["flat"]
    again = await _disable(world)
    assert not again.stored and world.counted == ["flat"]


async def test_a_write_ahead_refused_stores_nothing_and_does_no_effect() -> None:
    world = World()

    async def refused(stored: ExchangeAccount) -> None:
        raise RuntimeError("the audit writer is down")

    with pytest.raises(RuntimeError):
        await _disable(world, write_ahead=refused)
    assert world.log == ["cas", "hold", "release"]  # the hook's hold, released on the rollback
    assert world.account.is_enabled and world.counted == []


async def test_a_commit_that_fails_after_the_hook_releases_its_hold_and_does_no_effect() -> None:
    """hpe-worker-2 item 3: the hold is placed in the write-ahead hook, before the commit; a
    commit that fails leaves the row enabled, so the hold is released and nothing follows."""
    world = World()
    world.faults["commit"] = RuntimeError("the commit failed")
    with pytest.raises(RuntimeError):
        await _disable(world)
    assert world.log == ["cas", "hold", "record:False", "release"]
    assert world.account.is_enabled and world.counted == []


@pytest.mark.parametrize("landed", [False, True])
async def test_a_cancelled_disable_keeps_its_hold_and_the_retry_completes_it(landed: bool) -> None:
    """hpe-worker-2 item 3: a cancellation in the hook or as the commit lands keeps the hold
    (never released, never shielded) and propagates; the retry is a disable again, or a repeat
    when the commit had landed, and completes every effect."""
    world = World()

    async def cancelled(stored: ExchangeAccount) -> None:
        world.log.append("record:False")
        if not landed:  # cancelled while the record is written, inside the hook
            raise asyncio.CancelledError

    if landed:
        world.faults["commit"] = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await _disable(world, write_ahead=cancelled)
    assert world.log == ["cas", "hold", "record:False"] and world.counted == []
    assert world.account.is_enabled is not landed
    world.log.clear()
    again = await _disable(world)
    assert again.stored is not landed and not world.account.is_enabled
    assert world.log == ([*EFFECTS[:3], "keys", *EFFECTS[3:]] if landed else STORED)


async def test_a_stale_tag_in_the_write_is_raised_and_nothing_follows() -> None:
    world = World()
    world.faults["cas"] = AccountVersionConflictError()
    with pytest.raises(AccountVersionConflictError):
        await _disable(world, if_match=AT)
    assert world.log == ["cas"] and world.counted == []  # no hook ran: no hold, none released


async def test_a_concurrent_disable_makes_this_one_a_repeat_with_no_record() -> None:
    """Ruling 6: the second disable's compare-and-set misses on `expect_enabled`."""
    world = World()
    world.unchanged = True
    done = await _disable(world)
    assert world.log == ["cas", "get", *EFFECTS[:3], "keys", *EFFECTS[3:]]
    assert not done.stored and world.counted == []


async def test_a_repeat_disable_stores_nothing_and_completes_the_effects() -> None:
    world = World(enabled=False)
    done = await _disable(world, label="ignored")
    assert world.log == [*EFFECTS[:3], "keys", *EFFECTS[3:]] and not done.stored
    assert done.account.label == ACCOUNT.label


async def test_a_re_enable_lifts_each_signable_key_before_the_write_then_releases() -> None:
    world = World(enabled=False)
    done = await world.lifecycle().enable(
        OWNER, world.account, label="renamed", if_match=None, write_ahead=await _record(world)
    )
    assert world.log == [
        "keys", f"lift:{K1}", f"lift:{K2}", "cas", "record:True", "committed", "release",
    ]  # fmt: skip
    assert done.stored and done.account.is_enabled and done.account.label == "renamed"


@pytest.mark.parametrize(
    "fault", [AccountVersionConflictError(), AccountConflictError("label"), RuntimeError("store")]
)
async def test_a_re_enable_whose_write_fails_re_tombstones_each_key_and_releases_nothing(
    fault: Exception,
) -> None:
    """Round-1 F-2: the lift ran, the write did not; each lifted key is closed again with
    `account_disabled` (its tombstone set again), and the store's failure is the one raised."""
    world = World(enabled=False)
    world.faults["cas"] = fault
    with pytest.raises(type(fault)):
        await world.lifecycle().enable(
            OWNER, world.account, label=None, if_match=AT, write_ahead=await _record(world)
        )
    assert world.log == [
        "keys", f"lift:{K1}", f"lift:{K2}", "cas", f"close:{K1}", f"close:{K2}",
    ]  # fmt: skip
    assert "release" not in world.log and not world.account.is_enabled


async def test_a_re_tombstone_that_overruns_still_raises_the_stores_failure() -> None:
    """The adapter sets the tombstone before its close runs, so an overrun of the re-close leaves
    the key closed; the answer is the store's failure, and every key is still re-closed."""
    world = World(enabled=False)
    world.faults["cas"] = AccountVersionConflictError()
    world.faults[f"close:{K1}"] = PrivateStreamCloseOverran((ACCOUNT.id,))
    with pytest.raises(AccountVersionConflictError):
        await world.lifecycle().enable(
            OWNER, world.account, label=None, if_match=AT, write_ahead=await _record(world)
        )
    assert world.log[-2:] == [f"close:{K1}", f"close:{K2}"]


@pytest.mark.parametrize("raced", [False, True])
async def test_a_repeat_re_enable_stores_nothing_and_lifts_and_releases(raced: bool) -> None:
    world = World(enabled=raced is False)
    world.unchanged = raced
    done = await world.lifecycle().enable(
        OWNER, world.account, label=None, if_match=None, write_ahead=await _record(world)
    )
    middle = ["cas", "get"] if raced else []
    assert world.log == ["keys", f"lift:{K1}", f"lift:{K2}", *middle, "release"]
    assert not done.stored and done.account.is_enabled


async def test_a_relabel_is_one_write_with_its_record_and_no_effect() -> None:
    world = World()
    got = await world.lifecycle().relabel(
        OWNER, ACCOUNT.id, "new", if_match=AT, write_ahead=await _record(world)
    )
    assert world.log == ["cas", "record:True", "committed"] and got.label == "new"
