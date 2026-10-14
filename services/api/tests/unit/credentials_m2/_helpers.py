"""Shared helpers for the M2 broker tests."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from candleviewer.secrets import _envelope as env
from candleviewer.secrets.broker import BorrowHandle, CredentialBroker
from candleviewer.secrets.secret import Secret
from tests.unit.credentials_m2._vectors import (
    ACCOUNT,
    API_KEY,
    API_SECRET,
    ENV,
    SNAPSHOT,
)


async def _store(b: CredentialBroker, key: str = API_KEY, secret: str = API_SECRET) -> Any:
    """Store, then mark active (E27-T03 verification) so the row is signable."""
    meta = await b.store(ENV, ACCOUNT, "main", Secret(key), Secret(secret), SNAPSHOT)
    b._store.activate(meta.key_id)  # type: ignore[attr-defined]  # in-memory fake helper
    return meta


def _h(b: CredentialBroker) -> BorrowHandle:
    return b.borrow_handle("exchange_adapter")


async def _with[T](
    b: CredentialBroker,
    key_id: Any,
    fn: Callable[[Secret[str], Secret[str]], Awaitable[T]],
    purpose: str = "sign_rest",
) -> T:
    """M2's internal decrypt path, for M2's own round-trip tests. Its only production caller is
    `_sign`; no capability outside `secrets/` yields plaintext (#2339)."""
    return await b._borrow(key_id, fn, "exchange_adapter", purpose)


async def _borrow(b: CredentialBroker, key_id: Any) -> tuple[str, str]:
    async def fn(k: Secret[str], s: Secret[str]) -> tuple[str, str]:
        return k.reveal(), s.reveal()

    return await _with(b, key_id, fn)


class _Spy:
    """Captures the decrypted plaintext bytearrays to assert they are zeroed."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, fail_on: int | None = None) -> None:
        self.bufs: list[bytearray] = []
        real = env.open_
        calls = 0

        def open_(key: Any, blob: bytes, aad_: bytes) -> bytearray:
            nonlocal calls
            calls += 1
            if fail_on is not None and calls == fail_on:
                from cryptography.exceptions import InvalidTag

                raise InvalidTag
            out = real(key, blob, aad_)
            self.bufs.append(out)
            return out

        monkeypatch.setattr(env, "open_", open_)

    def all_zero(self) -> bool:
        return bool(self.bufs) and all(not any(b) for b in self.bufs)
