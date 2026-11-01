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
"stale". The register records the git blob of ``14`` and of ``findings.json`` it was generated from;
``--check`` regenerates against those pinned blobs (``git show``), so an edit to either file on
``main`` (a sign-off tick, a status flip) is a WARN/pending line and never reds an unrelated PR. Design reviews are spec-level: they are cited as findings, never counted as conformance
evidence (BQ-19 of E47-T01).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
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


def _levels(level: str, criteria: str) -> dict[str, str]:
    return dict.fromkeys(criteria.split(), level)


WCAG_LEVELS = {
    **_levels(
        "A",
        "1.1.1 1.2.1 1.2.2 1.2.3 1.3.1 1.3.2 1.3.3 1.4.1 1.4.2 2.1.1 2.1.2 2.1.4 2.2.1 2.2.2 2.3.1 2.4.1 2.4.2 2.4.3 2.4.4 2.5.1 2.5.2 2.5.3 2.5.4 3.1.1 3.2.1 3.2.2 3.2.6 3.3.1 3.3.2 3.3.7 4.1.1 4.1.2",
    ),
    **_levels(
        "AA",
        "1.2.4 1.2.5 1.3.4 1.3.5 1.4.3 1.4.4 1.4.5 1.4.10 1.4.11 1.4.12 1.4.13 2.4.5 2.4.6 2.4.7 2.4.11 2.5.7 2.5.8 3.1.2 3.2.3 3.2.4 3.3.3 3.3.4 3.3.8 4.1.3",
    ),
    **_levels(
        "AAA",
        "1.2.6 1.2.7 1.2.8 1.2.9 1.3.6 1.4.6 1.4.7 1.4.8 1.4.9 2.1.3 2.2.3 2.2.4 2.2.5 2.2.6 2.3.2 2.3.3 2.4.8 2.4.9 2.4.10 2.4.12 2.4.13 2.5.5 2.5.6 3.1.3 3.1.4 3.1.5 3.1.6 3.2.5 3.3.5 3.3.6 3.3.9",
    ),
}
# inputs outside this pack: pinned by git blob sha so a tick in another lane never reds `--check`
PINNED_INPUTS = (CATALOGUE_REL, FINDINGS_REL)
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
    layers = {
        k: ("mentioned in 14" if re.search(p, low) else "unverified") for k, p in LAYERS
    }
    return {
        "signoff": signoff,
        "surface": "canvas" if canvas else "chrome",
        "canvasLayers": layers if canvas else None,
    }


# ---------------------------------------------------------------- review finding tables


def split_row(line: str) -> list[str]:
    inner = line.strip()[1:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", inner)]


def clean_severity(raw: str) -> str:
    """``Minor (p2)`` -> ``Minor``: a review's priority suffix is not part of the severity word."""
    return re.sub(r"\s*\(.*?\)\s*$", "", raw).strip()


def parse_review_table(text: str, need_sentence: bool = True) -> list[dict[str, str]]:
    """The finding table of a design review: header ``| F|Id | ... Severity ... Sentence ... |``.

    The severity column may read ``Sev (p)``; every row also carries a clean ``severity`` key.
    ``need_sentence=False`` reads tables with no sentence column (counting only).
    """
    lines = text.splitlines()
    for i, line in enumerate(lines[:-2]):
        if not line.startswith("|"):
            continue
        head = [c.lower() for c in split_row(line)]
        if (
            len(head) >= 3
            and head[0] in ("f", "id")
            and any(h.startswith("sev") for h in head)
            and (not need_sentence or any("sentence" in h for h in head))
            and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip())
        ):
            rows: list[dict[str, str]] = []
            for raw in lines[i + 2 :]:
                if not raw.startswith("|"):
                    break
                cells = split_row(raw)
                if not re.fullmatch(r"F-\d+", cells[0]) or len(cells) < len(head):
                    raise CatalogueError(
                        f"malformed finding row (bad id or short): {raw[:80]!r}"
                    )
                if any(r[head[0]] == cells[0] for r in rows):
                    raise CatalogueError(f"duplicate finding id {cells[0]}")
                row = dict(zip(head, cells, strict=False))
                sev_col = next(h for h in head if h.startswith("sev"))
                row["severity"] = clean_severity(row[sev_col])
                rows.append(row)
            return rows
    return []


