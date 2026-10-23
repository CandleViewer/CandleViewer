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
import os
import shutil
import socket
import subprocess
import tempfile
import time
from collections.abc import Mapping
from dataclasses import replace
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
#: Where `drive_k6` keeps k6's `--summary-export` when this is set (the full pack's workflow sets
#: it, into its artifact): k6's own bytes, before `k6_reading` judges them (#2825).
K6_EXPORT_ENV: Final = "CV_BENCH_K6_EXPORT"
#: "1" on the full pack's weekly scheduled run alone (#2825): Budget #13's 150 ms rows are then
#: reported, not gated, until #2825's slice 2 decides the budget, as a known-red weekly job trains
#: everyone to ignore red. Every other check, and a run `k6_reading` refuses, still fail it.
B13_REPORT_ONLY_ENV: Final = "CV_BENCH_B13_REPORT_ONLY"
B13_SOFT_WEEKLY: Final = "reported, not gated, on the weekly run until #2825's slice 2 decides it"


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


#: k6's exit codes that leave a reading: 0 (passed) and 99 (a threshold crossed). The script arms
#: two kinds of threshold: each route's p95 under Budget #13's 150 ms, which `verdict` judges
#: itself, and `checks` (each response a 200), which `k6_reading` judges: one failed check refuses
#: the run, as the in-process driver refuses a non-200. Any other code is a script, configuration
#: or run error (#2825).
K6_READING_EXITS: Final = frozenset({0, 99})


def k6_reading(returncode: int, text: str) -> dict[str, list[float]]:
    """Route -> [p95] from k6's `--summary-export` text ("" when k6 wrote none). The run is refused
    unless k6 exited 0 or 99 and wrote a readable summary that counts no failed check. The script
    calls `check()` on every response, so a summary with no `checks` count is a changed export
    shape: the run is unknown, never a 0 that passes, schedule or dispatch alike. A 99 must be
    explained by a route's p95 at or over 150 ms; otherwise the `checks` threshold failed. A route
    with no samples (`count` 0, or a `p(95)` not above 0.0) has no reading, so `verdict` fails it
    by name, never a 0.0 that passes (#2825).
    """
    if returncode not in K6_READING_EXITS:
        raise RuntimeError(f"k6 exited {returncode}: the run is invalid, not a reading (#2825)")
    if not text:
        raise RuntimeError("k6 wrote no summary: the run is invalid (#2825)")
    try:
        metrics: Mapping[str, Any] = json.loads(text).get("metrics", {})
    except ValueError as exc:
        raise RuntimeError("k6 wrote an unreadable summary: the run is invalid (#2825)") from exc
    fails = metrics.get("checks", {}).get("fails")
    if fails is None:
        raise RuntimeError("k6 wrote no checks count: the run is unknown (#2825)")
    if fails != 0:
        raise RuntimeError(f"k6 counted {fails!r} failed checks: the run is invalid (#2825)")
    out: dict[str, list[float]] = {}
    for route in requests_plan():
        m = metrics.get(f"route_{route}_ms", {})
        p95 = float(m.get("p(95)", 0.0))
        if p95 > 0.0 and m.get("count") != 0:
            out[route] = [p95]
    if returncode == 99 and all(p < budgets.B13_READ_P95_MS for [p] in out.values()):
        raise RuntimeError(
            "k6 exited 99 with no route's p95 at or over 150 ms: a check failed (#2825)"
        )
    return out


def drive_k6(duration: str, vus: int) -> dict[str, list[float]]:
    """Full profile: real sockets, k6 load. Returns route -> [p95] (k6 aggregates for us). Where
    `K6_EXPORT_ENV` names a file, k6's summary is copied there unchanged first, also for a run
    refused below; unset, nothing is kept.

    Raises `RuntimeError` when k6 is not on PATH, the fixture app does not start, or `k6_reading`
    refuses the run. Other failures propagate under their own types, never as a reading:
    `subprocess.TimeoutExpired` when k6 runs past its hour; `OSError` when the summary cannot be
    read or kept, `UnicodeDecodeError` when it is not UTF-8; `AttributeError` when it parses but
    is not k6's shape (not an object, or a non-object where k6 writes one); `ValueError` or
    `TypeError` when a route's p95 is not a number."""
    import uvicorn

    k6 = shutil.which("k6")
    if k6 is None:
        raise RuntimeError("k6 not on PATH (the full pack's workflow installs the pinned k6)")
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
        try:
            for _ in range(200):
                if server.started:
                    break
                time.sleep(0.05)  # bench process, not a test: wait for the socket to listen
            if not server.started:
                raise RuntimeError("the fixture app did not start: no reading (#2825)")
            plan = Path(tmp) / "plan.json"
            plan.write_text(json.dumps(requests_plan()), encoding="utf-8")
            summary = Path(tmp) / "summary.json"
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
            keep = os.environ.get(K6_EXPORT_ENV)
            if keep and summary.exists():  # the evidence of a run, before anything judges it
                Path(keep).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(summary, keep)
            text = summary.read_text(encoding="utf-8") if summary.exists() else ""
        finally:
            server.should_exit = True
            th.join(timeout=10)
    return k6_reading(ran.returncode, text)


def verdict(
    sc: Scenario, lat: dict[str, list[float]], *, b13_report_only: bool = False
) -> budgets.Verdict:
    """Budget #13 over every route of `requests_plan()`. A route the driver did not measure (k6
    wrote no `p(95)` for it) fails, named, in every profile: never a 0.0 that passes (#399).
    `b13_report_only` (the weekly run) reports the full profile's 150 ms rows as the smoke does,
    noted `B13_SOFT_WEEKLY`; every other check stays hard (#2825)."""
    weekly = b13_report_only and sc.profile != "smoke"
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
            budget_hard=sc.profile != "smoke" and not weekly,
        )
    )
    if weekly:  # its soft rows are the 150 ms ones (the speed-up stays hard): say why
        v.checks = [c if c.hard else replace(c, note=B13_SOFT_WEEKLY) for c in v.checks]
    v.metrics = {f"rest_{r}_ms": budgets.summary(x) for r, x in lat.items()}
    return v


async def run_rest(sc: Scenario) -> budgets.Verdict:
    if sc.p("driver") == "k6":
        lat = await asyncio.to_thread(drive_k6, str(sc.p("k6_duration")), int(sc.p("k6_vus")))
    else:
        lat = await drive_inprocess(int(sc.p("iterations")), int(sc.p("concurrency")))
    v = verdict(sc, lat, b13_report_only=os.environ.get(B13_REPORT_ONLY_ENV) == "1")
    late = [c for c in v.checks if c.note == B13_SOFT_WEEKLY and not c.passed]
    if late:  # a green weekly run still names the budget and its routes over it (#2825)
        over = ", ".join(f"{c.name} {c.measured:.4g} ms" for c in late)
        print(f"::warning::{sc.name}: over Budget #13's 150 ms: {over}; {B13_SOFT_WEEKLY}")
    return v
