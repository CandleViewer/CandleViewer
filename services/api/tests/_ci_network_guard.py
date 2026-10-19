"""Pytest network guard (E03-T03; name resolution and the per-test verdict, #3826).

ADR-0012 ("offline deterministic CI, no live venue in CI") and SR-140
("CI must not hold production exchange credentials") require that no test in
this suite can reach the live exchange or any other non-loopback host
(C-13.5). This module guards the Python socket layer for the whole session:

* `socket.socket.connect`/`connect_ex`: a connection to a host outside the
  allow-list raises immediately, before the underlying OS call is made, so a
  test cannot "succeed" by timing out against a firewalled host and
  swallowing the error.
* Name resolution: `socket.getaddrinfo`, `gethostbyname`, `gethostbyname_ex`,
  `gethostbyaddr` and `getnameinfo` refuse a host outside the allow-list
  before the resolver runs, so no lookup leaves the machine. asyncio's
  `loop.getaddrinfo` runs `socket.getaddrinfo` in an executor, so
  `open_connection`, `create_connection`, anyio and httpx are covered too.
* Every refusal is also recorded. A client that absorbs the error (a bounded
  startup fetch, a retry loop) cannot hide it: the per-test verdict fails the
  test at teardown while a refusal is unclaimed. A test that drives the guard
  on purpose claims its refusals with `expected_refusals()`.

Allow-list: loopback (`127.0.0.1`, `::1`, `localhost`, any loopback literal)
plus any hostname/IP listed in the `CV_CI_ALLOWED_HOSTS` environment variable
(comma-separated), which CI sets to the service-container hostnames for the
`integration_db` subset (SR-131). Locally (no env var set) only loopback is
allowed. The guard sits at the Python `socket` layer: a resolver inside a C
extension (libpq, uvloop) does not pass through it.

This module contains no test collection itself; `tests/conftest.py` imports its
two autouse fixtures (the session guard and the per-test verdict), so every
test in `services/api/tests/**` is covered without per-file boilerplate.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import threading
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import pytest

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}

#: The `socket` module resolvers the session guard wraps (#3826).
_LOOKUPS = ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr", "getnameinfo")
#: The unguarded resolvers, captured once when the session guard installs its wrappers; the
#: wrappers call through this table (`resolver_tripwire()`, or a test's fake resolver).
_REAL_LOOKUPS: dict[str, Callable[..., Any]] = {}
#: The installed wrappers, by resolver name (`guard_installed`).
_WRAPPERS: dict[str, Callable[..., Any]] = {}


class NetworkGuardViolation(RuntimeError):
    """Raised when a test attempts an outbound connection to, or a name lookup of, a denied host.

    A `RuntimeError`, not an `OSError`: HTTP clients map `OSError` to a transient connect
    failure that a retry loop absorbs. A refusal absorbed anyway still fails the test at
    teardown (the per-test verdict)."""


@dataclass(frozen=True)
class Refusal:
    """One refused attempt: the guarded call and the host it named."""

    call: str
    host: str


class _RefusalLedger:
    """Refusals not yet claimed by a test. Thread-safe: resolvers run in executor threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._refusals: list[Refusal] = []

    def record(self, refusal: Refusal) -> None:
        with self._lock:
            self._refusals.append(refusal)

    def mark(self) -> int:
        with self._lock:
            return len(self._refusals)

    def take(self, since: int = 0) -> list[Refusal]:
        """Remove and return the refusals recorded after `since`."""
        with self._lock:
            taken = self._refusals[since:]
            del self._refusals[since:]
        return taken


_LEDGER = _RefusalLedger()


def _allowed_hosts() -> frozenset[str]:
    extra = os.environ.get("CV_CI_ALLOWED_HOSTS", "")
    hosts = {h.strip() for h in extra.split(",") if h.strip()}
    return frozenset(_LOOPBACK_HOSTS | hosts)


