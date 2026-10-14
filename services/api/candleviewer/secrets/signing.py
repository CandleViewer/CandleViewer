"""Exchange-neutral request signing for the exchange adapter (C-2.7, #2339).

The adapter owns its venue's canonical pre-sign format (C-2.2). It sends the message here as byte
segments and marks where the credential's key id (the API key its request header carries) belongs
with `KEY_ID_SLOT`. M2 splices the key id in and computes HMAC-SHA256 with the API secret, so the
secret is plaintext only inside `secrets/`. The caller gets the lowercase hex MAC and the key id
(as a `Secret`, for its request header), never the secret. The message is plain data, so an
out-of-process signer can serve the same call (#2279). It is bounded (size, parts, key-id slots),
so the capability is not a general-purpose HMAC oracle keyed by the secret.

A failed MAC does not carry plaintext out in a traceback either (C-12.6): it is raised as
`CredentialUnavailable("signing_failed")` with nothing chained, after the failed call's frames
are cleared, and no signing frame binds plaintext to a name.
"""

from __future__ import annotations

import enum
import hashlib
import hmac
import traceback
from dataclasses import dataclass, field
from typing import Final

from candleviewer.secrets.errors import CredentialUnavailable
from candleviewer.secrets.secret import Secret


class SigningSlot(enum.Enum):
    """Placeholders M2 fills in a signing message. Named after M2's own field (`key_id_enc`)."""

    KEY_ID = "key_id"


#: Where the credential's key id goes in a signing message.
KEY_ID_SLOT: Final = SigningSlot.KEY_ID

#: Bounds on a signing message, so the capability is no general-purpose HMAC oracle (#2350
#: review). The adapter's REST string-to-sign has four parts and one key-id slot; WS auth has none.
MAX_MESSAGE_BYTES: Final = 64 * 1024
MAX_MESSAGE_PARTS: Final = 16
MAX_KEY_ID_SLOTS: Final = 1

#: A message to sign: byte segments in wire order, with `KEY_ID_SLOT` wherever the key id goes.
SigningMessage = tuple[bytes | SigningSlot, ...]


@dataclass(frozen=True, slots=True)
class RequestSignature:
    """One signing result: the API key id for the request header and the lowercase hex MAC.

    It never carries the API secret. Neither value is rendered by `repr`."""

    api_key: Secret[str]
    signature: str = field(repr=False)


def check_message(message: object) -> SigningMessage:
    """Accept only a non-empty tuple of at most `MAX_MESSAGE_PARTS` parts, each `bytes` or
    `KEY_ID_SLOT`, with at most `MAX_KEY_ID_SLOTS` slot and `MAX_MESSAGE_BYTES` bytes in all.
    Callers run this before any borrow, so a refused message causes no decrypt and no audit."""
    if (
        type(message) is not tuple
        or not 0 < len(message) <= MAX_MESSAGE_PARTS
        or not all(type(part) is bytes or part is KEY_ID_SLOT for part in message)
        or sum(part is KEY_ID_SLOT for part in message) > MAX_KEY_ID_SLOTS
        or sum(len(part) for part in message if type(part) is bytes) > MAX_MESSAGE_BYTES
    ):
        raise TypeError(
            f"signing message must be a non-empty tuple of at most {MAX_MESSAGE_PARTS} bytes "
            f"parts and KEY_ID_SLOT markers: at most {MAX_KEY_ID_SLOTS} KEY_ID_SLOT and "
            f"{MAX_MESSAGE_BYTES} bytes"
        )
    return message


def message_sha256(message: SigningMessage) -> str:
    """Lowercase hex SHA-256 of `message` as the caller sent it, before the key id is spliced in,
    so the key id is never hashed. It ties a write-ahead audit record to its request (C-2.9).
    Each bytes part is framed as 0x00, its 8-byte big-endian length and the bytes; each
    `KEY_ID_SLOT` as 0x01. Different messages never share an encoding."""
    digest = hashlib.sha256()
    for part in message:
        if isinstance(part, bytes):
            digest.update(b"\x00" + len(part).to_bytes(8, "big") + part)
        else:
            digest.update(b"\x01")
    return digest.hexdigest()


def scrub_frames(exc: BaseException) -> None:
    """Drop the locals of every finished frame in the tracebacks of `exc` and of the exceptions
    chained to it, so a kept or locals-rendering traceback cannot show the key material those
    frames held. Executing frames are skipped (`traceback.clear_frames`), so a frame that
    catches a signing failure must not bind plaintext to a name."""
    seen: set[int] = set()
    todo = [exc]
    while todo:
        e = todo.pop()
        if id(e) not in seen:
            seen.add(id(e))
            traceback.clear_frames(e.__traceback__)
            todo += [c for c in (e.__cause__, e.__context__) if c is not None]


def _spliced(key_id: Secret[str], message: SigningMessage) -> bytes:
    return b"".join(p if isinstance(p, bytes) else key_id.reveal().encode() for p in message)


def mac_hex(key_id: Secret[str], secret: Secret[str], message: SigningMessage) -> str:
    """HMAC-SHA256 over `message` with the key id at each `KEY_ID_SLOT`; lowercase hex.

    Takes the `Secret` wrappers, so this frame holds no plaintext. On failure the stdlib frames
    (they hold the secret and the spliced key id) are cleared and `signing_failed` is raised after
    the handler, so nothing is chained to it. A `BaseException` that is not an `Exception`
    (`KeyboardInterrupt`, `CancelledError`) is not the MAC's doing: it propagates, scrubbed."""
    try:
        # A keyed request MAC (the venue's mandated signature), not password storage hashing.
        return hmac.new(
            secret.reveal().encode(), _spliced(key_id, message), hashlib.sha256
        ).hexdigest()
    except BaseException as exc:
        scrub_frames(exc)
        if not isinstance(exc, Exception):
            raise
    raise CredentialUnavailable("signing_failed")