def expected_counts(key: str, text: str) -> dict[str, int]:
    """The review's own count marker: total and per source severity. Raises when it has none."""
    m = re.search(r"<!-- audit:f=(\d+)/(\d+)/(\d+)/(\d+)/(\d+) -->", text)
    if m:
        n = [int(g) for g in m.groups()]
        return dict(zip(("total", *SEVERITIES), n, strict=True))
    named = {
        k: re.search(rf"<!-- audit:f{suf}=(\d+) -->", text)
        for k, suf in (
            ("total", ""),
            ("blocker", ".blocking"),
            ("major", ".major"),
            ("minor", ".minor"),
            ("info", ".info"),
        )
    }
    if all(named.values()):
        return {k: int(m.group(1)) for k, m in named.items() if m}
    out: dict[str, int] = {}
    for name, label in (
        ("total", "findings"),
        *((k, f"findings.{k}") for k in SEVERITIES),
    ):
        alts = [label, label.replace("findings", "f", 1)]
        if name == "total":
            alts.append("f.total")
        if name == "blocker":
            alts += ["findings.blocking", "f.blocking"]
        c = re.search(
            r"(\d+)<!--=COUNT:(?:" + "|".join(re.escape(a) for a in alts) + ")-->", text
        )
        if not c:
            raise CatalogueError(f"{key}: no finding count marker ({label})")
        out[name] = int(c.group(1))
    return out


