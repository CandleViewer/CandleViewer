"""Unit tests for tools/ci/security_gate.py (E03-T07).

Exercises the five Gherkin acceptance scenarios plus the underlying
severity-normalisation / accepted-risk-expiry logic, over fixture SARIF/JSON
outputs synthesised in-test (no network, no real scanner invocation).
"""

from __future__ import annotations

import ast
import json
import re
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.security_gate import (
    AcceptedRisk,
    Finding,
    LicenseFinding,
    SecurityGateError,
    evaluate_findings,
    evaluate_licenses,
    load_accepted_risks,
    load_license_allowlist,
    main,
    parse_gitleaks,
    parse_npm_audit,
    parse_pip_audit,
    parse_sarif,
)


def _write_yaml(tmp_path: Path, data: object) -> Path:
    p = tmp_path / "accepted-risks.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def _write_json(tmp_path: Path, name: str, data: object) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# --------------------------------------------------------------------------
# Scenario: A planted synthetic secret blocks the merge
# --------------------------------------------------------------------------


def test_gitleaks_finding_always_blocks_even_with_no_accepted_risks(
    tmp_path: Path,
) -> None:
    risks_path = _write_yaml(tmp_path, {"entries": []})
    risks = load_accepted_risks(risks_path)
    findings = [
        Finding(
            tool="gitleaks",
            finding_id="aws-key:app.py:10",
            severity="CRITICAL",
            detail="x",
        )
    ]
    result = evaluate_findings(findings, risks, run_date=date(2026, 1, 1))
    assert result.blocked
    assert result.code == "CI-SEC-001"


def test_gitleaks_finding_cannot_be_accepted_even_if_entry_present(
    tmp_path: Path,
) -> None:
    # load_accepted_risks rejects a gitleaks entry outright (CI-SEC-005) —
    # the register itself refuses to hold one.
    risks_path = _write_yaml(
        tmp_path,
        {
            "entries": [
                {
                    "id": "aws-key:app.py:10",
                    "tool": "gitleaks",
                    "severity": "CRITICAL",
                    "reason": "test",
                    "approver": "sec",
                    "expires": "2099-01-01",
                }
            ]
        },
    )
    with pytest.raises(SecurityGateError) as exc_info:
        load_accepted_risks(risks_path)
    assert exc_info.value.code == "CI-SEC-005"


def test_parse_gitleaks_report_never_reprints_secret_value(tmp_path: Path) -> None:
    report = _write_json(
        tmp_path,
        "gitleaks.json",
        [
            {
                "RuleID": "generic-api-key",
                "File": "app.py",
                "StartLine": 5,
                "Secret": "REDACTED",
            }
        ],
    )
    findings = parse_gitleaks(report)
    assert len(findings) == 1
    assert findings[0].severity == "CRITICAL"
    assert "REDACTED" not in findings[0].detail
    assert "generic-api-key" in findings[0].finding_id


# --------------------------------------------------------------------------
# Scenario: A prohibited licence fails the build
# --------------------------------------------------------------------------


def test_prohibited_license_fails_naming_package_license_and_sr136(
    tmp_path: Path,
) -> None:
    allowlist_path = tmp_path / "allowlist.json"
    allowlist_path.write_text(
        json.dumps(
            {
                "allowed": ["MIT"],
                "needs_approval": {"licenses": ["LGPL-3.0-only"]},
                "prohibited": {"licenses": ["AGPL-3.0-only"]},
                "dev_only_exceptions": {"packages": []},
                "unknown_license_policy": "fail",
            }
        ),
        encoding="utf-8",
    )
    allowlist = load_license_allowlist(allowlist_path)
    deps = [LicenseFinding(package="evil-dep", version="1.0.0", license="AGPL-3.0-only")]
    result = evaluate_licenses(deps, allowlist, risks=[], run_date=date(2026, 1, 1))
    assert result.blocked
    assert result.code == "CI-SEC-002"
    assert any("evil-dep" in m and "AGPL-3.0-only" in m and "SR-136" in m for m in result.messages)


def test_unknown_license_fails_closed(tmp_path: Path) -> None:
    allowlist = {
        "allowed": ["MIT"],
        "needs_approval": {"licenses": []},
        "prohibited": {"licenses": []},
        "dev_only_exceptions": {"packages": []},
        "unknown_license_policy": "fail",
    }
    deps = [LicenseFinding(package="mystery-dep", version="2.0.0", license="Some-Weird-License")]
    result = evaluate_licenses(deps, allowlist, risks=[], run_date=date(2026, 1, 1))
    assert result.blocked
    assert result.code == "CI-SEC-002"


def test_lgpl_needs_approval_blocks_without_accepted_risk() -> None:
    allowlist = {
        "allowed": [],
        "needs_approval": {"licenses": ["LGPL-3.0-only"]},
        "prohibited": {"licenses": []},
        "dev_only_exceptions": {"packages": []},
        "unknown_license_policy": "fail",
    }
    deps = [LicenseFinding(package="lgpl-dep", version="1.0.0", license="LGPL-3.0-only")]
    result = evaluate_licenses(deps, allowlist, risks=[], run_date=date(2026, 1, 1))
    assert result.blocked
    assert result.code == "CI-SEC-003"


def test_lgpl_needs_approval_passes_with_unexpired_accepted_risk() -> None:
    allowlist = {
        "allowed": [],
        "needs_approval": {"licenses": ["LGPL-3.0-only"]},
        "prohibited": {"licenses": []},
        "dev_only_exceptions": {"packages": []},
        "unknown_license_policy": "fail",
    }
    deps = [LicenseFinding(package="lgpl-dep", version="1.0.0", license="LGPL-3.0-only")]
    risks = [
        AcceptedRisk(
            finding_id="license:lgpl-dep@1.0.0",
            tool="license-scan",
            severity="MEDIUM",
            reason="owner approved LGPL for this tool",
            approver="basiltt",
            expires=date(2099, 1, 1),
        )
    ]
    result = evaluate_licenses(deps, allowlist, risks=risks, run_date=date(2026, 1, 1))
    assert not result.blocked


# --------------------------------------------------------------------------
# Scenario: A High-severity dependency advisory blocks
# --------------------------------------------------------------------------


def test_pip_audit_high_severity_with_no_accepted_risk_blocks(tmp_path: Path) -> None:
    report = _write_json(
        tmp_path,
        "pip-audit.json",
        {
            "dependencies": [
                {
                    "name": "vulnerable-pkg",
                    "version": "1.2.3",
                    "vulns": [
                        {
                            "id": "GHSA-xxxx",
                            "severity": "HIGH",
                            "description": "remote code execution",
                        }
                    ],
                }
            ]
        },
    )
    findings = parse_pip_audit(report)
    result = evaluate_findings(findings, risks=[], run_date=date(2026, 1, 1))
    assert result.blocked
    assert result.code == "CI-SEC-001"


def test_pip_audit_unscored_advisory_treated_as_high_fail_closed(
    tmp_path: Path,
) -> None:
    report = _write_json(
        tmp_path,
        "pip-audit.json",
        {"dependencies": [{"name": "p", "version": "1", "vulns": [{"id": "GHSA-yyyy"}]}]},
    )
    findings = parse_pip_audit(report)
    assert findings[0].severity == "HIGH"


def test_low_severity_finding_does_not_block(tmp_path: Path) -> None:
    report = _write_json(
        tmp_path,
        "pip-audit.json",
        {
            "dependencies": [
                {"name": "p", "version": "1", "vulns": [{"id": "X", "severity": "LOW"}]}
            ]
        },
    )
    findings = parse_pip_audit(report)
    result = evaluate_findings(findings, risks=[], run_date=date(2026, 1, 1))
    assert not result.blocked


# --------------------------------------------------------------------------
# Scenario: An expired accepted risk re-blocks
# --------------------------------------------------------------------------


def test_expired_accepted_risk_reblocks_on_run_date(tmp_path: Path) -> None:
    risks_path = _write_yaml(
        tmp_path,
        {
            "entries": [
                {
                    "id": "GHSA-xxxx",
                    "tool": "pip-audit",
                    "severity": "HIGH",
                    "reason": "temporary — fix in progress",
                    "approver": "basiltt",
                    "expires": "2026-09-27",
                }
            ]
        },
    )
    risks = load_accepted_risks(risks_path)
    findings = [Finding(tool="pip-audit", finding_id="GHSA-xxxx", severity="HIGH", detail="x")]

    # On the expiry date itself the entry no longer protects (exclusive expiry).
    result = evaluate_findings(findings, risks, run_date=date(2026, 9, 27))
    assert result.blocked
    assert result.code == "CI-SEC-004"
    assert any("accepted risk expired" in m for m in result.messages)

    # The day before, it still protects.
    result_before = evaluate_findings(findings, risks, run_date=date(2026, 9, 26))
    assert not result_before.blocked


def test_unexpired_accepted_risk_does_not_block() -> None:
    risks = [
        AcceptedRisk(
            finding_id="GHSA-aaaa",
            tool="pip-audit",
            severity="HIGH",
            reason="vendor patch pending",
            approver="basiltt",
            expires=date(2099, 1, 1),
        )
    ]
    findings = [Finding(tool="pip-audit", finding_id="GHSA-aaaa", severity="HIGH", detail="x")]
    result = evaluate_findings(findings, risks, run_date=date(2026, 1, 1))
    assert not result.blocked


def test_accepted_risks_register_rejects_critical_severity_entry(
    tmp_path: Path,
) -> None:
    risks_path = _write_yaml(
        tmp_path,
        {
            "entries": [
                {
                    "id": "GHSA-crit",
                    "tool": "pip-audit",
                    "severity": "CRITICAL",
                    "reason": "test",
                    "approver": "basiltt",
                    "expires": "2099-01-01",
                }
            ]
        },
    )
    with pytest.raises(SecurityGateError) as exc_info:
        load_accepted_risks(risks_path)
    assert exc_info.value.code == "CI-SEC-005"


# --------------------------------------------------------------------------
# Scenario: A Semgrep custom rule catches an unpinned action
# --------------------------------------------------------------------------


def _sarif_doc(rule_id: str, level: str = "error", severity: float | None = None) -> dict:
    props = {"security-severity": str(severity)} if severity is not None else {}
    return {
        "version": "2.1.0",
        "runs": [
            {
                "tool": {"driver": {"name": "semgrep"}},
                "results": [
                    {
                        "ruleId": rule_id,
                        "level": level,
                        "message": {"text": f"{rule_id} violated"},
                        "properties": props,
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {"uri": ".github/workflows/pr.yml"},
                                    "region": {"startLine": 12},
                                }
                            }
                        ],
                    }
                ],
            }
        ],
    }


def test_semgrep_cv_unpinned_action_rule_blocks_referencing_sr132(
    tmp_path: Path,
) -> None:
    report = _write_json(tmp_path, "semgrep.sarif", _sarif_doc("cv-unpinned-action"))
    findings = parse_sarif(report, "semgrep")
    assert findings[0].severity == "HIGH"
    result = evaluate_findings(findings, risks=[], run_date=date(2026, 1, 1))
    assert result.blocked
    assert any("cv-unpinned-action" in m for m in result.messages)


def test_sarif_security_severity_maps_to_critical_bucket(tmp_path: Path) -> None:
    report = _write_json(tmp_path, "codeql.sarif", _sarif_doc("py/sql-injection", severity=9.5))
    findings = parse_sarif(report, "codeql")
    assert findings[0].severity == "CRITICAL"


def test_sarif_warning_level_maps_to_medium_and_does_not_block(tmp_path: Path) -> None:
    report = _write_json(
        tmp_path, "semgrep.sarif", _sarif_doc("some-warning-rule", level="warning")
    )
    findings = parse_sarif(report, "semgrep")
    assert findings[0].severity == "MEDIUM"
    result = evaluate_findings(findings, risks=[], run_date=date(2026, 1, 1))
    assert not result.blocked


# --------------------------------------------------------------------------
# Regression (ci/e03-codeql-job-fix): CodeQL puts `security-severity` and the
# default `level` on the rule descriptor, not the result. Reading the result
# alone downgraded every CodeQL High to MEDIUM, so PRs #1715/#1691 passed
# `security / codeql` while GitHub's CodeQL check reported a High alert.
# --------------------------------------------------------------------------


