"""Seeded mutants for MFA's `503 auth_unavailable` decisions (#2152 S5b; repo convention, see
`tests/unit/credentials_m2/test_mutations.py`). Each case injects one plausible defect via
monkeypatch, runs the real oracle of `test_mfa_unavailable.py` under it and asserts the oracle
fails (mutant killed); every oracle passes unmutated, with the same seams."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from candleviewer.auth import invite_service, login_service, mfa_service, step_up
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.login_service import LoginService
from candleviewer.auth.mfa_keyring import require_available
from candleviewer.auth.models import UserRecord
from tests.unit.auth import test_mfa_unavailable as oracles

_KILLED = (AssertionError, pytest.fail.Exception)
Oracle = Callable[[], Awaitable[None]]


async def _no_check(*_args: Any, **_kwargs: Any) -> None:
    return None  # the 503 is never decided up front


async def _late(self: LoginService, user: UserRecord) -> None:
    """The 503 decided after the success path's first write: the count is reset."""
    await self._repository.record_login_success(str(user.id))
    await require_available(self._mfa_keyring, user_id=user.id)


#: (target, attribute, mutant, oracle): what each defect breaks and the test that sees it.
MUTANTS: dict[str, tuple[object, str, object, Oracle]] = {
    "login_resets_the_count_before_the_503": (
        LoginService, "_require_keyring", _late,
        oracles.test_login_answers_unavailable_after_the_password_and_writes_nothing,
    ),
    "unopenable_method_counts_as_no_method": (
        login_service, "require_available", _no_check,
        oracles.test_a_method_under_a_key_not_held_is_unavailable_never_no_method,
    ),
    "verify_checks_some_methods_first": (
        mfa_service, "require_available", _no_check,
        oracles.test_one_method_this_process_cannot_open_is_enough_for_the_503,
    ),
    "step_up_verifies_the_password_first": (
        step_up, "require_available", _no_check,
        oracles.test_step_up_answers_unavailable_before_either_factor,
    ),
    "redemption_hashes_before_the_503": (
        invite_service.InviteService, "begin_redemption", None,
        oracles.test_redemption_answers_unavailable_before_the_hash_and_the_token_is_kept,
    ),
}  # fmt: skip


def _hash_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """The redemption with its two steps swapped: the password hashed, then the keyring checked."""
    real = invite_service.InviteService.begin_redemption

    async def swapped(self: Any, token: str, *, password: str, source_ip: str) -> Any:
        await self._hasher.hash(password, None)
        return await real(self, token, password=password, source_ip=source_ip)

    monkeypatch.setattr(invite_service.InviteService, "begin_redemption", swapped)


@pytest.fixture(autouse=True)
async def _hashed() -> None:
    """The oracles' module hashes `PW` once in a fixture of its own, which a direct call skips."""
    if "pw" not in oracles._HASHES:
        oracles._HASHES["pw"] = await Hasher().hash(oracles.PW)


@pytest.mark.parametrize("name", sorted(MUTANTS))
async def test_mutant_killed(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    target, attribute, mutant, oracle = MUTANTS[name]
    if mutant is None:
        _hash_first(monkeypatch)
    else:
        monkeypatch.setattr(target, attribute, mutant)
    with pytest.raises(_KILLED):
        await oracle()


@pytest.mark.parametrize("name", sorted(MUTANTS))
async def test_every_oracle_passes_unmutated(name: str) -> None:
    """The kill above comes from the mutant: the same oracle passes."""
    await MUTANTS[name][3]()
