"""secrets module (M2): KEK custody, envelope encryption, scoped credential borrow.

Importable only by M4 (the exchange adapter) and M21 (`admin`, metadata only) — C-3.2.
Plaintext keys and unwrapped DEKs never leave this package except inside a caller-bound
borrow callback (`CredentialBorrower`, minted once by `admin.wiring` via `mint_borrower`);
`_kek`, `_envelope`, `_source`, `_metrics` and `broker` are internal.
"""

from __future__ import annotations

from candleviewer.secrets.errors import (
    CredentialUnavailable,
    KekSourceNotPermitted,
    KekUnavailable,
    SecretsError,
    WithdrawPermissionRejected,
)
from candleviewer.secrets.metrics import export_secrets_metrics
from candleviewer.secrets.models import KekCheckResult, RewrapReport, StoredCredential
from candleviewer.secrets.secret import Secret
from candleviewer.secrets.service import (
    CredentialBorrower,
    SecretsLifecycle,
    SecretsLifecycleFacade,
    SecretsMetadata,
    SecretsMetadataFacade,
    SecretsService,
    mint_borrower,
)
from candleviewer.secrets.store import AuditSink, CredentialStore, KcvStore

__all__ = [
    "AuditSink",
    "CredentialBorrower",
    "CredentialStore",
    "CredentialUnavailable",
    "KcvStore",
    "KekCheckResult",
    "KekSourceNotPermitted",
    "KekUnavailable",
    "RewrapReport",
    "Secret",
    "SecretsError",
    "SecretsLifecycle",
    "SecretsLifecycleFacade",
    "SecretsMetadata",
    "SecretsMetadataFacade",
    "SecretsService",
    "StoredCredential",
    "WithdrawPermissionRejected",
    "export_secrets_metrics",
    "mint_borrower",
]