def _codeql_sarif_doc(
    rule_id: str,
    *,
    security_severity: str | None,
    rule_level: str = "error",
    result_level: str | None = None,
    via_extension: bool = False,
    use_rule_ref: bool = False,
) -> dict:
    rule = {
        "id": rule_id,
        "defaultConfiguration": {"level": rule_level},
        "properties": {"security-severity": security_severity}
        if security_severity is not None
        else {},
    }
    result: dict = {
        "ruleId": rule_id,
        "message": {"text": "This expression logs sensitive data as clear text."},
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": "infra/scripts/obs_security_checks.py"},
                    "region": {"startLine": 94},
                }
            }
        ],
    }
    if result_level is not None:
        result["level"] = result_level
    tool: dict = {"driver": {"name": "CodeQL", "rules": [] if via_extension else [rule]}}
    if via_extension:
        tool["extensions"] = [{"name": "codeql/python-queries", "rules": [rule]}]
        if use_rule_ref:
            result["rule"] = {"id": rule_id, "toolComponent": {"index": 1}, "index": 0}
    elif use_rule_ref:
        result["rule"] = {"id": rule_id, "index": 0}
    return {"version": "2.1.0", "runs": [{"tool": tool, "results": [result]}]}


def test_codeql_rule_level_security_severity_high_blocks(tmp_path: Path) -> None:
    report = _write_json(
        tmp_path,
        "codeql.sarif",
        _codeql_sarif_doc("py/clear-text-logging-sensitive-data", security_severity="7.5"),
    )
    findings = parse_sarif(report, "codeql")
    assert findings[0].severity == "HIGH"
    assert (
        findings[0].finding_id
        == "py/clear-text-logging-sensitive-data:infra/scripts/obs_security_checks.py:94"
    )
    result = evaluate_findings(findings, risks=[], run_date=date(2026, 10, 3))
    assert result.blocked
    assert result.code == "CI-SEC-001"


def test_codeql_rule_in_extension_pack_resolved_by_rule_reference(
    tmp_path: Path,
) -> None:
    report = _write_json(
        tmp_path,
        "codeql.sarif",
        _codeql_sarif_doc(
            "js/tainted-format-string",
            security_severity="7.3",
            via_extension=True,
            use_rule_ref=True,
        ),
    )
    findings = parse_sarif(report, "codeql")
    assert findings[0].severity == "HIGH"


def test_codeql_result_without_level_falls_back_to_rule_default_level(
    tmp_path: Path,
) -> None:
    report = _write_json(
        tmp_path,
        "codeql.sarif",
        _codeql_sarif_doc("py/some-non-security-rule", security_severity=None, rule_level="error"),
    )
    findings = parse_sarif(report, "codeql")
    assert findings[0].severity == "HIGH"


def test_sarif_result_level_security_severity_still_takes_precedence(
    tmp_path: Path,
) -> None:
    doc = _codeql_sarif_doc("py/x", security_severity="9.5", result_level="warning")
    doc["runs"][0]["results"][0]["properties"] = {"security-severity": "3.0"}
    report = _write_json(tmp_path, "codeql.sarif", doc)
    findings = parse_sarif(report, "codeql")
    assert findings[0].severity == "LOW"


def test_codeql_high_with_matching_accepted_risk_does_not_block(tmp_path: Path) -> None:
    report = _write_json(
        tmp_path,
        "codeql.sarif",
        _codeql_sarif_doc("py/clear-text-logging-sensitive-data", security_severity="7.5"),
    )
    findings = parse_sarif(report, "codeql")
    risk = AcceptedRisk(
        finding_id=findings[0].finding_id,
        tool="codeql",
        severity="HIGH",
        reason="test",
        approver="basiltt",
        expires=date(2027, 1, 1),
    )
    result = evaluate_findings(findings, risks=[risk], run_date=date(2026, 10, 3))
    assert not result.blocked


# --------------------------------------------------------------------------
# Scanner infrastructure failure (CI-SEC-005) never passes as clean
# --------------------------------------------------------------------------


def test_malformed_sarif_raises_ci_sec_005_not_treated_as_clean(tmp_path: Path) -> None:
    bad = tmp_path / "broken.sarif"
    bad.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(SecurityGateError) as exc_info:
        parse_sarif(bad, "codeql")
    assert exc_info.value.code == "CI-SEC-005"


# #3337: a SARIF with no run, or a run without a named tool.driver, records no scan. Every tool
# that reaches parse_sarif writes one run per scan, clean or not (fixtures/sarif/README.md).
SARIF_TOOLS = ("codeql", "semgrep", "bandit", "trivy")
_RUN = {"tool": {"driver": {"name": "CodeQL"}}, "results": []}
_UNSCORED = {"ruleId": "x", "message": {"text": "x"}}  # no level and no rule descriptor


@pytest.mark.parametrize("tool", SARIF_TOOLS)
@pytest.mark.parametrize(
    ("runs", "reason"),
    [
        pytest.param([], "has no runs", id="no-runs"),
        pytest.param(None, "'runs' is not a list", id="runs-null"),
        pytest.param(_RUN, "'runs' is not a list", id="runs-object"),
        pytest.param(["x"], "run 0 is not an object", id="run-not-object"),
        # Was a MEDIUM finding, which the codeql policy does not block.
        pytest.param([{"results": [_UNSCORED]}], "run 0 has no tool.driver", id="unscored-no-tool"),
        pytest.param([{"tool": {"name": "x"}}], "run 0 has no tool.driver", id="tool-no-driver"),
        pytest.param([{"tool": {"driver": "x"}}], "run 0 has no tool.driver", id="driver-str"),
        pytest.param([{"tool": {"driver": {}}}], "run 0 has no tool.driver", id="driver-no-name"),
        # #3372: the name branch, for an empty, a non-string and a whitespace-only name.
        pytest.param(
            [{"tool": {"driver": {"name": ""}}}], "run 0 has no tool.driver", id="name-empty"
        ),
        pytest.param(
            [{"tool": {"driver": {"name": 5}}}], "run 0 has no tool.driver", id="name-int"
        ),
        pytest.param(
            [{"tool": {"driver": {"name": " \t"}}}], "run 0 has no tool.driver", id="name-blank"
        ),
        pytest.param([_RUN, {"results": []}], "run 1 has no tool.driver", id="second-run"),
    ],
)
def test_sarif_without_a_tool_run_raises_ci_sec_005(
    tmp_path: Path, tool: str, runs: object, reason: str
) -> None:
    report = _write_json(tmp_path, f"{tool}.sarif", {"version": "2.1.0", "runs": runs})
    with pytest.raises(SecurityGateError) as exc_info:
        parse_sarif(report, tool)
    assert exc_info.value.code == "CI-SEC-005"
    message = exc_info.value.message
    assert message.startswith(f"{tool}: {report} ") and reason in message


@pytest.mark.parametrize("tool", SARIF_TOOLS)
def test_sarif_without_runs_key_still_raises_ci_sec_005(tmp_path: Path, tool: str) -> None:
    report = _write_json(tmp_path, f"{tool}.sarif", {"version": "2.1.0"})
    with pytest.raises(SecurityGateError) as exc_info:
        parse_sarif(report, tool)
    assert exc_info.value.code == "CI-SEC-005"
    assert exc_info.value.message == f"{tool}: {report} is not a SARIF document (no 'runs')"


