#!/usr/bin/env python3
"""E47-Q04: the screen inventory behind gate A11Y-G008 and the pa11y / Lighthouse plans.

Inputs (read only, stdlib only):
  docs/plan/a11y/findings.json    one row per SCR-001..159 with its `coverage`
  apps/web/src/routes/manifest.ts route id -> path / access / owner
  apps/web/e2e/a11y/screens.ts    the ids the per-PR axe collector scans

Row status (BQ-03):
  mounted   coverage `covered` or `partial`: it renders at the audited sha
  pending   coverage `unreachable: ...`: counted, never failed, named by its owning ticket
  reserved  coverage `reserved: ...`: no screen exists; excluded from the counts

A mounted row reached through a route (`(R-001 -> LoginScreen)` in its coverageReason) must appear in
the axe report: in tier `pr` when the per-PR collector scans that route, in tier `full` (nightly,
A11Y_SWEEP=full) always. A mounted row with no route of its own (a host or overlay) is counted as
`hosted`: it is scanned inside the screen that mounts it.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINDINGS = ROOT / "docs/plan/a11y/findings.json"
MANIFEST = ROOT / "apps/web/src/routes/manifest.ts"
SCREENS_TS = ROOT / "apps/web/e2e/a11y/screens.ts"

MOUNTED_COVERAGE = ("covered", "partial")
ROUTE_MOUNT_RE = re.compile(r"\b(R-\d{3})\s*->")
MANIFEST_RE = re.compile(
    r'id:\s*"(R-\d{3})",\s*path:\s*"([^"]+)",\s*access:\s*(\w+|\{[^}]*\}),\s*owner:\s*(null|"[^"]*")'
)

# BQ-08: the ticket's eight Lighthouse screens (route = where each is reached), plus the two that the
# gate has always scored. A panel in the terminal is audited through the route that hosts it.
LIGHTHOUSE_SCREENS: tuple[tuple[str, str], ...] = (
    ("SCR-001", "R-001"),
    ("SCR-155", "R-901"),
    ("SCR-030", "R-100"),  # chart workspace
    ("SCR-060", "R-100"),  # order ticket
    ("SCR-063", "R-130"),  # positions
    ("SCR-121", "R-301"),  # admin users
    ("SCR-093", "R-180"),  # journal
    ("SCR-100", "R-110"),  # watchlist
    ("SCR-110", "R-200"),  # settings
    ("SCR-090", "R-190"),  # alerts
)


class InventoryError(Exception):
    """An input could not be read or parsed (reported as A11Y-INFRA by gates.py)."""


@dataclass(frozen=True)
class Route:
    id: str
    path: str
    access: str
    owner: str | None

    @property
    def public(self) -> bool:
        return self.access == "PUBLIC"

    @property
    def visit_path(self) -> str:
        return re.sub(r":[A-Za-z]+", "x", self.path)


@dataclass(frozen=True)
class Row:
    id: str
    name: str
    status: str  # mounted | pending | reserved
    ticket: str
    routes: tuple[str, ...] = field(default_factory=tuple)


def load_manifest(path: Path = MANIFEST) -> dict[str, Route]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InventoryError(f"A11Y-INFRA cannot read {path}: {exc}") from exc
    routes = {
        m[1]: Route(m[1], m[2], m[3], None if m[4] == "null" else m[4].strip('"'))
        for m in MANIFEST_RE.finditer(text)
    }
    if not routes:
        raise InventoryError(f"A11Y-INFRA no route entries parsed from {path}")
    return routes


def pr_scan_ids(path: Path = SCREENS_TS) -> frozenset[str]:
    """Route ids the per-PR axe collector scans: PR_IDS plus the SIGNED_IN map's keys."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InventoryError(f"A11Y-INFRA cannot read {path}: {exc}") from exc
    pr = re.search(r"PR_IDS[^=]*=\s*new Set\(\[([^\]]*)\]", text)
    signed = re.search(r"SIGNED_IN\s*=\s*new Map[^=]*?\(\[(.*?)\]\);", text, re.S)
    if not pr or not signed:
        raise InventoryError(f"A11Y-INFRA cannot find PR_IDS / SIGNED_IN in {path}")
    return frozenset(re.findall(r"R-\d{3}", pr.group(1)) + re.findall(r'\["(R-\d{3})"', signed.group(1)))


