"""Scenario 4 drivers: in-process (PR smoke, httpx ASGI transport, no sockets) and k6 (full).

The in-process driver issues the *same* request plan as `tests/load/k6/ingestion_rest.js`
(`fixture_app.requests_plan`), at a bounded concurrency, and records per-route latency. The k6
path starts uvicorn on 127.0.0.1 over the fixture backend, runs k6 with `--summary-export`, and
folds the per-route p95s into the same verdict. Both send the plan's first-read route to a second
app (`build_first_read_app`, #2523). Neither path can reach an exchange host.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
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
    FIRST_READ,
    assert_loopback_target,
    build_app,
    build_first_read_app,
    requests_plan,
    write_cold_lake,
)
from candleviewer.observability.metrics_runtime import unfreeze_startup_heap

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
    """Per-route latencies (ms). `build_app` runs the cold page cache at the app's default bound
    (#2523 lever 5). This driver warms every route untimed, so every timed cold call is a hit,
    but the first-read route (`FIRST_READ`): it goes to `build_first_read_app`'s app, whose page
    cache is off, through a client of its own, and one semaphore bounds the requests to both
    apps (#2523). `drive_k6` has no warm-up: each cold route's first requests, up to one per VU
    (no single-flight), miss inside its reading, which p95 hides but `max` can show."""
    with tempfile.TemporaryDirectory(prefix="cv-e08q04-") as tmp:
        write_cold_lake(Path(tmp))
        apps = await build_app(Path(tmp)), await build_first_read_app(Path(tmp))
        base = "http://127.0.0.1"
        assert_loopback_target(base)
        plan = requests_plan()
        out: dict[str, list[float]] = {k: [] for k in plan}
        sem = asyncio.Semaphore(concurrency)
        peer = ("127.0.0.1", 50000)
        main, first = (
            httpx.AsyncClient(transport=httpx.ASGITransport(app=a, client=peer), base_url=base)
            for a in apps
        )
        async with main, first:
            clients = {r: first if spec.get(FIRST_READ) else main for r, spec in plan.items()}

            async def one(route: str, spec: dict[str, Any]) -> None:
                async with sem:
                    t0 = time.perf_counter()
                    r = await clients[route].get(spec["path"], params=spec["params"])
                    out[route].append((time.perf_counter() - t0) * 1000)
                    if r.status_code != 200:
                        raise RuntimeError(f"{route}: HTTP {r.status_code}")

            for route, spec in plan.items():  # one untimed warm-up per route
                await clients[route].get(spec["path"], params=spec["params"])
            await asyncio.gather(*(one(r, s) for _ in range(iterations) for r, s in plan.items()))
        return out


def _free_ports(n: int) -> list[int]:
    """`n` distinct loopback ports, each free when picked: every socket stays bound until all
    are, so no two come back the same."""
    with contextlib.ExitStack() as held:
        socks = [held.enter_context(socket.socket()) for _ in range(n)]
        for s in socks:
            s.bind(("127.0.0.1", 0))
        return [int(s.getsockname()[1]) for s in socks]


#: k6's exit codes that leave a reading: 0 (passed) and 99 (a threshold crossed). The script arms
#: two kinds of threshold: each route's p95 under Budget #13's 150 ms, which `verdict` judges
#: itself, and `checks` (each response a 200), which `k6_reading` judges: one failed check refuses
#: the run, as the in-process driver refuses a non-200. Any other code is a script, configuration
#: or run error (#2825). The first-read route (`FIRST_READ`) arms no p95 threshold (#2523).
K6_READING_EXITS: Final = frozenset({0, 99})


def k6_reading(returncode: int, text: str) -> dict[str, list[float]]:
    """Route -> [p95] from k6's `--summary-export` text ("" when k6 wrote none). The run is refused
    unless k6 exited 0 or 99 and wrote a readable summary that counts no failed check. The script
    calls `check()` on every response, so a summary with no `checks` count is a changed export
    shape: the run is unknown, never a 0 that passes, schedule or dispatch alike. A 99 must be
    explained by a route's p95 at or over 150 ms; otherwise the `checks` threshold failed. A route
    with no samples (`count` 0, or a `p(95)` not above 0.0) has no reading, so `verdict` fails it
    by name, never a 0.0 that passes (#2825). The first-read route (`FIRST_READ`) arms no p95
    threshold, so it explains no 99 (#2523).
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
    plan = requests_plan()
    out: dict[str, list[float]] = {}
    for route in plan:
        m = metrics.get(f"route_{route}_ms", {})
        p95 = float(m.get("p(95)", 0.0))
        if p95 > 0.0 and m.get("count") != 0:
            out[route] = [p95]
    gated = [p for r, [p] in out.items() if not plan[r].get(FIRST_READ)]
    if returncode == 99 and all(p < budgets.B13_READ_P95_MS for p in gated):
        raise RuntimeError(
            "k6 exited 99 with no route's p95 at or over 150 ms: a check failed (#2825)"
        )
    return out


def drive_k6(duration: str, vus: int) -> dict[str, list[float]]:
    """Full profile: real sockets, k6 load. Returns route -> [p95] (k6 aggregates for us). Where
    `K6_EXPORT_ENV` names a file, k6's summary is copied there unchanged first, also for a run
    refused below; unset, nothing is kept. The first-read route (`FIRST_READ`) has a server of
    its own over `build_first_read_app`, on a second loopback port k6 gets as `BASE_URL_FIRST`
    (#2523); both servers stop on every path.

    Raises `RuntimeError` when k6 is not on PATH, both fixture apps get the same port, either
    does not start, or `k6_reading` refuses the run. Other failures propagate under their own
    types, never as a reading:
    `subprocess.TimeoutExpired` when k6 runs past its hour; `OSError` when the summary cannot be
    read or kept, `UnicodeDecodeError` when it is not UTF-8; `AttributeError` when it parses but
    is not k6's shape (not an object, or a non-object where k6 writes one); `ValueError` or
    `TypeError` when a route's p95 is not a number."""
    import uvicorn

    k6 = shutil.which("k6")
    if k6 is None:
        raise RuntimeError("k6 not on PATH (the full pack's workflow installs the pinned k6)")
    ports = _free_ports(2)
    if ports[0] == ports[1]:  # two servers bound to one port can both report started
        raise RuntimeError(f"both fixture apps were given port {ports[0]}: no reading (#2523)")
    base, base_first = (f"http://127.0.0.1:{p}" for p in ports)
    assert_loopback_target(base)
    assert_loopback_target(base_first)
    with tempfile.TemporaryDirectory(prefix="cv-e08q04-") as tmp:
        write_cold_lake(Path(tmp))
        apps = asyncio.run(build_app(Path(tmp))), asyncio.run(build_first_read_app(Path(tmp)))
        servers = [
            uvicorn.Server(uvicorn.Config(a, host="127.0.0.1", port=p, log_level="warning"))
            for a, p in zip(apps, ports, strict=True)
        ]
        import threading

        threads = [threading.Thread(target=s.run, daemon=True) for s in servers]
        try:
            for th in threads:
                th.start()
            for _ in range(200):
                if all(s.started for s in servers):
                    break
                time.sleep(0.05)  # bench process, not a test: wait for the sockets to listen
            if not all(s.started for s in servers):
                raise RuntimeError("a fixture app did not start: no reading (#2825)")
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
                    f"BASE_URL_FIRST={base_first}",
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
            for s in servers:
                s.should_exit = True
            for th in threads:
                if th.is_alive():
                    th.join(timeout=10)
    return k6_reading(ran.returncode, text)


def verdict(
    sc: Scenario, lat: dict[str, list[float]], *, b13_report_only: bool = False
) -> budgets.Verdict:
    """Budget #13 over every route of `requests_plan()`. A route the driver did not measure (k6
    wrote no `p(95)` for it) fails, named, in every profile: never a 0.0 that passes (#399).
    `b13_report_only` (the weekly run) reports the full profile's 150 ms rows as the smoke does,
    noted `B13_SOFT_WEEKLY`; every other check stays hard (#2825). The cache speed-up is the first
    read's p95 over the warm read's, and the first read's row is reported in every profile, under
    its own note (`budgets.check_rest`, #2523). The first read is the route the plan marks
    `FIRST_READ`, as the drivers send it; a plan that marks no route, or more than one, raises
    `RuntimeError`."""
    weekly = b13_report_only and sc.profile != "smoke"
    plan = requests_plan()
    marked = [r for r, spec in plan.items() if spec.get(FIRST_READ)]
    if len(marked) != 1:
        raise RuntimeError(f"the plan marks {marked} as the first read, not one route (#2523)")
    v = budgets.Verdict(sc.name)
    p95 = {r: budgets.percentile(x, 0.95) for r, x in lat.items() if x}
    v.checks.extend(
        budgets.Check(f"rest_measured[{r}]", "#13", 0.0, 1.0, "p95", False, note="no reading")
        for r in sorted(set(plan) - set(p95))
    )
    v.checks.extend(
        budgets.check_rest(
            p95,
            float(sc.p("min_cache_speedup")),
            first=marked[0],
            repeat="klines_warm",
            budget_hard=sc.profile != "smoke" and not weekly,
        )
    )
    if weekly:  # its soft rows are the 150 ms ones (the speed-up stays hard): say why. The first
        # read's keeps its own note: it is soft on every run, not until slice 2 decides (#2523)
        v.checks = [
            c if c.hard or c.note == budgets.B13_FIRST_READ else replace(c, note=B13_SOFT_WEEKLY)
            for c in v.checks
        ]
    v.metrics = {f"rest_{r}_ms": budgets.summary(x) for r, x in lat.items()}
    return v


async def run_rest(sc: Scenario) -> budgets.Verdict:
    try:
        if sc.p("driver") == "k6":
            lat = await asyncio.to_thread(drive_k6, str(sc.p("k6_duration")), int(sc.p("k6_vus")))
        else:
            lat = await drive_inprocess(int(sc.p("iterations")), int(sc.p("concurrency")))
    finally:
        # #3641: `build_app` froze this process, and `runner all` runs two more scenarios in it
        # (`latency_internal`, `ratelimit_headroom`). Their baselines are of an unfrozen heap, so
        # this run ends with the freeze undone, a failed run too.
        unfreeze_startup_heap()
    v = verdict(sc, lat, b13_report_only=os.environ.get(B13_REPORT_ONLY_ENV) == "1")
    late = [c for c in v.checks if c.note == B13_SOFT_WEEKLY and not c.passed]
    if late:  # a green weekly run still names the budget and its routes over it (#2825)
        over = ", ".join(f"{c.name} {c.measured:.4g} ms" for c in late)
        print(f"::warning::{sc.name}: over Budget #13's 150 ms: {over}; {B13_SOFT_WEEKLY}")
    return v
