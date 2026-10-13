"""Exchange-neutral request signing for the exchange adapter (C-2.7, #2339).

The adapter owns its venue's canonical pre-sign format (C-2.2). It sends the message here as byte
segments and marks where the credential's API key id belongs with `API_KEY_ID`. M2 splices the key
id in and computes HMAC-SHA256 with the API secret, so the secret is plaintext only inside
`secrets/`. The caller gets the lowercase hex MAC and the key id (as a `Secret`, for its request
header), never the secret. The message is plain data, so an out-of-process signer can serve the
same call (#2279).
"""

from __future__ import annotations

import enum
import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Final

from candleviewer.secrets.secret import Secret


class SigningSlot(enum.Enum):
    """Placeholders M2 fills in a signing message."""

    API_KEY_ID = "api_key_id"


#: Where the credential's API key id goes in a signing message.
API_KEY_ID: Final = SigningSlot.API_KEY_ID

#: A message to sign: byte segments in wire order, with `API_KEY_ID` wherever the key id goes.
SigningMessage = tuple[bytes | SigningSlot, ...]


@dataclass(frozen=True, slots=True)
class RequestSignature:
    """One signing result: the API key id for the request header and the lowercase hex MAC.

    It never carries the API secret. Neither value is rendered by `repr`."""

    api_key: Secret[str]
    signature: str = field(repr=False)


def check_message(message: object) -> SigningMessage:
    """Accept only a non-empty tuple of `bytes` segments and `API_KEY_ID` markers. Callers run
    this before any borrow, so a malformed message is refused without a decrypt or audit."""
    if (
        type(message) is not tuple
        or not message
        or not all(type(part) is bytes or part is API_KEY_ID for part in message)
    ):
        raise TypeError("signing message must be a non-empty tuple of bytes and API_KEY_ID")
    return message


def mac_hex(key_id: str, secret: str, message: SigningMessage) -> str:
    """HMAC-SHA256 over `message` with `key_id` at each `API_KEY_ID`; lowercase hex."""
    key_bytes = key_id.encode()
    data = b"".join(part if isinstance(part, bytes) else key_bytes for part in message)
    # A keyed request MAC (the venue's mandated signature), not password storage hashing.
    return hmac.new(secret.encode(), data, hashlib.sha256).hexdigest()
