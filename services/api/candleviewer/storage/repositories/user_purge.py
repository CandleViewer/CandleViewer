"""Driver-free surface of the deferred PII purge (E42-T10 #2650, #965 O6).

`DELETE /users/{userId}?purge=true` disables the user (E42-T04) and then schedules the purge:
`users.purge_after` is set `policy.USERS_PURGE_AFTER_DAYS` out, `users.delete` written ahead. The
retention reaper (`storage/retention/users_purge_tasks.py`) anonymises each disabled user whose
`purge_after` has passed, one transaction per user with `users.anonymise` written ahead, and stamps
`users.anonymised_at`. A re-enable before then clears `purge_after` (R6). O6 fixes what changes:
the username becomes `surrogate(user_id)`, the email `anonymised_email(user_id)`, and
`display_name`, `last_login_ip` and every session's `ip`, `user_agent`, `device_label` and
`tailscale_node` become NULL. Audit rows are never touched (C-5.7, C-12.8): each keeps the name it
was written with, so the records this purge writes carry ids, status and times only.
`user_purge_sqlalchemy.py` implements the store.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Protocol

SURROGATE_PREFIX: Final = "deleted-user-"
#: The hash's fixed domain prefix (O6), so the digest names a CandleViewer user id and nothing else.
_SURROGATE_DOMAIN: Final = b"cv-user-surrogate:"
#: RFC 2606 reserves `.invalid`: the address can never be delivered to.
ANONYMISED_EMAIL_DOMAIN: Final = "deleted.invalid"


def surrogate(user_id: uuid.UUID) -> str:
    """O6: `deleted-user-` and the first 12 hex digits of SHA-256(`cv-user-surrogate:` + the id in
    its canonical text, lower-case 8-4-4-4-12, as Postgres prints a `uuid`). It depends on the id
    alone: the same on every run and host, it groups a user's history as the id already does, and
    no email, name or address goes into it, so none can be read back from it. 25 characters, within
    the username's 3 to 32."""
    digest = hashlib.sha256(_SURROGATE_DOMAIN + str(user_id).encode("ascii")).hexdigest()
    return f"{SURROGATE_PREFIX}{digest[:12]}"


def anonymised_email(user_id: uuid.UUID) -> str:
    """O6: `<surrogate>@deleted.invalid`, unique per user as the surrogate is."""
    return f"{surrogate(user_id)}@{ANONYMISED_EMAIL_DOMAIN}"


class PurgeAuditEmitter(Protocol):
    """`AuditWriter.emit` as the store calls it; injected by the composition root, since storage
    (M10) may not import audit (M19). `outcome` and `severity` are passed as the plain values of
    `AuditOutcome` and `Severity` (`StrEnum`s there)."""

    async def emit(self, action: str, **fields: Any) -> None: ...


class PurgeUserNotFoundError(Exception):
    """No such user, or a soft-deleted one (HTTP 404 `not_found`); nothing changed."""


class PurgeUserNotDisabledError(Exception):
    """The user is not `disabled`: a re-enable won the race with the schedule (HTTP 409
    `conflict`); nothing changed."""


class PurgeAuditUnavailableError(Exception):
    """The write-ahead record was refused or outlived its bound, so the change rolled back (HTTP
    503 `audit_unavailable`)."""


@dataclass(frozen=True, slots=True)
class PurgeSchedule:
    """The purge in force after `schedule`: `changed` is False when one was already scheduled (or
    has run), which keeps its first date and writes nothing."""

    user_id: uuid.UUID
    purge_after: datetime
    changed: bool
