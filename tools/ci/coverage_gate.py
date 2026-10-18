#!/usr/bin/env python3
"""E03-T04: per-package coverage threshold gate.

Reads `tools/ci/coverage-baselines.json` (package -> {floor, baseline,
artifact, report_format}) and per-package coverage reports (lcov.info or
coverage.xml, downloaded as CI artifacts by the caller workflow) and decides
pass/fail per package plus an overall verdict.

Error codes (ticket "Technical notes / design"):
    CI-COV-001  measured < floor
    CI-COV-002  measured < baseline - tolerance (regression, even if above
                floor)
    CI-COV-003  missing or unreadable coverage artifact for an applicable
                package (a silently-absent report must never pass)
    CI-COV-004  coverage artifact refused (#3508): artifacts are untrusted
                input (read_artifact_bytes, check_artifact_entry_count)

Ratchet mode (``--ratchet``, used only on merges to `main`): when a
package's measured coverage exceeds its recorded baseline by >=1.0 pp, the
gate emits a baseline-raise proposal (new baselines JSON) instead of
mutating the file itself — the caller workflow uses that to open a bot PR.
Baselines only ever move up here; lowering is a manual, CODEOWNER-gated
edit to the JSON file (see the file's own header comment). Proposals are
written only when no applicable artifact is missing or unreadable.

Stdlib only — no network access performed by this module.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.parsers import expat

RATCHET_STEP_PP = 1.0

# Untrusted-input bounds (#3508); on 2026-10-18 services/api's coverage.xml was
# about 2.5 MB and a full download held about 20 entries.
MAX_REPORT_BYTES = 32 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
MAX_ARTIFACT_ENTRIES = 1_000

# Which CI lane produces which coverage artifact. A package is *applicable* only
# when its producing lane ran in this workflow run; lanes are path-filtered
# (pr.yml `changed-paths`), so a py-only PR legitimately has no frontend
# artifacts. "Lane skipped" is N/A; "lane ran but no artifact" is CI-COV-003.
ARTIFACT_LANE: dict[str, str] = {
    "py-coverage": "py",
    "coverage-unit-engine": "js",
    "coverage-unit-frontend": "js",
}


class CoverageGateError(Exception):
    """Raised for malformed configuration; distinct from a gate *failure*
    (a failure is a normal, reported verdict — this is a setup bug)."""


class ArtifactRefusedError(Exception):
    """An artifact failed an untrusted-input bound and was not read (CI-COV-004)."""


def read_artifact_bytes(root: Path, path: Path, max_bytes: int) -> bytes:
    """Read an artifact file as untrusted input: after resolving links and `..`,
    `path` must be a regular file inside `root` of at most `max_bytes` bytes."""
    try:
        target = path.resolve(strict=True)
        inside = target.is_relative_to(root.resolve(strict=True))
    except (OSError, RuntimeError) as exc:
        raise ArtifactRefusedError(f"{path} does not resolve") from exc
    if not inside or not target.is_file():
        raise ArtifactRefusedError(f"{path} is not a regular file inside {root}")
    with target.open("rb") as fh:
        data = fh.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ArtifactRefusedError(f"{path} is over the {max_bytes}-byte bound")
    return data


def check_artifact_entry_count(root: Path) -> None:
    """Refuse a download of more than MAX_ARTIFACT_ENTRIES entries (links not followed)."""
    seen = 0
    for _, dirs, files in os.walk(root):
        seen += len(dirs) + len(files)
        if seen > MAX_ARTIFACT_ENTRIES:
            raise ArtifactRefusedError(
                f"{root} holds over {MAX_ARTIFACT_ENTRIES} entries"
            )


@dataclass(frozen=True)
class PackageConfig:
    name: str
    floor: float
    baseline: float
    artifact: str
    report_format: str


@dataclass(frozen=True)
class PackageResult:
    name: str
    floor: float
    baseline: float
    measured: float | None
    delta: float | None
    verdict: str  # "PASS" | "FAIL" | "N/A" (producing lane did not run)
    code: str | None
    reason: str | None


@dataclass(frozen=True)
class GateReport:
    results: list[PackageResult] = field(default_factory=list)

    @property
    def conclusion(self) -> str:
        return (
            "success"
            if all(r.verdict in ("PASS", "N/A") for r in self.results)
            else "failure"
        )


def load_config(path: Path) -> tuple[float, dict[str, PackageConfig]]:
    """Load `coverage-baselines.json`. Raises CoverageGateError on a
    malformed file (missing keys, non-numeric floor/baseline)."""
    try:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CoverageGateError(
            f"cannot read coverage baselines file {path}: {exc}"
        ) from exc

    tolerance = raw.get("tolerance_pp")
    if not isinstance(tolerance, (int, float)):
        raise CoverageGateError(
            "coverage-baselines.json missing numeric 'tolerance_pp'"
        )

    packages_raw = raw.get("packages")
    if not isinstance(packages_raw, dict) or not packages_raw:
        raise CoverageGateError(
            "coverage-baselines.json missing non-empty 'packages' object"
        )

    packages: dict[str, PackageConfig] = {}
    for name, cfg in packages_raw.items():
        try:
            packages[name] = PackageConfig(
                name=name,
                floor=float(cfg["floor"]),
                baseline=float(cfg["baseline"]),
                artifact=str(cfg["artifact"]),
                report_format=str(cfg["report_format"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CoverageGateError(f"malformed package entry {name!r}: {exc}") from exc

    return float(tolerance), packages


def _excerpt(value: str, limit: int = 40) -> str:
    """Quote at most `limit` characters of artifact text in a message."""
    return repr(value[:limit]) + ("..." if len(value) > limit else "")


def _no_doctype(*_: object) -> None:
    raise CoverageGateError("malformed coverage.xml: it declares a document type")


def parse_coverage_xml(text: str) -> float:
    """Parse a Cobertura-style `coverage.xml` (pytest-cov / coverage.py
    `--cov-report=xml`) and return the overall line-rate as a percentage.
    Raises CoverageGateError unless it is well-formed XML with no document
    type declaration (coverage.py writes none), a `<coverage>` root and a
    decimal line-rate in [0, 1]."""
    roots: list[tuple[str, dict[str, str]]] = []

    def start(name: str, attrs: dict[str, str]) -> None:
        if not roots:
            roots.append((name, attrs))

    parser = expat.ParserCreate()
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    parser.StartDoctypeDeclHandler = _no_doctype
    parser.StartElementHandler = start
    try:
        parser.Parse(text, True)
    except expat.ExpatError as exc:
        raise CoverageGateError(f"malformed coverage.xml: {exc}") from exc

    name, attrs = roots[0]
    line_rate = attrs.get("line-rate") if name == "coverage" else None
    if line_rate is None:
        raise CoverageGateError(
            "coverage.xml root element missing 'line-rate' attribute"
        )
    if not re.fullmatch(r"[0-9]+(\.[0-9]+)?([eE][-+]?[0-9]+)?", line_rate):
        raise CoverageGateError(
            f"coverage.xml has non-numeric line-rate {_excerpt(line_rate)}"
        )
    if not 0.0 <= float(line_rate) <= 1.0:
        raise CoverageGateError(
            f"coverage.xml line-rate {_excerpt(line_rate)} is outside [0, 1]"
        )
    return float(line_rate) * 100.0


# Every line of an lcov tracefile is one of these records; counts are integers.
_LCOV_RECORD = re.compile(
    r"end_of_record|(?:TN|VER|SF|FN|FNL|FNA|FNDA|DA|BRDA):.*"
    r"|(LF|LH|FNF|FNH|BRF|BRH):([0-9]{1,15})"
)


def parse_lcov(text: str) -> float:
    """Parse an lcov `lcov.info` file (Vitest `--coverage`) and return the
    aggregate line-coverage percentage across every `SF:` record
    (lines hit / lines found * 100). Raises CoverageGateError when a line
    is not an lcov record, more lines are hit than found, or the file has
    no `LF:`/`LH:` records at all (malformed / empty report)."""
    lines_found = 0
    lines_hit = 0
    seen_any_record = False
    for number, line in enumerate(text.splitlines(), start=1):
        record = _LCOV_RECORD.fullmatch(line.strip())
        if record is None and line.strip():
            raise CoverageGateError(f"malformed or empty lcov.info: line {number}")
        if record is not None and record[1] in ("LF", "LH"):
            seen_any_record = True
            if record[1] == "LF":
                lines_found += int(record[2])
            else:
                lines_hit += int(record[2])

    if not seen_any_record:
        raise CoverageGateError(
            "lcov.info has no LF:/LH: records (malformed or empty report)"
        )
    if lines_hit > lines_found:
        raise CoverageGateError("malformed or empty lcov.info: LH above LF")
    if lines_found == 0:
        return 0.0
    return (lines_hit / lines_found) * 100.0


def read_measured_coverage(
    report_path: Path, report_format: str, root: Path | None = None
) -> float:
    """Read and parse a coverage report file. Raises CoverageGateError if
    the file is absent (caller maps that to CI-COV-003, not this
    exception's own message, so the reason stays distinguishable) or
    malformed; ArtifactRefusedError past read_artifact_bytes' bounds
    (`root` defaults to the report's own directory)."""
    if not report_path.is_file():
        raise CoverageGateError(f"coverage report not found at {report_path}")
    data = read_artifact_bytes(
        root or report_path.parent, report_path, MAX_REPORT_BYTES
    )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CoverageGateError(f"{report_path} is not UTF-8") from exc
    if report_format == "coverage-xml":
        return parse_coverage_xml(text)
    if report_format == "lcov":
        return parse_lcov(text)
    raise CoverageGateError(f"unknown report_format {report_format!r}")


def evaluate_package(
    pkg: PackageConfig,
    report_path: Path,
    tolerance_pp: float,
    root: Path | None = None,
) -> PackageResult:
    """Evaluate one package against its floor and baseline.

    Precedence: a missing/unreadable artifact is CI-COV-003 regardless of
    what the (non-existent) number would have been. Otherwise floor is
    checked first (CI-COV-001), then baseline regression (CI-COV-002) —
    both are independently reported-worthy, but floor takes precedence in
    the single `code`/`reason` surfaced per scenario, matching the ticket's
    Gherkin (a below-floor package reports the floor failure even though it
    is trivially also below any baseline at/above the floor).
    """
    if not report_path.is_file():
        return PackageResult(
            name=pkg.name,
            floor=pkg.floor,
            baseline=pkg.baseline,
            measured=None,
            delta=None,
            verdict="FAIL",
            code="CI-COV-003",
            reason=f"missing coverage artifact for {pkg.name} (expected {report_path})",
        )

    try:
        measured = read_measured_coverage(report_path, pkg.report_format, root)
    except CoverageGateError as exc:
        return PackageResult(
            name=pkg.name,
            floor=pkg.floor,
            baseline=pkg.baseline,
            measured=None,
            delta=None,
            verdict="FAIL",
            code="CI-COV-003",
            reason=f"missing coverage artifact for {pkg.name}: {exc}",
        )

    delta = measured - pkg.baseline
    if measured < pkg.floor:
        return PackageResult(
            name=pkg.name,
            floor=pkg.floor,
            baseline=pkg.baseline,
            measured=measured,
            delta=delta,
            verdict="FAIL",
            code="CI-COV-001",
            reason=f"{pkg.name} {measured:.1f}% < floor {pkg.floor:.1f}%",
        )

    regression = pkg.baseline - measured
    if regression > tolerance_pp:
        return PackageResult(
            name=pkg.name,
            floor=pkg.floor,
            baseline=pkg.baseline,
            measured=measured,
            delta=delta,
            verdict="FAIL",
            code="CI-COV-002",
            reason=(
                f"regression {regression:.1f}pp beyond {tolerance_pp:.1f}pp tolerance "
                f"({pkg.name} baseline {pkg.baseline:.1f}% -> measured {measured:.1f}%)"
            ),
        )

    return PackageResult(
        name=pkg.name,
        floor=pkg.floor,
        baseline=pkg.baseline,
        measured=measured,
        delta=delta,
        verdict="PASS",
        code=None,
        reason=None,
    )


AFFECTED_MANIFEST = "affected-packages.txt"

# Ticket package labels vs. repo directories (mirrors flatten_coverage_artifacts.py).
_PACKAGE_TO_REPO_DIR: dict[str, str] = {
    "apps/app-web": "apps/web",
    "apps/app-electron": "apps/desktop",
}


def _affected_by_change_set(package: str, artifact_dir: Path, root: Path) -> bool:
    """The JS lanes run `turbo run test:cov --filter=<pkg>...[origin/main]`, so a
    package untouched by the PR is never scheduled and writes no lcov. The lane
    uploads `affected-packages.txt` (tools/ci/turbo-affected-packages.mjs) listing
    the repo directories turbo *did* schedule. A package absent from that list is
    N/A. No manifest at all = legacy artifact = every package is required, so a
    lane that forgot to upload it can never make packages vanish silently."""
    manifest = artifact_dir / AFFECTED_MANIFEST
    if not manifest.is_file():
        return True
    try:
        text = read_artifact_bytes(root, manifest, MAX_MANIFEST_BYTES).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ArtifactRefusedError(f"{manifest} is not UTF-8") from exc
    listed = {
        line.strip().replace("\\", "/").rstrip("/")
        for line in text.splitlines()
        if line.strip()
    }
    return _PACKAGE_TO_REPO_DIR.get(package, package) in listed


def evaluate_all(
    packages: dict[str, PackageConfig],
    report_dir: Path,
    tolerance_pp: float,
    report_filenames: dict[str, str] | None = None,
    ran_lanes: set[str] | None = None,
) -> GateReport:
    """Evaluate every configured package. `report_filenames` maps package
    name -> the filename to look for under `report_dir/<artifact>/`
    (defaults to `coverage.xml` for coverage-xml, `lcov.info` for lcov).
    `ran_lanes` (None = all lanes ran) marks packages whose producing lane was
    path-skipped as N/A instead of CI-COV-003."""
    results: list[PackageResult] = []
    for name, pkg in packages.items():
        lane = ARTIFACT_LANE.get(pkg.artifact)
        if ran_lanes is not None and lane is not None and lane not in ran_lanes:
            results.append(
                PackageResult(
                    name=name,
                    floor=pkg.floor,
                    baseline=pkg.baseline,
                    measured=None,
                    delta=None,
                    verdict="N/A",
                    code=None,
                    reason=f"{lane} lane did not run for this change set",
                )
            )
            continue
        if not _affected_by_change_set(name, report_dir / pkg.artifact, report_dir):
            results.append(
                PackageResult(
                    name=name,
                    floor=pkg.floor,
                    baseline=pkg.baseline,
                    measured=None,
                    delta=None,
                    verdict="N/A",
                    code=None,
                    reason="package not in the lane's turbo affected graph for this change set",
                )
            )
            continue
        filename: str
        if report_filenames and name in report_filenames:
            filename = report_filenames[name]
        else:
            filename = (
                "coverage.xml" if pkg.report_format == "coverage-xml" else "lcov.info"
            )
        report_path = report_dir / pkg.artifact / filename
        results.append(evaluate_package(pkg, report_path, tolerance_pp, report_dir))
    return GateReport(results=results)


def compute_ratchet_proposals(report: GateReport) -> dict[str, float]:
    """Packages whose measured coverage exceeds their baseline by
    >= RATCHET_STEP_PP, mapped to the proposed new baseline (rounded to 1
    decimal place). Only PASS-ing packages are considered; a package that
    is failing has nothing to ratchet."""
    proposals: dict[str, float] = {}
    for r in report.results:
        if r.verdict != "PASS" or r.measured is None:
            continue
        if r.measured - r.baseline >= RATCHET_STEP_PP:
            proposals[r.name] = round(r.measured, 1)
    return proposals


def render_summary_table(report: GateReport) -> str:
    """PR-comment summary table: package, floor, baseline, measured, delta,
    verdict — words (PASS/FAIL) not colours, per the accessibility note."""
    header = "| package | floor | baseline | measured | delta | verdict |"
    sep = "| --- | --- | --- | --- | --- | --- |"
    rows = [header, sep]
    for r in report.results:
        measured_s = f"{r.measured:.1f}%" if r.measured is not None else "MISSING"
        delta_s = f"{r.delta:+.1f}pp" if r.delta is not None else "n/a"
        verdict_s = f"{r.verdict}" + (f" ({r.code})" if r.code else "")
        rows.append(
            f"| {r.name} | {r.floor:.1f}% | {r.baseline:.1f}% | {measured_s} | {delta_s} | {verdict_s} |"
        )
    return "\n".join(rows)


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baselines",
        type=Path,
        default=Path(__file__).parent / "coverage-baselines.json",
        help="Path to coverage-baselines.json",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path("coverage-artifacts"),
        help="Directory containing one subdirectory per downloaded coverage artifact",
    )
    parser.add_argument(
        "--ran-lanes",
        default=None,
        help="Comma-separated lanes that ran (e.g. 'py' or 'js,py'); packages whose "
        "producing lane is absent report N/A. Omit to require every artifact.",
    )
    parser.add_argument(
        "--ratchet",
        action="store_true",
        help="Emit baseline-raise proposals (used on merges to main only)",
    )
    parser.add_argument(
        "--summary-out",
        type=Path,
        default=None,
        help="Write the PR-comment summary table (Markdown) to this path",
    )
    parser.add_argument(
        "--ratchet-out",
        type=Path,
        default=None,
        help="Write ratchet proposals as JSON ({package: new_baseline}) to this path",
    )
    args = parser.parse_args(argv)

    try:
        tolerance_pp, packages = load_config(args.baselines)
    except CoverageGateError as exc:
        print(f"coverage gate configuration error: {exc}", file=sys.stderr)
        return 2

    ran_lanes = (
        {x.strip() for x in args.ran_lanes.split(",") if x.strip()}
        if args.ran_lanes is not None
        else None
    )
    try:
        check_artifact_entry_count(args.report_dir)
        report = evaluate_all(
            packages, args.report_dir, tolerance_pp, ran_lanes=ran_lanes
        )
    except ArtifactRefusedError as exc:
        refusal = f"CI-COV-004: coverage artifact refused: {exc}"
        print(refusal, file=sys.stderr)
        if args.summary_out is not None:
            args.summary_out.write_text(refusal + "\n", encoding="utf-8")
        return 1
    summary = render_summary_table(report)
    print(summary)

    if args.summary_out is not None:
        args.summary_out.write_text(summary + "\n", encoding="utf-8")

    for r in report.results:
        if r.verdict == "FAIL":
            print(f"{r.code}: {r.reason}", file=sys.stderr)

    if args.ratchet:
        # Fail closed (#3508); a floor or regression failure is the PR gate's verdict.
        if any(r.code == "CI-COV-003" for r in report.results):
            print("ratchet: no proposals written (CI-COV-003 above)", file=sys.stderr)
            return 1
        proposals = compute_ratchet_proposals(report)
        if args.ratchet_out is not None:
            args.ratchet_out.write_text(
                json.dumps(proposals, indent=2) + "\n", encoding="utf-8"
            )
        if proposals:
            print(f"ratchet proposals: {json.dumps(proposals)}")
        return 0

    return 0 if report.conclusion == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
