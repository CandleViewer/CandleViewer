"""In-memory `UserRepository` fake for auth unit tests. No database, no network."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from candleviewer.auth.models import MfaMethodKind, UserRecord, UserStatus
from candleviewer.auth.repository import UserRepository


class FakeUserRepository(UserRepository):
    def __init__(self) -> None:
        self.users: dict[str, UserRecord] = {}
        self.rehash_calls: list[tuple[str, str, dict[str, int]]] = []

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

    async def record_login_failure(
        self, user_id: str, *, lockout_threshold: int, lock_duration: timedelta, now: datetime
    ) -> datetime | None:
        # Single-threaded fake: the increment and the lock decision happen
        # in one synchronous step (no `await` between read and write), which
        # is the atomicity the real SQL statement must also provide.
        user = self.users[user_id]
        new_count = user.failed_login_count + 1
        lock_until = now + lock_duration if new_count >= lockout_threshold else None
        update: dict[str, object] = {"failed_login_count": new_count}
        if lock_until is not None:
            update["locked_until"] = lock_until
        self.users[user_id] = user.model_copy(update=update)
        return lock_until

    async def rehash_password(
        self, user_id: str, *, password_hash: str, algo_params: dict[str, int]
    ) -> None:
        self.rehash_calls.append((user_id, password_hash, algo_params))
        user = self.users[user_id]
        self.users[user_id] = user.model_copy(
            update={"password_hash": password_hash, "password_algo_params": algo_params}
        )


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
    session that proved it (`mfa_satisfied_at`) and the route's own checks decide."""

    async def find_by_id(self, user_id: str) -> UserRecord:
        return make_user(password_hash="unused").model_copy(update={"id": uuid.UUID(user_id)})
