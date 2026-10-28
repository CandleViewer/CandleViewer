"""The trade-group lists' opaque keyset cursor (E28-T05 #909; S2f reuses it): the route's position
as bytes, bound to operation, caller and filters by an 8-byte digest, for `CURSOR_TTL_S`. Binary, as
a name may take 320 bytes and a cursor 22's 512 characters at most; unsigned, as the other list
cursors (a caller can forge only a position, read in its own scope). Else `None`: a 400."""

from __future__ import annotations

import base64
import hashlib
import json
import struct
from collections.abc import Sequence
from typing import Final
from uuid import UUID

CURSOR_TTL_S: Final = 3600
MAX_CURSOR: Final = 512  # 22's `Cursor` parameter
_HEAD: Final = struct.Struct(">B8sI")  # version, binding digest, issued (epoch s); then position


def _binding(operation: str, caller: UUID, filters: Sequence[str | None]) -> bytes:
    return hashlib.sha256(json.dumps([operation, str(caller), [*filters]]).encode()).digest()[:8]


def encode_cursor(
    operation: str, caller: UUID, filters: Sequence[str | None], position: bytes, issued: int
) -> str:
    raw = _HEAD.pack(1, _binding(operation, caller, filters), issued) + position
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(
    cursor: str, operation: str, caller: UUID, filters: Sequence[str | None], now: int
) -> bytes | None:
    if len(cursor) > MAX_CURSOR:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        version, bound, issued = _HEAD.unpack_from(raw)
    except (ValueError, struct.error):  # not base64 (a `binascii.Error`), or too short
        return None
    if (version, bound) != (1, _binding(operation, caller, filters)):
        return None
    return raw[_HEAD.size :] if 0 <= now - issued <= CURSOR_TTL_S else None
