#!/usr/bin/env python3
"""#2424: the parallel pytest lanes of the `py` CI job (ADR-0013: rebalance when p90 > 15 min).

`tools/ci/py-test-lanes.json` is the one source of truth. Named lanes list test paths relative to
services/api; the rest lane runs `tests` minus every listed path, so a new test directory runs in
the rest lane instead of dropping out. `.github/workflows/_job-py.yml` calls `pytest-args LANE`
(one lane's path arguments), `data-files DIR` (the lane coverage data to combine; CI-COV-003 and
exit 1 unless there is exactly one file per lane) and `fail-under` (the addopts floor the lanes
switch off and the `py` job applies to the combined data). `check`, also run by
scripts/tests/test_py_test_lanes.py, fails when a listed path is missing, holds no test file or
overlaps another, or when a test file would run in no lane or in two. Stdlib only; no network.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPO_ROOT / "tools" / "ci" / "py-test-lanes.json"
DEFAULT_API_ROOT = REPO_ROOT / "services" / "api"

TESTS_DIR = "tests"
DATA_FILE_TEMPLATE = "py-lane-{lane}.coverage"
LANE_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# Relative POSIX path below tests/: no whitespace, no glob characters, no trailing slash.
LISTED_PATH_RE = re.compile(r"^tests(?:/[A-Za-z0-9_.-]+)+$")
FAIL_UNDER_RE = re.compile(r"--cov-fail-under[= ](\d+(?:\.\d+)?)")
PYTHON_FILES = ("test_*.py", "*_test.py")  # pytest's default; pyproject sets no other
IGNORE_PREFIX = "--ignore="


class LaneManifestError(Exception):
    """The manifest or pyproject is unusable: a setup bug (exit 2), not a finding (exit 1)."""


@dataclass(frozen=True)
class Manifest:
    lanes: Mapping[str, tuple[str, ...]]
    rest_lane: str

    @property
    def names(self) -> list[str]:
        """Every lane, in matrix order: the named lanes as listed, then the rest lane."""
        return [*self.lanes, self.rest_lane]

    @property
    def listed_paths(self) -> list[str]:
        return [path for paths in self.lanes.values() for path in paths]


def load_manifest(path: Path = DEFAULT_MANIFEST) -> Manifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LaneManifestError(f"cannot read {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise LaneManifestError(f"{path}: top level must be an object")
    rest = raw.get("rest_lane")
    if not isinstance(rest, str) or not LANE_NAME_RE.match(rest):
        raise LaneManifestError(f"{path}: 'rest_lane' must be a lowercase kebab-case name")
    lanes_raw = raw.get("lanes")
    if not isinstance(lanes_raw, dict) or not lanes_raw:
        raise LaneManifestError(f"{path}: 'lanes' must be a non-empty object")
    lanes: dict[str, tuple[str, ...]] = {}
    for name, paths in lanes_raw.items():
        if not LANE_NAME_RE.match(name) or name == rest:
            raise LaneManifestError(
                f"{path}: lane {name!r} must be a kebab-case name other than the rest lane"
            )
        if not isinstance(paths, list) or not paths:
            raise LaneManifestError(f"{path}: lane {name!r} must list at least one path")
        for entry in paths:
            if (
                not isinstance(entry, str)
                or not LISTED_PATH_RE.match(entry)
                or any(part in (".", "..") for part in entry.split("/"))
            ):
                raise LaneManifestError(
                    f"{path}: lane {name!r} path {entry!r} must be a plain path below tests/"
                )
        lanes[name] = tuple(paths)
    return Manifest(lanes=lanes, rest_lane=rest)


def pytest_args(manifest: Manifest, lane: str) -> list[str]:
    """Path arguments for one lane's pytest run from services/api."""
    if lane == manifest.rest_lane:
        return [TESTS_DIR, *(f"{IGNORE_PREFIX}{path}" for path in manifest.listed_paths)]
    if lane not in manifest.lanes:
        raise LaneManifestError(f"unknown lane {lane!r}; lanes: {', '.join(manifest.names)}")
    return list(manifest.lanes[lane])


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


def collects(args: Sequence[str], test_file: str) -> bool:
    """Whether pytest run with these path arguments collects `test_file`: the file sits under a
    positional path and under no ``--ignore`` path (all relative to services/api)."""
    targets: list[str] = []
    ignored: list[str] = []
    for arg in args:
        if arg.startswith(IGNORE_PREFIX):
            ignored.append(arg.removeprefix(IGNORE_PREFIX))
        elif arg.startswith("-"):
            raise LaneManifestError(f"unexpected pytest option in lane arguments: {arg}")
        else:
            targets.append(arg)
    return any(_under(test_file, t) for t in targets) and not any(
        _under(test_file, i) for i in ignored
    )


