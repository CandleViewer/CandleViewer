"""E12-X03: the market-data Semgrep rules and the ZAP baseline gate.

Each rule is proven on its positive (`# ruleid:`) and negative (`# ok:`) fixture lines in
`.semgrep/tests/<rule>.py` and must report zero findings on the production tree. Semgrep
tests skip when the binary is absent (neighbour convention: test_check_auth_semgrep.py).
No network: semgrep runs with --metrics=off against local files only.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.ci.check_semgrep_rule_tests import expected_lines  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "zap_baseline_gate", ROOT / "security" / "zap" / "baseline_gate.py"
)
assert _spec and _spec.loader
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)

E12_RULES = (
    "cv-bybit-category-required",
    "cv-no-float-prices",
    "cv-no-raw-sql-interpolation",
    "cv-unbounded-query-window",
    "cv-no-debug-probe-in-prod",
    "cv-untrusted-exchange-response",
    "cv-nosec-needs-reason-owner",
)
needs_semgrep = pytest.mark.skipif(not shutil.which("semgrep"), reason="semgrep not installed")


def _scan(rule: str, target: Path) -> list[dict[str, object]]:
    proc = subprocess.run(
        ["semgrep", "scan", "--metrics=off", "--quiet", "--json",
         "--config", str(ROOT / ".semgrep" / f"{rule}.yml"), str(target)],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )  # fmt: skip
    assert proc.returncode in (0, 1), proc.stderr
    data = json.loads(proc.stdout)
    assert not data["errors"], data["errors"]
    return list(data["results"])


@pytest.mark.parametrize("rule", E12_RULES)
def test_rule_metadata_names_sr_and_doc(rule: str) -> None:
    text = (ROOT / ".semgrep" / f"{rule}.yml").read_text(encoding="utf-8")
    assert f"id: {rule}" in text
    assert "sr: SR-" in text
    assert f"ci-gates-e12.md#{rule}" in text
    assert f"## {rule}" in (ROOT / "docs/plan/security/ci-gates-e12.md").read_text("utf-8")


@needs_semgrep
@pytest.mark.parametrize("rule", E12_RULES)
def test_rule_fires_on_positive_and_not_on_negative(rule: str) -> None:
    fixture = ROOT / ".semgrep" / "tests" / f"{rule}.py"
    must_fire, must_not = expected_lines(fixture, rule)
    assert must_fire and must_not, "rule needs both positive and negative fixture lines"
    hit = {int(r["start"]["line"]) for r in _scan(rule, fixture)}  # type: ignore[index]
    assert must_fire <= hit
    assert not (hit & must_not)


@needs_semgrep
@pytest.mark.parametrize("rule", E12_RULES)
def test_rule_is_clean_on_production_tree(rule: str) -> None:
    found = _scan(rule, ROOT / "services" / "api" / "candleviewer")
    assert found == [], [(r["path"], r["start"]["line"]) for r in found]  # type: ignore[index]


def _report(*alerts: tuple[str, int, str]) -> dict[str, object]:
    return {"site": [{"alerts": [
        {"pluginid": pid, "riskcode": str(risk), "name": "x",
         "instances": [{"uri": f"http://127.0.0.1:8000{path}?from=1", "method": "GET"}]}
        for pid, risk, path in alerts
    ]}]}  # fmt: skip


def test_zap_gate_new_medium_alert_fails() -> None:
    keys = gate.alert_keys(_report(("40018", 3, "/market/bars"), ("10049", 1, "/market/bars")))
    assert keys == {"40018 GET /market/bars": "x"}


def _high(pluginid: str, *, confidence: str, paths: tuple[str, ...] = ()) -> dict[str, object]:
    """A High alert at ZAP's `confidence`. An alertFilter `newRisk: "False Positive"` keeps the
    risk, sets the confidence to 0 and leaves no instance (#3991, dast-rules-nightly run 2)."""
    instances = [{"uri": f"http://127.0.0.1:8000{path}", "method": "GET"} for path in paths]
    return {"pluginid": pluginid, "riskcode": "3", "confidence": confidence, "name": pluginid,
            "instances": instances}  # fmt: skip


def test_zap_gate_alert_the_plan_marked_false_positive_does_not_count() -> None:
    alerts = [_high("6", confidence="0"), _high("40018", confidence="2", paths=("/rules",))]
    report: dict[str, object] = {"site": [{"alerts": alerts}]}
    assert gate.alert_keys(report) == {"40018 GET /rules": "40018"}


def test_zap_gate_a_low_confidence_alert_still_counts() -> None:
    """Only the filter's "False Positive" (0) is dropped: ZAP's Low (1) is a finding."""
    alerts = [_high("6", confidence="1", paths=("/rules/vocabulary",))]
    report: dict[str, object] = {"site": [{"alerts": alerts}]}
    assert gate.alert_keys(report) == {"6 GET /rules/vocabulary": "6"}


def test_zap_gate_names_each_alert_the_plan_waived(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A waiver is seen on every run: the gate passes, and names the alert it left out."""
    rep, base = tmp_path / "r.json", tmp_path / "b.json"
    rep.write_text(json.dumps({"site": [{"alerts": [_high("6", confidence="0")]}]}), "utf-8")
    base.write_text(json.dumps({"accepted": []}), encoding="utf-8")
    assert gate.main([str(rep), str(base), "--today", "2026-10-22"]) == 0
    out = capsys.readouterr().out
    assert "zap-baseline: waived by the plan's alertFilter (False Positive): 6 6" in out


def test_zap_gate_baselined_alert_passes_and_expired_entry_fails(tmp_path: Path) -> None:
    rep, base = tmp_path / "r.json", tmp_path / "b.json"
    rep.write_text(json.dumps(_report(("10202", 2, "/market/klines"))), encoding="utf-8")
    entry = {"key": "10202 GET /market/klines", "reason": "r", "owner": "@o", "review": ""}
    for review, code in (("2026-12-31", 0), ("2026-01-01", 1)):
        entry["review"] = review
        base.write_text(json.dumps({"accepted": [entry]}), encoding="utf-8")
        assert gate.main([str(rep), str(base), "--today", "2026-10-09"]) == code


def test_zap_gate_entry_without_owner_is_rejected() -> None:
    _, problems = gate.baseline_problems(
        {"accepted": [{"key": "k", "reason": "r", "review": "2026-12-31"}]}, date(2026, 10, 9)
    )
    assert problems and "owner" in problems[0]


def test_zap_gate_missing_report_site_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "r.json").write_text("{}", encoding="utf-8")
    (tmp_path / "b.json").write_text('{"accepted": []}', encoding="utf-8")
    assert gate.main([str(tmp_path / "r.json"), str(tmp_path / "b.json")]) == 2


def test_market_dast_workflow_is_nightly_only() -> None:
    import yaml

    wf = yaml.safe_load((ROOT / ".github/workflows/dast-market-nightly.yml").read_text("utf-8"))
    triggers = wf[True] if True in wf else wf["on"]  # PyYAML parses `on:` as True
    assert set(triggers) == {"schedule", "workflow_dispatch"}
