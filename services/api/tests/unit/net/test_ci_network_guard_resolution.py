"""Name-resolution guard and per-test verdict (#3826; C-13.5, ADR-0012, SR-140).

The session guard refuses a lookup of a host outside the loopback/CV_CI_ALLOWED_HOSTS
allow-list at every resolver entry point, before the resolver runs; loopback and the
allow-listed compose names keep resolving; and every refusal is recorded, so a client
that absorbs the error still fails its test at teardown; a wrapper left replaced fails
its test and is put back, and either left after the last test fails the session.
No lookup leaves the machine here: refused names use the reserved `.invalid` TLD and
TEST-NET-1, the captured real resolvers are tripwires while they are tried, and the real
lookups are loopback only.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import anyio
import pytest

from tests._ci_network_guard import (
    _REAL_LOOKUPS,
    NetworkGuardViolation,
    Refusal,
    _guarded_lookup,
    _verdict,
    expected_refusals,
    guard_installed,
    resolver_tripwire,
)

pytest_plugins = ("pytester",)

_DENIED = "venue.invalid"  # RFC 6761: reserved, never a real host
_DENIED_IP = "192.0.2.7"  # RFC 5737 TEST-NET-1: never routed
_SERVICE_ROOT = Path(__file__).resolve().parents[3]  # services/api


@pytest.fixture
def tripwire() -> Iterator[list[str]]:
    """A regressed guard fails the test instead of letting a lookup leave the machine."""
    with resolver_tripwire() as reached:
        yield reached


def _refused(call: str, host: str) -> str:
    return re.escape(f"name resolution of {host!r} ({call})")


@pytest.mark.parametrize(
    ("call", "lookup", "host"),
    [
        pytest.param("getaddrinfo", lambda: socket.getaddrinfo(_DENIED, 443), _DENIED, id="gai"),
        pytest.param(  # anyio and httpx pass the host IDNA-encoded
            "getaddrinfo", lambda: socket.getaddrinfo(_DENIED.encode(), 443), _DENIED, id="bytes"
        ),
        pytest.param(
            "getaddrinfo", lambda: socket.getaddrinfo(host=_DENIED, port=443), _DENIED, id="kw"
        ),
        pytest.param(
            "getaddrinfo",
            lambda: socket.create_connection((_DENIED, 443), timeout=0.01),
            _DENIED,
            id="create_connection",
        ),
        pytest.param("gethostbyname", lambda: socket.gethostbyname(_DENIED), _DENIED, id="ghbn"),
        pytest.param(
            "gethostbyname_ex", lambda: socket.gethostbyname_ex(_DENIED), _DENIED, id="ghbn_ex"
        ),
        pytest.param(
            "gethostbyaddr", lambda: socket.gethostbyaddr(_DENIED_IP), _DENIED_IP, id="reverse"
        ),
        pytest.param(
            "getnameinfo",
            lambda: socket.getnameinfo((_DENIED_IP, 443), 0),
            _DENIED_IP,
            id="getnameinfo",
        ),
    ],
)
def test_lookup_outside_the_allow_list_is_refused_before_the_resolver_runs(
    tripwire: list[str], call: str, lookup: Callable[[], object], host: str
) -> None:
    with (
        expected_refusals() as refused,
        pytest.raises(NetworkGuardViolation, match=_refused(call, host)),
    ):
        lookup()
    assert refused == [Refusal(call, host)]
    assert tripwire == []


async def test_asyncio_and_anyio_lookups_are_refused_in_the_executor(tripwire: list[str]) -> None:
    with expected_refusals() as refused:
        with pytest.raises(NetworkGuardViolation, match=_refused("getaddrinfo", _DENIED)):
            await asyncio.get_running_loop().getaddrinfo(_DENIED, 443)
        with pytest.raises(NetworkGuardViolation, match=_refused("getaddrinfo", _DENIED)):
            await asyncio.open_connection(_DENIED, 443)
        with pytest.raises(NetworkGuardViolation, match=_refused("getaddrinfo", _DENIED)):
            await anyio.connect_tcp(_DENIED, 443)  # the httpx path
    assert refused == [Refusal("getaddrinfo", _DENIED)] * 3
    assert tripwire == []


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1"])
def test_loopback_names_and_literals_still_resolve(host: str) -> None:
    with expected_refusals() as refused:
        infos = socket.getaddrinfo(host, 0, type=socket.SOCK_STREAM)
    assert infos
    assert all(ipaddress.ip_address(info[4][0]).is_loopback for info in infos)
    assert refused == []


def test_lookups_that_name_no_remote_host_still_run() -> None:
    with expected_refusals() as refused:
        assert ipaddress.ip_address(socket.gethostbyname("localhost")).is_loopback
        assert socket.getaddrinfo(None, 0, type=socket.SOCK_STREAM)  # the passive address
        numeric = socket.NI_NUMERICHOST | socket.NI_NUMERICSERV  # formats, looks nothing up
        assert socket.getnameinfo((_DENIED_IP, 443), numeric) == (_DENIED_IP, "443")
    assert refused == []


def test_allow_listed_compose_name_reaches_the_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CV_CI_ALLOWED_HOSTS", "postgres-ci, questdb-ci")
    answer = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.89.0.5", 9009))]
    seen: list[tuple[object, ...]] = []

    def fake_getaddrinfo(*args: object, **_kwargs: object) -> list[Any]:
        seen.append(args)  # stands in for the real resolver: no lookup in a test
        return answer

    monkeypatch.setitem(_REAL_LOOKUPS, "getaddrinfo", fake_getaddrinfo)
    with expected_refusals() as refused:
        assert socket.getaddrinfo("questdb-ci", 9009) == answer
        with pytest.raises(NetworkGuardViolation, match=_refused("getaddrinfo", "redis-ci")):
            socket.getaddrinfo("redis-ci", 6379)
    assert seen == [("questdb-ci", 9009)]
    assert refused == [Refusal("getaddrinfo", "redis-ci")]


def test_a_wrapper_that_outlives_the_session_still_guards_and_resolves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = _guarded_lookup("getaddrinfo", lambda *args, **_kwargs: [args])
    monkeypatch.delitem(_REAL_LOOKUPS, "getaddrinfo")  # as after the session guard's teardown
    with expected_refusals() as refused, pytest.raises(NetworkGuardViolation):
        stale(_DENIED, 443)
    assert stale("localhost", 0) == [("localhost", 0)]  # reached the resolver it wraps
    assert refused == [Refusal("getaddrinfo", _DENIED)]


async def test_a_refusal_the_client_absorbs_is_still_recorded(tripwire: list[str]) -> None:
    errors: list[Exception] = []

    async def bounded_fetch() -> None:  # retries, then gives up quietly (as the clock guard did)
        for _attempt in range(3):
            try:
                await asyncio.open_connection(_DENIED, 443)
            except Exception as exc:
                errors.append(exc)

    with expected_refusals() as refused:
        await bounded_fetch()
    assert [type(e) for e in errors] == [NetworkGuardViolation] * 3
    assert refused == [Refusal("getaddrinfo", _DENIED)] * 3
    assert tripwire == []


def test_verdict_fails_the_test_on_an_unclaimed_refusal() -> None:
    refusals = [Refusal("getaddrinfo", _DENIED)] * 20 + [Refusal("connect", _DENIED_IP)]
    expected = "refused 21 outbound attempt(s) during this test: getaddrinfo('venue.invalid') x20"
    with pytest.raises(pytest.fail.Exception, match=re.escape(f"{expected}, connect('192.0.2.7')")):
        _verdict(refusals, "during this test")


def test_every_test_runs_under_the_guard_and_its_verdict(request: pytest.FixtureRequest) -> None:
    assert {"_cv_network_guard", "_cv_network_guard_verdict"} <= set(request.fixturenames)
    assert guard_installed()


_INNER_CONFTEST = """
import sys

