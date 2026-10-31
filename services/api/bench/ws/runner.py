"""E17-Q03 runner: one profile run, the self-check, the W5 phases, the reproducibility check.

    export K6_BIN=<absolute path of the pinned k6 v2.3.0>   # run, selfcheck and w5 start it
    uv run python -m bench.ws.runner run A --out-dir DIR [--staging]
    uv run python -m bench.ws.runner run A --ws-path /api/v1/ws   # k6 on the prefixed path
    uv run python -m bench.ws.runner run smoke --duration-s 120 --warmup-s 20
    uv run python -m bench.ws.runner selfcheck [--duration-s 180]
    uv run python -m bench.ws.runner w5 --out-dir DIR
    uv run python -m bench.ws.runner w5-judge DIR         # re-judge a saved W5 directory, offline
    uv run python -m bench.ws.runner judge DIR            # re-judge a saved run
    uv run python -m bench.ws.runner gate DIR DIR DIR     # C-13.9: 5 % on the median of 3 runs
    uv run python -m bench.ws.runner repro DIR_A DIR_B    # AC 5: within 15 %, or a named source
    uv run python -m bench.ws.runner record DIR           # a PASS run's baseline (refused under CI)
    uv run python -m bench.ws.runner run A --instrumentation off   # #571: the uninstrumented half
    uv run python -m bench.ws.runner overhead ON_DIR OFF_DIR      # #571: E17-T06's cost, one pair

A run: the backend (`fixture_app`) boots on 127.0.0.1 with its tokens; the runner fixes an absolute
timeline (warm-up ends and the run ends at the same instant on every k6 VU), scrapes `/metrics` at
steady-start (t0), every 60 s and at the end (t1), and runs k6 from `K6_BIN`, the absolute path of
the pinned version, never taken from PATH. The verdict (`budgets.evaluate`) reads the k6 summary
and the t1 - t0 deltas. A scrape the backend leaves unanswered for 15 s is a finding, not a crash:
it is counted (`run.json` `scrapes`), the run goes on and the verdict FAILs on
`scrape.metrics_timeout`, even when a guard trips too (one unanswered 15 s window explains both;
the guard stays listed); a lost t0 or t1 is retried once, and the deltas are not judged if it
stays lost. Exit 0 pass, 1 a budget missed (named), 2 INVALID (a validity guard tripped, named).
`duration_s` is the steady window; warm-up comes before it. A single run only warns about a
regression against its baseline: the gate fails on the median of 3 runs (`gate`).

`--staging` reproduces the VPS-class profile on a larger machine: the backend in a systemd user
scope (`CPUQuota=400%`, `MemoryMax=8G`, no swap) on cpuset 0-7, k6 on 8-15, so they never share
a CPU (`--backend-cpus` and `--k6-cpus` set the cpusets alone, as on a 4 vCPU runner). It is not
a VPS: one asyncio loop is bound by single-core speed, which a laptop core beats, and the report
says so. k6 never phones home (`K6_NO_USAGE_REPORT=true`, no extension resolution).

`--feeder proc` runs the bench feeder in a child of the backend (`bench.ws.feed_proc`, #571) so
the backend CPU is the gateway's alone; the child runs on `--feeder-cpus`, by default k6's cpuset
(never the backend's), and inside the backend's systemd scope, so under `--staging` it shares the
scope's CPU quota. Its CPU is reported apart (`feeder_cpu_cores`) and taken out of the co-tenant
figure. `feeder` is in `run.json` and in a baseline, and runs or baselines of another mode are
never compared (an artefact that records none is `inproc`, the only mode there was).

`run --instrumentation off` (#571) serves the same build with E17-T06's hot-path series stood in
by no-ops (`bench.ws.instrumentation`): such a run is judged in overhead mode (budget #6 is not
measured, so it is never INVALID for its missing samples), is never a baseline nor gated against
one, and `instrumentation` is in `run.json`, the baseline name and every comparability check (an
artefact that records none is `on`, as every run was). `overhead ON_DIR OFF_DIR` compares one run
of each that differ in nothing else: backend CPU, k6 tick-to-decode and the loop lag, each as an
on/off delta, and the CPU's against the 2 % line (`overhead.json`, `overhead.md`).
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import platform
import re
import select
import shutil
import stat
import statistics
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bench.ingestion import gate
from bench.ingestion.budgets import Verdict
from bench.ingestion.config import machine_profile
from bench.ingestion.report import redact
from bench.ws import HARNESS_VERSION, LOOP, READY, budgets, profiles, w5
from bench.ws import instrumentation as instr
from bench.ws.budgets import Facts, Result, Scrape, ScrapeTally

K6_VERSION = "v2.3.0"
HERE = Path(__file__).resolve().parent
API = HERE.parents[1]
LOAD = HERE.parents[3] / "tests" / "load" / "ws"
VECTORS = HERE.parents[3] / "packages" / "fixtures" / "golden" / "cvwb" / "vectors.json"
BASELINES = HERE.parent / "baselines" / "e17"
SCOPE = ("-p", "CPUQuota=400%", "-p", "MemoryMax=8G", "-p", "MemorySwapMax=0", "-p", "TasksMax=512")
STAGING = {"backend": "0-7", "k6": "8-15", "label": "4cpu-8g"}
MEM_MAX = 8 << 30
#: What k6 needs to start before its first VU connects, plus this much per VU.
SLACK_S, SLACK_PER_VU_S = 8.0, 0.05
SCRAPE_EVERY_S = 60.0
SCRAPE_TIMEOUT_S = 15.0  # how long a scrape waits for the backend before it counts as a timeout
BOUNDARY_RETRY_S = 5.0  # the wait before a boundary scrape (`t0`, `t1`) is tried once more
MAX_SCRAPE_BYTES = 8 << 20  # a scrape is about 60 KB; this is a cap, not a size
TOLERANCE = (
    0.05  # C-13.9, 06 7.4: over 5 % on the median of 3 runs fails (--tolerance 0.10: the ticket's)
)
MIN_GATE_RUNS = 3
#: A source of variance between two runs of a profile: CPU the machine spent outside the run, in
#: cores, or a k6 client that lagged.
VARIANCE_OTHER_CORES, VARIANCE_CLIENT_LAG_MS = 1.0, 10.0
START_TIMEOUT_S = 90.0
#: What a run directory held from an earlier run that a judge could read as this one's.
STALE = (
    *("summary.json", "scrape0.txt", "scrape1.txt", "series.jsonl", "run.json"),
    *("result.json", "report.md"),
)
#: Written into a run directory by the runner that made it: a directory without it is not the
#: harness's to clear, whatever it holds.
MARKER = ".cv-bench-ws-run"
OVERRIDES = (
    "duration_s",
    "warmup_s",
    "rtt_delay_ms",
    "reauth_after_s",
    "probe_every_s",
    "send_delay_ms",
)
#: The feeder modes (`fixture_app.FEEDERS`), and the one an artefact without `feeder` ran.
FEEDERS, LEGACY_FEEDER = ("inproc", "proc"), "inproc"
FEEDER_CPU = "cv_bench_feeder_cpu_seconds_total"
#: #571's DoD line: E17-T06's instrumentation costs under this share of the backend CPU.
OVERHEAD_LINE_PCT = 2.0
#: Must match between the two runs of an overhead pair, beyond what `comparable` checks: the same
#: cpusets and scope, so the CPU and the latency are of one placement.
PAIR_KEYS = ("cpus", "cgroup", "staging", "feeder_cpus")
NOT_INSTRUMENTED = (
    "instrumentation off (overhead mode): only an instrumented run becomes a baseline"
)


def get(port: int, path: str) -> str:
    """One GET on the loopback backend (the only host a run talks to)."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=SCRAPE_TIMEOUT_S)
    try:
        conn.request("GET", path)
        return conn.getresponse().read(MAX_SCRAPE_BYTES).decode()
    finally:
        conn.close()