def test_main_cli_fails_a_sarif_with_no_runs_instead_of_ok(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    risks = _write_yaml(tmp_path, {"entries": []})
    report = _write_json(tmp_path, "python.sarif", {"version": "2.1.0", "runs": []})
    rc = main(["--tool", "codeql", "--report", str(report), "--accepted-risks", str(risks)])
    out, err = capsys.readouterr()
    assert (rc, out) == (1, "")
    assert err.startswith(f"CI-SEC-005: codeql: {report} has no runs")


# #3372: a run must also record a completed scan. SARIF 2.1.0 §3.14.23: `results` absent or null
# means the analysis was not performed; `[]` means it found nothing.
_NAMED = {"tool": {"driver": {"name": "Bandit"}}}
_DONE = {"executionSuccessful": True}
# How Bandit records a file it could not scan, while it still reports executionSuccessful: true.
_UNSCANNED = {"message": {"text": "syntax error while parsing AST from file"}, "level": "error"}


@pytest.mark.parametrize("tool", SARIF_TOOLS)
@pytest.mark.parametrize(
    ("run", "reason"),
    [
        pytest.param(_NAMED, "has no 'results' list (absent or null", id="results-absent"),
        pytest.param({**_NAMED, "results": None}, "has no 'results' list", id="results-null"),
        pytest.param({**_NAMED, "results": {}}, "'results' is not a list", id="results-object"),
        pytest.param({**_NAMED, "results": 5}, "'results' is not a list", id="results-int"),
        pytest.param({**_NAMED, "results": "abc"}, "'results' is not a list", id="results-str"),
        pytest.param({**_NAMED, "results": [1]}, "result 0 is not an object", id="result-int"),
        pytest.param({**_NAMED, "results": [[]]}, "result 0 is not an object", id="result-list"),
    ],
)
def test_sarif_run_without_a_results_list_raises_ci_sec_005(
    tmp_path: Path, tool: str, run: dict[str, object], reason: str
) -> None:
    report = _write_json(tmp_path, f"{tool}.sarif", {"version": "2.1.0", "runs": [_RUN, run]})
    with pytest.raises(SecurityGateError) as exc_info:
        parse_sarif(report, tool)
    assert exc_info.value.code == "CI-SEC-005"
    assert exc_info.value.message.startswith(f"{tool}: {report} run 1 {reason}")


@pytest.mark.parametrize("tool", SARIF_TOOLS)
@pytest.mark.parametrize(
    ("invocations", "reason"),
    [
        pytest.param(
            [{"executionSuccessful": False}],
            "invocation 0 does not report executionSuccessful: true",
            id="not-successful",
        ),
        pytest.param([{}], "invocation 0 does not report executionSuccessful: true", id="unset"),
        pytest.param(
            [_DONE, {"executionSuccessful": "true"}],
            "invocation 1 does not report executionSuccessful: true",
            id="second-not-bool",
        ),
        pytest.param(
            [{**_DONE, "toolConfigurationNotifications": [{"level": "warning"}, _UNSCANNED]}],
            "invocation 0 reports 1 configuration error(s), first: " + json.dumps(_UNSCANNED),
            id="configuration-error",
        ),
        pytest.param({}, "'invocations' is not a list", id="invocations-object"),
        pytest.param([1], "invocation 0 is not an object", id="invocation-int"),
        pytest.param(
            [{**_DONE, "toolConfigurationNotifications": [1]}],
            "invocation 0 'toolConfigurationNotifications' is not a list of objects",
            id="notification-int",
        ),
    ],
)
def test_sarif_run_that_did_not_complete_raises_ci_sec_005(
    tmp_path: Path, tool: str, invocations: object, reason: str
) -> None:
    run = {**_NAMED, "invocations": invocations, "results": []}
    report = _write_json(tmp_path, f"{tool}.sarif", {"version": "2.1.0", "runs": [run]})
    with pytest.raises(SecurityGateError) as exc_info:
        parse_sarif(report, tool)
    assert exc_info.value.code == "CI-SEC-005"
    assert exc_info.value.message == f"{tool}: {report} run 0 records no completed scan: {reason}"


@pytest.mark.parametrize("tool", SARIF_TOOLS)
def test_sarif_run_that_completed_with_warnings_is_a_clean_scan(tmp_path: Path, tool: str) -> None:
    # A warning (SARIF's default level) leaves the scan complete, and so does an execution
    # notification: CodeQL reports per-file extraction diagnostics there, at any level.
    invocation = {
        **_DONE,
        "toolConfigurationNotifications": [{"level": "warning"}, {"message": {"text": "x"}}],
        "toolExecutionNotifications": [{"level": "error", "message": {"text": "x"}}],
    }
    run = {**_NAMED, "invocations": [invocation], "results": []}
    report = _write_json(tmp_path, f"{tool}.sarif", {"version": "2.1.0", "runs": [run]})
    assert parse_sarif(report, tool) == []


# #3372: CodeQL describes every rule it reports, on the driver or a tool.extensions pack, so a
# result with no level and no descriptor to score it by is malformed, not an unscored MEDIUM.
_UNDESCRIBED = [
    pytest.param({"ruleId": "py/undescribed"}, id="rule-id"),
    pytest.param({"rule": {"id": "py/x", "index": 1, "toolComponent": {"index": 1}}}, id="index"),
    pytest.param({"rule": {"id": "py/x", "index": 0, "toolComponent": {"index": 2}}}, id="pack"),
]


@pytest.mark.parametrize("level", [None, "bogus"])  # "bogus" is no SARIF level, so scores nothing
@pytest.mark.parametrize("ref", _UNDESCRIBED)
def test_codeql_result_without_a_level_or_rule_descriptor_raises_ci_sec_005(
    tmp_path: Path, ref: dict[str, object], level: str | None
) -> None:
    doc = _codeql_sarif_doc("py/described", security_severity="7.5", via_extension=True)
    result = {"message": {"text": "x"}, **ref} | ({"level": level} if level else {})
    doc["runs"][0]["results"].append(result)
    report = _write_json(tmp_path, "codeql.sarif", doc)
    with pytest.raises(SecurityGateError) as exc_info:
        parse_sarif(report, "codeql")
    assert exc_info.value.code == "CI-SEC-005"
    message = exc_info.value.message
    tail = "has no level and no rule descriptor on tool.driver or tool.extensions"
    assert message.startswith(f"codeql: {report} run 0 result 1 (") and tail in message


def test_codeql_result_without_a_rule_descriptor_is_scored_by_its_own_level(
    tmp_path: Path,
) -> None:
    # The boundary #3372 draws: a level on the result still scores it, as for every tool.
    doc = _codeql_sarif_doc("py/described", security_severity="7.5", via_extension=True)
    doc["runs"][0]["results"].append({"ruleId": "py/x", "message": {"text": "x"}, "level": "note"})
    findings = parse_sarif(_write_json(tmp_path, "codeql.sarif", doc), "codeql")
    assert [f.severity for f in findings] == ["HIGH", "LOW"]


def test_parse_sarif_docstring_names_every_tool_it_parses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # #3372: every SARIF tool reaches parse_sarif (its no-runs message), bandit included.
    risks = _write_yaml(tmp_path, {"entries": []})
    report = _write_json(tmp_path, "x.sarif", {"version": "2.1.0", "runs": []})
    for tool in SARIF_TOOLS:
        assert main(["--tool", tool, "--report", str(report), "--accepted-risks", str(risks)]) == 1
        assert capsys.readouterr().err.startswith(f"CI-SEC-005: {tool}: {report} has no runs")
    used_for = (parse_sarif.__doc__ or "").split("\n\n")[1].strip()
    assert used_for.startswith("Used for CodeQL, Semgrep, Bandit and Trivy (")


SARIF_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sarif"


@pytest.mark.parametrize(
    ("name", "tool", "found"),
    [
        ("codeql-2.27.2-clean.sarif", "codeql", []),
        ("codeql-2.27.2-analyze-clean.sarif", "codeql", []),
        ("semgrep-1.178.0-clean.sarif", "semgrep", []),
        (
            "semgrep-1.178.0-finding.sarif",
            "semgrep",
            [("semgrep.cv-obs-no-print:.semgrep/tests/cv-obs-no-print.py:5", "HIGH")],
        ),
        ("bandit-1.9.4-clean.sarif", "bandit", []),
        ("bandit-1.9.4-finding.sarif", "bandit", [("B307:finding/parse_expr.py:2", "MEDIUM")]),
        ("trivy-0.70.0-clean.sarif", "trivy", []),
    ],
)
def test_real_scanner_sarif_still_parses(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    name: str,
    tool: str,
    found: list[tuple[str, str]],
) -> None:
    report = SARIF_FIXTURES / name
    assert [(f.finding_id, f.severity) for f in parse_sarif(report, tool)] == found
    risks = _write_yaml(tmp_path, {"entries": []})
    args = ["--tool", tool, "--report", str(report), "--accepted-risks", str(risks)]
    if tool == "semgrep":  # #3549: and the JSON report of a scan that parsed every file
        args += ["--semgrep-json", str(_semgrep_report(tmp_path, "semgrep-1.181.0.json", []))]
    rc = main(args)
    blocked = bool(found)  # each real finding meets its tool's threshold
    assert rc == int(blocked)
    assert (f"security_gate[{tool}]: OK" in capsys.readouterr().out) is not blocked


def test_real_bandit_sarif_with_a_file_it_could_not_scan_raises_ci_sec_005(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # #3372: Bandit exits 0 and reports executionSuccessful: true when it skips a file.
    report = SARIF_FIXTURES / "bandit-1.9.4-skipped.sarif"
    risks = _write_yaml(tmp_path, {"entries": []})
    rc = main(["--tool", "bandit", "--report", str(report), "--accepted-risks", str(risks)])
    out, err = capsys.readouterr()
    assert (rc, out) == (1, "")
    head = f"CI-SEC-005: bandit: {report} run 0 records no completed scan: invocation 0 reports 1 "
    assert err.startswith(head + "configuration error(s)") and "skipped/broken.py" in err


# --------------------------------------------------------------------------
# #3549: a target a Semgrep rule did not analyse fails its scan (fixtures/semgrep/README.md)
# --------------------------------------------------------------------------

SEMGREP_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "semgrep"
LOST = "target(s) a rule did not analyse, so their clean result means nothing: "
GAPS = "semgrep-1.181.0-rule-gaps.json"  # timeouts, too many matches, a YAML snippet
SKIPS = "semgrep-1.181.0-skips.json"  # a size limit, an exclude, a rule it cannot run
FAILED = "analysis_failed_parser_or_internal_error"  # a skip reason: the error says why
OK = "security_gate[semgrep]: OK"


def _semgrep_report(tmp_path: Path, name: str, keep: list[str] | None = None) -> Path:
    """Recorded report `name`, or a copy keeping only its errors on the files in `keep`."""
    if keep is None:
        return SEMGREP_FIXTURES / name
    return _semgrep_report_with(
        tmp_path, name, [error for error in _semgrep_errors(name) if error["path"] in keep]
    )


def _semgrep_errors(name: str) -> list[dict[str, Any]]:
    doc = json.loads((SEMGREP_FIXTURES / name).read_text(encoding="utf-8"))
    errors: list[dict[str, Any]] = doc["errors"]
    return errors


def _semgrep_report_with(
    tmp_path: Path,
    name: str,
    errors: list[dict[str, Any]],
    skipped: list[dict[str, Any]] | None = None,
) -> Path:
    """Recorded report `name` with `errors` in place of its own.

    As Semgrep writes it, `paths.skipped` keeps a target whose analysis failed only while an
    error names it; `skipped` replaces the whole list instead.
    """
    doc = json.loads((SEMGREP_FIXTURES / name).read_text(encoding="utf-8"))
    doc["errors"] = errors
    if skipped is None:
        named = {error.get("path") for error in errors}
        skipped = [
            entry
            for entry in doc["paths"]["skipped"]
            if entry["reason"] != FAILED or entry["path"] in named
        ]
    doc["paths"]["skipped"] = skipped
    return _write_json(tmp_path, f"edited-{name}", doc)


def _semgrep_gate(
    tmp_path: Path,
    report: Path | None,
    capsys: pytest.CaptureFixture[str],
    sarif: Path = SARIF_FIXTURES / "semgrep-1.178.0-clean.sarif",
) -> tuple[int, str, str]:
    """Gate a Semgrep SARIF, clean by default, with `report` as the scan's JSON report."""
    risks = _write_yaml(tmp_path, {"entries": []})
    args = ["--tool", "semgrep", "--report", str(sarif), "--accepted-risks", str(risks)]
    rc = main(args + (["--semgrep-json", str(report)] if report else []))
    out, err = capsys.readouterr()
    return rc, out, err


def test_semgrep_1_99_partial_parses_raise_ci_sec_005(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # CI's old pin skipped all of skipped.py (PEP 695) and drill.sh, and parts of the other
    # two, while its SARIF read as a clean, complete scan. Any part it skips can hide a match.
    report = _semgrep_report(tmp_path, "semgrep-1.99.0.json")
    rc, out, err = _semgrep_gate(tmp_path, report, capsys)
    assert (rc, out) == (1, "")
    lost = (
        "skipped.py (PartialParsing, line(s) 1-12); unparsed.py (PartialParsing, line(s) 11); "
        "partial.py (PartialParsing, line(s) 3); drill.sh (PartialParsing, line(s) 3-5)"
    )
    assert err == f"CI-SEC-005: semgrep: {report} shows 4 {LOST}{lost}\n"


def test_semgrep_1_181_file_no_parser_reads_raises_ci_sec_005(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The pinned version reads PEP 695, but no part of unparsed.py: a `Syntax error`, no span.
    report = _semgrep_report(tmp_path, "semgrep-1.181.0.json")
    rc, out, err = _semgrep_gate(tmp_path, report, capsys)
    assert (rc, out) == (1, "")
    lost = "unparsed.py (Syntax error); drill.sh (PartialParsing, line(s) 3-5)"
    assert err == f"CI-SEC-005: semgrep: {report} shows 2 {LOST}{lost}\n"


def test_semgrep_files_parsed_in_part_raise_ci_sec_005(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Semgrep 1.99.0 found partial.py's print on line 10 but not what line 3 might hold. The
    # report alone decides: the gate reads no source, so it runs anywhere.
    monkeypatch.chdir(tmp_path)  # the fixture sources are not here
    report = _semgrep_report(tmp_path, "semgrep-1.99.0.json", ["partial.py", "unparsed.py"])
    rc, out, err = _semgrep_gate(tmp_path, report, capsys)
    assert (rc, out) == (1, "")
    lost = "unparsed.py (PartialParsing, line(s) 11); partial.py (PartialParsing, line(s) 3)"
    assert err == f"CI-SEC-005: semgrep: {report} shows 2 {LOST}{lost}\n"


def test_semgrep_report_of_a_scan_that_parsed_every_file_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = _semgrep_report(tmp_path, "semgrep-1.181.0.json", [])
    assert _semgrep_gate(tmp_path, report, capsys) == (0, OK + "\n", "")


def test_semgrep_rule_gaps_report_raises_ci_sec_005(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # As recorded: no finding at all, though python-print matches many.py:28 and slow.py:68.
    report = _semgrep_report(tmp_path, GAPS)
    rc, out, err = _semgrep_gate(tmp_path, report, capsys)
    assert (rc, out) == (1, "")
    lost = (
        "many.py (Too many matches in slow-sequence-a); "
        "slow.py (3 rule timeouts, so Semgrep skipped the rules left)"
    )
    assert err == f"CI-SEC-005: semgrep: {report} shows 2 {LOST}{lost}\n"


def test_semgrep_too_many_matches_raises_ci_sec_005(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Semgrep names one rule, but drops every rule's findings on the file.
    report = _semgrep_report(tmp_path, GAPS, ["many.py"])
    rc, out, err = _semgrep_gate(tmp_path, report, capsys)
    assert (rc, out) == (1, "")
    lost = "many.py (Too many matches in slow-sequence-a)"
    assert err == f"CI-SEC-005: semgrep: {report} shows 1 {LOST}{lost}\n"


@pytest.mark.parametrize("count", [1, 2])
def test_semgrep_rule_timeouts_below_the_threshold_are_warnings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], count: int
) -> None:
    # Each timed-out rule missed the file; the others analysed it.
    timeouts = [e for e in _semgrep_errors(GAPS) if e["type"] == "Timeout"][:count]
    report = _semgrep_report_with(tmp_path, GAPS, timeouts)
    rc, out, err = _semgrep_gate(tmp_path, report, capsys)
    assert (rc, err) == (0, "")
    rules = ", ".join(f"slow-sequence-{c}" for c in "ab"[:count])
    note = f"{rules} timed out on slow.py; the other rules analysed it, not failing"
    assert out.splitlines() == [f"::warning file=slow.py::semgrep: {note}", OK]


@pytest.mark.parametrize("rule", ["cv-slow-sequence", "semgrep.cv-slow-sequence"])
def test_semgrep_cv_rule_timeout_raises_ci_sec_005(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], rule: str
) -> None:
    # A cv-* rule (CI names `.semgrep/cv-*.yml` rules `semgrep.cv-*`) guards an invariant.
    timeout, *_ = [e for e in _semgrep_errors(GAPS) if e["type"] == "Timeout"]
    report = _semgrep_report_with(tmp_path, GAPS, [{**timeout, "rule_id": rule}])
    rc, out, err = _semgrep_gate(tmp_path, report, capsys)
    assert (rc, out) == (1, "")
    assert err == f"CI-SEC-005: semgrep: {report} shows 1 {LOST}slow.py (Timeout in {rule})\n"


@pytest.mark.parametrize(
    ("drop", "lost"),
    [("rule_id", "slow.py (Timeout)"), ("path", "an unnamed target (Timeout in slow-sequence-a)")],
)
def test_semgrep_timeout_it_cannot_place_raises_ci_sec_005(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], drop: str, lost: str
) -> None:
    timeout, *_ = [e for e in _semgrep_errors(GAPS) if e["type"] == "Timeout"]
    report = _semgrep_report_with(tmp_path, GAPS, [{k: v for k, v in timeout.items() if k != drop}])
    rc, out, err = _semgrep_gate(tmp_path, report, capsys)
    assert (rc, out) == (1, "")
    assert err == f"CI-SEC-005: semgrep: {report} shows 1 {LOST}{lost}\n"


def test_semgrep_yaml_snippet_a_rule_could_not_parse_is_a_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The YAML parsed; only workflow-run-echo missed the run: script it reads as Bash.
    report = _semgrep_report(tmp_path, GAPS, ["workflow.yml"])
    rc, out, err = _semgrep_gate(tmp_path, report, capsys)
    assert (rc, err) == (0, "")
    note = "workflow-run-echo could not parse the snippet on line(s) 7-9; the rest was analysed"
    assert out.splitlines() == [
        f"::warning file=workflow.yml,line=7::semgrep: workflow.yml: {note}, not failing",
        OK,
    ]


@pytest.mark.parametrize(
    ("rule", "target"),
    [
        ("semgrep.cv-workflow-run-echo", "workflow.yml"),  # a cv-* rule's snippet
        ("workflow-run-echo", "deploy.py"),  # a snippet in a file that is not YAML
    ],
)
def test_semgrep_snippet_gap_of_a_cv_rule_or_outside_yaml_raises_ci_sec_005(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], rule: str, target: str
) -> None:
    (snippet,) = [e for e in _semgrep_errors(GAPS) if e["path"] == "workflow.yml"]
    message = snippet["message"].replace("'workflow-run-echo'", f"'{rule}'")
    report = _semgrep_report_with(tmp_path, GAPS, [{**snippet, "path": target, "message": message}])
    rc, out, err = _semgrep_gate(tmp_path, report, capsys)
    assert (rc, out) == (1, "")
    lost = f"{target} (PartialParsing in {rule}, line(s) 7-9)"
    assert err == f"CI-SEC-005: semgrep: {report} shows 1 {LOST}{lost}\n"


@pytest.mark.parametrize(
    "kind",
    [
        "Lexical error",
        "Other syntax error",
        "AST builder error",
        "Out of memory",
        "Stack overflow",
        "Fatal error",
        "Missing plugin",
        "a kind this gate has never seen",
    ],
)
@pytest.mark.parametrize("target", ["unparsed.py", None])
def test_semgrep_error_of_any_other_kind_raises_ci_sec_005(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str, target: str | None
) -> None:
    # Fail closed: only a timeout and a YAML snippet gap leave the other rules' findings.
    (error,) = _semgrep_errors("semgrep-1.181.0.json")[:1]
    edited = {k: v for k, v in error.items() if k != "path"} | {"type": kind}
    report = _semgrep_report_with(
        tmp_path, "semgrep-1.181.0.json", [edited | ({"path": target} if target else {})]
    )
    rc, out, err = _semgrep_gate(tmp_path, report, capsys)
    assert (rc, out) == (1, "")
    lost = f"{target or 'an unnamed target'} ({kind})"
    assert err == f"CI-SEC-005: semgrep: {report} shows 1 {LOST}{lost}\n"


def test_semgrep_error_with_no_type_name_raises_ci_sec_005(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (error,) = _semgrep_errors("semgrep-1.181.0.json")[:1]
    report = _semgrep_report_with(tmp_path, "semgrep-1.181.0.json", [{**error, "type": None}])
    rc, out, err = _semgrep_gate(tmp_path, report, capsys)
    assert (rc, out) == (1, "")
    assert err.startswith(f"CI-SEC-005: semgrep: {report} has an error with no type name: ")


def test_semgrep_warning_escapes_its_target_and_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Escaped as the Actions toolkit does: no file name can end or forge a workflow command.
    timeout, *_ = [e for e in _semgrep_errors(GAPS) if e["type"] == "Timeout"]
    report = _semgrep_report_with(tmp_path, GAPS, [{**timeout, "path": "a,b:c%\n::x.py"}])
    rc, out, err = _semgrep_gate(tmp_path, report, capsys)
    assert (rc, err) == (0, "")
    escaped = "a,b:c%25%0A::x.py"
    note = f"slow-sequence-a timed out on {escaped}; the other rules analysed it, not failing"
    assert out.splitlines() == [f"::warning file=a%2Cb%3Ac%25%0A%3A%3Ax.py::semgrep: {note}", OK]


def test_semgrep_gate_without_the_json_report_raises_ci_sec_005(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, out, err = _semgrep_gate(tmp_path, None, capsys)
    unknown = "no --semgrep-json report, so the files it did not parse are unknown"
    assert (rc, out, err) == (1, "", f"CI-SEC-005: semgrep: {unknown}\n")


@pytest.mark.parametrize("doc", [[], {"results": []}, {"errors": {}}, {"errors": ["x"]}])
def test_semgrep_json_that_is_no_report_raises_ci_sec_005(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], doc: object
) -> None:
    report = _write_json(tmp_path, "semgrep.json", doc)
    rc, out, err = _semgrep_gate(tmp_path, report, capsys)
    assert (rc, out) == (1, "")
    assert err == f"CI-SEC-005: semgrep: {report} has no 'errors' list of objects " + (
        "(not a semgrep --json-output report)\n"
    )


def test_semgrep_partial_parse_without_a_span_raises_ci_sec_005(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (error,) = [e for e in _semgrep_errors("semgrep-1.99.0.json") if e["path"] == "partial.py"]
    edited = {**error, "spans": [], "type": ["PartialParsing", []]}
    report = _semgrep_report_with(tmp_path, "semgrep-1.99.0.json", [edited])
    rc, out, err = _semgrep_gate(tmp_path, report, capsys)
    assert (rc, out) == (1, "")
    no_span = "has a PartialParsing error with no target or line span: "
    assert err.startswith(f"CI-SEC-005: semgrep: {report} {no_span}")


def test_semgrep_skips_report_raises_ci_sec_005(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # As recorded: only --verbose says Semgrep skipped slow.py for its size, and newer.yml's
    # rule never ran. The excluded unparsed.py and workflow.yml's YAML snippet gap would pass.
    report = _semgrep_report(tmp_path, SKIPS)
    rc, out, err = _semgrep_gate(tmp_path, report, capsys)
    assert (rc, out) == (1, "")
    lost = (
        "../newer.yml (IncompatibleRule in newer-semgrep-only); "
        "slow.py (skipped: exceeded_size_limit)"
    )
    assert err == f"CI-SEC-005: semgrep: {report} shows 2 {LOST}{lost}\n"


@pytest.mark.parametrize(
    "reason",
    [
        "semgrepignore_patterns_match",
        "Gitignore_patterns_match",
        "cli_include_flags_do_not_match",
        "cli_exclude_flags_match",
    ],
)
def test_semgrep_target_skipped_by_configuration_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], reason: str
) -> None:
    # An ignore file or a CLI include/exclude is configuration that review sees. workflow.yml
    # is listed as skipped because its analysis failed in part: its error is a warning.
    (snippet,) = [e for e in _semgrep_errors(SKIPS) if e["path"] == "workflow.yml"]
    skipped = [
        {"path": "slow.py", "reason": reason},
        {"path": "unparsed.py", "reason": "cli_exclude_flags_match"},
        {"path": "workflow.yml", "reason": FAILED},
    ]
    report = _semgrep_report_with(tmp_path, SKIPS, [snippet], skipped)
    rc, out, err = _semgrep_gate(tmp_path, report, capsys)
    assert (rc, err) == (0, "")
    note = "workflow-run-echo could not parse the snippet on line(s) 7-9; the rest was analysed"
    assert out.splitlines() == [
        f"::warning file=workflow.yml,line=7::semgrep: workflow.yml: {note}, not failing",
        OK,
    ]


@pytest.mark.parametrize(
    ("entry", "lost"),
    [
        ({"path": "workflow.yml", "reason": FAILED}, f"workflow.yml (skipped: {FAILED})"),
        ({"path": "app.min.js", "reason": "minified"}, "app.min.js (skipped: minified)"),
        ({"path": ".git", "reason": "always_skipped"}, ".git (skipped: always_skipped)"),
        ({"path": "slow.py", "reason": "a new reason"}, "slow.py (skipped: a new reason)"),
        ({"path": "slow.py"}, "slow.py (skipped: no reason given)"),
        (
            {"reason": "semgrepignore_patterns_match"},
            "an unnamed target (skipped: semgrepignore_patterns_match)",
        ),
    ],
)
def test_semgrep_target_skipped_for_another_reason_raises_ci_sec_005(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], entry: dict[str, str], lost: str
) -> None:
    # Fail closed: a target whose analysis failed with no error to say why, a reason that is
    # not configuration (one Semgrep's schema has, or a new one), or an entry it cannot place.
    report = _semgrep_report_with(tmp_path, SKIPS, [], [entry])
    rc, out, err = _semgrep_gate(tmp_path, report, capsys)
    assert (rc, out) == (1, "")
    assert err == f"CI-SEC-005: semgrep: {report} shows 1 {LOST}{lost}\n"


def test_semgrep_rule_it_skipped_raises_ci_sec_005(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # 1.181.0 always writes `skipped_rules: []` and reports a rule it cannot run in `errors`
    # (IncompatibleRule above); an entry, shaped as semgrep_output_v1's skipped_rule, fails.
    rule = {"rule_id": "x", "details": "unsupported", "position": {"line": 3, "col": 5}}
    doc = json.loads(_semgrep_report_with(tmp_path, SKIPS, [], []).read_text(encoding="utf-8"))
    report = _write_json(tmp_path, "skipped-rule.json", doc | {"skipped_rules": [rule]})
    rc, out, err = _semgrep_gate(tmp_path, report, capsys)
    assert (rc, out) == (1, "")
    assert err == f"CI-SEC-005: semgrep: {report} shows 1 {LOST}a rule Semgrep skipped: " + (
        json.dumps(rule) + "\n"
    )


NO_SKIPPED_TARGETS = (
    "has no 'paths.skipped' list of objects (semgrep writes it with --verbose), so the targets "
    "it skipped are unknown"
)
NO_SKIPPED_RULES = "has no 'skipped_rules' list of objects, so the rules it skipped are unknown"


@pytest.mark.parametrize(
    ("edit", "problem"),
    [
        (lambda doc: doc["paths"].pop("skipped"), NO_SKIPPED_TARGETS),
        (lambda doc: doc.pop("paths"), NO_SKIPPED_TARGETS),
        (lambda doc: doc["paths"].update(skipped=[["slow.py"]]), NO_SKIPPED_TARGETS),
        (lambda doc: doc.pop("skipped_rules"), NO_SKIPPED_RULES),
        (lambda doc: doc.update(skipped_rules=["x"]), NO_SKIPPED_RULES),
    ],
)
def test_semgrep_report_without_its_skip_lists_raises_ci_sec_005(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    edit: Callable[[dict[str, Any]], object],
    problem: str,
) -> None:
    # A report written without --verbose cannot say which targets Semgrep skipped.
    doc = json.loads((SEMGREP_FIXTURES / SKIPS).read_text(encoding="utf-8"))
    edit(doc)
    report = _write_json(tmp_path, "semgrep.json", doc)
    rc, out, err = _semgrep_gate(tmp_path, report, capsys)
    assert (rc, out, err) == (1, "", f"CI-SEC-005: semgrep: {report} {problem}\n")


def test_semgrep_lost_targets_are_escaped_onto_one_log_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The runner reads workflow commands from stderr too: no target name may start a new line.
    error = {"code": 2, "level": "error", "type": "Fatal error", "message": "x"}
    report = _semgrep_report_with(tmp_path, SKIPS, [error | {"path": "a%\r\n::error::x.py"}], [])
    rc, out, err = _semgrep_gate(tmp_path, report, capsys)
    assert (rc, out) == (1, "")
    lost = "a%25%0D%0A::error::x.py (Fatal error)"
    assert err == f"CI-SEC-005: semgrep: {report} shows 1 {LOST}{lost}\n"


def test_semgrep_scan_with_findings_and_a_lost_target_reports_both(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The step log names the blocking finding as well as the target Semgrep did not analyse.
    sarif = _write_json(tmp_path, "semgrep.sarif", _sarif_doc("cv-unpinned-action"))
    (unparsed,) = [e for e in _semgrep_errors("semgrep-1.181.0.json") if e["path"] == "unparsed.py"]
    report = _semgrep_report_with(tmp_path, "semgrep-1.181.0.json", [unparsed])
    rc, out, err = _semgrep_gate(tmp_path, report, capsys, sarif)
    assert (rc, out) == (1, "")
    blocked, verdict, gap = err.splitlines()
    assert blocked.startswith("CI-SEC-001: semgrep finding cv-unpinned-action:")
    assert verdict == "security_gate[semgrep]: BLOCKED (CI-SEC-001)"
    assert gap == f"CI-SEC-005: semgrep: {report} shows 1 {LOST}unparsed.py (Syntax error)"


def _semgrep_auth_gate(
    tmp_path: Path, report: Path, capsys: pytest.CaptureFixture[str]
) -> tuple[int, str, str]:
    risks = _write_yaml(tmp_path, {"entries": []})
    rc = main(["--tool", "semgrep-auth", "--report", str(report), "--accepted-risks", str(risks)])
    out, err = capsys.readouterr()
    return rc, out, err


def test_semgrep_auth_report_of_a_complete_scan_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = _semgrep_report_with(tmp_path, SKIPS, [], [])
    assert _semgrep_auth_gate(tmp_path, report, capsys) == (
        0,
        "security_gate[semgrep-auth]: OK\n",
        "",
    )


@pytest.mark.parametrize(
    ("kind", "lost"),
    [
        ("Timeout", "slow.py (Timeout in slow-sequence-a)"),
        ("PartialParsing", "workflow.yml (PartialParsing in workflow-run-echo, line(s) 7-9)"),
    ],
)
def test_semgrep_auth_gap_of_any_rule_raises_ci_sec_005(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str, lost: str
) -> None:
    # Each auth pack rule guards RBAC or audit (C-12.4, C-2.9), so no gap is only a warning:
    # neither one timeout nor a YAML snippet it could not parse.
    error, *_ = [e for e in _semgrep_errors(GAPS) if kind in (e["type"], e["type"][0])]
    report = _semgrep_report_with(tmp_path, GAPS, [error])
    rc, out, err = _semgrep_auth_gate(tmp_path, report, capsys)
    assert (rc, out) == (1, "")
    assert err == f"CI-SEC-005: semgrep: {report} shows 1 {LOST}{lost}\n"


def test_semgrep_auth_report_that_lists_no_skips_raises_ci_sec_005(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = json.loads((SEMGREP_FIXTURES / SKIPS).read_text(encoding="utf-8"))
    del doc["paths"]["skipped"]
    report = _write_json(tmp_path, "semgrep-auth.json", doc)
    rc, out, err = _semgrep_auth_gate(tmp_path, report, capsys)
    assert (rc, out) == (1, "")
    assert err.startswith(f"CI-SEC-005: semgrep: {report} has no 'paths.skipped' list")


def test_missing_accepted_risks_file_raises_ci_sec_005(tmp_path: Path) -> None:
    with pytest.raises(SecurityGateError) as exc_info:
        load_accepted_risks(tmp_path / "does-not-exist.yaml")
    assert exc_info.value.code == "CI-SEC-005"


def test_malformed_accepted_risks_entry_raises_ci_sec_005(tmp_path: Path) -> None:
    risks_path = _write_yaml(tmp_path, {"entries": [{"id": "x", "tool": "bandit"}]})
    with pytest.raises(SecurityGateError) as exc_info:
        load_accepted_risks(risks_path)
    assert exc_info.value.code == "CI-SEC-005"


@pytest.mark.parametrize("severity", ["Moderate", "medium", "HIGH ", "critical", None, ["HIGH"]])
def test_register_refuses_a_severity_the_gate_cannot_rank(tmp_path: Path, severity: object) -> None:
    # #3558: the cap ranks an entry's severity, so an entry in pnpm's words or another case is
    # malformed on load (CI-SEC-005), not a KeyError on the first finding that matches it. So is
    # an empty `severity:` (None) or a list, which only the str check keeps from a TypeError.
    entry = {"id": "GHSA-82fw-gwwq-j7x9", "tool": "npm-audit", "severity": severity}
    entry |= {"reason": "test", "approver": "basiltt", "expires": "2099-01-01"}
    with pytest.raises(SecurityGateError) as exc_info:
        load_accepted_risks(_write_yaml(tmp_path, {"entries": [entry]}))
    message = f"severity {severity!r} is not one of LOW, MEDIUM, HIGH, CRITICAL"
    assert exc_info.value.code == "CI-SEC-005"
    assert exc_info.value.message == f"accepted-risk entry #0 is malformed: {message}"


# --------------------------------------------------------------------------
# CLI entrypoint
# --------------------------------------------------------------------------


def test_main_cli_blocks_on_gitleaks_finding(tmp_path: Path) -> None:
    risks = _write_yaml(tmp_path, {"entries": []})
    report = _write_json(
        tmp_path,
        "gitleaks.json",
        [{"RuleID": "generic-api-key", "File": "a.py", "StartLine": 1}],
    )
    rc = main(
        [
            "--tool",
            "gitleaks",
            "--report",
            str(report),
            "--accepted-risks",
            str(risks),
            "--run-date",
            "2026-01-01",
        ]
    )
    assert rc == 1


def test_main_cli_ok_on_clean_report(tmp_path: Path) -> None:
    risks = _write_yaml(tmp_path, {"entries": []})
    report = _write_json(tmp_path, "gitleaks.json", [])
    rc = main(
        [
            "--tool",
            "gitleaks",
            "--report",
            str(report),
            "--accepted-risks",
            str(risks),
            "--run-date",
            "2026-01-01",
        ]
    )
    assert rc == 0


def test_repo_register_accepts_the_braces_ghsa_exception_with_approver_and_expiry() -> None:
    register = Path(__file__).resolve().parents[2] / "security" / "accepted-risks.yaml"
    risks = {r.finding_id: r for r in load_accepted_risks(register)}
    ids = ["GHSA-vfj7-8cjw-p6xm"]  # EX-05 cleared by override (#1857)
    findings = []
    for gid in ids:
        assert risks[gid].approver and risks[gid].expires
        findings.append(Finding(tool="npm-audit", finding_id=gid, severity="HIGH", package="x"))
    result = evaluate_findings(findings, list(risks.values()), run_date=date(2026, 10, 3))
    assert not result.blocked
    late = evaluate_findings(findings, list(risks.values()), run_date=date(2027, 1, 1))
    assert late.blocked


def test_gitleaks_block_message_cites_ir02(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    risks = _write_yaml(tmp_path, {"entries": []})
    report = _write_json(
        tmp_path,
        "gitleaks.json",
        [{"RuleID": "generic-api-key", "File": "a.py", "StartLine": 1}],
    )
    rc = main(["--tool", "gitleaks", "--report", str(report), "--accepted-risks", str(risks)])
    err = capsys.readouterr().err
    assert rc == 1
    assert "IR-02" in err and "docs/ci-runbook.md" in err


def test_gitleaks_negative_proof_fake_secret_fixture_blocks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A planted, clearly fake DUMMYKEY_ vector run through real gitleaks -> gate blocks."""
    import shutil
    import subprocess

    exe = shutil.which("gitleaks")
    if exe is None:
        pytest.skip("gitleaks binary not installed (CI runs the pinned container instead)")
    (tmp_path / "leak.txt").write_text("token = DUMMYKEY_ABCDEFGHIJKLMNOP\n", encoding="utf-8")
    (tmp_path / "cfg.toml").write_text(
        '[[rules]]\nid = "dummy-test-vector"\ndescription = "fake test vector"\n'
        "regex = '''DUMMYKEY_[A-Z]{16}'''\n",
        encoding="utf-8",
    )
    rep = tmp_path / "gl.json"
    subprocess.run(
        [
            exe,
            "detect",
            "--no-git",
            "--source",
            str(tmp_path),
            "--config",
            str(tmp_path / "cfg.toml"),
            "--redact",
            "-f",
            "json",
            "-r",
            str(rep),
        ],
        check=False,
        capture_output=True,
    )
    risks = _write_yaml(tmp_path, {"entries": []})
    rc = main(["--tool", "gitleaks", "--report", str(rep), "--accepted-risks", str(risks)])
    assert rc == 1
    assert "IR-02" in capsys.readouterr().err


# --------------------------------------------------------------------------
# CI-SEC-006: in-source Semgrep suppressions
# --------------------------------------------------------------------------

_RULE = "cv-broad-except-on-ingest"
_TAIL = "reason=fp owner=@basil review=2026-12-31"
_GOOD = f"# nosemgrep: {_RULE} {_TAIL}"
_INSRC = [{"kind": "inSource"}]


def _supp_sarif(supp: list[dict], uri: str = "a.py", line: int = 2) -> dict:
    doc = _sarif_doc(f"rules.{_RULE}")
    res = doc["runs"][0]["results"][0]
    res["suppressions"] = supp
    loc = res["locations"][0]["physicalLocation"]
    loc["artifactLocation"]["uri"] = uri
    loc["region"]["startLine"] = line
    return doc


def _parse(tmp_path: Path, doc: dict, src: str | None, tool: str = "semgrep") -> list[Finding]:
    if src is not None:
        (tmp_path / "a.py").write_text(src, encoding="utf-8")
    report = _write_json(tmp_path, "r.sarif", doc)
    return parse_sarif(report, tool, source_root=tmp_path, today=date(2026, 10, 6))


def test_justified_in_source_suppression_is_not_blocking(tmp_path: Path) -> None:
    assert _parse(tmp_path, _supp_sarif(_INSRC), f"{_GOOD}\nx = 1\n") == []
    assert _parse(tmp_path, _supp_sarif(_INSRC, line=1), f"x = 1  {_GOOD}\n") == []


def test_blanket_nosemgrep_still_blocks_ci_sec_006(tmp_path: Path) -> None:
    out = _parse(tmp_path, _supp_sarif(_INSRC), "# nosemgrep\nx = 1\n")
    assert len(out) == 1 and out[0].severity == "HIGH"
    assert "CI-SEC-006: unjustified in-source suppression" in out[0].detail


def test_nosemgrep_for_other_rule_still_blocks(tmp_path: Path) -> None:
    src = "# nosemgrep: other-rule reason=r owner=@b review=2026-12-31\nx = 1\n"
    out = _parse(tmp_path, _supp_sarif(_INSRC), src)
    assert len(out) == 1 and "CI-SEC-006" in out[0].detail


def test_expired_suppression_review_date_blocks(tmp_path: Path) -> None:
    src = f"# nosemgrep: {_RULE} reason=r owner=@b review=2026-10-05\nx = 1\n"
    out = _parse(tmp_path, _supp_sarif(_INSRC), src)
    assert len(out) == 1 and "expired" in out[0].detail
    src = f"# nosemgrep: {_RULE} reason=r owner=@b review=2026-10-06\nx = 1\n"
    assert _parse(tmp_path, _supp_sarif(_INSRC), src) == []


def test_justification_field_path_needs_no_source_file(tmp_path: Path) -> None:
    ok = _supp_sarif([{"kind": "inSource", "justification": _GOOD}])
    assert _parse(tmp_path, ok, None) == []
    bad = _supp_sarif([{"kind": "inSource", "justification": "nosemgrep"}])
    assert "CI-SEC-006" in _parse(tmp_path, bad, None)[0].detail


def test_missing_source_file_fails_closed(tmp_path: Path) -> None:
    assert len(_parse(tmp_path, _supp_sarif(_INSRC), None)) == 1


def test_external_suppression_kind_is_not_honoured(tmp_path: Path) -> None:
    out = _parse(tmp_path, _supp_sarif([{"kind": "external"}]), f"{_GOOD}\n")
    assert len(out) == 1 and "CI-SEC-006" not in out[0].detail


@pytest.mark.parametrize("tool", ["codeql", "trivy", "bandit"])
def test_non_semgrep_tools_ignore_suppressions(tmp_path: Path, tool: str) -> None:
    out = _parse(tmp_path, _supp_sarif(_INSRC), f"{_GOOD}\n", tool=tool)
    assert len(out) == 1 and "CI-SEC-006" not in out[0].detail


# --------------------------------------------------------------------------
# Review round 4: the reviewer's adversarial bypasses must all BLOCK.
# --------------------------------------------------------------------------


def _blocks(out: list[Finding]) -> bool:
    return len(out) == 1 and "CI-SEC-006" in out[0].detail and out[0].severity == "HIGH"


def test_rule_id_prefix_does_not_suppress(tmp_path: Path) -> None:
    src = f"# nosemgrep: {_RULE}-other {_TAIL}\nx = 1\n"
    assert _blocks(_parse(tmp_path, _supp_sarif(_INSRC), src))
    src = f"# nosemgrep: cv-broad {_TAIL}\nx = 1\n"
    assert _blocks(_parse(tmp_path, _supp_sarif(_INSRC), src))


def test_code_line_above_is_never_a_justification(tmp_path: Path) -> None:
    src = f"ok()  # nosemgrep: {_RULE} {_TAIL}\nx = 1\n"
    assert _blocks(_parse(tmp_path, _supp_sarif(_INSRC), src))


def test_comment_finding_line_does_not_borrow_comment_above(tmp_path: Path) -> None:
    src = f"{_GOOD}\n# a comment that is itself the finding\n"
    assert _blocks(_parse(tmp_path, _supp_sarif(_INSRC), src))


@pytest.mark.parametrize(
    "tail",
    [
        "reason=fp @ review=2026-12-31",
        "reason=owner-said-so review=2026-12-31",
        "reason=fp owner=@ review=2026-12-31",
        "reason=fp owner=basil review=2026-12-31",
        "- r, owner @b, review 2026-12-31",
    ],
)
def test_owner_spoofs_and_legacy_format_block(tmp_path: Path, tail: str) -> None:
    src = f"# nosemgrep: {_RULE} {tail}\nx = 1\n"
    assert _blocks(_parse(tmp_path, _supp_sarif(_INSRC), src))


def test_far_future_review_date_blocks(tmp_path: Path) -> None:
    src = f"# nosemgrep: {_RULE} reason=r owner=@b review=2099-12-31\nx = 1\n"
    out = _parse(tmp_path, _supp_sarif(_INSRC), src)
    assert _blocks(out) and "expiry too far" in out[0].detail
    cap = f"# nosemgrep: {_RULE} reason=r owner=@b review=2027-04-04\nx = 1\n"
    assert _parse(tmp_path, _supp_sarif(_INSRC), cap) == []  # today + 180 d
    over = f"# nosemgrep: {_RULE} reason=r owner=@b review=2027-04-05\nx = 1\n"
    assert _blocks(_parse(tmp_path, _supp_sarif(_INSRC), over))


def test_multi_rule_list_exact_members_suppress(tmp_path: Path) -> None:
    for rules in (f"other-rule, {_RULE}", f"other-rule,{_RULE}", f"rules.{_RULE} x"):
        src = f"# nosemgrep: {rules} {_TAIL}\nx = 1\n"
        assert _parse(tmp_path, _supp_sarif(_INSRC), src) == [], rules


def test_migrated_repo_format_with_org_team_owner_is_accepted(tmp_path: Path) -> None:
    tail = "reason=B5-b owner=@CandleViewer/security review=2026-12-31"
    src = f"x = 1  # nosemgrep: other,{_RULE} {tail}\n"
    assert _parse(tmp_path, _supp_sarif(_INSRC, line=1), src) == []


def test_rule_index_disagreeing_with_rule_id_takes_higher_severity(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = _sarif_doc("cv-z")
    run = doc["runs"][0]
    del run["results"][0]["level"]
    run["results"][0]["ruleIndex"] = 0
    run["tool"]["driver"]["rules"] = [
        {"id": "cv-low", "defaultConfiguration": {"level": "note"}},
        {"id": "cv-z", "defaultConfiguration": {"level": "error"}},
    ]
    out = parse_sarif(_write_json(tmp_path, "r.sarif", doc), "semgrep")
    assert out[0].severity == "HIGH"
    assert "disagree" in capsys.readouterr().err
    run["tool"]["driver"]["rules"] = [
        {"id": "cv-high", "properties": {"security-severity": "9.5"}},
        {"id": "cv-z", "defaultConfiguration": {"level": "note"}},
    ]
    out = parse_sarif(_write_json(tmp_path, "r2.sarif", doc), "semgrep")
    assert out[0].severity == "CRITICAL"


@pytest.mark.parametrize("tool", ["semgrep", "bandit", "trivy"])  # codeql: CI-SEC-005 (#3372)
def test_no_severity_anywhere_is_medium(tmp_path: Path, tool: str) -> None:
    doc = _sarif_doc("cv-q")
    del doc["runs"][0]["results"][0]["level"]
    assert parse_sarif(_write_json(tmp_path, "r.sarif", doc), tool)[0].severity == "MEDIUM"


def test_unreadable_source_still_blocks(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_bytes(b"\xff\xfe\x00bad")
    assert _blocks(_parse(tmp_path, _supp_sarif(_INSRC), None))


def test_accepted_risk_is_reported_not_silent() -> None:
    f = Finding(tool="semgrep", finding_id="cv-x:a.py:1", severity="HIGH")
    risk = AcceptedRisk("cv-x:a.py:1", "semgrep", "HIGH", "why", "basiltt", date(2026, 12, 31))
    res = evaluate_findings([f], [risk], run_date=date(2026, 10, 6))
    assert not res.blocked and any("accepted risk: semgrep" in m for m in res.messages)


def test_repo_register_covers_the_0004_migration_findings() -> None:
    root = Path(__file__).resolve().parents[2]
    risks = load_accepted_risks(root / "security" / "accepted-risks.yaml")
    mig = "services/api/candleviewer/migrations/versions/0004_instruments.py"
    hits = [r for r in risks if r.tool == "semgrep" and mig in r.finding_id]
    assert len(hits) == 3
    assert all(r.expires == date(2026, 12, 31) for r in hits)


# --------------------------------------------------------------------------
# #3494: the npm-audit leg reads what CI runs, `pnpm audit --json` (pnpm 12.5.1)
# --------------------------------------------------------------------------

PNPM_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "pnpm-audit"
REGISTER = Path(__file__).resolve().parents[2] / "security" / "accepted-risks.yaml"
# pnpm-12.5.1-main.json (main at d77138f07): one finding per advisory, in pnpm's order.
MAIN_FINDINGS = [
    ("GHSA-w5hq-g745-h8pq", "MEDIUM", "uuid@9.0.1"),
    ("GHSA-g7r4-m6w7-qqqr", "LOW", "esbuild@0.27.7"),
    ("GHSA-wrjc-x8rr-h8h6", "MEDIUM", "react-router@6.30.6"),
    ("GHSA-337j-9hxr-rhxg", "MEDIUM", "react-router@6.30.6"),
    ("GHSA-82fw-gwwq-j7x9", "MEDIUM", "vitest@3.2.7"),
    ("GHSA-82fw-gwwq-j7x9", "MEDIUM", "@vitest/mocker@3.2.7"),
    ("GHSA-vfj7-8cjw-p6xm", "HIGH", "braces@3.0.3"),
    ("GHSA-hp3w-g68c-fv3c", "MEDIUM", "sprintf-js@1.1.3"),
    ("GHSA-68fv-2mgg-jv7q", "HIGH", "source-map-js@1.2.1"),
    ("GHSA-5gmw-xhrv-c9v3", "CRITICAL", "tinypool@1.1.1"),
    ("GHSA-85c8-ppgw-ccpr", "CRITICAL", "tinypool@1.1.1"),
]
SOURCE_MAP_JS, BRACES, TINYPOOL = "1241209", "1240992", "1241260"  # their advisories' keys
VITEST, VITEST_MOCKER = "1193683", "1193684"  # GHSA-82fw-gwwq-j7x9 on each module
CRITICAL_RULE = "Critical findings take no accepted-risk entry (30-release-roadmap.md §4.4 R0)"


def _pnpm_doc(*keys: str) -> dict[str, Any]:
    """pnpm-12.5.1-main.json cut down to the advisories `keys`, recounted as pnpm counts them."""
    doc: dict[str, Any] = json.loads(
        (PNPM_FIXTURES / "pnpm-12.5.1-main.json").read_text(encoding="utf-8")
    )
    doc["advisories"] = {key: doc["advisories"][key] for key in keys}
    counts = dict.fromkeys(doc["metadata"]["vulnerabilities"], 0)
    for advisory in doc["advisories"].values():
        counts[advisory["severity"]] += 1
    doc["metadata"]["vulnerabilities"] = counts
    return doc


def _npm_gate(
    capsys: pytest.CaptureFixture[str],
    report: Path,
    risks: Path = REGISTER,
    run_date: str = "2026-10-18",
) -> tuple[int, str, str]:
    argv = ["--tool", "npm-audit", "--report", str(report), "--accepted-risks", str(risks)]
    rc = main([*argv, "--run-date", run_date])
    out, err = capsys.readouterr()
    return rc, out, err


def test_real_pnpm_audit_report_from_main_gives_one_finding_per_advisory() -> None:
    findings = parse_npm_audit(PNPM_FIXTURES / "pnpm-12.5.1-main.json")
    assert [(f.finding_id, f.severity, f.package) for f in findings] == MAIN_FINDINGS
    assert {f.tool for f in findings} == {"npm-audit"}
    assert findings[-1].detail == (
        "tinypool@1.1.1: Tinypool: Prototype Pollution Gadget to RCE in run() options "
        "(2 dependency paths, e.g. packages__config>@vitest/coverage-v8>vitest>tinypool)"
    )


def test_real_pnpm_audit_report_from_main_blocks_on_its_critical_and_high_advisories(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc, out, err = _npm_gate(capsys, PNPM_FIXTURES / "pnpm-12.5.1-main.json")
    assert (rc, out) == (1, "")
    blocking = re.findall(r"^CI-SEC-001: npm-audit finding (\S+) \((\w+)\)", err, re.MULTILINE)
    assert blocking == [
        ("GHSA-68fv-2mgg-jv7q", "HIGH"),
        ("GHSA-5gmw-xhrv-c9v3", "CRITICAL"),
        ("GHSA-85c8-ppgw-ccpr", "CRITICAL"),
    ]
    lines = err.splitlines()
    assert (len(lines), lines[-1]) == (5, "security_gate[npm-audit]: BLOCKED (CI-SEC-001)")
    (accepted,) = [line for line in lines if line.startswith("accepted risk: ")]
    head = "accepted risk: npm-audit finding GHSA-vfj7-8cjw-p6xm (HIGH) until 2026-12-31 - EX-06: "
    assert accepted.startswith(head)


def test_clean_pnpm_audit_report_passes_with_no_findings(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = PNPM_FIXTURES / "pnpm-12.5.1-clean.json"
    assert parse_npm_audit(report) == []
    assert _npm_gate(capsys, report) == (0, "security_gate[npm-audit]: OK\n", "")


def test_pnpm_advisory_on_several_versions_and_paths_is_one_finding() -> None:
    findings = parse_npm_audit(PNPM_FIXTURES / "pnpm-12.5.1-multi-version.json")
    assert [(f.finding_id, f.severity, f.package) for f in findings] == [
        ("GHSA-grv7-fg5c-xmjg", "HIGH", "braces@2.3.2,3.0.2"),
        ("GHSA-952p-6rrq-rcjv", "MEDIUM", "micromatch@3.1.10"),
        ("GHSA-vcc3-ghjq-m6fr", "MEDIUM", "decode-uri-component@0.2.2"),
        ("GHSA-vfj7-8cjw-p6xm", "HIGH", "braces@2.3.2,3.0.2"),
    ]
    assert "(5 dependency paths, e.g. .>micromatch>snapdragon>" in findings[2].detail


def test_pnpm_report_missing_an_advisory_its_metadata_counts_raises_ci_sec_005(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # pnpm leaves an advisory on its auditConfig ignore list out of `advisories` but still counts
    # it (fixtures README): exceptions go through security/accepted-risks.yaml only (C-12.3).
    report = PNPM_FIXTURES / "pnpm-12.5.1-ignored.json"
    rc, out, err = _npm_gate(capsys, report)
    assert (rc, out) == (1, "")
    assert err == (
        f"CI-SEC-005: npm-audit: {report} lists 1 high, 2 moderate advisories but its metadata "
        "counts 2 high, 2 moderate: every advisory pnpm counts must reach the gate\n"
    )


@pytest.mark.parametrize(
    ("keys", "high", "says"),
    [
        ((), 1, "lists no advisories but its metadata counts 1 high"),
        ((SOURCE_MAP_JS,), 0, "lists 1 high advisories but its metadata counts none"),
    ],
)
def test_pnpm_report_whose_counts_disagree_with_its_advisories_raises_ci_sec_005(
    tmp_path: Path, keys: tuple[str, ...], high: int, says: str
) -> None:
    doc = _pnpm_doc(*keys)
    doc["metadata"]["vulnerabilities"]["high"] = high
    with pytest.raises(SecurityGateError) as exc_info:
        parse_npm_audit(_write_json(tmp_path, "npm-audit.json", doc))
    assert (exc_info.value.code, exc_info.value.message.split(" ", 2)[2]) == (
        "CI-SEC-005",
        f"{says}: every advisory pnpm counts must reach the gate",
    )


def test_pnpm_high_advisory_without_a_register_entry_blocks_with_ci_sec_001(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = _write_json(tmp_path, "npm-audit.json", _pnpm_doc(SOURCE_MAP_JS))
    rc, out, err = _npm_gate(capsys, report)
    assert (rc, out) == (1, "")
    head = "CI-SEC-001: npm-audit finding GHSA-68fv-2mgg-jv7q (HIGH) has no accepted-risk entry"
    assert err.startswith(head + " — source-map-js@1.2.1: ")


def test_braces_stays_accepted_by_ex06_until_it_expires(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = _write_json(tmp_path, "npm-audit.json", _pnpm_doc(BRACES))
    rc, out, err = _npm_gate(capsys, report)
    assert (rc, err) == (0, "")
    assert out.startswith("accepted risk: npm-audit finding GHSA-vfj7-8cjw-p6xm (HIGH) until ")
    rc, out, err = _npm_gate(capsys, report, run_date="2026-12-31")
    assert (rc, out) == (1, "")
    assert err.startswith("CI-SEC-004: accepted risk expired for GHSA-vfj7-8cjw-p6xm ")


def test_one_register_entry_covers_its_ghsa_on_every_module_pnpm_reports(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Entries match on id and tool, never on the package (security/accepted-risks.yaml's schema
    # comment): pnpm reports GHSA-82fw-gwwq-j7x9 on vitest and on @vitest/mocker, and one entry
    # covers both. Raised to high, since only a finding at the gate's threshold meets the register.
    doc = _pnpm_doc(VITEST, VITEST_MOCKER)
    for advisory in doc["advisories"].values():
        advisory["severity"] = "high"
    doc["metadata"]["vulnerabilities"] |= {"moderate": 0, "high": 2}
    report = _write_json(tmp_path, "npm-audit.json", doc)
    entry = {"id": "GHSA-82fw-gwwq-j7x9", "tool": "npm-audit", "severity": "HIGH"}
    entry |= {"reason": "test", "approver": "basiltt", "expires": "2099-01-01"}
    rc, out, err = _npm_gate(capsys, report, _write_yaml(tmp_path, {"entries": [entry]}))
    assert (rc, err) == (0, "")
    accepted = "accepted risk: npm-audit finding GHSA-82fw-gwwq-j7x9 (HIGH) until 2099-01-01 - test"
    assert out.splitlines() == [accepted, accepted, "security_gate[npm-audit]: OK"]
    rc, out, err = _npm_gate(capsys, report, _write_yaml(tmp_path, {"entries": []}))
    assert (rc, out) == (1, "")
    assert [line.split(" — ")[-1].split(":")[0] for line in err.splitlines()[:2]] == [
        "vitest@3.2.7",
        "@vitest/mocker@3.2.7",
    ]


def test_critical_pnpm_advisory_blocks_even_with_a_matching_register_entry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The register refuses a CRITICAL entry at load, so a matching entry has a lower severity.
    report = _write_json(tmp_path, "npm-audit.json", _pnpm_doc(TINYPOOL))
    entry = {"id": "GHSA-5gmw-xhrv-c9v3", "tool": "npm-audit", "severity": "HIGH"}
    entry |= {"reason": "test", "approver": "basiltt", "expires": "2099-01-01"}
    rc, out, err = _npm_gate(capsys, report, _write_yaml(tmp_path, {"entries": [entry]}))
    assert (rc, out) == (1, "")
    head = "CI-SEC-001: npm-audit finding GHSA-5gmw-xhrv-c9v3 (CRITICAL) has an accepted-risk entry"
    assert err.startswith(f"{head}, but {CRITICAL_RULE} — tinypool@1.1.1: ")


@pytest.mark.parametrize("tool", ["codeql", "semgrep", "bandit", "pip-audit", "npm-audit", "trivy"])
def test_no_register_entry_covers_a_critical_finding(tool: str) -> None:
    finding = Finding(tool=tool, finding_id="X-1", severity="CRITICAL", detail="d")
    risk = AcceptedRisk("X-1", tool, "HIGH", "why", "basiltt", date(2099, 1, 1))
    result = evaluate_findings([finding], [risk], run_date=date(2026, 10, 18))
    assert (result.blocked, result.code) == (True, "CI-SEC-001")
    head = f"CI-SEC-001: {tool} finding X-1 (CRITICAL) has an accepted-risk entry"
    assert result.messages == [f"{head}, but {CRITICAL_RULE} — d"]


def test_an_entry_accepts_findings_up_to_its_own_severity_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # #3558: an entry records a decision about one severity. An advisory accepted as a Medium,
    # then re-scored High, needs a new decision, not that entry.
    doc = _pnpm_doc(VITEST)
    doc["advisories"][VITEST]["severity"] = "high"
    doc["metadata"]["vulnerabilities"] |= {"moderate": 0, "high": 1}
    report = _write_json(tmp_path, "npm-audit.json", doc)
    entry = {"id": "GHSA-82fw-gwwq-j7x9", "tool": "npm-audit", "severity": "MEDIUM"}
    entry |= {"reason": "test", "approver": "basiltt", "expires": "2099-01-01"}
    rc, out, err = _npm_gate(capsys, report, _write_yaml(tmp_path, {"entries": [entry]}))
    assert (rc, out) == (1, "")
    head = "CI-SEC-001: npm-audit finding GHSA-82fw-gwwq-j7x9 (HIGH) has an accepted-risk entry"
    assert err.startswith(f"{head} for MEDIUM only, so it needs a new decision — vitest@3.2.7: ")


def test_an_entry_still_accepts_a_finding_below_its_own_severity(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # #3558: up to, not only at. Bandit blocks from MEDIUM, and a HIGH entry still covers its
    # MEDIUM finding: a finding re-scored lower keeps the decision it already has.
    report = SARIF_FIXTURES / "bandit-1.9.4-finding.sarif"
    entry = {"id": "B307:finding/parse_expr.py:2", "tool": "bandit", "severity": "HIGH"}
    entry |= {"reason": "test", "approver": "basiltt", "expires": "2099-01-01"}
    argv = ["--tool", "bandit", "--report", str(report), "--run-date", "2026-10-18"]
    rc = main([*argv, "--accepted-risks", str(_write_yaml(tmp_path, {"entries": [entry]}))])
    out, err = capsys.readouterr()
    head = "accepted risk: bandit finding B307:finding/parse_expr.py:2 (MEDIUM)"
    assert (rc, err) == (0, "")
    assert out == f"{head} until 2099-01-01 - test\nsecurity_gate[bandit]: OK\n"


# npm 7+'s `npm audit --json`: nothing in CI or `make security` writes it any more.
NPM_V7 = {
    "auditReportVersion": 2,
    "vulnerabilities": {
        "braces": {
            "name": "braces",
            "severity": "high",
            "via": [
                {"source": 1098094, "url": "https://github.com/advisories/GHSA-vfj7-8cjw-p6xm"}
            ],
        }
    },
    "metadata": {"vulnerabilities": {"info": 0, "low": 0, "moderate": 0, "high": 1}},
}


@pytest.mark.parametrize(
    "doc",
    [
        pytest.param(NPM_V7, id="npm-audit-schema"),
        pytest.param({}, id="empty-object"),
        pytest.param([], id="array"),
        pytest.param(None, id="null"),
        pytest.param("advisories", id="string"),
        pytest.param({"error": {"code": "ERR_PNPM_AUDIT_BAD_RESPONSE"}}, id="error-object"),
        pytest.param({"advisories": {}}, id="no-metadata"),
        pytest.param({"metadata": _pnpm_doc()["metadata"]}, id="no-advisories"),
    ],
)
def test_unrecognised_npm_audit_document_raises_ci_sec_005(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], doc: object
) -> None:
    report = _write_json(tmp_path, "npm-audit.json", doc)
    with pytest.raises(SecurityGateError) as exc_info:
        parse_npm_audit(report)
    assert exc_info.value.code == "CI-SEC-005"
    rc, out, err = _npm_gate(capsys, report)
    assert (rc, out) == (1, "")
    assert err == (
        f"CI-SEC-005: npm-audit: {report} is not a `pnpm audit --json` report "
        "(an object with an 'advisories' object and a 'metadata' object)\n"
    )


@pytest.mark.parametrize("text", ["", "\n"])
def test_empty_npm_audit_report_raises_ci_sec_005(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str
) -> None:
    # pnpm 12.5.1 writes nothing to stdout when the registry is unreachable (fixtures README).
    report = tmp_path / "npm-audit.json"
    report.write_text(text, encoding="utf-8")
    rc, out, err = _npm_gate(capsys, report)
    assert (rc, out) == (1, "")
    assert err.startswith(f"CI-SEC-005: npm-audit: {report} is empty: pnpm audit wrote no report")


def test_npm_audit_report_that_is_not_json_raises_ci_sec_005(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = tmp_path / "npm-audit.json"
    report.write_text('{"advisories": {', encoding="utf-8")
    rc, out, err = _npm_gate(capsys, report)
    assert (rc, out) == (1, "")
    assert err.startswith(f"CI-SEC-005: npm-audit: {report} is not JSON: ")


def _advisory(doc: dict[str, Any]) -> dict[str, Any]:
    (advisory,) = doc["advisories"].values()
    result: dict[str, Any] = advisory
    return result


def _counts(doc: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = doc["metadata"]["vulnerabilities"]
    return result


COUNTS = "has no counts per severity in 'metadata.vulnerabilities'"
SEVERITY = "has no known severity (critical, high, moderate, low or info)"
GHSA = "has no GHSA id (github_advisory_id, or the last segment of url)"
FINDINGS = "has no findings (a non-empty list of objects with a version and a non-empty paths list)"
# Each edit breaks one key of a one-advisory report -> how the CI-SEC-005 message ends.
MISTYPED: dict[str, tuple[Callable[[dict[str, Any]], object], str]] = {
    "counts-missing": (lambda d: d["metadata"].pop("vulnerabilities"), COUNTS),
    "count-string": (lambda d: _counts(d).update(high="1"), COUNTS),
    "count-bool": (lambda d: _counts(d).update(high=True), COUNTS),
    "count-negative": (lambda d: _counts(d).update(low=-1), COUNTS),
    "count-unknown-severity": (lambda d: _counts(d).update(severe=0), COUNTS),
    "count-severity-missing": (lambda d: _counts(d).pop("info"), COUNTS),
    "advisory-not-object": (
        lambda d: d["advisories"].update({SOURCE_MAP_JS: []}),
        f"advisory {SOURCE_MAP_JS} is not an object",
    ),
    "severity-unknown": (lambda d: _advisory(d).update(severity="severe"), SEVERITY),
    "severity-missing": (lambda d: _advisory(d).pop("severity"), SEVERITY),
    "module-missing": (lambda d: _advisory(d).pop("module_name"), "has no module_name"),
    "module-empty": (lambda d: _advisory(d).update(module_name=""), "has no module_name"),
    "no-ghsa": (
        lambda d: _advisory(d).update(github_advisory_id=None, url="https://example.invalid/1"),
        GHSA,
    ),
    "ghsa-malformed": (lambda d: _advisory(d).update(github_advisory_id="GHSA-1", url=None), GHSA),
    "findings-missing": (lambda d: _advisory(d).pop("findings"), FINDINGS),
    "findings-empty": (lambda d: _advisory(d).update(findings=[]), FINDINGS),
    "finding-not-object": (lambda d: _advisory(d).update(findings=["1.2.1"]), FINDINGS),
    "version-missing": (lambda d: _advisory(d)["findings"][0].pop("version"), FINDINGS),
    "paths-not-list": (lambda d: _advisory(d)["findings"][0].update(paths="a>b"), FINDINGS),
    "paths-empty": (lambda d: _advisory(d)["findings"][0].update(paths=[]), FINDINGS),
    "path-not-string": (lambda d: _advisory(d)["findings"][0].update(paths=[1]), FINDINGS),
    "title-not-string": (lambda d: _advisory(d).update(title=7), "has no title"),
}


@pytest.mark.parametrize("edit", sorted(MISTYPED))
def test_pnpm_report_with_a_missing_or_mistyped_key_raises_ci_sec_005(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], edit: str
) -> None:
    doc = _pnpm_doc(SOURCE_MAP_JS)
    change, tail = MISTYPED[edit]
    change(doc)
    report = _write_json(tmp_path, "npm-audit.json", doc)
    if not tail.startswith(("advisory", COUNTS)):
        tail = f"advisory {SOURCE_MAP_JS} {tail}"
    assert _npm_gate(capsys, report) == (1, "", f"CI-SEC-005: npm-audit: {report} {tail}\n")


def test_pnpm_advisory_without_github_advisory_id_takes_the_ghsa_from_its_url(
    tmp_path: Path,
) -> None:
    doc = _pnpm_doc(BRACES)
    del _advisory(doc)["github_advisory_id"]
    report = _write_json(tmp_path, "npm-audit.json", doc)
    assert [f.finding_id for f in parse_npm_audit(report)] == ["GHSA-vfj7-8cjw-p6xm"]


@pytest.mark.parametrize("name", sorted(p.name for p in PNPM_FIXTURES.glob("*.json")))
def test_pnpm_audit_fixtures_keep_pnpms_own_formatting(name: str) -> None:
    # pnpm writes JSON.stringify(report, null, 2) and a newline; .prettierignore keeps it so.
    raw = (PNPM_FIXTURES / name).read_text(encoding="utf-8")
    assert raw == json.dumps(json.loads(raw), indent=2) + "\n"


# --------------------------------------------------------------------------
# #3540: a codeql entry keyed to a line must stay on the code it accepts. PR
# scans are diff-informed and never re-report an unchanged line, so an edit
# above an accepted line (login_service.py 59 -> 60, #2612) left its entry
# stale until a full scan (the merge queue's) blocked on the result.
# --------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parents[2]
_TOKEN_HASH = 'return hashlib.sha256(token.encode("utf-8")).hexdigest()'
# `rule:path` of every line-keyed codeql entry -> the code its line must still hold.
_CODEQL_LINE_PINS = {
    "py/weak-sensitive-data-hashing:services/api/candleviewer/auth/login_service.py": _TOKEN_HASH,
    "py/weak-sensitive-data-hashing:services/api/candleviewer/auth/mfa_service.py": _TOKEN_HASH,
    "py/clear-text-logging-sensitive-data:"
    "services/api/candleviewer/migrations/versions/0002_rbac_seed.py": (
        "print(message, file=sys.stdout)"
    ),
}
_MFA_TOKEN_ENTRY = (
    "py/weak-sensitive-data-hashing:services/api/candleviewer/auth/login_service.py:60"
)
_MFA_RULE, _MFA_PATH, _MFA_LINE = _MFA_TOKEN_ENTRY.rsplit(":", 2)
_MFA_TOKEN_RESULT = (_MFA_RULE, _MFA_PATH, int(_MFA_LINE))


def test_repo_register_codeql_line_entries_still_hold_the_code_they_accept() -> None:
    stale: list[str] = []
    keys: set[str] = set()
    for risk in load_accepted_risks(REGISTER):
        parts = risk.finding_id.rsplit(":", 2)
        if risk.tool != "codeql" or len(parts) != 3 or not parts[2].isdigit():
            continue
        rule, path, line = parts
        keys.add(f"{rule}:{path}")
        want = _CODEQL_LINE_PINS.get(f"{rule}:{path}")
        src = _ROOT / path
        lines = src.read_text(encoding="utf-8").splitlines() if src.is_file() else []
        n = int(line)
        held = lines[n - 1].strip() if 0 < n <= len(lines) else "<no such line>"
        if want is None:
            stale.append(f"{risk.finding_id}: add the code it accepts to _CODEQL_LINE_PINS")
        elif want not in held:
            stale.append(f"{risk.finding_id}: line {n} holds {held!r}, not {want!r}")
    hint = "re-key each entry to its code's line, and re-triage it if that code changed"
    assert not stale, f"{hint}: {'; '.join(stale)}"
    assert keys == set(_CODEQL_LINE_PINS)  # every pin names a live entry


_PRODUCT = _ROOT / "services/api/candleviewer"
_LOGIN_SERVICE = _PRODUCT / "auth/login_service.py"
_MFA_SERVICE = _PRODUCT / "auth/mfa_service.py"
# The hash helper on each weak-hashing entry's line -> the module that defines it.
_TOKEN_HASHERS = {"_hash_mfa_token": _LOGIN_SERVICE, "_hash_token": _MFA_SERVICE}


def _calls_of(tree: ast.Module, func: str) -> list[str]:
    """Every call of the module-level function `func` in `tree`, unparsed."""
    return [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == func
    ]


def _refs_of(tree: ast.Module, name: str) -> list[str]:
    """Every reference to `name` in the code of `tree`, unparsed: a name, an attribute, an
    import, or a string equal to it (as getattr takes). Prose that mentions it never counts."""
    return [
        ast.unparse(node)
        for node in ast.walk(tree)
        if (isinstance(node, ast.Name) and node.id == name)
        or (isinstance(node, ast.Attribute) and node.attr == name)
        or (isinstance(node, ast.alias) and node.name == name)
        or (isinstance(node, ast.Constant) and node.value == name)
    ]


def test_repo_register_mfa_token_hash_entries_still_hash_a_random_token() -> None:
    """The weak-hashing entries (login_service.py:60, mfa_service.py:68) are false positives
    only while the hashed value is the MFA challenge token and that token is 256 random bits.
    A result is keyed to its hashing line, so a new hashed value or token source would stay
    accepted there: pin both, so such a change fails here and the entries are re-triaged."""
    login = ast.parse(_LOGIN_SERVICE.read_text(encoding="utf-8"))
    factory = [
        ast.unparse(default)
        for node in ast.walk(login)
        if isinstance(node, ast.FunctionDef)
        for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults, strict=True)
        if arg.arg == "mfa_token_factory" and default is not None
    ]
    assert factory == ["lambda: secrets.token_urlsafe(32)"]  # 32 bytes: 256 random bits
    stores = [
        node
        for node in ast.walk(login)
        if isinstance(node, ast.Name) and node.id == "mfa_token" and isinstance(node.ctx, ast.Store)
    ]
    minted = [
        ast.unparse(node.value)
        for node in ast.walk(login)
        if isinstance(node, ast.Assign) and any(t in stores for t in node.targets)
    ]
    assert len(stores) == 1  # the token is bound once
    assert minted == ["self._mfa_token_factory()"]
    assert _calls_of(login, "_hash_mfa_token") == ["_hash_mfa_token(mfa_token)"]
    assert _refs_of(login, "_hash_mfa_token") == ["_hash_mfa_token"]  # that call only
    mfa = ast.parse(_MFA_SERVICE.read_text(encoding="utf-8"))
    assert _calls_of(mfa, "_hash_token") == ["_hash_token(mfa_token)"]  # the presented token
    assert _refs_of(mfa, "_hash_token") == ["_hash_token"]  # that call only


def test_repo_register_mfa_token_hash_helpers_are_not_reached_from_other_modules() -> None:
    """No other product module may override the token factory or reach a hash helper: one
    that imports a helper could hash another value on the accepted line, and that result
    would carry the accepted id. Tests are not product code and may import the helpers."""
    found: list[str] = []
    for path in sorted(_PRODUCT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(_ROOT)
        if path != _LOGIN_SERVICE and "mfa_token_factory" in text:
            found.append(f"{rel}: mfa_token_factory")
        named = [name for name, home in _TOKEN_HASHERS.items() if path != home and name in text]
        if named:
            tree = ast.parse(text)
            found.extend(f"{rel}: {ref}" for name in named for ref in _refs_of(tree, name))
    hint = "re-triage the weak-hashing entries (or give an unrelated helper another name)"
    assert not found, f"{hint}: {found}"


def _codeql_full_scan(results: list[tuple[str, str, int]]) -> dict[str, object]:
    """A CodeQL SARIF of these results, each rule scored HIGH (7.5) on its descriptor."""
    rules = [
        {
            "id": rule,
            "defaultConfiguration": {"level": "error"},
            "properties": {"security-severity": "7.5"},
        }
        for rule in sorted({rule for rule, _, _ in results})
    ]
    found = [
        {
            "ruleId": rule,
            "message": {"text": "synthetic result"},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": uri},
                        "region": {"startLine": line},
                    }
                }
            ],
        }
        for rule, uri, line in results
    ]
    run = {"tool": {"driver": {"name": "CodeQL", "rules": rules}}, "results": found}
    return {"version": "2.1.0", "runs": [run]}


def _real_codeql_gate(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    register: Path,
    results: list[tuple[str, str, int]],
    run_date: str = "2026-10-18",  # fixed, and before the entry expires: deterministic
) -> tuple[int, str]:
    """Run the gate's CLI on a full-scan SARIF of `results`; return its exit code and output."""
    report = _write_json(tmp_path, "python.sarif", _codeql_full_scan(results))
    argv = ["--tool", "codeql", "--report", str(report), "--accepted-risks", str(register)]
    rc = main([*argv, "--run-date", run_date])
    out = capsys.readouterr()
    return rc, out.out + out.err


def test_real_codeql_gate_mfa_token_hash_without_its_entry_blocks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = yaml.safe_load(REGISTER.read_text(encoding="utf-8"))
    rest = [e for e in doc["entries"] if e["id"] != _MFA_TOKEN_ENTRY]
    without = _write_yaml(tmp_path, {"entries": rest})
    rc, out = _real_codeql_gate(tmp_path, capsys, without, [_MFA_TOKEN_RESULT])
    assert rc == 1, out
    assert "security_gate[codeql]: BLOCKED (CI-SEC-001)" in out
    assert f"{_MFA_TOKEN_ENTRY} (HIGH) has no accepted-risk entry" in out


def test_real_codeql_gate_mfa_token_hash_with_its_entry_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, out = _real_codeql_gate(tmp_path, capsys, REGISTER, [_MFA_TOKEN_RESULT])
    assert rc == 0, out
    assert "security_gate[codeql]: OK" in out
    assert f"accepted risk: codeql finding {_MFA_TOKEN_ENTRY} (HIGH)" in out


@pytest.mark.parametrize(
    "other",
    [
        pytest.param((_MFA_RULE, _MFA_PATH, int(_MFA_LINE) + 1), id="same-rule-next-line"),
        pytest.param(
            ("py/clear-text-logging-sensitive-data", _MFA_PATH, int(_MFA_LINE)),
            id="other-high-same-line",
        ),
    ],
)
def test_real_codeql_gate_mfa_token_entry_other_result_still_blocks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], other: tuple[str, str, int]
) -> None:
    rc, out = _real_codeql_gate(tmp_path, capsys, REGISTER, [_MFA_TOKEN_RESULT, other])
    rule, path, line = other
    assert rc == 1, out
    assert "security_gate[codeql]: BLOCKED (CI-SEC-001)" in out
    assert f"{rule}:{path}:{line} (HIGH) has no accepted-risk entry" in out
    assert f"{_MFA_TOKEN_ENTRY} (HIGH) has no accepted-risk entry" not in out  # entry is exact


def test_real_codeql_gate_mfa_token_entry_on_its_expiry_blocks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    expires = {r.finding_id: r for r in load_accepted_risks(REGISTER)}[_MFA_TOKEN_ENTRY].expires
    run_date = expires.isoformat()
    rc, out = _real_codeql_gate(tmp_path, capsys, REGISTER, [_MFA_TOKEN_RESULT], run_date)
    assert rc == 1, out
    assert "security_gate[codeql]: BLOCKED (CI-SEC-004)" in out
    assert f"CI-SEC-004: accepted risk expired for {_MFA_TOKEN_ENTRY}" in out
