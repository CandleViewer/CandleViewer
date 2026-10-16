"""`SessionRepository` — the storage-facing seam `SessionService` depends on
(E09-S03), mirroring `UserRepository`'s own Protocol-not-SQL-driver pattern
(ADR-0003, `forbidden-storage-drivers-M18`).

The concrete `SqlAlchemyUserRepository`-sibling implementation lives in
`candleviewer.storage.repositories` and is out of this ticket's own file
list (composition-root wiring), but is structurally compatible with this
Protocol without either module importing the other's types.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from candleviewer.auth.models import SessionRecord

#: #2304: a row's step-up columns, `(step_up_elevations, step_up_failures, readonly_until)`.
StepUpState = tuple[dict[str, datetime], int, datetime | None]
#: A pure function from the step-up columns the row holds to the columns to store.
StepUpChange = Callable[[StepUpState], StepUpState]


class SessionRepository(Protocol):
    """Everything `SessionService` needs from the relational tier for
    `sessions`/`sessions_rotation` (`21-database-schema.md` §3.1.4)."""

    async def create_session(self, session: SessionRecord) -> SessionRecord | None:
        """Insert a new `sessions` row. Callers always pass a fully-formed
        `SessionRecord` (id/hash/timestamps already computed) — this method
        never generates an id or a token hash itself. #2911: inserts nothing and
        returns `None` when the user is `disabled` or gone (absent or soft-
        deleted), read under a lock on the user's row that a disable's own lock
        on it waits for (and vice versa), in the insert's transaction."""
        ...

    async def find_by_id(self, session_id: str) -> SessionRecord | None:
        """The row with its user's `users.status` (`user_status`, #2911). Always
        populated for a user that exists: `require_active` reads `None` as a
        gone user and revokes the session."""
        ...

    async def find_by_refresh_hash(self, refresh_token_hash: str) -> SessionRecord | None:
        """Look up the *live or revoked* row for a hash — reuse detection
        needs to find an already-`rotated` row, not just a live one. Carries
        `user_status` like `find_by_id`."""
        ...

    async def find_by_access_token_jti(self, access_token_jti: str) -> SessionRecord | None:
        """Look up by `sessions.access_token_jti` (the hashed opaque access
        handle, ADR-0020) — the per-request authentication path."""
        ...

    async def find_live_by_user(self, user_id: str) -> tuple[SessionRecord, ...]:
        """`WHERE user_id = :id AND revoked_at IS NULL` (`ix_sessions_user_
        live`) — SCR-112's session list and sign-out-everywhere both read
        this."""
        ...

    async def touch_last_seen(self, session_id: str, *, now: datetime) -> SessionRecord | None:
        """Stamp `last_seen_at = now` (idle-deadline reset on activity).
        Returns `None` if the session no longer exists or is already
        revoked (caller must not resurrect a dead session's idle clock)."""
        ...

    async def lift_idle_lock(self, session_id: str, *, now: datetime) -> SessionRecord | None:
        """The successful unlock of an idle-locked row (#2301, B16.7): in one
        write, stamp `last_seen_at = now` and clear `step_up_elevations` (grace
        windows, `once:` grants, `pending:` challenges), keeping
        `step_up_failures` and `readonly_until`. A one-factor unlock never
        inherits a two-factor elevation. Same `None` contract as
        `touch_last_seen`."""
        ...

    async def revoke(self, session_id: str, *, reason: str, now: datetime) -> SessionRecord | None:
        """Atomically set `revoked_at`/`revoked_reason` iff the row is not
        already revoked (idempotent — a session is never un-revoked, INV-
        B16-d). Returns the updated row, or `None` if it was already
        revoked or does not exist."""
        ...

    async def update_step_up_state(
        self, session_id: str, change: StepUpChange
    ) -> SessionRecord | None:
        """E09-S04: store `change(<the row's step-up columns>)` iff the row is not
        revoked. #2304: the read and the write are one transaction under the row
        lock, so a write never carries a stale read: a concurrent
        `consume_step_up_key` (or any other write of the row) lands wholly
        before the read or after the write, and a used one-shot grant is never
        written back. `change` is pure and never awaits. Returns the updated
        row, or `None` if revoked/absent (`change` is then not called)."""
        ...

    async def consume_step_up_key(
        self, session_id: str, *, key: str, now: datetime
    ) -> SessionRecord | None:
        """#2304: remove the one-shot grant `key` from `step_up_elevations` iff
        the row is live and still holds it unexpired at `now`, in one
        conditional statement: of two concurrent consumers exactly one gets
        the updated row, every other caller `None`."""
        ...

    async def revoke_all_for_user(
        self, user_id: str, *, reason: str, now: datetime, except_session_id: str | None = None
    ) -> tuple[SessionRecord, ...]:
        """Sign-out-everywhere (ticket: "revoking all sessions of the user
        including the current one" for `/auth/logout` with
        `all_sessions=true`; `except_session_id` lets `/auth/password`'s
        "revokes all *other* sessions on success" reuse this same method).
        Returns the sessions actually revoked (already-revoked rows are
        skipped, same idempotency as `revoke`)."""
        ...

    async def link_rotation(self, *, prev_session_id: str, next_session_id: str) -> None:
        """Insert one `sessions_rotation` row linking the rotated-out
        session to its replacement."""
        ...

    async def walk_rotation_family(self, session_id: str) -> tuple[str, ...]:
        """Every session id in *session_id*'s rotation family (both
        directions — ancestors via `prev_session_id` and descendants via
        `next_session_id`), used by refresh-reuse detection to revoke the
        entire family transitively (ticket "revokes the entire family
        transitively")."""
        ...
