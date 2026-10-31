#!/usr/bin/env python3
"""#5193: the committed index of the `py-perf` lane's tests, and its shards.

`py-perf` (`.github/workflows/_job-py.yml`) ran `pytest -m "perf and not flaky"` in one job, which
collected the whole services/api suite (68,000 tests, about 5 min on a hosted runner) to select
155, then ran them in about 12.7 min: 16.5-18.9 min a run against a hang guard of 20 (#5171,
#5186). `tools/ci/py-perf-index.json` now lists the selected node ids, so each shard of the
`py-perf` matrix runs `pytest <its ids> -m "perf and not flaky"` and imports only its own files.

The index holds the marker expression, the node ids (sorted) and `weights`: the seconds per test
file, setup, call and teardown summed from pytest's `--durations=0` lines in the log of CI job
124449801043 (run 41171217151, 2026-10-31, the slowest of the four runs #5186 measured: 1,059 s
of pytest, 759 s of it in the tests). A file pytest timed under 0.005 s a phase weighs 0. A file
missing from `weights` (a new perf file) costs `default_weight`, so it still lands in exactly one
shard; stale weights cost balance, never coverage. Shards are whole files (a module's fixtures
are set up once), split by `governance_shards.shards`: heaviest first, to the lightest shard.

Commands, run from services/api in its environment (`uv run python ../../tools/ci/...`), since
`write` and `check` collect with the interpreter that runs them:
  write [LOG...]    collect live and rewrite the index; with LOGs (a py-perf job log with
                    `--durations=0`), re-weigh every indexed file from them (a file's largest
                    total), else keep the weights
  check             collect live; exit 1 when the index differs, naming the tests and the fix
  shard INDEX COUNT the node ids of one shard, one per line (`_job-py.yml` reads them)
  plan COUNT        each shard's files, tests and weighted seconds, and the job's timeout
The `check` runs in CI's `py-perf-index` job and in scripts/tests/test_py_perf_index.py.
Stdlib only; no network.
"""

from __future__ import annotations

import json
import math
import re
import statistics
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from tools.ci.governance_shards import shards  # noqa: E402 - repo root added above

API_ROOT = REPO_ROOT / "services" / "api"
INDEX_PATH = REPO_ROOT / "tools" / "ci" / "py-perf-index.json"
MARKER = "perf and not flaky"
#: How to rewrite the index, quoted by `check`'s failure.
REGENERATE = (
    "cd services/api && uv run python ../../tools/ci/py_perf_index.py write  "
    "(add a py-perf job log with --durations=0 to re-weigh the files)"
)
#: The collection the index mirrors: `_job-py.yml`'s selection, with no coverage and no cache.
COLLECT_ARGS = (
    *("-m", MARKER, "--collect-only", "-q", "--no-cov"),
    *("-p", "no:cacheprovider", "-p", "no:randomly"),
)
#: A shard job's time outside its tests, measured in run 41171217151 (job 124449801043): set-up,
#: checkout, uv sync and the image pre-pull, 52 s (05:11:25 to 05:12:17), rounded up.
JOB_OVERHEAD_S = 60
#: Collecting one shard's files. Locally (2026-10-31, a loaded 8-core host) the whole marker
#: collection took 505 s and each shard's ids 8.3, 7.1 and 16.5 s, at most 3.3%; 3.3% of a hosted
#: runner's 304 s for the whole suite (05:12:17 to 05:17:21 in that log) is 10 s. 30 leaves room.
SHARD_COLLECT_S = 30
#: The hang guard is at least this many times a shard's expected duration (#5171, C-9.3).
TIMEOUT_FACTOR = 1.5
#: tools/ci/prepull_images.sh's worst case at PREPULL_PULL_TIMEOUT=45: 8 pulls x 45 s + 220 s of
#: waits. A shard's guard leaves room for it on top of the expected run.
PREPULL_WORST_S = 8 * 45 + 220
NODE_ID_RE = re.compile(r"^tests/\S+?\.py::\S.*$")
DURATION_RE = re.compile(r"(\d+\.\d+)s (?:setup|call|teardown) +(tests/\S+?\.py)::")
HIDDEN_RE = re.compile(r"\(\d+ durations < [\d.]+s hidden")


