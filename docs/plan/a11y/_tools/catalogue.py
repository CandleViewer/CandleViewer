#!/usr/bin/env python3
"""E47-D02 (#1301): the accessibility design audit catalogue, derived and never hand-edited.

Joins four inputs per screen: the E47-T01 register (``findings.json``, ids ``A11Y-F-nnnn`` kept),
the merged spec-level a11y design reviews (finding tables parsed from the review markdown), the
screens in ``docs/plan/14-screens-catalogue.md`` (SCR-001..159, reserved rows included) and the
routing table ``47-routing.json`` (design owner D03..D10 or engineering-only with a reason).

Writes ``47-audit-register.json`` (schema 1) and ``47-audit-catalogue.md``.

Usage::

    python3 docs/plan/a11y/_tools/catalogue.py            # regenerate both outputs
    python3 docs/plan/a11y/_tools/catalogue.py --check    # exit 1: a screen is missing or stale
    python3 docs/plan/a11y/_tools/catalogue.py --counts   # print the totals

Stdlib only. ``--check`` compares the Markdown modulo table padding, so a Prettier reflow is not
"stale". Design reviews are spec-level: they are cited as findings, never counted as conformance
evidence (BQ-19 of E47-T01).
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
ROOT = A11Y.parents[2]
SCR_IDS = [f"SCR-{n:03d}" for n in range(1, 160)]
SEVERITIES = ("blocker", "major", "minor", "info")
ENGINEERING_ONLY = "engineering-only"
CATALOGUE_REL = "docs/plan/14-screens-catalogue.md"
FINDINGS_REL = "docs/plan/a11y/findings.json"
ROUTING_REL = "docs/plan/a11y/47-routing.json"
E47_REL = "docs/plan/backlog/E47.json"
REGISTER_REL = "docs/plan/a11y/47-audit-register.json"
CATALOGUE_OUT_REL = "docs/plan/a11y/47-audit-catalogue.md"
LAYERS = (
    ("canvasRole", r'role="img"|aria-label|accessible name|\blabel\b'),
    ("domMirror", r"mirror|real `?role=|role=\"(?:grid|table|tree|list)\"|keyboard"),
    ("liveRegion", r"aria-live|polite|assertive|live region|announce"),
    ("tableAlternative", r"\btable\b|role=\"grid\"|data grid|\bgrid\b"),
)
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


class CatalogueError(Exception):
    """An input is unusable or a gate failed."""


def band_of(scr: str) -> str:
    n = int(scr[4:])
    return next(name for lo, hi, name in BANDS if lo <= n <= hi)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogueError(f"cannot read {path.name}: {exc}") from exc


# ---------------------------------------------------------------- 14-screens-catalogue.md


def parse_screens(text: str) -> dict[str, dict[str, Any]]:
    """``### SCR-nnn - Name`` sections: name, sign-off counts, surface and the canvas layers."""
    parts = re.split(r"^### (SCR-\d{3}) [—-] (.+)$", text, flags=re.MULTILINE)
    screens: dict[str, dict[str, Any]] = {}
    for i in range(1, len(parts) - 2, 3):
        scr, name, body = parts[i], parts[i + 1].strip(), parts[i + 2]
        body = re.split(r"^#{1,2} ", body, maxsplit=1, flags=re.MULTILINE)[0]
        if scr in screens:
            raise CatalogueError(f"{scr} appears twice in the screens catalogue")
        screens[scr] = {"name": name, **_section_facts(body)}
    return screens


def _line(body: str, label: str) -> str | None:
    m = re.search(rf"^- \*\*{label}:\*\*(.*)$", body, flags=re.MULTILINE)
    return m.group(1).strip() if m else None


