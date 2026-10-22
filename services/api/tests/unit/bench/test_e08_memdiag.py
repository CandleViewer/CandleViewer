"""#399 R4 memory diagnosis (`bench.ingestion.memdiag`): the snapshot diff, the hourly probes, the
leg report and the reading rule. Unit tests only: `run_soak` is faked, or runs 3 virtual seconds of
the bars path; no soak runs."""

from __future__ import annotations

import asyncio
import ctypes
import gc
import hashlib
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tracemalloc
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from bench.ingestion import budgets, memdiag
from bench.ingestion.budgets import Check, Sample, Verdict
from bench.ingestion.config import SCENARIOS_DIR, Scenario
from bench.ingestion.engine import ProcSampler, ScriptedSampler
from bench.ingestion.memdiag import Doc
from bench.ingestion.runner import run_soak

MiB = 2**20
HERE = "services/api/tests/unit/bench/test_e08_memdiag.py:"
R3 = Check("bars_store_at_cap", "#8", 1000.0, 1000.0, "bars", True)
LIB, BARS = "site-packages/pydantic/main.py:10", "services/api/candleviewer/bars/series_store.py:9"
ELSE = "services/api/candleviewer/ingestion/trade_stream.py:140"


def _b(mib: float) -> int:
    return round(mib * MiB)


def _read(path: Path) -> Doc:
    doc: Doc = json.loads(path.read_text(encoding="utf-8"))
    return doc


def _lines(path: Path) -> list[Doc]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def test_top_growth_ranks_growth_first_new_lines_whole_freed_negative_ties_by_line() -> None:
    prev = {"a:1": (100, 1), "b:2": (50, 5), "c:3": (10, 1), "z:9": (7, 1)}
    cur = {"a:1": (130, 2), "b:2": (80, 6), "d:4": (30, 3), "z:9": (7, 1)}
    got = memdiag.top_growth(prev, cur, 9)
    assert [g["where"] for g in got] == ["a:1", "b:2", "d:4", "z:9", "c:3"]
    assert got[2] == {"where": "d:4", "size": 30, "size_diff": 30, "count": 3, "count_diff": 3}
    assert got[4] == {"where": "c:3", "size": 0, "size_diff": -10, "count": 0, "count_diff": -1}
    shrank = memdiag.top_growth(prev, cur, 3, shrank=True)  # the most shrunk first, ties by line
    assert [g["where"] for g in shrank] == ["c:3", "z:9", "a:1"]


def test_top_growth_has_compare_to_numbers_on_a_real_session() -> None:
    tracemalloc.start(1)
    try:
        before = tracemalloc.take_snapshot().filter_traces(memdiag.DROP)
        held = [bytearray(4096) for _ in range(8)]
        after = tracemalloc.take_snapshot().filter_traces(memdiag.DROP)
    finally:
        tracemalloc.stop()
    nums = ("size", "size_diff", "count", "count_diff")
    want = {
        memdiag.where(d.traceback[0].filename, d.traceback[0].lineno): [getattr(d, k) for k in nums]
        for d in after.compare_to(before, "lineno")
    }
    got = memdiag.top_growth(memdiag.line_map(before)[0], memdiag.line_map(after)[0], len(want))
    assert {g["where"]: [g[k] for k in nums] for g in got} == want
    assert got[0]["where"].startswith(HERE) and got[0]["size_diff"] >= len(held) * 4096


@pytest.mark.parametrize("gc_on", [True, False])
def test_snapshots_diff_the_hour_before_and_hour_2_gc_off_and_back_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gc_on: bool
) -> None:
    a, b, c, g = (("a.py", 1), ("main.py", 5)), (("b.py", 2),), (("c.py", 3),), (("g.py", 7),)
    hours: list[dict[tuple[tuple[str, int], ...], int]] = [  # traces a traceback, newest first
        {a: 100, b: 500, ((memdiag.__file__, 1),): 9999},  # memdiag's own: dropped
        {a: 200, b: 500, c: 50},  # hour 2: the base
        {a: 300, b: 400, c: 60},
        {a: 300, b: 300, c: 50, g: 10},
    ]
    shots = iter(
        [tracemalloc.Snapshot([(0, n, t, len(t)) for t, n in h.items()], 6) for h in hours]
    )
    gc_seen: list[bool] = []

    def take() -> tracemalloc.Snapshot:
        gc_seen.append(gc.isenabled())
        return next(shots)

    monkeypatch.setattr(tracemalloc, "take_snapshot", take)
    monkeypatch.setattr(tracemalloc, "is_tracing", lambda: True)
    (gc.enable if gc_on else gc.disable)()
    try:
        with (tmp_path / "x.jsonl").open("w", encoding="utf-8") as fh:
            smp = memdiag.DiagSampler(fh, 0, 3600.0, 3, ScriptedSampler())  # a top-3
            for _ in range(5):  # t = 0 (no snapshot), then hours 1-4
                smp.sample()
        assert (gc_seen, gc.isenabled()) == ([False] * 4, gc_on)
    finally:
        gc.enable()
    snaps = [x for x in _lines(tmp_path / "x.jsonl") if "hour" in x]  # each a line of its own
    assert [(s["hour"], s["total"]) for s in snaps] == [(1, 600), (2, 750), (3, 760), (4, 660)]
    assert "vs_prev" not in snaps[0] and "vs_h2" not in snaps[1]
    diff = {k: [(x["where"], x["size_diff"]) for x in snaps[3][k]] for k in ("vs_prev", "vs_h2")}
    assert diff["vs_prev"] == [("g.py:7", 10), ("a.py:1", 0), ("c.py:3", -10)]
    assert diff["vs_h2"] == [("a.py:1", 100), ("g.py:7", 10), ("c.py:3", 0)]
    assert [x["where"] for x in snaps[3]["shrank_h2"]] == ["b.py:2"]
    assert snaps[3]["tracebacks"] == {  # the lines that grew since hour 2, frames newest first
        "a.py:1": [{"size": 300, "count": 1, "frames": ["a.py:1", "main.py:5"]}],
        "g.py:7": [{"size": 10, "count": 1, "frames": ["g.py:7"]}],
    }


