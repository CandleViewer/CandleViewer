"""Break-glass Owner MFA reset port and service (E09-S11 #2119 slice 3, SR-023).

The offline CLI (slice 4) calls `reset()` after its host, KEK and run-lock checks.
Reset only (decision O2): ONE transaction revokes every unrevoked MFA method of the
named Owner (pending ones too, so no earlier TOTP secret can be confirmed later)
and every live session (`revoked_reason='break_glass'`), and inserts a critical,
unresolved `system_events` row (`auth`/`break_glass_used`, O4). No login is minted
and nothing secret is returned. Ratified rule (ADR-0009 Amendment 1; O3 is with the
owner): in `live` one unused recovery code of that Owner is checked offline against
its keyed hash (SR-022) and consumed in the same transaction. `--live` and the typed
phrase are CLI input (slice 4). `auth` may not import a storage driver (ADR-0003),
so the transaction sits behind the `BreakGlassResetStore` port (R4), implemented by
`storage/repositories/break_glass_sqlalchemy.py`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from candleviewer.auth.errors import BreakGlassRefused
from candleviewer.auth.recovery_codes import hash_recovery_code

#: `sessions.revoked_reason` of every session the reset revokes (decision R3).
BREAK_GLASS_REVOKED_REASON = "break_glass"
#: `system_events.kind` (component `auth`) of the row the reset writes (O4).
BREAK_GLASS_EVENT_KIND = "break_glass_used"


class BreakGlassRefusal(StrEnum):
    NOT_OWNER = "not_owner"  # unknown, deleted, not active, or no unexpired owner role
    RECOVERY_CODE_REQUIRED = "recovery_code_required"  # live without a code
    RECOVERY_CODE_INVALID = "recovery_code_invalid"  # not an unused code of this Owner


class BreakGlassResetStore(Protocol):
    async def reset_owner_mfa(
        self,
        target_user_id: str,
        *,
        now: datetime,
        recovery_code_hash: str | None,
        correlation_id: str,
    ) -> tuple[int, int, int] | str:
        """One transaction. Returns (methods revoked, sessions revoked, event id)
        after commit, or a `BreakGlassRefusal` value after rolling back: the target
        must be an active, undeleted user with an unexpired `owner` role, and a
        given `recovery_code_hash` must match an unused code of that user."""
        ...


@dataclass(frozen=True, slots=True)
class BreakGlassResetResult:
    """Counts only: no secret, code or token field."""

    target_user_id: uuid.UUID
    methods_revoked: int
    sessions_revoked: int
    recovery_code_consumed: bool
    system_event_id: int


class BreakGlassResetService:
    """`recovery_code_key` is the server-side `recovery_code_hmac_key` (SR-022)."""

    def __init__(
        self,
        store: BreakGlassResetStore,
        *,
        recovery_code_key: bytes,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._key = recovery_code_key
        self._clock = clock or (lambda: datetime.now(UTC))

    async def reset(
        self,
        target_user_id: uuid.UUID,
        *,
        live: bool,
        recovery_code: str | None,
        correlation_id: uuid.UUID,
    ) -> BreakGlassResetResult:
        """Raises `BreakGlassRefused` with zero rows changed. A supplied code is
        verified and consumed in every environment; `live` requires one."""
        if live and recovery_code is None:
            raise BreakGlassRefused(BreakGlassRefusal.RECOVERY_CODE_REQUIRED)
        code_hash = (
            None if recovery_code is None else hash_recovery_code(recovery_code, key=self._key)
        )
        outcome = await self._store.reset_owner_mfa(
            str(target_user_id),
            now=self._clock(),
            recovery_code_hash=code_hash,
            correlation_id=str(correlation_id),
        )
        if isinstance(outcome, str):
            raise BreakGlassRefused(BreakGlassRefusal(outcome))
        methods, sessions, event_id = outcome
        return BreakGlassResetResult(
            target_user_id, methods, sessions, code_hash is not None, event_id
        )
