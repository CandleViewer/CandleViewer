"""The age v1 format, as far as the sidecar reads it without a key (ADR-0041 sections 2 and 3).

- `fingerprint`: the SHA-256 over the lower-case Bech32 `age1...` recipient string as ASCII,
  written `age-x25519-sha256:<64 lower-case hex digits>`, the value `encryption_ref` carries.
- `header_ok`: an age v1 header of at most `MAX_HEADER` bytes with exactly one `X25519` stanza
  and a well-formed MAC line, followed by at least a nonce and one chunk's tag. No decryption
  code exists here; an X25519 stanza names no recipient, so this cannot tell which key a file is
  for (the pinned fingerprint fixes that when the file is written).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from typing import Final

MAX_HEADER: Final = 4096
FINGERPRINT_PREFIX: Final = "age-x25519-sha256:"
_VERSION_LINE: Final = b"age-encryption.org/v1"
_COLUMNS: Final = 64
_NONCE: Final = 16
_TAG: Final = 16
_B64: Final = re.compile(rb"[A-Za-z0-9+/]*")
_CHARSET: Final = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_RECIPIENT: Final = re.compile(r"age1[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{58}")
_GENERATOR: Final = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)


def _polymod(values: list[int]) -> int:
    checksum = 1
    for value in values:
        top = checksum >> 25
        checksum = (checksum & 0x1FFFFFF) << 5 ^ value
        for bit, generator in enumerate(_GENERATOR):
            if (top >> bit) & 1:
                checksum ^= generator
    return checksum


def is_recipient(text: str) -> bool:
    """An age X25519 recipient: Bech32 (not Bech32m) with the `age` prefix, its checksum valid
    and its 52 data groups spelling 32 bytes with zero padding bits."""
    if _RECIPIENT.fullmatch(text) is None:
        return False
    data = [_CHARSET.index(c) for c in text[4:]]
    prefix = [ord(c) >> 5 for c in "age"] + [0] + [ord(c) & 31 for c in "age"]
    if _polymod(prefix + data) != 1:
        return False
    groups = data[:-6]
    return groups[-1] & 0b1111 == 0  # 52 groups of 5 bits carry 256 bits and 4 zero bits


def fingerprint(recipient: str) -> str:
    return FINGERPRINT_PREFIX + hashlib.sha256(recipient.encode("ascii")).hexdigest()


def is_fingerprint(text: str) -> bool:
    digest = text.removeprefix(FINGERPRINT_PREFIX)
    return digest != text and re.fullmatch(r"[0-9a-f]{64}", digest) is not None


def _raw_b64(text: bytes, size: int) -> bool:
    """Unpadded standard base64 of exactly `size` bytes, in its one canonical spelling."""
    if _B64.fullmatch(text) is None:
        return False
    try:
        raw = base64.b64decode(text + b"=" * (-len(text) % 4), validate=True)
    except binascii.Error:
        return False
    return len(raw) == size and base64.b64encode(raw).rstrip(b"=") == text


def header_ok(prefix: bytes, size: int) -> bool:
    """Whether a file of `size` bytes that starts with `prefix` (its first `MAX_HEADER` bytes, or
    all of it) opens with a well-formed age v1 header for one X25519 recipient."""
    end = prefix.find(b"\n--- ", 0, MAX_HEADER)
    if end < 0:
        return False
    close = prefix.find(b"\n", end + 1, MAX_HEADER)
    if close < 0:
        return False
    lines = prefix[:end].split(b"\n")
    mac = prefix[end + 5 : close]
    if lines[0] != _VERSION_LINE or not _raw_b64(mac, 32):
        return False
    stanza = lines[1:]
    if len(stanza) != 2 or stanza[0][:3] != b"-> ":  # one stanza: its line and one body line
        return False
    arguments = stanza[0][3:].split(b" ")
    if len(arguments) != 2 or arguments[0] != b"X25519" or not _raw_b64(arguments[1], 32):
        return False
    body = stanza[1]
    if len(body) >= _COLUMNS or not _raw_b64(body, 32):  # the wrapped file key: a short line
        return False
    return size - (close + 1) >= _NONCE + _TAG
