#!/usr/bin/env python3
"""E47-T02: pure decision logic behind the accessibility CI gates.

The Playwright / Lighthouse runners only *collect* data (JSON); every pass/fail
decision lives here so it is unit-testable without a browser. Stdlib only.

Exit codes (all subcommands): 0 pass, 1 violation (A11Y-G0xx), 3 infrastructure
error (A11Y-INFRA). Infra errors are distinct from violations so the documented
break-glass path never has to disable a gate for a real violation.

Codes: G001 axe regression, G002 Lighthouse below floor, G003 contrast (see
tools/contrast), G004 keyboard E2E, G005 flash rate, G006 a11y-tree drift, G007 runtime budget,
G008 screen inventory (E47-Q04: a mounted screen absent from the axe report).
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import os
import re
import sys
from pathlib import Path

from tools.a11y import inventory

BLOCKING_IMPACTS = ("serious", "critical")
TRACKED_IMPACTS = ("moderate", "minor")
# Sections of axe-baseline.json (BQ-05). Each entry is
# {fingerprint, finding, owner, ticket, target, expiry}: `entries` holds serious/critical (shrink-only,
# keyed screen|rule|selector), `minor_entries` moderate/minor (keyed rule|stable selector path),
BASELINE_SECTIONS = ("entries", "minor_entries")
MAX_EXPIRY_DAYS = 90  # a suppression is a short loan, not a standing exemption
ENTRY_FIELDS = ("fingerprint", "finding", "owner", "ticket", "target", "expiry")
LIGHTHOUSE_FLOOR = 0.95
MAX_FLASHES_PER_SECOND = 3
FLASH_LUMINANCE_DELTA = 0.1  # WCAG 2.3.1 general-flash relative-luminance step
EXIT_OK, EXIT_VIOLATION, EXIT_INFRA = 0, 1, 3


class InfraError(Exception):
    """The runner could not produce a result (not a score/violation failure)."""


def _load(path: str) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InfraError(f"A11Y-INFRA cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise InfraError(f"A11Y-INFRA {path} is not a JSON object")
    return data


# --- Gate 1: axe baseline -------------------------------------------------


def axe_fingerprints(report: dict) -> dict[str, str]:
    """Map `screen|rule|selector` -> message for serious/critical nodes.

    Report shape: {"screens": {"<screen>": {"violations": [axe violation]}}}.
    """
    out: dict[str, str] = {}
    screens = report.get("screens")
    if not isinstance(screens, dict):
        raise InfraError("A11Y-INFRA axe report has no 'screens' object")
    for screen, data in screens.items():
        for v in data.get("violations", []):
            if v.get("impact") not in BLOCKING_IMPACTS:
                continue
            for node in v.get("nodes") or [{"target": ["<page>"]}]:
                sel = " ".join(str(t) for t in node.get("target", ["<page>"]))
                key = f"{screen}|{v['id']}|{sel}"
                out[key] = (
                    f"screen={screen} rule={v['id']} impact={v['impact']} node={sel}"
                )
    return out


def check_axe(report: dict, baseline: dict) -> list[str]:
    """Return A11Y-G001 messages for violations absent from the baseline."""
    allowed = {e["fingerprint"] for e in baseline.get("entries", [])}
    return [
        f"A11Y-G001 new violation: {msg}"
        for key, msg in sorted(axe_fingerprints(report).items())
        if key not in allowed
    ]


def check_baseline_entries(baseline: dict) -> list[str]:
    """Every baseline entry must cite a findings-register id (shrink-only policy)."""
    return [
        f"A11Y-G001 baseline entry {e.get('fingerprint', '?')!r} lacks a finding id"
        for e in baseline.get("entries", [])
        if not str(e.get("finding", "")).startswith("A11Y-F")
    ]


def check_baseline_pr_ids(base: dict, head: dict, pr_body: str) -> list[str]:
    """Every baseline entry added/changed vs base must have its finding id named in the PR body."""
    old = {
        json.dumps(e, sort_keys=True)
        for sec in BASELINE_SECTIONS
        for e in base.get(sec, [])
    }
    return [
        f"A11Y-G001 baseline change {e.get('fingerprint', '?')!r} not justified: "
        f"PR description must name {e.get('finding', '?')}"
        for sec in BASELINE_SECTIONS
        for e in head.get(sec, [])
        if json.dumps(e, sort_keys=True) not in old
        and str(e.get("finding", "")) not in pr_body
    ]


# --- Moderate/minor tracking, schema and expiry (E47-Q04, BQ-05/06) ----------

_USE_ID_RE = re.compile(r":r[0-9a-z]+:")  # React useId, differs per render


def stable_path(target: list | None) -> str:
    """A selector path that survives re-renders: React useId segments become `:r*:`."""
    return _USE_ID_RE.sub(":r*:", " ".join(str(t) for t in (target or ["<page>"])))


def axe_minor_fingerprints(report: dict) -> dict[str, str]:
    """Map `rule|stable selector path` -> message for moderate/minor nodes."""
    out: dict[str, str] = {}
    screens = report.get("screens")
    if not isinstance(screens, dict):
        raise InfraError("A11Y-INFRA axe report has no 'screens' object")
    for screen, data in screens.items():
        for v in data.get("violations", []):
            if v.get("impact") not in TRACKED_IMPACTS:
                continue
            for node in v.get("nodes") or [{"target": ["<page>"]}]:
                sel = stable_path(node.get("target"))
                out.setdefault(
                    f"{v['id']}|{sel}",
                    f"screen={screen} rule={v['id']} impact={v['impact']} node={sel}",
                )
    return out


def check_axe_minor(report: dict, baseline: dict) -> list[str]:
    """A11Y-G001 messages for moderate/minor findings above the baseline."""
    allowed = {e.get("fingerprint") for e in baseline.get("minor_entries", [])}
    return [
        f"A11Y-G001 new moderate/minor finding above baseline: {msg}"
        for key, msg in sorted(axe_minor_fingerprints(report).items())
        if key not in allowed
    ]


def _today(now: dt.datetime | None) -> dt.date:
    return (now or dt.datetime.now(dt.timezone.utc)).date()


def check_baseline_schema(baseline: dict, now: dt.datetime | None = None) -> list[str]:
    """Every entry in every section carries the full schema and has not expired (BQ-06), within 90 days.

    An expired entry names its owner and ticket. `expiry` is the last valid day (UTC); `target`
    is the planned burn-down date and must not be later than the expiry.
    """
    today, msgs = _today(now), []
    for section in BASELINE_SECTIONS:
        for e in baseline.get(section, []):
            fp = e.get("fingerprint", "?")
            missing = [f for f in ENTRY_FIELDS if not str(e.get(f, "")).strip()]
            if missing:
                msgs.append(
                    f"A11Y-G001 {section} entry {fp!r} lacks {', '.join(missing)} "
                    f"(owner={e.get('owner', '?')} ticket={e.get('ticket', '?')})"
                )
                continue
            try:
                expiry = dt.date.fromisoformat(str(e["expiry"]))
                target = dt.date.fromisoformat(str(e["target"]))
            except ValueError:
                msgs.append(
                    f"A11Y-G001 {section} entry {fp!r} has an invalid date "
                    f"(owner={e['owner']} ticket={e['ticket']}); use YYYY-MM-DD"
                )
                continue
            if section != "entries" and not str(e["finding"]).startswith("A11Y-F"):
                msgs.append(
                    f"A11Y-G001 {section} entry {fp!r} lacks a finding id "
                    f"(owner={e['owner']} ticket={e['ticket']})"
                )
            if expiry > today + dt.timedelta(days=MAX_EXPIRY_DAYS):
                msgs.append(
                    f"A11Y-G001 {section} entry {fp!r} expires {expiry}, more than "
                    f"{MAX_EXPIRY_DAYS} days out (owner={e['owner']} ticket={e['ticket']})"
                )
            if expiry < today:
                msgs.append(
                    f"A11Y-G001 {section} entry {fp!r} expired on {expiry}: "
                    f"owner={e['owner']} ticket={e['ticket']} must fix it or renew with a new expiry"
                )
            elif target > expiry:
                msgs.append(
                    f"A11Y-G001 {section} entry {fp!r} target {target} is after its expiry {expiry} "
                    f"(owner={e['owner']} ticket={e['ticket']})"
                )
    return msgs


# --- Gate 8: screen inventory (A11Y-G008) ------------------------------------


def check_inventory(report: dict, tier: str = "pr") -> list[str]:
    try:
        manifest = inventory.load_manifest()
        rows = inventory.load_rows(manifest=manifest)
        return inventory.check_inventory(report, rows, inventory.pr_scan_ids(), tier)
    except inventory.InventoryError as exc:
        raise InfraError(str(exc)) from exc

# --- Gate 2: Lighthouse ---------------------------------------------------


def check_lighthouse(scores: dict, floor: float = LIGHTHOUSE_FLOOR) -> list[str]:
    """scores: {"<screen>": 0..1 | null}. null/empty = runner failure -> infra.

    The collector (E47-Q04) writes {"chromium", "runnerClass", "lighthouse", "scores", "pending"}:
    a `pending` screen is counted, never failed; the other fields record what produced the scores.
    """
    if "scores" in scores:
        scores = scores["scores"]
    if not scores:
        raise InfraError(
            "A11Y-INFRA Lighthouse produced no scores (runner did not start?)"
        )
    missing = sorted(k for k, v in scores.items() if v is None)
    if missing:
        raise InfraError(
            f"A11Y-INFRA Lighthouse gave no score for: {', '.join(missing)}"
        )
    return [
        f"A11Y-G002 screen={s} accessibility score {v:.2f} < {floor:.2f}"
        for s, v in sorted(scores.items())
        if v < floor
    ]


def lighthouse_line(doc: dict) -> str:
    """One line recording what produced the scores, so a score change is attributable (BQ-08)."""
    pending = doc.get("pending") or {}
    return (
        f"A11Y-G002 lighthouse {doc.get('lighthouse', '?')} on Chromium {doc.get('chromium', '?')}, "
        f"runner {doc.get('runnerClass', '?')}: {len(doc.get('scores') or {})} scored, "
        f"{len(pending)} pending"
    )


# --- Gate 5: flash audit --------------------------------------------------


def count_flashes(luminance: list[float], fps: float) -> int:
    """Max flashes in any 1 s window.

    Calibration (E47-S04, WCAG 2.3.1 general flash): "a flash is a pair of opposing
    changes in relative luminance", each >= FLASH_LUMINANCE_DELTA (0.1), so the
    window's change count is halved and a dangling half is ignored. The window
    slides: every change opens one, so it is any 1 s period, not wall-second buckets. The gate fails at >= 3 flashes in any 1 s window
    (WCAG's own line is "more than 3"; this is one stricter). The flash coalescer lets
    one cell start at most every 500 ms (HS-1): at most 2 flashes in any 1 s window,
    which passes with margin; the ticket's earlier 400 ms interval would admit 3 and
    fail.
    """
    if fps <= 0:
        raise InfraError("A11Y-INFRA fps must be positive")
    # Every qualifying change is an event, the first one included: a pulse (rise, then
    # fall) is two events, so N pulses in a window are 2N events and N flashes.
    events: list[int] = []
    direction = 0
    last = luminance[0] if luminance else 0.0
    for i, lum in enumerate(luminance[1:], start=1):
        d = lum - last
        if abs(d) >= FLASH_LUMINANCE_DELTA:
            sign = 1 if d > 0 else -1
            if sign != direction:
                events.append(i)
            direction = sign
            last = lum
    window = max(1, round(fps))
    changes = max(
        (
            sum(1 for e in events[idx:] if e - start < window)
            for idx, start in enumerate(events)
        ),
        default=0,
    )
    return changes // 2


def check_flash(capture: dict) -> list[str]:
    """capture: {"fps": n, "components": {"<name>": [luminance per frame]}}."""
    comps = capture.get("components")
    if not comps or not capture.get("fps"):
        raise InfraError("A11Y-INFRA flash capture is empty")
    msgs = []
    for name, lum in sorted(comps.items()):
        rate = count_flashes(lum, float(capture["fps"]))
        if rate >= MAX_FLASHES_PER_SECOND:
            msgs.append(
                f"A11Y-G005 component={name} {rate} flashes/s (limit < {MAX_FLASHES_PER_SECOND})"
            )
    return msgs


def flash_table(capture: dict) -> str:
    """Markdown flash-rate table (component | max flashes/s | limit | result) for the CI summary."""
    comps = capture.get("components")
    if not comps or not capture.get("fps"):
        raise InfraError("A11Y-INFRA flash capture is empty")
    rows = ["| component | max flashes/s | limit | result |", "|---|---|---|---|"]
    for name, lum in sorted(comps.items()):
        rate = count_flashes(lum, float(capture["fps"]))
        verdict = "FAIL" if rate >= MAX_FLASHES_PER_SECOND else "pass"
        rows.append(f"| {name} | {rate} | < {MAX_FLASHES_PER_SECOND} | {verdict} |")
    return "\n".join(rows)


# --- Gate 6: accessibility-tree snapshot ---------------------------------


def check_tree(snapshot_dir: str, actual_dir: str) -> list[str]:
    """Text-diff each committed screen snapshot against the freshly captured one."""
    base, act = Path(snapshot_dir), Path(actual_dir)
    if not act.is_dir():
        raise InfraError(f"A11Y-INFRA no captured trees at {actual_dir}")
    msgs = []
    for f in sorted(base.glob("*.txt")):
        new = act / f.name
        if not new.exists():
            msgs.append(f"A11Y-G006 screen={f.stem} snapshot missing from capture")
            continue
        a = f.read_text(encoding="utf-8").splitlines()
        b = new.read_text(encoding="utf-8").splitlines()
        if a != b:
            diff = "\n".join(
                difflib.unified_diff(a, b, "committed", "actual", lineterm="")
            )
            msgs.append(f"A11Y-G006 screen={f.stem} tree changed:\n{diff}")
    return msgs


# --- Gate 4: keyboard-only E2E result ------------------------------------


def check_keyboard(result: dict) -> list[str]:
    """result: {"mouseEvents": n, "perScreen": {id: n}, "steps": [{"name":..,"ok":bool}]}."""
    steps = result.get("steps")
    if not steps:
        raise InfraError("A11Y-INFRA keyboard E2E reported no steps")
    msgs = [
        f"A11Y-G004 step={s['name']} failed (keyboard trap/focus loss)"
        for s in steps
        if not s.get("ok")
    ]
    if result.get("mouseEvents", 0):
        per = result.get("perScreen") or {}
        screens = ", ".join(f"{k}={v}" for k, v in per.items() if v)
        where = f" on screen(s) {screens}" if screens else ""
        msgs.append(
            f"A11Y-G004 {result['mouseEvents']} mouse event(s) dispatched{where}"
        )
    return msgs


def check_budget(elapsed_s: float, limit_s: float) -> list[str]:
    """Runtime budget (AC: PR gate < 12 min, nightly sweep < 20 min)."""
    if limit_s <= 0 or elapsed_s < 0:
        raise InfraError("A11Y-INFRA invalid runtime budget arguments")
    if elapsed_s >= limit_s:
        return [
            (
                f"A11Y-G007 gate wall-clock {elapsed_s:.0f}s >= budget {limit_s:.0f}s "
                "(shard the axe sweep by screen band; do not sample)"
            )
        ]
    return []


MAX_WAIVER_HOURS = 24


def infra_waiver_active(env: dict[str, str], now: dt.datetime | None = None) -> bool:
    """Break-glass: CV_A11Y_INFRA_WAIVER_UNTIL (ISO-8601 UTC, <=24h ahead) downgrades
    an INFRA error (exit 3) to a warning. It never affects violations (exit 1)."""
    raw = env.get("CV_A11Y_INFRA_WAIVER_UNTIL", "")
    if not raw:
        return False
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        until = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if until.tzinfo is None:
        return False
    return now < until <= now + dt.timedelta(hours=MAX_WAIVER_HOURS)


def _inventory_line(tier: str) -> str:
    try:
        rows = inventory.load_rows()
        return inventory.describe(rows, inventory.pr_scan_ids(), tier)
    except inventory.InventoryError as exc:
        raise InfraError(str(exc)) from exc


def _emit(msgs: list[str]) -> int:
    for m in msgs:
        print(m)
    if not msgs:
        print("a11y gate: pass")
    return EXIT_VIOLATION if msgs else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("axe")
    a.add_argument("report")
    a.add_argument("--baseline", default="tools/a11y/axe-baseline.json")
    sub.add_parser("lighthouse").add_argument("scores")
    fl = sub.add_parser("flash")
    fl.add_argument("capture")
    fl.add_argument(
        "--table", action="store_true", help="print the markdown rate table first"
    )
    sub.add_parser("keyboard").add_argument("result")
    bp = sub.add_parser("baseline-pr")
    bp.add_argument("base_baseline")
    bp.add_argument("head_baseline")
    bp.add_argument("body_file")
    b = sub.add_parser("budget")
    b.add_argument("elapsed", type=float)
    b.add_argument("--limit", type=float, required=True)
    iv = sub.add_parser("inventory")
    iv.add_argument("report")
    iv.add_argument("--tier", choices=("pr", "full"), default="pr")
    sub.add_parser("lighthouse-plan")
    t = sub.add_parser("tree")
    t.add_argument("--snapshots", default="tools/a11y/tree-snapshots")
    t.add_argument("actual")
    args = p.parse_args(argv)
    try:
        if args.cmd == "axe":
            baseline = _load(args.baseline)
            return _emit(
                check_baseline_entries(baseline)
                + check_baseline_schema(baseline)
                + check_axe(_load(args.report), baseline)
                + check_axe_minor(_load(args.report), baseline)
            )
        if args.cmd == "inventory":
            report = _load(args.report)
            print(_inventory_line(args.tier))
            return _emit(check_inventory(report, args.tier))
        if args.cmd == "lighthouse-plan":
            m = inventory.load_manifest()
            print(json.dumps(inventory.lighthouse_plan(inventory.load_rows(manifest=m), m), indent=2))
            return EXIT_OK
        if args.cmd == "baseline-pr":
            body = Path(args.body_file).read_text(encoding="utf-8")
            return _emit(
                check_baseline_pr_ids(
                    _load(args.base_baseline), _load(args.head_baseline), body
                )
            )
        if args.cmd == "budget":
            return _emit(check_budget(args.elapsed, args.limit))
        if args.cmd == "lighthouse":
            doc = _load(args.scores)
            if "scores" in doc:
                print(lighthouse_line(doc))
            return _emit(check_lighthouse(doc))
        if args.cmd == "flash":
            if args.table:
                print(flash_table(_load(args.capture)))
            return _emit(check_flash(_load(args.capture)))
        if args.cmd == "keyboard":
            return _emit(check_keyboard(_load(args.result)))
        return _emit(check_tree(args.snapshots, args.actual))
    except (InfraError, inventory.InventoryError) as exc:
        print(exc, file=sys.stderr)
        if infra_waiver_active(dict(os.environ)):
            print(
                "A11Y-INFRA break-glass waiver active: infra error waived (not a violation)"
            )
            return EXIT_OK
        return EXIT_INFRA


if __name__ == "__main__":
    sys.exit(main())
