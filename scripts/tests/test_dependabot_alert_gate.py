"""#3558: C-9.1 #11's Dependabot alert gate, `security_gate.py --tool dependabot`, on recorded
`gh api --paginate --slurp` listings of the open alerts (scripts/tests/fixtures/dependabot-alerts/;
no network)."""

from __future__ import annotations

import json
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
    SecurityGateError,
    evaluate_findings,
    main,
    parse_dependabot_alerts,
)

REGISTER = Path(__file__).resolve().parents[2] / "security" / "accepted-risks.yaml"
ALERTS = Path(__file__).resolve().parent / "fixtures" / "dependabot-alerts"
TAURI = "GHSA-7gmj-67g7-phm9"
# gh-2.67.0-main.json (main at d61631fa6): one finding per alert, in the API's order.
VITEST = ("GHSA-82fw-gwwq-j7x9", "MEDIUM", "npm:vitest")
MAIN_ALERTS = [(TAURI, "MEDIUM", "rust:tauri"), *[VITEST] * 7]


def _write_json(tmp_path: Path, name: str, data: object) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _write_yaml(tmp_path: Path, data: object) -> Path:
    p = tmp_path / "accepted-risks.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def _alert_pages() -> list[list[dict[str, Any]]]:
    pages: list[list[dict[str, Any]]] = json.loads(
        (ALERTS / "gh-2.67.0-main.json").read_text(encoding="utf-8")
    )
    return pages


def _dependabot_gate(
    capsys: pytest.CaptureFixture[str], report: Path, risks: Path = REGISTER
) -> tuple[int, str, str]:
    argv = ["--tool", "dependabot", "--report", str(report), "--accepted-risks", str(risks)]
    rc = main([*argv, "--run-date", "2026-10-18"])
    out, err = capsys.readouterr()
    return rc, out, err


def test_recorded_alerts_on_main_give_one_finding_per_alert_on_any_page_split(
    tmp_path: Path,
) -> None:
    findings = parse_dependabot_alerts(ALERTS / "gh-2.67.0-main.json")
    assert [(f.finding_id, f.severity, f.package) for f in findings] == MAIN_ALERTS
    assert {f.tool for f in findings} == {"dependabot"}
    assert findings[0].detail == (
        "alert 55, rust:tauri in packages/chart-engine/bench/matrix/tauri/src-tauri/Cargo.toml: "
        "Tauri has an Origin Confusion Issue that Allows Remote Pages to Invoke Local-Only IPC "
        "Commands"
    )
    (alerts,) = _alert_pages()
    split = _write_json(tmp_path, "alerts.json", [alerts[:3], alerts[3:], []])
    assert parse_dependabot_alerts(split) == findings


@pytest.mark.parametrize("pages", [None, [[]]])
def test_medium_alerts_on_main_and_no_alerts_pass_the_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], pages: object
) -> None:
    report = ALERTS / "gh-2.67.0-main.json"
    if pages is not None:
        report = _write_json(tmp_path, "alerts.json", pages)
    assert _dependabot_gate(capsys, report) == (0, "security_gate[dependabot]: OK\n", "")


@pytest.mark.parametrize(
    ("severity", "tool", "expires", "verdict"),
    [
        ("high", None, None, "CI-SEC-001: dependabot finding GHSA-7gmj-67g7-phm9 (HIGH) has no "),
        ("high", "npm-audit", "2099-01-01", "accepted risk: dependabot finding GHSA-7gmj-67g7"),
        ("high", "dependabot", "2099-01-01", "accepted risk: dependabot finding GHSA-7gmj-67g7"),
        ("high", "dependabot", "2026-10-18", "CI-SEC-004: accepted risk expired for GHSA-7gmj"),
        ("critical", "dependabot", "2099-01-01", "CI-SEC-001: dependabot finding GHSA-7gmj-67g7"),
    ],
)
def test_high_alert_blocks_unless_an_unexpired_entry_for_its_ghsa_covers_it(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    severity: str,
    tool: str | None,
    expires: str | None,
    verdict: str,
) -> None:
    (alerts,) = _alert_pages()
    alerts[0]["security_advisory"]["severity"] = severity
    report = _write_json(tmp_path, "alerts.json", [alerts])
    entry = {"id": TAURI, "tool": tool, "severity": "HIGH", "expires": expires}
    entries = [] if tool is None else [entry | {"reason": "test", "approver": "basiltt"}]
    rc, out, err = _dependabot_gate(capsys, report, _write_yaml(tmp_path, {"entries": entries}))
    accepted = verdict.startswith("accepted risk")
    assert (rc, (out if accepted else err).startswith(verdict)) == (int(not accepted), True)
    if verdict.startswith("CI-SEC-001"):  # the finding names the alert, package and manifest
        assert " — alert 55, rust:tauri in packages/chart-engine/bench/matrix/tauri/" in err


