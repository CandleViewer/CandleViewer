"""`PasswordChangeService` (#2110; `22` `authChangePassword` steps 5 to 8; BQ-225 / 226 / 227 /
232): the order of checks, the history, the shared verification bound and the compare-and-swap.
In-memory store and a fake hasher; no I/O, no clock reads but the injected one."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from candleviewer.auth.errors import CurrentPasswordInvalid, PasswordRefused, SignInBusy
from candleviewer.auth.failure_hold import FailureHold
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.password_service import HISTORY_KEPT, PasswordChangeService
from candleviewer.auth.step_up import PasswordVerdict
from candleviewer.auth.throttle import VerifyAdmission
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user, no_wait

T0 = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
OLD = "old-password-Zq7!xx"
NEW = "new-password-Kp4#yy"
_LOCK = datetime(2026, 10, 31, 12, 15, tzinfo=UTC)


class FakeHasher(Hasher):
    """A reversible stand-in: the Argon2id prefix and the password, so a test can read it."""

    def __init__(self) -> None:
        super().__init__()
        self.verified: list[str] = []
        self.hashed = 0

    async def hash(self, password: str, params: dict[str, int] | None = None) -> str:
        self.hashed += 1
        return f"$argon2id$fake${password}"

    async def verify(self, password_hash: str, password: str) -> bool:
        self.verified.append(password_hash)
        return password_hash == f"$argon2id$fake${password}"


class Verifier:
    """`StepUpService.verify_password`'s seam: login's verdict, and the order of calls."""

    def __init__(self, users: FakeUserRepository, calls: list[str]) -> None:
        self._users, self._calls = users, calls
        self.locks = False
        self.failure_hold = FailureHold(timedelta(milliseconds=250), sleep=no_wait)

    async def verify_password(
        self, user_id: str, password: str, *, hold: bool = True
    ) -> PasswordVerdict:
        assert hold is False  # the route holds the refusal after its rows
        self._calls.append("verify_current")
        user = await self._users.find_by_id(user_id)
        ok = user is not None and user.password_hash == f"$argon2id$fake${password}"
        return PasswordVerdict(ok=ok, locked_until=None if ok or not self.locks else _LOCK)


class Store(FakeUserRepository):
    def __init__(self, calls: list[str]) -> None:
        super().__init__()
        self._calls = calls

    async def recent_password_hashes(self, user_id: str, *, limit: int) -> tuple[str, ...]:
        self._calls.append("history")
        return await super().recent_password_hashes(user_id, limit=limit)


def _world(
    *, admission: VerifyAdmission | None = None
) -> tuple[PasswordChangeService, Store, str, list[str], FakeHasher, Verifier]:
    calls: list[str] = []
    store = Store(calls)
    user = make_user(
        username="annie", email="ann@example.com", password_hash=f"$argon2id$fake${OLD}"
    )
    store.add(user)
    hasher, verifier = FakeHasher(), Verifier(store, calls)
    service = PasswordChangeService(
        store,
        verifier,
        hasher,
        admission=admission or VerifyAdmission(2),
        clock=lambda: T0,
        breached=frozenset(),
    )
    return service, store, str(user.id), calls, hasher, verifier


async def test_a_good_change_hashes_the_new_password_and_swaps_from_the_verified_hash() -> None:
    service, store, uid, calls, hasher, _ = _world()
    change = await service.prepare(uid, current=OLD, new=NEW)
    assert calls == ["verify_current", "history"]
    assert change.expected_hash == f"$argon2id$fake${OLD}" and change.new_hash.endswith(NEW)
    assert hasher.hashed == 1
    assert await service.commit(change) is True
    assert store.users[uid].password_hash == change.new_hash
    assert store.history[uid] == [(T0, f"$argon2id$fake${OLD}")]


async def test_a_wrong_current_password_reads_no_history_and_checks_no_rule() -> None:
    """No rule on the new password runs before the current one verifies (no oracle)."""
    service, _, uid, calls, hasher, _ = _world()
    with pytest.raises(CurrentPasswordInvalid) as refused:
        await service.prepare(uid, current="not-it", new="short")
    assert refused.value.locked_until is None
    assert calls == ["verify_current"] and hasher.hashed == 0


async def test_a_wrong_current_password_that_locks_the_account_says_until_when() -> None:
    service, _, uid, _, _, verifier = _world()
    verifier.locks = True
    with pytest.raises(CurrentPasswordInvalid) as refused:
        await service.prepare(uid, current="not-it", new=NEW)
    assert refused.value.locked_until == _LOCK


@pytest.mark.parametrize(
    ("new", "code", "rule"),
    [
        ("Zq7!short", "password_policy", "min_length"),
        ("annie-is-my-name-9", "password_policy", "contains_identity"),
        ("abababababababab", "password_breached", None),
    ],
)
async def test_a_policy_refusal_names_its_code_and_rule(
    new: str, code: str, rule: str | None
) -> None:
    service, _, uid, calls, hasher, _ = _world()
    with pytest.raises(PasswordRefused) as refused:
        await service.prepare(uid, current=OLD, new=new)
    assert (refused.value.code, refused.value.rule) == (code, rule)
    assert "history" not in calls and hasher.hashed == 0


async def test_a_listed_password_is_breached() -> None:
    service, store, uid, _, _, verifier = _world()
    listed = PasswordChangeService(
        store, verifier, FakeHasher(), admission=VerifyAdmission(1), clock=lambda: T0
    )
    with pytest.raises(PasswordRefused) as refused:
        await listed.prepare(uid, current=OLD, new="passwordpassword")
    assert refused.value.code == "password_breached"
    assert service is not listed


async def test_the_current_password_again_is_reused_without_a_second_hash() -> None:
    service, _, uid, _, hasher, _ = _world()
    with pytest.raises(PasswordRefused) as refused:
        await service.prepare(uid, current=OLD, new=OLD)
    assert refused.value.code == "password_reused" and refused.value.rule is None
    assert hasher.verified == [] and hasher.hashed == 0


async def test_each_of_the_last_4_retired_passwords_is_reused_and_the_5th_back_is_not() -> None:
    service, store, uid, _, _, _ = _world()
    retired = [f"retired-pass-{i}-Zq7!" for i in range(HISTORY_KEPT + 1)]
    store.history[uid] = [
        (T0 - timedelta(days=i + 1), f"$argon2id$fake${pw}") for i, pw in enumerate(retired)
    ]
    for pw in retired[:HISTORY_KEPT]:
        with pytest.raises(PasswordRefused) as refused:
            await service.prepare(uid, current=OLD, new=pw)
        assert refused.value.code == "password_reused"
    change = await service.prepare(uid, current=OLD, new=retired[HISTORY_KEPT])
    assert await service.commit(change)
    assert len(store.history[uid]) == HISTORY_KEPT  # pruned in the same unit of work


async def test_a_full_verification_bound_refuses_at_once_and_a_refusal_frees_its_place() -> None:
    """BQ-226: one bound with sign-in; a refusal or a success gives its place back."""
    bound = VerifyAdmission(1)
    service, _, uid, calls, _, _ = _world(admission=bound)
    assert bound.try_enter()
    with pytest.raises(SignInBusy):
        await service.prepare(uid, current=OLD, new=NEW)
    assert calls == []
    bound.leave()
    with pytest.raises(CurrentPasswordInvalid):
        await service.prepare(uid, current="not-it", new=NEW)
    assert bound.in_flight == 0
    await service.prepare(uid, current=OLD, new=NEW)
    assert bound.in_flight == 0


async def test_a_concurrent_change_that_won_first_makes_the_commit_write_nothing() -> None:
    """BQ-232: the swap is against the hash read before the verification."""
    service, store, uid, _, _, _ = _world()
    first = await service.prepare(uid, current=OLD, new=NEW)
    second = await service.prepare(uid, current=OLD, new="another-one-Kp4#zz")
    assert await service.commit(first) is True
    assert await service.commit(second) is False
    assert store.users[uid].password_hash == first.new_hash
    assert store.history[uid] == [(T0, f"$argon2id$fake${OLD}")]


async def test_an_unknown_user_is_refused_as_a_wrong_current_password() -> None:
    service, _, _, _, _, _ = _world()
    with pytest.raises(CurrentPasswordInvalid):
        await service.prepare("00000000-0000-4000-8000-000000000000", current=OLD, new=NEW)
