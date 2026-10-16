"""`MfaRepository` — the storage-facing seam `MfaService` depends on
(mirrors `auth/repository.py`'s `UserRepository` Protocol: M18 may not
import a storage driver directly, ADR-0003 `forbidden-storage-drivers-M18`).

The concrete implementation lives in M10 (`candleviewer.storage`) and is
structurally compatible with this Protocol without either module importing
the other's types — same composition-root pattern `UserRepository` uses.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from candleviewer.auth.models import MfaChallengeRecord, MfaMethodRecord


class MfaRepository(Protocol):
    """Everything `MfaService` needs from the relational tier."""

    # -- mfa_methods -----------------------------------------------------

    async def create_pending_method(
        self,
        user_id: str,
        *,
        secret_enc: bytes,
        secret_key_ref: str,
        label: str,
    ) -> MfaMethodRecord:
        """Insert a new `mfa_methods` row with `confirmed_at IS NULL`
        (ticket "the method stays pending until confirmed")."""
        ...

    async def find_pending_method(self, method_id: str, user_id: str) -> MfaMethodRecord | None:
        """The confirmable method `method_id` of `user_id`, or `None` (#2295): never
        confirmed (no accepted time step), not revoked, and the user's latest method, so
        only the one the latest enrolment created qualifies. A recovery sign-in revokes
        every method (#2344); one it un-confirmed before that has an accepted step, so
        neither qualifies again."""
        ...

    async def supersede_pending_methods(self, user_id: str, *, now: datetime) -> None:
        """Revoke (`revoked_at = now`) every unconfirmed, unrevoked method of `user_id`
        before a new enrolment starts (#2295: at most one method is pending)."""
        ...

    async def complete_enrollment(
        self,
        user_id: str,
        *,
        method_id: str,
        time_step: int,
        now: datetime,
        code_hashes: tuple[str, ...],
    ) -> MfaMethodRecord | None:
        """#2295, ONE transaction: confirm `method_id` (`confirmed_at = now`, accepted
        `time_step`) only while `find_pending_method` would still return it, revoke every
        other unrevoked TOTP method of `user_id`, and replace the user's recovery codes
        with `code_hashes`, so the old method and codes stop working at the instant the
        new ones start. Returns the confirmed method, or `None` after rolling back when
        the method is no longer confirmable (a concurrent confirm or enrolment won)."""
        ...

    async def find_active_totp_methods(self, user_id: str) -> tuple[MfaMethodRecord, ...]:
        """Confirmed, non-revoked `kind='totp'` methods for `user_id`,
        newest-first."""
        ...

    async def find_active_methods(self, user_id: str) -> tuple[MfaMethodRecord, ...]:
        """Every confirmed, non-revoked method for `user_id` (any kind),
        for SCR-112 and the last-method-protected delete check."""
        ...

    async def record_time_step(self, method_id: str, *, time_step: int) -> bool:
        """Atomically accept `time_step` for `method_id` if and only if it
        is strictly greater than the method's currently stored
        `last_accepted_time_step` (or that column is `NULL`), updating it in
        the same statement. Returns `True` on acceptance, `False` when
        `time_step` is a replay (ticket "Reused code is rejected" — this
        must be a single atomic compare-and-set, never a read-then-write
        round trip, for the identical concurrency reason
        `record_login_failure` documents in `auth/repository.py`)."""
        ...

    async def revoke_method(self, method_id: str, *, now: datetime) -> None:
        """Soft-delete via `revoked_at = now` (never a hard `DELETE` — audit
        trail)."""
        ...

    async def touch_method_used(self, method_id: str, *, now: datetime) -> None:
        """Stamp `last_used_at = now` after a successful verification."""
        ...

    # -- mfa_challenges ----------------------------------------------------

    async def create_challenge(
        self,
        user_id: str,
        *,
        purpose: str,
        mfa_token_hash: str,
        expires_at: datetime,
    ) -> MfaChallengeRecord: ...

    async def find_open_challenge_by_token_hash(
        self, mfa_token_hash: str
    ) -> MfaChallengeRecord | None:
        """`satisfied_at IS NULL`, or `None` if no such open challenge
        exists (unknown token and an already-satisfied one are
        indistinguishable to the caller — ticket "expired-challenge")."""
        ...

    async def record_challenge_attempt(self, challenge_id: str) -> int:
        """Atomically increment `attempts` by 1 and return the new count
        (same atomicity rationale as `record_time_step`)."""
        ...

    async def satisfy_challenge(self, challenge_id: str, *, now: datetime) -> bool:
        """Conditional `UPDATE ... WHERE satisfied_at IS NULL`, stamping
        `satisfied_at = now`, returning whether *this call* won the race.
        PR #1618 review finding 2 (high): two concurrent requests racing
        the same open challenge (e.g. the same valid TOTP code replayed a
        few milliseconds apart, or a recovery-code request racing a TOTP
        request) must not both be able to mint a session from one
        challenge — the caller must treat `False` as `MfaChallengeInvalid`
        rather than as success."""
        ...

    # -- recovery_codes ------------------------------------------------------

    async def replace_recovery_codes(self, user_id: str, *, code_hashes: tuple[str, ...]) -> None:
        """Hard-delete every existing (used and unused) `recovery_codes` row
        for `user_id` and insert the new set (ticket "regenerates codes,
        hard-deleting unused ones")."""
        ...

    async def find_unused_recovery_code(self, user_id: str, *, code_hash: str) -> str | None:
        """Return the row id (as `str`) of the matching unused code, or
        `None`."""
        ...

    async def count_unused_recovery_codes(self, user_id: str) -> int: ...

    async def complete_recovery(
        self, user_id: str, *, challenge_id: str, code_id: str, now: datetime
    ) -> bool:
        """#2344, ONE transaction: mark the recovery code `code_id` of `user_id` used and
        satisfy its login challenge `challenge_id`, each only while unused and unsatisfied
        (conditional `UPDATE`s), then revoke (`revoked_at = now`) every unrevoked MFA method
        of `user_id`, which forces TOTP re-enrolment: `find_pending_method` never returns a
        revoked method. Returns whether this call won both; when it did not, it rolls back,
        so a lost race spends no code. PR #1618 review finding 2 (high): the conditions are
        what make one code, and one challenge, sign in at most once."""
        ...
