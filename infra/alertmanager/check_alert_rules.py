#!/usr/bin/env python3
"""E04-T05 CI gate: every alert rule has severity page|ticket (Watchdog excepted),
a component label and a runbook_url whose anchor resolves in docs/plan/07-release-and-prr.md
(or, for the E08-T06 ingestion set, in docs/ops/ingestion.md). The optional `resolves: window`
label (#2931) is allowed on pages only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
ALERT_DIR = ROOT / "infra" / "prometheus" / "alerts"
RUNBOOK = "docs/plan/07-release-and-prr.md"
#: Additional runbooks an alert may link to (E08-T06).
EXTRA_RUNBOOKS = ("docs/ops/ingestion.md", "docs/ops/runbooks/kek-custody.md")
SEVERITIES = {"page", "ticket"}
#: `resolves: window` marks an event-type page: it clears when its rate window moves on, not when
#: anyone acts, so Alertmanager sends no [RESOLVED] for it (receiver `page_event`, #2931). The
#: value set is closed: a typo would fall through to the generic page route and send one.
RESOLVES = ("window",)
EXEMPT = {"Watchdog"}


def anchors(text: str) -> set[str]:
    out: set[str] = set()
    for m in re.finditer(r'<a id="([^"]+)"', text):
        out.add(m.group(1))
    for m in re.finditer(r"^#{1,6}\s+(.*)$", text, re.MULTILINE):
        slug = re.sub(r"[^a-z0-9 -]", "", m.group(1).strip().lower()).replace(" ", "-")
        out.add(slug)
    return out


def check(alert_dir: Path = ALERT_DIR, runbook_text: str | None = None) -> list[str]:
    if runbook_text is None:
        runbook_text = (ROOT / RUNBOOK).read_text(encoding="utf-8")
    known_by = {RUNBOOK: anchors(runbook_text)}
    for extra in EXTRA_RUNBOOKS:
        f = ROOT / extra
        known_by[extra] = anchors(f.read_text(encoding="utf-8")) if f.exists() else set()
    errors: list[str] = []
    for f in sorted(alert_dir.glob("*.yml")):
        doc: dict[str, Any] = yaml.safe_load(f.read_text(encoding="utf-8"))
        for g in doc.get("groups", []):
            for r in g.get("rules", []):
                name = r.get("alert")
                if name is None:
                    continue
                labels = r.get("labels") or {}
                if name not in EXEMPT:
                    if labels.get("severity") not in SEVERITIES:
                        errors.append(f"{name}: severity must be page|ticket")
                    if not labels.get("component"):
                        errors.append(f"{name}: missing component label")
                if "resolves" in labels:
                    if labels["resolves"] not in RESOLVES:
                        allowed = " or ".join(repr(v) for v in RESOLVES)
                        errors.append(f"{name}: resolves label must be {allowed}")
                    if labels.get("severity") != "page":
                        errors.append(f"{name}: resolves label is only valid on a page")
                url = (r.get("annotations") or {}).get("runbook_url")
                if not url:
                    errors.append(f"{name}: missing annotations.runbook_url")
                    continue
                path, _, anchor = url.partition("#")
                if anchor not in known_by.get(path, set()):
                    errors.append(f"{name}: runbook_url anchor not found: {url}")
    return errors


def main() -> int:
    errs = check()
    for e in errs:
        print(f"ALERT-RULE-LINT: {e}", file=sys.stderr)
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main())
