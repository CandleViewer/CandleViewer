"""Unit tests for tools/ci/security_gate.py (E03-T07).

Exercises the five Gherkin acceptance scenarios plus the underlying
severity-normalisation / accepted-risk-expiry logic, over fixture SARIF/JSON
outputs synthesised in-test (no network, no real scanner invocation).
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

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


def test_npm_audit_high_severity_blocks(tmp_path: Path) -> None:
    report = _write_json(
        tmp_path,
        "npm-audit.json",
        {"vulnerabilities": {"left-pad": {"severity": "high", "via": [{"source": "GHSA-zzzz"}]}}},
    )
    findings = parse_npm_audit(report)
    result = evaluate_findings(findings, risks=[], run_date=date(2026, 1, 1))
    assert result.blocked


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
    rc = main(["--tool", tool, "--report", str(report), "--accepted-risks", str(risks)])
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


def test_missing_accepted_risks_file_raises_ci_sec_005(tmp_path: Path) -> None:
    with pytest.raises(SecurityGateError) as exc_info:
        load_accepted_risks(tmp_path / "does-not-exist.yaml")
    assert exc_info.value.code == "CI-SEC-005"


def test_malformed_accepted_risks_entry_raises_ci_sec_005(tmp_path: Path) -> None:
    risks_path = _write_yaml(tmp_path, {"entries": [{"id": "x", "tool": "bandit"}]})
    with pytest.raises(SecurityGateError) as exc_info:
        load_accepted_risks(risks_path)
    assert exc_info.value.code == "CI-SEC-005"


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


def test_npm_audit_ghsa_url_becomes_finding_id(tmp_path: Path) -> None:
    report = _write_json(
        tmp_path,
        "npm-audit.json",
        {
            "vulnerabilities": {
                "braces": {
                    "severity": "high",
                    "via": [
                        {
                            "source": 1098094,
                            "url": "https://github.com/advisories/GHSA-vfj7-8cjw-p6xm",
                        }
                    ],
                }
            }
        },
    )
    assert parse_npm_audit(report)[0].finding_id == "GHSA-vfj7-8cjw-p6xm"


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
