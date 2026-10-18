#!/usr/bin/env python3
"""E03-T04: flatten per-package coverage reports into the single
`<artifact-dir>/<artifact-name>/{coverage.xml,lcov.info}` layout that
`tools/ci/coverage_gate.py` expects by default.

The JS/engine lanes (`_job-js.yml`, E03-T02) upload one shared artifact
(`coverage-unit-frontend`, `coverage-unit-engine`) containing several
packages' `lcov.info` files at their original repo-relative paths, e.g.:

    coverage-unit-frontend/apps/web/coverage/lcov.info
    coverage-unit-frontend/apps/desktop/coverage/lcov.info
    coverage-unit-frontend/packages/ui/coverage/lcov.info

`coverage-baselines.json` maps each package name (e.g. `"apps/app-web"`) to
the artifact it lives in, and `coverage_gate.py` looks for
`<report-dir>/<artifact>/lcov.info` by default. This script copies each
matching per-package `lcov.info` to `<report-dir>/<artifact>/lcov.info`
using the package's own coverage-baselines.json entry, so no path mapping
is duplicated between this script and the baselines file.

Package name -> on-disk directory mapping (only needed because
`apps/app-web` / `apps/app-electron` are the ticket's package names but the
repo directories are `apps/web` / `apps/desktop` — see
`docs/plan/20-architecture.md` §5 repo map vs. this ticket's Scope /
Deliverables list, which names the floors by the ticket's own package
labels). `services/api`, `packages/chart-engine`, `packages/protocol` and
`packages/ui` already match their repo directories 1:1.

Artifacts are untrusted input (#3508): reports are read through
`coverage_gate.read_artifact_bytes` and must parse as lcov, and a copy is only
ever created as a new file. A refusal prints CI-COV-004 (a malformed report
CI-COV-003), writes the same line to `--summary-out` when given (the summary
the PR comment posts, as the gate does) and exits 1.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.coverage_gate import (
    MAX_REPORT_BYTES,
    ArtifactRefusedError,
    CoverageGateError,
    check_artifact_entry_count,
    parse_lcov,
    read_artifact_bytes,
)

_PACKAGE_TO_REPO_DIR: dict[str, str] = {
    "apps/app-web": "apps/web",
    "apps/app-electron": "apps/desktop",
}


def _repo_dir_for(package: str) -> str:
    return _PACKAGE_TO_REPO_DIR.get(package, package)


def _create_inside(root: Path, dest: Path, data: bytes) -> None:
    """Write `data` to `dest` as a new file whose directory resolves inside `root`;
    an existing path at `dest`, a link included, is refused rather than followed."""
    parent = dest.parent.resolve(strict=True)
    if not parent.is_relative_to(root.resolve(strict=True)):
        raise ArtifactRefusedError(f"{dest} resolves outside {root}")
    try:
        fd = os.open(parent / dest.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    except FileExistsError as exc:
        raise ArtifactRefusedError(
            f"{dest} already exists and is not a regular file"
        ) from exc
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


def flatten(report_dir: Path) -> list[Path]:
    """Copy each package's `coverage/lcov.info` into
    `<report_dir>/<artifact>/lcov.info` if it isn't already there
    (services/api's `coverage.xml` is already uploaded flat by `_job-py.yml`
    and needs no flattening). Returns the list of files written. Raises
    ArtifactRefusedError (CI-COV-004) or CoverageGateError (CI-COV-003)."""
    import json

    baselines_path = Path(__file__).parent / "coverage-baselines.json"
    config = json.loads(baselines_path.read_text(encoding="utf-8"))
    check_artifact_entry_count(report_dir)
    written: list[Path] = []

    for package, cfg in config["packages"].items():
        if cfg["report_format"] != "lcov":
            continue
        artifact = cfg["artifact"]
        dest = report_dir / artifact / "lcov.info"
        if dest.is_file():
            continue  # already flat (e.g. a single-package artifact)

        repo_dir = _repo_dir_for(package)
        source = report_dir / artifact / repo_dir / "coverage" / "lcov.info"
        if not source.is_file():
            continue  # coverage_gate.py will report CI-COV-003 for this one

        data = read_artifact_bytes(report_dir, source, MAX_REPORT_BYTES)
        try:
            parse_lcov(data.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise CoverageGateError(f"{source} is not UTF-8") from exc
        except CoverageGateError as exc:
            raise CoverageGateError(f"{source}: {exc}") from exc
        _create_inside(report_dir, dest, data)
        written.append(dest)

    return written


def _refuse(message: str, summary_out: Path | None) -> int:
    print(message, file=sys.stderr)
    if summary_out is not None:
        summary_out.write_text(message + "\n", encoding="utf-8")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "report_dir", nargs="?", type=Path, default=Path("coverage-artifacts")
    )
    parser.add_argument(
        "--summary-out",
        type=Path,
        default=None,
        help="On a refusal, write it to this path (the PR-comment summary)",
    )
    args = parser.parse_args(argv)
    try:
        written = flatten(args.report_dir)
    except ArtifactRefusedError as exc:
        message = f"CI-COV-004: coverage artifact refused: {exc}"
        return _refuse(message, args.summary_out)
    except CoverageGateError as exc:
        message = f"CI-COV-003: unreadable coverage artifact: {exc}"
        return _refuse(message, args.summary_out)
    for path in written:
        print(f"flattened -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