def _section_facts(body: str) -> dict[str, Any]:
    signoff = None
    for label in (
        "Design sign-off acceptance checklist",
        "Sign-off checklist",
        "Sign-off",
    ):
        raw = _line(body, label)
        if raw is not None:
            raw = raw.split("**Stories:**")[0]
            signoff = {
                "line": label,
                "checked": len(re.findall(r"\[[xX]\]", raw)),
                "unchecked": len(re.findall(r"\[ \]", raw)),
            }
            break
    a11y = _line(body, "A11y") or ""
    low = a11y.lower()
    canvas = "canvas" in low and not re.search(r"not (?:a )?canvas", low)
    layers = {k: ("present" if re.search(p, low) else "unverified") for k, p in LAYERS}
    return {
        "signoff": signoff,
        "surface": "canvas" if canvas else "chrome",
        "canvasLayers": layers if canvas else None,
    }


# ---------------------------------------------------------------- review finding tables


def split_row(line: str) -> list[str]:
    inner = line.strip()[1:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", inner)]


def parse_review_table(text: str) -> list[dict[str, str]]:
    """The finding table of a design review: header ``| F|Id | ... Severity ... Sentence ... |``."""
    lines = text.splitlines()
    for i, line in enumerate(lines[:-2]):
        if not line.startswith("|"):
            continue
        head = [c.lower() for c in split_row(line)]
        if (
            len(head) >= 3
            and head[0] in ("f", "id")
            and "severity" in head
            and any("sentence" in h for h in head)
            and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip())
        ):
            rows: list[dict[str, str]] = []
            for raw in lines[i + 2 :]:
                if not raw.startswith("|"):
                    break
                cells = split_row(raw)
                if not re.fullmatch(r"F-\d+", cells[0]) or len(cells) < len(head):
                    continue
                rows.append(dict(zip(head, cells, strict=False)))
            return rows
    return []


