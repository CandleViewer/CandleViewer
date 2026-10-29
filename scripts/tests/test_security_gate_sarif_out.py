"""The SARIF code scanning receives: the gate's copy, without what the gate cleared (#1882).

GitHub code scanning reads raw SARIF and ignores `suppressions`, so the `Semgrep OSS` check went
red on results the required gate had cleared: a justified in-source suppression (CI-SEC-006) or
an unexpired accepted-risk entry. `security_gate.py --sarif-out` writes the copy without them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.ci.security_gate import main, write_gate_sarif

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BANDIT = FIXTURES / "sarif" / "bandit-1.9.4-finding.sarif"
BANDIT_ID = "B307:finding/parse_expr.py:2"  # the recorded report's one MEDIUM finding
RULE = "cv-broad-except-on-ingest"
GOOD = f"# nosemgrep: {RULE} reason=fp owner=@basil review=2026-12-31"


def _result(rule: str, uri: str, line: int, **extra: Any) -> dict[str, Any]:
    location = {
        "physicalLocation": {"artifactLocation": {"uri": uri}, "region": {"startLine": line}}
    }
    return {
        "ruleId": rule,
        "level": "error",
        "message": {"text": f"{rule} violated"},
        "locations": [location],
        **extra,
    }


def _doc(*results: dict[str, Any]) -> dict[str, Any]:
    run = {"tool": {"driver": {"name": "semgrep"}}, "results": list(results)}
    return {"version": "2.1.0", "runs": [run]}


def _write(path: Path, data: object) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _risks(tmp_path: Path, *entries: dict[str, str]) -> Path:
    path = tmp_path / "accepted-risks.yaml"
    path.write_text(yaml.safe_dump({"entries": list(entries)}), encoding="utf-8")
    return path


def _bandit_risk(expires: str = "2026-12-31") -> dict[str, str]:
    return {
        "id": BANDIT_ID,
        "tool": "bandit",
        "severity": "MEDIUM",
        "reason": "test",
        "approver": "basiltt",
        "expires": expires,
        "ticket": "https://github.com/CandleViewer/CandleViewer/issues/1882",
    }


def _results(path: Path) -> list[dict[str, Any]]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    results: list[dict[str, Any]] = doc["runs"][0]["results"]
    return results


def _clean_semgrep_json(tmp_path: Path) -> Path:
    doc = json.loads((FIXTURES / "semgrep" / "semgrep-1.181.0.json").read_text(encoding="utf-8"))
    doc["errors"], doc["paths"]["skipped"] = [], []
    return _write(tmp_path / "semgrep.json", doc)


def test_write_gate_sarif_keeps_only_what_the_gate_did_not_clear(tmp_path: Path) -> None:
    suppressed = _result("rules.a", "a.py", 2, suppressions=[{"kind": "inSource"}])
    accepted, blocking = _result("rules.b", "b.py", 3), _result("rules.c", "c.py", 4)
    report = _write(tmp_path / "in.sarif", _doc(suppressed, accepted, blocking))
    kept = {(0, 1): "rules.b:b.py:3", (0, 2): "rules.c:c.py:4"}
    out = tmp_path / "out.sarif"
    dropped = write_gate_sarif(report, out, kept, {"rules.b:b.py:3"})
    assert _results(out) == [blocking]
    assert dropped == [
        "code-scanning copy: dropped rules.a at a.py:2 (justified in-source suppression)",
        "code-scanning copy: dropped rules.b at b.py:3 (accepted risk)",
    ]


def test_write_gate_sarif_keeps_the_rest_of_the_document(tmp_path: Path) -> None:
    doc = _doc(_result("rules.c", "c.py", 4))
    doc["runs"][0]["invocations"] = [{"executionSuccessful": True}]
    report = _write(tmp_path / "in.sarif", doc)
    out = tmp_path / "out.sarif"
    assert write_gate_sarif(report, out, {(0, 0): "rules.c:c.py:4"}, set()) == []
    assert json.loads(out.read_text(encoding="utf-8")) == doc


def test_bandit_copy_drops_a_finding_an_accepted_risk_clears(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "bandit.gate.sarif"
    argv = ["--tool", "bandit", "--report", str(BANDIT), "--sarif-out", str(out)]
    risks = _risks(tmp_path, _bandit_risk())
    rc = main([*argv, "--accepted-risks", str(risks), "--run-date", "2026-10-29"])
    printed = capsys.readouterr().out
    assert rc == 0 and _results(out) == []
    assert "code-scanning copy: dropped B307 at finding/parse_expr.py:2 (accepted risk)" in printed


def test_bandit_copy_keeps_a_finding_that_blocks_the_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # No entry, then an expired one: the gate blocks, and code scanning shows the same finding.
    for i, entries in enumerate(([], [_bandit_risk(expires="2026-10-29")])):
        out = tmp_path / f"bandit-{i}.gate.sarif"
        argv = ["--tool", "bandit", "--report", str(BANDIT), "--sarif-out", str(out)]
        rc = main(
            [*argv, "--accepted-risks", str(_risks(tmp_path, *entries)), "--run-date", "2026-10-29"]
        )
        capsys.readouterr()
        assert rc == 1 and _results(out) == _results(BANDIT)


def test_semgrep_copy_drops_a_justified_in_source_suppression(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # the gate reads the marker from the scanned file, cwd-relative
    (tmp_path / "a.py").write_text(f"{GOOD}\nx = 1\n", encoding="utf-8")
    hit = _result(f"rules.{RULE}", "a.py", 2, suppressions=[{"kind": "inSource"}])
    report = _write(tmp_path / "semgrep.sarif", _doc(hit))
    out = tmp_path / "semgrep.gate.sarif"
    argv = ["--tool", "semgrep", "--report", str(report), "--sarif-out", str(out)]
    argv += ["--semgrep-json", str(_clean_semgrep_json(tmp_path)), "--run-date", "2026-10-29"]
    rc = main([*argv, "--accepted-risks", str(_risks(tmp_path))])
    printed = capsys.readouterr().out
    assert rc == 0 and _results(out) == []
    assert f"dropped rules.{RULE} at a.py:2 (justified in-source suppression)" in printed


def test_semgrep_copy_keeps_an_unjustified_suppression(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.py").write_text("# nosemgrep\nx = 1\n", encoding="utf-8")  # CI-SEC-006
    hit = _result(f"rules.{RULE}", "a.py", 2, suppressions=[{"kind": "inSource"}])
    report = _write(tmp_path / "semgrep.sarif", _doc(hit))
    out = tmp_path / "semgrep.gate.sarif"
    argv = ["--tool", "semgrep", "--report", str(report), "--sarif-out", str(out)]
    argv += ["--semgrep-json", str(_clean_semgrep_json(tmp_path)), "--run-date", "2026-10-29"]
    rc = main([*argv, "--accepted-risks", str(_risks(tmp_path))])
    capsys.readouterr()
    assert rc == 1 and _results(out) == [hit]


def test_sarif_out_refuses_a_tool_it_does_not_serve(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "codeql.gate.sarif"
    report = FIXTURES / "sarif" / "codeql-2.27.2-clean.sarif"
    argv = ["--tool", "codeql", "--report", str(report), "--sarif-out", str(out)]
    rc = main([*argv, "--accepted-risks", str(_risks(tmp_path))])
    err = capsys.readouterr().err
    assert rc == 1 and not out.exists()
    assert err == "CI-SEC-005: --sarif-out is for semgrep and bandit, not codeql\n"