def review_findings(
    key: str,
    text: str,
    sev_map: dict[str, str],
    attribution: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    rows = parse_review_table(text)
    for r in rows:
        if r["severity"].strip().lower() not in sev_map:
            raise CatalogueError(
                f"{key} {r.get('f') or r.get('id')}: severity {r['severity']!r} has no mapping"
            )
    want = expected_counts(key, text)
    got = {"total": len(rows)}
    for k in SEVERITIES:
        got[k] = sum(sev_map.get(r["severity"].strip().lower()) == k for r in rows)
    if got != want:
        raise CatalogueError(
            f"{key}: parsed finding counts {got} differ from the review's own markers {want}"
        )
    for row in rows:
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
        plain = re.sub(r"`[^`]*`", "", clause or row.get("wcag", ""))
        scs = re.findall(r"\b[1-4]\.\d\.\d{1,2}\b", plain) or re.findall(
            r"WCAG (\d\.\d\.\d{1,2})", sentence
        )
        # a review with its own Screen column is read from that column alone
        scope = row["screen"] if "screen" in row else " ".join(row.values())
        scr = [s for s in sorted(set(re.findall(r"SCR-\d{3}", scope))) if s in SCR_IDS]
        fin_id = f"A11Y-R-{key}-{fid}"
        how = "row text"
        mapped = (attribution or {}).get(fin_id)
        if not scr and mapped:
            scr, how = list(mapped["screens"]), f"routing attribution: {mapped['cite']}"
        out.append(
            {
                "id": fin_id,
                "screenSource": how if scr else "none",
                "source": f"review {key}",
                "sourceId": fid,
                "screens": scr,
                "sc": scs,
                "clause": re.sub(r"`", "", clause).strip(),
                "level": None,
                "severity": sev_map[sev_word],
                "sourceSeverity": row["severity"],
                "class": row.get("class"),
                "pattern": None,
                "title": sentence,
                "remedy": remedy,
                "remediation": row.get("owner") or row.get("owner; target", ""),
                "status": "open (spec-level)",
            }
        )
    return out


def cited_review(root: Path, rv: dict[str, Any]) -> dict[str, Any] | None:
    """A merged a11y review that is cited, not joined row by row: counts read from its own table."""
    path = root / rv["path"]
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    rows = parse_review_table(text, need_sentence=False)
    title = re.sub(r"^#\s*\S+\s*[—-]\s*", "", text.splitlines()[0]).strip()
    issue = re.search(r"\(#(\d+)\)", text)
    return {
        "key": rv["key"],
        "path": rv["path"],
        "issue": issue.group(1) if issue else None,
        "scope": title,
        "total": len(rows),
        **{
            k: sum(
                {"blocking": "blocker"}.get(w := r["severity"].lower(), w) == k
                for r in rows
            )
            for k in SEVERITIES
        },
    }


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
        if "text" in m and not re.search(
            "|".join(m["text"]),
            f"{f.get('title', '')} {f.get('remedy', '')}",
            re.IGNORECASE,
        ):
            continue
        return rule["owner"], rule["reason"]
    why = (
        "no design-ticket rule matches this finding's criterion or class "
        f"(SC {', '.join(f['sc']) or 'none'}; class {f.get('class') or 'none'}) "
        "and no override gives it a reason"
    )
    return ENGINEERING_ONLY, why


def levels_for(scs: list[str]) -> str | None:
    found = [WCAG_LEVELS[s] for s in scs if s in WCAG_LEVELS]
    return " / ".join(dict.fromkeys(found)) or None


def sc_reason(f: dict[str, Any]) -> str:
    """Why a row has no SC, or no level: stated, never left blank."""
    if f["sc"] and f["level"]:
        return ""
    if f["sc"]:
        return "the cited criterion is not in the WCAG 2.2 A/AA/AAA table"
    if f.get("clause"):
        return f"the review cites `05` clause {f['clause']} only, no WCAG criterion"
    if f.get("class"):
        return f"class {f['class']}: the review row cites no WCAG criterion"
    return "the source row cites no WCAG criterion"


def status_for(f: dict[str, Any], routing: dict[str, Any]) -> str:
    """The register's status, unless ``statusOverrides`` marks the row fixed on main.

    The override is a stop-gap for a register PR that has not landed: it applies only while the
    register still reads a non-fixed status, so it drops out cleanly once the register says fixed.
    """
    status = f.get("status", "open")
    ov = routing.get("statusOverrides", {}).get(f["id"])
    if not ov or status.startswith("fixed"):
        return str(status)
    if ov.get("status") != "fixed" or not re.fullmatch(
        r"[0-9a-f]{40}", ov.get("sha", "")
    ):
        raise CatalogueError(
            f"{f['id']}: statusOverrides needs status fixed and a full sha"
        )
    return f"fixed (#{ov['pr']}, {ov['sha'][:12]})"


def t01_findings(reg: dict[str, Any], routing: dict[str, Any]) -> list[dict[str, Any]]:
    smap = routing["severityMap"]["t01"]
    out = []
    for f in reg["findings"]:
        if f["severity"] not in smap:
            raise CatalogueError(
                f"{f['id']}: severity {f['severity']!r} has no mapping"
            )
        sev = smap[f["severity"]]
        out.append(
            {
                "id": f["id"],
                "screenSource": "T01 register",
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
                "status": status_for(f, routing),
            }
        )
    return out


def extra_findings(routing: dict[str, Any]) -> list[dict[str, Any]]:
    """The G-T2 rows of this audit itself (modelled on E08-D12 F-03), carried in the routing."""
    smap = routing["severityMap"]["review"]
    out = []
    for x in routing.get("extraFindings", []):
        sev = x["severity"]
        if sev.lower() not in smap:
            raise CatalogueError(f"{x['id']}: severity {sev!r} has no mapping")
        out.append(
            {
                "id": x["id"],
                "screenSource": "this audit's G-T2 pass",
                "source": "E47-D02 G-T2 pass",
                "sourceId": x["id"],
                "screens": x["screens"],
                "sc": [],
                "clause": x.get("clause", ""),
                "level": None,
                "severity": smap[sev.lower()],
                "sourceSeverity": sev,
                "class": x.get("class"),
                "pattern": None,
                "title": x["title"],
                "remedy": x["remedy"],
                "remediation": x["remediation"],
                "status": "open (spec-level)",
            }
        )
    return out


def verdict_for(cov: str, n_live: int, n_fixed: int = 0) -> tuple[str, str]:
    """A screen's verdict, from the T01 register's coverage and the live (not fixed) findings."""
    if cov.startswith("reserved"):
        return (
            "n/a (reserved)",
            "reserved id: no screen exists to audit (14 section 0.2)",
        )
    fixed = f"; {n_fixed} T01 finding(s) fixed since the audit" if n_fixed else ""
    if n_live:
        note = (
            "; spec-level only, screen is " + cov
            if cov.startswith("unreachable")
            else ""
        )
        return "findings", f"{n_live} open finding(s){note}{fixed}"
    if cov.startswith("unreachable"):
        return "not auditable at sha", cov + fixed
    if cov == "partial":
        return "no findings at sha", "partial coverage: the built part only" + fixed
    return "no findings at sha", "covered" + fixed


def evidence_note(t: dict[str, Any]) -> str:
    """What the T01 run actually exercised on this screen (register coverage, not sign-off ticks)."""
    ev = t.get("evidence") or {}
    auto, kb = ev.get("automated") or {}, ev.get("keyboard") or {}
    bits = []
    if auto.get("verdict"):
        bits.append(
            f"axe {auto['verdict']} in {', '.join(auto.get('themes', [])) or 'one theme'}"
        )
    if kb.get("verdict"):
        bits.append(f"keyboard {kb['verdict']}")
    return "; ".join(bits)


def _check_screen_sets(cat: dict[str, Any], t01: dict[str, Any]) -> None:
    """14 and the T01 register must agree on the screens and on which ids are reserved."""
    if set(t01) != set(SCR_IDS) or set(cat) - set(SCR_IDS):
        raise CatalogueError(
            "14 and findings.json disagree on the screen set: "
            f"missing from T01 {sorted(set(SCR_IDS) - set(t01))}, "
            f"outside SCR-001..159 {sorted((set(t01) | set(cat)) - set(SCR_IDS))}"
        )
    reserved = {
        i for i, s in t01.items() if s.get("coverage", "").startswith("reserved")
    }
    unused = set(SCR_IDS) - set(cat)
    if reserved != unused:
        raise CatalogueError(
            "14 and findings.json disagree on the reserved ids: "
            f"reserved in T01 only {sorted(reserved - unused)}, "
            f"no section in 14 only {sorted(unused - reserved)}"
        )


def blob_sha(data: bytes) -> str:
    """The git blob id of ``data`` (what ``git hash-object`` prints)."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def git_show(root: Path, blob: str) -> str | None:
    """A pinned input as text, or None when the object is not in this checkout."""
    try:
        res = subprocess.run(
            ["git", "show", blob],
            cwd=root,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout.decode("utf-8") if res.returncode == 0 else None


def read_input(root: Path, rel: str, over: dict[str, str] | None) -> str:
    if over and rel in over:
        return over[rel]
    try:
        return (root / rel).read_text(encoding="utf-8")
    except OSError as exc:
        raise CatalogueError(f"cannot read {rel}: {exc}") from exc


def build(root: Path = ROOT, over: dict[str, str] | None = None) -> dict[str, Any]:
    """The derived register. Raises CatalogueError on a join that cannot be made honestly.

    ``over`` maps an input path to the text to use instead of the working-tree file: the pinned
    blob, when ``--check`` regenerates against the base the committed output was built from.
    """
    routing = load_json(root / ROUTING_REL)
    try:
        reg = json.loads(read_input(root, FINDINGS_REL, over))
    except json.JSONDecodeError as exc:
        raise CatalogueError(f"cannot read findings.json: {exc}") from exc
    cat_text = read_input(root, CATALOGUE_REL, over)
    cat = parse_screens(cat_text)
    t01_screens = {s["id"]: s for s in reg["screens"]}
    _check_screen_sets(cat, t01_screens)
    attribution = routing.get("attribution", {})
    findings = t01_findings(reg, routing)
    used, pending = [], list(routing.get("pendingReviews", []))
    inputs = {
        CATALOGUE_REL: blob_sha(cat_text.encode("utf-8")),
        FINDINGS_REL: blob_sha(read_input(root, FINDINGS_REL, over).encode("utf-8")),
    }
    for rv in routing["reviews"]:
        path = root / rv["path"]
        if not path.is_file():
            pending.append(rv["key"])
            continue
        text = path.read_text(encoding="utf-8")
        findings += review_findings(
            rv["key"], text, routing["severityMap"]["review"], attribution
        )
        used.append(rv["key"])
    cited = [
        c for rv in routing.get("citedReviews", []) if (c := cited_review(root, rv))
    ]
    pending += [
        rv["key"]
        for rv in routing.get("citedReviews", [])
        if not (root / rv["path"]).is_file()
    ]
    findings += extra_findings(routing)
    notes = routing.get("remedyNotes", {})
    vehicles = routing.get("vehicles", {})
    for f in findings:
        f["designOwner"], f["ownerReason"] = route(f, routing)
        canvas = any(cat.get(s, {}).get("surface") == "canvas" for s in f["screens"])
        f["surface"] = "both" if canvas else "chrome"
        if not f.get("level"):
            f["level"] = levels_for(f["sc"])
        f["scReason"] = sc_reason(f)
        f["remedyNote"] = notes.get(f["id"], "")
        f["vehicle"] = vehicles.get(f["id"], "")
    stale = sorted(
        (set(attribution) | set(notes) | set(vehicles)) - {f["id"] for f in findings}
    )
    if stale:
        raise CatalogueError(
            f"routing attribution, remedy note or vehicle names no parsed finding: {stale}"
        )
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
        live = [f for f in by_screen[scr] if not f["status"].startswith("fixed")]
        verdict, why = verdict_for(cov, len(live), len(by_screen[scr]) - len(live))
        screens.append(
            {
                "id": scr,
                "name": facts["name"],
                "band": band_of(scr),
                "coverage": cov,
                "evidence": evidence_note(t),
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
        "schema": 2,
        "derivedFrom": {
            "t01Register": FINDINGS_REL,
            "auditedSha": reg.get("auditedSha"),
            "inputs": inputs,
            "reviews": used,
            "citedReviews": cited,
            "pendingReviews": sorted(set(pending)),
            "routing": ROUTING_REL,
        },
        "auditor": routing["auditor"],
        "auditDate": routing["auditDate"],
        "severityMap": routing["severityMap"],
        "counts": counts(screens, findings, unattributed),
        "screens": screens,
        "findings": findings,
        "unattributed": unattributed,
    }


def is_fixed(f: dict[str, Any]) -> bool:
    return f["status"].startswith("fixed")


def counts(
    screens: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    unattributed: list[dict[str, Any]],
) -> dict[str, Any]:
    live = [f for f in findings if not is_fixed(f)]
    return {
        "attributedByRouting": sum(
            f["screenSource"].startswith("routing attribution") for f in findings
        ),
        "unattributed": len(unattributed),
        "unattributedBlockers": sum(f["severity"] == "blocker" for f in unattributed),
        "screens": len(screens),
        "verdicts": dict(sorted(Counter(s["verdict"] for s in screens).items())),
        "findings": len(findings),
        "fixed": len(findings) - len(live),
        "open": len(live),
        "bySeverity": {k: sum(f["severity"] == k for f in live) for k in SEVERITIES},
        "bySource": dict(sorted(Counter(f["source"] for f in findings).items())),
        "byOwner": dict(sorted(Counter(f["designOwner"] for f in live).items())),
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
            "Partial against #1301: the open items are listed in section 4. Inputs pinned by git "
            f"blob: `14` at `{d['inputs'][CATALOGUE_REL][:12]}`, `findings.json` at "
            f"`{d['inputs'][FINDINGS_REL][:12]}`; `--check` regenerates against those blobs, so a "
            "later edit to either file is reported as pending drift, folded at the pack's next "
            "touch, and never a failure."
        ),
        "",
        "## 1. Coverage summary",
        "",
        (
            f"{c['screens']} screens, {c['findings']} findings, of which {c['fixed']} are marked "
            f"fixed in the T01 register and {c['open']} are open "
            f"({sev['blocker']} blocker, {sev['major']} major, {sev['minor']} minor, "
            f"{sev['info']} info). Counts by severity and owner, and the heat map, are of the "
            "open rows; fixed rows stay in the per-screen tables with their status."
        ),
        "",
    ]
    lines += table(["Verdict", "Screens"], [[k, v] for k, v in c["verdicts"].items()])
    lines += [
        "",
        (
            "A verdict rests on the E47-T01 register's coverage for the screen (axe in three themes "
            "and the keyboard traversal, named per screen in section 3), never on the design "
            "sign-off ticks in `14`; those ticks are listed per screen as a separate fact. A "
            "screen that is not built is not auditable at the sha, and its rows are spec-level."
        ),
        "",
    ]
    lines += table(["Source", "Findings"], [[k, v] for k, v in c["bySource"].items()])
    lines.append("")
    if d.get("citedReviews"):
        lines += [
            (
                "Other merged a11y design reviews, cited and not joined row by row (the verdicts "
                "and the owner counts above do not include their rows; they are spec-level "
                "findings against screens this audit already lists, and they join at the pack's "
                "next touch):"
            ),
            "",
        ]
        lines += table(
            ["Review", "Scope", "Findings (blocker / major / minor / info)"],
            [
                [
                    f"{r['key']} (#{r['issue']})" if r["issue"] else r["key"],
                    r["scope"],
                    f"{r['total']} ({r['blocker']} / {r['major']} / {r['minor']} / {r['info']})",
                ]
                for r in d["citedReviews"]
            ],
        )
        lines.append("")
    lines += table(
        ["Design owner", "Findings"], [[k, v] for k, v in c["byOwner"].items()]
    )
    lines += [
        "",
        (
            f"Design reviews joined: {', '.join(d['reviews']) or 'none'}. Not on main yet, "
            f"re-run the tool when they land: {', '.join(d['pendingReviews']) or 'none'}. "
            f"Review findings whose row text names no screen: {c['attributedByRouting']} are "
            "attributed from the review's own screen mapping (the `attribution` map in "
            "`47-routing.json`, each entry citing the review section and line); "
            f"{c['unattributed']} remain unattributed because the review gives no mapping "
            f"({c['unattributedBlockers']} of them blocker; listed in section 3)."
        ),
        "",
        (
            "Severity map. T01: blocker is blocker, serious is major, moderate and minor are minor, "
            "and T01 never yields a blocker (blockers come from the reviews). Reviews: Blocker and "
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
    live_ids = {
        s["id"]: [i for i in s["findings"] if not is_fixed(fmap[i])]
        for s in reg["screens"]
    }
    ranked = sorted(
        (s for s in reg["screens"] if live_ids[s["id"]]),
        key=lambda s: (
            *[
                -sum(fmap[i]["severity"] == k for i in live_ids[s["id"]])
                for k in SEVERITIES
            ],
            s["id"],
        ),
    )
    rows = []
    for s in ranked:
        live = live_ids[s["id"]]
        n = [sum(fmap[i]["severity"] == k for i in live) for k in SEVERITIES]
        rows.append([s["id"], s["name"], *n, len(live), "█" * min(len(live), 10)])
    lines += table(
        ["Screen", "Name", "Blocker", "Major", "Minor", "Info", "Total", "Bar"], rows
    )
    zero = sum(1 for s in reg["screens"] if not live_ids[s["id"]])
    lines += [
        "",
        f"{zero} screens carry no open finding; their verdicts are in section 3.",
        "",
        (
            "Multi-screen findings are counted on each screen, so the per-screen totals sum to "
            "more than the number of distinct findings."
        ),
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
                f"{s['surface']}. Design sign-off checklist in 14 (a separate fact from the "
                f"verdict): {so_text}. T01 owner: {s['t01Owner'] or '-'}."
            ),
        ]
        if s["evidence"]:
            lines.append(f"- T01 run on this screen: {s['evidence']}.")
        if s["canvasLayers"]:
            lay = ", ".join(f"{k} {v}" for k, v in s["canvasLayers"].items())
            lines.append(
                f"- Canvas four-layer check (keyword matches on the 14 A11y line, not verified against a build; unverified is not absent): {lay}."
            )
        if s["findings"]:
            lines.append("")
            rows = []
            for i in s["findings"]:
                f = fmap[i]
                rem = f["remedy"] + (
                    f" Catalogue note: {f['remedyNote']}" if f["remedyNote"] else ""
                )
                story = f["remediation"] + (
                    f"; vehicle: {f['vehicle']}" if f["vehicle"] else ""
                )
                rows.append(
                    [
                        f["id"],
                        f["source"],
                        f["status"],
                        f["title"],
                        ", ".join(f["sc"]) or f"none ({f['scReason']})",
                        f["level"] or ("-" if not f["sc"] else f"- ({f['scReason']})"),
                        f"{f['severity']} (source: {f['sourceSeverity']})",
                        rem,
                        f"{f['designOwner']}: {f['ownerReason']}",
                        story,
                    ]
                )
            lines += table(
                [
                    "Id",
                    "Source",
                    "Status",
                    "Finding",
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
    lines += ["### Review findings with no screen mapping", ""]
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
        "- Canvas four-layer verification, and the missing-layer blocker rule, pending a build. Only the screens listed with a canvas check in section 3 carry one, and those come from keyword matches on the 14 A11y line.",
        "- Contrast pairs are cited from the T01 and review tables, not re-measured here.",
        (
            "- The four Blockers (E09-D10 F-1, F-2, F-25, F-26) are carried by #5254 (the fix issue "
            "for the E09 Blocking rows) and #193 (the held E09-D10 delta re-review); both are named "
            "on each Blocker row in section 3."
        ),
        (
            "- Inter-rater agreement carried from the E47-T01 sweep (`docs/qa/a11y/e47-t01-sweep.md` "
            "section 10.1, not recomputed here: this tool reads no rater data): primary Cohen's "
            "kappa 0.61 (n = 96, six WCAG 2.2 criteria); secondary kappa 0.28 (n = 880, 55 "
            "criteria, fail against not-fail), below the 0.6 target because fails are rare "
            "(chance agreement 0.962)."
        ),
        (
            '- Correction to that sweep\'s section 13 row "STEST not in CI": '
            "`scripts/tests/test_a11y_finding_schema.py` (STEST) does run in CI, in the "
            "`governance` lane, which runs the `scripts/tests` suites on every PR. The row is "
            "wrong; the sweep document is owned by its own PR and is not edited here."
        ),
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


def pinned_inputs(
    root: Path, committed: dict[str, Any]
) -> tuple[dict[str, str], list[str], bool]:
    """The pinned blobs the committed register was built from.

    Returns the text overrides to regenerate with, one WARN line per input that has moved since,
    and whether a moved input could not be recovered from this checkout (no git object).
    """
    over: dict[str, str] = {}
    warns: list[str] = []
    missing = False
    for rel, blob in (committed.get("derivedFrom", {}).get("inputs") or {}).items():
        try:
            now = blob_sha((root / rel).read_bytes())
        except OSError:
            now = ""
        if now == blob:
            continue
        text = git_show(root, blob)
        if text is None:
            missing = True
            warns.append(
                f"WARN {rel} moved since the catalogue base (pinned blob {blob[:12]}, now "
                f"{now[:12] or 'absent'}) and the pinned blob is not in this checkout: only "
                "the committed outputs' internal consistency is checked"
            )
            continue
        over[rel] = text
        warns.append(
            f"WARN pending: {rel} moved since the catalogue base (pinned blob {blob[:12]}, now "
            f"{now[:12] or 'absent'}); checked against the pinned blob, fold at the pack's next touch"
        )
    return over, warns, missing


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if a screen is missing or the outputs are stale against their pinned base",
    )
    mode.add_argument("--counts", action="store_true", help="print the totals as JSON")
    ap.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    root: Path = args.root
    reg_path, md_path = root / REGISTER_REL, root / CATALOGUE_OUT_REL
    over: dict[str, str] | None = None
    missing = False
    if args.check:
        try:
            committed = json.loads(reg_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            committed = {}
        over, warns, missing = pinned_inputs(root, committed)
        for w in warns:
            print(f"catalogue.py: {w}", file=sys.stderr)
    try:
        reg = build(root, over)
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
        if missing:
            # the pinned base is unavailable: the committed register must still render its own md
            try:
                have = json.loads(reg_path.read_text(encoding="utf-8"))
                reg_text = json.dumps(have, indent=2, ensure_ascii=False) + "\n"
                md = render(have)
            except (OSError, json.JSONDecodeError, KeyError):
                pass
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