class PerfIndexError(Exception):
    """The index or a collection is unusable: a setup bug (exit 2), not a finding (exit 1)."""


@dataclass(frozen=True)
class Index:
    marker: str
    tests: tuple[str, ...]
    weights: Mapping[str, float]
    default_weight: float

    @property
    def files(self) -> list[str]:
        return sorted({file_of(test) for test in self.tests})

    def weight(self, file: str) -> float:
        return self.weights.get(file, self.default_weight)


def file_of(node_id: str) -> str:
    return node_id.split("::", 1)[0]


def load(path: Path = INDEX_PATH) -> Index:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PerfIndexError(f"cannot read {path}: {exc}") from exc
    tests, weights = raw.get("tests"), raw.get("weights")
    default = raw.get("default_weight")
    if raw.get("marker") != MARKER:
        raise PerfIndexError(f"{path}: 'marker' must be {MARKER!r}, the py-perf selection")
    if not isinstance(tests, list) or not all(
        isinstance(t, str) and NODE_ID_RE.match(t) for t in tests
    ):
        raise PerfIndexError(f"{path}: 'tests' must list node ids below tests/")
    if tests != sorted(set(tests)):
        raise PerfIndexError(f"{path}: 'tests' must be sorted, without duplicates")
    if not isinstance(weights, dict) or not all(
        isinstance(v, (int, float)) and v >= 0 for v in weights.values()
    ):
        raise PerfIndexError(f"{path}: 'weights' must map test files to seconds")
    if not isinstance(default, (int, float)) or default <= 0:
        raise PerfIndexError(f"{path}: 'default_weight' must be a positive number of seconds")
    return Index(MARKER, tuple(tests), {k: float(v) for k, v in weights.items()}, float(default))


def dump(index: Index, path: Path = INDEX_PATH) -> None:
    files = set(index.files)
    payload = {
        "marker": index.marker,
        "default_weight": index.default_weight,
        "weights": {f: round(w, 2) for f, w in sorted(index.weights.items()) if f in files},
        "tests": list(index.tests),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_collection(stdout: str) -> list[str]:
    """The node ids of a `--collect-only -q` listing, sorted."""
    return sorted({line for line in stdout.splitlines() if NODE_ID_RE.match(line)})


def collect(python: Sequence[str] = (sys.executable,), api_root: Path = API_ROOT) -> list[str]:
    """The live `perf and not flaky` collection of services/api, as sorted node ids."""
    proc = subprocess.run(
        [*python, "-m", "pytest", *COLLECT_ARGS],
        cwd=api_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-20:])
        raise PerfIndexError(f"the collection exited {proc.returncode}:\n{tail}")
    found = parse_collection(proc.stdout)
    if not found:
        raise PerfIndexError("the collection listed no perf test")
    return found


def drift(index: Index, live: Sequence[str]) -> str:
    """'' when the index lists exactly the live collection, else what differs and the fix."""
    listed, collected = set(index.tests), set(live)
    missing, stale = sorted(collected - listed), sorted(listed - collected)
    if not missing and not stale:
        return ""
    lines = [
        (
            f"{INDEX_PATH.relative_to(REPO_ROOT)} differs from the live `pytest -m {MARKER!r}` "
            f"collection ({len(collected)} tests): no py-perf shard would run the tests it misses."
        )
    ]
    lines += [f"  not in the index: {t}" for t in missing]
    lines += [f"  no longer collected: {t}" for t in stale]
    lines.append(f"Regenerate it: {REGENERATE}")
    return "\n".join(lines)


def log_weights(text: str) -> dict[str, float]:
    """Seconds per test file from pytest's `--durations=0` lines (setup, call and teardown)."""
    if not HIDDEN_RE.search(text) and "slowest durations" not in text:
        raise PerfIndexError("the log holds no `--durations=0` report")
    totals: dict[str, float] = {}
    for match in DURATION_RE.finditer(text):
        totals[match.group(2)] = totals.get(match.group(2), 0.0) + float(match.group(1))
    return totals