def review_findings(
    key: str, text: str, sev_map: dict[str, str]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in parse_review_table(text):
        fid = row["f"] if "f" in row else row["id"]
        sent_col = next(h for h in row if "sentence" in h)
        sentence, _, repl = row[sent_col].partition(" · ")
        remedy = row.get("replacement") or repl or "see the review row"
        sev_word = row["severity"].strip().lower()
        if sev_word not in sev_map:
            raise CatalogueError(
                f"{key} {fid}: severity {row['severity']!r} has no mapping"
            )
        clause = row.get("clause", "")
        plain = re.sub(r"`[^`]*`", "", clause)
        scs = re.findall(r"\b[1-4]\.\d\.\d{1,2}\b", plain) or re.findall(
            r"WCAG (\d\.\d\.\d{1,2})", sentence
        )
        scr = sorted(set(re.findall(r"SCR-\d{3}", " ".join(row.values()))))
        out.append(
            {
                "id": f"A11Y-R-{key}-{fid}",
                "source": f"review {key}",
                "sourceId": fid,
                "screens": [s for s in scr if s in SCR_IDS],
                "sc": scs,
                "level": None,
                "severity": sev_map[sev_word],
                "sourceSeverity": row["severity"],
                "class": row.get("class"),
                "pattern": None,
                "title": sentence,
                "remedy": remedy,
                "remediation": row.get("owner", ""),
            }
        )
    return out


# ---------------------------------------------------------------- routing and join


def route(f: dict[str, Any], routing: dict[str, Any]) -> tuple[str, str]:
    ov = routing.get("overrides", {}).get(f["id"])
    if ov:
        return ov["owner"], ov["reason"]
    for rule in routing["rules"]:
        m = rule["match"]
        if "screen" in m and not set(m["screen"]) & set(f["screens"]):
            continue
        if "sc" in m and not set(m["sc"]) & set(f["sc"]):
            continue
        if "class" in m and (f.get("class") or "") not in m["class"]:
            continue
        if "pattern" in m and f.get("pattern") not in m["pattern"]:
            continue
        return rule["owner"], rule["reason"]
    return (
        ENGINEERING_ONLY,
        "no design-ticket rule matches this finding's criterion or class",
    )


def t01_findings(reg: dict[str, Any], routing: dict[str, Any]) -> list[dict[str, Any]]:
    smap = routing["severityMap"]["t01"]
    blocking = re.compile(routing["severityMap"]["taskBlockingPattern"], re.IGNORECASE)
    out = []
    for f in reg["findings"]:
        if f["severity"] not in smap:
            raise CatalogueError(
                f"{f['id']}: severity {f['severity']!r} has no mapping"
            )
        sev = smap[f["severity"]]
        if blocking.search(f.get("title", "") + " " + f.get("observed", "")):
            sev = "blocker"
        out.append(
            {
                "id": f["id"],
                "source": "E47-T01 register",
                "sourceId": f["id"],
                "screens": [f["screenId"], *f.get("alsoOn", [])],
                "sc": [f["wcagSc"]] if f.get("wcagSc") else [],
                "level": f.get("level"),
                "severity": sev,
                "sourceSeverity": f["severity"],
                "class": None,
                "pattern": f.get("pattern"),
                "title": f.get("title", ""),
                "remedy": f.get("expected", ""),
                "remediation": f.get("owningTicket", ""),
            }
        )
    return out


def verdict_for(cov: str, n_findings: int) -> tuple[str, str]:
    if cov.startswith("reserved"):
        return (
            "n/a (reserved)",
            "reserved id: no screen exists to audit (14 section 0.2)",
        )
    if n_findings:
        note = (
            "; spec-level only, screen is " + cov
            if cov.startswith("unreachable")
            else ""
        )
        return "findings", f"{n_findings} finding(s){note}"
    if cov.startswith("unreachable"):
        return "not auditable at sha", cov
    if cov == "partial":
        return "no findings at sha", "partial coverage: the built part only"
    return "no findings at sha", "covered"


def build(root: Path = ROOT) -> dict[str, Any]:
    """The derived register. Raises CatalogueError on a join that cannot be made honestly."""
    routing = load_json(root / ROUTING_REL)
    reg = load_json(root / FINDINGS_REL)
    cat = parse_screens((root / CATALOGUE_REL).read_text(encoding="utf-8"))
    t01_screens = {s["id"]: s for s in reg["screens"]}
    findings = t01_findings(reg, routing)
    used, pending = [], list(routing.get("pendingReviews", []))
    for rv in routing["reviews"]:
        path = root / rv["path"]
        if not path.is_file():
            pending.append(rv["key"])
            continue
        text = path.read_text(encoding="utf-8")
        findings += review_findings(rv["key"], text, routing["severityMap"]["review"])
        used.append(rv["key"])
    for f in findings:
        f["designOwner"], f["ownerReason"] = route(f, routing)
        canvas = any(cat.get(s, {}).get("surface") == "canvas" for s in f["screens"])
        f["surface"] = "both" if canvas else "chrome"
    unattributed = [f for f in findings if not f["screens"]]
    findings = [f for f in findings if f["screens"]]
    by_screen: dict[str, list[dict[str, Any]]] = {s: [] for s in SCR_IDS}
    for f in findings:
        for s in f["screens"]:
            if s in by_screen:
                by_screen[s].append(f)
    screens = []
    for scr in SCR_IDS:
        t = t01_screens.get(scr, {})
        cov = t.get("coverage", "")
        facts = cat.get(scr)
        if facts is None:
            facts = {
                "name": t.get("name", "reserved"),
                "signoff": None,
                "surface": "chrome",
                "canvasLayers": None,
            }
            cov = cov or "reserved: no screen"
        verdict, why = verdict_for(cov, len(by_screen[scr]))
        screens.append(
            {
                "id": scr,
                "name": facts["name"],
                "band": band_of(scr),
                "coverage": cov,
                "verdict": verdict,
                "verdictReason": why,
                "auditor": routing["auditor"],
                "date": routing["auditDate"],
                "surface": facts["surface"],
                "canvasLayers": facts["canvasLayers"],
                "signoff": facts["signoff"],
                "findings": [f["id"] for f in by_screen[scr]],
                "t01Owner": t.get("owningTicket"),
            }
        )
    return {
        "schema": 1,
        "derivedFrom": {
            "t01Register": FINDINGS_REL,
            "auditedSha": reg.get("auditedSha"),
            "reviews": used,
            "pendingReviews": sorted(set(pending)),
            "routing": ROUTING_REL,
        },
        "auditor": routing["auditor"],
        "auditDate": routing["auditDate"],
        "severityMap": routing["severityMap"],
        "counts": counts(screens, findings),
        "screens": screens,
        "findings": findings,
        "unattributed": unattributed,
    }


def counts(
    screens: list[dict[str, Any]], findings: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "screens": len(screens),
        "verdicts": dict(sorted(Counter(s["verdict"] for s in screens).items())),
        "findings": len(findings),
        "bySeverity": {
            k: sum(f["severity"] == k for f in findings) for k in SEVERITIES
        },
        "bySource": dict(sorted(Counter(f["source"] for f in findings).items())),
        "byOwner": dict(sorted(Counter(f["designOwner"] for f in findings).items())),
    }


# ---------------------------------------------------------------- gates


def validate(reg: dict[str, Any], e47_keys: set[str] | None = None) -> list[str]:
    problems: list[str] = []
    ids = [s["id"] for s in reg["screens"]]
    for scr in SCR_IDS:
        n = ids.count(scr)
        if n != 1:
            problems.append(
                f"{scr} appears {n} times in the register (must be exactly once)"
            )
    for s in reg["screens"]:
        if not s.get("verdict"):
            problems.append(f"{s['id']}: no verdict")
        if s["verdict"].startswith("no findings") and not (
            s.get("auditor") and s.get("date")
        ):
            problems.append(
                f"{s['id']}: a no-findings verdict needs an auditor and a date"
            )
        if s["verdict"] == "findings" and not s["findings"]:
            problems.append(f"{s['id']}: verdict findings with no finding ids")
    for f in reg["findings"]:
        o = f.get("designOwner")
        if not o or not (o == ENGINEERING_ONLY or re.fullmatch(r"E47-D(0[3-9]|10)", o)):
            problems.append(
                f"{f['id']}: owner {o!r} is not D03..D10 or engineering-only"
            )
        if not f.get("ownerReason"):
            problems.append(f"{f['id']}: the routing carries no reason")
        if f["severity"] not in SEVERITIES:
            problems.append(f"{f['id']}: severity {f['severity']!r} is outside the map")
        if e47_keys is not None and o != ENGINEERING_ONLY and o not in e47_keys:
            problems.append(f"{f['id']}: owner {o} does not resolve in E47.json")
    return problems


# ---------------------------------------------------------------- rendering


def cell(text: Any) -> str:
    s = " ".join(str(text).split())
    return s.replace("|", "\\|") or "-"


def table(header: list[str], rows: list[list[Any]]) -> list[str]:
    out = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    out += ["| " + " | ".join(cell(c) for c in r) + " |" for r in rows]
    return out


def render(reg: dict[str, Any]) -> str:
    c = reg["counts"]
    fmap = {f["id"]: f for f in reg["findings"]}
    d = reg["derivedFrom"]
    sev = c["bySeverity"]
    lines = [
        "# E47-D02 accessibility design audit catalogue",
        "",
        (
            "<!-- Generated by docs/plan/a11y/_tools/catalogue.py from 47-audit-register.json. "
            "Do not edit by hand. -->"
        ),
        "",
        (
            f"Auditor {reg['auditor']}, {reg['auditDate']}, over the E47-T01 register at sha "
            f"`{str(d['auditedSha'])[:12]}`. A text-first design audit of every id SCR-001 to "
            "SCR-159 in `14-screens-catalogue.md`: the T01 observed findings and the merged "
            "spec-level a11y design reviews, joined per screen, normalised to four severities and "
            "routed to one design owner (E47-D03 to E47-D10) or to engineering-only with a reason. "
            "Design reviews are spec-level: cited as findings, never counted as conformance evidence. "
            "Partial against #1301: the open items are listed in section 4."
        ),
        "",
        "## 1. Coverage summary",
        "",
        (
            f"{c['screens']} screens, {c['findings']} findings "
            f"({sev['blocker']} blocker, {sev['major']} major, {sev['minor']} minor, "
            f"{sev['info']} info)."
        ),
        "",
    ]
    lines += table(["Verdict", "Screens"], [[k, v] for k, v in c["verdicts"].items()])
    lines.append("")
    lines += table(["Source", "Findings"], [[k, v] for k, v in c["bySource"].items()])
    lines.append("")
    lines += table(
        ["Design owner", "Findings"], [[k, v] for k, v in c["byOwner"].items()]
    )
    lines += [
        "",
        (
            f"Design reviews joined: {', '.join(d['reviews']) or 'none'}. Not on main yet, "
            f"re-run the tool when they land: {', '.join(d['pendingReviews']) or 'none'}. "
            f"Review findings naming no screen: {len(reg['unattributed'])} (listed in section 3)."
        ),
        "",
        (
            "Severity map. T01: blocker is blocker, serious is major, moderate and minor are minor, "
            "and a finding whose text says task-blocking is raised to blocker. Reviews: Blocker and "
            "Blocking are blocker; Major, Minor and Info pass through."
        ),
        "",
        "## 2. Heat map",
        "",
        (
            "Screens with findings, ranked by blocker count, then major, minor and info. The bar is "
            "one block per finding (capped at 10); the counts carry the value."
        ),
        "",
    ]
    ranked = sorted(
        (s for s in reg["screens"] if s["findings"]),
        key=lambda s: (
            *[
                -sum(fmap[i]["severity"] == k for i in s["findings"])
                for k in SEVERITIES
            ],
            s["id"],
        ),
    )
    rows = []
    for s in ranked:
        n = [sum(fmap[i]["severity"] == k for i in s["findings"]) for k in SEVERITIES]
        rows.append(
            [
                s["id"],
                s["name"],
                *n,
                len(s["findings"]),
                "█" * min(len(s["findings"]), 10),
            ]
        )
    lines += table(
        ["Screen", "Name", "Blocker", "Major", "Minor", "Info", "Total", "Bar"], rows
    )
    zero = sum(1 for s in reg["screens"] if not s["findings"])
    lines += [
        "",
        f"{zero} screens carry no finding; their verdicts are in section 3.",
        "",
    ]
    lines += ["## 3. Screens", ""]
    for s in reg["screens"]:
        lines += [f"### {s['id']} {s['name']}", ""]
        so = s["signoff"]
        so_text = (
            f"{so['checked']} of {so['checked'] + so['unchecked']} items ticked ({so['line']})"
            if so
            else "none in 14"
        )
        lines += [
            (
                f"- Verdict: {s['verdict']} ({s['verdictReason']}); auditor {s['auditor']}, "
                f"{s['date']}."
            ),
            (
                f"- Band: {s['band']}. Coverage at sha: {s['coverage'] or '-'}. Surface: "
                f"{s['surface']}. Design sign-off checklist: {so_text}. T01 owner: "
                f"{s['t01Owner'] or '-'}."
            ),
        ]
        if s["canvasLayers"]:
            lay = ", ".join(f"{k} {v}" for k, v in s["canvasLayers"].items())
            lines.append(
                f"- Canvas four-layer check (from the 14 A11y line; unverified is not absent): {lay}."
            )
        if s["findings"]:
            lines.append("")
            rows = []
            for i in s["findings"]:
                f = fmap[i]
                rows.append(
                    [
                        f["id"],
                        f["source"],
                        ", ".join(f["sc"]) or "-",
                        f["level"] or "-",
                        f"{f['severity']} (source: {f['sourceSeverity']})",
                        f["remedy"],
                        f"{f['designOwner']}: {f['ownerReason']}",
                        f["remediation"],
                    ]
                )
            lines += table(
                [
                    "Id",
                    "Source",
                    "SC",
                    "Level",
                    "Severity",
                    "Design remedy",
                    "Design owner",
                    "Remediation story",
                ],
                rows,
            )
        lines.append("")
    lines += ["### Review findings naming no screen", ""]
    if reg["unattributed"]:
        lines += table(
            ["Id", "Source", "Severity", "Design owner", "Finding"],
            [
                [f["id"], f["source"], f["severity"], f["designOwner"], f["title"]]
                for f in reg["unattributed"]
            ],
        )
    else:
        lines.append("None.")
    lines += [
        "",
        "## 4. Open items for #1301",
        "",
        (
            "- Routed to the coordinator and owner, not done here: Penpot frame annotations, the "
            "NVDA live pass and mirror-lag measurement, the 5-screen inter-rater calibration and "
            "third-reviewer check, the E47-D01 blocker absorption (D01 is unmerged), the D03 to D10 "
            "lead review of the routing, CDO sign-off and the 31-sprint-plan reorder."
        ),
        "- Contrast pairs are cited from the T01 and review tables, not re-measured here.",
        "",
    ]
    return "\n".join(lines)


def normalise(text: str) -> list[str]:
    """Lines modulo Markdown table padding and trailing space (Prettier-stable comparison)."""
    out: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        if line.startswith("|") and line.endswith("|"):
            cells = [x.strip() for x in re.split(r"(?<!\\) \| ", line[1:-1])]
            cells = ["---" if x and set(x) <= {"-", ":"} else x for x in cells]
            line = "| " + " | ".join(cells) + " |"
        out.append(line)
    while out and out[-1] == "":
        out.pop()
    return out


def e47_keys(root: Path) -> set[str] | None:
    path = root / E47_REL
    if not path.is_file():
        return None
    return {t["key"] for t in load_json(path)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument(
        "--check", action="store_true", help="exit 1 if a screen is missing or stale"
    )
    mode.add_argument("--counts", action="store_true", help="print the totals as JSON")
    ap.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    root: Path = args.root
    reg_path, md_path = root / REGISTER_REL, root / CATALOGUE_OUT_REL
    try:
        reg = build(root)
    except (CatalogueError, KeyError) as exc:
        print(f"catalogue.py: {exc}", file=sys.stderr)
        return 2
    problems = validate(reg, e47_keys(root))
    if problems:
        for p in problems:
            print(f"catalogue.py: {p}", file=sys.stderr)
        return 1 if args.check else 2
    if args.counts:
        print(json.dumps(reg["counts"], indent=2, ensure_ascii=False))
        return 0
    reg_text = json.dumps(reg, indent=2, ensure_ascii=False) + "\n"
    md = render(reg)
    if args.check:
        stale = []
        for path, want, norm in ((reg_path, reg_text, None), (md_path, md, normalise)):
            try:
                have = path.read_text(encoding="utf-8")
            except OSError:
                stale.append(f"{path.name} is missing")
                continue
            if norm is None:
                try:
                    differs = json.loads(have) != json.loads(want)
                except json.JSONDecodeError:
                    differs = True
            else:
                differs = norm(have) != norm(want)
            if differs:
                stale.append(f"{path.name} is stale")
        if stale:
            for p in stale:
                print(f"catalogue.py: {p}; regenerate it", file=sys.stderr)
            return 1
        print("catalogue.py: outputs are current and every SCR is covered")
        return 0
    reg_path.write_text(reg_text, encoding="utf-8", newline="\n")
    md_path.write_text(md, encoding="utf-8", newline="\n")
    print(
        f"catalogue.py: wrote {reg_path.name} and {md_path.name} ({len(reg['screens'])} screens)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