def test_where_names_a_line_alike_on_every_machine_and_in_a_linked_checkout(tmp_path: Path) -> None:
    root, std = Path(__file__).resolve().parents[5], "/usr/lib/python3.12/json/decoder.py"
    venv = f"{root}/services/api/.venv/lib/python3.12/site-packages/pydantic/main.py"
    assert memdiag.where(venv, 3) == "site-packages/pydantic/main.py:3"
    assert memdiag.where(std, 1) == f"{std}:1"
    assert memdiag.where("<frozen abc>", 0) == "<frozen abc>:0"
    (tmp_path / "co").symlink_to(root)  # a linked checkout: its files named through the link
    linked_py = tmp_path / "co/services/api/bench/ingestion/memdiag.py"
    spec = importlib.util.spec_from_file_location("linked", linked_py)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(linked := importlib.util.module_from_spec(spec))
    assert linked.where(f"{tmp_path}/co/services/api/x.py", 2) == "services/api/x.py:2"


@pytest.mark.parametrize("setup", [1, 3, 4])
def test_sampler_hands_back_every_reading_and_probes_hourly_after_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], setup: int
) -> None:
    soak = ScriptedSampler(base=5 * MiB, slope=MiB)
    monkeypatch.setattr(memdiag, "probes", lambda proc: {"call": soak.n})  # the soak's read first
    with (tmp_path / "leg.jsonl").open("w", encoding="utf-8") as fh:
        smp = memdiag.DiagSampler(fh, setup, 1800.0, 5, soak)  # a probe line every 2nd sample
        got = [smp.sample() for _ in range(setup + 5)]
        lines = _lines(tmp_path / "leg.jsonl")  # flushed, the file still open; not tracing
    assert got == [((5 + c) * MiB, c * 0.01) for c in range(setup + 5)]
    calls = [setup + 1, setup + 3, setup + 5]
    assert [(x["t_s"], x["call"], x["rss"]) for x in lines] == [
        (t, c, (4 + c) * MiB) for t, c in zip((0.0, 3600.0, 7200.0), calls, strict=True)
    ]
    assert capsys.readouterr().out.splitlines() == [  # one flushed progress line a probe
        f"memdiag: t={h} h, RSS {4 + c}.0 MiB" for h, c in enumerate(calls)
    ]


def test_allocator_records_its_settings_and_pythonmalloc_malloc_leaves_no_pymalloc_block() -> None:
    env = {"PYTHONMALLOC": "malloc", "MALLOC_ARENA_MAX": "2", "GLIBC_TUNABLES": "x", "HOME": "/h"}
    seen = {"GLIBC_TUNABLES": "x", "MALLOC_ARENA_MAX": "2", "PYTHONMALLOC": "malloc"}
    assert memdiag.allocator(env, 0) == {"seen": seen, "pymalloc": False, "self_check": True}
    preload = memdiag.allocator({"LD_PRELOAD": "x.so"}, 9, dev_mode=True)["seen"]
    assert preload == {"LD_PRELOAD": "x.so", "dev_mode": "on"}  # `-X dev`: debug hooks
    assert not memdiag.allocator({"PYTHONMALLOC": "malloc"}, 9)["self_check"]
    assert memdiag.allocator({"PYTHONMALLOC": "debug"}, 9)["self_check"]  # pymalloc, hooked
    assert memdiag.allocator({}, 9)["self_check"] and not memdiag.allocator({}, 0)["self_check"]
    argv = [sys.executable, "-c", "import sys; print(sys.getallocatedblocks())"]
    done = subprocess.run(  # noqa: S603 -- fixed argv, no shell (#399)
        argv, env={"PYTHONMALLOC": "malloc"}, capture_output=True, text=True, timeout=60
    )  # not -I: isolated mode ignores PYTHON* variables
    assert (done.returncode, done.stdout.strip()) == (0, "0"), done.stderr