def suite_files(api_root: Path = DEFAULT_API_ROOT) -> list[str]:
    """Every test module under services/api/tests, as POSIX paths relative to services/api."""
    found: list[str] = []
    for path in sorted((api_root / TESTS_DIR).rglob("*.py")):
        relative = path.relative_to(api_root)
        if any(part == "__pycache__" or part.startswith(".") for part in relative.parts):
            continue
        if any(fnmatch.fnmatch(path.name, pattern) for pattern in PYTHON_FILES):
            found.append(relative.as_posix())
    return found


def partition_problems(lane_args: Mapping[str, Sequence[str]], files: Iterable[str]) -> list[str]:
    """One finding per test file that would run in no lane or in more than one."""
    problems: list[str] = []
    for test_file in files:
        lanes = [lane for lane, args in lane_args.items() if collects(args, test_file)]
        if len(lanes) != 1:
            where = "no lane" if not lanes else f"{len(lanes)} lanes ({', '.join(lanes)})"
            problems.append(f"{test_file} would run in {where}")
    return problems


def check(manifest: Manifest, api_root: Path = DEFAULT_API_ROOT) -> list[str]:
    files = suite_files(api_root)
    problems: list[str] = []
    listed = manifest.listed_paths
    for path in listed:
        if not (api_root / path).exists():
            problems.append(f"{path}: listed but missing (renamed or deleted?)")
        elif not any(_under(f, path) for f in files):
            problems.append(f"{path}: listed but holds no test file")
    for index, first in enumerate(listed):
        for second in listed[index + 1 :]:
            if _under(first, second) or _under(second, first):
                problems.append(
                    f"{first} and {second} overlap: list a path once, never inside another"
                )
    lane_args = {lane: pytest_args(manifest, lane) for lane in manifest.names}
    return problems + partition_problems(lane_args, files)


def data_files(manifest: Manifest, directory: Path) -> tuple[list[Path], list[str]]:
    """The lane data files in `directory`, and what keeps them from being exactly one per lane."""
    expected = {DATA_FILE_TEMPLATE.format(lane=lane): lane for lane in manifest.names}
    present = (
        sorted(p.name for p in directory.iterdir() if p.is_file()) if directory.is_dir() else []
    )
    problems = [
        f"lane {lane!r} left no coverage data ({name})"
        for name, lane in expected.items()
        if name not in present
    ]
    problems += [
        f"unexpected file {name} (no lane writes it)" for name in present if name not in expected
    ]
    return [directory / name for name in expected if name in present], problems


def fail_under(api_root: Path = DEFAULT_API_ROOT) -> str:
    path = api_root / "pyproject.toml"
    try:
        pyproject = tomllib.loads(path.read_text(encoding="utf-8"))
        addopts = pyproject["tool"]["pytest"]["ini_options"]["addopts"]
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError) as exc:
        raise LaneManifestError(f"cannot read the pytest addopts in {path}: {exc}") from exc
    if isinstance(addopts, list):
        addopts = " ".join(str(a) for a in addopts)
    floors = FAIL_UNDER_RE.findall(str(addopts))
    if len(floors) != 1:
        raise LaneManifestError(f"{path}: expected one --cov-fail-under in addopts, found {floors}")
    return str(floors[0])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--api-root", type=Path, default=DEFAULT_API_ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("pytest-args", help="print one lane's pytest path arguments").add_argument(
        "lane"
    )
    commands.add_parser("data-files", help="list the lane coverage data to combine").add_argument(
        "directory", type=Path
    )
    commands.add_parser("fail-under", help="print the --cov-fail-under floor from addopts")
    commands.add_parser("check", help="verify that the lanes partition the test files")
    args = parser.parse_args(argv)

    try:
        manifest = load_manifest(args.manifest)
        if args.command == "pytest-args":
            print(" ".join(pytest_args(manifest, args.lane)))
            return 0
        if args.command == "fail-under":
            print(fail_under(args.api_root))
            return 0
        if args.command == "data-files":
            files, problems = data_files(manifest, args.directory)
            for problem in problems:
                print(f"::error title=CI-COV-003 incomplete py lane coverage::{problem}")
            if problems:
                return 1
            print("\n".join(str(f) for f in files))
            return 0
        problems = check(manifest, args.api_root)
    except LaneManifestError as exc:
        print(f"py_test_lanes: {exc}", file=sys.stderr)
        return 2
    for problem in problems:
        print(f"py_test_lanes: {problem}", file=sys.stderr)
    if problems:
        return 1
    count = len(suite_files(args.api_root))
    print(f"py_test_lanes: {len(manifest.names)} lanes partition {count} test files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
