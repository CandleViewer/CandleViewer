"""E08-X02 security note: the suite is incapable of targeting live Bybit.

Every REST client here is built on an `httpx.MockTransport`, every socket is a
fake, and the repo-wide network guard (`tests/_ci_network_guard.py`) is autouse.
This guard proves the guard is active for this package, and that it refuses the
venue host at name resolution, so not even a lookup leaves the machine (#3826).
"""

from __future__ import annotations

import socket

import pytest

from tests._ci_network_guard import (
    NetworkGuardViolation,
    Refusal,
    expected_refusals,
    resolver_tripwire,
)


def test_network_guard_blocks_exchange_hosts() -> None:
    with (
        resolver_tripwire() as reached,  # even a regressed guard cannot let the lookup out
        expected_refusals() as refused,
        pytest.raises(NetworkGuardViolation, match=r"name resolution of 'stream\.bybit\.com'"),
    ):
        socket.create_connection(("stream.bybit.com", 443), timeout=0.01)
    assert refused == [Refusal("getaddrinfo", "stream.bybit.com")]  # claimed: refused, not dialled
    assert reached == []


def test_no_suite_module_opens_real_transport() -> None:
    from pathlib import Path

    banned = ("httpx." + "AsyncHTTPTransport", "ws_" + "connect(", "BybitRestClient(Rest")
    here = Path(__file__).parent
    for py in here.glob("*.py"):
        text = py.read_text(encoding="utf-8")
        for needle in banned[:2]:
            assert needle not in text, f"{py.name}: {needle}"
        # Every REST client constructed in the suite is given a mock transport.
        assert text.count("BybitRestClient(\n") <= text.count("MockTransport("), py.name
