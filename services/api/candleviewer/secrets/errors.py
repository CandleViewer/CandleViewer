"""Domain errors for the secrets module (M2).

Messages carry reason codes and ids only, never key material (C-12.6).
"""

from __future__ import annotations


class SecretsError(Exception):
    """Base exception for the M2 `secrets` module."""


class KekSourceNotPermitted(SecretsError):
    """`CV_KEK_SOURCE=file` with `CV_ENV=live`: fatal at start-up (e27-kek.md §4)."""

    code = "kek_source_not_permitted"


class KekLoadError(SecretsError):
    """The KEK could not be loaded/verified; `reason` is one of the §6 reason tokens."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class KekUnavailable(SecretsError):
    """An operation needs the KEK but the module is degraded (fail closed)."""

    code = "kek_unavailable"


class CredentialUnavailable(SecretsError):
    """A borrow/destroy failed: unknown/revoked key, GCM authentication failure or timeout."""

    code = "credential_unavailable"


class WithdrawPermissionRejected(SecretsError):
    """The key reports any withdraw permission (C-2.8)."""

    code = "key_withdraw_permission"


class SnapshotInvalid(WithdrawPermissionRejected):
    """The permission snapshot is malformed or not JSON (callers pass `model_dump(mode="json")`).
    Still refuses the key (fail closed), but with its own code so operators see the cause."""

    code = "snapshot_invalid"
