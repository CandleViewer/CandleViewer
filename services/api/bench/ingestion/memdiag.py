"""Memory diagnosis of `soak_bars` (#399 D2-G4, R4): one leg a process, and the rule over them.

    uv run python -m bench.ingestion.memdiag leg --label default --out-dir <dir>   # a reading
    uv run python -m bench.ingestion.memdiag leg --label tracemalloc --hours 12 --tracemalloc 6 ...
    uv run python -m bench.ingestion.memdiag judge <dir>

A leg runs the unchanged `runner.run_soak` on the full `soak_bars` profile with a `DiagSampler`: the
soak's own RSS reading at every sample, allocator probes once an hour of scenario time. Only a leg
with no `--hours`, no tracemalloc and no allocator variable (`LEG_ENV`, set by the caller before the
interpreter starts) is a reading. The rule: docs/qa/perf/e12-bars-r4-diagnosis.md
"""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import gc
import itertools
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import tracemalloc
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, TextIO

import psutil

from bench.ingestion import budgets
from bench.ingestion.config import load, machine_profile
from bench.ingestion.engine import ProcSampler, PsutilProcSampler
from bench.ingestion.runner import run_soak

MiB: Final = 2**20
Doc = dict[str, Any]
Lines = dict[str, tuple[int, int]]  # where -> (size, count)
#: The reading rule's thresholds (R4's own limit, 0.18 MiB/h a symbol, is `budgets`').
LEAK_MIN_RUN: Final = 6  # consecutive post-warm-up hourly snapshots a LEAK line grows strictly over
LEAK_MIN_GROWTH_MIB: Final = 1.0  # and by this much at least over that run
WARMUP_H: Final = 2  # the first hours of a leg; the hour-2 snapshot is the first after them
BARS_SHARE: Final = 0.5  # share of the LEAK growth owned under candleviewer/bars/: IN BARS
MOVE_MIN: Final = 0.09  # MiB/h a symbol between an allocator leg's W24 slope and the default's
W24: Final = (12.0, 24.0)  # R4's window, in scenario hours, both ends in
TRACE_LEG_H: Final = 12.0  # the tracemalloc leg's length: attribution only, its RSS never sloped
PROBE_EVERY_S: Final = 3600.0  # scenario seconds between two probe lines (and snapshots)
STEP_MIB: Final = 1.0  # an RSS rise this large between two probe lines is a step
STEP_SHARE: Final = 0.5  # a counter that rose with a step by this share of it explains it
#: The legs in dispatch order, one a dispatch, with the allocator environment each runs under.
LEG_ENV: Final[Mapping[str, Mapping[str, str]]] = {
    "default": {},
    "tracemalloc": {},
    "malloc": {"PYTHONMALLOC": "malloc"},
    "mmap128k": {"MALLOC_MMAP_THRESHOLD_": "131072"},
}
MOVERS: Final = ("malloc", "mmap128k")
R3: Final = ("bars_store_at_cap", "bars_closes_folded", "bars_builders_healthy")
_ROOT: Final = f"{Path(__file__).resolve().parents[4]}/"
_NOT_REPO: Final = ("/", "<", "site-packages/")  # how `where` writes a line outside the checkout
#: Traces whose newest frame is tracemalloc's, the import system's or this module's.
DROP: Final = [
    tracemalloc.Filter(False, pattern)
    for pattern in (tracemalloc.__file__, "<frozen importlib.*>", "*/importlib/*", __file__)
]


def where(filename: str, lineno: int) -> str:
    """`path:line`, alike on every machine: `site-packages/...` for an installed package (a venv in
    the checkout too), repo-relative in the checkout, else as tracemalloc gave it."""
    _, sep, tail = filename.partition("/site-packages/")
    return f"{'site-packages/' + tail if sep else filename.removeprefix(_ROOT)}:{lineno}"


def top_growth(prev: Lines, cur: Lines, n: int) -> list[Doc]:
    """The `n` lines that grew most from `prev` to `cur`, by `Snapshot.compare_to(prev, "lineno")`'s
    numbers (a new line grew by all of it, a freed one by minus all of it); ties by line."""
    rows: list[Doc] = []
    for k in prev.keys() | cur.keys():
        (s0, c0), (s1, c1) = prev.get(k, (0, 0)), cur.get(k, (0, 0))
        rows.append(dict(where=k, size=s1, size_diff=s1 - s0, count=c1, count_diff=c1 - c0))
    return sorted(rows, key=lambda r: (-r["size_diff"], r["where"]))[:n]