def k6_binary() -> str:
    path = os.environ.get("K6_BIN")
    if not path:
        raise SystemExit("set K6_BIN to the pinned k6 binary: it is never taken from PATH")
    binary = Path(path)
    if not binary.is_absolute():
        raise SystemExit(
            f"K6_BIN={path!r} is not an absolute path: k6 is never found through PATH or the cwd"
        )
    try:  # stat, not Path.is_file(): from Python 3.13 that is False for every OSError
        st = binary.stat()
        is_file, runnable = stat.S_ISREG(st.st_mode), os.access(binary, os.X_OK)
    except (FileNotFoundError, NotADirectoryError):
        is_file = runnable = False  # nothing there, or a file where a directory should be
    except OSError as exc:  # a parent that cannot be searched, a name too long, a link loop
        raise SystemExit(f"K6_BIN={path!r} cannot be checked: {exc.strerror or exc}") from None
    if not is_file:
        raise SystemExit(f"K6_BIN={path!r} is not a regular file")
    if not runnable:
        raise SystemExit(f"K6_BIN={path!r} is not executable")
    argv0 = os.fspath(binary)  # the path the checks saw (`Path` drops a trailing slash): run that
    # Semgrep (CI-SEC-001) reads argv[0], the operator's own K6_BIN, as environment data. It is an
    # absolute, executable regular file by now, never found on PATH, run with a fixed argv and then
    # held to the pinned version (the perf workflow installs it by sha256 first): the marker below
    # records that, as Semgrep cannot see any of it.
    try:
        out = subprocess.run(  # noqa: S603 - the operator's own binary, fixed argv
            # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-tainted-env-args.dangerous-subprocess-use-tainted-env-args reason=bench-only-operator-env-k6-path-fixed-argv owner=@CandleViewer/security review=2027-03-25  # noqa: E501 - semgrep marker format is fixed
            [argv0, "version"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
            env=_env(),
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:  # cannot start, exits non-zero, too slow
        raise SystemExit(f"K6_BIN={path!r} cannot be run: {exc}") from None
    if f"k6 {K6_VERSION} " not in out:
        raise SystemExit(f"{out.strip()!r}: this harness is pinned to k6 {K6_VERSION}")
    return argv0


def _env(*, debug: bool = False) -> dict[str, str]:
    env = {**os.environ, "K6_NO_USAGE_REPORT": "true", "K6_AUTO_EXTENSION_RESOLUTION": "false"}
    return env | {"CV_LOG_LEVEL": "debug"} if debug else env


def _cpus(spec: str) -> int:
    parts = [p.partition("-") for p in spec.split(",")]
    return sum(int(b) - int(a) + 1 if sep else 1 for a, sep, b in parts)


def _proc_cpu_s(pid: int) -> float:
    fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()
    return (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")


def _cgroup(pid: int) -> Path | None:
    for line in Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8").splitlines():
        if line.startswith("0::"):
            path = Path("/sys/fs/cgroup") / line[4:].lstrip("/")
            return path if path.is_dir() else None
    return None


def _cgroup_count(cg: Path | None, name: str, key: str) -> int:
    try:
        text = (cg / name).read_text(encoding="utf-8") if cg else ""
    except OSError:
        return 0
    m = re.search(rf"^{key} (\d+)$", text, re.MULTILINE)
    return int(m.group(1)) if m else 0


def _cpu_model() -> str:
    for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
        if line.startswith("model name"):
            return line.partition(":")[2].strip()
    return platform.processor() or "unknown"


def _commit() -> str:
    git = shutil.which("git") or "git"
    argv = [git, "rev-parse", "HEAD"]
    done = subprocess.run(argv, capture_output=True, text=True, check=False, cwd=HERE)  # noqa: S603
    return done.stdout.strip()


@dataclass(slots=True)
class Plan:
    profile: str  # the key in profiles.json the backend and k6 resolve
    prof: dict[str, Any]  # that profile with this run's overrides applied
    out: Path
    staging: bool
    seed: int
    backend_cpus: str | None = None
    k6_cpus: str | None = None
    trace_sp: bool = False
    #: The profile's own steady window and warm-up, before the run's overrides: a run shorter than
    #: these is not the profile (`run_profile`).
    nominal_duration_s: float = 0.0
    nominal_warmup_s: float = 0.0
    feeder: str = "inproc"
    feeder_cpus: str | None = None  # the child's cpuset under `--feeder proc`
    instrumentation: str = "on"  # `instr.MODES`; off: E17-T06's series stood in (#571)

    @property
    def duration_s(self) -> float:
        return float(self.prof["duration_s"])


def plan(
    table: dict[str, Any], a: argparse.Namespace, profile: str, out: Path, **over: Any
) -> Plan:
    nominal = profiles.resolve(table, profile) | over  # the table's, and a phase's own, values
    prof = nominal | {k: getattr(a, k) for k in OVERRIDES if getattr(a, k, None) is not None}
    prof["name"] = profile
    if getattr(a, "gate_on", None):
        prof["gate_on"] = a.gate_on
    if getattr(a, "ws_path", None):
        prof["ws_path"] = profiles.ws_path(a.ws_path)
    backend = a.backend_cpus or (STAGING["backend"] if a.staging else None)
    k6 = a.k6_cpus or (STAGING["k6"] if a.staging else None)
    feeder = getattr(a, "feeder", None) or "inproc"
    if feeder not in FEEDERS:
        raise ValueError(f"feeder {feeder!r}: one of {', '.join(FEEDERS)}")
    # the child keeps off the backend's cpus: on k6's unless told otherwise
    feeder_cpus = (getattr(a, "feeder_cpus", None) or k6) if feeder == "proc" else None
    if feeder == "proc" and backend and not feeder_cpus:
        # the child inherits the backend's affinity: the backend's own cpus, which the child must
        # not share (as k6 is kept off them); the runner refuses what it cannot record truthfully
        print(
            f"::error::--feeder proc: the backend is pinned to cpus {backend} and the child would "
            "inherit them: give it its own with --feeder-cpus (or --k6-cpus, or --staging)"
        )
        raise SystemExit(2)
    mode = getattr(a, "instrumentation", None) or instr.LEGACY  # selfcheck and w5: always on
    if mode not in instr.MODES:
        raise ValueError(f"instrumentation {mode!r}: one of {', '.join(instr.MODES)}")
    if mode == "off" and a.trace_sp:
        print("::error::--trace-sp with --instrumentation off: no frame carries an sp to trace")
        raise SystemExit(2)
    return Plan(
        profile, prof, out, a.staging, a.seed, backend, k6, a.trace_sp,
        float(nominal["duration_s"]), float(nominal["warmup_s"]), feeder, feeder_cpus, mode,
    )  # fmt: skip


def _stop(proc: subprocess.Popen[Any], wait_s: float = 30.0) -> None:
    """End a process this runner started: SIGTERM to its one pid (never a pattern), SIGKILL when it
    is still there after `wait_s`, and always reaped."""
    if proc.poll() is None:
        proc.terminate()
    try:
        proc.wait(timeout=wait_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    for pipe in (proc.stdout, proc.stderr):  # the ready line's pipe, left open, is a leaked handle
        if pipe is not None:
            pipe.close()


def _fresh(out: Path) -> None:
    """An empty slate for a run in `out`: nothing an earlier run left is judged as this one's.
    It takes only a directory the harness made: an empty one, or one with our marker, a regular
    file as a run writes it. Any other (`--out-dir candleviewer` holds a `bars/`) is refused and
    nothing in it is touched. No step follows a link inside it: a link is an entry, and the clear
    removes the link, never what it points at."""
    out.mkdir(parents=True, exist_ok=True)
    marker = out / MARKER
    held = sorted(entry.name for entry in out.iterdir())
    if held and not (marker.is_file() and not marker.is_symlink()):
        shown = ", ".join(held[:3]) + (", ..." if len(held) > 3 else "")
        raise SystemExit(
            f"{out} was not made by this harness (no {MARKER} file) and holds {shown}: "
            "use an empty --out-dir; nothing was deleted"
        )
    for name in (*STALE, "bars"):
        path = out / name
        if name == "bars" and path.is_dir() and not path.is_symlink():
            shutil.rmtree(path, ignore_errors=True)  # the next backend would restore its state
        else:
            path.unlink(missing_ok=True)  # a directory named like a run file fails here, as before
    marker.write_text(f"{HARNESS_VERSION}\n", encoding="utf-8")


def start_backend(p: Plan) -> tuple[subprocess.Popen[str], int, int]:
    argv = [
        sys.executable,
        "-m",
        "bench.ws.fixture_app",
        "--profile",
        p.profile,
        "--seed",
        str(p.seed),
        "--out",
        str(p.out),
        "--send-delay-ms",
        str(int(p.prof.get("send_delay_ms", 0))),
        "--ws-path",
        str(p.prof["ws_path"]),
        "--instrumentation",
        p.instrumentation,
        "--feeder",
        p.feeder,
    ]
    if p.feeder_cpus:
        argv += ["--feeder-cpus", p.feeder_cpus]
    if p.backend_cpus:
        argv = ["taskset", "-c", p.backend_cpus, *argv]
    if p.staging:
        argv = ["systemd-run", "--user", "--scope", "--quiet", *SCOPE, "--", *argv]
    p.out.mkdir(parents=True, exist_ok=True)
    with (p.out / "backend.err").open("w") as err:  # the child keeps its own copy of the descriptor
        proc = subprocess.Popen(  # noqa: S603 - fixed argv; the backend binds loopback only
            argv, cwd=API, env=_env(debug=p.trace_sp), stdout=subprocess.PIPE, stderr=err, text=True
        )
    try:
        deadline = time.monotonic() + START_TIMEOUT_S
        while time.monotonic() < deadline and proc.poll() is None and proc.stdout is not None:
            if select.select([proc.stdout], [], [], 0.5)[0]:
                line = proc.stdout.readline()
                if line.startswith(READY):
                    kv = dict(x.split("=", 1) for x in line.split()[1:])
                    return proc, int(kv["port"]), int(kv["pid"])
    except BaseException:
        _stop(proc)
        raise
    code = proc.poll()
    _stop(proc)  # a backend that is slow or wedged must not outlive the runner
    raise SystemExit(f"the backend did not become ready (exit {code}); see {p.out}/backend.err")


def _sample(text: str) -> dict[str, float]:
    s = budgets.parse_scrape(text)
    return {
        "rss": budgets.total(s, "process_resident_memory_bytes"),
        "cpu_s": budgets.total(s, "process_cpu_seconds_total"),
        "connections": budgets.total(s, "cv_ws_connections_in_use"),
    }


def _ask(port: int) -> tuple[str | None, int]:
    """One `/metrics` request: its text, or `None` and the ms it waited when it timed out."""
    began = time.monotonic()
    try:
        return get(port, "/metrics"), 0
    except TimeoutError:  # `socket.timeout` is the same class since Python 3.10
        return None, round((time.monotonic() - began) * 1000)


def scrape(port: int, tally: ScrapeTally, boundary: str | None = None) -> str | None:
    """One steady-state scrape, counted once in `tally`: `None` when it timed out, and how long it
    waited is kept. A boundary scrape (`boundary` is `t0` or `t1`: the counter deltas read both) is
    tried once more after `BOUNDARY_RETRY_S`: named in `tally.missing` if that times out too (its
    wait is added), in `tally.retried` if it answers. It still counts as a timeout when the retry
    answers: the silence is the finding, the retry only saves the data. Only a timeout is caught. A
    reset or refused connection is no 15 s silence (a closed socket, a dead listener) and would make
    the budget's message false, so it still ends the run as before."""
    tally.attempted += 1
    text, waited = _ask(port)
    if text is None:
        if boundary:
            time.sleep(BOUNDARY_RETRY_S)
            text, again = _ask(port)
            waited += again  # a retry that timed out waited too: the silence is both
            (tally.retried if text is not None else tally.missing).append(boundary)
        tally.timed_out_ms.append(waited)
    return text


def scrape_sample(port: int, tally: ScrapeTally) -> dict[str, float]:
    """A periodic scrape as a series sample: the backend's numbers, or how long it waited."""
    text = scrape(port, tally)
    return _sample(text) if text is not None else {"scrape_timeout_ms": tally.timed_out_ms[-1]}


def _busy_s(stat: str) -> float:
    """CPU seconds the whole machine has spent busy, from the first line of `/proc/stat` (user,
    nice, system, irq, softirq and steal: not idle, not iowait; guest time is inside user)."""
    v = [int(x) for x in stat.splitlines()[0].split()[1:9]]
    return (sum(v[0:3]) + sum(v[5:8])) / os.sysconf("SC_CLK_TCK")


def _other_cores(busy_s: float, wall_s: float, ours: Sequence[float]) -> float:
    """CPU the machine spent on anything but this run, in cores: its busy time over `wall_s` less
    what the backend and k6 used (core-seconds per second each). Never below zero."""
    return max(0.0, busy_s / wall_s - sum(ours)) if wall_s > 0 else 0.0


def k6_env(p: Plan, port: int, steady_at: float, end_at: float) -> dict[str, Any]:
    """What k6 is told through `-e`: the target, the profile and its overrides, the timeline."""
    return {
        "PORT": port,
        "PROFILE": p.profile,
        "PROFILES": profiles.PROFILES,
        "TOKENS": p.out / "tokens.json",
        "VECTORS": VECTORS,
        "STEADY_AT_MS": int(steady_at * 1000),
        "END_AT_MS": int(end_at * 1000),
        "SUMMARY": p.out / "summary.json",
        "RTT_DELAY_MS": int(p.prof["rtt_delay_ms"]),
        "FAMILIES": ",".join(p.prof["families"]),
        "REAUTH_AFTER_S": int(p.prof.get("reauth_after_s") or 0),
        "PROBE_EVERY_S": int(p.prof["probe_every_s"]),
        "TRACE_SP": int(p.trace_sp),
        "WS_PATH": p.prof["ws_path"],
    }


def execute(p: Plan, k6: str) -> Path:
    """Run the backend and k6 for `p` and write the artefacts (the verdict is `judge`'s)."""
    _fresh(p.out)
    backend, port, pid = start_backend(p)
    kproc: subprocess.Popen[bytes] | None = None
    t0 = t1 = None
    series: list[dict[str, float]] = []
    scrapes = ScrapeTally(SCRAPE_TIMEOUT_S)
    k6cpu: dict[str, tuple[float, float]] = {}  # (cpu seconds, when), the run's first and last
    stat: dict[str, tuple[float, float]] = {}  # (machine busy seconds, when) at t0 and at t1
    try:
        cg = _cgroup(pid)
        n_vus = int(p.prof["users"]) * int(p.prof["connections"]) + int(bool(p.prof.get("probe")))
        steady_at = time.time() + SLACK_S + SLACK_PER_VU_S * n_vus + float(p.prof["warmup_s"])
        end_at = steady_at + p.duration_s
        env = k6_env(p, port, steady_at, end_at)
        argv = [k6, "run", "--quiet", "--no-usage-report"]
        argv += [x for k, v in env.items() for x in ("-e", f"{k}={v}")]
        argv.append(str(LOAD / "ws_load.js"))
        if p.k6_cpus:
            argv = ["taskset", "-c", p.k6_cpus, *argv]
        with (p.out / "k6.out").open("w") as out, (p.out / "k6.err").open("w") as err:
            # the pinned k6, aimed at the loopback backend
            kproc = subprocess.Popen(argv, env=_env(), stdout=out, stderr=err)  # noqa: S603
        next_periodic = steady_at + SCRAPE_EVERY_S
        throttled0 = _cgroup_count(cg, "cpu.stat", "nr_throttled")
        while True:
            now = time.time()
            if t0 is None and now >= steady_at and kproc.poll() is None:
                t0 = scrape(port, scrapes, "t0") or ""
                now = time.time()  # a scrape that waited has ended: both CPU samples are of now
                k6cpu["0"] = (_proc_cpu_s(kproc.pid), now)
                stat["0"] = (_busy_s(Path("/proc/stat").read_text()), now)
            if t0 is not None and t1 is None and now >= next_periodic:
                series.append({"t": now - steady_at} | scrape_sample(port, scrapes))
                next_periodic += SCRAPE_EVERY_S
            if "1" not in k6cpu and t0 is not None and now >= end_at - 1.5 and kproc.poll() is None:
                k6cpu["1"] = (_proc_cpu_s(kproc.pid), now)  # k6 is gone by t1: read it just before
            if t1 is None and t0 is not None and now >= end_at + 1.0:
                t1 = scrape(port, scrapes, "t1") or ""
                stat["1"] = (_busy_s(Path("/proc/stat").read_text()), time.time())  # after the wait
            if kproc.poll() is not None and (t1 is not None or t0 is None):
                break
            time.sleep(0.25)
        kproc.wait(timeout=120)
    finally:
        for proc, wait_s in ((kproc, 30.0), (backend, 60.0)):
            if proc is not None:
                _stop(proc, wait_s)  # one pid we started; never a pattern kill
    (p.out / "scrape0.txt").write_text(t0 or "", encoding="utf-8")
    (p.out / "scrape1.txt").write_text(t1 or "", encoding="utf-8")
    (p.out / "series.jsonl").write_text(
        "".join(json.dumps(x) + "\n" for x in series), encoding="utf-8"
    )
    cpus = _cpus(p.k6_cpus) if p.k6_cpus else os.cpu_count() or 1
    other: float | None = None  # null when not read (a lost boundary): never 0.0
    actual: float | None = None  # t0 to t1 as answered; none when a boundary was lost
    feeder_cores: float | None = None  # the child's CPU (`--feeder proc`), in cores
    if len(stat) == 2 and not scrapes.missing:
        actual = stat["1"][1] - stat["0"][1]
        if p.feeder == "proc" and actual > 0:
            d = budgets.delta(budgets.parse_scrape(t0 or ""), budgets.parse_scrape(t1 or ""))
            feeder_cores = budgets.total(d, FEEDER_CPU) / actual
    if len(stat) == len(k6cpu) == 2 and not scrapes.missing:  # busy CPU less backend, k6, feeder
        (busy0, w0), (busy1, w1) = stat["0"], stat["1"]
        (c0, u0), (c1, u1) = k6cpu["0"], k6cpu["1"]
        if w1 > w0 and u1 > u0:
            d = budgets.delta(budgets.parse_scrape(t0 or ""), budgets.parse_scrape(t1 or ""))
            backend_rate = budgets.total(d, "process_cpu_seconds_total") / (w1 - w0)
            ours = [backend_rate, (c1 - c0) / (u1 - u0)]
            ours += [budgets.total(d, FEEDER_CPU) / (w1 - w0)] if p.feeder == "proc" else []
            other = _other_cores(busy1 - busy0, w1 - w0, ours)
    facts = {
        "harness": HARNESS_VERSION,
        "profile": p.profile,
        "resolved": p.prof,
        # #2409: every run is on the outbound pipeline, so "on"; the key stays so that a run
        # matches the baselines and reports recorded while the backpressure flag existed.
        "flag": "on",
        "steady_s": p.duration_s,
        "steady_actual_s": actual,
        "warmup_s": float(p.prof["warmup_s"]),
        "profile_duration_s": p.nominal_duration_s,
        "profile_warmup_s": p.nominal_warmup_s,
        "k6_exit": kproc.returncode,
        "k6_version": K6_VERSION,
        "staging": p.staging,
        "cpus": [p.backend_cpus, p.k6_cpus],
        "cgroup": STAGING["label"] if p.staging else "none",
        "loop": LOOP,
        "feeder": p.feeder,
        "feeder_cpus": p.feeder_cpus,
        "feeder_cpu_cores": feeder_cores,
        "instrumentation": p.instrumentation,
        # true by construction: the runner starts both, and ws_load.js refuses non-loopback
        "same_host": True,
        "scrapes": asdict(scrapes),
        "k6_cpu_frac": _cpu_frac(k6cpu, cpus),
        "rss_bytes": int(max((x["rss"] for x in series if "rss" in x), default=0)) or None,
        "mem_max_bytes": MEM_MAX if p.staging else None,
        "oom_events": _cgroup_count(cg, "memory.events", "oom_kill"),
        "commit": _commit(),
        "cpu_model": _cpu_model(),
        "kernel": platform.release(),
        "machine_profile": machine_profile() + (f"+{STAGING['label']}" if p.staging else ""),
        "variance": {
            "nr_throttled": _cgroup_count(cg, "cpu.stat", "nr_throttled") - throttled0,
            "other_cores": other,
        },
        "finished": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    (p.out / "run.json").write_text(json.dumps(facts, indent=2) + "\n", encoding="utf-8")
    return p.out


def _cpu_frac(k6cpu: Mapping[str, tuple[float, float]], cpus: int) -> float | None:
    """k6's CPU over its cpuset between the two samples; `None` when it was not sampled twice."""
    if "0" not in k6cpu or "1" not in k6cpu:
        return None
    (c0, t0), (c1, t1) = k6cpu["0"], k6cpu["1"]
    return (c1 - c0) / ((t1 - t0) * cpus) if t1 > t0 else None


def load_run(out: Path) -> tuple[dict[str, Any], dict[str, Any], Scrape, Scrape]:
    facts = json.loads((out / "run.json").read_text(encoding="utf-8"))
    path = out / "summary.json"
    summ = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    t0 = budgets.parse_scrape((out / "scrape0.txt").read_text(encoding="utf-8"))
    return facts, summ, t0, budgets.parse_scrape((out / "scrape1.txt").read_text(encoding="utf-8"))


def judge(out: Path) -> tuple[Result, dict[str, Any]]:
    """The verdict of a saved run: artefacts only, no clock and no process."""
    facts, summ, t0, t1 = load_run(out)
    scrapes = ScrapeTally(**facts["scrapes"]) if "scrapes" in facts else None
    cpu_s = budgets.total(budgets.delta(t0, t1), "process_cpu_seconds_total") or None
    run = Facts(
        facts["steady_s"],
        facts["k6_cpu_frac"],
        facts["rss_bytes"],
        facts["mem_max_bytes"],
        facts["oom_events"],
        cpu_s,
        scrapes,
        facts.get("steady_actual_s"),
    )
    judged = {"flag": facts["flag"], "instrumentation": instrumentation_of(facts)}
    res = budgets.evaluate(facts["resolved"] | judged, summ, t0, t1, run)
    if not summ:
        res.invalid.append("no_k6_summary: k6 wrote none")
    if facts["k6_exit"] not in (
        0,
        99,
    ):  # 99: k6's own thresholds crossed, which the verdict reads for itself
        res.invalid.append(f"k6_exit: {facts['k6_exit']}")
    lag = (summ.get("trends", {}).get("cv_client_lag_ms") or {}).get("p95")
    return res, facts | {"client_lag_p95_ms": lag}


def baseline_name(facts: Mapping[str, Any]) -> str:
    mode = "-proc" if feeder_of(facts) == "proc" else ""  # inproc keeps the names it always had
    off = "-instr-off" if instrumentation_of(facts) == "off" else ""  # never recorded: a guard
    return str(facts["profile"]) + ("" if facts["flag"] == "on" else "-flag-off") + mode + off


def run_profile(facts: Mapping[str, Any]) -> str:
    """`full` for a run as long as its profile asks, steady window and warm-up alike; a shorter one
    (`--duration-s`, `--warmup-s`, the workflow's `duration_s`) is `smoke`, which the baseline gate
    never compares with a full baseline (`gate.compare`). Measured against the profile's own table
    values, not against the overridden ones the run used."""
    unknown = float("inf")  # artefacts that do not say how long their profile is are never `full`
    long_enough = facts["steady_s"] >= facts.get("profile_duration_s", unknown) and facts[
        "warmup_s"
    ] >= facts.get("profile_warmup_s", unknown)
    return "full" if long_enough else "smoke"


def not_recordable(res: Result, facts: Mapping[str, Any]) -> str | None:
    """Why a run cannot become a baseline: it did not pass, it records no event loop (a baseline
    without one is never compared), or it was shortened (a baseline taken from a short window would
    be gated against full-length runs), or it ran without instrumentation (#571: the uninstrumented
    half of an overhead pair, never a baseline); `None` when it can."""
    if instrumentation_of(facts) == "off":
        return NOT_INSTRUMENTED
    if res.status != "PASS":
        return f"the run is {res.status}; only a PASS run becomes a baseline"
    if not facts.get("loop"):
        return "the run does not record its event loop: a baseline without one is never compared"
    if run_profile(facts) != "full":
        if "profile_duration_s" not in facts or "profile_warmup_s" not in facts:
            return "the run does not record how long its profile is: it may be a short one"
        return (
            f"the run is shortened (steady {facts['steady_s']:.0f} s of the profile's "
            f"{facts['profile_duration_s']:.0f} s, warm-up {facts['warmup_s']:.0f} s of "
            f"{facts['profile_warmup_s']:.0f} s): only a full-length run becomes a baseline"
        )
    return None


def compare(
    res: Result, facts: Mapping[str, Any], tolerance: float, runs: int = 1
) -> gate.GateResult:
    """The baseline gate. C-13.9 compares the median of at least `MIN_GATE_RUNS` runs, never a
    single noisy sample, so fewer runs can only warn."""
    tol = {m: tolerance for m in res.verdict.metrics}
    if instrumentation_of(facts) == "off":
        return gate.GateResult(
            gated=False,
            reason="instrumentation off (overhead mode): never gated against a baseline, nor "
            "recorded as one; `runner overhead` compares it with its instrumented twin",
        )
    base = gate.load_baseline(baseline_name(facts), BASELINES)
    if base is not None and (not facts.get("loop") or base.get("loop") != facts.get("loop")):
        return gate.GateResult(  # refused when either side records none: never taken as this loop
            gated=False,
            reason=f"baseline loop {base.get('loop') or 'not recorded'}, this run's "
            f"{facts.get('loop') or 'not recorded'}: loop-sensitive numbers are not comparable "
            "across loops, or without one",
        )
    if base is not None and feeder_of(base) != feeder_of(facts):
        return gate.GateResult(  # the feeder's CPU and loop time are in one side's numbers only
            gated=False,
            reason=f"baseline feeder {feeder_of(base)}, this run's {feeder_of(facts)}: a feeder on "
            "the backend's loop and one in its own process are not comparable",
        )
    if base is not None and instrumentation_of(base) != instrumentation_of(facts):
        return gate.GateResult(  # a misfiled baseline: E17-T06's cost is in one side's only
            gated=False,
            reason=f"baseline instrumentation {instrumentation_of(base)}, this run's "
            f"{instrumentation_of(facts)}: an instrumented build and an uninstrumented one are "
            "not comparable",
        )
    g = gate.compare(
        res.verdict,
        base,
        facts["machine_profile"],
        tol,
        run_profile(facts),
        harness_version=HARNESS_VERSION,
    )
    if runs < MIN_GATE_RUNS and g.failures:
        note = f" (one run: C-13.9 gates the median of {MIN_GATE_RUNS})"
        g.warnings += [f + note for f in g.failures]
        g.failures = []
    return g


def variance_sources(a: Mapping[str, Any], b: Mapping[str, Any]) -> list[str]:
    """What can explain two runs of one profile differing (AC 5), from what each run recorded."""
    out = []
    if any(f["variance"]["nr_throttled"] > 0 for f in (a, b)):
        out.append("cpu throttling (cpu.stat nr_throttled rose)")
    if any((f["variance"].get("other_cores") or 0.0) > VARIANCE_OTHER_CORES for f in (a, b)):
        out.append(f"co-tenant load (over {VARIANCE_OTHER_CORES:g} core busy outside the run)")
    if a["cpu_model"] != b["cpu_model"]:
        out.append(f"cpu model changed ({a['cpu_model']} / {b['cpu_model']})")
    if any((f.get("client_lag_p95_ms") or 0) >= VARIANCE_CLIENT_LAG_MS for f in (a, b)):
        out.append("k6 client lag")
    return out


APPROXIMATIONS = (
    "k6 decode-complete stands in for paint (no paint is measured); loopback replaces the "
    "network; book and trades come from bench stand-in producers (the feeder), not ingestion; "
    "deflate is offered as k6 can (no context takeover); a laptop core beats a VPS vCPU; the "
    f"fixture runs on the {LOOP} loop where production's uvicorn picks uvloop, so fan-out, loop "
    "lag and CPU err on the pessimistic side and compare with this harness's own runs only"
)


def _missed(res: Result) -> str:
    return f"; missed: {', '.join(res.failed())}" if res.failed() else ""


def render(res: Result, facts: Mapping[str, Any], g: gate.GateResult) -> str:
    p = facts["resolved"]
    shape = f"{p['users']} user(s) x {p['connections']} connection(s), {p['symbols']} symbols"
    off = instrumentation_of(facts) == "off"
    mode = ", instrumentation off (overhead mode)" if off else ""
    lines = [
        f"# E17-Q03 WS load report: {facts['profile']}, flag {facts['flag']}{mode}: {res.status}",
        "",
        f"- Harness `{facts['harness']}`, k6 `{facts['k6_version']}`, commit "
        f"`{facts['commit'][:12]}`, machine profile `{facts['machine_profile']}` "
        f"({facts['cpu_model']}, kernel {facts['kernel']})",
        f"- {shape}, `{p['workspace']}`; steady window {facts['steady_s']:.0f} s after "
        f"{facts['warmup_s']:.0f} s of warm-up",
        f"- Tick-to-decode gates **{p.get('gate_on', 'excluding')}** the throttle wait; both shown",
        f"- Approximations: {APPROXIMATIONS}",
    ]
    backend_cpus, k6_cpus = facts.get("cpus", (None, None))
    lines.append(f"- CPU sets: backend {backend_cpus or 'any'}, k6 {k6_cpus or 'any'}")
    if facts.get("feeder") == "proc":  # an inproc report reads as it always has
        cores = facts.get("feeder_cpu_cores")
        used = "not read" if cores is None else f"{cores:.2f} core(s)"
        lines.append(
            f"- Feeder out of process (`--feeder proc`) on cpus "
            f"{facts.get('feeder_cpus') or 'any (inherited, not pinned)'}: {used}, "
            "outside the backend CPU"
            + (" (inside the backend's systemd scope and its quota)" if facts["staging"] else "")
        )
    if off:  # an instrumented report reads as it always has
        lines.append(
            "- Instrumentation off (`--instrumentation off`, #571): E17-T06's hot-path series are "
            "stood in by no-ops, so budget #6 is not measured; the uninstrumented half of an "
            "overhead pair (`runner overhead`), never gated and never a baseline"
        )
    if not facts["staging"]:
        lines.append("- Not staged: no systemd scope, so no CPU quota and no memory cap")
    if (cs := res.clock_skew) is not None:  # why the validity guard let the run through, or not
        host = facts.get("same_host")
        same = "not recorded" if host is None else str(bool(host)).lower()
        lines.append(
            f"- Clock skew at the hello (same_host {same}, skew_estimator {cs.skew_estimator}): "
            f"{cs.text}"
        )
        lines += [f"- WARNING: {cs.warning}"] if cs.warning else []  # a fallback is said
    lines += [
        "",
        "| check | budget | measured | limit | unit | result |",
        "|---|---|---:|---:|---|---|",
    ]
    for c in [*res.verdict.checks, *res.informational]:
        verdict = "pass" if c.passed else "FAIL" if c.hard else "miss (reported)"
        note = f" - {c.note}" if c.note else ""
        row = (c.name + note, c.budget, f"{c.measured:.4g}", f"{c.limit:.4g}", c.unit, verdict)
        lines.append("| " + " | ".join(row) + " |")
    lines += ["", "| metric | p50 | p95 | p99 | max | n |", "|---|---:|---:|---:|---:|---:|"]
    for k, m in sorted(res.verdict.metrics.items()):
        cells = " | ".join(f"{m[x]:.4g}" if x in m else "" for x in ("p50", "p95", "p99", "max"))
        lines.append(f"| {k} | {cells} | {m['count']:.0f} |")
    if res.not_judged:
        lines += ["", "Not judged:", *(f"- {x}" for x in res.not_judged)]
    if res.invalid:
        if res.status == "INVALID":
            head = f"**INVALID** (a validity guard tripped, so no budget is judged{_missed(res)}):"
        else:  # the scrape line outranks it
            head = f"Also invalid (a validity guard tripped; {budgets.SCRAPE_LINE} decides FAIL):"
        lines += ["", head, *(f"- {x}" for x in res.invalid)]
    lines += ["", "Not measurable here:", *(f"- {x}" for x in budgets.NOT_MEASURABLE)]
    lines += ["", f"Baseline gate: **{g.status}**" + (f" ({g.reason})" if g.reason else "")]
    lines += [*(f"- WARN {w}" for w in g.warnings), *(f"- FAIL {f}" for f in g.failures)]
    if g.diff:
        lines += ["", gate.render_diff(g)]
    return redact("\n".join(lines)) + "\n"


def finish(out: Path, tolerance: float, *, record: bool = False) -> int:
    res, facts = judge(out)
    g = compare(res, facts, tolerance)
    (out / "report.md").write_text(render(res, facts, g), encoding="utf-8")
    body = {"facts": facts, "result": res.as_dict(), "gate": {"status": g.status, "diff": g.diff}}
    (out / "result.json").write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    overhead = res.mode == budgets.OVERHEAD_MODE
    print(
        f"{facts['profile']} flag {facts['flag']}: {res.status}"
        + (" (overhead mode: instrumentation off, budget #6 not measured)" if overhead else "")
        + (f", failed: {', '.join(res.failed())}" if res.failed() else "")
    )
    lead = "INVALID" if res.status == "INVALID" else "also invalid:"
    for text in res.invalid:
        print(f"  {lead} {text}")
    if res.clock_skew is not None and res.clock_skew.warning:
        print(f"::warning::{facts['profile']}: clock skew: {res.clock_skew.warning}")
    for w in g.warnings:
        print(f"::warning::{facts['profile']}: {w}")
    for f in g.failures:
        print(f"::error::{facts['profile']}: {f}")
    if record:
        why = not_recordable(res, facts)
        print(f"not recorded: {why}" if why else f"baseline -> {record_baseline(res, facts)}")
    return 1 if g.failures else res.exit_code


def record_baseline(res: Result, facts: Mapping[str, Any]) -> Path:
    """A baseline from a passing, full-length run: `warn-only` until a reviewed PR sets its `gate`
    key to `gated` once a second same-profile run confirms it (06 7.4; `gate.compare` never fails
    against a `warn-only` one). `gate.record` refuses under CI, so a run never rewrites it. A run
    with instrumentation off is refused here too, whoever calls it."""
    if instrumentation_of(facts) == "off":
        raise ValueError(NOT_INSTRUMENTED)
    extra = {k: facts[k] for k in ("commit", "k6_version", "cpu_model", "cgroup", "loop")}
    extra["flag"] = facts["flag"]
    extra["feeder"] = feeder_of(facts)
    extra["instrumentation"] = instrumentation_of(facts)
    named = Verdict(baseline_name(facts), list(res.verdict.checks), dict(res.verdict.metrics))
    scaling = f"steady {facts['steady_s']:.0f} s"
    return gate.record(
        named, facts["machine_profile"], scaling, run_profile(facts), BASELINES,
        harness_version=HARNESS_VERSION, extra=extra,
    )  # fmt: skip


def merge(runs: Sequence[tuple[Result, dict[str, Any]]]) -> tuple[Result, dict[str, Any]]:
    """The per-metric median of several runs' headline p95s (C-13.9: the median of at least 3)."""
    first = runs[0][0]
    merged = Verdict(first.verdict.scenario, list(first.verdict.checks))
    for name, m in first.verdict.metrics.items():
        mids = [r.verdict.metrics[name]["p95"] for r, _ in runs if name in r.verdict.metrics]
        merged.metrics[name] = {**m, "p95": statistics.median(mids)}
    return Result(merged, [x for r, _ in runs for x in r.invalid]), runs[0][1]


def feeder_of(facts: Mapping[str, Any]) -> str:
    """The feeder mode a run or a baseline records: one from before the mode was recorded ran the
    only mode there was, `inproc`."""
    return str(facts.get("feeder") or LEGACY_FEEDER)


def instrumentation_of(facts: Mapping[str, Any]) -> str:
    """The instrumentation a run or a baseline records: one from before it was recorded ran the
    build as it ships, `on`."""
    return str(facts.get("instrumentation") or instr.LEGACY)


def comparable(
    runs: Sequence[tuple[Result, dict[str, Any]]],
    names: Sequence[str],
    *,
    across_instrumentation: bool = False,
) -> list[str]:
    """Why these runs cannot be compared with each other: an INVALID run proves nothing, nor does a
    run that records no event loop, and runs of another profile, flag, machine, length, event
    loop, feeder mode or instrumentation are not samples of one thing (`across_instrumentation`:
    the overhead pair, whose one difference is that). Empty when they can."""
    why = [
        f"{name} is {res.status} ({'; '.join(res.invalid)}{_missed(res)})"
        for name, (res, _) in zip(names, runs, strict=True)
        if res.invalid
    ]
    why += [
        f"{name} does not record its event loop"
        for name, (_, facts) in zip(names, runs, strict=True)
        if not facts.get("loop")
    ]
    for key in ("profile", "flag", "machine_profile", "steady_s", "warmup_s", "loop"):
        seen = sorted({str(facts.get(key, "not recorded")) for _, facts in runs})
        if len(seen) > 1:
            why.append(f"the runs differ in {key}: {', '.join(seen)}")
    modes = sorted({feeder_of(facts) for _, facts in runs})
    if len(modes) > 1:  # the feeder's CPU is in the backend's numbers in one mode only
        why.append(f"the runs differ in feeder: {', '.join(modes)}")
    built = sorted({instrumentation_of(facts) for _, facts in runs})
    if len(built) > 1 and not across_instrumentation:  # E17-T06's cost is in one side's only
        why.append(f"the runs differ in instrumentation: {', '.join(built)}")
    return why


def cmd_run(a: argparse.Namespace) -> int:
    table = profiles.load()
    p = plan(table, a, a.profile, a.out_dir)
    execute(p, k6_binary())
    return finish(p.out, a.tolerance, record=a.record_baseline)


def cmd_selfcheck(a: argparse.Namespace) -> int:
    table = profiles.load()
    p = plan(table, a, "selfcheck", a.out_dir)
    execute(p, k6_binary())
    code = finish(p.out, a.tolerance)
    ok, text = budgets.expect_failure(judge(p.out)[0], p.prof["expect_fail"])
    (p.out / "selfcheck.txt").write_text(f"{'OK' if ok else 'NOT OK'}: {text}\n", encoding="utf-8")
    named = p.prof["expect_fail"]
    print(
        f"self-check OK: the inflated run failed the profile, naming {named}"
        if ok
        else f"self-check NOT OK: {text}"
    )
    return 0 if ok and code in (0, 1) else 1


def cmd_w5(a: argparse.Namespace) -> int:
    """The 10 phases of the W5 plan. `--duration-s` and `--warmup-s` replace every phase's window
    and warm-up (a dry run: 30 and 10 take about 9 minutes); a phase's class is its pong delay, so
    `--rtt-delay-ms` is refused."""
    if a.rtt_delay_ms is not None:
        raise SystemExit(
            "w5: every phase sets its own pong delay, which is its class: no --rtt-delay-ms"
        )
    table, k6, phases = profiles.load(), k6_binary(), []
    left_out: list[str] = []  # phases that lost a boundary scrape: no steady window to read
    kept: dict[str, str] = {}  # phases read as they are after a scrape timed out
    for ph in table["w5"]["phases"]:
        out = a.out_dir / ph["name"]
        p = plan(table, a, table["w5"]["base"], out, **{k: v for k, v in ph.items() if k != "name"})
        execute(p, k6)
        res, facts = judge(out)
        tally = facts.get("scrapes", {})
        if tally.get("missing"):
            left_out.append(ph["name"])
            continue
        if tally.get("timed_out_ms"):  # a retried boundary's CPU rate spans the real interval
            n, again = len(tally["timed_out_ms"]), " and ".join(tally.get("retried", []))
            note = f"{n} of {tally['attempted']} scrapes timed out"
            note += f" ({again} retried)" if again else ""
            kept[ph["name"]] = f"phase {ph['name']}: {note}, kept"
        _, summ, t0, t1 = load_run(out)
        rtt = int(p.prof["rtt_delay_ms"])
        phases.append(
            w5.Phase(
                ph["name"],
                tuple(p.prof["families"]),
                rtt,
                summ,
                budgets.delta(t0, t1),
                facts["steady_s"],
                "INVALID" if res.invalid else res.status,  # W5 leaves out on validity alone
                facts.get("steady_actual_s"),
            )
        )
    answer = w5.analyze(phases, left_out)
    answer["notes"] += [n for name, n in kept.items() if name not in answer["skipped"]]
    answer["notes"] += [f"phase {n}: a boundary scrape timed out, left out" for n in left_out]
    (a.out_dir / "w5.json").write_text(
        json.dumps(answer, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(w5.headline(answer))
    for note in answer["notes"]:
        print(f"  {note}")
    return 1 if left_out else w5.exit_code(answer)


def cmd_w5_judge(a: argparse.Namespace) -> int:
    """Re-judge a saved W5 directory (`w5 --out-dir DIR`) offline: the phases `cmd_w5` builds, from
    the saved files alone, through `w5.analyze`. It prints the answer as JSON, writes nothing and
    exits as `cmd_w5` does (the note on a scrape that timed out and was kept is not repeated). A
    symlink, a FIFO or a device (a read of one waits for a writer), or a file over 64 MiB, in DIR
    or under it, is refused before anything is read; a DIR that is not there gets `no_data`."""
    root = Path(a.dir)
    for p in (root, *root.rglob("*")):
        special = p.exists() and not (p.is_dir() or p.is_file())  # a FIFO, a device
        if p.is_symlink() or special or (p.is_file() and p.stat().st_size > 64 << 20):
            raise SystemExit(f"{p}: a symlink or over 64 MiB: not read")
    phases: list[w5.Phase] = []
    left_out: list[str] = []
    for ph in profiles.load()["w5"]["phases"]:
        out = root / ph["name"]
        if not out.is_dir():  # `analyze` names a mixed phase the directory does not hold
            continue
        res, facts = judge(out)
        if facts.get("scrapes", {}).get("missing"):
            left_out.append(ph["name"])
            continue
        _, summ, t0, t1 = load_run(out)
        prof, status = facts["resolved"], "INVALID" if res.invalid else res.status
        phases.append(
            w5.Phase(
                ph["name"], tuple(prof["families"]), int(prof["rtt_delay_ms"]), summ,
                budgets.delta(t0, t1), facts["steady_s"], status, facts.get("steady_actual_s"),
            )
        )  # fmt: skip
    answer = w5.analyze(phases, left_out)
    answer["notes"] += [f"phase {n}: a boundary scrape timed out, left out" for n in left_out]
    print(json.dumps(answer, indent=2, default=str))
    return 1 if left_out else w5.exit_code(answer)


def cmd_record(a: argparse.Namespace) -> int:
    res, facts = judge(Path(a.dir))
    if why := not_recordable(res, facts):
        print(f"not recorded: {why}")
        return 1
    print("baseline ->", record_baseline(res, facts))
    return 0


def cmd_judge(a: argparse.Namespace) -> int:
    return finish(Path(a.dir), a.tolerance)


def cmd_gate(a: argparse.Namespace) -> int:
    """C-13.9: the median of `MIN_GATE_RUNS` runs against the baseline. Exit 2 when the runs cannot
    be gated (fewer than three, an INVALID one, one without a loop, or not of one profile), 1 for a
    regression or a run that missed a budget, 0 only for three comparable runs that passed and did
    not regress."""
    outs = [Path(d) for d in a.dirs]
    runs = [judge(o) for o in outs]
    why = comparable(runs, [o.name for o in outs])
    if len(outs) < MIN_GATE_RUNS:
        why.append(f"{len(outs)} run(s): the gate needs {MIN_GATE_RUNS} (C-13.9 gates the median)")
    if why:
        for text in why:
            print(f"::error::gate refused: {text}")
        return 2
    res, facts = merge(runs)
    g = compare(res, facts, a.tolerance, len(outs))
    print(
        f"gate over {len(outs)} run(s) at {a.tolerance:.0%}: {g.status}"
        + (f" ({g.reason})" if g.reason else "")
    )
    print(gate.render_diff(g))
    for f in g.failures:
        print(f"::error::{facts['profile']}: {f}")
    missed = [(o.name, r.failed()) for o, (r, _) in zip(outs, runs, strict=True) if r.failed()]
    for name, checks in missed:
        print(f"::error::{name} missed a budget: {', '.join(checks)}")
    return 1 if g.failures or missed else 0


def cmd_repro(a: argparse.Namespace) -> int:
    (ra, fa), (rb, fb) = judge(Path(a.dir_a)), judge(Path(a.dir_b))
    if why := comparable([(ra, fa), (rb, fb)], [a.dir_a, a.dir_b]):
        print(f"reproducibility refused: {'; '.join(why)}")
        return 2
    off = budgets.repro_diff(ra.verdict.metrics, rb.verdict.metrics)
    only_one = ra.verdict.metrics.keys() ^ rb.verdict.metrics.keys()  # a lost boundary, say
    skipped = [name for name in budgets.HEADLINES if name in only_one]
    named = variance_sources(fa, fb) + list(a.variance_source or [])
    for name, rel in off.items():
        print(f"  {name}: {rel:+.1%} between the two runs")
    if skipped:
        print(f"  not compared (no reading in one run): {', '.join(skipped)}")
    if off and not named:
        tol = f"{budgets.REPRO_TOLERANCE:.0%}"
        print(f"reproducibility FAIL: {len(off)} headline(s) differ by more than {tol}, no source")
        return 1
    every = "every compared headline" if skipped else "every headline"
    print(
        "reproducibility OK"
        + (
            f", differences explained by: {'; '.join(named)}"
            if off
            else f": {every} within {budgets.REPRO_TOLERANCE:.0%}"
        )
    )
    return 0


def _lag_ms(out: Path, q: float) -> float | None:
    """The loop-lag quantile `q` of a saved run's steady window, in ms (`None`: no sample)."""
    _, _, t0, t1 = load_run(out)
    lag = budgets.quantile(budgets.delta(t0, t1), "event_loop_lag_seconds", q)
    return None if lag is None else lag * 1000


def _row(name: str, unit: str, on: float | None, off: float | None) -> dict[str, Any]:
    pct = (on - off) / off * 100 if on is not None and off else None
    return {"name": name, "unit": unit, "on": on, "off": off, "delta_pct": pct}


def overhead_pair(on_dir: Path, off_dir: Path) -> tuple[list[str], dict[str, Any]]:
    """#571: why the two runs are not an overhead pair (empty when they are), and the comparison.
    A pair is one instrumented run and then one uninstrumented run that differ in nothing else
    `comparable` or `PAIR_KEYS` names; each row is the on run's value, the off run's and the delta
    in % of the off run's. The CPU's is E17-T06's overhead, held to `OVERHEAD_LINE_PCT`."""
    (ron, fon), (roff, foff) = runs = [judge(on_dir), judge(off_dir)]
    why = comparable(runs, [str(on_dir), str(off_dir)], across_instrumentation=True)
    built = [instrumentation_of(fon), instrumentation_of(foff)]
    if built != ["on", "off"]:
        why.append(
            f"overhead takes one instrumentation-on run, then one off: got {' and '.join(built)}"
        )
    for key in PAIR_KEYS:
        if fon.get(key) != foff.get(key):
            why.append(f"the runs differ in {key}: {fon.get(key)}, {foff.get(key)}")
    cpu = [r.verdict.metrics.get("backend_cpu_s_per_s") for r in (ron, roff)]
    why += [
        f"{d} has no backend CPU reading (a boundary scrape was lost)"
        for d, m in zip((on_dir, off_dir), cpu, strict=True)
        if m is None
    ]
    if why:
        return why, {}
    ttd = [r.verdict.metrics["tick_to_decode_trades_ms"] for r in (ron, roff)]
    on_cpu, off_cpu = (None if m is None else m["p95"] for m in cpu)  # both read: refused above
    rows = [_row("backend_cpu_s_per_s", "core-s/s", on_cpu, off_cpu)]
    rows += [
        _row(f"tick_to_decode_trades_ms.{q}", "ms", ttd[0][q], ttd[1][q])
        for q in ("p50", "p95", "p99")
    ]
    rows += [
        _row(f"event_loop_lag_ms.p{int(q * 100)}", "ms", _lag_ms(on_dir, q), _lag_ms(off_dir, q))
        for q in (0.95, 0.99)
    ]
    cpu_pct = rows[0]["delta_pct"]
    notes = [
        "one pair: one sample of each build; the harness's own run-to-run spread (the "
        f"reproducibility check allows {budgets.REPRO_TOLERANCE:.0%}) can be wider than the "
        f"{OVERHEAD_LINE_PCT:g} % line, so repeat the pair for an interval before closing it",
        f"k6 times whole milliseconds: a latency that moved by {budgets.K6_CLOCK_MS:g} ms or less "
        "has not changed",
    ]
    if feeder_of(fon) == "inproc":
        notes.append(
            "the feeder ran on the backend's loop (`--feeder inproc`): its CPU is in both runs' "
            "backend CPU, so the share is of the backend, below the fan-out path's own; "
            "`--feeder proc` takes it out"
        )
    body = {
        "pair": {"on": str(on_dir), "off": str(off_dir)},
        "status": {"on": ron.status, "off": roff.status},
        **{k: fon.get(k) for k in ("profile", "flag", "machine_profile", "loop", "steady_s")},
        "feeder": feeder_of(fon),
        "cpus": fon.get("cpus"),
        "rows": rows,
        "cpu_overhead_pct": cpu_pct,
        "line_pct": OVERHEAD_LINE_PCT,
        "under_line": cpu_pct is not None and cpu_pct < OVERHEAD_LINE_PCT,
        "notes": notes,
    }
    return [], body


def _cell(v: float | None, fmt: str) -> str:
    return "not read" if v is None else format(v, fmt)


def render_overhead(body: Mapping[str, Any]) -> str:
    pct, line = body["cpu_overhead_pct"], body["line_pct"]
    verdict = "under" if body["under_line"] else "at or over"
    lines = [
        f"# E17-T06 instrumentation overhead (#571): {body['profile']}, flag {body['flag']}, "
        f"feeder {body['feeder']}",
        "",
        f"- On: `{body['pair']['on']}` ({body['status']['on']}); off: `{body['pair']['off']}` "
        f"({body['status']['off']}); machine profile `{body['machine_profile']}`, loop "
        f"{body['loop']}, steady window {body['steady_s']:.0f} s",
        f"- Backend CPU overhead **{_cell(pct, '+.2f')} %**: {verdict} the {line:g} % line",
        "",
        "| metric | unit | on | off | on vs off |",
        "|---|---|---:|---:|---:|",
    ]
    for r in body["rows"]:
        delta = _cell(r["delta_pct"], "+.1f") + (" %" if r["delta_pct"] is not None else "")
        lines.append(
            f"| {r['name']} | {r['unit']} | {_cell(r['on'], '.4g')} | {_cell(r['off'], '.4g')} "
            f"| {delta} |"
        )
    lines += ["", "Notes:", *(f"- {n}" for n in body["notes"])]
    return "\n".join(lines) + "\n"


def cmd_overhead(a: argparse.Namespace) -> int:
    """#571: E17-T06's overhead from one instrumented run and one uninstrumented run of the same
    profile, flag, feeder, machine, loop and placement. Exit 2 when they are not such a pair
    (named; nothing written), 1 when the CPU overhead is at or over the 2 % line, 0 under it."""
    on_dir, off_dir = Path(a.on_dir), Path(a.off_dir)
    why, body = overhead_pair(on_dir, off_dir)
    if why:
        for text in why:
            print(f"::error::overhead refused: {text}")
        return 2
    out = Path(a.out_dir) if a.out_dir else off_dir
    out.mkdir(parents=True, exist_ok=True)
    (out / "overhead.json").write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    (out / "overhead.md").write_text(render_overhead(body), encoding="utf-8")
    pct = body["cpu_overhead_pct"]
    print(
        f"E17-T06 overhead, {body['profile']} flag {body['flag']} feeder {body['feeder']}: "
        f"backend CPU {_cell(pct, '+.1f')} % against the {body['line_pct']:g} % line "
        f"({'under' if body['under_line'] else 'at or over'}); {out / 'overhead.md'}"
    )
    for r in body["rows"][1:]:
        print(f"  {r['name']}: {_cell(r['on'], '.4g')} vs {_cell(r['off'], '.4g')} {r['unit']}")
    for note in body["notes"]:
        print(f"  note: {note}")
    return 0 if body["under_line"] else 1


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name: str, fn: Any, *, runs: bool = False) -> argparse.ArgumentParser:
        sp = sub.add_parser(name)
        sp.set_defaults(fn=fn)
        sp.add_argument("--tolerance", type=float, default=TOLERANCE)
        if runs:
            sp.add_argument("--out-dir", type=Path, default=API / "bench" / "reports" / "e17")
            sp.add_argument("--staging", action="store_true")
            sp.add_argument(
                "--trace-sp", action="store_true", help="log `sp` ids and the backend's debug spans"
            )
            sp.add_argument("--backend-cpus", help="taskset cpuset of the backend (--staging: 0-7)")
            sp.add_argument("--k6-cpus", help="taskset cpuset of k6 (--staging: 8-15)")
            sp.add_argument(
                "--feeder", choices=FEEDERS, default="inproc",
                help="the feeder on the backend's loop (inproc) or in a child process (proc)",
            )  # fmt: skip
            sp.add_argument("--feeder-cpus", help="--feeder proc: the child's cpuset (k6's)")
            sp.add_argument("--seed", type=int, default=7)
            sp.add_argument("--ws-path", help="k6's path: /ws (default), or /api/v1/ws")
            sp.add_argument("--gate-on", choices=("including", "excluding"))
            for opt in OVERRIDES:
                sp.add_argument(f"--{opt.replace('_', '-')}", type=float)
        return sp

    add("run", cmd_run, runs=True).add_argument("profile")
    sub.choices["run"].add_argument(
        "--record-baseline", action="store_true", help="deliberate, local only"
    )
    sub.choices["run"].add_argument(
        "--instrumentation", choices=instr.MODES, default="on",
        help="off: E17-T06's hot-path series stood in by no-ops, for `overhead` (#571)",
    )  # fmt: skip
    add("selfcheck", cmd_selfcheck, runs=True)
    add("w5", cmd_w5, runs=True)
    add("w5-judge", cmd_w5_judge).add_argument("dir")
    add("judge", cmd_judge).add_argument("dir")
    add("record", cmd_record).add_argument("dir")
    add("gate", cmd_gate).add_argument("dirs", nargs="+")
    rp = add("repro", cmd_repro)
    rp.add_argument("dir_a")
    rp.add_argument("dir_b")
    rp.add_argument("--variance-source", action="append")
    op = add("overhead", cmd_overhead)
    op.add_argument("on_dir", help="the run with --instrumentation on")
    op.add_argument("off_dir", help="the run with --instrumentation off")
    op.add_argument("--out-dir", help="where overhead.json and overhead.md go (default: OFF_DIR)")
    a = ap.parse_args(argv)
    code: int = a.fn(a)
    return code


if __name__ == "__main__":
    sys.exit(main())
