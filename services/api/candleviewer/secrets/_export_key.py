"""Audit export signing key core (#889 S5; ADR-0039, ADR-0009 Amendment 8). Private to M2.

Pure functions, with no I/O and no store (S4 stores the row; S6 boots the key and mints the signer).
The Ed25519 seed is sealed under the row's DEK with an AAD that binds the environment, the key id
and the public key, as `cred_aad` binds an exchange key's fields. Every open builds that AAD from
the process environment, the KEK's, which the caller passes, and refuses a row that names another
(C-2.11). The KEK version is bound only in the DEK's own wrap under the KEK, under a label of its
own, `cv-export-dek-v1` (`LoadedKek.wrap_export_dek`), like `dek_aad`: a re-wrap moves only the DEK,
the sealed seed never changes once created, and S4's write-once trigger allows only the retire, Q3's
destroy and the re-wrap's DEK columns. The DEK is a 32-byte `bytearray` the caller zeroes; every
call here drops its own name for it, so no frame of a refusal holds it, as `broker._borrow` drops
its plaintext (C-12.6).

A seed is used or returned only once the public key derived from it equals the row's, compared in
constant time (decision 4). A signature covers only `cv.audit.export.v1:` and the hex of a 32-byte
digest; a digest refused before any key operation is a `TypeError` by design, as `check_message`'s
refusal is. A private key object lives inside one expression, and `private_bytes` is never called.
Each seed `bytearray` made here is zeroed. `check_key` and `sign_export`, and `_open_seed` behind
them (private: it alone returns a seed), fail as a typed `CredentialUnavailable` with nothing
chained and the frames below cleared (C-12.6): `credential_unavailable`, `export_key_mismatch` or
`signing_failed`. `seal_seed` re-raises a failure scrubbed; so does `generate`, which also refuses
a seal that does not open (`check_key`). SR-009 residual, as in `_envelope.py`: `new_seed`'s
`os.urandom` bytes, `env.seal`'s `bytes(plaintext)`, AES-GCM's decrypted output and
`from_private_bytes`'s seed are immutable copies that no zeroing reaches.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass, field

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from candleviewer.secrets import _envelope as env
from candleviewer.secrets.errors import CredentialUnavailable
from candleviewer.secrets.signing import scrub_frames

SEED_LEN = PUBLIC_KEY_LEN = DIGEST_LEN = 32
#: The signed bytes: this prefix, then the digest's lowercase hex (22 `AuditExportResult`).
MESSAGE_PREFIX = b"cv.audit.export.v1:"
KEY_ID_PREFIX = "cv-audit-export-v"


@dataclass(frozen=True, slots=True)
class SealedExportKey:
    """A key as its row holds it: all public but `sealed_seed`, sealed under the row's DEK. The
    row's `env_name` is checked against the process's at every open."""

    env_name: str
    key_id: str
    public_key: bytes
    sealed_seed: bytes = field(repr=False)


def new_seed() -> bytearray:
    """A fresh seed from the CSPRNG M2 draws its DEKs from (`os.urandom`)."""
    return bytearray(os.urandom(SEED_LEN))


def derive_public_key(seed: bytes | bytearray) -> bytes:
    """The raw 32-byte public key of a 32-byte seed. A caller clears a failure's frames."""
    if len(seed) != SEED_LEN:
        raise ValueError("export seed length")
    return Ed25519PrivateKey.from_private_bytes(bytes(seed)).public_key().public_bytes_raw()


def fingerprint(public_key: bytes) -> str:
    """The lowercase hex SHA-256 of exactly 32 raw public-key bytes."""
    if len(public_key) != PUBLIC_KEY_LEN:
        raise ValueError("export public key length")
    return hashlib.sha256(public_key).hexdigest()


def derive_key_id(version: int, public_key: bytes) -> str:
    """`cv-audit-export-v<N>:` and the first 16 hex of the public key's SHA-256."""
    if type(version) is not int or version < 1:
        raise ValueError("export key version must be a positive int")
    return f"{KEY_ID_PREFIX}{version}:{fingerprint(public_key)[:16]}"


def check_digest(digest: object) -> bytes:
    """A copy of exactly 32 bytes from a `bytes` or `bytearray`, which no later change to the
    caller's buffer reaches; `TypeError` for anything else, before any key operation."""
    if type(digest) is not bytes and type(digest) is not bytearray:
        raise TypeError("export digest: exactly 32 bytes")
    copy = bytes(digest)
    if len(copy) != DIGEST_LEN:
        raise TypeError("export digest: exactly 32 bytes")
    return copy


