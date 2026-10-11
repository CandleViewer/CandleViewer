"""Scenario 4 drivers: in-process (PR smoke, httpx ASGI transport, no sockets) and k6 (full).

The in-process driver issues the *same* request plan as `tests/load/k6/ingestion_rest.js`
(`fixture_app.requests_plan`), at a bounded concurrency, and records per-route latency. The k6
path starts uvicorn on 127.0.0.1 over the fixture backend, runs k6 with `--summary-export`, and
folds the per-route p95s into the same verdict. Neither path can reach an exchange host.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import socket
import subprocess  # noqa: S404 - runs the pinned k6 binary against a loopback fixture app only
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

from bench.ingestion import budgets
from bench.ingestion.config import Scenario
from bench.ingestion.fixture_app import assert_loopback_target, build_app, requests_plan, write_cold_lake

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

            for route, spec in requests_plan().items():  # one untimed warm-up per route
                await client.get(spec["path"], params=spec["params"])
            await asyncio.gather(
                *(one(r, s) for _ in range(iterations) for r, s in requests_plan().items())
            )
        return out


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


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
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
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
            subprocess.run(  # noqa: S603 - fixed argv, loopback target asserted above
                [k6, "run", "--quiet", "--summary-export", str(summary), "-e", f"BASE_URL={base}",
                 "-e", f"PLAN={plan}", "-e", f"DURATION={duration}", "-e", f"VUS={vus}", str(K6_SCRIPT)],
                check=False, timeout=3600,
            )  # fmt: skip
            data = json.loads(summary.read_text(encoding="utf-8"))
        finally:
            server.should_exit = True
            th.join(timeout=10)
    out: dict[str, list[float]] = {}
    for route in requests_plan():
        m = data.get("metrics", {}).get(f"route_{route}_ms", {})
        if "p(95)" in m:
            out[route] = [float(m["p(95)"])]
    return out


def verdict(sc: Scenario, lat: dict[str, list[float]]) -> budgets.Verdict:
    v = budgets.Verdict(sc.name)
    p95 = {r: budgets.percentile(x, 0.95) for r, x in lat.items() if x}
    v.checks.extend(
        budgets.check_rest(
            {r: p for r, p in p95.items() if r != "klines_cold"} | {"klines_cold": p95.get("klines_cold", 0.0)},
            p95.get("klines_cold", 0.0), p95.get("klines_warm", 0.0), float(sc.p("min_cache_speedup")),
        )  # fmt: skip
    )
    v.metrics = {f"rest_{r}_ms": budgets.summary(x) for r, x in lat.items()}
    return v


async def run_rest(sc: Scenario) -> budgets.Verdict:
    if sc.p("driver") == "k6":
        lat = await asyncio.to_thread(drive_k6, str(sc.p("k6_duration")), int(sc.p("k6_vus")))
    else:
        lat = await drive_inprocess(int(sc.p("iterations")), int(sc.p("concurrency")))
    return verdict(sc, lat)