def test_a_dependabot_entry_covers_no_other_tools_finding() -> None:
    # The rule runs one way: a finding pnpm reports still needs an entry of its own tool.
    risk = AcceptedRisk(TAURI, "dependabot", "HIGH", "why", "basiltt", date(2099, 1, 1))
    finding = Finding(tool="npm-audit", finding_id=TAURI, severity="HIGH", package="x")
    result = evaluate_findings([finding], [risk], run_date=date(2026, 10, 18))
    assert (result.blocked, result.code) == (True, "CI-SEC-001")


NOT_FOUND = (ALERTS / "gh-2.67.0-not-found.json").read_text(encoding="utf-8")
UNREADABLE = {
    "": "is empty: the alerts API call wrote nothing",
    "[[": "is not JSON: ",
    NOT_FOUND: f"is not a list of pages of alerts: {NOT_FOUND}",
    '{"message": "Resource not accessible by integration"}': "is not a list of pages of alerts: ",
    "[]": "is not a list of pages of alerts: []",
}


@pytest.mark.parametrize("body", sorted(UNREADABLE))
def test_alert_listing_the_gate_cannot_read_raises_ci_sec_005(tmp_path: Path, body: str) -> None:
    report = tmp_path / "alerts.json"
    report.write_text(body, encoding="utf-8")
    with pytest.raises(SecurityGateError) as exc_info:
        parse_dependabot_alerts(report)
    assert exc_info.value.code == "CI-SEC-005"
    assert exc_info.value.message.startswith(f"dependabot: {report} {UNREADABLE[body]}")


MALFORMED_ALERT: dict[str, tuple[Callable[[dict[str, Any]], object], str]] = {
    "dismissed": (lambda a: a.update(state="dismissed"), "alert 55 is 'dismissed': the step "),
    "no-number": (lambda a: a.update(number="55"), "has an alert without a number"),
    "severity": (lambda a: a["security_advisory"].update(severity="moderate"), "alert 55 has no "),
    "no-ghsa": (lambda a: a["security_advisory"].pop("ghsa_id"), "alert 55 has no GHSA id"),
    "no-manifest": (lambda a: a["dependency"].pop("manifest_path"), "alert 55 has no package "),
}


@pytest.mark.parametrize("edit", sorted(MALFORMED_ALERT))
def test_alert_that_is_not_open_or_lacks_a_field_raises_ci_sec_005(
    tmp_path: Path, edit: str
) -> None:
    (alerts,) = _alert_pages()
    change, says = MALFORMED_ALERT[edit]
    change(alerts[0])
    report = _write_json(tmp_path, "alerts.json", [alerts])
    with pytest.raises(SecurityGateError) as exc_info:
        parse_dependabot_alerts(report)
    assert (exc_info.value.code, exc_info.value.message.split(" ", 2)[2].startswith(says)) == (
        "CI-SEC-005",
        True,
    )


@pytest.mark.parametrize("name", sorted(p.name for p in ALERTS.glob("*.json")))
def test_dependabot_alert_fixtures_keep_ghs_own_formatting(name: str) -> None:
    # gh writes compact JSON with no final newline; .prettierignore keeps it so.
    raw = (ALERTS / name).read_text(encoding="utf-8")
    assert raw == json.dumps(json.loads(raw), separators=(",", ":"), ensure_ascii=False)
