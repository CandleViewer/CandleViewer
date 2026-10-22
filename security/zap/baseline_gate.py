#!/usr/bin/env python3
"""E12-X03: fail a ZAP run on any High/Medium alert not in the committed baseline.

Key = `<pluginId> <METHOD> <path>` (query string dropped, so fuzzed parameter values do not
mint "new" alerts). An alert the plan's `alertFilter` marked "False Positive" (ZAP's confidence 0)
never counts: the plan's filter, a reviewed file, is its disposition (#3991), and each one is
named in the run's output, so a waiver is seen on every run. Baseline entries must carry
`reason`, `owner` and `review` (ISO date, not in the past); an expired entry no longer protects.
Stdlib only; no network.

Usage: baseline_gate.py <zap traditional-json report> <baseline.json> [--today YYYY-MM-DD]
Exit: 0 clean, 1 new medium+ alert or invalid baseline, 2 unreadable input.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

MEDIUM = 2  # ZAP's risk code for Medium: Medium and High fail the gate
FALSE_POSITIVE = 0  # ZAP's confidence for an alert a plan's alertFilter marked "False Positive"
UNSTATED_CONFIDENCE = 2  # an alert that states no confidence is read as ZAP's Medium: it counts


def alert_keys(report: dict[str, object]) -> dict[str, str]:
    """Medium+ alert keys -> alert name, from a ZAP traditional-json report."""
    keys: dict[str, str] = {}
    for site in report.get("site", []) or []:  # type: ignore[union-attr]  # report is untyped JSON
        for alert in site.get("alerts", []):
            if int(alert.get("riskcode", 0)) < MEDIUM:
                continue
            if int(alert.get("confidence", UNSTATED_CONFIDENCE)) == FALSE_POSITIVE:
                continue
            for inst in alert.get("instances", []) or [{"uri": "", "method": ""}]:
                path = urlsplit(inst.get("uri", "")).path
                key = f"{alert.get('pluginid', '?')} {inst.get('method', '').upper()} {path}"
                keys[key] = str(alert.get("name", ""))
    return keys


def waived(report: dict[str, Any]) -> list[str]:
    """`<pluginId> <name>` of each Medium+ alert the plan's `alertFilter` marked "False
    Positive": the alerts `alert_keys` leaves out."""
    names: list[str] = []
    for site in report.get("site", []) or []:
        for alert in site.get("alerts", []):
            confidence = int(alert.get("confidence", UNSTATED_CONFIDENCE))
            if int(alert.get("riskcode", 0)) >= MEDIUM and confidence == FALSE_POSITIVE:
                names.append(f"{alert.get('pluginid', '?')} {alert.get('name', '')}")
    return names


def baseline_problems(baseline: dict[str, object], today: date) -> tuple[set[str], list[str]]:
    accepted: set[str] = set()
    problems: list[str] = []
    for entry in baseline.get("accepted", []) or []:  # type: ignore[union-attr]  # untyped JSON
        key = entry.get("key", "")
        missing = [f for f in ("key", "reason", "owner", "review") if not entry.get(f)]
        if missing:
            problems.append(f"baseline entry {key!r} missing {', '.join(missing)}")
            continue
        if date.fromisoformat(entry["review"]) < today:
            problems.append(f"baseline entry {key!r} expired on {entry['review']}")
            continue
        accepted.add(key)
    return accepted, problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report", type=Path)
    ap.add_argument("baseline", type=Path)
    ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    a = ap.parse_args(argv)
    try:
        report = json.loads(a.report.read_text(encoding="utf-8"))
        baseline = json.loads(a.baseline.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"zap-baseline: unreadable input: {exc}", file=sys.stderr)
        return 2
    if "site" not in report:
        print("zap-baseline: report has no 'site' (scan did not run)", file=sys.stderr)
        return 2
    accepted, problems = baseline_problems(baseline, a.today)
    for name in waived(report):
        print(f"zap-baseline: waived by the plan's alertFilter (False Positive): {name}")
    new = {k: n for k, n in alert_keys(report).items() if k not in accepted}
    for k, n in sorted(new.items()):
        problems.append(f"NEW medium+ alert (triage SLA: ci-gates-e12.md#dast): {n} [{k}]")
    for p in problems:
        print(f"zap-baseline: {p}", file=sys.stderr)
    if not problems:
        print("zap-baseline: no new medium+ alerts above the baseline")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
