"""Unit tests for tools/ci/flatten_coverage_artifacts.py (E03-T04)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci import coverage_gate
from tools.ci.flatten_coverage_artifacts import _create_inside, flatten, main


def test_flatten_copies_web_lcov_to_expected_path(tmp_path: Path) -> None:
    report_dir = tmp_path / "coverage-artifacts"
    source = (
        report_dir
        / "coverage-unit-frontend"
        / "apps"
        / "web"
        / "coverage"
        / "lcov.info"
    )
    source.parent.mkdir(parents=True)
    source.write_text("SF:x.ts\nLF:10\nLH:8\nend_of_record\n", encoding="utf-8")

    written = flatten(report_dir)

    dest = report_dir / "coverage-unit-frontend" / "apps-app-web" / "lcov.info"
    assert dest in written
    assert dest.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")


def test_flatten_copies_the_flat_py_report_to_its_own_directory(tmp_path: Path) -> None:
    report_dir = tmp_path / "coverage-artifacts"
    source = report_dir / "py-coverage" / "coverage.xml"
    source.parent.mkdir(parents=True)
    source.write_text('<coverage line-rate="0.9"></coverage>', encoding="utf-8")

    dest = report_dir / "py-coverage" / "services-api" / "coverage.xml"
    assert flatten(report_dir) == [dest]
    assert dest.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")


def test_flatten_missing_source_is_silently_skipped(tmp_path: Path) -> None:
    # No source files at all -> nothing written, no exception (coverage_gate.py
    # is responsible for reporting the resulting CI-COV-003).
    report_dir = tmp_path / "coverage-artifacts"
    assert flatten(report_dir) == []


def test_main_cli_prints_flattened_paths(tmp_path: Path, capsys: object) -> None:
    from tools.ci.flatten_coverage_artifacts import main

    report_dir = tmp_path / "coverage-artifacts"
    source = (
        report_dir
        / "coverage-unit-frontend"
        / "apps"
        / "web"
        / "coverage"
        / "lcov.info"
    )
    source.parent.mkdir(parents=True)
    source.write_text("SF:x.ts\nLF:10\nLH:8\nend_of_record\n", encoding="utf-8")

    rc = main([str(report_dir)])
    assert rc == 0


def test_main_defaults_to_coverage_artifacts_dir() -> None:
    from tools.ci.flatten_coverage_artifacts import main

    # No CLI arg -> defaults to Path("coverage-artifacts"), which doesn't
    # exist in the test working directory, so flatten() finds nothing and
    # returns cleanly rather than raising.
    assert main([]) == 0


# --- Untrusted input (#3508): every artifact is read as untrusted input ------

WEB_REPORT = Path("apps") / "web" / "coverage" / "lcov.info"
VALID_LCOV = "SF:x.ts\nLF:10\nLH:8\nend_of_record\n"


@pytest.mark.parametrize(
    "case", ["file-link", "dir-link", "destination-link", "oversized", "too-many"]
)
def test_main_refuses_an_untrusted_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case: str
) -> None:
    outside = tmp_path / "outside"
    (outside / WEB_REPORT).parent.mkdir(parents=True)
    (outside / WEB_REPORT).write_text(VALID_LCOV, encoding="utf-8")
    report_dir = tmp_path / "coverage-artifacts"
    artifact = report_dir / "coverage-unit-frontend"
    if case == "dir-link":
        report_dir.mkdir()
        artifact.symlink_to(outside, target_is_directory=True)
    else:
        (artifact / WEB_REPORT).parent.mkdir(parents=True)
    if case == "file-link":
        (artifact / WEB_REPORT).symlink_to(outside / WEB_REPORT)
    elif case != "dir-link":
        (artifact / WEB_REPORT).write_text(VALID_LCOV, encoding="utf-8")
    if case == "destination-link":
        own = artifact / "apps-app-web"
        own.symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    elif case == "oversized":
        os.truncate(artifact / WEB_REPORT, coverage_gate.MAX_REPORT_BYTES + 1)
    elif case == "too-many":
        for i in range(coverage_gate.MAX_ARTIFACT_ENTRIES):
            (report_dir / f"extra-{i}").touch()

    assert main([str(report_dir)]) == 1
    assert "CI-COV-004" in capsys.readouterr().err
    assert not (artifact / "apps-app-web" / "lcov.info").exists()
    assert not (tmp_path / "elsewhere").exists()


@pytest.mark.parametrize("case", ["missing", "link-loop"])
def test_a_copy_whose_directory_does_not_resolve_is_refused(
    tmp_path: Path, case: str
) -> None:
    root = tmp_path / "coverage-artifacts"
    root.mkdir()
    artifact = root / "coverage-unit-frontend"
    if case == "link-loop":
        artifact.symlink_to(root / "loop")
        (root / "loop").symlink_to(artifact)
    with pytest.raises(coverage_gate.ArtifactRefusedError, match="does not resolve"):
        _create_inside(root, artifact / "lcov.info", VALID_LCOV.encode())
    assert not any(path.is_file() for path in tmp_path.rglob("*"))


@pytest.mark.parametrize("data", [b"not lcov\n", b"SF:x\nLF:ten\n", b"SF:\xff\n"])
def test_main_rejects_a_malformed_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], data: bytes
) -> None:
    source = tmp_path / "coverage-unit-frontend" / WEB_REPORT
    source.parent.mkdir(parents=True)
    source.write_bytes(data)
    assert main([str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "CI-COV-003" in err and str(source) in err
    assert not (tmp_path / "coverage-unit-frontend" / "apps-app-web").exists()


@pytest.mark.parametrize(
    ("case", "code"), [("malformed", "CI-COV-003"), ("oversized", "CI-COV-004")]
)
def test_main_writes_a_refusal_to_the_summary_the_pr_comment_posts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case: str, code: str
) -> None:
    source = tmp_path / "artifacts" / "coverage-unit-frontend" / WEB_REPORT
    source.parent.mkdir(parents=True)
    source.write_text(
        "not lcov\n" if case == "malformed" else VALID_LCOV, encoding="utf-8"
    )
    if case == "oversized":
        os.truncate(source, coverage_gate.MAX_REPORT_BYTES + 1)
    summary = tmp_path / "coverage-summary.md"
    assert main([str(tmp_path / "artifacts"), "--summary-out", str(summary)]) == 1
    assert summary.read_text(encoding="utf-8") == capsys.readouterr().err
    assert summary.read_text(encoding="utf-8").startswith(code)


PR_JOB = Path(__file__).resolve().parents[2] / ".github/workflows/_job-coverage.yml"
RATCHET_JOB = PR_JOB.with_name("coverage-ratchet.yml")


def test_the_pr_job_hands_flatten_the_summary_its_comment_posts() -> None:
    doc = yaml.safe_load(PR_JOB.read_text(encoding="utf-8"))
    steps = doc["jobs"]["coverage-thresholds"]["steps"]
    (flatten_run,) = [
        s["run"] for s in steps if "flatten_coverage_artifacts" in s.get("run", "")
    ]
    (comment,) = [s for s in steps if s.get("name") == "Post PR summary comment"]
    assert "--summary-out coverage-summary.md" in " ".join(flatten_run.split())
    assert "readFileSync('coverage-summary.md'" in comment["with"]["script"]
    assert "always()" in comment["if"]


def _gate_jobs(workflow: Path) -> list[list[dict[str, Any]]]:
    """The steps of each job in `workflow` that runs the coverage gate."""
    jobs = yaml.safe_load(workflow.read_text(encoding="utf-8")).get("jobs", {})
    steps = [job.get("steps", []) for job in jobs.values()]
    return [s for s in steps if any("coverage_gate" in x.get("run", "") for x in s)]


GATE_WORKFLOWS = [p for p in sorted(PR_JOB.parent.glob("*.y*ml")) if _gate_jobs(p)]


def test_the_order_pin_finds_both_workflows_that_run_the_gate_today() -> None:
    assert {PR_JOB, RATCHET_JOB} <= set(GATE_WORKFLOWS)


@pytest.mark.parametrize("workflow", GATE_WORKFLOWS, ids=lambda p: p.name)
def test_the_gate_reads_reports_only_after_flatten_succeeded(workflow: Path) -> None:
    # The gate trusts <artifact>/<package-slug>/ as flatten refuses a download that
    # already holds one (#3562): a refusal must end the job before the gate step.
    # Every workflow with a job that runs the gate is checked, not a fixed list.
    for steps in _gate_jobs(workflow):
        runs = [step.get("run", "") for step in steps]
        (flat,) = [i for i, run in enumerate(runs) if "flatten_coverage" in run]
        gate = [i for i, run in enumerate(runs) if "coverage_gate" in run]
        assert flat < min(gate)
        for i in (flat, *gate):
            assert not {"if", "continue-on-error"} & set(steps[i]), runs[i]


# --- Each package is judged on its own report (#3562) ------------------------


def _upload(report_dir: Path, artifact: str, hits: dict[str, int]) -> None:
    """Lay out an artifact as the JS lane uploads it: an lcov.info per repo directory."""
    for repo_dir, hit in hits.items():
        source = report_dir / artifact / repo_dir / "coverage" / "lcov.info"
        source.parent.mkdir(parents=True)
        record = f"SF:x.ts\nLF:100\nLH:{hit}\nBRF:100\nBRH:{hit}\nend_of_record\n"
        source.write_text(record, "utf-8")


def _judged(
    report_dir: Path, capsys: pytest.CaptureFixture[str]
) -> dict[str, tuple[str, str]]:
    """Flatten, then gate as _job-coverage.yml does: package -> (measured, verdict)."""
    assert main([str(report_dir)]) == 0
    capsys.readouterr()
    coverage_gate.main(["--report-dir", str(report_dir), "--ran-lanes", "js"])
    rows = [row.split("|") for row in capsys.readouterr().out.splitlines()[2:]]
    return {cells[1].strip(): (cells[4].strip(), cells[-2].strip()) for cells in rows}


def test_packages_sharing_an_artifact_are_each_judged_on_their_own_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    frontend = {"packages/ui": 100, "apps/web": 70, "apps/desktop": 90}
    _upload(tmp_path, "coverage-unit-frontend", frontend)
    engine = {"packages/chart-engine": 99, "packages/protocol": 80}
    _upload(tmp_path, "coverage-unit-engine", engine)
    judged = _judged(tmp_path, capsys)
    assert {name: measured for name, (measured, _) in judged.items()} == {
        "services/api": "MISSING",  # the py lane did not run
        "packages/chart-engine": "99.0%",
        "packages/protocol": "80.0%",
        "packages/ui": "100.0%",
        "apps/app-web": "70.0%",
        "apps/app-electron": "90.0%",
    }
    failed = {judged["apps/app-web"][1], judged["packages/protocol"][1]}
    assert failed == {"FAIL (CI-COV-001)"}


def test_a_package_without_its_own_report_fails_beside_one_with_a_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    frontend = {"packages/ui": 100, "apps/desktop": 90}
    _upload(tmp_path, "coverage-unit-frontend", frontend)
    assert _judged(tmp_path, capsys)["apps/app-web"] == ("MISSING", "FAIL (CI-COV-003)")


def test_a_package_directory_already_in_the_download_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _upload(tmp_path, "coverage-unit-engine", {"packages/chart-engine": 99})
    planted = tmp_path / "coverage-unit-engine" / "packages-protocol" / "lcov.info"
    planted.parent.mkdir()
    planted.write_text(VALID_LCOV, encoding="utf-8")
    assert main([str(tmp_path)]) == 1
    assert "CI-COV-004" in capsys.readouterr().err


def test_a_report_directory_is_never_made_outside_the_download(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report_dir, outside = tmp_path / "coverage-artifacts", tmp_path / "outside"
    _upload(report_dir, ".", {"apps/web": 90})  # the report resolves inside ...
    outside.mkdir()
    (outside / "apps").symlink_to(report_dir / "apps")
    # ... and its artifact outside
    (report_dir / "coverage-unit-frontend").symlink_to(outside)
    assert main([str(report_dir)]) == 1
    assert "CI-COV-004" in capsys.readouterr().err
    assert [path.name for path in outside.iterdir()] == ["apps"]


@pytest.mark.parametrize(
    "formats",
    [
        {"services/api": "coverage-xml", "services/worker": "coverage-xml"},
        {"apps/app-web": "lcov", "apps/web": "lcov"},
    ],
    ids=["one-flat-report", "one-repo-directory"],
)
def test_a_report_that_would_serve_two_packages_is_refused(
    tmp_path: Path, formats: dict[str, str]
) -> None:
    entry = {"floor": 80.0, "baseline": 80.0, "artifact": "shared"}
    packages = {name: {**entry, "report_format": f} for name, f in formats.items()}
    baselines = tmp_path / "baselines.json"
    baselines.write_text(json.dumps({"tolerance_pp": 0.5, "packages": packages}))
    with pytest.raises(coverage_gate.CoverageGateError, match="report of both"):
        flatten(tmp_path / "artifacts", baselines)
