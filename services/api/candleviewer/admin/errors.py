"""Domain errors for the admin module (M21)."""

from __future__ import annotations

from typing import ClassVar


class AdminError(Exception):
    """Base exception for the M21 `admin` module."""


class UserLifecycleError(AdminError):
    """A user-lifecycle change refused with nothing changed (E42-T04, #965); `code` is the
    `x-error-codes` slug of `22-api-openapi.yaml` that the route answers with."""

    code: ClassVar[str]


class LifecycleForbiddenError(UserLifecycleError):  # 403: `forbidden_role` or `self_target`
    code = "forbidden"

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


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