def split(index: Index, count: int) -> list[list[str]]:
    """The index's node ids in `count` shards of whole files, about equal in weight."""
    parts = shards(index.files, count, weights=index.weights, default=index.default_weight)
    by_file: dict[str, list[str]] = {}
    for test in index.tests:
        by_file.setdefault(file_of(test), []).append(test)
    return [[t for f in part for t in by_file[f]] for part in parts]


def shard_seconds(index: Index, part: Sequence[str]) -> float:
    return sum(index.weight(f) for f in sorted({file_of(t) for t in part}))


def expected_seconds(index: Index, count: int) -> list[float]:
    """Each shard's expected job time at the measured (slowest observed) pace."""
    return [
        JOB_OVERHEAD_S + SHARD_COLLECT_S + shard_seconds(index, part)
        for part in split(index, count)
    ]


def timeout_minutes(index: Index, count: int) -> int:
    """The shard job's hang guard: the larger of 1.5x the heaviest shard's expected time and that
    time plus the image pre-pull's worst case, in whole minutes."""
    heaviest = max(expected_seconds(index, count))
    return math.ceil(max(heaviest * TIMEOUT_FACTOR, heaviest + PREPULL_WORST_S) / 60)


USAGE = (
    "usage: py_perf_index.py write [LOG...] | check | shard INDEX COUNT | plan COUNT"
    "  (1 <= INDEX <= COUNT)"
)


def _count_args(args: list[str], n: int) -> list[int] | None:
    if len(args) != n or not all(a.isdigit() and int(a) >= 1 for a in args):
        return None
    return [int(a) for a in args]


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command, rest = (args[0], args[1:]) if args else ("", [])
    try:
        if command == "write":
            old = load() if INDEX_PATH.exists() else None
            weights = dict(old.weights) if old else {}
            default = old.default_weight if old else 1.0
            live = collect()
            if rest:
                measured: dict[str, float] = {}
                for log in rest:
                    for name, seconds in log_weights(
                        Path(log).read_text("utf-8", "replace")
                    ).items():
                        measured[name] = max(measured.get(name, 0.0), seconds)
                # A file the logs ran but timed under 0.005 s a phase weighs 0.
                weights = {file_of(t): measured.get(file_of(t), 0.0) for t in live}
                # A new file costs the median timed file, about what a perf test file takes.
                default = round(statistics.median(w for w in weights.values() if w > 0), 2)
            dump(Index(MARKER, tuple(live), weights, default))
            print(f"py_perf_index: wrote {len(live)} tests to {INDEX_PATH.relative_to(REPO_ROOT)}")
            return 0
        if command == "check" and not rest:
            index = load()
            problem = drift(index, collect())
            if problem:
                print(problem, file=sys.stderr)
                return 1
            print(
                f"py_perf_index: the index matches the live collection ({len(index.tests)} tests)"
            )
            return 0
        if command == "shard" and (pair := _count_args(rest, 2)) and pair[0] <= pair[1]:
            chosen = split(load(), pair[1])[pair[0] - 1]
            if not chosen:
                print(
                    f"py_perf_index: shard {pair[0]} of {pair[1]} is empty",
                    file=sys.stderr,
                )
                return 1
            print("\n".join(chosen))
            return 0
        if command == "plan" and (one := _count_args(rest, 1)):
            index = load()
            parts, seconds = split(index, one[0]), expected_seconds(index, one[0])
            for number, (part, total) in enumerate(zip(parts, seconds, strict=True), start=1):
                files = len({file_of(t) for t in part})
                print(
                    f"shard {number}/{one[0]}: {files} files, {len(part)} tests, "
                    f"{shard_seconds(index, part):.0f} s of tests, {total:.0f} s expected"
                )
            print(f"timeout-minutes: {timeout_minutes(index, one[0])}")
            return 0
    except PerfIndexError as exc:
        print(f"py_perf_index: {exc}", file=sys.stderr)
        return 2
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
