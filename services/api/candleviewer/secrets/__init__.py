"""secrets module (M2): KEK custody, envelope encryption, request signing.

Importable only by M4 (the exchange adapter) and M21 (`admin`, metadata only) — C-3.2.
Plaintext keys and unwrapped DEKs never leave this package (C-2.7, #2339). M4 holds one
caller-bound signing capability (`CredentialBorrower`, minted once by `admin.wiring` via
`mint_borrower`): it sends a message with `KEY_ID_SLOT` where the key id goes and gets back a
`RequestSignature` (hex MAC + key id), never the secret. `admin` alone may call the offline
break-glass proof `prove_kek_possession` (#2119): metadata only, it never enrols a KEK. `_kek`,
`_envelope`, `_auth_keyring`, `_export_key`, `_export_custody`, `_source`, `_metrics` and `broker`
are internal.
Key import holds `CandidateKeys` (minted by `admin.wiring` too): M2 verifies a pasted pair through
its `CandidateSigner`, a `SigningCapability`, and stores it only after the check passes (#836).
`admin.wiring` also mints the audit export's `ExportSigner` and `SigningKeys` and adapts them to
`audit`'s ports (#889, ADR-0039 decision 3): a signature and public key material, never a seed.
It mints `SigningKeyRotator` for `admin` too (#889 S7): the signing key's rotation, which answers
with public key material, or `ExportKeyRotationError`; and `RotationRunning` for the export route
(#889 S10): whether a rotation runs, a bool; and `LoopSigning`, the order lane's (#913 L3b), over
a store M2 builds with the root's `LoopStoreFactory` (#913 L1d). `KeyDestroyer` (#898), minted
there for the account delete and the key revoke, destroys one stored key of one account.
`AuthKeyring` (#2152 S4), minted there too by `mint_auth_keyring` and adapted to `auth`'s
`MfaKeyring`, gives MFA the environment's auth keyring as seals, seeds and digests, never a key;
`AuthKeyringUnavailable` and `AuthSealInvalid` are its refusals. `_auth_custody` is internal.
"""

from __future__ import annotations

from candleviewer.secrets.broker import Purpose
from candleviewer.secrets.candidate import CandidateKeys, CandidateSigner
from candleviewer.secrets.errors import (
    AuthKeyringUnavailable,
    AuthSealInvalid,
    CredentialUnavailable,
    ExportKeyRotationError,
    KekRotationError,
    KekSourceNotPermitted,
    KekUnavailable,
    SecretsError,
    WithdrawPermissionRejected,
)
from candleviewer.secrets.export_rotator import RotationRunning, SigningKeyRotator
from candleviewer.secrets.export_signer import ExportSigner, SigningKeys
from candleviewer.secrets.metrics import export_secrets_metrics
from candleviewer.secrets.models import KekCheckResult, RewrapReport, StoredCredential
from candleviewer.secrets.secret import Secret
from candleviewer.secrets.service import (
    AuthKeyring,
    CredentialBorrower,
    KeyDestroyer,
    LoopSigning,
    LoopStoreFactory,
    SecretsLifecycle,
    SecretsLifecycleFacade,
    SecretsMetadata,
    SecretsMetadataFacade,
    SecretsService,
    SigningCapability,
    mint_auth_keyring,
    mint_borrower,
    mint_candidate_keys,
    mint_export_signer,
    mint_key_destroyer,
    mint_loop_signing,
    mint_rotation_running,
    mint_signing_key_rotator,
    mint_signing_keys,
    prove_kek_possession,
)
from candleviewer.secrets.signing import KEY_ID_SLOT, RequestSignature
from candleviewer.secrets.store import (
    AuditSink,
    AuthKeyStore,
    CredentialStore,
    ExportKeyStore,
    KcvStore,
)

__all__ = [
    "KEY_ID_SLOT",
    "AuditSink",
    "AuthKeyStore",
    "AuthKeyring",
    "AuthKeyringUnavailable",
    "AuthSealInvalid",
    "CandidateKeys",
    "CandidateSigner",
    "CredentialBorrower",
    "CredentialStore",
    "CredentialUnavailable",
    "ExportKeyRotationError",
    "ExportKeyStore",
    "ExportSigner",
    "KcvStore",
    "KekCheckResult",
    "KekRotationError",
    "KekSourceNotPermitted",
    "KekUnavailable",
    "KeyDestroyer",
    "LoopSigning",
    "LoopStoreFactory",
    "Purpose",
    "RequestSignature",
    "RewrapReport",
    "RotationRunning",
    "Secret",
    "SecretsError",
    "SecretsLifecycle",
    "SecretsLifecycleFacade",
    "SecretsMetadata",
    "SecretsMetadataFacade",
    "SecretsService",
    "SigningCapability",
    "SigningKeyRotator",
    "SigningKeys",
    "StoredCredential",
    "WithdrawPermissionRejected",
    "export_secrets_metrics",
    "mint_auth_keyring",
    "mint_borrower",
    "mint_candidate_keys",
    "mint_export_signer",
    "mint_key_destroyer",
    "mint_loop_signing",
    "mint_rotation_running",
    "mint_signing_key_rotator",
    "mint_signing_keys",
    "prove_kek_possession",
]
