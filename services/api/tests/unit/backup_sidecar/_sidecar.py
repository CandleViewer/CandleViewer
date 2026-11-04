"""Test support for the backup sidecar (#3319 B1b): generated age recipients and well-formed age
headers (no key, no crypto: a header's stanza values are random bytes), a fake UTC clock, a
configuration under `tmp_path` and an in-process sidecar built on it. Every value is generated per
test; no network, nothing outside `tmp_path`."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cvbackup import age_format, protocol
from cvbackup.config import SidecarConfig
from cvbackup.floor import Floor
from cvbackup.ledger import Ledger, timestamp
from cvbackup.ops import KINDS, Ops
from cvbackup.paths import LEDGER_DIR, QUARANTINE_DIR, Root

T0 = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
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


def _write(location: str, data: bytes) -> None:
    fd = os.open(location, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def exists(path: str | Path) -> bool:
    return os.path.lexists(path)


def read(path: str | Path) -> bytes:
    return Path(path).read_bytes()


def write(path: str | Path, data: bytes, *, append: bool = False) -> None:
    with Path(path).open("ab" if append else "wb") as out:
        out.write(data)


def mode(path: str | Path) -> int:
    return os.stat(path).st_mode & 0o7777


class Clock:
    """A UTC clock that moves only when told."""

    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


def config(tmp_path: Path, sock: str, **changes: Any) -> SidecarConfig:
    """`sock`: the `sock` fixture's path (an AF_UNIX path holds at most 107 bytes)."""
    root = tmp_path / "backups"
    root.mkdir(exist_ok=True)
    to = recipient()
    values: dict[str, Any] = {
        "socket": sock,
        "root": str(root),
        "api_uid": os.getuid(),
        "recipient": to,
        "pin": age_format.fingerprint(to),
    }
    values.update(changes)
    return SidecarConfig(**values)


@dataclass
class Sidecar:
    config: SidecarConfig
    root: Root
    ledger: Ledger
    floor: Floor
    ops: Ops
    clock: Clock
    server: asyncio.Server | None = None

    async def finished(
        self, kind: str = "pg_dump", content: bytes | None = None, *, covers_to: datetime = T0,
        backup_id: str | None = None,
    ) -> tuple[str, str, str]:  # fmt: skip
        """A run the record holds as finished, its file in place: (backup id, location, digest)."""
        backup_id, name = backup_id or str(uuid.uuid4()), str(uuid.uuid4())
        location = f"{self.root.path}/{kind}/{name}.age"
        data = age_bytes(seed=uuid.UUID(name).int) if content is None else content
        await asyncio.to_thread(_write, location, data)
        digest = hashlib.sha256(data).hexdigest()
        await self.ledger.append("started", backup_id, kind=kind)
        await self.ledger.append(
            "finished", backup_id, kind=kind, location=location, digest=digest,
            covers_to=timestamp(covers_to), size_bytes=len(data),
        )  # fmt: skip
        return backup_id, location, digest

    async def handle(self, op: str, /, **args: str) -> dict[str, object]:
        request = protocol.Request(str(uuid.uuid4()), op, 60, args)
        return await self.ops.handle(request, lambda pct: None)


async def build(cfg: SidecarConfig, clock: Clock | None = None) -> Sidecar:
    clock = Clock() if clock is None else clock
    root = Root(cfg.root)
    root.ensure((LEDGER_DIR, QUARANTINE_DIR, *sorted(KINDS)))
    ledger = Ledger(root, clock)
    await ledger.load()
    floor = Floor(root, ledger, run_cap=cfg.run_cap, run_window=cfg.run_window, grace=cfg.grace)
    return Sidecar(cfg, root, ledger, floor, Ops(cfg, root, ledger, floor, clock=clock), clock)
