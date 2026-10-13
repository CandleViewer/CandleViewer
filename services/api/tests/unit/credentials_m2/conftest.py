"""Fixtures for M2 tests (vectors and fakes live in `_vectors`)."""

from __future__ import annotations

import pytest

from candleviewer.secrets.broker import CredentialBroker
from candleviewer.secrets.store import InMemoryCredentialStore
from tests.unit.credentials_m2._vectors import AuditLog, FakeClock, kek


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
