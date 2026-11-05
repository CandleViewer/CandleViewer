"""The alert chain of the admin chaos scenarios (E42-Q03, #1216; plan section 7).

[BQ-6] The ticket's names are stale: the series are `audit_chain_verification_failures_total`,
`cv_audit_chain_verified_state` and `cv_audit_break_halt_state`; the pages are
`AuditChainVerificationFailed` and `AuditBreakHaltEngaged` (`infra/prometheus/alerts/
system_page.yml`); the backup age feeds `BackupLastSuccessStale`, a ticket (`system_ticket.yml`).

A scenario scrapes the process's exposition (`scrape`), then writes the values it saw as a
`promtool test rules` suite over the real rule files (`write_suite`): each case expects the alert
with the rule's own labels and annotations, so the suite fails only when the scraped values do
not fire the rule. The nightly workflow runs promtool over what was written (the directory in
`OUT_ENV`); a local run writes under the test's `tmp_path` and promtool is not run.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import yaml
from prometheus_client import REGISTRY, CollectorRegistry, generate_latest
from prometheus_client.parser import text_string_to_metric_families

ROOT: Final = Path(__file__).resolve().parents[5]
ALERTS: Final = ROOT / "infra" / "prometheus" / "alerts"
RULE_FILES: Final = ("system_page.yml", "system_ticket.yml")
#: Where the nightly mounts `infra/prometheus` in the promtool container.
MOUNTED: Final = "/p/alerts"
OUT_ENV: Final = "CV_ADMIN_CHAOS_ALERTS_DIR"


def scrape(name: str, registry: CollectorRegistry = REGISTRY, **labels: str) -> float | None:
    """The sample `name` with at least `labels`, read from the text exposition as a scrape reads
    it; `None` when the process exports none."""
    text = generate_latest(registry).decode("utf-8")
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            if sample.name == name and labels.items() <= sample.labels.items():
                return float(sample.value)
    return None


def rule(alertname: str) -> dict[str, Any]:
    """The alerting rule `alertname` of the rule files the suite loads."""
    for name in RULE_FILES:
        doc = yaml.safe_load((ALERTS / name).read_text(encoding="utf-8"))
        for group in doc["groups"]:
            for found in group["rules"]:
                if found.get("alert") == alertname:
                    return dict(found)
    raise KeyError(alertname)


def series(name: str, labels: Mapping[str, str]) -> str:
    inner = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return f"{name}{{{inner}}}" if inner else name


def case(
    alertname: str,
    inputs: Mapping[str, str],
    *,
    eval_time: str,
    labels: Mapping[str, str],
) -> dict[str, Any]:
    """One promtool test: `inputs` (series -> values) must fire `alertname` at `eval_time` with
    the rule's labels plus `labels` (the series labels the expression keeps)."""
    found = rule(alertname)
    annotations = {str(k): str(v) for k, v in (found.get("annotations") or {}).items()}
    if any("{{" in text for text in annotations.values()):
        raise ValueError(f"{alertname}: a templated annotation needs its expansion here")
    expected = {str(k): str(v) for k, v in (found.get("labels") or {}).items()} | dict(labels)
    return {
        "interval": "1m",
        "input_series": [{"series": s, "values": v} for s, v in inputs.items()],
        "alert_rule_test": [
            {
                "eval_time": eval_time,
                "alertname": alertname,
                "exp_alerts": [{"exp_labels": expected, "exp_annotations": annotations}],
            }
        ],
    }


def out_dir(fallback: Path) -> Path:
    """The nightly's directory (`OUT_ENV`), else `fallback`."""
    chosen = os.environ.get(OUT_ENV)
    path = Path(chosen) if chosen else fallback
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_suite(name: str, cases: list[dict[str, Any]], out: Path) -> Path:
    doc = {
        "rule_files": [f"{MOUNTED}/{f}" for f in RULE_FILES],
        "evaluation_interval": "1m",
        "tests": cases,
    }
    path = out / f"{name}.test.yml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path
