"""Envelope: nonces, AAD/layout goldens, tamper and AAD-binding rejection (E27-T02)."""

from __future__ import annotations

from uuid import UUID

import pytest

from candleviewer.secrets import _envelope as env
from tests.unit.credentials_m2._vectors import (
    ACCOUNT,
)


def test_envelope_nonce_unique_across_1e5() -> None:
    assert len({env.new_nonce() for _ in range(100_000)}) == 100_000


def test_aad_encoding_golden() -> None:
    cid = UUID("00000000-0000-4000-8000-0000000000aa")
    assert env.aad(b"ab", b"") == b"\x00\x02ab\x00\x00"
    assert env.dek_aad(cid, 7) == (b"\x00\x09cv-dek-v1\x00\x10" + cid.bytes + b"\x00\x017")
    assert env.cred_aad("demo", ACCOUNT, cid, "secret") == (
        b"\x00\x0acv-cred-v2" + b"\x00\x04demo" + b"\x00\x10" + ACCOUNT.bytes
        + b"\x00\x10" + cid.bytes + b"\x00\x06secret"
    )  # fmt: skip
    with pytest.raises(ValueError):
        env.cred_aad("prod", ACCOUNT, cid, "secret")
    # 0x7C ('|') inside a UUID cannot alias a boundary any more
    assert env.aad(b"a|", b"b") != env.aad(b"a", b"|b")


#: AES-256-GCM(key=0^32, nonce=0^12, pt=b"abc", aad=b"") — independent of this module.
GOLDEN_SEAL = "000000000000000000000000afc52354109ef65a2f5ccbb3f052097814df3c"


def test_sealed_layout_golden_vector(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pinned layout: nonce(12) || ct || tag(16) under a fixed nonce + key."""
    monkeypatch.setattr(env, "new_nonce", lambda: bytes(12))
    blob = env.seal(bytes(32), b"abc", b"")
    assert len(blob) == 12 + 3 + 16 and blob[:12] == bytes(12)
    assert blob.hex() == GOLDEN_SEAL
    assert bytes(env.open_(bytes(32), blob, b"")) == b"abc"


def test_open_rejects_short_blob() -> None:
    with pytest.raises(ValueError):
        env.open_(bytes(32), bytes(27), b"")
