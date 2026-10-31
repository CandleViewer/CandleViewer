# ruff: noqa: S101  (pytest asserts: the project's tests/** ignore does not reach spike/)
"""The harness's test session: any socket connect or name lookup fails the test (#843 A4 gates).

Stricter than `tests/_ci_network_guard.py`, which allows loopback: here nothing may dial at all,
loopback included, so an offline run that completes under it has opened no socket (C-13.5). A
refusal a client swallows still fails the test at teardown. structlog is reset after each test,
since `__main__` configures it for the harness's own process.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from typing import Any

import pytest
import structlog

_GUARDED = ("connect", "connect_ex")
_LOOKUPS = ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "create_connection")


class NetworkRefused(RuntimeError):
    """The spike's tests dial nothing (C-13.5)."""


class Ledger:
    def __init__(self) -> None:
        self.attempts: list[str] = []

    def refuse(self, what: str) -> NetworkRefused:
        self.attempts.append(what)
        return NetworkRefused(f"network refused in the spike's tests: {what}")


_LEDGER = Ledger()


def _refusing(what: str) -> Any:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise _LEDGER.refuse(what)

    return refuse


@pytest.fixture(scope="session", autouse=True)
def no_network() -> Iterator[Ledger]:
    patcher = pytest.MonkeyPatch()
    for name in _GUARDED:
        patcher.setattr(socket.socket, name, _refusing(f"socket.{name}"))
    for name in _LOOKUPS:
        patcher.setattr(socket, name, _refusing(name))
    yield _LEDGER
    patcher.undo()


@pytest.fixture(autouse=True)
def no_network_verdict(no_network: Ledger) -> Iterator[Ledger]:
    """A test that met a refusal fails, even when a client absorbed it; a test that drives the
    guard on purpose clears what it caused (`claim`)."""
    mark = len(no_network.attempts)
    yield no_network
    unclaimed = no_network.attempts[mark:]
    del no_network.attempts[mark:]
    assert not unclaimed, f"the test tried the network: {unclaimed}"


@pytest.fixture(autouse=True)
def reset_structlog() -> Iterator[None]:
    yield
    structlog.reset_defaults()