from tests._ci_network_guard import _cv_network_guard, _cv_network_guard_verdict  # noqa: F401


def _backstop(event, args):
    # This run only: if the guard ever stopped refusing, the lookup fails here (an OSError
    # the client absorbs, so the outer assertion fails) instead of leaving the machine.
    if event == "socket.getaddrinfo" and args[0] not in (None, "localhost", b"localhost"):
        raise OSError("lookup stopped by the test backstop")


sys.addaudithook(_backstop)
"""

_ABSORBED = """
import socket


def test_a_bounded_fetch_that_absorbs_every_failure():
    errors = []
    for _attempt in range(3):
        try:
            socket.getaddrinfo("venue.invalid", 443)
        except Exception as exc:  # treated as transient, then given up on quietly
            errors.append(exc)
    assert len(errors) == 3
"""

_LEFT_AFTER_THE_LAST_TEST = """
import socket

import pytest


@pytest.fixture(scope="module")
def absorbs_a_lookup_at_module_teardown():
    yield
    try:  # a module teardown runs after the last test's own verdict
        socket.getaddrinfo("venue.invalid", 443)
    except Exception:
        pass
    socket.socket.connect_ex = lambda self, address: 0  # and leaves a wrapper replaced


def test_the_last_test(absorbs_a_lookup_at_module_teardown):
    pass
"""

_LEFT_REPLACED = """
import socket

from tests._ci_network_guard import guard_installed


def test_replaces_two_wrappers_and_leaves_them():
    socket.getaddrinfo = lambda *args, **kwargs: []
    socket.socket.connect = lambda self, address: None


def test_the_next_test_runs_guarded_again():
    assert guard_installed()
"""


def _run_inner(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, tests: str
) -> pytest.RunResult:
    """Run `tests` in a fresh pytest process under the session guard and its verdict."""
    monkeypatch.setenv("PYTHONPATH", str(_SERVICE_ROOT))
    monkeypatch.delenv("CV_CI_ALLOWED_HOSTS", raising=False)
    pytester.makeini("[pytest]\n")
    pytester.makeconftest(_INNER_CONFTEST)
    pytester.makepyfile(tests)
    return pytester.runpytest_subprocess("-p", "no:cacheprovider", timeout=120)


def test_a_refusal_absorbed_by_the_code_under_test_fails_that_test(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _run_inner(pytester, monkeypatch, _ABSORBED)
    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines(
        [
            "*ERROR at teardown of test_a_bounded_fetch_that_absorbs_every_failure*",
            "*network guard refused 3 outbound attempt(s) during this test: "
            "getaddrinfo('venue.invalid') x3*",
        ]
    )


def test_a_refusal_or_wrapper_left_after_the_last_test_fails_the_session(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _run_inner(pytester, monkeypatch, _LEFT_AFTER_THE_LAST_TEST)
    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines(
        [
            "*ERROR at teardown of test_the_last_test*",
            "*the network guard's connect_ex wrapper(s) were replaced after the last test and left "
            "in place*network guard refused 1 outbound attempt(s) after the last test: "
            "getaddrinfo('venue.invalid'). *",
        ]
    )


def test_a_wrapper_left_replaced_fails_that_test_and_is_put_back(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _run_inner(pytester, monkeypatch, _LEFT_REPLACED)
    result.assert_outcomes(passed=2, errors=1)  # the next test finds the guard in place again
    result.stdout.fnmatch_lines(
        [
            "*ERROR at teardown of test_replaces_two_wrappers_and_leaves_them*",
            "*the network guard's getaddrinfo, connect wrapper(s) were replaced during this test "
            "and left in place*",
        ]
    )
