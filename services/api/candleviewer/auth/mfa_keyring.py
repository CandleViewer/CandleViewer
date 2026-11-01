"""`MfaKeyring`: the key custody MFA seals TOTP seeds and digests recovery codes through (#2152,
ADR-0009 Amendment 4).

`auth` (M18) imports neither `secrets` (M2, C-3.2) nor `admin`: the composition root injects an
implementation. Until #2152's switch-over that is an env-backed keyring that keeps today's
formats; then it is M2's `AuthKeyring`, adapted in `admin.wiring`, whose seals and digests bind
the user and whose keys never leave M2. Inputs and outputs are plain data (#2279).
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class MfaKeyring(Protocol):
    """Seals, seeds and digests, never a key. A refusal raises `MfaKeyringUnavailable` (the HTTP
    edge's `503 auth_unavailable`, never "no method", AC6) or `MfaSealInvalid` (a wrong code, AC9),
    with nothing chained."""

    async def available(self, *key_refs: str) -> bool:
        """Whether the keyring is open and holds the key of every `key_refs` (none: open at all).
        Metadata only: no seed is opened, so a 503 is decided before any seed is touched."""
        ...

    async def seal_totp_seed(self, seed: bytes | bytearray, user_id: UUID) -> tuple[bytes, str]:
        """`(secret_enc, secret_key_ref)` of a new seal of `seed` for `user_id`."""
        ...

    async def open_totp_seed(self, blob: bytes, key_ref: str, user_id: UUID) -> bytearray:
        """The seed sealed in `blob` under `key_ref` for `user_id`, as a `bytearray` the caller
        zeroes once it has verified the code."""
        ...

    async def recovery_code_digests(self, code: str, user_id: UUID) -> tuple[str, ...]:
        """Every candidate digest of `code` for `user_id`: a stored digest matching any of them is
        the code; a new code stores the first. `ValueError` for a code no contract body carries."""
        ...

