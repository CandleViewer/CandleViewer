#!/usr/bin/env python3
"""E49-D01 (#1330) self-check: the design-QA protocol, its fixture ledgers and the two ledgers.

Offline and default-deny. The shared gates (git, cites, closing keywords, public text, hygiene,
G-UNTOUCHED, the runner and the mutation harness) live in `docs/design/_tools/spec_audit_lib.py`,
imported by path, never copied (G-HELPER pins its sha256). This file keeps only E49-D01's rows:
the clause list of `16` section 12, the severity map, the audit order, the reserved ids, the
ledger rules and their fixtures. Every plan document is read AS TEXT at the pinned base.

Ledger rules (`--ledger SCREENS FINDINGS`; codes in the protocol's section 11): E_HEADER,
E_MISSING, E_EXTRA, E_RESERVED, E_DUP, E_NAME, E_VERDICT, E_AUDIT, E_COUNTS, E_BUGKEY,
E_EXCEPTION, E_NA, E_EPIC, E_E47, E_FINDINGS, E_CROSS. The finding ledger's header, severities and
statuses come from `tools/ga_defects/ledger.py`, loaded by path.

Usage (from the repo root):
  python3 -I -B scripts/design_qa_ledger_check.py --check | --self-test | --fill | --order
  python3 -I -B scripts/design_qa_ledger_check.py --ledger SCREENS.csv FINDINGS.csv
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import functools
import hashlib
import importlib.util
import io
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docs" / "design" / "_tools"))
import spec_audit_lib as L  # noqa: E402 - sys.path first: the shared helper, never copied

BASE = "a53a5b438"  # origin/main where every cite was read
BQ_LIST = "6634720626"  # the BQ list on #1330
HELPER_SHA = "62b56d6446b218cd"  # sha256[:16] of the shared helper as landed

SPEC_REL = "docs/plan/backlog/artifacts/e49-design-qa-protocol.md"
TOOL_REL = "scripts/design_qa_ledger_check.py"
TEST_REL = "scripts/tests/test_design_qa_ledger_check.py"
LIB_REL = "docs/design/_tools/spec_audit_lib.py"
GA_LEDGER_REL = "tools/ga_defects/ledger.py"
SCREENS_REL = "docs/plan/backlog/artifacts/e49-design-qa-screens.csv"
FINDINGS_REL = "docs/plan/backlog/artifacts/e49-design-qa-ledger.csv"
REGISTER_REL = "docs/plan/a11y/47-audit-register.json"
TICKETS_REL = "docs/plan/backlog/all-tickets.json"
PUBLISHED_REL = "docs/plan/backlog/_tools/published.json"
FX_DIR = "tests/fixtures/design_qa"
FX_FILES = (
    "README.md",
    "catalogue.md",
    "register.json",
    "findings.csv",
    "complete.csv",
    "missing-row.csv",
    "bad-verdict.csv",
    "exception-without-owner.csv",
    "findings-without-bug-key.csv",
)
FIXTURES: dict[str, frozenset[str]] = {
    "complete.csv": frozenset(),
    "missing-row.csv": frozenset({"E_MISSING"}),
    "bad-verdict.csv": frozenset({"E_VERDICT"}),
    "exception-without-owner.csv": frozenset({"E_EXCEPTION"}),
    "findings-without-bug-key.csv": frozenset({"E_BUGKEY"}),
}
FIXTURE_KEYS = frozenset({"E49-D05", "E49-S04"})
CROSS_LINK = "docs/plan/16-design-system-brief.md"
OWN = (
    SPEC_REL,
    TOOL_REL,
    TEST_REL,
    SCREENS_REL,
    FINDINGS_REL,
    *(f"{FX_DIR}/{n}" for n in FX_FILES),
)
BUDGETS = {CROSS_LINK: (2, 0)}  # the one cross-link line and its blank line

PLAN = {
    "02": "docs/plan/02-definition-of-ready-done.md",
    "03": "docs/plan/03-testing-strategy.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "18": "docs/plan/18-traceability-matrix.md",
}
KEYED = {
    "E09-D11": L.DocRef("docs/design/E09/E09-D11.md", BASE),
    "E05-D05": L.DocRef("docs/design/E05/E05-D05-design-qa.md", BASE),
    "E12-D13": L.DocRef("docs/design/E12/E12-D13.md", BASE),
    "ledger.py": L.DocRef(GA_LEDGER_REL, BASE),
    "run.py": L.DocRef("tools/ga_defects/run.py", BASE),
    "design-qa-ledger-export.yml": L.DocRef(".github/workflows/design-qa-ledger-export.yml", BASE),
    "47-audit-catalogue.md": L.DocRef("docs/plan/a11y/47-audit-catalogue.md", BASE),
}
KEY_CITES = (
    L.KeyCite("16", 686, "## 12. Design QA checklist"),
    L.KeyCite("16", 693, "Verified in all three themes"),
    L.KeyCite("03", 320, "### 11.3 Bug taxonomy"),
    L.KeyCite("14", 27, "SCR-030..049"),
    L.KeyCite("14", 1122, "### SCR-046"),
    L.KeyCite("14", 1234, "### SCR-051"),
    L.KeyCite("14", 1687, "### SCR-070"),
    L.KeyCite("14", 2513, "### SCR-118"),
    L.KeyCite("18", 44, "## 2. Story"),
    L.KeyCite("E09-D11", 513, "**A-1**"),
    L.KeyCite("E09-D11", 515, "## 16. The design-QA procedure"),
    L.KeyCite("E09-D11", 523, "PS-7 Severity"),
    L.KeyCite("E05-D05", 4, "four groups"),
    L.KeyCite("E12-D13", 3, "fixture-only captures"),
    L.KeyCite("ledger.py", 17, "HEADER = "),
    L.KeyCite("run.py", 21, "LEDGER_PATH"),
    L.KeyCite("47-audit-catalogue.md", 18, "not built is not auditable"),
)
CITE_RE = L.cite_regex(KEYED, ranges=True, spaced=True)

GROUPS = {
    "Tokens & visual": ("TV", ("P3", "P3", "P2", "P2")),
    "Behaviour & states": ("BS", ("P3", "P2", "P2")),
    "Accessibility": ("AX", ("P2",) * 6),
    "Trading-specific safety": ("TS", ("P1", "P2", "P1")),
    "Consistency": ("CO", ("P3", "P3", "P3")),
}
SEVERITY_MAP = (
    ("a secret shown, or a safety-clause breach that can send an order in the wrong env or "
     "unconfirmed", "P0"),
    ("PS-7 Blocking", "P1"),
    ("E47 blocker", "P1"),
    ("token drift that changes a trading signal's meaning", "P1"),
    ("PS-7 Major", "P2"),
    ("E47 major", "P2"),
    ("missing designed empty/error state", "P2"),
    ("a11y AA violation", "P2"),
    ("PS-7 Minor", "P3"),
    ("E47 minor", "P3"),
    ("wrong-but-readable spacing", "P3"),
    ("PS-7 Info, E47 info", "notes"),
)  # fmt: skip
FIRST_TIER = ("SCR-030", "SCR-050", "SCR-060", "SCR-063", "SCR-074")
BUILT = frozenset({"covered", "partial", "unreachable: built, not mounted"})
RESERVED = tuple(f"SCR-{n:03d}" for n in (7, 8, 9, 105, 106, 107, 108, 109, 138, 139))
PILOT = 10

SCREEN_HEADER = (
    "screen_id", "screen_name", "owning_epic", "auditor", "audit_date", "verdict",
    "p0", "p1", "p2", "p3", "bug_keys", "notes", "e47_verdict", "e47_ref",
)  # fmt: skip
VERDICTS = frozenset({"", "pass", "findings", "accepted-exception", "not-applicable"})
HEADING_RE = re.compile(r"^### (SCR-\d{3}) — (.+?)\s*$", re.MULTILINE)
EPIC_RE = re.compile(r"E\d\d(?:;E\d\d)*")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
KEY_RE = re.compile(r"#\d+|E\d\d-[A-Z]\d\d|DQA-\d{4}")
BACKLOG_RE = re.compile(r"E\d\d-[A-Z]\d\d")
OWNER_RE = re.compile(r"(?:^|;\s*)owner:\s*\S")
REASON_RE = re.compile(r"(?:^|;\s*)reason:\s*\S")
TICKET_RE = re.compile(r"(E\d\d-[A-Z]\d\d) #(\d+)")
AC_ROWS = tuple(f"AC {n}" for n in range(1, 6)) + tuple(f"DoD {n}" for n in range(1, 10))
AC_STATES = frozenset({"done", "PR 2", "owner", "open"})
BQ_HEADING = f"## 2. The questions BQ-0 … BQ-9 — defaults built; ruling pending (comment {BQ_LIST})"
SLICE_MARK = "**Slice: PR 1 of 2**"


# ---------- inputs at the base --------------------------------------------------------------------
@functools.cache
def repo() -> L.Repo:
    return L.Repo(ROOT)


def at_base(rel: str) -> str:
    text = repo().show(BASE, rel)
    if text is None:
        raise L.AuditError(f"{rel} is not readable at {BASE}")
    return text


@functools.cache
def ga_ledger() -> ModuleType:
    """The exporter's parser module, by path (registered first: it defines a dataclass)."""
    spec = importlib.util.spec_from_file_location("ga_defects_ledger", ROOT / GA_LEDGER_REL)
    if spec is None or spec.loader is None:
        raise L.AuditError(f"cannot load {GA_LEDGER_REL}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def docs(t: L.Tree) -> L.Docs:
    d = L.Docs(repo(), BASE, KEYED, plan=PLAN)
    for line in t.text("drift").splitlines():
        key, n, text = line.split("|", 2)
        lines = list(d.lines(key) or ())
        lines[int(n) - 1] = text
        d = d.drifted(key, tuple(lines))
    return d


def catalogue(text: str) -> list[tuple[str, str]]:
    return HEADING_RE.findall(text)


def must_weights(matrix: str) -> Counter[str]:
    """Must stories per screen in `18` section 2 (a story counts once per screen it names)."""
    weights: Counter[str] = Counter()
    for line in matrix.split("\n## 3.")[0].split("\n"):
        if line.startswith("| **US-"):
            row = L.cells(line)
            if row[1].startswith("Must"):
                weights.update(set(re.findall(r"SCR-\d{3}", row[2])))
    return weights


def audit_order(cat: Sequence[tuple[str, str]], weights: Counter[str]) -> list[str]:
    ids = [i for i, _ in cat]
    rest = sorted((i for i in ids if i not in FIRST_TIER), key=lambda i: (-weights[i], i))
    return [i for i in FIRST_TIER if i in ids] + rest


@functools.cache
def base_inputs() -> tuple[list[tuple[str, str]], Counter[str], dict[str, object]]:
    register = json.loads(at_base(REGISTER_REL))
    return catalogue(at_base(PLAN["14"])), must_weights(at_base(PLAN["18"])), register


def order_rows() -> tuple[list[list[str]], list[list[str]]]:
    cat, weights, register = base_inputs()
    names = dict(cat)
    coverage = {s["id"]: s["coverage"] for s in register["screens"]}  # type: ignore[attr-defined]
    order = audit_order(cat, weights)
    tier = [["first", i, names[i], str(weights[i])] for i in FIRST_TIER]
    built = [i for i in order if coverage.get(i) in BUILT][:PILOT]
    pilot = [
        [str(n), i, names[i], str(order.index(i) + 1), str(weights[i]), coverage[i]]
        for n, i in enumerate(built, 1)
    ]
    return tier, pilot


@functools.cache
def backlog_keys() -> frozenset[str]:
    return frozenset(t["key"] for t in json.loads(at_base(TICKETS_REL)))


@functools.cache
def issue_numbers() -> dict[str, int]:
    pub = json.loads(at_base(PUBLISHED_REL))
    return {k: v["number"] for k, v in pub.items() if isinstance(v, dict) and "number" in v}


# ---------- the ledger rules ----------------------------------------------------------------------
def finding_rows(text: str) -> tuple[list[dict[str, str]], list[str]]:
    """The finding ledger by the exporter's own header, severities and statuses."""
    ga = ga_ledger()
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or tuple(c.strip() for c in rows[0]) != tuple(ga.HEADER):
        return [], ["E_FINDINGS header"]
    out: list[dict[str, str]] = []
    bad: list[str] = []
    statuses = ga.OPEN_STATUSES | ga.CLOSED_STATUSES
    for r in rows[1:]:
        if not r:
            continue
        d = dict(zip(ga.HEADER, (c.strip() for c in r), strict=False))
        if len(r) != len(ga.HEADER) or d["severity"] not in ga.SEVERITIES:
            bad.append(f"E_FINDINGS {r[0]}: malformed")
        elif d["status"] not in statuses:
            bad.append(f"E_FINDINGS {r[0]}: status {d['status']!r}")
        else:
            out.append(d)
    return out, bad


def _row_codes(d: dict[str, str], keys: frozenset[str], dqa: set[str]) -> list[str]:
    sid, v = d["screen_id"], d["verdict"]
    counts = [d[p] for p in ("p0", "p1", "p2", "p3")]
    bug = [k for k in d["bug_keys"].split(";") if k]
    if v == "":
        return (
            [f"E_AUDIT {sid}: unaudited row carries data"]
            if any([d["auditor"], d["audit_date"], *counts, *bug])
            else []
        )
    bad: list[str] = []
    if not d["auditor"] or not DATE_RE.fullmatch(d["audit_date"]):
        bad.append(f"E_AUDIT {sid}: auditor or date")
    if not all(c.isdigit() for c in counts):
        return [*bad, f"E_COUNTS {sid}: not whole numbers"]
    total = sum(int(c) for c in counts)
    if (v == "pass" and total) or (v == "findings" and not total):
        bad.append(f"E_COUNTS {sid}: {v} with {total}")
    wrong = [
        k for k in bug if not KEY_RE.fullmatch(k) or (BACKLOG_RE.fullmatch(k) and k not in keys)
    ]
    if wrong or (v == "findings" and not bug):
        bad.append(f"E_BUGKEY {sid}: {wrong or 'none'}")
    bad += [
        f"E_CROSS {sid}: {k} names no finding row"
        for k in bug
        if k.startswith("DQA-") and k not in dqa
    ]
    follow = [k for k in bug if k.startswith("#") or BACKLOG_RE.fullmatch(k)]
    if v == "accepted-exception" and not (
        OWNER_RE.search(d["notes"]) and REASON_RE.search(d["notes"]) and follow
    ):
        bad.append(f"E_EXCEPTION {sid}: owner, reason and follow-up key")
    if v == "not-applicable" and not REASON_RE.search(d["notes"]):
        bad.append(f"E_NA {sid}: no reason")
    return bad


def check_ledger(
    screens: str,
    findings: str,
    catalogue_text: str,
    register: Mapping[str, object],
    keys: frozenset[str],
) -> list[str]:
    """Every rule of the protocol's section 11; messages lead with their code."""
    names = dict(catalogue(catalogue_text))
    rows = list(csv.reader(io.StringIO(screens)))
    if not rows or tuple(rows[0]) != SCREEN_HEADER:
        return ["E_HEADER screen ledger"]
    found, bad = finding_rows(findings)
    per: dict[str, Counter[str]] = {}
    for f in found:
        per.setdefault(f["component"], Counter())[f["severity"]] += 1
    dqa = {f["finding_id"] for f in found}
    reg_screens = register["screens"]
    derived = register["derivedFrom"]
    if not isinstance(reg_screens, list) or not isinstance(derived, dict):
        raise L.AuditError("the register lacks its screens or derivedFrom")
    e47 = {s["id"]: s["verdict"] for s in reg_screens}
    ref = str(derived["auditedSha"])[:9]
    seen: Counter[str] = Counter()
    for r in rows[1:]:
        if not r:
            continue
        if len(r) != len(SCREEN_HEADER):
            bad.append(f"E_HEADER row {r[0]}: {len(r)} cells")
            continue
        d = dict(zip(SCREEN_HEADER, r, strict=True))
        sid = d["screen_id"]
        seen[sid] += 1
        if sid in RESERVED or sid not in names:
            bad.append(f"{'E_RESERVED' if sid in RESERVED else 'E_EXTRA'} {sid}")
            continue
        if d["screen_name"] != names[sid]:
            bad.append(f"E_NAME {sid}")
        if not EPIC_RE.fullmatch(d["owning_epic"]):
            bad.append(f"E_EPIC {sid}")
        if d["e47_verdict"] != e47.get(sid) or d["e47_ref"] != ref:
            bad.append(f"E_E47 {sid}")
        if d["verdict"] not in VERDICTS:
            bad.append(f"E_VERDICT {sid}: {d['verdict']!r}")
            continue
        bad += _row_codes(d, keys, dqa)
        got = per.get(sid, Counter())
        want = [d[p] for p in ("p0", "p1", "p2", "p3")]
        have = [str(got[s]) if got[s] or d["verdict"] else "" for s in ("P0", "P1", "P2", "P3")]
        if all(c.isdigit() or c == "" for c in want) and want != have:
            bad.append(f"E_CROSS {sid}: counts {want} vs finding rows {have}")
    bad += [f"E_DUP {i}" for i, n in seen.items() if n > 1]
    bad += [f"E_MISSING {i}" for i in names if i not in seen]
    return bad


def codes(messages: Sequence[str]) -> frozenset[str]:
    return frozenset(m.split(" ", 1)[0] for m in messages)


# ---------- gates over the pack -------------------------------------------------------------------
def spec(t: L.Tree) -> str:
    return t.text("spec")


def g_cite(t: L.Tree) -> list[str]:
    """Every cite resolves at the base; a range may span blank lines, its two ends may not."""
    cites = L.extract_cites(L.strip_fences(spec(t)), CITE_RE)
    d = docs(t)
    ends = [c for c in cites if not all((d.line(c.doc, n) or "").strip() for n in (c.lo, c.hi))]
    return L.check_cites(cites, d, nonblank=False, min_count=30) + [
        f"{c.raw} (a blank end line)" for c in ends
    ]


def g_keycite(t: L.Tree) -> list[str]:
    return L.check_key_cites(KEY_CITES, docs(t))


def _plain(s: str) -> str:
    return s.replace("\\*", "*").strip()


def g_clauses(t: L.Tree) -> list[str]:
    want: list[list[str]] = []
    group = ""
    for line in L.section("\n".join(docs(t).lines("16") or ()), "## 12.").split("\n"):
        m = re.fullmatch(r"\*\*(.+)\*\*", line.strip())
        if m:
            group = m.group(1)
        elif line.startswith("- [ ] "):
            abbr, floors = GROUPS[group]
            n = sum(1 for w in want if w[1] == group)
            want.append([f"DQ-{abbr}-{n + 1}", group, _plain(line[6:]), floors[n]])
    got = [[_plain(c) for c in r] for r in L.table_rows(L.section(spec(t), "## 4."))]
    bad = [f"{w[0]} differs" for w, g in zip(want, got, strict=False) if w != g]
    return bad + ([f"{len(got)} rows, not {len(want)}"] if len(got) != len(want) else [])


def g_severity(t: L.Tree) -> list[str]:
    got = [(r[0], r[1]) for r in L.table_rows(L.section(spec(t), "## 7."))]
    return [] if got == list(SEVERITY_MAP) else ["the severity map differs from the tool's"]


def g_order(t: L.Tree) -> list[str]:
    tier, pilot = order_rows()
    bad = [] if L.table_rows(L.section(spec(t), "### 6.1")) == tier else ["6.1 differs"]
    return bad + ([] if L.table_rows(L.section(spec(t), "### 6.2")) == pilot else ["6.2 differs"])


def g_reserved(t: L.Tree) -> list[str]:
    cat, _, register = base_inputs()
    heads = {i for i, _ in cat}
    gaps = tuple(f"SCR-{n:03d}" for n in range(1, 160) if f"SCR-{n:03d}" not in heads)
    na = tuple(
        s["id"] for s in register["screens"] if s["verdict"] == "n/a (reserved)"  # type: ignore[attr-defined]
    )
    m = re.search(r"Reserved ids \(never rows\): ([^.]+)\.", spec(t))
    named = tuple(re.findall(r"SCR-\d{3}", m.group(1))) if m else ()
    bad = [] if gaps == RESERVED == na else [f"catalogue gaps {gaps} or register {na} drifted"]
    return bad + ([] if named == RESERVED else ["section 11 names other reserved ids"])


def g_fixtures(t: L.Tree) -> list[str]:
    reg = json.loads(t.text("fx:register.json"))
    cat, fnd = t.text("fx:catalogue.md"), t.text("fx:findings.csv")
    bad: list[str] = []
    for name, want in FIXTURES.items():
        got = codes(check_ledger(t.text(f"fx:{name}"), fnd, cat, reg, FIXTURE_KEYS))
        if got != want:
            bad.append(f"{name} gives {sorted(got)}, not {sorted(want)}")
    rows = L.table_rows(L.section(spec(t), "### 20.1"))
    table = {r[0].strip("`"): frozenset(re.findall(r"E_[A-Z0-9]+", r[1])) for r in rows}
    return bad + ([] if table == FIXTURES else ["section 20.1 differs from the tool"])


def g_ledger(t: L.Tree) -> list[str]:
    screens, findings = t.text("screens"), t.text("findings")
    if not screens and not findings:
        return [] if SLICE_MARK in spec(t) else ["no ledgers, and the pack is not slice PR 1"]
    if not screens or not findings:
        return ["one ledger without the other"]
    _, _, register = base_inputs()
    return check_ledger(screens, findings, at_base(PLAN["14"]), register, backlog_keys())


def g_ac(t: L.Tree) -> list[str]:
    rows = L.table_rows(L.section(spec(t), "## 1."))
    bad = [] if tuple(r[0] for r in rows) == AC_ROWS else ["the AC / DoD rows differ"]
    return bad + [f"{r[0]}: state {r[2]!r}" for r in rows if r[2] not in AC_STATES]


def g_bq(t: L.Tree) -> list[str]:
    if BQ_HEADING not in spec(t).split("\n"):
        return ["the BQ heading is not the pending stamp"]
    bullets = L.bq_bullets(spec(t), BQ_HEADING)
    ids = [m.group(1) for b in bullets if (m := re.match(r"- \*\*(BQ-\d+) ", b))]
    bad = [] if ids == [f"BQ-{n}" for n in range(10)] else [f"BQ ids {ids}"]
    return bad + [f"{b[:12]} lacks 'Built as:'" for b in bullets if "Built as:" not in b]


def _ticket_ok(cell: str) -> bool:
    m = TICKET_RE.fullmatch(cell)
    return bool(m) and issue_numbers().get(m.group(1)) == int(m.group(2))  # type: ignore[union-attr]


def g_decisions(t: L.Tree) -> list[str]:
    rows = L.table_rows(L.section(spec(t), "## 15."))
    bad = [] if [r[0] for r in rows] == [f"AD-{n}" for n in range(1, len(rows) + 1)] else ["ids"]
    return bad + [f"{r[0]}: owner {r[3]!r}" for r in rows if not (r[2] and _ticket_ok(r[3]))]


def g_oq(t: L.Tree) -> list[str]:
    rows = L.table_rows(L.section(spec(t), "## 17."))
    return [f"{r[0]}: {r[2]!r}" for r in rows if r[2] != "the owner" and not _ticket_ok(r[2])]


def g_walk(t: L.Tree) -> list[str]:
    items = re.findall(r"^(\d+)\. ", L.section(spec(t), "## 18."), re.MULTILINE)
    bad = [] if 1 <= len(items) <= 10 else [f"{len(items)} walkthrough items"]
    last = L.section(spec(t), "## 18.").rstrip().split("\n")[-1]
    return bad + ([] if "`approved`" in last else ["the last item is not the approval"])


def _own(t: L.Tree) -> list[tuple[str, str]]:
    return [(k, v) for k, v in t.files.items() if k not in ("lib", "drift")]


def g_noclose(t: L.Tree) -> list[str]:
    return L.closing_keywords(_own(t))


def g_public(t: L.Tree) -> list[str]:
    return L.scan_public(_own(t)) + L.comment_findings(_own(t))


def g_hygiene(t: L.Tree) -> list[str]:
    return L.whitespace_hygiene([(k, v) for k, v in _own(t) if v])


def g_helper(t: L.Tree) -> list[str]:
    got = hashlib.sha256(t.text("lib").encode("utf-8")).hexdigest()
    return [] if got.startswith(HELPER_SHA) else [f"{LIB_REL} is {got[:16]}, not {HELPER_SHA}"]


def g_untouched(t: L.Tree) -> list[str]:
    return L.untouched(t.changed, OWN, budgets=BUDGETS, numstat=t.numstat)


def g_mutlist(t: L.Tree) -> list[str]:
    return L.check_mutlist(spec(t), "### 20.3", MUTATIONS)


# fmt: off
GATES = tuple(L.Gate("G-" + f.__name__[2:].upper(), f) for f in (
    g_cite, g_keycite, g_clauses, g_severity, g_order, g_reserved, g_fixtures, g_ledger, g_ac,
    g_bq, g_decisions, g_oq, g_walk, g_noclose, g_public, g_hygiene, g_helper, g_untouched,
    g_mutlist,
))
# fmt: on


def _set(label: str, text: str, mid: str, gate: str, what: str) -> L.Mutation:
    def fn(tree: L.Tree) -> L.Tree:
        return dataclasses.replace(tree, files={**tree.files, label: text})

    return L.Mutation(mid, gate, what, fn=fn)


_M = L.Mutation
_S = "spec"
# fmt: off
MUTATIONS: tuple[L.Mutation, ...] = (
    _M("M-01", "G-CITE", "a cite past the end of ledger.py", _S, "(ledger.py :17)",
       "(ledger.py :9999)"),
    _set("drift", "16|686|## 12. Design QA list", "M-02", "G-KEYCITE", "a pinned line reworded"),
    _M("M-03", "G-CLAUSES", "a clause reworded", _S, "Accessible-name/role table completed.",
       "Accessible-name table completed."),
    _M("M-04", "G-CLAUSES", "a safety floor lowered", _S,
       r"(\| DQ-TS-3 \|[^\n]*\| )P1( +\|)", r"\1P3\2", regex=True),
    _M("M-05", "G-SEVERITY", "Blocking mapped to P2", _S,
       r"(\| PS-7 Blocking +\| )P1", r"\1P2", regex=True),
    _M("M-06", "G-ORDER", "SCR-051 put in the first tier", _S,
       r"(\| first +\| )SCR-050 \| [^|]+\|", r"\1SCR-051 | x |", regex=True),
    _M("M-07", "G-ORDER", "a pilot rank drifts", _S,
       r"(\| 1 +\| SCR-030 +\|[^|]+\| )1( +\|)", r"\g<1>2\2", regex=True),
    _M("M-08", "G-RESERVED", "a reserved id dropped", _S, "SCR-138, SCR-139.", "SCR-138."),
    _M("M-09", "G-FIXTURES", "the complete fixture loses a row", "fx:complete.csv",
       r"\nSCR-005,[^\n]*", "", regex=True),
    _M("M-10", "G-FIXTURES", "the fixture table drifts", _S,
       r"(\| `bad-verdict\.csv` +\| )`E_VERDICT`", r"\1`E_NAME`", regex=True),
    _M("M-11", "G-LEDGER", "no ledgers outside slice PR 1", _S, SLICE_MARK,
       "**Slice: PR 2 of 2**"),
    _M("M-12", "G-AC", "an AC state outside the vocabulary", _S,
       r"(\| AC 3 +\|[^|]+\| )PR 2", r"\1maybe", regex=True),
    _M("M-13", "G-BQ", "the BQ heading names another comment", _S,
       f"ruling pending (comment {BQ_LIST})", "ruling pending (comment 6634720625)"),
    _M("M-14", "G-BQ", "a default without its built line", _S,
       "- **BQ-5 — the audit order.** Built as:", "- **BQ-5 — the audit order.** As:"),
    _M("M-15", "G-DECISIONS", "an owner ticket with the wrong issue", _S,
       r"(\| AD-9 [^\n]*)E49-T03 #1342", r"\1E49-T03 #1343", regex=True),
    _M("M-16", "G-OQ", "an open question owned by nobody", _S,
       r"(\| OQ-4 [^\n]*\| )E49-T01 #1340", r"\1a reviewer   ", regex=True),
    _M("M-17", "G-WALK", "an eleventh walkthrough item", _S,
       "10. Comment `approved`", "10. One more pass.\n11. Comment `approved`"),
    _M("M-18", "G-NOCLOSE", "a closing keyword", _S, "this PR files none;",
       "this PR files none; " + "Clo" + "ses #1330;"),
    _M("M-19", "G-PUBLIC", "a URL", _S, "No third-party screenshot",
       "See " + "http" + "s://example.org. No third-party screenshot"),
    _M("M-20", "G-PUBLIC", "a stray HTML comment", _S, "## 16. Prior art (public knowledge only)",
       "## 16. Prior art (public knowledge only) " + "<!" + "-- note -->"),
    _M("M-21", "G-HYGIENE", "trailing whitespace", _S, "## 16. Prior art (public knowledge only)\n",
       "## 16. Prior art (public knowledge only)  \n"),
    _M("M-22", "G-HELPER", "the helper edited", "lib", "Shared gates for the per-spec",
       "Shared checks for the per-spec"),
    _M("M-23", "G-UNTOUCHED", "an owner document edited", "@changed", "",
       "docs/plan/15-component-catalogue.md"),
    _M("M-24", "G-UNTOUCHED", "the cross-link grows", f"@numstat:{CROSS_LINK}", "", "5 0"),
    _M("M-25", "G-MUTLIST", "the list drifts", _S, r"\| M-01 +\| G-CITE +\|", "| M-01 | G-AC |",
       regex=True),
)
# fmt: on


# ---------- modes ---------------------------------------------------------------------------------
def _disk(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def read_tree(changed: tuple[str, ...] | None = None) -> L.Tree:
    files = {
        "spec": _disk(SPEC_REL),
        "tool": _disk(TOOL_REL),
        "test": _disk(TEST_REL),
        "lib": _disk(LIB_REL),
        "screens": _disk(SCREENS_REL),
        "findings": _disk(FINDINGS_REL),
        **{f"fx:{n}": _disk(f"{FX_DIR}/{n}") for n in FX_FILES},
    }
    numstat: dict[str, tuple[int, int] | None] = {}
    if changed is None:
        base = repo().diff_base(BASE)
        changed = repo().changed_paths(base)
        numstat = {p: repo().numstat(base, p) for p in changed if p in BUDGETS}
    return L.Tree(files=files, changed=changed, numstat=numstat)


def check() -> int:
    return L.report(L.run_gates(GATES, read_tree()))


def self_test(changed: tuple[str, ...] | None = None) -> int:
    disk = [ROOT / rel for rel in OWN]
    return L.self_test(read_tree(changed), GATES, MUTATIONS, disk, namespace=globals())


def replace_table(text: str, heading: str, rows: Sequence[Sequence[str]]) -> str:
    start = text.index("\n|", text.index(heading)) + 1
    lines = text[start:].split("\n")
    head = lines[:2]
    n = 2
    while n < len(lines) and lines[n].startswith("|"):
        n += 1
    body = ["| " + " | ".join(r) + " |" for r in rows]
    return text[:start] + "\n".join(head + body + lines[n:])


def fill() -> int:
    p = ROOT / SPEC_REL
    tier, pilot = order_rows()
    text = replace_table(p.read_text(encoding="utf-8"), "### 6.1", tier)
    text = replace_table(text, "### 6.2", pilot)
    rows = [[m.mid, m.gate, m.what] for m in MUTATIONS]
    p.write_text(replace_table(text, "### 20.3", rows), encoding="utf-8", newline="\n")
    print("sections 6.1, 6.2 and 20.3 written; run prettier on the protocol")
    return 0


def print_order() -> int:
    cat, weights, _ = base_inputs()
    names = dict(cat)
    for n, i in enumerate(audit_order(cat, weights), 1):
        print(f"{n:3d} {i} {weights[i]:2d} {names[i]}")
    return 0


def ledger_mode(screens: Path, findings: Path) -> int:
    register = json.loads(_disk(REGISTER_REL))
    keys = frozenset(t["key"] for t in json.loads(_disk(TICKETS_REL)))
    bad = check_ledger(
        screens.read_text(encoding="utf-8"),
        findings.read_text(encoding="utf-8"),
        _disk(PLAN["14"]),
        register,
        keys,
    )
    for b in bad:
        print(L.ascii_out(b))
    print(f"FAIL {len(bad)}")
    return 1 if bad else 0


def main(argv: Sequence[str]) -> int:
    if argv and argv[0] == "--ledger":
        ap = argparse.ArgumentParser(prog="design_qa_ledger_check.py --ledger")
        ap.add_argument("screens", type=Path)
        ap.add_argument("findings", type=Path)
        args = ap.parse_args(list(argv[1:]))
        return ledger_mode(args.screens, args.findings)
    modes = {"check": check, "self-test": self_test, "fill": fill, "order": print_order}
    return L.cli(argv, modes, __doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
