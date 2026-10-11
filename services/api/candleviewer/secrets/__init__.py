"""secrets module (M2): KEK custody, envelope encryption, scoped credential borrow.

Importable only by M4 (`exchange.base`) and M21 (`admin`, metadata only) — C-3.2.
Plaintext keys and unwrapped DEKs never leave this package except inside the
`with_credentials` callback; `_kek` / `_envelope` are private.
"""

from __future__ import annotations

from candleviewer.secrets.errors import (
    CredentialUnavailable,
    KekSourceNotPermitted,
    KekUnavailable,
    SecretsError,
    WithdrawPermissionRejected,
)
from candleviewer.secrets.models import KekCheckResult, RewrapReport, StoredCredential
from candleviewer.secrets.secret import Secret
from candleviewer.secrets.service import SecretsService

__all__ = [
    "CredentialUnavailable",
    "KekCheckResult",
    "KekSourceNotPermitted",
    "KekUnavailable",
    "RewrapReport",
    "Secret",
    "SecretsError",
    "SecretsService",
    "StoredCredential",
    "WithdrawPermissionRejected",
]
