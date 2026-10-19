"""`exchange_smoke` suite wiring (E08-T05). See `tests/exchange_smoke/README.md`.

Opt-in: without `CV_EXCHANGE_SMOKE=1` every test here is skipped, nothing is looked
up, and the default CI py lane also deselects the marker (`-m "not exchange_smoke"`).
When opted in, the demo-only guard runs at import, before any lookup, and aborts the
whole session on a live-looking configuration (fail closed). Only then are the two
demo hosts resolved, still at import: the session network guard
(`tests/_ci_network_guard.py`) installs at the first test and refuses a name lookup
outside its allow-list (#3826). Only the resolved IPs go on that allow-list
(`CV_CI_ALLOWED_HOSTS`), never an exchange hostname. The clients look the hostnames
up again when they connect, so the session fixture fails the run closed, with an
explicit message, while the guard would refuse those lookups.
"""

from __future__ import annotations

import os
import socket
from collections.abc import Iterator, Mapping

import pytest

from tests._ci_network_guard import is_host_allowed
from tests.exchange_smoke._guard import DEMO_HOSTS, assert_demo_only, opted_in


def demo_ips_before_the_guard(env: Mapping[str, str]) -> frozenset[str]:
    """Resolve the demo hosts before the network guard installs; nothing unless opted in."""
    if not opted_in(env):
        return frozenset()
    assert_demo_only(env)  # raises SmokeGuardError before any lookup: the session aborts
    return frozenset(str(info[4][0]) for h in DEMO_HOSTS for info in socket.getaddrinfo(h, 443))


DEMO_IPS = demo_ips_before_the_guard(os.environ)  # at import: collection precedes the guard


@pytest.fixture(autouse=True, scope="session")
def _demo_only_session() -> Iterator[None]:
    if not opted_in(os.environ):
        pytest.skip("exchange_smoke is opt-in: set CV_EXCHANGE_SMOKE=1 (demo only)")
    by_name = [h for h in DEMO_HOSTS if not is_host_allowed(h)]
    if by_name:
        pytest.fail(
            f"exchange_smoke fails closed (#3826): the clients look up {', '.join(by_name)} by "
            "name when they connect, the test network guard refuses a name lookup outside its "
            "allow-list, and no exchange hostname is ever allow-listed (only the demo IPs "
            "resolved at import). No test dialled; see tests/exchange_smoke/README.md.",
            pytrace=False,
        )
    previous = os.environ.get("CV_CI_ALLOWED_HOSTS", "")
    os.environ["CV_CI_ALLOWED_HOSTS"] = ",".join(sorted(DEMO_IPS | ({previous} - {""})))
    try:
        yield
    finally:
        os.environ["CV_CI_ALLOWED_HOSTS"] = previous
