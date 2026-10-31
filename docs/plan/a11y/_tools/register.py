#!/usr/bin/env python3
"""E47-T01 (#1323): generate the per-screen conformance matrix from the a11y register.

Reads ``docs/plan/a11y/findings.json`` (schema v2, ``finding-record.schema.json``), checks its
structure lightly (full schema validation stays in ``scripts/tests/test_a11y_finding_schema.py``) and
writes ``docs/plan/a11y/conformance-matrix.md``: one row per SCR id, one column per evidence type.

Usage::

    python3 docs/plan/a11y/_tools/register.py            # regenerate the matrix
    python3 docs/plan/a11y/_tools/register.py --check    # exit 1 if the committed matrix is stale
    python3 docs/plan/a11y/_tools/register.py --counts   # print the totals

Stdlib only. ``--check`` compares modulo Markdown table padding (cells are stripped and delimiter
rows normalised), so a Prettier reflow of the committed file by lint-staged is not "stale".
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

A11Y = Path(__file__).resolve().parents[1]
REGISTER = A11Y / "findings.json"
MATRIX = A11Y / "conformance-matrix.md"

SCR_IDS = [f"SCR-{n:03d}" for n in range(1, 160)]
CRITERIA = ("2.4.11", "2.5.7", "2.5.8", "3.2.6", "3.3.7", "3.3.8")
COVERAGE = (
    "covered",
    "partial",
    "unreachable: not built",
    "unreachable: built, not mounted",
    "unreachable: needs a state the harness cannot induce",
    "reserved: no screen",
)
REACHABLE = ("covered", "partial")
LEVELS = ("A", "AA")
SEVERITIES = ("blocker", "serious", "moderate", "minor")
PRIORITIES = ("P0", "P1", "P2", "P3")
OPEN_STATUSES = ("open", "in-progress")
# 14-screens-catalogue.md §0.2 ID bands (first id, last id, area).
BANDS = (
    (1, 19, "Auth, app shell, global chrome, onboarding"),
    (20, 29, "Workspaces, dockable panel system, layouts"),
    (30, 49, "Charting"),
    (50, 59, "Order flow"),
    (60, 79, "Trading"),
    (80, 89, "Rule engine"),
    (90, 99, "Alerts, journal, analytics, replay"),
    (100, 109, "Watchlist, symbol search, symbol info"),
    (110, 119, "Settings (user-scoped)"),
    (120, 149, "Admin (owner-only)"),
    (150, 159, "Global system states"),
)
SCREEN_KEYS = ("id", "name", "coverage", "owningTicket", "states", "evidence", "noFindings")
EVIDENCE_KEYS = ("automated", "keyboard", "deep", "sr")
FINDING_KEYS = ("id", "screenId", "level", "severity", "owningTicket", "status")


class RegisterError(Exception):
    """The register is structurally unusable for the matrix."""


def load(path: Path = REGISTER) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegisterError(f"cannot read {path.name}: {exc}") from exc
    if not isinstance(doc, dict):
        raise RegisterError("register root is not an object")
    return doc


def validate(doc: dict[str, Any]) -> list[str]:
    """Lightweight structural checks the generator relies on; returns the problems found."""
    errors: list[str] = []
    if doc.get("schemaVersion") != 2:
        errors.append("schemaVersion must be 2")
    sha = doc.get("auditedSha")
    if not (isinstance(sha, str) and len(sha) == 40):
        errors.append("auditedSha must be a 40-character sha")
    for key in ("screens", "findings", "patterns"):
        if not isinstance(doc.get(key), list):
            errors.append(f"{key} must be a list")
    if errors:
        return errors
    ids: list[str] = []
    for row in doc["screens"]:
        rid = row.get("id", "?") if isinstance(row, dict) else "?"
        if not isinstance(row, dict):
            errors.append("screen row is not an object")
            continue
        missing = [k for k in SCREEN_KEYS if k not in row]
        if missing:
            errors.append(f"{rid}: missing {', '.join(missing)}")
            continue
        ids.append(row["id"])
        if row["coverage"] not in COVERAGE:
            errors.append(f"{rid}: unknown coverage {row['coverage']!r}")
        ev = row["evidence"]
        if not isinstance(ev, dict) or any(k not in ev for k in EVIDENCE_KEYS):
            errors.append(f"{rid}: evidence needs {', '.join(EVIDENCE_KEYS)}")
        wcag = row.get("wcag22")
        if wcag is not None and (not isinstance(wcag, dict) or set(wcag) != set(CRITERIA)):
            errors.append(f"{rid}: wcag22 needs exactly {', '.join(CRITERIA)}")
    if sorted(ids) != SCR_IDS or len(ids) != len(set(ids)):
        dup = sorted(k for k, v in Counter(ids).items() if v > 1)
        gone = sorted(set(SCR_IDS) - set(ids))
        errors.append(
            f"screens must hold SCR-001..159 once each (duplicates {dup}, missing {gone})"
        )
    fids: list[str] = []
    for f in doc["findings"]:
        if not isinstance(f, dict) or any(k not in f for k in FINDING_KEYS):
            errors.append(
                f"finding {f.get('id', '?') if isinstance(f, dict) else '?'}: missing keys"
            )
            continue
        fids.append(f["id"])
        for scr in [f["screenId"], *f.get("alsoOn", [])]:
            if scr not in SCR_IDS:
                errors.append(f"{f['id']}: unknown screen {scr}")
    if len(fids) != len(set(fids)):
        errors.append("finding ids are not unique")
    pids = [p.get("id") for p in doc["patterns"] if isinstance(p, dict)]
    if len(pids) != len(set(pids)):
        errors.append("pattern ids are not unique")
    return errors


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def table(header: list[str], rows: list[list[str]]) -> list[str]:
    """A Markdown table padded the way Prettier pads it, so a lint-staged reflow is a no-op."""
    body = [[_cell(x) for x in r] for r in [header, *rows]]
    widths = [max(3, *(len(r[i]) for r in body)) for i in range(len(header))]
    out = ["| " + " | ".join(x.ljust(w) for x, w in zip(body[0], widths, strict=True)) + " |"]
    out.append("| " + " | ".join("-" * w for w in widths) + " |")
    for r in body[1:]:
        out.append("| " + " | ".join(x.ljust(w) for x, w in zip(r, widths, strict=True)) + " |")
    return out


def _short(verdict: str | None) -> str:
    """A compact matrix token for a verdict string (the register keeps the reason)."""
    if not verdict:
        return "not run"
    if verdict.startswith("pass (exception"):
        return "pass (exception)"
    for token in ("pass", "fail", "n/a", "unreachable", "not run", "deferred"):
        if verdict.startswith(token):
            return token
    return verdict


def _automated(ev: dict[str, Any]) -> str:
    """The axe cell; a pass with unresolved colour-contrast incompletes says so (record §3)."""
    token = _short(ev.get("verdict"))
    note = ev.get("note", "")
    if token == "pass" and "not resolved yet" in note:
        match = re.search(r"incomplete nodes per theme: dark (\d+)", note)
        if match and int(match.group(1)):
            return f"pass (0 violations; {match.group(1)} unresolved)"
    return token


def _keyboard(ev: dict[str, Any]) -> str:
    """The keyboard cell; a traversal-only pass is not a full keyboard pass."""
    token = _short(ev.get("verdict"))
    if token == "pass" and ev.get("note", "").startswith("traversal only"):
        return "pass (traversal only)"
    return token


def _pending(screen: dict[str, Any]) -> bool:
    """A no-findings row whose note names second-rater fails awaiting adjudication."""
    return bool(screen["noFindings"]) and "(record §10.5)" in (screen.get("note") or "")


def _screens_of(finding: dict[str, Any]) -> list[str]:
    return [finding["screenId"], *finding.get("alsoOn", [])]


def counts(doc: dict[str, Any]) -> dict[str, Any]:
    screens = doc["screens"]
    findings = doc["findings"]
    cov = Counter(s["coverage"] for s in screens)
    states = [st for s in screens for st in s["states"]]
    reach_states = [st for s in screens if s["coverage"] in REACHABLE for st in s["states"]]
    open_f = [f for f in findings if f["status"] in OPEN_STATUSES]
    wcag: Counter[str] = Counter()
    for s in screens:
        if "wcag22" not in s:  # reserved rows carry no criteria (no screen)
            continue
        for c in CRITERIA:
            wcag[_short(s["wcag22"].get(c, {}).get("verdict"))] += 1
    deep_listed = [s for s in screens if s.get("deepPassListed")]
    band_rows = []
    for lo, hi, area in BANDS:
        ids = {f"SCR-{n:03d}" for n in range(lo, hi + 1)}
        rows = [s for s in screens if s["id"] in ids]
        band_rows.append(
            {
                "band": f"SCR-{lo:03d}..{hi:03d}",
                "area": area,
                "reachable": sum(s["coverage"] in REACHABLE for s in rows),
                "rows": len(rows),
                "open": sum(any(x in ids for x in _screens_of(f)) for f in open_f),
            }
        )
    return {
        "screens": len(screens),
        "coverage": {k: cov.get(k, 0) for k in COVERAGE},
        "reachable": sum(cov.get(k, 0) for k in REACHABLE),
        "unreachable": sum(v for k, v in cov.items() if k.startswith("unreachable")),
        "reserved": cov.get("reserved: no screen", 0),
        "states": {
            "total": len(states),
            "onReachable": len(reach_states),
            **{
                k: sum(st["status"] == k for st in states)
                for k in ("covered", "unreachable", "not run")
            },
        },
        "deepPass": {
            "listed": len(deep_listed),
            "auditable": sum(s["coverage"] in REACHABLE for s in deep_listed),
            "run": sum(
                _short(s["evidence"]["deep"]["verdict"]) in ("pass", "fail") for s in deep_listed
            ),
        },
        "wcag22Cells": dict(sorted(wcag.items())),
        "noFindingsRows": sum(bool(s["noFindings"]) for s in screens),
        "noFindingsPendingAdjudication": sum(_pending(s) for s in screens),
        "findings": {
            "total": len(findings),
            "open": len(open_f),
            "openByLevel": {k: sum(f["level"] == k for f in open_f) for k in LEVELS},
            "openBySeverity": {k: sum(f["severity"] == k for f in open_f) for k in SEVERITIES},
            "openByPriority": {k: sum(f.get("priority") == k for f in open_f) for k in PRIORITIES},
            "needsFilingGo": sum(bool(f.get("needsFilingGo")) for f in open_f),
        },
        "patterns": {p["id"]: len(p["findings"]) for p in doc["patterns"]},
        "bands": band_rows,
    }


def render(doc: dict[str, Any]) -> str:
    c = counts(doc)
    f = c["findings"]
    by_screen: dict[str, Counter[str]] = {sid: Counter() for sid in SCR_IDS}
    for fd in doc["findings"]:
        if fd["status"] in OPEN_STATUSES:
            for scr in _screens_of(fd):
                by_screen[scr][fd["level"]] += 1
    lines = [
        "<!-- generated by docs/plan/a11y/_tools/register.py from findings.json; do not edit -->",
        "",
        "# Accessibility conformance matrix (E47-T01 skeleton, generated)",
        "",
        (
            "Generated, do not edit: regenerate with `python3 docs/plan/a11y/_tools/register.py`;"
            " `--check` fails when this file is stale. Source: `docs/plan/a11y/findings.json`"
            " (schema v2). E47-T05 publishes the report from the register."
        ),
        "",
        f"- Audited sha: `{doc['auditedSha']}`",
        f"- Environment: {doc.get('environment', 'not stated')}",
        (
            f"- Screens: {c['screens']} rows; {c['reachable']} reachable"
            f" ({c['coverage']['covered']} covered, {c['coverage']['partial']} partial);"
            f" {c['unreachable']} unreachable"
            f" ({c['coverage']['unreachable: built, not mounted']} built, not mounted;"
            f" {c['coverage']['unreachable: not built']} not built;"
            f" {c['coverage']['unreachable: needs a state the harness cannot induce']}"
            " need a state the harness cannot induce);"
            f" {c['reserved']} reserved."
        ),
        (
            f"- States: {c['states']['total']} ({c['states']['onReachable']} on reachable screens);"
            f" {c['states']['covered']} covered, {c['states']['unreachable']} unreachable,"
            f" {c['states']['not run']} not run."
        ),
        (
            f"- Deep pass: {c['deepPass']['auditable']} of {c['deepPass']['listed']} listed ids"
            f" auditable; {c['deepPass']['run']} run."
        ),
        "- WCAG 2.2 cells (6 per non-reserved row): "
        + ", ".join(f"{k} {v}" for k, v in c["wcag22Cells"].items())
        + " (unreachable counted apart from n/a).",
        (
            f"- Findings: {f['total']} in all, {f['open']} open"
            f" (Level A {f['openByLevel']['A']}, AA {f['openByLevel']['AA']};"
            f" P0 {f['openByPriority']['P0']}, P1 {f['openByPriority']['P1']},"
            f" P2 {f['openByPriority']['P2']}, P3 {f['openByPriority']['P3']};"
            f" needs filing go {f['needsFilingGo']}); explicit no-findings rows: {c['noFindingsRows']}"
            " (no finding recorded in this run's checks; not a conformance claim;"
            f" {c['noFindingsPendingAdjudication']} of them have second-rater disagreements"
            " pending adjudication, record §10.5)."
        ),
        "- Patterns: "
        + (", ".join(f"{k} ({v})" for k, v in c["patterns"].items()) if c["patterns"] else "none")
        + ".",
        "- Screen reader: the sign-off passes are E47-T04's; this sweep records proxies only.",
        "",
        "## Bands",
        "",
    ]
    lines += table(
        ["Band", "Area", "Reachable", "Rows", "Open findings"],
        [
            [b["band"], b["area"], str(b["reachable"]), str(b["rows"]), str(b["open"])]
            for b in c["bands"]
        ],
    )
    lines += [
        "",
        "## Matrix",
        "",
        "Findings are open findings naming the screen (`screenId` or `alsoOn`), as A / AA.",
        (
            "Automated `pass (0 violations; N unresolved)`: axe found no violation, but N"
            " colour-contrast incomplete nodes per theme are not resolved yet, which is not a pass"
            " for those nodes (record §3). Keyboard `pass (traversal only)`: every stop was reached"
            " and none was fully obscured; activation and focus-ring visibility were judged on the"
            " deep and spot screens only."
        ),
        "",
    ]
    header = ["ID", "Name", "Coverage", "States covered", "Automated (axe)", "Keyboard"]
    header += [*CRITERIA, "Deep pass", "SR", "Findings A / AA", "Owning ticket"]
    rows: list[list[str]] = []
    for s in sorted(doc["screens"], key=lambda r: r["id"]):
        ev = s["evidence"]
        covered = sum(st["status"] == "covered" for st in s["states"])
        wc = s.get("wcag22") or {}
        deep = _short(ev["deep"]["verdict"])
        if "spot" in ev:
            deep = f"{deep}; spot {_short(ev['spot']['verdict'])}"
        n = by_screen[s["id"]]
        rows.append(
            [
                s["id"],
                s["name"],
                s["coverage"],
                f"{covered} / {len(s['states'])}",
                _automated(ev["automated"]),
                _keyboard(ev["keyboard"]),
                *[_short(wc.get(k, {}).get("verdict")) if wc else "reserved" for k in CRITERIA],
                deep,
                ev["sr"]["owner"],
                f"{n['A']} / {n['AA']}",
                s["owningTicket"],
            ]
        )
    lines += table(header, rows)
    return "\n".join(lines) + "\n"


def normalise(text: str) -> list[str]:
    """Lines modulo Markdown table padding and trailing space (Prettier-stable comparison)."""
    out: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        if line.startswith("|") and line.endswith("|"):
            cells = [x.strip() for x in line[1:-1].split(" | ")]
            cells = ["---" if x and set(x) <= {"-", ":"} else x for x in cells]
            line = "| " + " | ".join(cells) + " |"
        out.append(line)
    while out and out[-1] == "":
        out.pop()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="exit 1 if the matrix is stale")
    mode.add_argument("--counts", action="store_true", help="print the totals as JSON")
    ap.add_argument("--register", type=Path, default=REGISTER, help=argparse.SUPPRESS)
    ap.add_argument("--matrix", type=Path, default=MATRIX, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    try:
        doc = load(args.register)
    except RegisterError as exc:
        print(f"register.py: {exc}", file=sys.stderr)
        return 2
    problems = validate(doc)
    if problems:
        for p in problems:
            print(f"register.py: {p}", file=sys.stderr)
        return 2
    if args.counts:
        print(json.dumps(counts(doc), indent=2, ensure_ascii=False))
        return 0
    text = render(doc)
    if args.check:
        try:
            committed = args.matrix.read_text(encoding="utf-8")
        except OSError:
            print(f"register.py: {args.matrix.name} is missing; regenerate it", file=sys.stderr)
            return 1
        if normalise(committed) != normalise(text):
            print(f"register.py: {args.matrix.name} is stale; regenerate it", file=sys.stderr)
            return 1
        print(f"register.py: {args.matrix.name} is current")
        return 0
    args.matrix.write_text(text, encoding="utf-8", newline="\n")
    print(f"register.py: wrote {args.matrix.name} ({len(doc['screens'])} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
