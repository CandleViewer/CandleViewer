"""#399 R4 memory diagnosis (`bench.ingestion.memdiag`): the snapshot diff, the hourly probes, the
leg report and the reading rule. Unit tests only: `run_soak` is faked, no soak runs."""

from __future__ import annotations

import asyncio
import ctypes
import dataclasses
import json
import os
import subprocess
import sys
import tracemalloc
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from bench.ingestion import memdiag
from bench.ingestion.budgets import Check, Verdict
from bench.ingestion.config import Scenario
from bench.ingestion.engine import ProcSampler, ScriptedSampler
from bench.ingestion.memdiag import Doc

MiB = 2**20
HERE = "services/api/tests/unit/bench/test_e08_memdiag.py:"
R3 = Check("bars_store_at_cap", "#8", 1000.0, 1000.0, "bars", True)


def test_top_growth_ranks_growth_first_new_lines_whole_freed_negative_ties_by_line() -> None:
    prev = {"a:1": (100, 1), "b:2": (50, 5), "c:3": (10, 1), "z:9": (7, 1)}
    cur = {"a:1": (130, 2), "b:2": (80, 6), "d:4": (30, 3), "z:9": (7, 1)}
    got = memdiag.top_growth(prev, cur, 9)
    assert [g["where"] for g in got] == ["a:1", "b:2", "d:4", "z:9", "c:3"]
    assert got[2] == {"where": "d:4", "size": 30, "size_diff": 30, "count": 3, "count_diff": 3}
    assert got[4] == {"where": "c:3", "size": 0, "size_diff": -10, "count": 0, "count_diff": -1}


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


def test_hourly_snapshot_diffs_the_hour_before_and_names_the_grown_line(tmp_path: Path) -> None:
    held: list[bytearray] = []
    with (tmp_path / "x.jsonl").open("w", encoding="utf-8") as fh:
        smp = memdiag.DiagSampler(fh, 1, 1800.0, 5, ScriptedSampler())
        tracemalloc.start(2)
        try:
            for call in range(6):  # setup; then t = 0, 1800, 3600 (hour 1), 5400, 7200 (hour 2)
                if call == 4:
                    held.extend(bytearray(65536) for _ in range(4))
                smp.sample()
        finally:
            tracemalloc.stop()
    assert [s["hour"] for s in smp.snapshots] == [1, 2] and "vs_prev" not in smp.snapshots[0]
    top = smp.snapshots[1]["vs_prev"][0]
    assert top["where"].startswith(HERE) and top["size_diff"] >= 4 * 65536
    assert smp.snapshots[1]["tracebacks"][top["where"]][0]["frames"][0] == top["where"]


def test_where_is_repo_relative_or_site_packages_else_as_given() -> None:
    root, std = Path(__file__).resolve().parents[5], "/usr/lib/python3.12/json/decoder.py"
    venv = f"{root}/services/api/.venv/lib/python3.12/site-packages/pydantic/main.py"
    assert memdiag.where(venv, 3) == "site-packages/pydantic/main.py:3"
    assert memdiag.where(std, 1) == f"{std}:1"
    assert memdiag.where("<frozen abc>", 0) == "<frozen abc>:0"


@pytest.mark.parametrize("setup", [1, 3, 4])
def test_sampler_hands_back_every_reading_and_probes_hourly_after_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, setup: int
) -> None:
    soak = ScriptedSampler(base=5 * MiB, slope=MiB)
    monkeypatch.setattr(memdiag, "probes", lambda proc: {"call": soak.n})  # the soak's read first
    with (tmp_path / "leg.jsonl").open("w", encoding="utf-8") as fh:
        smp = memdiag.DiagSampler(fh, setup, 1800.0, 0, soak)  # a probe line every 2nd sample
        got = [smp.sample() for _ in range(setup + 5)]
        text = (tmp_path / "leg.jsonl").read_text(encoding="utf-8")  # flushed, the file still open
    assert got == [((5 + c) * MiB, c * 0.01) for c in range(setup + 5)]
    lines, calls = [json.loads(x) for x in text.splitlines()], [setup + 1, setup + 3, setup + 5]
    assert [(x["t_s"], x["call"], x["rss"]) for x in lines] == [
        (t, c, (4 + c) * MiB) for t, c in zip((0.0, 3600.0, 7200.0), calls, strict=True)
    ]


