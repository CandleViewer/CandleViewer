"""#898 B3d (E27-S04): `accounts.key_revoke`, the key revoke's effects in ruling item 4's order
(destroy, hold, then for the last signable key the WS revoke and the disarm, then the close),
the repeat's, and the completion payload kept per key (bounded) or derived from the same inputs
once it is gone (R7). One ordered log; no I/O, no sleeps."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from candleviewer.accounts.errors import KeyDestroyFailedError
from candleviewer.accounts.key_revoke import (
    MEMO_KEYS,
    Completion,
    KeyRevoke,
    completion,
    last_signable,
)
from candleviewer.accounts.locks import AccountLocks
from candleviewer.accounts.models import KeyStatus
from candleviewer.exchange.base.errors import PrivateStreamCloseOverran
from tests.unit.accounts.test_exposure_read import ACCOUNT, key

ACTOR = UUID(int=78)
AT = datetime(2026, 10, 28, 12, tzinfo=UTC)
K1, K2, K3 = UUID(int=1), UUID(int=2), UUID(int=3)
LAST = ["destroy", "standing_revoke", "ws", "disarm", "close"]


class Ports:
    """Every port of the revoke, logging into one ordered `log`; `faults` names the next raise."""

    def __init__(self) -> None:
        self.log: list[str] = []
        self.faults: dict[str, BaseException] = {}

    def _hit(self, name: str) -> None:
        self.log.append(name)
        if name in self.faults:
            raise self.faults.pop(name)

    def hold(self, account_id: UUID, reason: str) -> None:
        raise AssertionError("a revoke holds no lifecycle")

    def release(self, account_id: UUID) -> bool:
        raise AssertionError("a revoke releases nothing")

    def revoke(self, account_id: UUID, key_id: UUID) -> None:
        assert (account_id, key_id) == (ACCOUNT.id, K1)
        self._hit("standing_revoke")

    async def account_revoked(self, account_id: UUID, reason: str) -> int:
        assert reason == "key_revoked"
        self._hit("ws")
        return 1

    async def disarm(
        self, account_id: UUID, *, lifecycle: str, actor: UUID, role: str, at: datetime
    ) -> object:
        assert (lifecycle, actor, role, at) == ("key_revoked", ACTOR, "owner", AT)
        self._hit("disarm")
        return None

    async def close_private_streams(self, key_ref: str, *, reason: str) -> tuple[UUID, ...]:
        assert (key_ref, reason) == (str(K1), "key_revoked")
        self._hit("close")
        return (ACCOUNT.id,)

    def reopen_private_streams(self, key_ref: str, *, reason: str) -> bool:
        raise AssertionError("a revoke lifts nothing")

    async def destroy(
        self, account_id: UUID, key_id: UUID, *, actor_user_id: str, actor_role: str
    ) -> None:
        assert (account_id, key_id, actor_user_id, actor_role) == (
            ACCOUNT.id, K1, str(ACTOR), "owner",
        )  # fmt: skip
        self._hit("destroy")

    def revoker(self, memo_keys: int = MEMO_KEYS) -> KeyRevoke:
        return KeyRevoke(self, self, self, self, self, locks=AccountLocks(), clock=lambda: AT,
                         memo_keys=memo_keys)  # fmt: skip


PAYLOAD = Completion(False, None, (ACCOUNT.id,))


async def _revoke(ports: Ports, revoker: KeyRevoke, *, last: bool = True) -> Completion:
    return await revoker.revoke(
        ACCOUNT.id, K1, last=last, payload=PAYLOAD, actor=ACTOR, role="owner"
    )


async def test_the_last_signable_keys_revoke_runs_in_the_ruled_order() -> None:
    ports = Ports()
    assert await _revoke(ports, ports.revoker()) == PAYLOAD
    assert ports.log == LAST


async def test_another_signable_key_left_ends_no_subscription_and_disarms_nothing() -> None:
    ports = Ports()
    await _revoke(ports, ports.revoker(), last=False)
    assert ports.log == ["destroy", "standing_revoke", "close"]


@pytest.mark.parametrize("step", ["standing_revoke", "ws", "disarm", "close"])
async def test_the_destroy_lands_before_any_later_step_and_a_fault_stops_there(step: str) -> None:
    ports = Ports()
    ports.faults[step] = RuntimeError("down")
    with pytest.raises(RuntimeError):
        await _revoke(ports, ports.revoker())
    assert ports.log == LAST[: LAST.index(step) + 1] and ports.log[0] == "destroy"


async def test_a_key_m2_does_not_destroy_runs_nothing_after_and_keeps_no_payload() -> None:
    ports = Ports()
    revoker = ports.revoker()
    ports.faults["destroy"] = ValueError("credential_unavailable")
    with pytest.raises(KeyDestroyFailedError) as caught:
        await _revoke(ports, revoker)
    assert ports.log == ["destroy"] and caught.value.__cause__ is None
    assert "credential" not in str(caught.value) and K1 not in revoker._memo


async def test_an_overrun_is_raised_once_the_payload_is_kept_for_the_repeat() -> None:
    ports = Ports()
    revoker = ports.revoker()
    ports.faults["close"] = PrivateStreamCloseOverran((ACCOUNT.id,))
    flattened = Completion(True, None, (ACCOUNT.id,))
    with pytest.raises(PrivateStreamCloseOverran):
        await revoker.revoke(ACCOUNT.id, K1, last=True, payload=flattened, actor=ACTOR,
                             role="owner")  # fmt: skip
    ports.log.clear()
    keys = [key(K1, KeyStatus.REVOKED)]
    again = await revoker.complete(ACCOUNT.id, K1, keys=keys, choice=None, actor=ACTOR,
                                   role="owner")  # fmt: skip
    assert again == flattened and ports.log == LAST[1:]  # the memo's, no second destroy


async def test_a_repeat_whose_memo_is_gone_derives_the_same_payload_from_its_inputs() -> None:
    ports = Ports()
    keys = [key(K1, KeyStatus.REVOKED), key(K2, KeyStatus.ACTIVE)]
    first = completion(ACCOUNT.id, choice="flatten_first", last=last_signable(keys, K1))
    derived = await ports.revoker().complete(
        ACCOUNT.id, K1, keys=keys, choice="flatten_first", actor=ACTOR, role="owner"
    )
    assert derived == first == Completion(False, "other_key_signable", (ACCOUNT.id,))
    assert ports.log == ["standing_revoke", "close"]


@pytest.mark.parametrize(
    ("others", "last"),
    [((), True), ((KeyStatus.ACTIVE,), False), ((KeyStatus.ROTATING,), False),
     ((KeyStatus.REVOKED, KeyStatus.PENDING, KeyStatus.INVALID, KeyStatus.EXPIRED), True)],
)  # fmt: skip
def test_last_signable_counts_only_another_active_or_rotating_key(
    others: tuple[KeyStatus, ...], last: bool
) -> None:
    keys = [key(K1)] + [key(UUID(int=10 + i), s) for i, s in enumerate(others)]
    assert last_signable(keys, K1) is last


@pytest.mark.parametrize(
    ("choice", "last", "reason"),
    [(None, False, None), ("leave_positions", False, None), ("flatten_first", True, None),
     ("flatten_first", False, "other_key_signable")],
)  # fmt: skip
def test_the_payload_names_the_no_op_and_the_keys_account(
    choice: Any, last: bool, reason: str | None
) -> None:
    got = completion(ACCOUNT.id, choice=choice, last=last)
    assert (got.flattened, got.reason, got.accounts_closed) == (False, reason, (ACCOUNT.id,))
    shown = got.state(ACCOUNT.id)
    assert ("reason" in shown) is (reason is not None)
    assert shown["accounts_closed"] == [str(ACCOUNT.id)]


async def test_the_memo_is_bounded_oldest_first() -> None:
    ports = Ports()
    revoker = ports.revoker(memo_keys=2)
    for n in range(3):
        revoker._remember(UUID(int=100 + n), PAYLOAD)
    assert list(revoker._memo) == [UUID(int=101), UUID(int=102)]


async def test_the_locks_table_is_empty_once_no_one_holds_or_waits() -> None:
    locks = AccountLocks()
    async with locks.hold(ACCOUNT.id):
        assert len(locks) == 1
    assert len(locks) == 0
