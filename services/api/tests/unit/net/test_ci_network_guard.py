"""Unit tests for the CI network guard (E03-T03).

Loopback connections must succeed (against a real local listener); a
connection to a non-allow-listed host must raise `NetworkGuardViolation`
before any real socket I/O happens; `CV_CI_ALLOWED_HOSTS` entries must be
honoured. No real network egress in any case (C-13.5/C-13.7) — the "denied"
path never reaches the OS, and the "allowed" path only ever talks to a
socket this test itself opened on loopback. A deliberate refusal is claimed
with `expected_refusals()`, or the per-test verdict fails the test (#3826).
"""

from __future__ import annotations

import socket
from collections.abc import Iterator

import pytest

from tests._ci_network_guard import (
    NetworkGuardViolation,
    Refusal,
    expected_refusals,
    is_host_allowed,
)

pytestmark = pytest.mark.usefixtures("_cv_network_guard")


@pytest.fixture
def loopback_listener() -> Iterator[tuple[str, int]]:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    try:
        yield server.getsockname()
    finally:
        server.close()


def test_guard_allows_loopback_connect(loopback_listener: tuple[str, int]) -> None:
    host, port = loopback_listener
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client.connect((host, port))
    finally:
        client.close()


def test_guard_denies_non_loopback_connect() -> None:
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with (
            expected_refusals() as refused,
            pytest.raises(NetworkGuardViolation, match="outbound network denied in CI"),
        ):
            client.connect(("93.184.216.34", 443))
    finally:
        client.close()
    assert refused == [Refusal("connect", "93.184.216.34")]


def test_guard_denies_live_exchange_hostname_resolution_bypass() -> None:
    # A bare hostname (not pre-resolved) still must be denied — the guard
    # checks the literal address tuple passed to connect(), which is what
    # every real caller (including `httpx`/`websockets`) ultimately supplies
    # after their own resolution step.
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with expected_refusals() as refused, pytest.raises(NetworkGuardViolation):
            client.connect(("198.51.100.7", 443))
    finally:
        client.close()
    assert refused == [Refusal("connect", "198.51.100.7")]


def test_is_host_allowed_true_for_loopback_variants() -> None:
    assert is_host_allowed("127.0.0.1") is True
    assert is_host_allowed("::1") is True
    assert is_host_allowed("localhost") is True


def test_is_host_allowed_false_for_arbitrary_public_host() -> None:
    assert is_host_allowed("93.184.216.34") is False


def test_is_host_allowed_honours_explicit_allow_list() -> None:
    allowed = frozenset({"127.0.0.1", "::1", "localhost", "questdb-ci"})
    assert is_host_allowed("questdb-ci", allowed_hosts=allowed) is True
    assert is_host_allowed("other-host", allowed_hosts=allowed) is False


def test_is_host_allowed_reads_cv_ci_allowed_hosts_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CV_CI_ALLOWED_HOSTS", "postgres-ci, questdb-ci")
    assert is_host_allowed("postgres-ci") is True
    assert is_host_allowed("questdb-ci") is True
    assert is_host_allowed("random-host") is False
