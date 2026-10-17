"""E17-Q01: every socket-driven row under both subprotocols (AC6), and the requirement coverage
matrix in the CI output, so a silently skipped or deselected requirement is visible rather than
green (ticket "Observability")."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import pytest

from tests.contract.ws._harness import JSON_ONLY_ATTR, OFFERS, current_wire, reset_wire, use_wire

#: §16.1 server MUSTs; client obligations C1-C12 are E17-Q04's (cross-referenced in the plan).
REQUIREMENTS = tuple(f"S{n}" for n in range(1, 15))
#: Only this directory's `test_sN_` rows count: the `py` lane runs other suites in the same session.
_NAME = re.compile(r"(?:^|/)tests/contract/ws/[^:]*::test_(s\d+)_")
#: A test drives a socket when its own code names one of these (`World()` builds the gateway,
#: `connect()` opens a client on it). `connect()` fails loudly for a test that does so without
#: either, so a helper that hides them cannot leave a test on one subprotocol unnoticed.
_SOCKET_NAMES = frozenset({"World", "connect"})


@pytest.fixture(autouse=True)
def wire(request: pytest.FixtureRequest) -> Iterator[str | None]:
    """The wire (an `OFFERS` key) this socket-driven test runs under: `connect()` offers it unless
    the test names an offer. `None` for a test that opens no socket."""
    name: str | None = getattr(request, "param", None)
    if name is None:  # a test with its own `offer` still counts, under the wire that offer speaks
        own = getattr(getattr(request.node, "callspec", None), "params", {}).get("offer")
        for tag, offer in OFFERS.items():
            if offer == own:
                request.node.user_properties.append(("wire", tag))
        yield None
        return
    request.node.user_properties.append(("wire", name))
    token = use_wire(name)
    try:
        assert current_wire() == name  # a broken fixture fails every row, not one
        yield name
    finally:
        reset_wire(token)


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Run every socket-driven test under each wire (AC6): `cv.v1.json`, and `cv.v1.msgpack`
    preferred with JSON as the fallback. A test with its own `offer` parameter chose its offers;
    a test that opens no socket has no wire; a `json_only` test runs under JSON alone."""
    if "offer" in metafunc.fixturenames:
        return
    if not _SOCKET_NAMES & set(metafunc.function.__code__.co_names):
        return
    json_only = getattr(metafunc.function, JSON_ONLY_ATTR, False)
    metafunc.parametrize("wire", ["json"] if json_only else list(OFFERS), indirect=True)


def pytest_terminal_summary(terminalreporter: Any) -> None:
    ran: dict[str, int] = {}
    by_wire: dict[str, dict[str, int]] = {}
    only_perf = True
    for status in ("passed", "failed", "skipped", "xfailed", "xpassed"):
        for report in terminalreporter.stats.get(status, []):
            if getattr(report, "when", "call") != "call" and status != "skipped":
                continue
            m = _NAME.search(report.nodeid)
            if m:
                only_perf &= "perf" in report.keywords
                req = m.group(1).upper()
                ran.setdefault(req, 0)
                ran[req] += status == "passed"
                for key, name in getattr(report, "user_properties", ()):
                    if key == "wire" and status == "passed":
                        counts = by_wire.setdefault(req, {})
                        counts[name] = counts.get(name, 0) + 1
    if not ran or only_perf:  # nothing ran, or only the `perf` job's rows: no matrix to read
        return
    terminalreporter.section("E17-Q01 WS conformance: requirement coverage (23-ws-protocol §16.1)")
    for req in REQUIREMENTS:
        n = ran.get(req)
        wires = ", ".join(f"{name} {count}" for name, count in sorted(by_wire.get(req, {}).items()))
        row = "NOT RUN" if n is None else f"{n} passed" + (f" ({wires})" if wires else "")
        terminalreporter.write_line(f"{req:>4}  {row}")
    terminalreporter.write_line(
        "C1-C12  client obligations: asserted from the client side in E17-Q04"
    )