def test_allocator_records_its_variables_and_pythonmalloc_malloc_leaves_no_pymalloc_block() -> None:
    env = {"PYTHONMALLOC": "malloc", "MALLOC_ARENA_MAX": "2", "GLIBC_TUNABLES": "x", "HOME": "/h"}
    seen = {"GLIBC_TUNABLES": "x", "MALLOC_ARENA_MAX": "2", "PYTHONMALLOC": "malloc"}
    assert memdiag.allocator(env, 0) == {"seen": seen, "pymalloc": False, "self_check": True}
    assert not memdiag.allocator({"PYTHONMALLOC": "malloc"}, 9)["self_check"]
    assert memdiag.allocator({}, 9)["self_check"] and not memdiag.allocator({}, 0)["self_check"]
    argv = [sys.executable, "-c", "import sys; print(sys.getallocatedblocks())"]
    env = {"PYTHONMALLOC": "malloc"}  # not -I: isolated mode ignores PYTHON* variables
    done = subprocess.run(argv, env=env, capture_output=True, text=True)  # noqa: S603 #399
    assert done.stdout.strip() == "0"


def test_mallinfo2_is_glibcs_ten_size_t_and_smaps_and_thp_parse_fixed_text() -> None:
    assert ctypes.sizeof(memdiag._Mallinfo2) == 10 * ctypes.sizeof(ctypes.c_size_t)
    assert memdiag._mallinfo2(None) is None and memdiag._mallinfo2("musl 1.2.5") is None
    got = memdiag.mallinfo2()  # the test runner's glibc
    assert got is not None and set(got) == set(memdiag.MALLINFO) and got["arena"] > 0
    rollup = "55d4c8a00000-7ffd5b1f2000 ---p 00000000 00:00 0    [rollup]\nRss:  204800 kB\n"
    rollup += "Pss:  190000 kB\nAnonymous:  180224 kB\nAnonHugePages:  40960 kB\n"
    want = {"Rss": 200 * MiB, "Anonymous": 176 * MiB, "AnonHugePages": 40 * MiB}
    assert memdiag.smaps(rollup) == want and memdiag.smaps("Rss:   4 kB\n") is None
    assert memdiag.thp_mode("always [madvise] never\n") == "madvise"
    assert memdiag.thp_mode("[always] madvise never") == "always" and memdiag.thp_mode(None) is None


def test_window_is_per_symbol_and_steps_name_the_counter_that_rose_with_rss() -> None:
    hours = [
        {"t_s": h * 3600.0, "rss": (100 + 3 * h) * MiB, "blocks": 30 * h, "smaps": None}
        | {"mi": {"arena": (50 + 3 * h) * MiB, "hblkhd": 0, "uordblks": 0}}
        for h in range(25)
    ]
    w24 = memdiag.window(hours, 3)  # 3 symbols: 1 MiB/h each, 12 MiB over hours 12-24
    assert (w24["rss_mib"]["slope"], w24["rss_mib"]["rise"]) == pytest.approx((1, 12))
    assert (w24["blocks"]["slope"], w24["arena_hblkhd_mib"]["slope"]) == pytest.approx((10, 1))
    assert w24["anon_huge_mib"] == {"slope": None, "rise": None}
    assert [x["by"] for x in memdiag.steps(hours)] == ["glibc"] * 24
    rises = enumerate([(0, 0), (2, 2), (4, 2), (4.5, 2)])  # RSS and AnonHugePages, MiB
    huge = [
        {"t_s": 60.0 * i, "rss": r * MiB, "mi": None, "smaps": {"AnonHugePages": a * MiB}}
        for i, (r, a) in rises
    ]
    assert [(x["t_s"], x["by"]) for x in memdiag.steps(huge)] == [(60.0, "thp"), (120.0, "other")]


