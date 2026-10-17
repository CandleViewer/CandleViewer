"""`UserRepository` — the storage-facing seam `LoginService` depends on
instead of a raw SQL driver (mirrors `candleviewer.audit.repository.AuditRepository`).

`candleviewer.auth` may not import a storage driver directly (ADR-0003,
`.importlinter` `forbidden-storage-drivers-M18`); the concrete implementation
(`candleviewer.storage.repositories.auth_sqlalchemy.SqlAlchemyUserRepository`,
this ticket's own follow-up wiring) lives in M10 and is structurally
compatible with this Protocol without either module importing the other's
types — the composition root injects it into `AuthService(repository=...)`.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from candleviewer.auth.models import UserRecord


class UserRepository(Protocol):
    """Everything `LoginService` needs from the relational tier, expressed
    without any SQL-driver type in its signatures."""

    async def find_by_identifier(self, identifier: str) -> UserRecord | None:
        """Look up by `username` or `email` (case-insensitive `citext`
        columns), or `None` if no such user exists. Never raises for an
        unknown identifier — the enumeration-resistance guarantee is built
        on this returning cleanly so `LoginService` can still run a dummy
        Argon2id verification and take the identical code path."""
        ...

    async def find_by_id(self, user_id: str) -> UserRecord | None:
        """Look up a live user by id (step-up password re-verification,
        #1778 AE), or `None` if absent."""
        ...

    async def record_login_success(self, user_id: str) -> None:
        """Reset `failed_login_count` to 0, clear `locked_until`, stamp
        `last_login_at`/`last_login_ip`. Called only after a real password
        match on an active, unlocked account."""
        ...

    async def record_login_failure(
        self, user_id: str, *, lockout_threshold: int, lock_duration: timedelta, now: datetime
    ) -> datetime | None:
        """Atomically increment `failed_login_count` by 1 and, if the new
        count reaches `lockout_threshold`, set `users.locked_until = now +
        lock_duration` in the same statement (e.g. a single `UPDATE ...
        SET failed_login_count = failed_login_count + 1, locked_until =
        CASE WHEN failed_login_count + 1 >= :threshold THEN :lock_until ELSE
        locked_until END RETURNING locked_until`).

        The increment-and-lock decision must happen in one atomic operation
        here, never as a read-then-write round trip in the caller —
        `LoginService` no longer computes `new_count` itself from a
        (possibly stale) `UserRecord` snapshot, precisely so two concurrent
        wrong-password attempts cannot both observe `failed_login_count - 1`
        and race past the threshold. Returns the resulting `locked_until`
        (or `None` if the account is not newly locked)."""
        ...

    async def rehash_password(
        self, user_id: str, *, password_hash: str, algo_params: dict[str, int]
    ) -> None:
        """Persist a re-hashed `password_hash`/`password_algo_params` after
        a successful verification against out-of-date Argon2id parameters
        (ticket "transparent rehash-on-login when parameters change")."""
        ...

    async def set_mfa_required(self, user_id: str) -> None:
        """Set `users.mfa_required = true` (#2295, Q9: an owner TOTP reset makes the
        target's next sign-in enrolment-only, even for a user exempted from MFA)."""
        ...
