"""In-memory `UserRepository` fake for auth unit tests. No database, no network."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta

from candleviewer.auth.mfa_repository import MfaRepository
from candleviewer.auth.models import MfaMethodKind, SessionRecord, UserRecord, UserStatus
from candleviewer.auth.repository import UserRepository
from candleviewer.auth.session_repository import SessionRepository
from candleviewer.auth.step_up import ResetAudit
from candleviewer.storage.errors import ActorNotAuthorised


async def no_wait(_delay: float) -> None:
    """#4664: the injected wait for suites that do not test the minimum time of a refused step.
    A service refuses a minimum time below the setting's lowest value, so such a suite keeps the
    minimum and skips the wait instead (the hold itself still runs)."""


class FakeUserRepository(UserRepository):
    def __init__(self) -> None:
        self.users: dict[str, UserRecord] = {}
        self.rehash_calls: list[tuple[str, str, dict[str, int]]] = []
        #: #2110: retired hashes per user, `(retired_at, hash)`; `fail_change` makes a change raise.
        self.history: dict[str, list[tuple[datetime, str]]] = {}
        self.fail_change: Exception | None = None
        #: Where `record_login_failure` puts its work for an id with no row; never read.
        self._discarded: dict[str, UserRecord] = {}

    def add(self, user: UserRecord) -> None:
        self.users[str(user.id)] = user

    async def find_by_identifier(self, identifier: str) -> UserRecord | None:
        needle = identifier.lower()
        for user in self.users.values():
            if user.username.lower() == needle or user.email.lower() == needle:
                return user
        return None

    async def find_by_id(self, user_id: str) -> UserRecord | None:
        return self.users.get(user_id)

    async def record_login_success(self, user_id: str) -> None:
        user = self.users[user_id]
        self.users[user_id] = user.model_copy(
            update={"failed_login_count": 0, "locked_until": None}
        )

    async def record_sign_in_unless_locked(self, user_id: str, *, now: datetime) -> bool:
        # The lock check and the reset in one synchronous step, as the SQL's conditional update.
        user = self.users.get(user_id)
        if user is None or (user.locked_until is not None and user.locked_until > now):
            return False
        self.users[user_id] = user.model_copy(
            update={"failed_login_count": 0, "locked_until": None}
        )
        return True

    async def record_login_failure(
        self, user_id: str, *, lockout_threshold: int, lock_duration: timedelta, now: datetime
    ) -> datetime | None:
        # Single-threaded fake: the increment and the lock decision happen
        # in one synchronous step (no `await` between read and write), which
        # is the atomicity the real SQL statement must also provide.
        # An id with no row (the login placeholder's nil UUID) changes no row and returns
        # None, like the SQL UPDATE, but does the same record work on a stand-in and discards
        # it, so the fake costs both login failure paths the same.
        user = self.users.get(user_id)
        rows = self.users if user is not None else self._discarded
        if user is None:
            user = _ABSENT_ROW
        new_count = user.failed_login_count + 1
        lock_until = now + lock_duration if new_count >= lockout_threshold else None
        update: dict[str, object] = {"failed_login_count": new_count}
        if lock_until is not None:
            update["locked_until"] = lock_until
        rows[user_id] = user.model_copy(update=update)
        return lock_until if rows is self.users else None

    async def rehash_password(
        self, user_id: str, *, password_hash: str, algo_params: dict[str, int]
    ) -> None:
        self.rehash_calls.append((user_id, password_hash, algo_params))
        user = self.users[user_id]
        self.users[user_id] = user.model_copy(
            update={"password_hash": password_hash, "password_algo_params": algo_params}
        )

    async def set_mfa_required(self, user_id: str) -> None:
        user = self.users.get(user_id)
        if user is not None:  # an unknown id changes no row, like the SQL UPDATE
            self.users[user_id] = user.model_copy(update={"mfa_required": True})

    # -- #2110: the password change's store (`PasswordStore`, 21 Sec.3.1.1a) -----------------

    async def recent_password_hashes(self, user_id: str, *, limit: int) -> tuple[str, ...]:
        rows = sorted(self.history.get(user_id, []), reverse=True)
        return tuple(h for _, h in rows[:limit])

    async def change_password(
        self,
        user_id: str,
        *,
        expected_hash: str,
        new_hash: str,
        algo_params: dict[str, int],
        keep: int,
        now: datetime,
    ) -> bool:
        """The compare-and-swap, the retirement and the prune in one synchronous step."""
        if self.fail_change is not None:
            raise self.fail_change
        user = self.users.get(user_id)
        if user is None or user.password_hash != expected_hash:
            return False
        self.users[user_id] = user.model_copy(
            update={"password_hash": new_hash, "password_algo_params": algo_params}
        )
        rows = sorted([*self.history.get(user_id, []), (now, expected_hash)], reverse=True)
        self.history[user_id] = rows[:keep]
        return True


def make_user(
    *,
    username: str = "basiltt",
    email: str = "owner@example.com",
    password_hash: str,
    status: UserStatus = UserStatus.ACTIVE,
    mfa_required: bool = True,
    mfa_methods: tuple[MfaMethodKind, ...] = (MfaMethodKind.TOTP,),
    failed_login_count: int = 0,
    locked_until: datetime | None = None,
    algo_params: dict[str, int] | None = None,
) -> UserRecord:
    return UserRecord(
        id=uuid.uuid4(),
        username=username,
        email=email,
        password_hash=password_hash,
        password_algo_params=algo_params or {"m": 65536, "t": 3, "p": 4},
        status=status,
        mfa_required=mfa_required,
        failed_login_count=failed_login_count,
        locked_until=locked_until,
        mfa_methods=mfa_methods,
    )


#: When a fake full session proved its second factor (`SessionRecord.mfa_satisfied_at`).
MFA_PROVED_AT = datetime(2026, 1, 1, tzinfo=UTC)


class FullUsers:
    """The user store of a test world whose fake sessions stand for full ones (#2295): any id
    reads as an active user with a confirmed TOTP method, so the enrolment-only guard serves a
    session that proved it (`mfa_satisfied_at`) and the route's own checks decide. Given a fake
    session store's `user_statuses`, it follows them as the one `users` row does (#2911): a user
    reads as `disabled` there, or as gone (`None`)."""

    def __init__(self, statuses: Mapping[str, UserStatus | None] | None = None) -> None:
        self._statuses: Mapping[str, UserStatus | None] = {} if statuses is None else statuses

    async def find_by_id(self, user_id: str) -> UserRecord | None:
        status = self._statuses.get(user_id, UserStatus.ACTIVE)
        if status is None:
            return None
        user = make_user(password_hash="unused", status=status)
        return user.model_copy(update={"id": uuid.UUID(user_id)})


#: `record_login_failure`'s stand-in for an id with no row: a user shaped like `make_user`'s.
_ABSENT_ROW = make_user(password_hash="unused").model_copy(update={"id": uuid.UUID(int=0)})


class InMemoryOwnerReset:
    """`auth.step_up.OwnerTotpReset` over the in-memory repositories (#2593): `active_owner` is
    the actor's re-read (every actor passes by default), refused with the store's
    `ActorNotAuthorised` before anything; then the audit with the counts, then the writes, through
    the repositories' own methods (a test's holds on them still apply). No transaction exists in
    memory, so the record goes ahead of the writes; the Postgres store's one unit of work is
    covered by its integration test."""

    def __init__(
        self,
        users: UserRepository,
        mfa: MfaRepository,
        sessions: SessionRepository,
        *,
        active_owner: Callable[[str], bool] = lambda _actor: True,
    ) -> None:
        self._users, self._mfa, self._sessions = users, mfa, sessions
        self.active_owner = active_owner

    async def reset_totp(
        self,
        target_user_id: str,
        *,
        actor_user_id: str,
        now: datetime,
        reason: str,
        audit: ResetAudit,
    ) -> tuple[int, tuple[SessionRecord, ...]] | None:
        if not self.active_owner(actor_user_id):
            raise ActorNotAuthorised(actor_user_id)
        methods = await self._mfa.find_active_methods(target_user_id)
        live = await self._sessions.find_live_by_user(target_user_id)
        await audit(len(methods), len(live))
        await self._users.set_mfa_required(target_user_id)
        for method in methods:
            await self._mfa.revoke_method(str(method.id), now=now)
        revoked = await self._sessions.revoke_all_for_user(target_user_id, reason=reason, now=now)
        return len(methods), revoked
