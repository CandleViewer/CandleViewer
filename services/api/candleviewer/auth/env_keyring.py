"""`EnvMfaKeyring`: the env-backed `MfaKeyring` that keeps today's formats (#2152 S5a, BQ-16).

Behaviour unchanged: the TOTP seed is sealed with AES-256-GCM and no AAD under the key from
`CV_AUTH_TOTP_KEY_HEX` (`TotpEncryptor`, `secret_key_ref = 'local-dev-v1'`), and a recovery code's
digest is the HMAC-SHA256 of the normalised code under `CV_AUTH_RECOVERY_HMAC_KEY_HEX`
(`hash_recovery_code`), with no user bound. As before, a seal opens whatever its `secret_key_ref`
says and one that does not open raises the cipher's own error, and outside live a process without
the keys holds process-local ones (`process_local`). #2152's switch-over replaces it with M2's
`AuthKeyring` and deletes it; until then `auth` reaches its keys only through `MfaKeyring`.
"""

from __future__ import annotations

import os
from typing import NoReturn
from uuid import UUID

from candleviewer.auth.envelope import LOCAL_KEY_REF, TotpEncryptor
from candleviewer.auth.recovery_codes import hash_recovery_code


class EnvMfaKeyring:
    """Today's TOTP sealing and recovery-code keys, as `MfaKeyring` (#2152 S5a). Renders masked
    and cannot be pickled; never logs or returns a key."""

    def __init__(self, totp_key: bytes, recovery_key: bytes) -> None:
        self._encryptor = TotpEncryptor(totp_key, key_ref=LOCAL_KEY_REF)
        self._recovery_key = recovery_key

    @classmethod
    def process_local(cls) -> EnvMfaKeyring:
        """Two random keys held by this process alone: seeds and codes made under them die with
        it, so `AuthService` refuses this in live (PR #1618 review finding 3)."""
        return cls(os.urandom(32), os.urandom(32))

    async def available(self, *key_refs: str) -> bool:
        return all(ref == LOCAL_KEY_REF for ref in key_refs)

    async def seal_totp_seed(self, seed: bytes | bytearray, user_id: UUID) -> tuple[bytes, str]:
        return self._encryptor.encrypt(bytes(seed)), self._encryptor.key_ref

    async def open_totp_seed(self, blob: bytes, key_ref: str, user_id: UUID) -> bytearray:
        return bytearray(self._encryptor.decrypt(blob))

    async def recovery_code_digests(self, code: str, user_id: UUID) -> tuple[str, ...]:
        return (hash_recovery_code(code, key=self._recovery_key),)

    def __repr__(self) -> str:
        return "EnvMfaKeyring(***)"

    __str__ = __repr__

    def __reduce_ex__(self, protocol: object) -> NoReturn:
        raise TypeError("EnvMfaKeyring cannot be pickled")
