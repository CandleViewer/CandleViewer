#!/usr/bin/env python3
"""E47-Q04: the accessibility burn-down dashboard, a generated static page (BQ-09).

Open defects by severity, by screen and by WCAG criterion come from `docs/plan/a11y/findings.json`; the
gate trend (axe, Lighthouse, keyboard, inventory) comes from the QA result store (tools/a11y/store.py).
Every figure is a table cell with its number in text, so the page needs no chart and has its own table
equivalent. No script, no external resource. Stdlib only.

Usage: python -m tools.a11y.dashboard [--out reports/a11y/dashboard.html] [--sprints 4]
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from collections import Counter
from pathlib import Path

from tools.a11y import store

ROOT = Path(__file__).resolve().parents[2]
FINDINGS = ROOT / "docs/plan/a11y/findings.json"
OPEN_STATES = ("open", "in-progress")
SEVERITIES = ("critical", "serious", "moderate", "minor")
CSS = """
:root{--bg:#fff;--fg:#1a1a1a;--muted:#4d4d4d;--line:#767676;--head:#eee;--link:#0b4fa8}
@media (prefers-color-scheme:dark){:root{--bg:#121212;--fg:#ececec;--muted:#b5b5b5;--line:#8a8a8a;--head:#232323;--link:#8ab4f8}}
body{background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif;margin:0 auto;max-width:72rem;padding:0 16px 3rem}
h1,h2{line-height:1.2}table{border-collapse:collapse;width:100%;margin:.5rem 0 1.5rem}
caption{text-align:left;font-weight:600;padding:.25rem 0}th,td{border:1px solid var(--line);padding:.35rem .6rem;text-align:left}
th{background:var(--head)}td.n{text-align:right;font-variant-numeric:tabular-nums}a{color:var(--link)}
.skip{position:absolute;left:-999px}.skip:focus{left:8px;top:8px;background:var(--bg);padding:4px}
@media (max-width:40rem){table{display:block;overflow-x:auto}}
"""


def load_findings(path: Path = FINDINGS) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def burn_down(data: dict) -> dict:
    """Open counts by severity, screen and WCAG criterion (open = open or in-progress)."""
    names = {s["id"]: s.get("name", "") for s in data.get("screens", [])}
    sev: dict[str, Counter] = {s: Counter() for s in SEVERITIES}
    by_screen: dict[str, Counter] = {}
    by_sc: dict[str, Counter] = {}
    levels: dict[str, str] = {}
    for f in data.get("findings", []):
        state = "open" if f.get("status") in OPEN_STATES else "closed"
        sev.setdefault(f["severity"], Counter())[state] += 1
        by_screen.setdefault(f["screenId"], Counter())[(state, f["severity"])] += 1
        by_sc.setdefault(f["wcagSc"], Counter())[state] += 1
        levels[f["wcagSc"]] = f.get("level", "")
    return {"severity": sev, "screen": by_screen, "sc": by_sc, "names": names, "levels": levels}


def trend(sprints: dict[int, dict], last: int) -> list[dict]:
    """One row per sprint (newest `last`), from the latest build recorded for each (kind, screen)."""
    rows = []
    for n in sorted(sprints)[-last:]:
        doc, latest = sprints[n], {}
        for r in doc["results"]:
            k = (r["source"], r["kind"], r["screen"])
            if k not in latest or (r["recorded"], r["build"]) > (latest[k]["recorded"], latest[k]["build"]):
                latest[k] = r
        res = list(latest.values())
        axe = [r for r in res if r["kind"] == "axe"]
        lh = [r for r in res if r["kind"] == "lighthouse" and r["outcome"] != "pending"]
        kb = [r for r in res if r["kind"] == "keyboard"]
        inv = [r for r in res if r["kind"] == "inventory"]
        rows.append({
            "sprint": n, "start": doc["start"], "end": doc["end"],
            "blocking": sum(r["metrics"].get("critical", 0) + r["metrics"].get("serious", 0) for r in axe) if axe else None,
            "minor": sum(r["metrics"].get("moderate", 0) + r["metrics"].get("minor", 0) for r in axe) if axe else None,
            "lh_min": min((r["metrics"]["score"] for r in lh), default=None),
            "lh_pending": sum(1 for r in res if r["kind"] == "lighthouse" and r["outcome"] == "pending"),
            "keyboard": kb[0]["outcome"] if kb else None,
            "mounted": inv[0]["metrics"].get("mounted") if inv else None,
            "pending": inv[0]["metrics"].get("pending") if inv else None,
        })
    return rows


def _e(v: object) -> str:
    return html.escape("not recorded" if v is None else str(v))


def _table(caption: str, head: list[str], rows: list[list[object]]) -> str:
    th = "".join(f'<th scope="col">{_e(h)}</th>' for h in head)
    body = "".join(
        "<tr>" + "".join(
            (f'<th scope="row">{_e(c)}</th>' if i == 0 else f'<td class="n">{_e(c)}</td>' if isinstance(c, (int, float)) else f"<td>{_e(c)}</td>")
            for i, c in enumerate(row)) + "</tr>"
        for row in rows) or f'<tr><td colspan="{len(head)}">None</td></tr>'
    return f"<table><caption>{_e(caption)}</caption><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"


def render(data: dict, sprints: dict[int, dict], last: int = 4) -> str:
    b, t = burn_down(data), trend(sprints, last)
    total_open = sum(c["open"] for c in b["severity"].values())
    screens = sorted(b["screen"], key=lambda s: (-sum(v for (st, _), v in b["screen"][s].items() if st == "open"), s))
    parts = [
        f"<p>{total_open} open accessibility defects ({_e(len(data.get('findings', [])))} recorded). "
        f"Gate history: {len(t)} of the last {last} sprints recorded.</p>",
        "<h2 id=\"sev\">Open defects by severity</h2>",
        _table("Open and closed defects by severity", ["Severity", "Open", "Closed"],
               [[s, b["severity"][s]["open"], b["severity"][s]["closed"]] for s in SEVERITIES]),
        "<h2 id=\"screen\">Open defects by screen</h2>",
        _table("Open defects by screen and severity", ["Screen", "Name", "Open", "Serious", "Moderate", "Minor"],
               [[s, b["names"].get(s, ""), *(sum(v for (st, sv), v in b["screen"][s].items() if st == "open" and (sv in x)) for x in (("critical", "serious", "moderate", "minor"), ("serious", "critical"), ("moderate",), ("minor",)))]
                for s in screens if any(st == "open" for st, _ in b["screen"][s])]),
        "<h2 id=\"sc\">Open defects by WCAG criterion</h2>",
        _table("Open and closed defects by WCAG 2.2 success criterion", ["Criterion", "Level", "Open", "Closed"],
               [[sc, b["levels"].get(sc, ""), b["sc"][sc]["open"], b["sc"][sc]["closed"]] for sc in sorted(b["sc"])]),
        "<h2 id=\"trend\">Gate trend by sprint</h2>",
        _table("Gate results per sprint (latest recorded build)",
               ["Sprint", "Dates", "axe serious or critical", "axe moderate or minor", "Lighthouse lowest score",
                "Lighthouse pending", "Keyboard", "Screens mounted", "Screens pending"],
               [[f"Sprint {r['sprint']:02d}", f"{r['start']} to {r['end']}", r["blocking"], r["minor"], r["lh_min"],
                 r["lh_pending"], r["keyboard"], r["mounted"], r["pending"]] for r in t]),
    ]
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Accessibility burn-down</title><style>{CSS}</style></head><body>"
        '<a class="skip" href="#main">Skip to the report</a><header><h1>Accessibility burn-down</h1>'
        f"<p>Audited build {_e(data.get('auditedSha', 'unknown'))[:12]}. Generated from the findings register and the QA result store.</p></header>"
        f'<main id="main">{"".join(parts)}</main></body></html>'
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", default="reports/a11y/dashboard.html")
    p.add_argument("--findings", default=str(FINDINGS))
    p.add_argument("--store", default=str(store.STORE))
    p.add_argument("--sprints", type=int, default=4)
    a = p.parse_args(argv)
    try:
        page = render(load_findings(Path(a.findings)), store.load_store(Path(a.store)), a.sprints)
    except (OSError, ValueError, KeyError, store.StoreError) as exc:
        print(f"A11Y-INFRA dashboard: {exc}", file=sys.stderr)
        return 3
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"a11y dashboard: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
