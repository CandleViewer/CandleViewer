"""`MfaKeyring`: the key custody MFA seals TOTP seeds and digests recovery codes through (#2152,
ADR-0009 Amendment 4).

`auth` (M18) imports neither `secrets` (M2, C-3.2) nor `admin`: the composition root injects
M2's `AuthKeyring`, adapted in `admin.wiring`, whose seals and digests bind the user and whose
keys never leave M2. Inputs and outputs are plain data (#2279).
"""

from __future__ import annotations

from typing import Final, Protocol
from uuid import UUID

from candleviewer.auth.errors import MfaKeyringUnavailable

#: The bounded reasons `require_available` gives `MfaKeyringUnavailable` (the audit record's,
#: never the answer's, 22 `AuthUnavailable`): no keyring can serve at all (the KEK or the
#: environment's keyring; `secrets` health names the cause), or one of the user's methods is
#: sealed under a key this process does not hold.
KEYRING_UNAVAILABLE: Final = "auth_keyring_unavailable"
KEY_NOT_HELD: Final = "auth_key_not_held"


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


def zero_seeds(seeds: list[bytearray]) -> None:
    """Wipe every opened seed in place once its code is checked: a seed is plaintext only inside
    the MFA verifier, for the check (ruling D7, schema Sec.12; #2152 BQ-6)."""
    for seed in seeds:
        seed[:] = bytes(len(seed))


async def require_available(
    keyring: MfaKeyring | None, *key_refs: str, user_id: UUID | None = None
) -> None:
    """`MfaKeyringUnavailable` (naming `user_id`) unless `keyring` is open and holds the key of
    every `key_refs` (#2152, 22 `AuthUnavailable`, BQ-13): metadata only, so an operation decides
    its `503` before any seed is generated, opened or sealed and before any code is examined. One
    method this process cannot open is enough, and it never counts as "no method" (AC6)."""
    if keyring is not None and await keyring.available(*key_refs):
        return
    whole = keyring is None or not key_refs or not await keyring.available()
    reason = KEYRING_UNAVAILABLE if whole else KEY_NOT_HELD
    raise MfaKeyringUnavailable(reason, user_id=user_id)