def line_map(snap: tracemalloc.Snapshot) -> tuple[Lines, dict[str, tracemalloc.Frame]]:
    """`snap.statistics("lineno")` by `where`, and each line's frame."""
    sizes: Lines = {}
    frames: dict[str, tracemalloc.Frame] = {}
    for st in snap.statistics("lineno"):
        key = where((fr := st.traceback[0]).filename, fr.lineno)
        size, count = sizes.get(key, (0, 0))
        sizes[key], frames[key] = (size + st.size, count + st.count), fr
    return sizes, frames


def tracebacks(snap: tracemalloc.Snapshot, fr: tracemalloc.Frame) -> list[Doc]:
    """The three biggest tracebacks that allocate at `fr`'s line, frames newest first."""
    sub = snap.filter_traces([tracemalloc.Filter(True, fr.filename, fr.lineno)])
    out: list[Doc] = []
    for st in sub.statistics("traceback")[:3]:
        frames = [where(f.filename, f.lineno) for f in reversed(st.traceback)]
        out.append({"size": st.size, "count": st.count, "frames": frames})
    return out


_MI_FIELDS: Final = "arena ordblks smblks hblks hblkhd usmblks fsmblks uordblks fordblks keepcost"


class _Mallinfo2(ctypes.Structure):
    """glibc's `struct mallinfo2` (2.33+): ten `size_t`."""

    _fields_ = [(name, ctypes.c_size_t) for name in _MI_FIELDS.split()]


def _mallinfo2(libc: str | None) -> Callable[[], _Mallinfo2] | None:
    """glibc's `mallinfo2` when `libc` (`os.confstr`'s) is glibc 2.33 or later, else None."""
    if not (libc or "").startswith("glibc") or not hasattr(lib := ctypes.CDLL(None), "mallinfo2"):
        return None
    lib.mallinfo2.restype, lib.mallinfo2.argtypes = _Mallinfo2, []
    return lib.mallinfo2


_CS: Final = "CS_GNU_LIBC_VERSION"
GLIBC: Final = os.confstr(_CS) if _CS in os.confstr_names else None  # "glibc 2.39"; None: not glibc
_MALLINFO2: Final = _mallinfo2(GLIBC)
MALLINFO: Final = ("arena", "hblkhd", "uordblks", "fordblks", "keepcost")


def mallinfo2() -> dict[str, int] | None:
    """`mallinfo2()`'s arena, hblkhd, uordblks, fordblks and keepcost; None off glibc."""
    got = None if _MALLINFO2 is None else _MALLINFO2()
    return None if got is None else {k: getattr(got, k) for k in MALLINFO}


def smaps(text: str) -> dict[str, int] | None:
    """`/proc/self/smaps_rollup`'s Rss, Anonymous and AnonHugePages in bytes; None if one lacks."""
    got = {}
    for line in text.splitlines():
        name, _, rest = line.partition(":")
        if name in ("Rss", "Anonymous", "AnonHugePages"):
            got[name] = int(rest.split()[0]) * 1024
    return got if len(got) == 3 else None


def thp_mode(text: str | None) -> str | None:
    """The bracketed mode of `/sys/kernel/mm/transparent_hugepage/enabled`."""
    return text.split("[", 1)[1].split("]", 1)[0] if text and "[" in text else None


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return None


def probes(proc: psutil.Process) -> Doc:
    """What a probe line holds besides the soak's own reading: reads of /proc and the allocators."""
    rollup = _read("/proc/self/smaps_rollup")
    out: Doc = {"blocks": sys.getallocatedblocks(), "threads": proc.num_threads()}
    out["mi"], out["smaps"] = mallinfo2(), None if rollup is None else smaps(rollup)
    out["thp"] = thp_mode(_read("/sys/kernel/mm/transparent_hugepage/enabled"))
    if tracemalloc.is_tracing():
        out["traced"] = tracemalloc.get_traced_memory()[0]
    return out