def export_message(digest: object) -> bytes:
    """The bytes a signature covers: `cv.audit.export.v1:` and the checked digest's hex."""
    return MESSAGE_PREFIX + check_digest(digest).hex().encode("ascii")


def seal_seed(dek: bytearray, seed: bytearray, *, env_name: str, version: int) -> SealedExportKey:
    """`seed` sealed under `dek`, a 32-byte `bytearray`, bound to the environment and the key id
    and public key it derives. A failure is re-raised with the frames below it cleared."""
    try:
        if type(dek) is not bytearray or len(dek) != env.KEY_LEN:
            raise ValueError("export DEK: a 32-byte bytearray")
        public_key = derive_public_key(seed)
        key_id = derive_key_id(version, public_key)
        sealed = env.seal(dek, seed, env.export_seed_aad(env_name, key_id, public_key))
    except BaseException as exc:
        scrub_frames(exc)  # the frames below hold the DEK and the seed
        del dek  # and this one did: the caller zeroes it
        raise
    return SealedExportKey(env_name, key_id, public_key, sealed)


def _open_seed(dek: bytearray, key: SealedExportKey, *, env_name: str) -> bytearray:
    """The seed of `key`, a `bytearray` the caller zeroes, once its public key is the row's
    (decision 4: at boot and before every signature). Private: it alone returns a seed. `env_name`
    is the process's. Otherwise the opened bytes are zeroed and refused: `credential_unavailable`
    (a DEK that is not a 32-byte `bytearray`, a row of another environment, or no open under this
    binding) or `export_key_mismatch`."""
    seed, code = bytearray(), "credential_unavailable"
    try:
        if type(dek) is not bytearray or len(dek) != env.KEY_LEN or key.env_name != env_name:
            raise ValueError("export DEK not a 32-byte bytearray, or a row of another environment")
        aad = env.export_seed_aad(env_name, key.key_id, key.public_key)
        seed = env.open_(dek, key.sealed_seed, aad)
        code = "export_key_mismatch"
        if hmac.compare_digest(derive_public_key(seed), key.public_key):
            return seed
    except BaseException as exc:
        scrub_frames(exc)  # the frames below hold the DEK and the seed
        if not isinstance(exc, Exception):
            env.zero(seed)
            raise
        code = "credential_unavailable"
    finally:
        del dek  # no frame of a refusal holds the DEK: the caller zeroes it
    env.zero(seed)
    raise CredentialUnavailable(code)  # after the handler: nothing chained


def check_key(dek: bytearray, key: SealedExportKey, *, env_name: str) -> None:
    """Prove `key` usable without holding its seed (S6's boot check, S7's `verified` mark): open
    it and check its public key as `_open_seed` does, then zero it. Refusals are `_open_seed`'s."""
    try:
        env.zero(_open_seed(dek, key, env_name=env_name))
    finally:
        del dek  # no frame of a refusal holds the DEK: the caller zeroes it


def generate(dek: bytearray, *, env_name: str, version: int) -> SealedExportKey:
    """A new key: a fresh seed sealed under `dek` by `seal_seed`, the seal proven to open to its key
    (`check_key`) before it is returned, as `_auth_keyring.wrap_verified` proves a wrap, and the
    seed zeroed."""
    seed = bytearray()
    try:
        seed = new_seed()
        key = seal_seed(dek, seed, env_name=env_name, version=version)
        check_key(dek, key, env_name=env_name)
    finally:
        env.zero(seed)
        del dek  # no frame of a refusal holds the DEK: the caller zeroes it
    return key


def sign_export(dek: bytearray, key: SealedExportKey, digest: object, *, env_name: str) -> bytes:
    """The 64-byte signature of `key` over `export_message(digest)`: the digest is checked first,
    then the seed opened (`_open_seed`), used once and zeroed. A refusal keeps its code, a failure
    is `signing_failed`; a cancellation is not the key's doing and propagates, scrubbed."""
    seed, code = bytearray(), "signing_failed"
    try:
        message = export_message(digest)  # refused here, before any key operation
        try:
            seed = _open_seed(dek, key, env_name=env_name)
            return Ed25519PrivateKey.from_private_bytes(bytes(seed)).sign(message)
        except BaseException as exc:
            scrub_frames(exc)  # the frames below hold the DEK and the seed
            if not isinstance(exc, Exception):
                raise
            if isinstance(exc, CredentialUnavailable):
                code = str(exc)
    finally:
        env.zero(seed)
        del dek  # no frame of a refusal holds the DEK: the caller zeroes it
    raise CredentialUnavailable(code)  # after the handler: nothing chained