def test_mallinfo2_is_glibcs_struct_and_smaps_and_thp_parse_fixed_text() -> None:
    assert ctypes.sizeof(memdiag._Mallinfo2) == 10 * ctypes.sizeof(ctypes.c_size_t)
    assert memdiag._mallinfo2(None) is None and memdiag._mallinfo2("musl 1.2.5") is None
    before = memdiag.mallinfo2()
    held, big = [bytearray(100_000) for _ in range(64)], bytearray(64 * MiB)  # the heap; an mmap
    after = memdiag.mallinfo2()
    if memdiag._MALLINFO2 is None:  # no glibc mallinfo2 (musl, macOS): no reading, none made up
        assert (before, after) == (None, None)
    else:
        assert before is not None and after is not None and set(after) == set(memdiag.MALLINFO)
        assert after["arena"] == after["uordblks"] + after["fordblks"]
        assert after["uordblks"] - before["uordblks"] >= len(held) * 100_000
        assert after["hblkhd"] - before["hblkhd"] >= len(big)
    rollup = "55d4c8a00000-7ffd5b1f2000 ---p 00000000 00:00 0    [rollup]\nRss:  204800 kB\n"
    rollup += "Pss:  190000 kB\nAnonymous:  180224 kB\nAnonHugePages:  40960 kB\n"
    want = {"Rss": 200 * MiB, "Anonymous": 176 * MiB, "AnonHugePages": 40 * MiB}
    assert memdiag.smaps(rollup) == want and memdiag.smaps("Rss:   4 kB\n") is None
    assert memdiag.thp_mode("always [madvise] never\n") == "madvise"
    assert memdiag.thp_mode("[always] madvise never") == "always" and memdiag.thp_mode(None) is None


def _probe(t_h: float, heap: float, huge: float, used: float, free: float) -> Doc:
    mi = {"arena": _b(heap), "hblkhd": 0, "uordblks": _b(used), "fordblks": _b(free)}
    return {
        "t_s": t_h * 3600,
        "rss": 0,
        "blocks": 0,
        "mi": mi,
        "smaps": {"AnonHugePages": _b(huge)},
    }


def test_window_is_per_symbol_and_steps_are_curve_rises_put_down_by_the_probes_either_side() -> (
    None
):
    hours = [
        {"t_s": h * 3600.0, "rss": (100 + 3 * h) * MiB, "blocks": 30 * h, "smaps": None}
        | {"mi": {"arena": (50 + 3 * h) * MiB, "hblkhd": 0, "uordblks": 0, "fordblks": 0}}
        for h in range(25)
    ]
    w24 = memdiag.window(hours, 3)  # 3 symbols: 1 MiB/h each, 12 MiB over hours 12-24
    assert (w24["rss_mib"]["slope"], w24["rss_mib"]["rise"]) == pytest.approx((1, 12))
    assert (w24["blocks"]["slope"], w24["arena_hblkhd_mib"]["slope"]) == pytest.approx((10, 1))
    assert w24["anon_huge_mib"] == {"slope": None, "rise": None}
    probes = [_probe(0, 50, 0, 40, 10), _probe(1, 50.5, 1, 40, 10), _probe(2, 50.5, 1, 40, 10)]
    probes.append(_probe(3, 50.5, 3, 44, 6))
    mib = {0: 100.0, 60: 100.0, 120: 101.0, 180: 101.5, 3600: 101.5, 3660: 103.5, 7260: 107.5}
    got = memdiag.steps({str(t): y for t, y in mib.items()}, probes)  # 0.5 MiB at 180 s: no step
    assert [(x["t_s"], x["rss_mib"], x["by"]) for x in got] == [
        (120.0, 1.0, "glibc"),  # a step of exactly STEP_MIB; the heap rose half of it
        (3660.0, 2.0, "other"),  # the probe at 3600 s is the one before it
        (7260.0, 4.0, "thp"),  # AnonHugePages rose half of it
    ]
    assert (got[2]["uordblks_mib"], got[2]["fordblks_mib"]) == (4.0, -4.0)


def _snaps(
    lines: Mapping[str, Sequence[float | None]], total: Sequence[float] = (), tbs: Doc | None = None
) -> list[Doc]:
    """Hourly snapshot lines from hour 2: each line's size (MiB; None: out of that hour's top-N)
    and the filtered total (MiB; by default 100 more than the lines), diffed against hour 2."""
    out: list[Doc] = []
    for n in range(max(map(len, lines.values()))):
        at = {w: x for w, v in lines.items() if n < len(v) and (x := v[n]) is not None}
        top = [
            {"where": w, "size": _b(x), "size_diff": _b(x) - _b(lines[w][0] or 0)}
            for w, x in at.items()
        ]
        rec = {"hour": 2 + n, "total": _b(total[n] if total else 100 + sum(at.values()))}
        out.append(rec | {"tracebacks": tbs or {}} | ({"vs_h2": top} if n else {}))
    return out


