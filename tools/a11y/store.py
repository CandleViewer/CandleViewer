#!/usr/bin/env python3
"""E47-Q04: the QA gate and trend results store (BQ-02).

One JSON file per sprint under `qa/evidence/e47/results/` (`sprint-NN.json`), one schema shared by the
writers E47-Q02 (manual screen-reader pass), Q03 (keyboard, tree) and Q04 (axe, Lighthouse, inventory):
`qa/evidence/e47/results.schema.json`. It holds gate and trend results only; defects stay in
`docs/plan/a11y/findings.json` (the K01 schema). Stdlib only.

A result is {source, kind, screen, outcome, metrics, tags, build, recorded}. Its identity is
(source, kind, screen, build): recording it again replaces it, so a re-run never double counts.
Values pass through the redaction filter before they are written (C-2.7).

Usage: python -m tools.a11y.store record <report-dir> --build <sha> [--date YYYY-MM-DD] [--store DIR]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

from tools.a11y import redact

ROOT = Path(__file__).resolve().parents[2]
STORE = ROOT / "qa/evidence/e47/results"
SCHEMA_VERSION = 1
SOURCES = ("Q02", "Q03", "Q04", "Q05", "T03")
KINDS = ("axe", "lighthouse", "keyboard", "tree", "flash", "inventory", "manual")
OUTCOMES = ("pass", "fail", "blocked", "pending", "not run")  # the plan's words, never a colour
# 1-week sprints, Fri -> Thu, Sprint 01 = 2026-09-25 (docs/plan/backlog/_tools/calendar_cv.py)
SPRINT01_START = dt.date(2026, 9, 25)
FIELDS = ("source", "kind", "screen", "outcome", "metrics", "tags", "build", "recorded")
LIGHTHOUSE_FLOOR = 0.95


class StoreError(Exception):
    """A result or store file that breaks the schema."""


def sprint_of(day: dt.date) -> int:
    return (day - SPRINT01_START).days // 7 + 1


def sprint_range(n: int) -> tuple[dt.date, dt.date]:
    start = SPRINT01_START + dt.timedelta(days=(n - 1) * 7)
    return start, start + dt.timedelta(days=6)


def key_of(r: dict) -> tuple[str, str, str, str]:
    return (r["source"], r["kind"], r["screen"], r["build"])


def validate_result(r: object) -> list[str]:
    """Return the schema violations of one result (empty = valid)."""
    if not isinstance(r, dict):
        return ["result is not an object"]
    errs = [f"missing {f}" for f in FIELDS if f not in r]
    if errs:
        return errs
    if extra := sorted(set(r) - set(FIELDS)):
        errs.append(f"unknown field(s) {', '.join(extra)}")
    if r["source"] not in SOURCES:
        errs.append(f"source {r['source']!r} not in {SOURCES}")
    if r["kind"] not in KINDS:
        errs.append(f"kind {r['kind']!r} not in {KINDS}")
    if r["outcome"] not in OUTCOMES:
        errs.append(f"outcome {r['outcome']!r} not in {OUTCOMES}")
    if not (isinstance(r["screen"], str) and re.fullmatch(r"(SCR-\d{3}|R-\d{3}|\*)", r["screen"])):
        errs.append("screen must be SCR-nnn, R-nnn or * (the whole run)")
    m = r["metrics"]
    if not isinstance(m, dict) or not all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in m.values()
    ):
        errs.append("metrics must map names to numbers")
    t = r["tags"]
    if not (isinstance(t, list) and "epic:E47" in t and all(re.fullmatch(r"[a-z]+:[\w.-]+", str(x)) for x in t)):
        errs.append("tags must be name:value strings and include epic:E47")
    if not (isinstance(r["build"], str) and re.fullmatch(r"[0-9a-f]{7,40}", r["build"])):
        errs.append("build must be a 7-40 character commit sha")
    try:
        dt.date.fromisoformat(str(r["recorded"]))
    except ValueError:
        errs.append("recorded must be YYYY-MM-DD")
    return errs


def load_sprint(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StoreError(f"cannot read {path}: {exc}") from exc
    if doc.get("schemaVersion") != SCHEMA_VERSION or not isinstance(doc.get("results"), list):
        raise StoreError(f"{path}: not a v{SCHEMA_VERSION} sprint file")
    for i, r in enumerate(doc["results"]):
        if errs := validate_result(r):
            raise StoreError(f"{path} result {i}: {'; '.join(errs)}")
    return doc


def load_store(store: Path = STORE) -> dict[int, dict]:
    """sprint number -> sprint document, for every sprint-NN.json in the store."""
    out: dict[int, dict] = {}
    for p in sorted(store.glob("sprint-*.json")):
        m = re.fullmatch(r"sprint-(\d{2,3})\.json", p.name)
        if not m:
            raise StoreError(f"unexpected file name {p.name}")
        doc = load_sprint(p)
        if doc.get("sprint") != int(m[1]):
            raise StoreError(f"{p}: sprint field does not match the file name")
        out[int(m[1])] = doc
    return out


def append_results(store: Path, results: list[dict], today: dt.date) -> Path:
    """Add results to the sprint of their `recorded` date; same identity replaces. Returns the file."""
    if not results:
        raise StoreError("no results to record")
    clean = [redact.redact_json(r) for r in results]
    for r in clean:
        if errs := validate_result(r):
            raise StoreError(f"invalid result {r.get('kind')}/{r.get('screen')}: {'; '.join(errs)}")
    days = {dt.date.fromisoformat(r["recorded"]) for r in clean}  # type: ignore[index]
    sprints = {sprint_of(d) for d in days}
    if len(sprints) != 1 or max(days) > today:
        raise StoreError("results must share one sprint and not be dated in the future")
    n = sprints.pop()
    path = store / f"sprint-{n:02d}.json"
    if path.exists():
        doc = load_sprint(path)
    else:
        start, end = sprint_range(n)
        doc = {"schemaVersion": SCHEMA_VERSION, "sprint": n, "start": start.isoformat(),
               "end": end.isoformat(), "results": []}
    merged = {key_of(r): r for r in doc["results"]}
    merged.update({key_of(r): r for r in clean})  # type: ignore[arg-type]
    doc["results"] = [merged[k] for k in sorted(merged)]
    store.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


# --- Q04 reports -> results ------------------------------------------------------------------


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def results_from_reports(report_dir: Path, build: str, day: dt.date) -> list[dict]:
    """The Q04 gate results of one run: axe per screen, Lighthouse per screen, the inventory, keyboard."""
    base = {"source": "Q04", "tags": ["epic:E47"], "build": build, "recorded": day.isoformat()}
    out: list[dict] = []
    if axe := _read(report_dir / "axe.json"):
        for screen, data in sorted((axe.get("screens") or {}).items()):
            c = {k: 0 for k in ("critical", "serious", "moderate", "minor")}
            for v in data.get("violations", []):
                n = len(v.get("nodes") or [1])
                if v.get("impact") in c:
                    c[v["impact"]] += n
            fail = c["critical"] + c["serious"] > 0
            out.append({**base, "kind": "axe", "screen": screen,
                        "outcome": "fail" if fail else "pass", "metrics": c})
    if lh := _read(report_dir / "lighthouse.json"):
        scores = lh.get("scores", lh)
        for screen, score in sorted(scores.items()):
            if not isinstance(score, (int, float)):
                continue
            out.append({**base, "kind": "lighthouse", "screen": screen,
                        "outcome": "pass" if score >= LIGHTHOUSE_FLOOR else "fail",
                        "metrics": {"score": score}})
        for screen in sorted(lh.get("pending") or {}):
            out.append({**base, "kind": "lighthouse", "screen": screen, "outcome": "pending", "metrics": {}})
    if kb := _read(report_dir / "keyboard.json"):
        steps = kb.get("steps") or []
        bad = sum(1 for s in steps if not s.get("ok")) + int(kb.get("mouseEvents", 0) > 0)
        out.append({**base, "kind": "keyboard", "screen": "*", "outcome": "fail" if bad else "pass",
                    "metrics": {"steps": len(steps), "failed": bad}})
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("report_dir")
    r.add_argument("--build", required=True)
    r.add_argument("--date", default=dt.date.today().isoformat())
    r.add_argument("--store", default=str(STORE))
    args = p.parse_args(argv)
    try:
        day = dt.date.fromisoformat(args.date)
        results = results_from_reports(Path(args.report_dir), args.build, day)
        path = append_results(Path(args.store), results, dt.date.today())
    except (StoreError, ValueError) as exc:
        print(f"A11Y-INFRA {exc}", file=sys.stderr)
        return 3
    print(f"a11y store: {len(results)} result(s) -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
