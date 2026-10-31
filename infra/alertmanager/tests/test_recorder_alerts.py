"""E16-T09 (#567): recorder alerts <-> runbook, promtool cases, declared series, app thresholds."""

from __future__ import annotations

import importlib.util
import math
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
API = ROOT / "services/api/candleviewer"
RUNBOOK = ROOT / "docs/ops/runbooks/recorder.md"
#: The ticket's recorder alerts; its DiskWarn / DiskCritical are the system DiskHigh / DiskCritical.
#: RecorderDown reads the ticket's synthetic `recorder_up`.
REQUIRED = {"RecorderSilentStop", "RecorderMessagesDropped", "RecorderSpilling"}
REQUIRED |= {"RecorderGapBurst", "RollOffWatermarkLag", "RetentionStale", "RecorderDown"}
#: Disk-budget sampling (#4581), the write gate (#567) and skipped seek anchors (#2223).
TRACKERS = {
    "RecorderDiskBudgetSampleStale": "#4581",
    "RecorderDiskPressureAutostop": "#4581",
    "RecorderWriteGateClosed": "#567",
    "RecorderAnchorSkipped": "#2223",
}
REQUIRED |= set(TRACKERS)


def _load(path: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(Path(path).stem, ROOT / path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rules(name: str = "recorder.yml") -> dict[str, dict[str, Any]]:
    doc = yaml.safe_load((ROOT / "infra/prometheus/alerts" / name).read_text(encoding="utf-8"))
    return {r["alert"]: r for g in doc["groups"] for r in g["rules"] if "alert" in r}


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_rules_runbook_link_gate_and_declared_series() -> None:
    rules = _rules()
    assert set(rules) == REQUIRED
    sibling = _load("infra/alertmanager/tests/test_ingestion_alerts.py")
    assert sibling.cross_check(list(rules.values()), _text(RUNBOOK)) == []
    assert _load("infra/alertmanager/check_alert_rules.py").check() == []
    sys.path.insert(0, str(ROOT / "infra/grafana"))
    lint = _load("infra/grafana/lint_dashboards.py")
    for name, rule in rules.items():
        assert lint.metrics_in(rule["expr"]) - {"unless"} <= lint.catalogue_names(), name


def test_tracker_annotations_name_the_tracker_only() -> None:
    rules = _rules()
    for name, rule in rules.items():
        assert rule["annotations"].get("tracker") == TRACKERS.get(name), name


def test_each_entry_has_three_checks_remediation_and_a_do_not() -> None:
    text = _text(RUNBOOK)
    for name in _rules():
        section = text.split(f"## {name}", 1)[1].split("\n## ", 1)[0]
        assert len(re.findall(r"^\d\. ", section, re.MULTILINE)) == 3, name
        assert "**Remediation.**" in section and "**Do not**" in section, name
    assert "(recorder-rolloff.md" in text and "(recorder-retention.md" in text


def test_every_rule_has_a_firing_and_a_silent_promtool_case() -> None:
    doc = yaml.safe_load(_text(ROOT / "infra/prometheus/tests/ingestion_alerts.test.yml"))
    assert "../alerts/recorder.yml" in doc["rule_files"]
    cases = [c for t in doc["tests"] for c in t["alert_rule_test"]]
    for name in REQUIRED:
        mine = [bool(c["exp_alerts"]) for c in cases if c["alertname"] == name]
        assert True in mine and False in mine, name


def test_thresholds_follow_the_application_defaults() -> None:
    """Watermark lag: each roll-off stream's hot window + 2 days. Disk: CV_DISK_WARN/HALT_PCT."""
    hot = dict(re.findall(r'"(\w+)": \((\d+), ', _text(API / "recorder/retention_defaults.py")))
    block = _text(API / "recorder/rolloff.py").split("ROLLOFF_STREAMS", 1)[1].split(")\n", 1)[0]
    want = {s.lower(): int(hot[s.lower()]) + 2 for s in re.findall(r"StreamKind\.(\w+)", block)}
    found = re.findall(r'stream=~?"([^"]+)"\}\) > (\d+)', _rules()["RollOffWatermarkLag"]["expr"])
    assert {s: int(n) for sel, n in found for s in sel.split("|")} == want
    pct = dict(
        re.findall(r"disk_(warn|halt)_pct: int = Field\(default=(\d+)", _text(API / "settings.py"))
    )
    high = _rules("system_ticket.yml")["DiskHigh"]["expr"]
    assert high.startswith(f"disk_used_ratio > {int(pct['warn']) / 100}")
    assert (
        _rules("system_page.yml")["DiskCritical"]["expr"]
        == f"disk_used_ratio > {int(pct['halt']) / 100}"
    )


def test_retention_stale_is_two_reaper_intervals_and_recorder_down_guards_the_exporter() -> None:
    """RetentionStale: 48 h = twice `RetentionConfig.interval_s`, over a window that outlasts it
    (a restart resets the gauge to 0). RecorderDown pages on 0 and on an absent exporter."""
    block = _text(API / "recorder/retention.py").split("class RetentionConfig", 1)[1]
    (product,) = re.findall(r"interval_s: float = ([\d. *]+)\n", block)
    interval = math.prod(float(factor) for factor in product.split("*"))
    rules = _rules()
    stale = rules["RetentionStale"]["expr"]
    assert re.search(r"\) > 0\)\s+> (\d+)$", stale)
    assert int(stale.rsplit("> ", 1)[1]) == 2 * interval
    assert "max_over_time(retention_last_success_timestamp[7d])" in stale
    down = rules["RecorderDown"]
    assert down["expr"] == "max by (env) (recorder_up) == 0 or absent(recorder_up)"
    assert (down["for"], down["labels"]["severity"]) == ("5m", "page")