def _is_loopback_address(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_host_allowed(host: str, *, allowed_hosts: frozenset[str] | None = None) -> bool:
    """Return True iff `host` may be connected to from inside the test suite."""
    allowed = allowed_hosts if allowed_hosts is not None else _allowed_hosts()
    if host in allowed:
        return True
    return _is_loopback_address(host)


_Address = tuple[Any, ...] | str | bytes


def _extract_host(address: _Address) -> str | None:
    # `connect`/`connect_ex` accept a family-dependent tuple; IPv4/IPv6 both
    # have the host as element 0. Unix-domain sockets pass a str/bytes path,
    # not a host — always allowed (no network egress involved).
    if isinstance(address, tuple) and address:
        return str(address[0])
    return None


def _refuse(call: str, host: str) -> NetworkGuardViolation:
    """Record the refusal (so absorbing it cannot hide it) and build the error to raise."""
    _LEDGER.record(Refusal(call, host))
    if call in _LOOKUPS:
        target = f"name resolution of {host!r} ({call})"
    else:
        target = f"connection to {host!r}"
    return NetworkGuardViolation(
        f"outbound network denied in CI: {target} is not in the "
        "loopback/CV_CI_ALLOWED_HOSTS allow-list (ADR-0012, SR-140)"
    )


def _lookup_target(call: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> object:
    """The host a resolver call names, or None when the call looks nothing up."""
    if call == "getnameinfo":  # (sockaddr, flags): a reverse lookup unless NI_NUMERICHOST
        if len(args) == 2 and isinstance(args[0], tuple) and args[0] and isinstance(args[1], int):
            return None if args[1] & socket.NI_NUMERICHOST else args[0][0]
        return None  # malformed: the real call raises TypeError and looks nothing up
    # getaddrinfo(None, port) is the passive/loopback address: no lookup either.
    return args[0] if args else kwargs.get("host")


def _host_text(host: object) -> str | None:
    """The host as text (anyio and httpx pass IDNA-encoded bytes), or None if it is not one."""
    if isinstance(host, str):
        return host
    if isinstance(host, bytes | bytearray):
        return bytes(host).decode("ascii", "backslashreplace")
    return None  # None, or a type the real call rejects without a lookup


def _guarded_lookup(call: str) -> Callable[..., Any]:
    def guarded(*args: Any, **kwargs: Any) -> Any:
        host = _host_text(_lookup_target(call, args, kwargs))
        if host is not None and not is_host_allowed(host):
            raise _refuse(call, host)
        return _REAL_LOOKUPS[call](*args, **kwargs)

    guarded.__name__ = guarded.__qualname__ = f"cv_guarded_{call}"
    return guarded


def guard_installed() -> bool:
    """True while the session guard's resolver wrappers are the ones on `socket`."""
    return bool(_WRAPPERS) and all(getattr(socket, n) is _WRAPPERS.get(n) for n in _LOOKUPS)


def _tripwire(call: str, real: Callable[..., Any], reached: list[str]) -> Callable[..., Any]:
    def trip(*args: Any, **kwargs: Any) -> Any:
        host = _host_text(_lookup_target(call, args, kwargs))
        if host is None or host == "localhost" or _is_loopback_address(host):
            return real(*args, **kwargs)  # a loopback lookup never leaves the machine
        reached.append(call)
        raise AssertionError(f"a lookup of {host!r} got past the network guard to {call}")

    return trip


@contextmanager
def resolver_tripwire() -> Iterator[list[str]]:
    """For the guard's own tests: inside the block a non-loopback lookup that gets past the
    guard trips (and is listed) instead of reaching the real resolver, so even a regressed
    guard lets nothing leave the machine. Refuses to start unless the session guard is
    installed."""
    if not guard_installed():
        raise RuntimeError("the session network guard is not installed")
    reached: list[str] = []
    saved = dict(_REAL_LOOKUPS)
    _REAL_LOOKUPS.update({name: _tripwire(name, real, reached) for name, real in saved.items()})
    try:
        yield reached
    finally:
        _REAL_LOOKUPS.update(saved)


@contextmanager
def expected_refusals() -> Iterator[list[Refusal]]:
    """Claim the refusals made inside the block, for a test that drives the guard on purpose.

    The yielded list is filled when the block exits, so assert on it after the block. Claimed
    refusals do not fail the test at teardown; any other refusal still does."""
    claimed: list[Refusal] = []
    since = _LEDGER.mark()
    try:
        yield claimed
    finally:
        claimed.extend(_LEDGER.take(since))


def _verdict(refusals: list[Refusal], when: str) -> None:
    """Fail the current test (or session) when the guard refused anything nobody claimed."""
    if not refusals:
        return
    attempts = ", ".join(
        f"{r.call}({r.host!r})" + (f" x{n}" if n > 1 else "") for r, n in Counter(refusals).items()
    )
    pytest.fail(
        f"network guard refused {len(refusals)} outbound attempt(s) {when}: {attempts}. Tests "
        "must not reach a host outside the loopback/CV_CI_ALLOWED_HOSTS allow-list (C-13.5), "
        "and a refusal absorbed by the code under test still fails the test: stub the client, "
        "or claim a deliberate refusal with `expected_refusals()`.",
        pytrace=False,
    )


@pytest.fixture(autouse=True, scope="session")
def _cv_network_guard() -> Iterator[None]:
    """Autouse session fixture: deny non-loopback outbound connections and name lookups.

    Patches `socket.socket.connect`/`connect_ex` and the `socket` module resolvers for
    the lifetime of the test session. Guard is process-global by design (a background
    or executor thread opening a socket or resolving a name must be caught too), so it
    is not reset per-test. A refusal still unclaimed when the session ends (a session
    fixture's teardown) fails the session.
    """
    if _WRAPPERS:  # an enclosing session (an in-process pytester run) already guards
        yield
        return
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def _guarded_connect(self: socket.socket, address: _Address) -> None:
        host = _extract_host(address)
        if host is not None and not is_host_allowed(host):
            raise _refuse("connect", host)
        real_connect(self, address)

    def _guarded_connect_ex(self: socket.socket, address: _Address) -> int:
        host = _extract_host(address)
        if host is not None and not is_host_allowed(host):
            raise _refuse("connect_ex", host)
        return real_connect_ex(self, address)

    _REAL_LOOKUPS.update({name: getattr(socket, name) for name in _LOOKUPS})
    _WRAPPERS.update({name: _guarded_lookup(name) for name in _LOOKUPS})
    socket.socket.connect = _guarded_connect  # type: ignore[method-assign,assignment]
    socket.socket.connect_ex = _guarded_connect_ex  # type: ignore[method-assign,assignment]
    for name, wrapper in _WRAPPERS.items():
        setattr(socket, name, wrapper)
    try:
        yield
    finally:
        socket.socket.connect = real_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = real_connect_ex  # type: ignore[method-assign]
        for name, real in _REAL_LOOKUPS.items():
            setattr(socket, name, real)
        _WRAPPERS.clear()
        _REAL_LOOKUPS.clear()
    _verdict(_LEDGER.take(), "after the last test")


@pytest.fixture(autouse=True)
def _cv_network_guard_verdict(_cv_network_guard: None) -> Iterator[None]:
    """Autouse per-test verdict (#3826): fail the test at teardown while the guard holds a
    refusal nobody claimed, so a refusal the code under test absorbed (a bounded fetch, a
    retry loop) still fails the test that caused it."""
    yield
    _verdict(_LEDGER.take(), "during this test")
