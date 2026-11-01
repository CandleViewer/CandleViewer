"""E27-Q03 (#892) finding F7: the account fixture stub's own cost per signed call (BQ-03).

    cd services/api && uv run python -m tests.chaos.accounts._e27_stub_cost --calls 1000

Builds the #2893 `FixtureTransport` on the checkout's pack, with the request log written to a
temporary directory on disk as on a stack, signs each call as the transport guard tests do
(`tests/unit/cvdev/test_transport_guards.py` `_get`), and times `handle_async_request` on one
event loop: p50 and p95 per call and calls per second, for the key-info read and the wallet read
of `compliant`. In process only: no socket, no network, no stack. Not a test (no assertion, not
collected); the plan's F7 row quotes its output, and PR-2 re-measures on the stack.
"""

from __future__ import annotations

import argparse
import asyncio
import platform
import statistics
import tempfile
import threading
import time
from pathlib import Path

# nosemgrep: cv-adapter-isolation reason=test-stub owner=@CandleViewer/security review=2027-03-25
from candleviewer.exchange.bybit.key_info import KEY_INFO_PATH
from candleviewer.net.read_only_gate import ReadOnlyGate
from candleviewer.settings import Environment
from cvdev.account_fixture.control import KeyStates
from cvdev.account_fixture.requestlog import RequestLog
from cvdev.account_fixture.transport import FixtureTransport
from tests._account_fixtures import PACK
from tests.unit.cvdev.test_transport_guards import _get
from tests.unit.cvdev.test_transport_serving import KEY_IDS, WALLET

# nosemgrep: cv-adapter-isolation reason=test-stub owner=@CandleViewer/security review=2027-03-25
from tests.unit.exchange.bybit.test_account_fixture_pack import NOW


async def _time(transport: FixtureTransport, path: str, calls: int) -> list[float]:
    """Milliseconds per call for `calls` signed GETs of `path`, one at a time."""
    out: list[float] = []
    for _ in range(calls):
        request = _get("compliant", path=path)
        t0 = time.perf_counter()
        response = await transport.handle_async_request(request)
        await response.aread()
        out.append((time.perf_counter() - t0) * 1000)
    return out


def _line(name: str, ms: list[float]) -> str:
    p95 = statistics.quantiles(ms, n=20)[18]
    return (
        f"{name}: n={len(ms)} p50={statistics.median(ms):.2f} ms p95={p95:.2f} ms "
        f"rate={len(ms) / (sum(ms) / 1000):.0f} calls/s"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    ap.add_argument("--calls", type=int, default=1000)
    a = ap.parse_args(argv)
    print(f"python {platform.python_version()} on {platform.system()} {platform.machine()}")
    with (
        tempfile.TemporaryDirectory() as tmp,
        RequestLog(
            Path(tmp), process_env=Environment.DEMO, clock=lambda: NOW, pack_key_ids=KEY_IDS
        ) as log,
    ):
        keys = KeyStates(Path(tmp), PACK, log=log, clock=lambda: NOW)
        transport = FixtureTransport(
            PACK,
            log=log,
            gate=ReadOnlyGate(),
            clock=lambda: NOW,
            default="compliant",
            keys=keys,
            latch=threading.Event(),
        )
        for name, path in (("key info", KEY_INFO_PATH), ("wallet", WALLET)):
            print(_line(name, asyncio.run(_time(transport, path, a.calls))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