@pytest.mark.parametrize(
    ("mib", "total", "growth"),
    [
        ([0, 0.2, 0.4, 0.6, 0.8, 1.0], (), 1.0),  # 6 snapshots (hours 2-7) and +1 MiB: a LEAK line
        ([0, 0.25, 0.5, 0.75, 1.0], (), None),  # 5 snapshots
        ([0, 0.19, 0.38, 0.57, 0.76, 0.95], (), None),  # under the growth floor
        ([0, 0.5, 0.4, 0.9, 1.4, 1.9, 2.4], (), None),  # the dip restarts the run: 5 after it
        ([0, 0.5, 0.4, 0.9, 1.4, 1.9, 2.4, 2.9], (), 2.5),  # and 6 from the dip on
        ([0, 0.3, 0.6, 0.6, 0.9, 1.2, 1.5, 1.8], (), None),  # a flat hour restarts it too
        ([0, 0.3, 0.6, None, 0.9, 1.2, 1.5, 1.8, 2.1], (), None),  # so does an hour out of the top
        ([5, 5.0001, 5.0002, 5.0003, 5.0004, 5.0005], (100, 101, 102, 103, 104, 105), None),  # base
        ([0, 1, 2, 3, 4, 5, 0, 0.2, 0.4, 0.6, 0.8, 1.0], (), 5.0),  # its largest run
        ([0, 0.4, 0.8, 1.2, 1.6, 2.0], (100, 99.8, 99.6, 99.4, 99.2, 99.0), None),  # B1: turnover
        ([0, 0.4, 0.8, 1.2, 1.6, 2.0], (100, 100.2, 100.4, 100.6, 100.8, 100.95), None),  # < 1 MiB
        ([0, 0.5, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4], (100, 102, 102, 102, 102, 102, 102, 102.5), None),
    ],
)
def test_a_leak_line_grows_strictly_over_six_hourly_snapshots_by_a_mib_and_the_total_too(
    mib: list[float | None], total: tuple[float, ...], growth: float | None
) -> None:
    want = {} if growth is None else {"a/b.py:1": pytest.approx(growth)}
    assert memdiag.leak_lines(_snaps({"a/b.py:1": mib}, total)) == want


def _tb(*frames: str, size: int = 1) -> Doc:
    return {"size": size, "count": 1, "frames": [LIB, *frames]}


@pytest.mark.parametrize(
    ("tbs", "share"),
    [
        ([{LIB: [_tb(ELSE)]}, {LIB: [_tb(BARS)]}], 1.0),  # the last snapshot that holds one
        ([{LIB: [_tb(BARS)]}, {}], 1.0),
        ([{LIB: [_tb(BARS, size=9), _tb(ELSE)]}], 1.0),  # its biggest traceback
        ([{LIB: [_tb(ELSE, BARS)]}], 0.0),  # that traceback's newest repo frame
        ([{}], 0.0),  # none kept: the library line itself, so elsewhere
    ],
)
def test_bars_share_owns_a_library_line_by_its_last_biggest_tracebacks_newest_repo_frame(
    tbs: list[Doc], share: float
) -> None:
    snaps = [{"hour": 3 + i, "tracebacks": x} for i, x in enumerate(tbs)]
    assert memdiag.bars_share({LIB: 2.0}, snaps) == share


