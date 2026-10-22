"""Scenario 4 drivers: in-process (PR smoke, httpx ASGI transport, no sockets) and k6 (full).

The in-process driver issues the *same* request plan as `tests/load/k6/ingestion_rest.js`
(`fixture_app.requests_plan`), at a bounded concurrency, and records per-route latency. The k6
path starts uvicorn on 127.0.0.1 over the fixture backend, runs k6 with `--summary-export`, and
folds the per-route p95s into the same verdict. Neither path can reach an exchange host.
"""

from __future__ import annotations

import asyncio
import json
import math
import shutil
import socket
import subprocess
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import httpx

from bench.ingestion import budgets
from bench.ingestion.config import Scenario
from bench.ingestion.fixture_app import (
    assert_loopback_target,
    build_app,
    requests_plan,
    write_cold_lake,
)

K6_SCRIPT = Path(__file__).resolve().parents[4] / "tests" / "load" / "k6" / "ingestion_rest.js"


async def drive_inprocess(iterations: int, concurrency: int) -> dict[str, list[float]]:
    """Per-route latencies (ms). Cold klines bypass nothing: each cold call hits DuckDB."""
    with tempfile.TemporaryDirectory(prefix="cv-e08q04-") as tmp:
        write_cold_lake(Path(tmp))
        app = await build_app(Path(tmp))
        base = "http://127.0.0.1"
        assert_loopback_target(base)
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
        out: dict[str, list[float]] = {k: [] for k in requests_plan()}
        sem = asyncio.Semaphore(concurrency)
        async with httpx.AsyncClient(transport=transport, base_url=base) as client:

            async def one(route: str, spec: dict[str, Any]) -> None:
                async with sem:
                    t0 = time.perf_counter()
                    r = await client.get(spec["path"], params=spec["params"])
                    out[route].append((time.perf_counter() - t0) * 1000)
                    if r.status_code != 200:
                        raise RuntimeError(f"{route}: HTTP {r.status_code}")

            for spec in requests_plan().values():  # one untimed warm-up per route
                await client.get(spec["path"], params=spec["params"])
            await asyncio.gather(
                *(one(r, s) for _ in range(iterations) for r, s in requests_plan().items())
            )
        return out


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


#: k6's exit codes that leave a reading: 0 (passed) and 99 (a threshold crossed, which `verdict`
#: judges itself). Any other code is a script, configuration or run error: no reading (#2825).
K6_READING_EXITS: Final = frozenset({0, 99})


def k6_reading(returncode: int, summary: Mapping[str, Any]) -> dict[str, list[float]]:
    """Route -> [p95] from k6's `--summary-export`. A run k6 ended with an exit code other than 0
    or 99 is refused. A route with no samples (`count` 0, or a `p(95)` that is not above 0.0) has
    no reading, so `verdict` fails it by name, never a 0.0 that passes Budget #13 (#2825)."""
    if returncode not in K6_READING_EXITS:
        raise RuntimeError(f"k6 exited {returncode}: the run is invalid, not a reading (#2825)")
    out: dict[str, list[float]] = {}
    for route in requests_plan():
        m = summary.get("metrics", {}).get(f"route_{route}_ms", {})
        p95 = float(m.get("p(95)", 0.0))
        if p95 > 0.0 and m.get("count") != 0:
            out[route] = [p95]
    return out


def drive_k6(duration: str, vus: int) -> dict[str, list[float]]:
    """Full profile: real sockets, k6 load. Returns route -> [p95] (k6 aggregates for us)."""
    import uvicorn

    k6 = shutil.which("k6")
    if k6 is None:
        raise RuntimeError("k6 not on PATH (nightly installs it via grafana/setup-k6-action)")
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    assert_loopback_target(base)
    with tempfile.TemporaryDirectory(prefix="cv-e08q04-") as tmp:
        write_cold_lake(Path(tmp))
        app = asyncio.run(build_app(Path(tmp)))
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        )
        import threading

        th = threading.Thread(target=server.run, daemon=True)
        th.start()
        for _ in range(200):
            if server.started:
                break
            time.sleep(0.05)  # bench process, not a test: wait for the socket to listen
        plan = Path(tmp) / "plan.json"
        plan.write_text(json.dumps(requests_plan()), encoding="utf-8")
        summary = Path(tmp) / "summary.json"
        try:
            ran = subprocess.run(  # noqa: S603 - fixed argv, loopback target asserted above
                [
                    k6,
                    "run",
                    "--quiet",
                    "--summary-export",
                    str(summary),
                    "-e",
                    f"BASE_URL={base}",
                    "-e",
                    f"PLAN={plan}",
                    "-e",
                    f"DURATION={duration}",
                    "-e",
                    f"VUS={vus}",
                    str(K6_SCRIPT),
                ],
                check=False,
                timeout=3600,
            )
            data = json.loads(summary.read_text(encoding="utf-8")) if summary.exists() else {}
        finally:
            server.should_exit = True
            th.join(timeout=10)
    return k6_reading(ran.returncode, data)


def verdict(sc: Scenario, lat: dict[str, list[float]]) -> budgets.Verdict:
    """Budget #13 over every route of `requests_plan()`. A route the driver did not measure (k6
    wrote no `p(95)` for it) fails, named, in every profile: never a 0.0 that passes (#399)."""
    v = budgets.Verdict(sc.name)
    p95 = {r: budgets.percentile(x, 0.95) for r, x in lat.items() if x}
    v.checks.extend(
        budgets.Check(f"rest_measured[{r}]", "#13", 0.0, 1.0, "p95", False, note="no reading")
        for r in sorted(set(requests_plan()) - set(p95))
    )
    v.checks.extend(
        budgets.check_rest(
            p95,
            p95.get("klines_cold", math.nan),
            p95.get("klines_warm", math.nan),
            float(sc.p("min_cache_speedup")),
            budget_hard=sc.profile != "smoke",
        )
    )
    v.metrics = {f"rest_{r}_ms": budgets.summary(x) for r, x in lat.items()}
    return v


async def run_rest(sc: Scenario) -> budgets.Verdict:
    if sc.p("driver") == "k6":
        lat = await asyncio.to_thread(drive_k6, str(sc.p("k6_duration")), int(sc.p("k6_vus")))
    else:
        lat = await drive_inprocess(int(sc.p("iterations")), int(sc.p("concurrency")))
    return verdict(sc, lat)
