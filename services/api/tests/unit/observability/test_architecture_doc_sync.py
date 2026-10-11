"""E04-T07: the 20-architecture.md section 12.1 table matches the metric catalogue,
and every alert runbook section carries the seven required elements."""

from __future__ import annotations

import re
from pathlib import Path

from candleviewer.observability.metrics_catalogue import CATALOGUE

ROOT = Path(__file__).resolve().parents[5]
PLAN = ROOT / "docs" / "plan"


def test_architecture_metric_table_lists_every_catalogue_metric() -> None:
    text = (PLAN / "20-architecture.md").read_text(encoding="utf-8")
    section = text[text.index("### 12.1") : text.index("### 12.2")]
    documented = set(re.findall(r"`([a-z][a-z0-9_:]+)(?:\{[^`]*\})?`", section))
    missing = sorted({m.name for m in CATALOGUE} - documented)
    assert missing == []


def test_every_alert_runbook_has_the_seven_elements() -> None:
    text = (PLAN / "07-release-and-prr.md").read_text(encoding="utf-8")
    start = text.index("## 9. Alert runbooks")
    sections = re.split(r'(?=<a id=")', text[start:])[1:]
    assert len(sections) >= 40
    required = (
        "1. What fired",
        "2. User impact",
        "3. What is still safe",
        "4. First three diagnostic commands",
        "5. Remediation",
        "6. Escalation",
        "7. Verify recovery",
    )
    bad = [s.splitlines()[0] for s in sections if any(r not in s for r in required)]
    assert bad == []


def test_runbooks_embed_no_credentials() -> None:
    text = (PLAN / "07-release-and-prr.md").read_text(encoding="utf-8")
    assert not re.search(r"(gho_|ghp_|sk-[A-Za-z0-9]{10}|PRIVATE KEY)", text)


def _section(text: str, start: str, end: str) -> str:
    return text[text.index(start) : text.index(end)]


def test_architecture_metric_labels_match_catalogue() -> None:
    text = (PLAN / "20-architecture.md").read_text(encoding="utf-8")
    section = _section(text, "### 12.1", "### 12.2")
    mismatched: list[str] = []
    for spec in CATALOGUE:
        found = re.findall(rf"`{re.escape(spec.name)}\{{([^}}]*)\}}`", section)
        expected = {label for label in spec.labels if label != "env"}
        for raw in found:
            documented = {x.strip() for x in raw.split(",")} - {"env"}
            if documented != expected:
                mismatched.append(f"{spec.name}: doc={sorted(documented)} code={sorted(expected)}")
    assert mismatched == []


def test_alert_rules_resolve_to_runbook_anchors_and_policy_severities() -> None:
    prr = (PLAN / "07-release-and-prr.md").read_text(encoding="utf-8")
    anchors = set(re.findall(r'<a id="([^"]+)"', prr))
    # E08-T06: the ingestion alert set links docs/ops/ingestion.md (20-architecture §12.5).
    ops = (ROOT / "docs" / "ops" / "ingestion.md").read_text(encoding="utf-8")
    anchors |= set(re.findall(r'<a id="([^"]+)"', ops))
    # E27-T02: KekUnavailable links the KEK custody runbook.
    kek = (ROOT / "docs" / "ops" / "runbooks" / "kek-custody.md").read_text(encoding="utf-8")
    anchors |= set(re.findall(r'<a id="([^"]+)"', kek))
    rules = list((ROOT / "infra" / "prometheus" / "alerts").glob("*.y*ml"))
    assert rules, "no alert rule files found"
    bad: list[str] = []
    for f in rules:
        body = f.read_text(encoding="utf-8")
        for url in re.findall(r"runbook_url:\s*\S*#([\w-]+)", body):
            if url not in anchors:
                bad.append(f"{f.name}: {url}")
        for sev in re.findall(r"severity:\s*(\w+)", body):
            if sev not in {"page", "ticket", "none"}:
                bad.append(f"{f.name}: severity {sev}")
    assert bad == []


def test_architecture_log_fields_and_dashboards_documented() -> None:
    text = (PLAN / "20-architecture.md").read_text(encoding="utf-8")
    logging_sec = _section(text, "### 12.2", "### 12.3")
    for field in ("ts", "level", "logger", "event", "env"):
        assert f"`{field}`" in logging_sec
    dash_sec = _section(text, "### 12.4", "### 12.5")
    dashboards = list((ROOT / "infra" / "grafana" / "dashboards").glob("*.json"))
    assert len(re.findall(r"^\d\. \*\*", dash_sec, re.M)) == len(dashboards) or dashboards == []