class DiagSampler:
    """`engine.ProcSampler` for a leg. Each call returns the soak's own reading, taken first. Every
    `PROBE_EVERY_S` of scenario time (`setup` calls, then a sample each `every_s`) it writes a
    flushed JSON line of probes to `out` and, while tracing with `top`, diffs a filtered snapshot,
    GC off, against the hour before and hour 2."""

    def __init__(
        self, out: TextIO, setup: int, every_s: float, top: int, rss: ProcSampler | None = None
    ) -> None:
        self._out, self._setup, self._every, self._top = out, setup, every_s, top
        self._per_probe = max(1, round(PROBE_EVERY_S / every_s))
        self._rss, self._proc = rss or PsutilProcSampler(), psutil.Process()
        self.calls = 0
        self.snapshots: list[Doc] = []
        self._prev: Lines | None = None
        self._h2: Lines | None = None

    def sample(self) -> tuple[int, float]:
        rss, cpu = self._rss.sample()
        self.calls += 1
        k = self.calls - self._setup - 1  # the sample's index: 0 at t=0
        if k >= 0 and k % self._per_probe == 0:
            line = {"t_s": k * self._every, "rss": rss, "cpu": cpu, **probes(self._proc)}
            self._out.write(json.dumps(line) + "\n")
            self._out.flush()
            if self._top and tracemalloc.is_tracing() and k > 0:
                self._snapshot(k // self._per_probe)
        return rss, cpu

    def _snapshot(self, hour: int) -> None:
        gc.disable()
        try:
            snap = tracemalloc.take_snapshot().filter_traces(DROP)
            cur, frames = line_map(snap)
            rec: Doc = {"hour": hour}
            diff: list[Doc] = []  # the tracebacks follow the diff against hour 2, if there is one
            if self._prev is not None:
                rec["vs_prev"] = diff = top_growth(self._prev, cur, self._top)
            if self._h2 is not None:
                rec["vs_h2"] = diff = top_growth(self._h2, cur, self._top)
            grown = [g for g in diff[:5] if g["size_diff"] > 0]
            rec["tracebacks"] = {g["where"]: tracebacks(snap, frames[g["where"]]) for g in grown}
            del snap, frames
        finally:
            gc.enable()
        self._prev, self._h2 = cur, cur if hour == WARMUP_H else self._h2
        self.snapshots.append(rec)


SERIES: Final[Mapping[str, Callable[[Doc], float | None]]] = {
    "rss_mib": lambda p: p["rss"] / MiB,
    "blocks": lambda p: float(p["blocks"]),
    "arena_hblkhd_mib": lambda p: (p["mi"]["arena"] + p["mi"]["hblkhd"]) / MiB if p["mi"] else None,
    "uordblks_mib": lambda p: p["mi"]["uordblks"] / MiB if p["mi"] else None,
    "anon_huge_mib": lambda p: p["smaps"]["AnonHugePages"] / MiB if p["smaps"] else None,
}


def _w24(t_s: float) -> bool:
    return W24[0] * 3600 <= t_s <= W24[1] * 3600


def window(probes: Sequence[Doc], n_sym: int) -> Doc:
    """Each series over the probe lines in W24, a symbol: its Theil-Sen slope an hour
    (`budgets.theil_sen_mb_per_h`) and its net rise; None without two sample times."""
    kept, out = [p for p in probes if _w24(p["t_s"])], Doc()
    for name, read in SERIES.items():
        pts = [(p["t_s"], y / n_sym) for p in kept if (y := read(p)) is not None]
        if len({t for t, _ in pts}) < 2:
            out[name] = {"slope": None, "rise": None}
        else:
            out[name] = {"slope": budgets.theil_sen_mb_per_h(pts), "rise": pts[-1][1] - pts[0][1]}
    return out


def steps(probes: Sequence[Doc]) -> list[Doc]:
    """Each RSS rise of `STEP_MIB` or more between two probe lines, put down to the counter that
    rose with it by `STEP_SHARE` of it: glibc's heap (arena + hblkhd), else THP (AnonHugePages),
    else other (pymalloc's arenas, which glibc does not count, among them)."""

    def delta(name: str, a: Doc, b: Doc) -> float:
        ya, yb = SERIES[name](a), SERIES[name](b)
        return 0.0 if ya is None or yb is None else yb - ya

    out: list[Doc] = []
    for a, b in itertools.pairwise(probes):
        rise, heap, thp = (delta(n, a, b) for n in ("rss_mib", "arena_hblkhd_mib", "anon_huge_mib"))
        if rise >= STEP_MIB:
            half = STEP_SHARE * rise
            by = "glibc" if heap >= half else "thp" if thp >= half else "other"
            out.append(dict(t_s=b["t_s"], rss_mib=rise, glibc_mib=heap, thp_mib=thp, by=by))
    return out


def report(meta: Doc, lines: list[Doc], verdict: Doc | None, snaps: list[Doc]) -> Doc:
    """`<label>.json`: `meta`, the runner's verdict as returned, the W24 slope a symbol of the
    soak's RSS curve (never for a traced leg), the probe lines with their W24 window and steps."""
    curve: dict[str, float] = (verdict or {}).get("metrics", {}).get("_curve", {})
    traced, n_sym = bool(meta["tracemalloc_frames"]), meta["symbols"]
    pts = [(float(t), mib / n_sym) for t, mib in curve.items() if _w24(float(t))]
    last = max((float(t) for t in curve), default=lines[-1]["t_s"] if lines else 0.0)
    doc = {**meta, "finished": _now(), "samples": len(curve), "last_t_s": last}
    same = [curve.get(f"{p['t_s']:.0f}") == p["rss"] / MiB for p in lines]
    doc["aligned"] = bool(curve) and all(same)
    doc["threads_max"] = max((p["threads"] for p in lines), default=0)
    doc["rss_w24"] = None if traced or len(pts) < 2 else budgets.theil_sen_mb_per_h(pts)
    doc["w24"] = None if traced else window(lines, n_sym)
    return doc | {"steps": steps(lines), "verdict": verdict, "snapshots": snaps, "probes": lines}


def why_not(leg: Doc) -> list[str]:
    """Why a leg report is no reading under the rule; empty when it is one."""
    label, tm = leg["label"], leg["label"] == "tracemalloc"
    end = (TRACE_LEG_H if tm else W24[1]) * 3600
    why = [] if leg["verdict"] else [f"no verdict (stopped: {leg['stopped']})"]
    if leg["last_t_s"] < end:
        why.append(f"ends at t={leg['last_t_s']:.0f} s, before {end:.0f} s")
    checks = (leg["verdict"] or {}).get("checks", [])
    why += [f"R3 {c['name']} failed" for c in checks if c["name"] in R3 and not c["passed"]]
    if leg["allocator"]["seen"] != LEG_ENV[label] or not leg["allocator"]["self_check"]:
        why.append(f"allocator not as declared: {leg['allocator']}")
    if bool(leg["tracemalloc_frames"]) != tm:
        why.append(f"tracemalloc frames: {leg['tracemalloc_frames']}")
    if label == "default" and not leg["reading"]:
        why.append(f"not a reading: overrides {leg['overrides']}")
    return why + ([] if leg["aligned"] else ["probe lines not aligned with the soak's samples"])


def leak_lines(snaps: Sequence[Doc]) -> dict[str, float]:
    """The LEAK lines and their growth (MiB): a line in a snapshot's top-N (the most growth since
    hour 2) whose size grows strictly over `LEAK_MIN_RUN` or more consecutive hourly snapshots from
    hour 2 on, by `LEAK_MIN_GROWTH_MIB` or more over that run (its largest such run)."""
    sizes: dict[str, dict[int, int]] = {}
    for s in snaps:
        for g in s.get("vs_h2", []):
            by_hour = sizes.setdefault(g["where"], {WARMUP_H: g["size"] - g["size_diff"]})
            by_hour[s["hour"]] = g["size"]
    out: dict[str, float] = {}
    for line, by_hour in sizes.items():
        start = prev = -1
        for h in sorted(by_hour):
            if not (h == prev + 1 and by_hour[h] > by_hour[prev]):
                start = h
            prev, growth = h, (by_hour[h] - by_hour[start]) / MiB
            if h - start + 1 >= LEAK_MIN_RUN and growth >= LEAK_MIN_GROWTH_MIB:
                out[line] = max(out.get(line, 0.0), growth)
    return out


def bars_share(leaks: Mapping[str, float], snaps: Sequence[Doc]) -> float:
    """The share of the LEAK growth owned under `candleviewer/bars/`: a library line's owner is the
    newest repo frame of its biggest traceback in the last snapshot that holds one."""
    tbs: Doc = {}
    for s in snaps:
        tbs |= s.get("tracebacks", {})

    def owner(line: str) -> str:
        first: Doc = next(iter(tbs.get(line, [])), {"frames": []})  # the biggest traceback
        frames: list[str] = first["frames"] if line.startswith(_NOT_REPO) else []
        return next((f for f in frames if not f.startswith(_NOT_REPO)), line)

    bars = sum(g for line, g in leaks.items() if "candleviewer/bars/" in owner(line))
    return bars / sum(leaks.values()) if leaks else 0.0


def rule(legs: Mapping[str, Doc]) -> tuple[str, list[str]]:
    """The reading rule over the valid legs, by label: (outcome, what it turned on). The
    tracemalloc leg is read for its snapshots only, never for a slope."""
    if "default" not in legs:
        return "NO VERDICT", ["no valid default leg"]
    d, w24 = legs["default"]["rss_w24"], legs["default"]["w24"]
    u, r = w24["uordblks_mib"]["rise"], w24["rss_mib"]["rise"]
    why = [f"default W24 slope {d:+.3f} MiB/h a symbol"]
    if u is not None and r:
        why.append(f"annotation: uordblks rose {u / r:.2f} of RSS's rise over W24")
    if d <= budgets.SLOPE_LIMIT_MB_PER_H:
        return "NOT REPRODUCED", why
    leaks = leak_lines(legs["tracemalloc"]["snapshots"]) if "tracemalloc" in legs else None
    moved = [x for x in MOVERS if x in legs and abs(legs[x]["rss_w24"] - d) >= MOVE_MIN]
    missing = [x for x in LEG_ENV if x not in legs]
    why += [f"{x} W24 slope {legs[x]['rss_w24']:+.3f}" for x in MOVERS if x in legs]
    why += [f"LEAK line {line}: +{g:.2f} MiB" for line, g in (leaks or {}).items()]
    if leaks and moved:
        return "MIXED", [*why, f"moved by {', '.join(moved)}: the orchestrator rules"]
    if leaks and not missing:
        share = bars_share(leaks, legs["tracemalloc"]["snapshots"])
        why.append(f"{share:.0%} of the LEAK growth is under candleviewer/bars/")
        return ("LEAK IN BARS" if share >= BARS_SHARE else "LEAK ELSEWHERE"), why
    if leaks == {} and moved:  # the kind: the movers, and what the default's W24 steps add most to
        by: dict[str, float] = {}
        for x in (x for x in legs["default"]["steps"] if _w24(x["t_s"])):
            by[x["by"]] = by.get(x["by"], 0.0) + x["rss_mib"]
        most = max(sorted(by), key=by.__getitem__) if by else "no step"
        return f"FRAGMENTATION ({', '.join(moved)}; steps: {most})", why
    return "INCONCLUSIVE", [*why, f"legs missing or invalid: {', '.join(missing) or 'none'}"]


def judge(root: Path) -> Doc:
    """The rule over the leg reports under `root`, whichever legs have come (for each, a valid one
    before an invalid one, then the latest); writes `memdiag-verdict.json` and `.md` there."""
    found = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(root.rglob("*.json"))]
    docs = [d for d in found if isinstance(d, dict) and d.get("kind") == "memdiag-leg"]
    docs = sorted((d for d in docs if d["label"] in LEG_ENV), key=lambda d: d["finished"])
    legs = {d["label"]: d for d in sorted(docs, key=lambda d: not why_not(d))}  # stable sort
    why = {k: why_not(d) for k, d in legs.items()}
    outcome, reasons = rule({k: d for k, d in legs.items() if not why[k]})
    v: Doc = {"kind": "memdiag-verdict", "version": 1, "outcome": outcome, "reasons": reasons}
    v["missing"] = [k for k in LEG_ENV if k not in legs]
    v["legs"] = {
        k: {"head": d["head"], "rss_w24": d["rss_w24"], "why_not": why[k]} for k, d in legs.items()
    }
    (root / "memdiag-verdict.json").write_text(json.dumps(v, indent=2) + "\n", encoding="utf-8")
    md = [f"# soak_bars memory diagnosis (#399 R4): {outcome}", "", *(f"- {r}" for r in reasons)]
    md += [f"- legs with no report yet: {', '.join(v['missing']) or 'none'}", "", "## Legs", ""]
    for k, leg in v["legs"].items():
        slope = "-" if leg["rss_w24"] is None else f"{leg['rss_w24']:+.3f} MiB/h a symbol"
        md.append(f"- {k} at {leg['head'][:9]}: W24 slope {slope}; {'; '.join(leg['why_not'])}")
    md += ["", "The rule: docs/qa/perf/e12-bars-r4-diagnosis.md", ""]
    (root / "memdiag-verdict.md").write_text("\n".join(md), encoding="utf-8")
    return v


