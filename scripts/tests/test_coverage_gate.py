"""Unit tests for tools/ci/coverage_gate.py (E03-T04).

Covers the four Gherkin acceptance scenarios plus the fixture matrix named
in the ticket's Test plan: below floor, at floor, above baseline, within
tolerance, missing artifact, malformed lcov, malformed coverage.xml.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci import coverage_gate
from tools.ci.coverage_gate import (
    CoverageGateError,
    PackageConfig,
    PackageResult,
    compute_ratchet_proposals,
    evaluate_all,
    evaluate_package,
    load_config,
    parse_coverage_xml,
    parse_lcov,
    render_summary_table,
)


def _lcov(lines_found: int, lines_hit: int) -> str:
    return f"SF:src/x.ts\nLF:{lines_found}\nLH:{lines_hit}\nend_of_record\n"


def _coverage_xml(line_rate: float) -> str:
    return f'<?xml version="1.0"?><coverage line-rate="{line_rate}"></coverage>'


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# Where flatten_coverage_artifacts.py puts a package's own report (#3562).
API_REPORT = Path("py-coverage") / "services-api" / "coverage.xml"
PROTOCOL_REPORT = Path("coverage-unit-engine") / "packages-protocol" / "lcov.info"
UI_REPORT = Path("coverage-unit-frontend") / "packages-ui" / "lcov.info"


# --- Gherkin scenario 1: below floor fails --------------------------------


def test_evaluate_package_below_floor_fails(tmp_path: Path) -> None:
    pkg = PackageConfig(
        "services/api",
        floor=85.0,
        baseline=85.0,
        artifact="py-coverage",
        report_format="coverage-xml",
    )
    report_path = _write(tmp_path / "coverage.xml", _coverage_xml(0.832))
    result = evaluate_package(pkg, report_path, tolerance_pp=0.5)
    assert result.verdict == "FAIL"
    assert result.code == "CI-COV-001"
    assert result.reason == "services/api 83.2% < floor 85.0%"


# --- Gherkin scenario 2: regression beyond tolerance fails, even above floor


def test_evaluate_package_baseline_regression_beyond_tolerance_fails(
    tmp_path: Path,
) -> None:
    pkg = PackageConfig(
        "packages/ui",
        floor=80.0,
        baseline=91.0,
        artifact="coverage-unit-frontend",
        report_format="lcov",
    )
    report_path = _write(tmp_path / "lcov.info", _lcov(lines_found=1000, lines_hit=880))
    result = evaluate_package(pkg, report_path, tolerance_pp=0.5)
    assert result.verdict == "FAIL"
    assert result.code == "CI-COV-002"
    assert "regression 3.0pp beyond 0.5pp tolerance" in result.reason


# --- Gherkin scenario 3: ratchet proposal on improvement ------------------


def test_ratchet_proposal_emitted_when_measured_exceeds_baseline_by_at_least_one_pp() -> (
    None
):
    from tools.ci.coverage_gate import GateReport, PackageResult

    report = GateReport(
        results=[
            PackageResult(
                name="packages/protocol",
                floor=85.0,
                baseline=88.0,
                measured=89.4,
                delta=1.4,
                verdict="PASS",
                code=None,
                reason=None,
            )
        ]
    )
    proposals = compute_ratchet_proposals(report)
    assert proposals == {"packages/protocol": 89.4}


def test_ratchet_proposal_not_emitted_below_one_pp_improvement() -> None:
    from tools.ci.coverage_gate import GateReport, PackageResult

    report = GateReport(
        results=[
            PackageResult(
                name="packages/protocol",
                floor=85.0,
                baseline=88.0,
                measured=88.6,
                delta=0.6,
                verdict="PASS",
                code=None,
                reason=None,
            )
        ]
    )
    assert compute_ratchet_proposals(report) == {}


# --- Gherkin scenario 4: missing artifact is a failure --------------------


def test_evaluate_package_missing_artifact_fails(tmp_path: Path) -> None:
    pkg = PackageConfig(
        "packages/chart-engine",
        floor=85.0,
        baseline=85.0,
        artifact="coverage-unit-engine",
        report_format="lcov",
    )
    missing_path = tmp_path / "does-not-exist" / "lcov.info"
    result = evaluate_package(pkg, missing_path, tolerance_pp=0.5)
    assert result.verdict == "FAIL"
    assert result.code == "CI-COV-003"
    assert "missing coverage artifact" in result.reason


# --- Additional fixture-matrix cases (ticket Test plan) -------------------


def test_evaluate_package_at_floor_exactly_passes(tmp_path: Path) -> None:
    pkg = PackageConfig(
        "services/api",
        floor=85.0,
        baseline=85.0,
        artifact="py-coverage",
        report_format="coverage-xml",
    )
    report_path = _write(tmp_path / "coverage.xml", _coverage_xml(0.85))
    result = evaluate_package(pkg, report_path, tolerance_pp=0.5)
    assert result.verdict == "PASS"


def test_evaluate_package_regression_within_tolerance_passes(tmp_path: Path) -> None:
    pkg = PackageConfig(
        "packages/ui",
        floor=80.0,
        baseline=91.0,
        artifact="coverage-unit-frontend",
        report_format="lcov",
    )
    # 90.6% is 0.4pp below baseline — within the 0.5pp tolerance.
    report_path = _write(tmp_path / "lcov.info", _lcov(lines_found=1000, lines_hit=906))
    result = evaluate_package(pkg, report_path, tolerance_pp=0.5)
    assert result.verdict == "PASS"


def test_evaluate_package_above_baseline_passes(tmp_path: Path) -> None:
    pkg = PackageConfig(
        "packages/protocol",
        floor=85.0,
        baseline=88.0,
        artifact="coverage-unit-engine",
        report_format="lcov",
    )
    report_path = _write(tmp_path / "lcov.info", _lcov(lines_found=1000, lines_hit=894))
    result = evaluate_package(pkg, report_path, tolerance_pp=0.5)
    assert result.verdict == "PASS"
    assert result.measured == pytest.approx(89.4)


def test_parse_lcov_malformed_raises() -> None:
    with pytest.raises(CoverageGateError, match="malformed or empty"):
        parse_lcov("this is not an lcov file\n")


def test_parse_coverage_xml_malformed_raises() -> None:
    with pytest.raises(CoverageGateError, match="malformed coverage.xml"):
        parse_coverage_xml("<not-xml")


def test_parse_coverage_xml_missing_line_rate_raises() -> None:
    with pytest.raises(CoverageGateError, match="line-rate"):
        parse_coverage_xml("<coverage></coverage>")


def test_evaluate_package_malformed_lcov_is_missing_artifact_failure(
    tmp_path: Path,
) -> None:
    pkg = PackageConfig(
        "packages/chart-engine",
        floor=85.0,
        baseline=85.0,
        artifact="coverage-unit-engine",
        report_format="lcov",
    )
    report_path = _write(tmp_path / "lcov.info", "garbage, not lcov at all\n")
    result = evaluate_package(pkg, report_path, tolerance_pp=0.5)
    assert result.verdict == "FAIL"
    assert result.code == "CI-COV-003"


def test_evaluate_package_malformed_coverage_xml_is_missing_artifact_failure(
    tmp_path: Path,
) -> None:
    pkg = PackageConfig(
        "services/api",
        floor=85.0,
        baseline=85.0,
        artifact="py-coverage",
        report_format="coverage-xml",
    )
    report_path = _write(tmp_path / "coverage.xml", "<broken")
    result = evaluate_package(pkg, report_path, tolerance_pp=0.5)
    assert result.verdict == "FAIL"
    assert result.code == "CI-COV-003"


# --- Config loading --------------------------------------------------------


def test_load_config_reads_real_baselines_file() -> None:
    baselines_path = (
        Path(__file__).resolve().parents[2] / "tools" / "ci" / "coverage-baselines.json"
    )
    tolerance, packages = load_config(baselines_path)
    assert tolerance == pytest.approx(0.5)
    assert "services/api" in packages
    assert packages["services/api"].floor == pytest.approx(85.0)


def test_load_config_missing_tolerance_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            {
                "packages": {
                    "x": {
                        "floor": 1,
                        "baseline": 1,
                        "artifact": "a",
                        "report_format": "lcov",
                    }
                }
            }
        )
    )
    with pytest.raises(CoverageGateError, match="tolerance_pp"):
        load_config(bad)


def test_load_config_missing_packages_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"tolerance_pp": 0.5}))
    with pytest.raises(CoverageGateError, match="packages"):
        load_config(bad)


def test_load_config_malformed_package_entry_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({"tolerance_pp": 0.5, "packages": {"x": {"floor": "not-a-number"}}})
    )
    with pytest.raises(CoverageGateError, match="malformed package entry"):
        load_config(bad)


def test_load_config_unreadable_file_raises(tmp_path: Path) -> None:
    with pytest.raises(CoverageGateError, match="cannot read"):
        load_config(tmp_path / "does-not-exist.json")


# --- evaluate_all / summary table ------------------------------------------


def test_evaluate_all_mixed_pass_and_fail(tmp_path: Path) -> None:
    packages = {
        "services/api": PackageConfig(
            "services/api", 85.0, 85.0, "py-coverage", "coverage-xml"
        ),
        "packages/ui": PackageConfig(
            "packages/ui", 80.0, 80.0, "coverage-unit-frontend", "lcov"
        ),
    }
    _write(tmp_path / API_REPORT, _coverage_xml(0.90))
    _write(tmp_path / UI_REPORT, _lcov(1000, 700))

    report = evaluate_all(packages, tmp_path, tolerance_pp=0.5)
    verdicts = {r.name: r.verdict for r in report.results}
    assert verdicts["services/api"] == "PASS"
    assert verdicts["packages/ui"] == "FAIL"
    assert report.conclusion == "failure"


def test_render_summary_table_uses_words_not_colour() -> None:
    packages = {
        "services/api": PackageConfig(
            "services/api", 85.0, 85.0, "py-coverage", "coverage-xml"
        )
    }
    report = evaluate_all(packages, Path("/nonexistent"), tolerance_pp=0.5)
    table = render_summary_table(report)
    assert "PASS" in table or "FAIL" in table
    assert "package" in table and "verdict" in table


def test_parse_coverage_xml_non_numeric_line_rate_raises() -> None:
    with pytest.raises(CoverageGateError, match="non-numeric line-rate"):
        parse_coverage_xml('<coverage line-rate="not-a-number"></coverage>')


def test_read_measured_coverage_unknown_format_raises(tmp_path: Path) -> None:
    from tools.ci.coverage_gate import read_measured_coverage

    report_path = _write(tmp_path / "report.txt", "x")
    with pytest.raises(CoverageGateError, match="unknown report_format"):
        read_measured_coverage(report_path, "unknown-format")


def test_read_measured_coverage_missing_file_raises(tmp_path: Path) -> None:
    from tools.ci.coverage_gate import read_measured_coverage

    with pytest.raises(CoverageGateError, match="not found"):
        read_measured_coverage(tmp_path / "nope.info", "lcov")


def test_parse_lcov_zero_lines_found_returns_zero() -> None:
    assert parse_lcov("SF:x.ts\nLF:0\nLH:0\nend_of_record\n") == (0.0, None)


# --- CLI main() -------------------------------------------------------------


def test_main_passes_writes_summary_and_returns_zero(tmp_path: Path) -> None:
    from tools.ci.coverage_gate import main

    baselines = tmp_path / "coverage-baselines.json"
    baselines.write_text(
        json.dumps(
            {
                "tolerance_pp": 0.5,
                "packages": {
                    "services/api": {
                        "floor": 85.0,
                        "baseline": 85.0,
                        "artifact": "py-coverage",
                        "report_format": "coverage-xml",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    report_dir = tmp_path / "artifacts"
    _write(report_dir / API_REPORT, _coverage_xml(0.90))
    summary_out = tmp_path / "summary.md"

    rc = main(
        [
            "--baselines",
            str(baselines),
            "--report-dir",
            str(report_dir),
            "--summary-out",
            str(summary_out),
        ]
    )
    assert rc == 0
    assert "services/api" in summary_out.read_text(encoding="utf-8")


def test_main_fails_and_prints_error_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from tools.ci.coverage_gate import main

    baselines = tmp_path / "coverage-baselines.json"
    baselines.write_text(
        json.dumps(
            {
                "tolerance_pp": 0.5,
                "packages": {
                    "services/api": {
                        "floor": 85.0,
                        "baseline": 85.0,
                        "artifact": "py-coverage",
                        "report_format": "coverage-xml",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    rc = main(
        ["--baselines", str(baselines), "--report-dir", str(tmp_path / "no-artifacts")]
    )
    assert rc == 1
    assert "CI-COV-003" in capsys.readouterr().err


def test_main_ratchet_writes_proposals_file(tmp_path: Path) -> None:
    from tools.ci.coverage_gate import main

    baselines = tmp_path / "coverage-baselines.json"
    baselines.write_text(
        json.dumps(
            {
                "tolerance_pp": 0.5,
                "packages": {
                    "packages/protocol": {
                        "floor": 85.0,
                        "baseline": 88.0,
                        "artifact": "coverage-unit-engine",
                        "report_format": "lcov",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    report_dir = tmp_path / "artifacts"
    _write(report_dir / PROTOCOL_REPORT, _lcov(1000, 894))
    ratchet_out = tmp_path / "ratchet.json"

    rc = main(
        [
            "--baselines",
            str(baselines),
            "--report-dir",
            str(report_dir),
            "--ratchet",
            "--ratchet-out",
            str(ratchet_out),
        ]
    )
    assert rc == 0
    proposals = json.loads(ratchet_out.read_text(encoding="utf-8"))
    assert proposals == {"packages/protocol": 89.4}


def test_main_bad_config_returns_two(tmp_path: Path) -> None:
    from tools.ci.coverage_gate import main

    baselines = tmp_path / "coverage-baselines.json"
    baselines.write_text("not json", encoding="utf-8")
    assert main(["--baselines", str(baselines)]) == 2


# --- Lane applicability (path-filtered lanes) -----------------------------


def _engine_pkg() -> PackageConfig:
    return PackageConfig(
        "packages/chart-engine",
        floor=85.0,
        baseline=85.0,
        artifact="coverage-unit-engine",
        report_format="lcov",
    )


def test_missing_artifact_is_na_when_producing_lane_did_not_run(tmp_path: Path) -> None:
    # A py-only PR skips the js lane; frontend/engine artifacts legitimately do not exist.
    report = evaluate_all(
        {"packages/chart-engine": _engine_pkg()},
        tmp_path,
        tolerance_pp=0.5,
        ran_lanes={"py"},
    )
    (r,) = report.results
    assert r.verdict == "N/A"
    assert r.code is None
    assert report.conclusion == "success"


def test_missing_artifact_still_fails_when_producing_lane_ran(tmp_path: Path) -> None:
    report = evaluate_all(
        {"packages/chart-engine": _engine_pkg()},
        tmp_path,
        tolerance_pp=0.5,
        ran_lanes={"js", "py"},
    )
    (r,) = report.results
    assert r.verdict == "FAIL"
    assert r.code == "CI-COV-003"
    assert report.conclusion == "failure"


def test_ran_lanes_none_requires_every_artifact(tmp_path: Path) -> None:
    # Backwards compatible: no lane info means every configured package is applicable.
    report = evaluate_all(
        {"packages/chart-engine": _engine_pkg()}, tmp_path, tolerance_pp=0.5
    )
    assert report.results[0].code == "CI-COV-003"


# --- Turbo affected-graph manifest (affected-packages.txt) -----------------


def _write_manifest(tmp_path: Path, artifact: str, lines: list[str]) -> None:
    d = tmp_path / artifact
    d.mkdir(parents=True, exist_ok=True)
    (d / "affected-packages.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_unaffected_package_is_na_when_manifest_omits_it(tmp_path: Path) -> None:
    # An e2e-config-only PR: the js lane ran but turbo never scheduled chart-engine.
    _write_manifest(tmp_path, "coverage-unit-engine", ["packages/protocol"])
    report = evaluate_all(
        {"packages/chart-engine": _engine_pkg()},
        tmp_path,
        tolerance_pp=0.5,
        ran_lanes={"js"},
    )
    (r,) = report.results
    assert r.verdict == "N/A"
    assert "affected graph" in r.reason
    assert report.conclusion == "success"


def test_affected_package_without_report_still_fails(tmp_path: Path) -> None:
    _write_manifest(tmp_path, "coverage-unit-engine", ["packages/chart-engine"])
    report = evaluate_all(
        {"packages/chart-engine": _engine_pkg()},
        tmp_path,
        tolerance_pp=0.5,
        ran_lanes={"js"},
    )
    assert report.results[0].code == "CI-COV-003"


def test_missing_manifest_requires_every_package(tmp_path: Path) -> None:
    # Legacy artifact without the manifest: fail closed, never silently N/A.
    (tmp_path / "coverage-unit-engine").mkdir()
    report = evaluate_all(
        {"packages/chart-engine": _engine_pkg()},
        tmp_path,
        tolerance_pp=0.5,
        ran_lanes={"js"},
    )
    assert report.results[0].code == "CI-COV-003"


def test_manifest_maps_ticket_label_to_repo_dir(tmp_path: Path) -> None:
    # coverage-baselines.json names apps/app-web; turbo reports apps/web.
    _write_manifest(tmp_path, "coverage-unit-frontend", [r"apps\web"])
    web = PackageConfig(
        "apps/app-web",
        floor=80.0,
        baseline=80.0,
        artifact="coverage-unit-frontend",
        report_format="lcov",
    )
    report = evaluate_all(
        {"apps/app-web": web}, tmp_path, tolerance_pp=0.5, ran_lanes={"js"}
    )
    assert (
        report.results[0].code == "CI-COV-003"
    )  # listed (after normalising) but no lcov


# --- Untrusted input (#3508): every artifact is read as untrusted input ------


def _protocol_code(report_dir: Path, artifact: str = "coverage-unit-engine") -> str:
    pkg = PackageConfig("packages/protocol", 85.0, 85.0, artifact, "lcov")
    (result,) = evaluate_all({pkg.name: pkg}, report_dir, tolerance_pp=0.5).results
    return str(result.code)


@pytest.mark.parametrize(
    "case", ["file-link", "dir-link", "dot-dot", "absolute", "oversized"]
)
def test_evaluate_all_refuses_an_untrusted_report(tmp_path: Path, case: str) -> None:
    outside_dir = tmp_path / "outside"
    outside = _write(outside_dir / "packages-protocol" / "lcov.info", _lcov(1000, 990))
    report_dir = tmp_path / "artifacts"
    artifact = report_dir / "coverage-unit-engine"
    report_dir.mkdir()
    if case == "file-link":
        (report_dir / PROTOCOL_REPORT).parent.mkdir(parents=True)
        (report_dir / PROTOCOL_REPORT).symlink_to(outside)
    elif case == "dir-link":
        artifact.symlink_to(outside_dir, target_is_directory=True)
    elif case == "oversized":
        report = _write(report_dir / PROTOCOL_REPORT, _lcov(1000, 990))
        os.truncate(report, coverage_gate.MAX_REPORT_BYTES + 1)
    leave = {"dot-dot": "../outside", "absolute": str(outside_dir)}
    with pytest.raises(coverage_gate.ArtifactRefusedError):
        _protocol_code(report_dir, leave.get(case, artifact.name))


@pytest.mark.parametrize("case", ["link", "oversized", "not-utf8"])
def test_evaluate_all_refuses_an_untrusted_manifest(tmp_path: Path, case: str) -> None:
    report_dir = tmp_path / "artifacts"
    _write(report_dir / "coverage-unit-engine" / "lcov.info", _lcov(1000, 990))
    manifest = report_dir / "coverage-unit-engine" / "affected-packages.txt"
    if case == "link":
        manifest.symlink_to(_write(tmp_path / "outside.txt", "packages/chart-engine\n"))
    else:
        manifest.write_bytes(
            b"\xff\n" if case == "not-utf8" else b"packages/protocol\n"
        )
    if case == "oversized":
        os.truncate(manifest, coverage_gate.MAX_MANIFEST_BYTES + 1)
    with pytest.raises(coverage_gate.ArtifactRefusedError):
        _protocol_code(report_dir)


def test_evaluate_all_rejects_a_report_that_is_not_utf8(tmp_path: Path) -> None:
    (tmp_path / PROTOCOL_REPORT).parent.mkdir(parents=True)
    (tmp_path / PROTOCOL_REPORT).write_bytes(b"SF:\xff\nLF:1\n")
    assert _protocol_code(tmp_path) == "CI-COV-003"


@pytest.mark.parametrize(
    "text",
    [
        "SF:x.ts\nLF:ten\nLH:8\nend_of_record\n",
        "SF:x.ts\nLF:-10\nLH:-8\nend_of_record\n",
        "SF:x.ts\nLF:\u0661\u0660\nLH:8\nend_of_record\n",
        "SF:x.ts\nXY:1\nLF:10\nLH:8\nend_of_record\n",
        "SF:x.ts\nLF:10\nLH:11\nend_of_record\n",
        "SF:x.ts\nLF:10\nLH:8\nBRF:1\nBRH:2\nend_of_record\n",
    ],
    ids=[
        "non-integer",
        "negative",
        "non-ascii-digits",
        "unknown-record",
        "hit>found",
        "branch-hit>found",
    ],
)
def test_parse_lcov_rejects_a_report_outside_the_tracefile_format(text: str) -> None:
    with pytest.raises(CoverageGateError, match="malformed"):
        parse_lcov(text)


def test_parse_lcov_reads_every_record_type_a_vitest_report_writes() -> None:
    text = (
        "TN:\nSF:src/a.ts\nFN:1,f\nFNF:1\nFNH:1\nFNDA:3,f\nDA:1,3\nDA:2,0\n"
        "LF:2\nLH:1\nBRDA:1,0,0,1\nBRDA:1,0,1,-\nBRF:2\nBRH:1\nend_of_record\n"
    )
    assert parse_lcov(text) == pytest.approx((50.0, 50.0))


@pytest.mark.parametrize(
    "text",
    [
        '<?xml version="1.0"?><!DOCTYPE coverage><coverage line-rate="0.9"/>',
        '<report line-rate="0.9"></report>',
        '<coverage line-rate="1.5"></coverage>',
        '<coverage line-rate="nan"></coverage>',
        '<coverage line-rate="1_0"></coverage>',
    ],
    ids=["doctype", "wrong-root", "above-one", "not-a-number", "python-literal"],
)
def test_parse_coverage_xml_rejects_a_report_outside_the_cobertura_shape(
    text: str,
) -> None:
    with pytest.raises(CoverageGateError):
        parse_coverage_xml(text)


@pytest.mark.parametrize(
    "line_rate", ["x" * 10_000, "9" * 10_000], ids=["not-a-number", "above-one"]
)
def test_parse_coverage_xml_quotes_at_most_an_excerpt_of_a_bad_line_rate(
    line_rate: str,
) -> None:
    with pytest.raises(CoverageGateError) as raised:
        parse_coverage_xml(f'<coverage line-rate="{line_rate}"></coverage>')
    assert len(str(raised.value)) <= 100


def test_parse_coverage_xml_reads_a_coverage_py_report() -> None:
    text = (
        '<?xml version="1.0" ?>\n<coverage version="7.16.1" line-rate="0.9792">\n'
        "\t<!-- Generated by coverage.py -->\n\t<sources><source>cv</source></sources>\n"
        "</coverage>\n"
    )
    assert parse_coverage_xml(text) == pytest.approx((97.92, None))


def _baselines_file(tmp_path: Path) -> Path:
    lcov = {"floor": 85.0, "baseline": 85.0, "report_format": "lcov"}
    packages = {
        "packages/protocol": {**lcov, "artifact": "coverage-unit-engine"},
        "packages/ui": {**lcov, "floor": 80.0, "artifact": "coverage-unit-frontend"},
    }
    path = tmp_path / "coverage-baselines.json"
    path.write_text(json.dumps({"tolerance_pp": 0.5, "packages": packages}))
    return path


def _main(tmp_path: Path, report_dir: Path, *extra: str) -> int:
    baselines = str(_baselines_file(tmp_path))
    return coverage_gate.main(
        ["--baselines", baselines, "--report-dir", str(report_dir), *extra]
    )


def test_main_refuses_a_download_with_too_many_entries(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report_dir = tmp_path / "artifacts"
    _write(report_dir / "coverage-unit-engine" / "lcov.info", _lcov(1000, 990))
    for i in range(coverage_gate.MAX_ARTIFACT_ENTRIES):
        (report_dir / f"extra-{i}").touch()
    summary = tmp_path / "summary.md"
    assert _main(tmp_path, report_dir, "--summary-out", str(summary)) == 1
    assert "CI-COV-004" in capsys.readouterr().err
    assert "CI-COV-004" in summary.read_text(encoding="utf-8")


@pytest.mark.parametrize("case", ["file-link", "oversized"])
def test_main_refuses_an_untrusted_report_with_ci_cov_004(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case: str
) -> None:
    report_dir = tmp_path / "artifacts"
    report = report_dir / PROTOCOL_REPORT
    if case == "file-link":
        report.parent.mkdir(parents=True)
        report.symlink_to(_write(tmp_path / "outside.info", _lcov(1000, 990)))
    else:
        os.truncate(
            _write(report, _lcov(1000, 990)), coverage_gate.MAX_REPORT_BYTES + 1
        )
    summary = tmp_path / "summary.md"
    assert _main(tmp_path, report_dir, "--summary-out", str(summary)) == 1
    assert "CI-COV-004" in capsys.readouterr().err
    assert summary.read_text(encoding="utf-8").startswith("CI-COV-004")


@pytest.mark.parametrize(
    ("frontend", "rc", "proposed", "code"),
    [
        (None, 1, None, "CI-COV-004"),
        ("not lcov\n", 1, None, "CI-COV-003"),
        (_lcov(1000, 500), 0, {"packages/protocol": 99.0}, "CI-COV-001"),
    ],
    ids=["refused", "malformed", "other-package-below-floor"],
)
def test_main_ratchet_proposes_only_from_a_complete_valid_download(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    frontend: str | None,
    rc: int,
    proposed: dict[str, float] | None,
    code: str,
) -> None:
    report_dir = tmp_path / "artifacts"
    _write(report_dir / PROTOCOL_REPORT, _lcov(1000, 990))
    ui = report_dir / UI_REPORT
    if frontend is None:
        ui.parent.mkdir(parents=True)
        ui.symlink_to(_write(tmp_path / "outside.info", _lcov(1000, 990)))
    else:
        _write(ui, frontend)
    out = tmp_path / "ratchet.json"
    assert _main(tmp_path, report_dir, "--ratchet", "--ratchet-out", str(out)) == rc
    assert (json.loads(out.read_text()) if out.exists() else None) == proposed
    assert code in capsys.readouterr().err


# --- Each package is judged on its own report (#3562) ------------------------


def test_evaluate_all_judges_packages_sharing_an_artifact_on_their_own_reports(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "coverage-unit-frontend"
    _write(artifact / "lcov.info", _lcov(100, 100))  # names no package, so judges none
    _write(artifact / "packages-ui" / "lcov.info", _lcov(100, 95))
    _write(artifact / "apps-app-web" / "lcov.info", _lcov(100, 70))
    packages = {
        name: PackageConfig(name, 80.0, 80.0, artifact.name, "lcov")
        for name in ("packages/ui", "apps/app-web", "apps/app-electron")
    }
    report = evaluate_all(packages, tmp_path, tolerance_pp=0.5)
    assert [(r.measured, r.code) for r in report.results] == [
        (pytest.approx(95.0), None),
        (pytest.approx(70.0), "CI-COV-001"),
        (None, "CI-COV-003"),
    ]


@pytest.mark.parametrize(
    "names",
    [["a-b/c", "a/b-c"], ["../ui"], ["/ui"], ["a//ui"], ["Ui/x"], [""], ["ui"]],
    ids=["collision", "dot-dot", "absolute", "empty-part", "upper", "empty", "single"],
)
def test_load_config_refuses_a_package_without_a_report_directory_of_its_own(
    tmp_path: Path, names: list[str]
) -> None:
    entry = {"floor": 80.0, "baseline": 80.0, "artifact": "a", "report_format": "lcov"}
    doc = {"tolerance_pp": 0.5, "packages": dict.fromkeys(names, entry)}
    path = tmp_path / "baselines.json"
    path.write_text(json.dumps(doc))
    with pytest.raises(CoverageGateError, match="report directory"):
        load_config(path)


def test_load_config_refuses_an_unknown_report_format(tmp_path: Path) -> None:
    entry = {"floor": 80.0, "baseline": 80.0, "artifact": "a", "report_format": "html"}
    doc = {"tolerance_pp": 0.5, "packages": {"packages/ui": entry}}
    path = tmp_path / "baselines.json"
    path.write_text(json.dumps(doc))
    with pytest.raises(CoverageGateError, match="unknown report_format"):
        load_config(path)


# --- Branch floors: services/api and the chart engine (#3691) ---------------


def _cobertura(line_rate: float, branch_rate: float, branches: int = 100) -> str:
    attrs = f'line-rate="{line_rate}" branch-rate="{branch_rate}"'
    return f'<coverage {attrs} branches-valid="{branches}"></coverage>'


def _lcov_branches(found: int, hit: int) -> str:
    return f"SF:src/x.ts\nLF:100\nLH:96\nBRF:{found}\nBRH:{hit}\nend_of_record\n"


def _judge_branches(tmp_path: Path, report_format: str, text: str) -> PackageResult:
    """Judge a package with a 75% branch floor and a 90% branch baseline on `text`."""
    name = {"lcov": "packages/chart-engine"}.get(report_format, "services/api")
    pkg = PackageConfig(name, 85.0, 85.0, "a", report_format, 75.0, 90.0)
    return evaluate_package(pkg, _write(tmp_path / "report", text), tolerance_pp=0.5)


@pytest.mark.parametrize("report_format", ["coverage-xml", "lcov"])
@pytest.mark.parametrize(
    ("percent", "code", "reason"),
    [
        (60, "CI-COV-001", "{} branches 60.0% < floor 75.0%"),
        (89, "CI-COV-002", "regression 1.0pp beyond 0.5pp tolerance ({} branches"),
        (90, None, None),
    ],
    ids=["below-floor", "below-baseline", "at-baseline"],
)
def test_branches_are_judged_once_lines_pass(
    tmp_path: Path, report_format: str, percent: int, code: str, reason: str | None
) -> None:
    text = _cobertura(0.96, percent / 100)
    if report_format == "lcov":
        text = _lcov_branches(100, percent)
    result = _judge_branches(tmp_path, report_format, text)
    assert (result.code, result.branches) == (code, percent)
    assert result.measured == pytest.approx(96.0)
    assert (result.reason or "").startswith((reason or "").format(result.name))


@pytest.mark.parametrize(
    ("line_rate", "branch_rate", "reason", "cell"),
    [
        (0.8499, 0.96, "services/api 84.99% < floor 85.0%", "| 84.99% |"),
        (0.96, 0.7499, "services/api branches 74.99% < floor 75.0%", "| 74.99% |"),
        (0.96, 0.8946, "regression 0.54pp beyond 0.5pp tolerance", "| 89.5% |"),
    ],
)
def test_a_failing_number_never_prints_equal_to_its_bound(
    tmp_path: Path, line_rate: float, branch_rate: float, reason: str, cell: str
) -> None:
    text = _cobertura(line_rate, branch_rate)
    result = _judge_branches(tmp_path, "coverage-xml", text)
    assert result.verdict == "FAIL"
    assert (result.reason or "").startswith(reason)
    assert cell in render_summary_table(coverage_gate.GateReport([result]))


def test_the_summary_table_prints_a_number_at_its_floor_to_one_decimal(
    tmp_path: Path,
) -> None:
    result = _judge_branches(tmp_path, "coverage-xml", _cobertura(0.85, 0.9))
    table = render_summary_table(coverage_gate.GateReport([result]))
    assert "| 85.0% | +0.0pp | 75.0% | 90.0% | 90.0% | PASS |" in table


# coverage.py writes branch-rate "0" without --cov-branch and "1" when it finds no branch.
@pytest.mark.parametrize(
    ("report_format", "text"),
    [
        ("coverage-xml", '<coverage line-rate="0.96"></coverage>'),
        ("coverage-xml", _cobertura(0.96, 0, branches=0)),
        ("coverage-xml", _cobertura(0.96, 1, branches=0)),
        ("lcov", _lcov(100, 96)),
        ("lcov", _lcov_branches(0, 0)),
    ],
)
def test_a_report_that_records_no_branches_fails_closed(
    tmp_path: Path, report_format: str, text: str
) -> None:
    result = _judge_branches(tmp_path, report_format, text)
    assert (result.verdict, result.code) == ("FAIL", "CI-COV-003")
    assert result.reason == (
        f"{result.name}'s report records no branches, so its 75.0% branch floor "
        "cannot be judged"
    )


def test_only_services_api_and_the_chart_engine_have_a_branch_floor() -> None:
    path = Path(coverage_gate.__file__).with_name("coverage-baselines.json")
    floored = {
        n: p for n, p in load_config(path)[1].items() if p.branch_floor is not None
    }
    assert {n: (p.branch_floor, p.branch_baseline) for n, p in floored.items()} == {
        "services/api": (75.0, 75.0),
        "packages/chart-engine": (75.0, 75.0),
    }


@pytest.mark.parametrize(
    "branch",
    [
        {"branch_floor": 75},
        {"branch_baseline": 75},
        {"branch_floor": "x", "branch_baseline": 1},
    ],
)
def test_load_config_refuses_a_malformed_branch_floor(
    tmp_path: Path, branch: dict[str, object]
) -> None:
    entry = {"floor": 1, "baseline": 1, "artifact": "a", "report_format": "lcov"}
    doc = {"tolerance_pp": 0.5, "packages": {"a/b": {**entry, **branch}}}
    with pytest.raises(CoverageGateError, match="malformed package entry"):
        load_config(_write(tmp_path / "baselines.json", json.dumps(doc)))


def test_parse_coverage_xml_reads_the_branch_rate_of_a_coverage_py_report() -> None:
    # The root of services/api's report on 2026-10-19, less its counts of lines.
    root = 'line-rate="0.9805" branches-valid="14162" branch-rate="0.9549"'
    measured = parse_coverage_xml(f"<coverage {root}></coverage>")
    assert measured == pytest.approx((98.05, 95.49))


@pytest.mark.parametrize(
    "attrs", ['branch-rate="x"', 'branch-rate="1.5"', "", 'branches-valid="-1"']
)
def test_parse_coverage_xml_rejects_a_bad_branch_rate(attrs: str) -> None:
    counted = "" if "branches-valid" in attrs else 'branches-valid="10"'
    with pytest.raises(CoverageGateError, match="branch"):
        parse_coverage_xml(f'<coverage line-rate="0.9" {counted} {attrs}></coverage>')


def test_parse_lcov_sums_branches_over_every_record() -> None:
    measured = parse_lcov(_lcov_branches(10, 9) + _lcov_branches(30, 21))
    assert measured == pytest.approx((96.0, 75.0))


def test_the_summary_table_shows_lines_and_judged_branches(tmp_path: Path) -> None:
    api = PackageConfig("services/api", 85, 85, "py-coverage", "coverage-xml", 75, 75)
    proto = PackageConfig("packages/protocol", 85, 85, "coverage-unit-engine", "lcov")
    _write(tmp_path / API_REPORT, _cobertura(0.96, 0.6))
    _write(tmp_path / PROTOCOL_REPORT, _lcov_branches(100, 60))  # branches not judged
    report = evaluate_all({p.name: p for p in (api, proto)}, tmp_path, 0.5)
    rows = render_summary_table(report).splitlines()
    assert rows[0].endswith("| branch floor | branch baseline | branches | verdict |")
    assert [row.split(" | ")[3:] for row in rows[2:]] == [
        ["96.0%", "+11.0pp", "75.0%", "75.0%", "60.0%", "FAIL (CI-COV-001) |"],
        ["96.0%", "+11.0pp", "n/a", "n/a", "n/a", "PASS |"],
    ]


def test_main_fails_a_package_whose_lines_pass_and_branches_do_not(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    entry = {"floor": 85, "baseline": 85, "branch_floor": 75, "branch_baseline": 75}
    api = {**entry, "artifact": "py-coverage", "report_format": "coverage-xml"}
    doc = {"tolerance_pp": 0.5, "packages": {"services/api": api}}
    baselines = _write(tmp_path / "baselines.json", json.dumps(doc))
    _write(tmp_path / "artifacts" / API_REPORT, _cobertura(0.96, 0.6))
    args = ["--baselines", str(baselines), "--report-dir", str(tmp_path / "artifacts")]
    assert coverage_gate.main(args) == 1
    err = capsys.readouterr().err
    assert "CI-COV-001: services/api branches 60.0% < floor 75.0%" in err