def test_report_slopes_r4s_window_a_symbol_as_check_plateau_does_and_aligns_on_the_calls() -> None:
    ts = range(0, 86401, 60)  # 1441 samples: 50 B/s before hour 12, 7 B/s after
    rss = [200 * MiB + 50 * min(t, 43200) + 7 * max(0, t - 43200) for t in ts]
    samples = [Sample(float(t), r, 0.0, 0.0, 0, 0) for t, r in zip(ts, rss, strict=True)]
    r4 = budgets.check_plateau(samples, 3, 43200.0, 150 * MiB)
    verdict = {"metrics": {"_curve": {f"{s.t_s:.0f}": s.rss_bytes / MiB for s in samples}}}
    base = {"blocks": 1, "mi": None, "smaps": None}
    lines = [base | {"t_s": float(t), "rss": rss[t // 60]} for t in range(0, 86401, 3600)]
    meta = {"symbols": 3, "tracemalloc_frames": 0, "setup": 3, "calls": 3 + len(samples)}
    doc = memdiag.report(meta, lines, verdict)
    assert (doc["rss_w24"], doc["aligned"]) == (pytest.approx(r4.measured, abs=1e-12), True)
    assert (doc["samples"], doc["last_t_s"]) == (1441, 86400.0)
    assert not memdiag.report(meta | {"calls": 4 + len(samples)}, lines, verdict)["aligned"]
    assert not memdiag.report(meta, [lines[0] | {"rss": 0}, *lines[1:]], verdict)["aligned"]
    assert not memdiag.report(meta | {"calls": 3}, [], None)["aligned"]  # no curve: no alignment
    traced = memdiag.report(meta | {"tracemalloc_frames": 6}, lines, verdict)
    assert (traced["rss_w24"], traced["w24"]) == (None, None)  # a traced leg is never sloped


def _leg(label: str, w24: float = 0.3, rise: float = 3.0, **kw: Any) -> Doc:
    """A valid leg report with what the rule reads: W24 slope `w24` and net rise `rise` (MiB a
    symbol), a flat line and a flat total, one glibc step in W24."""
    tm = label == "tracemalloc"
    r4 = Check("rss_plateau_slope", "#8", w24, 0.18, "MB/h", w24 <= 0.18)
    doc: Doc = {"kind": "memdiag-leg", "label": label, "stopped": None, "symbols": 3, "top": 100}
    doc |= dict.fromkeys(memdiag.ALIKE, "same") | {"finished": "2026-10-23T00:00:00Z"}
    doc |= {"aligned": True, "reading": label == "default", "overrides": {}}
    doc |= {"last_t_s": 43200.0 if tm else 86400.0, "tracemalloc_frames": 6 if tm else 0}
    doc |= {"allocator": {"seen": dict(memdiag.LEG_ENV[label]), "self_check": True}}
    doc |= {"verdict": {"checks": [asdict(R3), asdict(r4)]}, "rss_w24": None if tm else w24}
    doc |= {"snapshots": _snaps({"a/b.py:1": [1.0] * 11}), "steps": _steps((14, 3.9, "glibc"))}
    return doc | {"w24": {"uordblks_mib": {"rise": 0.5}, "rss_mib": {"rise": rise}}} | kw


def _steps(*steps: tuple[float, float, str]) -> list[Doc]:
    return [{"t_s": h * 3600, "rss_mib": mib, "by": by} for h, mib, by in steps]


def _heap(mib_h: float, snaps: list[Doc] | None = None) -> Doc:
    """A tracemalloc leg: a flat line and a filtered total that grows `mib_h` MiB an hour."""
    total = [100 + mib_h * h for h in range(11)]
    return _leg("tracemalloc", snapshots=snaps or _snaps({"a/b.py:1": [1.0] * 11}, total))


_UP = {LIB: [0.4 * h for h in range(11)], "a/c.py:2": [0.3 * h for h in range(11)]}  # hours 2-12
D, TM, M, MM = (_leg(x) for x in memdiag.LEG_ENV)
TL = _leg("tracemalloc", snapshots=_snaps(_UP))  # two LEAK lines: +4.0 and +3.0 MiB
TL_BARS = _leg("tracemalloc", snapshots=_snaps(_UP, tbs={LIB: [_tb(BARS)]}))  # 4.0 via bars/
TL_HALF = _heap(0, _snaps({LIB: _UP[LIB], "c.py:2": _UP[LIB]}, tbs={LIB: [_tb(BARS)]}))
DOWN = {"w24": 0.21, "rise": 1.92}  # below the default's 0.3 and 3.0 by MOVE_MIN and 12 times it
MM_DOWN, M_DOWN = _leg("mmap128k", **DOWN), _leg("malloc", **DOWN)
TURNOVER = _snaps(_UP, total=[100 - 0.3 * h for h in range(11)])  # B1: builders up, total down
TURNOVER[-1]["shrank_h2"] = [{"where": "candleviewer/bars/reader.py:573", "size_diff": -_b(1.5)}]
D_OTHER = _leg("default", steps=_steps((14, 3.9, "other")))
D_MIX = _leg("default", steps=_steps((14, 3, "glibc"), (15, 1, "other"), (6, 10, "other")))
UNREAD, FRAG = {"reading": False, "overrides": {"duration_s": 3600.0}}, "FRAGMENTATION (mmap128k; s"
UNFOLDED = [asdict(R3), asdict(R3) | {"name": "bars_closes_folded", "passed": False}]


@pytest.mark.parametrize(
    ("label", "change", "reason"),
    [
        ("default", {"verdict": None, "stopped": "SIGTERM"}, "no verdict (stopped: SIGTERM)"),
        ("default", {"last_t_s": 86399.0}, "ends at t=86399 s, before 86400 s"),
        ("tracemalloc", {"last_t_s": 43199.0}, "ends at t=43199 s, before 43200 s"),
        ("malloc", {"verdict": {"checks": UNFOLDED}}, "R3 bars_closes_folded failed"),
        ("malloc", {"allocator": {"seen": {}, "self_check": True}}, "allocator not as declared"),
        ("malloc", {"allocator": M["allocator"] | {"self_check": False}}, "allocator not as"),
        ("default", {"tracemalloc_frames": 6}, "tracemalloc frames: 6"),
        ("tracemalloc", {"tracemalloc_frames": 5}, "tracemalloc: 5 frames, top 100"),
        ("tracemalloc", {"top": 25}, "tracemalloc: 6 frames, top 25"),
        ("tracemalloc", {"snapshots": _snaps({"a/b.py:1": [1.0] * 10})}, "tracemalloc: 6 frames"),
        ("default", UNREAD, "not a reading: overrides {'duration_s': 3600.0}"),
        ("default", {"rss_w24": 0.31}, "W24 slope 0.31 is not R4's 0.3"),
        ("default", {"aligned": False}, "probe lines not aligned with the soak's samples"),
        *(("mmap128k", {k: "x"}, f"not comparable with the default: {k}") for k in memdiag.ALIKE),
    ],
)
def test_why_not_names_each_reason_a_leg_is_no_reading(
    label: str, change: Doc, reason: str
) -> None:
    assert memdiag.why_not(_leg(label), D) == []
    why = memdiag.why_not(_leg(label) | change, D)
    assert len(why) == 1 and why[0].startswith(reason), why


@pytest.mark.parametrize(
    ("legs", "outcome", "reason"),
    [
        ([_leg("default", 0.15)], "NOT REPRODUCED", "default W24 slope +0.150"),
        ([_leg("default", budgets.SLOPE_LIMIT_MB_PER_H)], "NOT REPRODUCED", ""),  # at the limit
        ([_leg("default", 0.2)], "INCONCLUSIVE", "invalid: tracemalloc, malloc, mmap128k"),
        ([], "NO VERDICT", "no valid default leg"),
        ([D | {"verdict": {"checks": UNFOLDED}}, TM, M, MM], "NO VERDICT", ""),
        ([D | UNREAD, TM, M, MM], "NO VERDICT", ""),
        ([D, TL_BARS, M, MM], "LEAK IN BARS", "57% of the LEAK growth is under candleviewer/bars/"),
        ([D, TL_HALF, M, MM], "LEAK IN BARS", "50% of"),
        ([D, TL, M, MM], "LEAK ELSEWHERE", "0% of"),
        ([D, TL, M, MM], "LEAK ELSEWHERE", "LEAK growth +7.00 MiB, the default's W24 rise +9.00"),
        ([D, TL, M_DOWN, MM], "MIXED", "moved by malloc"),
        ([D, TM, M, MM_DOWN], FRAG, "mmap128k W24 slope +0.210 MiB/h, net rise +1.92 MiB"),
        ([D_OTHER, TM, M_DOWN, MM], "FRAGMENTATION (malloc; steps: other)", ""),
        ([D, TM, M_DOWN, MM], "INCONCLUSIVE", "moved by malloc; glibc steps call for mmap128k"),
        ([D, TM, M, _leg("mmap128k", 0.4, 1.92)], "INCONCLUSIVE", "annotation: mmap128k raises"),
        ([D, TM, M, _leg("mmap128k", 0.2, 4.2)], "INCONCLUSIVE", "net rise +4.20 MiB"),  # M2
        ([D, TM, M, MM_DOWN | {"w24": {"rss_mib": {"rise": None}}}], "INCONCLUSIVE", "rise - MiB"),
        ([D, _heap(0.3), M, MM_DOWN], "INCONCLUSIVE", "Python heap grows, not attributed to a"),
        ([D, _heap(0.26), M, MM_DOWN], FRAG, "filtered traced total +2.60 MiB over hours 2-12"),
        ([D, _heap(0, TURNOVER), M, MM_DOWN], FRAG, "filtered traced total -3.00 MiB"),  # B1
        ([D, _heap(0, TURNOVER), M, MM], "INCONCLUSIVE", "annotation: candleviewer/bars/reader."),
        ([D_MIX, TM, M, MM_DOWN], FRAG, ""),  # the most of W24's steps, not of the whole run's
        ([D, M, MM_DOWN], "INCONCLUSIVE", "missing or invalid: tracemalloc"),  # no FRAGMENTATION
        ([D, TM | {"rss_w24": 9.9}, M, MM], "INCONCLUSIVE", "invalid: none"),  # never sloped
        ([D, TL, M], "INCONCLUSIVE", "missing or invalid: mmap128k"),  # MIXED not ruled out
        ([D, M | {"verdict": None}, MM], "INCONCLUSIVE", "missing or invalid: tracemalloc, malloc"),
        ([D, TM, M, MM_DOWN | {"head": "x"}], "INCONCLUSIVE", "invalid: mmap128k"),  # M3
        ([_leg("default", rise=0.0)], "INCONCLUSIVE", "net rise +0.00 MiB"),  # no rise to divide by
    ],
)
def test_judge_applies_the_reading_rule_to_the_valid_legs(
    tmp_path: Path, legs: list[Doc], outcome: str, reason: str
) -> None:
    for i, doc in enumerate(legs):
        (tmp_path / f"{i}-{doc['label']}.json").write_text(json.dumps(doc), encoding="utf-8")
    v, labels = memdiag.judge(tmp_path), {d["label"] for d in legs}
    assert v["outcome"].startswith(outcome) and any(reason in r for r in v["reasons"]), v
    assert v["missing"] == [x for x in memdiag.LEG_ENV if x not in labels]
    md = (tmp_path / "memdiag-verdict.md").read_text(encoding="utf-8")
    assert md.startswith(f"# soak_bars memory diagnosis (#399 R4): {v['outcome']}\n")


def test_judge_picks_a_valid_report_then_the_latest_and_skips_what_it_cannot_read(
    tmp_path: Path,
) -> None:
    late = {"finished": "2026-10-24T00:00:00Z"}
    files: dict[str, object] = {
        "a/default.json": D,
        "b/default.json": _leg("default", 0.31) | late | {"aligned": False},  # newer, invalid
        "c/mmap128k.json": _leg("mmap128k", 0.25),
        "d/mmap128k.json": MM_DOWN | late,  # two valid reports: the latest
        "e/arena2.json": D | {"label": "arena2"},  # no such leg
        "f/list.json": [1, 2],
        "g/verdict.json": {"kind": "memdiag-verdict"},
        "h.json": {"kind": "memdiag-leg", "label": "malloc"},  # lacks what the rule reads
    }
    for name, doc in files.items():
        (tmp_path / name).parent.mkdir(exist_ok=True)
        (tmp_path / name).write_text(json.dumps(doc), encoding="utf-8")
    (tmp_path / "i.json").write_text('{"kind": "memdiag-leg", "label": "de', encoding="utf-8")
    v = memdiag.judge(tmp_path)
    assert memdiag.judge(tmp_path) == v  # it reads past its own verdict
    assert {k: x["rss_w24"] for k, x in v["legs"].items()} == {"default": 0.3, "mmap128k": 0.21}
    assert v["skipped"] == ["h.json: KeyError", "i.json: JSONDecodeError"]  # i.json: cut short
    md = (tmp_path / "memdiag-verdict.md").read_text(encoding="utf-8")
    assert (
        "\n- default at same: W24 slope +0.300 MiB/h a symbol; rises h14.00 +3.90 MiB glibc\n" in md
    )
    assert "\n- skipped, unreadable: i.json: JSONDecodeError\n" in md
    assert not list(tmp_path.rglob("*.tmp")) and memdiag.main(["judge", str(tmp_path / "no")]) == 2


def _clean(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    """A reading's environment (no allocator setting) plus `env`, at a fixed commit."""
    monkeypatch.setenv("GITHUB_SHA", "f" * 40)
    for name in memdiag.allocator(os.environ, 1)["seen"]:
        monkeypatch.delenv(name)
    for name, value in env.items():
        monkeypatch.setenv(name, value)


def _soak(n: int, how: str = "") -> Callable[..., Awaitable[Verdict]]:
    """A `run_soak` stand-in: the bars path's 3 setup calls and `n` samples 60 s apart, then a
    verdict, unless `how` stops it: a signal it sends itself, the deadline it waits for, a crash."""

    async def run(sc: Scenario, sampler: ProcSampler, **over: Any) -> Verdict:
        assert (sc.name, sc.profile) == ("soak_bars", "full")
        for _ in range(3):
            sampler.sample()
        curve = {f"{60 * k}": sampler.sample()[0] / MiB for k in range(n)}
        if how == "crash":
            raise RuntimeError("the soak died")
        if how:  # wait for what stops the leg: the signal it sends itself, or the deadline
            if how != "deadline":
                os.kill(os.getpid(), getattr(signal, how))
            try:
                await asyncio.wait_for(asyncio.Event().wait(), 5.0)
            except TimeoutError:
                raise RuntimeError("nothing stopped the leg") from None
        return Verdict(sc.name, [R3], {"_curve": curve})

    return run


def test_a_default_leg_reports_the_runners_verdict_and_a_traced_leg_its_snapshots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = ["--out-dir", str(tmp_path)]
    _clean(monkeypatch)
    monkeypatch.setattr(memdiag, "run_soak", _soak(61))  # the unchanged scenario
    assert memdiag.main(["leg", "--label", "default", *out]) == 0
    doc = _read(tmp_path / "default.json")
    sha = hashlib.sha256((SCENARIOS_DIR / "soak_bars.json").read_bytes()).hexdigest()
    assert (doc["reading"], doc["overrides"], doc["aligned"]) == (True, {}, True)
    assert (doc["scenario_sha256"], doc["setup"], doc["calls"], doc["samples"]) == (sha, 3, 64, 61)
    assert doc["verdict"]["checks"] == [asdict(R3)] and doc["head"] == "f" * 40
    assert [p["t_s"] for p in doc["probes"]] == [0, 3600] and doc["w24"]["rss_mib"]["slope"] is None
    argv = ["leg", "--label", "tracemalloc", "--hours", "12", "--tracemalloc", "1", *out]
    assert memdiag.main(argv) == 0 and not tracemalloc.is_tracing()
    doc = _read(tmp_path / "tracemalloc.json")
    assert (doc["reading"], doc["overrides"]) == (False, {"duration_s": 43200.0})
    assert (doc["rss_w24"], doc["w24"], [s["hour"] for s in doc["snapshots"]]) == (None, None, [1])
    tracemalloc.start(1)  # as `-X tracemalloc` would: traced from the start, so no default leg
    try:
        assert memdiag.main(["leg", "--label", "default", "--out-dir", str(tmp_path / "x")]) == 2
    finally:
        tracemalloc.stop()
    assert memdiag.main(["judge", str(tmp_path)]) == 0
    v = _read(tmp_path / "memdiag-verdict.json")
    assert (v["outcome"], v["missing"]) == ("NO VERDICT", ["malloc", "mmap128k"])
    assert v["legs"]["default"]["why_not"][0] == "ends at t=3600 s, before 86400 s"
    monkeypatch.delenv("GITHUB_SHA")
    monkeypatch.setattr(shutil, "which", lambda name: "/nonexistent/git")  # no git here
    assert memdiag._head() == "unknown"


@pytest.mark.parametrize(
    ("how", "argv", "stopped"),
    [
        ("SIGTERM", [], "CancelledError"),  # a cancelled job
        ("SIGINT", [], "KeyboardInterrupt"),
        ("deadline", ["--deadline-h", "1e-6"], "TimeoutError"),
        ("crash", [], "RuntimeError"),  # recorded, then raised
    ],
)
def test_a_stopped_or_crashed_leg_reports_what_it_had_and_stops_tracing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, how: str, argv: list[str], stopped: str
) -> None:
    _clean(monkeypatch)
    monkeypatch.setattr(memdiag, "run_soak", _soak(61, how))
    run = ["leg", "--label", "tracemalloc", "--tracemalloc", "1", "--out-dir", str(tmp_path), *argv]
    if how == "crash":
        with pytest.raises(RuntimeError, match="the soak died"):
            memdiag.main(run)
    else:
        assert memdiag.main(run) == 1
    doc = _read(tmp_path / "tracemalloc.json")
    assert (doc["stopped"], doc["verdict"], doc["calls"]) == (stopped, None, 64)
    assert [s["hour"] for s in doc["snapshots"]] == [1] and not tracemalloc.is_tracing()


@pytest.mark.parametrize(
    ("label", "env", "argv", "reading"),
    [
        ("default", {}, [], True),
        ("default", {}, ["--hours", "1"], False),  # an override
        ("tracemalloc", {}, ["--tracemalloc", "6"], False),  # traced, though 24 h
        ("mmap128k", {"MALLOC_MMAP_THRESHOLD_": "131072"}, [], False),  # an allocator variable
        ("default", {"MALLOC_ARENA_MAX": "2"}, [], None),  # None: refused before the soak
        ("default", {"LD_PRELOAD": "libjemalloc.so.2"}, [], None),
        ("default", {}, ["--tracemalloc", "6"], None),
        ("tracemalloc", {}, [], None),
        ("mmap128k", {}, [], None),
        ("malloc", {"PYTHONMALLOC": "malloc"}, [], None),  # set too late: pymalloc holds blocks
    ],
)
def test_a_leg_is_a_reading_only_unchanged_and_refuses_an_environment_not_its_labels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    label: str,
    env: Doc,
    argv: list[str],
    reading: bool | None,
) -> None:
    _clean(monkeypatch, **env)
    monkeypatch.setattr(memdiag, "run_soak", _soak(2))
    code = memdiag.main(["leg", "--label", label, "--out-dir", str(tmp_path), *argv])
    got = _read(tmp_path / f"{label}.json")["reading"] if code == 0 else None
    assert (code, got) == ((2, None) if reading is None else (0, reading))


def test_the_bars_soak_takes_three_setup_samples_and_a_leg_aligns_on_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real engine for 3 virtual seconds, one symbol, one series: 3 calls before t=0."""
    _clean(monkeypatch)
    short = {"symbols": ("BTCUSDT",), "duration_s": 3.0, "sample_every_s": 1.0, "warmup_s": 0.0}
    short |= {"warmup_wall_s": 0.0, "bars_specs": 1, "bars_state_root": tmp_path / "state"}

    async def run(sc: Scenario, sampler: ProcSampler, **over: Any) -> Verdict:
        return await run_soak(sc, sampler, **over, **short)

    monkeypatch.setattr(memdiag, "run_soak", run)
    assert memdiag.main(["leg", "--label", "default", "--out-dir", str(tmp_path)]) == 0
    doc = _read(tmp_path / "default.json")
    assert (doc["setup"], doc["calls"], doc["samples"], doc["aligned"]) == (3, 7, 4, True)