def allocator(env: Mapping[str, str], blocks: int) -> Doc:
    """The allocator variables in `env` and the self-check: pymalloc holds blocks
    (`sys.getallocatedblocks()`) exactly when PYTHONMALLOC is not `malloc`."""
    names = ("PYTHONMALLOC", "PYTHONTRACEMALLOC", "GLIBC_TUNABLES")
    seen = {k: v for k, v in sorted(env.items()) if k in names or k.startswith("MALLOC_")}
    malloc = seen.get("PYTHONMALLOC") == "malloc"
    return {"seen": seen, "pymalloc": blocks > 0, "self_check": (blocks > 0) != malloc}


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _head() -> str:
    """The commit measured: `GITHUB_SHA` in a workflow, else the checkout's HEAD."""
    if sha := os.environ.get("GITHUB_SHA"):
        return sha
    argv = [shutil.which("git") or "git", "rev-parse", "HEAD"]
    done = subprocess.run(argv, capture_output=True, text=True, cwd=_ROOT)  # noqa: S603 #399 git
    return done.stdout.strip() or "unknown"


def leg(a: argparse.Namespace) -> int:
    """One leg: 0 when the soak returned, 1 when it was stopped (its report holds what it had)."""
    sc = load("soak_bars", "full")
    over: Doc = {} if a.hours is None else {"duration_s": a.hours * 3600}
    setup, every = (3 if sc.params.get("bars_specs") else 1), float(sc.p("sample_every_s"))
    alloc = allocator(os.environ, sys.getallocatedblocks())
    meta: Doc = {"kind": "memdiag-leg", "version": 1, "label": a.label, "scenario": sc.name}
    meta |= {"profile": sc.profile, "overrides": over, "symbols": int(sc.p("symbols"))}
    meta["reading"] = not over and not a.tracemalloc and not alloc["seen"]
    meta |= {"head": _head(), "machine_profile": machine_profile(), "glibc": GLIBC}
    meta |= {"python": platform.python_version(), "tracemalloc_frames": a.tracemalloc, "top": a.top}
    meta |= {"allocator": alloc, "started": _now(), "stopped": None}
    a.out_dir.mkdir(parents=True, exist_ok=True)
    jsonl, verdict = a.out_dir / f"{a.label}.jsonl", None

    async def soak(smp: DiagSampler) -> budgets.Verdict:  # SIGTERM (a cancelled job) stops it too
        if (task := asyncio.current_task()) is not None:
            asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, task.cancel)
        async with asyncio.timeout(None if a.deadline_h is None else a.deadline_h * 3600):
            return await run_soak(sc, smp, **over)

    with jsonl.open("w", encoding="utf-8") as fh:
        smp = DiagSampler(fh, setup, every, a.top)
        if a.tracemalloc:
            tracemalloc.start(a.tracemalloc)
        try:
            verdict = asyncio.run(soak(smp))
        except (asyncio.CancelledError, TimeoutError, KeyboardInterrupt) as exc:
            meta["stopped"] = type(exc).__name__
        finally:
            if a.tracemalloc:
                tracemalloc.stop()
    lines = [json.loads(x) for x in jsonl.read_text(encoding="utf-8").splitlines()]
    doc = report(meta, lines, verdict.as_dict() if verdict else None, smp.snapshots)
    out = a.out_dir / f"{a.label}.json"
    out.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"memdiag {a.label}: {doc['samples']} samples, stopped={meta['stopped']} -> {out}")
    return 0 if verdict else 1


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    lg = sub.add_parser("leg", help="run one leg in this process")
    lg.add_argument("--label", required=True, choices=tuple(LEG_ENV))
    lg.add_argument("--hours", type=float, help="scenario hours; any value overrides the profile")
    lg.add_argument("--tracemalloc", type=int, default=0, metavar="N", help="frames; 0: off")
    lg.add_argument("--top", type=int, default=25, metavar="K", help="lines a snapshot diff keeps")
    lg.add_argument("--deadline-h", type=float, help="wall hours after which the leg reports")
    lg.add_argument("--out-dir", type=Path, required=True)
    sub.add_parser("judge", help="the rule over DIR's leg reports").add_argument("dir", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "leg":
        return leg(a)
    print(f"memdiag: {judge(a.dir)['outcome']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
