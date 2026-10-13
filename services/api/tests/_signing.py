"""Test double for the M2 signing capability the exchange adapter holds (#2339, C-2.7).

The adapter never sees an API secret, so this double has none either. It splices the key id into
the message exactly where `API_KEY_ID` marks it, records the call, and returns a deterministic
stand-in signature (64 hex chars, not a MAC). The real HMAC-SHA256 is tested against M2 with fixed
vectors in `tests/unit/credentials_m2/test_signing.py` and end to end in the signer's own tests.
"""

from __future__ import annotations

import zlib
from collections.abc import Sequence
from uuid import UUID

from candleviewer.secrets import API_KEY_ID, CredentialBorrower, RequestSignature, Secret

#: The `api_keys.id` every double signs for.
CREDENTIAL_ID = UUID("00000000-0000-4000-8000-0000000000c1")

#: One recorded call: (credential id, assembled message bytes, purpose).
Call = tuple[UUID, bytes, str]


def assemble(key_id: str, message: Sequence[object]) -> bytes:
    """The message M2 would MAC: byte segments in order, the key id at each `API_KEY_ID`."""
    out = b""
    for part in message:
        if part is API_KEY_ID:
            out += key_id.encode()
        elif isinstance(part, bytes):
            out += part
        else:
            raise TypeError("message parts are bytes or API_KEY_ID")
    return out


def stand_in_signature(data: bytes) -> str:
    """Deterministic per message; only the shape (64 lowercase hex chars) mimics a real MAC."""
    return f"{zlib.crc32(data):08x}" * 8


def fake_capability(
    key_id: str = "test-key", calls: list[Call] | None = None
) -> CredentialBorrower:
    """A `CredentialBorrower` whose closure is this double instead of the M2 broker."""

    async def sign(
        credential_id: UUID, message: Sequence[object], purpose: str
    ) -> RequestSignature:
        data = assemble(key_id, message)
        if calls is not None:
            calls.append((credential_id, data, purpose))
        return RequestSignature(Secret(key_id), stand_in_signature(data))

    return CredentialBorrower(sign)
