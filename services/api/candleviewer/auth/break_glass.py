"""Break-glass Owner MFA reset port (E09-S11 #2119 slice 3a, SR-023).

Reset only (decision O2): ONE transaction revokes every unrevoked MFA method of the
named Owner (pending ones too, so no earlier TOTP secret can be confirmed later)
and every live session (`revoked_reason='break_glass'`), and inserts a critical,
unresolved `system_events` row (`auth`/`break_glass_used`, O4). No login is minted
and nothing secret is returned. A supplied recovery code arrives only as its keyed
hash (SR-022) and is consumed in the same transaction; the rule that `live` needs
one (ADR-0009 Amendment 1) is the reset service of slice 3b. `auth` may not import
a storage driver (ADR-0003), so the transaction sits behind the
`BreakGlassResetStore` port (R4), implemented by
`storage/repositories/break_glass_sqlalchemy.py`.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol

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
