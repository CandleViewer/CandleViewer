#!/usr/bin/env python3
"""E49-Q01 (#1335, BQ-05): balance the GA regression pack's nightly shards and hold the budget.

Each lane's pack spec files (``specs.pack_files``) go to its shards greedily, longest first, each
to the currently lightest shard (LPT), from the per-file seconds in the committed
``tools/ga/durations.json``. A file the table does not name costs ``DEFAULT_SECONDS``, so a new
spec always lands in exactly one shard; stale seconds cost balance, never coverage. Ties break on
the path, so a plan is a pure function of the files and the table.

The budget (ticket: "the full pack completes within 45 minutes wall-clock") is checked twice:
here, before the run, on the plan (the heaviest shard plus ``SETUP_SECONDS`` of checkout, install,
builds and browser setup, against ``BUDGET_SECONDS``), and after the run on the measured
wall-clock (report.py). Shard assignment is recomputed on every run, so it follows the table;
the table is refreshed weekly from the nightly's ``ga-durations`` artefact through a reviewed PR.

    python3 tools/ga/shard_plan.py web-chromium 1 4   # shard 1 of 4: one spec path per line
    python3 tools/ga/shard_plan.py --check            # the plan of every lane fits the budget

Paths are relative to the lane's package (apps/web, apps/desktop), as Playwright's file filter
takes them. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

if __package__ in (None, ""):  # run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ga import specs

DURATIONS = Path(__file__).with_name("durations.json")
BUDGET_SECONDS = 45 * 60
#: Checkout, install, workspace + app builds and the browser install, per shard job (the e2e lane's
#: own jobs, measured in pr.yml runs, take 6 to 9 minutes before the first test).
SETUP_SECONDS = 12 * 60
DEFAULT_SECONDS = 30.0
#: Shards per lane: web runs in parallel jobs; Electron runs one worker on one display.
SHARDS = {"web-chromium": 4, "electron": 1}


def load_durations(path: Path = DURATIONS) -> dict[str, dict[str, float]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {lane: {k: float(v) for k, v in data.get(lane, {}).items()} for lane in specs.APPS}


def plan(files: Sequence[str], seconds: Mapping[str, float], total: int) -> list[list[str]]:
    """LPT: heaviest first, each to the lightest shard (ties: lowest index); each shard sorted."""
    if total < 1:
        raise ValueError("total must be >= 1")
    loads = [0.0] * total
    shards: list[list[str]] = [[] for _ in range(total)]
    for f in sorted(set(files), key=lambda f: (-seconds.get(f, DEFAULT_SECONDS), f)):
        i = min(range(total), key=lambda k: (loads[k], k))
        shards[i].append(f)
        loads[i] += seconds.get(f, DEFAULT_SECONDS)
    return [sorted(s) for s in shards]


def shard_seconds(shard: Sequence[str], seconds: Mapping[str, float]) -> float:
    return sum(seconds.get(f, DEFAULT_SECONDS) for f in shard)


def budget_findings(
    plans: Mapping[str, list[list[str]]],
    durations: Mapping[str, Mapping[str, float]],
    budget: float = BUDGET_SECONDS,
    setup: float = SETUP_SECONDS,
) -> list[str]:
    """One line per lane whose heaviest planned shard, plus setup, exceeds the budget."""
    out = []
    for lane, shards in sorted(plans.items()):
        worst = max((shard_seconds(s, durations.get(lane, {})) for s in shards), default=0.0)
        if worst + setup > budget:
            out.append(
                f"{lane}: heaviest shard {worst:.0f} s + {setup:.0f} s setup exceeds the"
                f" {budget:.0f} s budget; add shards or split the heaviest spec file"
            )
    return out


def duration_findings(
    files: Mapping[str, Sequence[str]], durations: Mapping[str, Mapping[str, float]]
) -> list[str]:
    """A durations key that names no pack file of its lane is stale (a renamed or retired spec
    would otherwise fall silently to DEFAULT_SECONDS)."""
    out = []
    for lane, table in sorted(durations.items()):
        for key in sorted(set(table) - set(files.get(lane, ()))):
            out.append(
                f"tools/ga/durations.json: {lane} names {key}, which is not a pack spec file;"
                " drop it or refresh the table from the nightly's ga-durations artefact"
            )
    return out


def duration_notes(
    files: Mapping[str, Sequence[str]], durations: Mapping[str, Mapping[str, float]]
) -> list[str]:
    """Lanes whose planned budget is an estimate: pack files with no measured seconds."""
    out = []
    for lane, lane_files in sorted(files.items()):
        unmeasured = [f for f in lane_files if f not in durations.get(lane, {})]
        if unmeasured:
            out.append(
                f"{lane}: {len(unmeasured)} of {len(lane_files)} pack files have no measured"
                f" seconds; the planned budget counts {DEFAULT_SECONDS:.0f} s each (provisional"
                " until a nightly's ga-durations artefact is committed)"
            )
    return out


def filter_overlaps(files: Sequence[str]) -> list[str]:
    """Playwright reads each file argument as a regular expression over the path, so one pack
    path must never match another (a shard would then run the other shard's file too)."""
    out = []
    for a in sorted(set(files)):
        for b in sorted(set(files)):
            if a != b and re.search(a, b):
                out.append(f"shard file filter {a} also matches {b}; rename one of them")
    return out


def all_plans(
    root: Path = specs.REPO_ROOT, durations_path: Path = DURATIONS
) -> tuple[dict[str, list[list[str]]], dict[str, dict[str, float]]]:
    tests = specs.scan(root)
    durations = load_durations(durations_path)
    plans = {
        lane: plan(specs.pack_files(tests, lane), durations[lane], SHARDS[lane])
        for lane in specs.APPS
    }
    return plans, durations


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("lane", nargs="?", choices=sorted(specs.APPS))
    p.add_argument("index", nargs="?", type=int)
    p.add_argument("total", nargs="?", type=int)
    p.add_argument("--check", action="store_true", help="fail when a lane's plan misses budget")
    p.add_argument("--root", type=Path, default=specs.REPO_ROOT)
    p.add_argument("--durations", type=Path, default=DURATIONS)
    args = p.parse_args(argv)
    if args.check:
        plans, durations = all_plans(args.root, args.durations)
        findings = budget_findings(plans, durations)
        for lane, shards in sorted(plans.items()):
            loads = ", ".join(f"{shard_seconds(s, durations[lane]):.0f}" for s in shards)
            print(f"{lane}: {sum(map(len, shards))} spec files, shard seconds [{loads}]")
        for f in findings:
            print(f"::error title=ga-regression budget::{f}")
        return 1 if findings else 0
    if args.lane is None or args.index is None:
        p.error("give LANE INDEX [TOTAL], or --check")
    total = args.total or SHARDS[args.lane]
    if not 1 <= args.index <= total:
        p.error(f"index must be in 1..{total}")
    tests = specs.scan(args.root)
    seconds = load_durations(args.durations)[args.lane]
    for f in plan(specs.pack_files(tests, args.lane), seconds, total)[args.index - 1]:
        print(f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
