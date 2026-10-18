"""Unit tests for tools/ci/flatten_coverage_artifacts.py (E03-T04)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci import coverage_gate
from tools.ci.flatten_coverage_artifacts import flatten, main


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

    dest = report_dir / "coverage-unit-frontend" / "lcov.info"
    assert dest in written
    assert dest.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")


def test_flatten_skips_when_already_flat(tmp_path: Path) -> None:
    report_dir = tmp_path / "coverage-artifacts"
    dest = report_dir / "py-coverage" / "coverage.xml"
    # services/api uses coverage-xml, not lcov, so it should never be touched.
    dest.parent.mkdir(parents=True)
    dest.write_text("<coverage></coverage>", encoding="utf-8")

    written = flatten(report_dir)
    assert dest not in written


def test_flatten_missing_source_is_silently_skipped(tmp_path: Path) -> None:
    # No source files at all -> nothing written, no exception (coverage_gate.py
    # is responsible for reporting the resulting CI-COV-003).
    report_dir = tmp_path / "coverage-artifacts"
    assert flatten(report_dir) == []


def test_flatten_does_not_overwrite_existing_destination(tmp_path: Path) -> None:
    report_dir = tmp_path / "coverage-artifacts"
    existing = report_dir / "coverage-unit-engine" / "lcov.info"
    existing.parent.mkdir(parents=True)
    existing.write_text("already-here", encoding="utf-8")

    source = (
        report_dir
        / "coverage-unit-engine"
        / "packages"
        / "chart-engine"
        / "coverage"
        / "lcov.info"
    )
    source.parent.mkdir(parents=True)
    source.write_text("would-overwrite", encoding="utf-8")

    written = flatten(report_dir)
    assert existing not in written
    assert existing.read_text(encoding="utf-8") == "already-here"


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
        (artifact / "lcov.info").symlink_to(tmp_path / "elsewhere.info")
    elif case == "oversized":
        os.truncate(artifact / WEB_REPORT, coverage_gate.MAX_REPORT_BYTES + 1)
    elif case == "too-many":
        for i in range(coverage_gate.MAX_ARTIFACT_ENTRIES):
            (report_dir / f"extra-{i}").touch()

    assert main([str(report_dir)]) == 1
    assert "CI-COV-004" in capsys.readouterr().err
    assert not (artifact / "lcov.info").exists()
    assert not (tmp_path / "elsewhere.info").exists()


@pytest.mark.parametrize("data", [b"not lcov\n", b"SF:x\nLF:ten\n", b"SF:\xff\n"])
def test_main_rejects_a_malformed_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], data: bytes
) -> None:
    source = tmp_path / "coverage-unit-frontend" / WEB_REPORT
    source.parent.mkdir(parents=True)
    source.write_bytes(data)
    assert main([str(tmp_path)]) == 1
    assert "CI-COV-003" in capsys.readouterr().err
    assert not (tmp_path / "coverage-unit-frontend" / "lcov.info").exists()
