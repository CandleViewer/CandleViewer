"""secrets module (M2): KEK custody, envelope encryption, request signing.

Importable only by M4 (the exchange adapter) and M21 (`admin`, metadata only) — C-3.2.
Plaintext keys and unwrapped DEKs never leave this package (C-2.7, #2339). M4 holds one
caller-bound signing capability (`CredentialBorrower`, minted once by `admin.wiring` via
`mint_borrower`): it sends a message with `KEY_ID_SLOT` where the key id goes and gets back a
`RequestSignature` (hex MAC + key id), never the secret. `admin` alone may call the offline
break-glass proof `prove_kek_possession` (#2119): metadata only, it never enrols a KEK. `_kek`,
`_envelope`, `_auth_keyring`, `_source`, `_metrics` and `broker` are internal.
"""

from __future__ import annotations

from candleviewer.secrets.broker import Purpose
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
    SigningCapability,
    mint_borrower,
    prove_kek_possession,
)
from candleviewer.secrets.signing import KEY_ID_SLOT, RequestSignature
from candleviewer.secrets.store import AuditSink, CredentialStore, KcvStore

__all__ = [
    "KEY_ID_SLOT",
    "AuditSink",
    "CredentialBorrower",
    "CredentialStore",
    "CredentialUnavailable",
    "KcvStore",
    "KekCheckResult",
    "KekSourceNotPermitted",
    "KekUnavailable",
    "Purpose",
    "RequestSignature",
    "RewrapReport",
    "Secret",
    "SecretsError",
    "SecretsLifecycle",
    "SecretsLifecycleFacade",
    "SecretsMetadata",
    "SecretsMetadataFacade",
    "SecretsService",
    "SigningCapability",
    "StoredCredential",
    "WithdrawPermissionRejected",
    "export_secrets_metrics",
    "mint_borrower",
    "prove_kek_possession",
]
