"""Domain errors for the secrets module (M2).

Messages carry reason codes and ids only, never key material (C-12.6).
"""

from __future__ import annotations

from typing import Literal

#: `rewrapKek` error codes a KEK re-wrap answers with besides `KekUnavailable` (#2266).
RotationCode = Literal[
    "kek_rotation_not_staged", "kek_rotation_in_progress", "audit_unavailable", "store_unavailable"
]


class SecretsError(Exception):
    """Base exception for the M2 `secrets` module."""


class KekRotationError(SecretsError):
    """A KEK re-wrap (`rewrap_deks`) refused or stopped (#2266): `code` is its `rewrapKek` error
    code. A refusal (`kek_rotation_not_staged`, `kek_rotation_in_progress`) is audited first and
    latches or moves nothing. A record that cannot be written, a refusal's included, is
    `audit_unavailable`, a store failure `store_unavailable`; a run stopped after its latch keeps
    the latch and the rows it moved."""

    def __init__(self, code: RotationCode) -> None:
        super().__init__(code)
        self.code: RotationCode = code


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


class AuthKeyringUnavailable(SecretsError):
    """MFA fails closed (`503 auth_unavailable`, ADR-0009 Amendment 4). `reason` is one of
    `auth_keyring_missing`, `auth_keyring_mismatch`, `auth_keyring_stranded`, `auth_keyring_closed`
    and `auth_key_not_held` (a seal under a key not held here, never "no method")."""

    code = "auth_keyring_unavailable"

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AuthKeyEnvForbidden(SecretsError):
    """An old env auth key setting in `live` (D3: import on `demo` and `testnet` only): fatal."""

    code = "auth_key_env_forbidden"


class AuthSealInvalid(SecretsError):
    """A seal under a held key failed authentication (moved or tampered): a wrong code (AC9)."""

    code = "auth_seal_invalid"