def _snaps(lines: Mapping[str, Sequence[float]], tbs: Doc | None = None) -> list[Doc]:
    """Hourly snapshots from hour 3, their top-N since hour 2 holding `lines` (MiB, hour 2 on)."""
    out: list[Doc] = []
    for h in range(3, 2 + max(map(len, lines.values()))):
        n = h - 2
        at = {w: (round(v[n] * MiB), round(v[0] * MiB)) for w, v in lines.items() if n < len(v)}
        top = [{"where": w, "size": s, "size_diff": s - s2} for w, (s, s2) in at.items()]
        out.append({"hour": h, "tracebacks": tbs or {}, "vs_h2": top})
    return out


@pytest.mark.parametrize(
    ("mib", "growth"),
    [
        ([0, 0.2, 0.4, 0.6, 0.8, 1.0], 1.0),  # 6 snapshots (hours 2-7) and +1 MiB: a LEAK line
        ([0, 0.25, 0.5, 0.75, 1.0], None),  # 5 snapshots
        ([0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6], None),  # under the growth floor
        ([0, 0.5, 0.4, 0.9, 1.4, 1.9, 2.4], None),  # the dip restarts the run: 5 after it
        ([0, 0.5, 0.4, 0.9, 1.4, 1.9, 2.4, 2.9], 2.5),  # and 6 from the dip on
    ],
)
def test_leak_line_grows_strictly_over_six_hourly_snapshots_by_a_mib(
    mib: list[float], growth: float | None
) -> None:
    want = {} if growth is None else {"a/b.py:1": pytest.approx(growth)}
    assert memdiag.leak_lines(_snaps({"a/b.py:1": mib})) == want


def _soak(n: int, overrides: Doc, stop: bool = False) -> Callable[..., Awaitable[Verdict]]:
    """A `run_soak` stand-in: the bars path's 3 setup calls, `n` samples 60 s apart, a verdict."""

    async def run(sc: Scenario, sampler: ProcSampler, **over: Any) -> Verdict:
        assert (sc.name, sc.profile, over) == ("soak_bars", "full", overrides)
        for _ in range(3):
            sampler.sample()
        curve = {f"{60 * k}": sampler.sample()[0] / MiB for k in range(n)}
        if stop:
            raise asyncio.CancelledError  # what the SIGTERM handler does to the soak's task
        return Verdict(sc.name, [R3], {"_curve": curve})

    return run


def test_a_leg_is_a_reading_unless_overridden_and_a_traced_leg_is_never_sloped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = ["--out-dir", str(tmp_path)]
    monkeypatch.setenv("GITHUB_SHA", "f" * 40)
    for name in memdiag.allocator(os.environ, 1)["seen"]:  # a reading runs with none of them
        monkeypatch.delenv(name)
    monkeypatch.setattr(memdiag, "run_soak", _soak(61, {}))  # the unchanged scenario
    assert memdiag.main(["leg", "--label", "default", *out]) == 0
    doc = json.loads((tmp_path / "default.json").read_text(encoding="utf-8"))
    assert (doc["reading"], doc["overrides"], doc["aligned"]) == (True, {}, True)
    assert doc["head"] == "f" * 40 and doc["allocator"]["self_check"]
    assert doc["verdict"]["checks"] == [dataclasses.asdict(R3)] and doc["samples"] == 61
    assert [p["t_s"] for p in doc["probes"]] == [0, 3600] and doc["w24"]["rss_mib"]["slope"] is None
    monkeypatch.setattr(memdiag, "run_soak", _soak(2, {"duration_s": 43200.0}, stop=True))
    argv = ["leg", "--label", "tracemalloc", "--hours", "12", "--tracemalloc", "1", *out]
    assert memdiag.main(argv) == 1
    doc = json.loads((tmp_path / "tracemalloc.json").read_text(encoding="utf-8"))
    assert (doc["reading"], doc["stopped"], doc["verdict"]) == (False, "CancelledError", None)
    assert (doc["rss_w24"], doc["w24"], "traced" in doc["probes"][0]) == (None, None, True)
    assert memdiag.main(["judge", str(tmp_path)]) == 0
    v = json.loads((tmp_path / "memdiag-verdict.json").read_text(encoding="utf-8"))
    assert (v["outcome"], v["missing"]) == ("NO VERDICT", ["malloc", "mmap128k"])
    assert v["legs"]["default"]["why_not"] == ["ends at t=3600 s, before 86400 s"]


