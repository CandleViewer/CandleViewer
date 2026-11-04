"""Test support for the backup sidecar (#3319 B1b): generated age recipients and well-formed age
headers (no key, no crypto: a header's stanza values are random bytes). Every value is
generated per test; no network, nothing outside `tmp_path`."""

from __future__ import annotations

import base64
import hashlib
import os

_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _polymod(values: list[int]) -> int:
    generator = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    checksum = 1
    for value in values:
        top = checksum >> 25
        checksum = (checksum & 0x1FFFFFF) << 5 ^ value
        for bit in range(5):
            checksum ^= generator[bit] if (top >> bit) & 1 else 0
    return checksum


def recipient(key: bytes | None = None) -> str:
    """A Bech32 `age1...` recipient for 32 bytes (random by default): shape only, no key pair."""
    key = os.urandom(32) if key is None else key
    bits = int.from_bytes(key, "big") << 4  # 256 bits, then 4 zero padding bits: 52 groups
    data = [(bits >> (5 * (51 - i))) & 31 for i in range(52)]
    prefix = [ord(c) >> 5 for c in "age"] + [0] + [ord(c) & 31 for c in "age"]
    mod = _polymod(prefix + data + [0] * 6) ^ 1
    data += [(mod >> 5 * (5 - i)) & 31 for i in range(6)]
    return "age1" + "".join(_CHARSET[d] for d in data)


class _Bytes:
    """Deterministic test bytes from a seed (SHAKE-256), never a secret."""

    def __init__(self, seed: int) -> None:
        self._seed, self._count = seed, 0

    def take(self, size: int) -> bytes:
        self._count += 1
        return hashlib.shake_256(f"{self._seed}:{self._count}".encode()).digest(size)


def _b64(size: int, rng: _Bytes) -> bytes:
    return base64.b64encode(rng.take(size)).rstrip(b"=")


def age_bytes(
    payload: int = 64, *, stanzas: tuple[str, ...] = ("X25519",), seed: int = 1, pad: int = 0
) -> bytes:
    """An age v1 file in shape: one stanza per entry of `stanzas`, `pad` extra bytes in the first
    stanza's line (to push the header past its bound), the MAC line, then `payload` bytes."""
    rng = _Bytes(seed)
    lines = [b"age-encryption.org/v1"]
    for kind in stanzas:
        lines.append(b"-> " + kind.encode() + b" " + _b64(32, rng) + b"A" * pad)
        lines.append(_b64(32, rng))
    lines.append(b"--- " + _b64(32, rng))
    return b"\n".join(lines) + b"\n" + rng.take(payload)
