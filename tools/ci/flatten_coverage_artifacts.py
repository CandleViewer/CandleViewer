#!/usr/bin/env python3
"""E03-T04: copy each package's coverage report into a directory of its own,
`<artifact-dir>/<artifact-name>/<package-slug>/{coverage.xml,lcov.info}`, the one
report `tools/ci/coverage_gate.py` judges that package on (`own_report_path`, #3562).

The JS/engine lanes (`_job-js.yml`, E03-T02) upload one shared artifact
(`coverage-unit-frontend`, `coverage-unit-engine`) containing several
packages' `lcov.info` files at their original repo-relative paths, e.g.:

    coverage-unit-frontend/apps/web/coverage/lcov.info
    coverage-unit-frontend/apps/desktop/coverage/lcov.info
    coverage-unit-frontend/packages/ui/coverage/lcov.info

and `_job-py.yml` uploads services/api's `coverage.xml` at its artifact's root.
`coverage-baselines.json` maps each package name (e.g. `"apps/app-web"`) to
the artifact it lives in, so this script copies that package's own report to
`<artifact>/apps-app-web/lcov.info`: packages that share an artifact are never
judged on one another's report, and two packages may not name one upload path.

Package name -> on-disk directory mapping (only needed because
`apps/app-web` / `apps/app-electron` are the ticket's package names but the
repo directories are `apps/web` / `apps/desktop` — see
`docs/plan/20-architecture.md` §5 repo map vs. this ticket's Scope /
Deliverables list, which names the floors by the ticket's own package
labels). `services/api`, `packages/chart-engine`, `packages/protocol` and
`packages/ui` already match their repo directories 1:1.

Artifacts are untrusted input (#3508): reports are read through
`coverage_gate.read_artifact_bytes` and must parse, and a copy is only ever
created as a new file in a directory this script creates; one the download already
holds is refused, so a second run needs a fresh download. A refusal prints CI-COV-004
(a malformed report, or a baselines error such as two packages naming one upload path,
CI-COV-003), writes the same line to `--summary-out` when given (the summary the PR
comment posts, as the gate does) and exits 1.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.coverage_gate import (
    MAX_REPORT_BYTES,
    REPORT_FILENAMES,
    ArtifactRefusedError,
    CoverageGateError,
    PackageConfig,
    check_artifact_entry_count,
    load_config,
    own_report_path,
    parse_report,
    read_artifact_bytes,
)

BASELINES = Path(__file__).parent / "coverage-baselines.json"

_PACKAGE_TO_REPO_DIR: dict[str, str] = {
    "apps/app-web": "apps/web",
    "apps/app-electron": "apps/desktop",
}


def _repo_dir_for(package: str) -> str:
    return _PACKAGE_TO_REPO_DIR.get(package, package)


def _create_inside(root: Path, dest: Path, data: bytes) -> None:
    """Write `data` to `dest` as a new file whose directory resolves inside `root`;
    an existing path at `dest`, a link included, is refused rather than followed."""
    try:
        parent = dest.parent.resolve(strict=True)
        inside = parent.is_relative_to(root.resolve(strict=True))
    except (OSError, RuntimeError) as exc:
        raise ArtifactRefusedError(f"{dest.parent} does not resolve") from exc
    if not inside:
        raise ArtifactRefusedError(f"{dest} resolves outside {root}")
    try:
        fd = os.open(parent / dest.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    except FileExistsError as exc:
        raise ArtifactRefusedError(
            f"{dest} already exists and is not a regular file"
        ) from exc
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


def _source_for(report_dir: Path, pkg: PackageConfig) -> Path:
    """Where the lane uploads `pkg`'s report: an lcov.info under its repo directory
    (`_job-js.yml`), or a coverage.xml at its artifact's root (`_job-py.yml`)."""
    if pkg.report_format == "lcov":
        repo_dir = _repo_dir_for(pkg.name)
        return report_dir / pkg.artifact / repo_dir / "coverage" / "lcov.info"
    return report_dir / pkg.artifact / REPORT_FILENAMES[pkg.report_format]


def flatten(report_dir: Path, baselines: Path = BASELINES) -> list[Path]:
    """Copy each package's own report to its `own_report_path` and return the
    copies written; a package whose lane uploaded no report is skipped
    (coverage_gate.py reports CI-COV-003 or N/A for it). Raises
    ArtifactRefusedError (CI-COV-004) or CoverageGateError (CI-COV-003, also
    when two packages name one upload path)."""
    _, packages = load_config(baselines)
    owners: dict[Path, str] = {}
    for pkg in packages.values():
        source = _source_for(report_dir, pkg)
        if source in owners:
            raise CoverageGateError(
                f"{source} would be the report of both {owners[source]} and {pkg.name}"
            )
        owners[source] = pkg.name
    check_artifact_entry_count(report_dir)
    written: list[Path] = []

    for source, name in owners.items():
        pkg = packages[name]
        dest = own_report_path(report_dir, pkg)
        if os.path.lexists(dest.parent):
            raise ArtifactRefusedError(f"{dest.parent} exists; only flatten makes it")
        if not source.is_file():
            continue  # coverage_gate.py will report CI-COV-003 for this one

        data = read_artifact_bytes(report_dir, source, MAX_REPORT_BYTES)
        try:
            parse_report(data.decode("utf-8"), pkg.report_format)
        except UnicodeDecodeError as exc:
            raise CoverageGateError(f"{source} is not UTF-8") from exc
        except CoverageGateError as exc:
            raise CoverageGateError(f"{source}: {exc}") from exc
        if not dest.parent.parent.resolve().is_relative_to(report_dir.resolve()):
            raise ArtifactRefusedError(f"{dest.parent} resolves outside {report_dir}")
        dest.parent.mkdir()
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