def _leg(label: str, w24: float = 0.3, **kw: Any) -> Doc:
    """A valid leg report with what the rule reads: W24 slope `w24`, flat lines, glibc steps."""
    tm = label == "tracemalloc"
    doc: Doc = {"kind": "memdiag-leg", "label": label, "head": "c0ffee", "stopped": None}
    doc |= {"finished": "2026-10-23T00:00:00Z", "aligned": True, "reading": label == "default"}
    doc |= {"last_t_s": 43200.0 if tm else 86400.0, "tracemalloc_frames": 6 if tm else 0}
    doc |= {"allocator": {"seen": dict(memdiag.LEG_ENV[label]), "self_check": True}}
    doc |= {"verdict": {"checks": [dataclasses.asdict(R3)]}, "overrides": {}}
    doc |= {"rss_w24": None if tm else w24, "snapshots": _snaps({"a/b.py:1": [1.0] * 11})}
    doc |= {"w24": {"uordblks_mib": {"rise": 0.5}, "rss_mib": {"rise": 4.0}}}
    return doc | {"steps": [{"t_s": 50400.0, "rss_mib": 3.9, "by": "glibc"}]} | kw


_LIB = "site-packages/pydantic/main.py:10"
_UP = {_LIB: [0.0, 0.4, 0.8, 1.2, 1.6, 2.0], "a/c.py:2": [0.0, 0.3, 0.6, 0.9, 1.2, 1.5]}
_VIA_BARS = {_LIB: [{"frames": [_LIB, "services/api/candleviewer/bars/series_store.py:9"]}]}
D, TM, M, MM = (_leg(x) for x in memdiag.LEG_ENV)
TL = _leg("tracemalloc", snapshots=_snaps(_UP))  # two LEAK lines: +2.0 and +1.5 MiB
NOT_A_READING = {"reading": False, "overrides": {"duration_s": 86400.0}}
BAD = {"verdict": {"checks": [dataclasses.asdict(R3) | {"passed": False}]}}


@pytest.mark.parametrize(
    ("legs", "outcome", "reason"),
    [
        ([_leg("default", 0.15)], "NOT REPRODUCED", "default W24 slope +0.150"),
        ([], "NO VERDICT", "no valid default leg"),
        ([D | BAD, TM, M, MM], "NO VERDICT", ""),
        ([D | NOT_A_READING, TM, M, MM], "NO VERDICT", ""),
        ([D, TL | {"snapshots": _snaps(_UP, _VIA_BARS)}, M, MM], "LEAK IN BARS", "57% of"),
        ([D, TL, M, MM], "LEAK ELSEWHERE", "0% of"),
        ([D, TL, _leg("malloc", 0.2), MM], "MIXED", "moved by malloc"),
        ([D, TM, _leg("malloc", 0.2), MM], "FRAGMENTATION (malloc; steps: glibc)", ""),
        ([D, TM, M, _leg("mmap128k", 0.4)], "FRAGMENTATION (mmap128k; steps: glibc)", ""),
        ([D, TM, _leg("malloc", 0.22), _leg("mmap128k", 0.38)], "INCONCLUSIVE", "invalid: none"),
        ([D, TM | {"rss_w24": 9.9}, M, MM], "INCONCLUSIVE", "invalid: none"),  # never sloped
        ([D, TL, M], "INCONCLUSIVE", "missing or invalid: mmap128k"),  # MIXED not ruled out
        ([D, M | {"verdict": None}, MM], "INCONCLUSIVE", "missing or invalid: tracemalloc, malloc"),
    ],
)
def test_judge_applies_the_reading_rule_to_the_valid_legs(
    tmp_path: Path, legs: list[Doc], outcome: str, reason: str
) -> None:
    for i, doc in enumerate(legs):
        (tmp_path / f"{i}-{doc['label']}.json").write_text(json.dumps(doc), encoding="utf-8")
    v, labels = memdiag.judge(tmp_path), {d["label"] for d in legs}
    assert v["outcome"] == outcome and v["missing"] == [
        x for x in memdiag.LEG_ENV if x not in labels
    ]
    assert any(reason in r for r in v["reasons"]), v["reasons"]
    md = (tmp_path / "memdiag-verdict.md").read_text(encoding="utf-8")
    assert md.startswith(f"# soak_bars memory diagnosis (#399 R4): {outcome}\n")
