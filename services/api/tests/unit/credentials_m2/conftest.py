"""Fixtures for M2 tests. Fixed test vectors only; never a real key (C-13.5)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from candleviewer.secrets._kek import LoadedKek
from candleviewer.secrets.broker import CredentialBroker
from candleviewer.secrets.store import InMemoryCredentialStore

KEK_V1 = bytes(range(32))
KEK_V2 = bytes(range(100, 132))
ACCOUNT = UUID("00000000-0000-4000-8000-000000000001")
API_KEY = "TESTKEYabcd1234WXYZ"  # fixed vector, not a credential
API_SECRET = "TESTSECRETzzzz0000yyyy1111xxxx2222"  # noqa: S105 -- fixed test vector, not a credential
SNAPSHOT: dict[str, Any] = {"uid": "1", "permissions": {"ContractTrade": ["Order"]}}


def kek(raw: bytes = KEK_V1, version: int = 1) -> LoadedKek:
    return LoadedKek(bytearray(raw), version)


class AuditLog:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, str]]] = []
        self.fail = False

    async def __call__(self, action: str, fields: dict[str, str]) -> None:
        if self.fail:
            raise RuntimeError("audit down")
        self.records.append((action, dict(fields)))

    def actions(self) -> list[str]:
        return [a for a, _ in self.records]


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def store() -> InMemoryCredentialStore:
    return InMemoryCredentialStore()


@pytest.fixture
def audit() -> AuditLog:
    return AuditLog()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def broker(store: InMemoryCredentialStore, audit: AuditLog, clock: FakeClock) -> CredentialBroker:
    return CredentialBroker(store, audit, kek(), clock=clock)
