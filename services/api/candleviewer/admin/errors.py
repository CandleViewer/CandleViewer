"""Domain errors for the admin module (M21)."""

from __future__ import annotations

from typing import ClassVar, Literal

#: Why the break-glass CLI cannot use its host journal (E09-S11 #2119): the anchored directory
#: or the journal is unusable, or the run lock is held (cv-api, or another break-glass run).
JournalRefusal = Literal["host_fs_unavailable", "api_running"]
#: `rewrapKek`'s error codes (`22-api-openapi.yaml`, #2266): its audited refusals, then its 503s.
KekRefusal = Literal["kek_unavailable", "kek_rotation_not_staged", "kek_rotation_in_progress"]
KekRewrapCode = KekRefusal | Literal["audit_unavailable", "store_unavailable"]
#: A view-as start that could not write its records (#3085 S13a): nothing started.
ViewAsStartCode = Literal["audit_unavailable", "store_unavailable"]


class AdminError(Exception):
    """Base exception for the M21 `admin` module."""


class BreakGlassUnavailable(AdminError):
    """The break-glass journal port could not open the host journal under the run lock
    (E09-S11 #2119, SR-023). `reason` names no path and no secret; the flow refuses with it."""

    def __init__(self, reason: JournalRefusal) -> None:
        super().__init__(f"break-glass journal unavailable: {reason}")
        self.reason: JournalRefusal = reason


class UserLifecycleError(AdminError):
    """A user-lifecycle change refused with nothing changed (E42-T04, #965); `code` is the
    `x-error-codes` slug of `22-api-openapi.yaml` that the route answers with."""

    code: ClassVar[str]


class LifecycleForbiddenError(UserLifecycleError):  # 403: `forbidden_role` or `self_target`
    code = "forbidden"

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class LifecycleActorRevokedError(LifecycleForbiddenError):
    """#2593: refused at the effect, the actor no longer being an active owner when the change's
    own transaction read it. Its reason is the guard's own (`forbidden_role`), so the answer is
    the 403 a fresh request gets at entry; the route of a PATCH answers its own entry refusal."""

    def __init__(self) -> None:
        super().__init__("forbidden_role")


class UserNotFoundError(UserLifecycleError):
    code = "not_found"


class LastOwnerError(UserLifecycleError):  # 409: the last active owner (SR-055, AC6)
    code = "conflict"


class PositionsUnknownError(UserLifecycleError):  # 409: an unacknowledged unknown count (AC7)
    code = "positions_unknown"

    def __init__(self, source: str) -> None:
        super().__init__(source)
        self.source = source  # the position provider's, e.g. `not_deployed`


class LifecycleAuditUnavailableError(UserLifecycleError):  # 503: nothing changed (AC8)
    code = "audit_unavailable"


class UserVersionConflictError(UserLifecycleError):  # 412: a stale `If-Match` (E42-T09, #2649)
    """A `PATCH /users/{userId}` to `disabled` whose `If-Match` no longer names the user read
    under the disable's lock: the transaction rolled back before any write."""

    code = "version_conflict"


class OpsNotWired(AdminError):
    """The ops read model has no provider yet (E42-T05): 501 `not_implemented`, nothing read."""


class OpsUnavailable(AdminError):
    """The ops source failed, timed out or has nothing yet (E42-T05): 503, retryable. The
    message is a fixed literal, never an exception's text."""


class InvalidCursor(AdminError):
    """A pagination cursor that is malformed, expired or issued for another listing (400)."""


class IncidentNotFound(AdminError):
    """No incident has the id to acknowledge (E42-T05): 404 `not_found`, nothing changed."""


class IncidentResolved(AdminError):
    """A `resolved` incident has nothing to acknowledge (E42-T05): 409 `conflict`, no change."""


class OpsAuditUnavailable(AdminError):
    """The write-ahead audit record could not be written (E42-T05, C-2.9): 503
    `audit_unavailable`, nothing changed. Fixed message, never the cause."""


class KekRewrapError(AdminError):
    """`AdminService.rewrap_kek` ended without a run's counts (#2266): `code` is the `rewrapKek`
    error code. A refusal (403 `kek_unavailable`, 409 `kek_rotation_not_staged` and
    `kek_rotation_in_progress`) was audited and latched or moved nothing. A 503
    (`audit_unavailable`, `store_unavailable`) after the latch keeps it and the rows moved;
    calling again resumes."""

    def __init__(self, code: KekRewrapCode) -> None:
        super().__init__(code)
        self.code: KekRewrapCode = code


class ViewAsStartUnavailable(AdminError):
    """A view-as start whose records could not be written: nothing started (22 `startViewAs`),
    answered 503 with `code`, `audit_unavailable` or `store_unavailable`."""

    def __init__(self, code: ViewAsStartCode) -> None:
        super().__init__(code)
        self.code: ViewAsStartCode = code


class SigningKeyRotationError(AdminError):
    """`AdminService.rotate_audit_signing_key` answered no rotation (#889 S7): `code` is the
    `rotateAuditSigningKey` code (an idempotency answer, a refusal or a `503`) and `retry_after_s`
    the `429`'s wait. A refusal rotated nothing, M2 auditing all but the `429`; a `503` may be sent
    again with the same key, which finds the rotation if it committed."""

    def __init__(self, code: str, retry_after_s: int | None = None) -> None:
        super().__init__(code)
        self.code, self.retry_after_s = code, retry_after_s
