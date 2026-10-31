"""`PasswordChangeService`: the checks of `PUT /auth/password` (#2110, #2330; `22`
`authChangePassword`; `04-security-program.md` SR-028 and Sec.6.3.1).

`prepare()` runs steps 5 to 8 of the contract's order and changes nothing but the lockout
counters a wrong current password moves: a verification place (`VerifyAdmission`, shared
with sign-in; `SignInBusy` when full), the current password on login's Argon2id path and
lockout counters (`StepUpService.verify_password`, so a locked account fails alike;
`CurrentPasswordInvalid`), then the policy (`auth.password_policy`) and the history (the current
password and the last 4 retired; `PasswordRefused`), then the new hash. No rule on the new
password runs before the current one verifies, so a hijacked session cannot use the refusals as
an oracle. `commit()` is the store's compare-and-swap against the hash read *before* the
verification, so a change that won meanwhile makes it write nothing (`False`). The HTTP edge
writes the audit records between the two (C-2.9).
"""

from __future__ import annotations

import hmac
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from candleviewer.auth import password_policy
from candleviewer.auth.errors import CurrentPasswordInvalid, PasswordRefused, SignInBusy
from candleviewer.auth.failure_hold import FailureHold
from candleviewer.auth.hashing import DEFAULT_ARGON2_PARAMS, Hasher
from candleviewer.auth.login_service import LOGIN_BUSY_RETRY_AFTER_S
from candleviewer.auth.models import UserRecord
from candleviewer.auth.step_up import PasswordVerdict
from candleviewer.auth.throttle import VerifyAdmission

#: Retired hashes kept per user: with the current one, the last 5 (SCR-004, SR-028).
HISTORY_KEPT = 4
REUSED_DETAIL = "You can't reuse any of your last 5 passwords."


class PasswordStore(Protocol):
    """The user rows a change reads and the one unit of work it writes (21 Sec.3.1.1a)."""

    async def find_by_id(self, user_id: str) -> UserRecord | None: ...

    async def recent_password_hashes(self, user_id: str, *, limit: int) -> tuple[str, ...]: ...

    async def change_password(
        self,
        user_id: str,
        *,
        expected_hash: str,
        new_hash: str,
        algo_params: dict[str, int],
        keep: int,
        now: datetime,
    ) -> bool: ...


class PasswordVerifier(Protocol):
    """`StepUpService`'s password check: login's path and counters, and its minimum time."""

    @property
    def failure_hold(self) -> FailureHold: ...

    async def verify_password(
        self, user_id: str, password: str, *, hold: bool = True
    ) -> PasswordVerdict: ...


@dataclass(frozen=True, slots=True)
class PreparedChange:
    """A change every check passed: the hash to swap from and the new one. Never the password."""

    user_id: str
    expected_hash: str
    new_hash: str
    algo_params: dict[str, int]


class PasswordChangeService:
    def __init__(
        self,
        store: PasswordStore,
        verifier: PasswordVerifier,
        hasher: Hasher,
        *,
        admission: VerifyAdmission,
        clock: Callable[[], datetime],
        breached: frozenset[str] | None = None,
    ) -> None:
        self._store = store
        self._verifier = verifier
        self._hasher = hasher
        self._admission = admission
        self._clock = clock
        #: Read once here, at start, so a damaged list fails the start, never a request.
        self._breached = password_policy.breached_list() if breached is None else breached

    @property
    def failure_hold(self) -> FailureHold:
        """The minimum time of a refused current password (#4664), held by the caller after its
        refusal's records are written."""
        return self._verifier.failure_hold

    async def prepare(self, user_id: str, *, current: str, new: str) -> PreparedChange:
        """Steps 5 to 8 of `authChangePassword`. Raises `SignInBusy`, `CurrentPasswordInvalid`
        (not held: the caller holds it with `failure_hold`) or `PasswordRefused`."""
        if not self._admission.try_enter():
            raise SignInBusy(LOGIN_BUSY_RETRY_AFTER_S)
        try:
            return await self._prepare_admitted(user_id, current=current, new=new)
        finally:
            self._admission.leave()

    async def _prepare_admitted(self, user_id: str, *, current: str, new: str) -> PreparedChange:
        # Read before the verification: the compare-and-swap is against this hash, so a change
        # that commits between this read and the commit below leaves this one writing nothing.
        user = await self._store.find_by_id(user_id)
        verdict = await self._verifier.verify_password(user_id, current, hold=False)
        if user is None or not verdict.ok:
            raise CurrentPasswordInvalid(verdict.locked_until)
        refused = password_policy.check(
            new, username=user.username, email=user.email, breached=self._breached
        )
        if refused is not None:
            rule = refused.rule if refused.code is password_policy.PolicyCode.POLICY else None
            raise PasswordRefused(refused.code.value, refused.detail, rule)
        # The current password verified, so "equals the current one" needs no second hash.
        if hmac.compare_digest(new.encode("utf-8"), current.encode("utf-8")):
            raise PasswordRefused("password_reused", REUSED_DETAIL)
        for retired in await self._store.recent_password_hashes(user_id, limit=HISTORY_KEPT):
            if await self._hasher.verify(retired, new):
                raise PasswordRefused("password_reused", REUSED_DETAIL)
        params = dict(DEFAULT_ARGON2_PARAMS)
        new_hash = await self._hasher.hash(new, params)
        return PreparedChange(user_id, user.password_hash, new_hash, params)

    async def commit(self, change: PreparedChange) -> bool:
        """The compare-and-swap, the retirement and the prune, as one unit of work; `False`, with
        nothing written, when a concurrent change won first."""
        return await self._store.change_password(
            change.user_id,
            expected_hash=change.expected_hash,
            new_hash=change.new_hash,
            algo_params=change.algo_params,
            keep=HISTORY_KEPT,
            now=self._clock(),
        )