def load_rows(findings: Path = FINDINGS, manifest: dict[str, Route] | None = None) -> list[Row]:
    manifest = manifest if manifest is not None else load_manifest()
    try:
        data = json.loads(findings.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InventoryError(f"A11Y-INFRA cannot read {findings}: {exc}") from exc
    rows: list[Row] = []
    for s in data.get("screens", []):
        cov = str(s.get("coverage", ""))
        if cov.startswith("reserved"):
            status = "reserved"
        elif cov in MOUNTED_COVERAGE:
            status = "mounted"
        else:
            status = "pending"
        routes = tuple(
            dict.fromkeys(r for r in ROUTE_MOUNT_RE.findall(str(s.get("coverageReason", ""))) if r in manifest)
        )
        rows.append(Row(str(s["id"]), str(s.get("name", "")), status, str(s.get("owningTicket", "")), routes))
    if not rows:
        raise InventoryError(f"A11Y-INFRA {findings} has no screen rows")
    return rows


def summary(rows: list[Row]) -> dict[str, int]:
    counted = [r for r in rows if r.status != "reserved"]
    return {
        "rows": len(counted),
        "mounted": sum(r.status == "mounted" for r in counted),
        "pending": sum(r.status == "pending" for r in counted),
        "reserved": len(rows) - len(counted),
    }


def check_inventory(
    report: dict, rows: list[Row], pr_scanned: frozenset[str], tier: str = "pr"
) -> list[str]:
    """A11Y-G008: every mounted, routed row must be in the axe report (see module doc)."""
    screens = report.get("screens")
    if not isinstance(screens, dict):
        raise InventoryError("A11Y-INFRA axe report has no 'screens' object")
    msgs: list[str] = []
    for r in rows:
        if r.status != "mounted" or not r.routes:
            continue
        if tier == "pr" and not any(rt in pr_scanned for rt in r.routes):
            continue  # nightly-only: its route is not in the per-PR set
        if r.id in screens or any(rt in screens for rt in r.routes):
            continue
        msgs.append(
            f"A11Y-G008 screen={r.id} ({r.name}) is mounted at {', '.join(r.routes)} "
            f"but absent from the axe report (tier={tier}); add it to apps/web/e2e/a11y/screens.ts"
        )
    return msgs


def describe(rows: list[Row], pr_scanned: frozenset[str], tier: str) -> str:
    c = summary(rows)
    routed = [r for r in rows if r.status == "mounted" and r.routes]
    required = [r for r in routed if tier == "full" or any(rt in pr_scanned for rt in r.routes)]
    return (
        f"A11Y-G008 inventory: {c['rows']} screens, {c['mounted']} mounted "
        f"({len(required)} required in tier {tier}, {len(routed) - len(required)} nightly-only, "
        f"{c['mounted'] - len(routed)} hosted), {c['pending']} pending "
        f"({len({r.ticket for r in rows if r.status == 'pending'})} tickets), {c['reserved']} reserved"
    )


def pa11y_config(rows: list[Row], manifest: dict[str, Route], base_url: str, chrome: str | None) -> dict:
    """pa11y-ci config driven from the inventory: the mounted, public routes.

    A guarded route visited bare is bounced to /login (#3470), so it is left to axe's session entry.
    """
    seen: dict[str, str] = {}
    for r in rows:
        if r.status != "mounted":
            continue
        for rt in r.routes:
            route = manifest[rt]
            if route.public:
                seen.setdefault(rt, route.visit_path)
    launch: dict = {"args": ["--no-sandbox", "--disable-dev-shm-usage"]}
    if chrome:
        launch["executablePath"] = chrome
    return {
        "defaults": {
            "standard": "WCAG2AA",
            "timeout": 30000,
            "wait": 500,
            "chromeLaunchConfig": launch,
            "ignore": [],
        },
        "urls": [{"url": f"{base_url.rstrip('/')}{p}", "_route": rt} for rt, p in sorted(seen.items())],
    }


def lighthouse_plan(rows: list[Row], manifest: dict[str, Route]) -> dict:
    """Per Lighthouse screen: `run` (mounted and public) or `pending <why>` (BQ-08)."""
    by_id = {r.id: r for r in rows}
    plan = []
    for scr, rt in LIGHTHOUSE_SCREENS:
        row, route = by_id.get(scr), manifest.get(rt)
        if row is None or route is None:
            raise InventoryError(f"A11Y-INFRA Lighthouse screen {scr}/{rt} is not in the inventory")
        entry = {"screen": scr, "route": rt, "path": route.visit_path}
        if row.status != "mounted":
            entry["pending"] = f"pending {row.ticket}"
        elif not route.public:
            entry["pending"] = "pending session harness (guarded route)"
        plan.append(entry)
    return {"screens": plan}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    manifest = load_manifest()
    rows = load_rows(manifest=manifest)
    if argv[:1] == ["lighthouse-plan"]:
        print(json.dumps(lighthouse_plan(rows, manifest), indent=2))
        return 0
    print(json.dumps(summary(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
