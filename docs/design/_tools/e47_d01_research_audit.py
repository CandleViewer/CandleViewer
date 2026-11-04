#!/usr/bin/env python3
"""E47-D01 (#1300) audit: the keyboard-only and screen-reader baseline research memo.

Offline and default-deny. The shared gates (git, cites, closing keywords, hygiene, public text,
G-UNTOUCHED, the runner and the mutation harness) live in `spec_audit_lib.py` on main; this file
keeps only E47-D01's rows. It reads, AS TEXT at the pinned base, the plan, design, register and
code texts the memo cites; from the working tree, the memo, this tool and its test. G-FLOOD runs
one repo module: the merged E47-D07 announcement tool's `replay`, on E47-D07's own spec and
seeded transcripts at the base, to re-derive the memo's SYNTHETIC counts.

Gates: G-AC, G-BQ, G-TASKS, G-ROWS, G-KEYS, G-D02, G-ROUTE, G-COUNTS, G-SC (section 3.2 screens
every AA criterion in SC_SCREEN), G-T2 (section 3.3 names every AD and TOP-1/2 and the T2 items),
G-FLOOD, G-CITE, G-CHECKLIST, G-NOCLOSE, G-PUBLIC, G-UNTOUCHED and G-MUTLIST (section 14 equals
this tool's list).
The BQ list (comment 6634720172) is posted with its ruling pending: G-BQ checks the
"defaults built; ruling pending" heading and the ten rows BQ-0..BQ-9.

Usage (from the repo root):
  python3 -I docs/design/_tools/e47_d01_research_audit.py --check | --self-test
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import functools
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_audit_lib as L  # the shared helper sits beside this file

ROOT = Path(__file__).resolve().parents[3]
BASE = "a53a5b4385eb9fbf73ad530900065a0f8626e523"  # origin/main the memo cites
BQ_LIST = "6634720172"  # the BQ list on #1300, ruling pending

MEMO_REL = "docs/research/a11y/47-keyboard-sr-baseline.md"
TOOL_REL = "docs/design/_tools/e47_d01_research_audit.py"
TEST_REL = "docs/design/_tools/test_e47_d01_research_audit.py"
OWN = (MEMO_REL, TOOL_REL, TEST_REL)
REG_REL = "docs/plan/a11y/47-audit-register.json"
E47J_REL = "docs/plan/backlog/E47.json"
D07_TOOL_REL = "docs/design/_tools/e47_d07_announcement_audit.py"
D07_REL = "docs/design/E47/E47-D07.md"
D07_JSON_REL = "docs/design/E47/E47-D07-transcripts.json"

KEYED = {
    "CAT": L.DocRef("docs/plan/a11y/47-audit-catalogue.md", BASE),
    "D04": L.DocRef("docs/design/E47/E47-D04.md", BASE),
    "D05": L.DocRef("docs/design/E47/E47-D05.md", BASE),
    "D06": L.DocRef("docs/design/E47/E47-D06.md", BASE),
    "D07": L.DocRef(D07_REL, BASE),
    "D09": L.DocRef("docs/design/E47/E47-D09.md", BASE),
    "D13": L.DocRef("docs/design/E47/E47-D13.md", BASE),
    "E47J": L.DocRef(E47J_REL, BASE),
    "KMAP": L.DocRef("apps/web/src/keymap/keymap.json", BASE),
    "CHS": L.DocRef("apps/web/src/keymap/Cheatsheet.tsx", BASE),
    "HOST": L.DocRef("apps/web/src/keymap/KeymapHost.tsx", BASE),
    "MODEL": L.DocRef("apps/web/src/features/a11y-preferences/model.ts", BASE),
    "PW": L.DocRef("apps/web/src/chart/a11y/politeWriter.ts", BASE),
    "CTP": L.DocRef("apps/web/src/chart/a11y/ChartTablePanel.tsx", BASE),
    "SHELL": L.DocRef("apps/web/src/features/app-shell/ShellLayout.tsx", BASE),
    "TREE": L.DocRef("apps/web/src/routes/tree.tsx", BASE),
    "SRR": L.DocRef("docs/qa/a11y/sr/README.md", BASE),
    "README": L.DocRef("docs/design/README.md", BASE),
    "CONST": L.DocRef("CONSTITUTION.md", BASE),
}
# A backticked key, a colon, a line or an en-dash range: `05`:185, `KMAP`:615 to 618.
CITE_RE = re.compile(r"`(?P<key>\d\d|[A-Z][A-Z0-9]*)`:(?P<first>\d+)(?:\u2013(?P<end>\d+))?")
MIN_CITES = 80  # a broken grammar parses far fewer
PINS = (  # load-bearing cites: the needle must stand on the cited line
    L.KeyCite("05", 64, "Ctrl+Shift+F"),
    L.KeyCite("05", 185, "default 1 update / 2s per field"),
    L.KeyCite("05", 282, "Defect severity bar"),
    L.KeyCite("05", 293, "counts"),
    L.KeyCite("KMAP", 615, "positions.close_all"),
    L.KeyCite("KMAP", 337, "chart.table_toggle"),
    L.KeyCite("MODEL", 25, 'announce_prices: "significant"'),
    L.KeyCite("PW", 103, "significant = false"),
    L.KeyCite("D05", 382, "D05-G4"),
    L.KeyCite("D07", 638, "D07-Q2"),
    L.KeyCite("D09", 417, "D09-G1"),
    L.KeyCite("CHS", 31, "focus returns"),
)

SCENARIOS_RE = re.compile(r"^\s*Scenario: (.+)$", re.MULTILINE)
BQ_HEADING = f"## BQ list — defaults built; ruling pending (comment {BQ_LIST})"
VERDICTS = ("completable", "blocker", "not built at the sha")
SEVERITIES = ("blocker", "major", "minor")
SCR_RE = re.compile(r"^SCR-\d{3}(?:, SCR-\d{3})*$")
SC_RE = re.compile(r"^(?:\d\.\d+\.\d+(?:, \d\.\d+\.\d+)*|n/a \(usability, `\d\d`:\d+\))$")
REG_ID_RE = re.compile(r"A11Y-(?:F-\d{4}|R-E\d\d-D\d\d-F-\d\d)")
TICKET = r"E\d\d-[A-Z]\d\d \(#\d+\)"
ROUTE_RE = re.compile(rf"^(?:{TICKET}(?:, {TICKET})*|engineering-only.*)$")
OWNER_RE = re.compile(rf"^(?:{TICKET}(?:, {TICKET})*|owner.*|E\d\d-[A-Z]\d\d, E\d\d-[A-Z]\d\d)$")
FLOOD_ROWS = {
    "Off": "off",
    "On significant change (default)": "significant",
    "Always · Low": "always-low",
    "Always · Normal": "always-normal",
    "Always · High (= Normal)": "always-high",
    "Always · Normal, whale prints on": "always-whale",
    "Reduce announcements on": "reduce",
}
SC_SCREEN = (  # the AA criteria that decide a keyboard and SR trading UI (section 3.2)
    "1.4.1", "1.4.3", "1.4.10", "2.1.1", "2.1.2", "2.4.3", "2.4.5", "2.4.6", "2.4.7", "2.4.11",
    "2.5.7", "2.5.8", "3.2.1", "3.2.2", "3.3.4", "3.3.8", "4.1.2", "4.1.3",
)  # fmt: skip
SC_STATUS = ("finding: F-", "no finding (heuristic)", "not assessable at the sha", "not assessed: ")
T2_ITEMS = ("G-T2.1b", "G-T2.1c", "G-T2.3", "TOP-1", "TOP-2")
WINDOW_MS = 120_000  # BQ-6: a 2-minute window
CADENCES = (1000, 2000, 5000)


@functools.cache
def repo() -> L.Repo:
    return L.Repo(ROOT)


@functools.cache
def docs() -> L.Docs:
    return L.Docs(repo(), BASE, KEYED)


def base_text(rel: str) -> str:
    text = repo().show(BASE, rel)
    if text is None:
        raise L.AuditError(f"{rel} is not readable at {BASE[:9]}")
    return text


def rows_of(memo: str, heading: str) -> list[list[str]]:
    return L.table_rows(L.section(memo, heading))


def f_rows(memo: str) -> list[list[str]]:
    return rows_of(memo, "## 3.")


def task_rows(memo: str) -> list[list[str]]:
    return rows_of(memo, "## 2.")


# ---------- gates ---------------------------------------------------------------------------------
def g_ac(t: L.Tree) -> list[str]:
    """Every `Scenario:` of the ticket stands, quoted verbatim, in the AC trace."""
    tickets = json.loads(base_text(E47J_REL))
    body = next(str(x["body"]) for x in tickets if x.get("key") == "E47-D01")
    names = SCENARIOS_RE.findall(body)
    trace = L.section(t.text("memo"), "## Acceptance-criteria trace")
    bad = [n for n in names if f'"{n}"' not in trace]
    return bad if len(names) == 5 else [f"{len(names)} scenarios parsed, not 5", *bad]


def g_bq(t: L.Tree) -> list[str]:
    memo = t.text("memo")
    bad = [] if BQ_HEADING + "\n" in memo else ["the BQ heading is not the pending form"]
    ids = [r[0] for r in rows_of(memo, "## BQ list")]
    return bad + ([] if ids == [f"BQ-{i}" for i in range(10)] else [f"BQ rows {ids}"])


def g_tasks(t: L.Tree) -> list[str]:
    rows = task_rows(t.text("memo"))
    bad = [] if [r[0] for r in rows] == [f"T{i}" for i in range(1, 10)] else ["T1..T9 order"]
    return bad + [f"{r[0]}: verdict {r[3]!r}" for r in rows if r[3] not in VERDICTS]


def g_rows(t: L.Tree) -> list[str]:
    memo = t.text("memo")
    tasks = {r[0] for r in task_rows(memo)}
    rows = f_rows(memo)
    bad = [] if [r[0] for r in rows] == [f"F-{i}" for i in range(1, len(rows) + 1)] else ["F ids"]
    for r in rows:
        if len(r) != 11:
            bad.append(f"{r[0]}: {len(r)} cells")
            continue
        fid, text, scr, _cmp, sc, task, sev = r[:7]
        if not text.startswith("`(heuristic)` "):
            bad.append(f"{fid}: not labelled (heuristic)")
        if not SCR_RE.match(scr):
            bad.append(f"{fid}: SCR {scr!r}")
        if not SC_RE.match(sc):
            bad.append(f"{fid}: SC {sc!r}")
        if task not in tasks:
            bad.append(f"{fid}: task {task!r}")
        if sev not in SEVERITIES:
            bad.append(f"{fid}: severity {sev!r}")
    return bad


def g_keys(t: L.Tree) -> list[str]:
    """AC4: a blocker carries the keystroke sequence that produced it."""
    return [
        f"{r[0]}: a blocker without keystrokes"
        for r in f_rows(t.text("memo"))
        if len(r) > 7 and r[6] == "blocker" and r[7] in ("", "—")
    ]


@functools.cache
def register() -> dict[str, dict[str, object]]:
    reg = json.loads(base_text(REG_REL))
    return {str(f["id"]): f for f in reg["findings"]}


def g_d02(t: L.Tree) -> list[str]:
    reg, memo = register(), t.text("memo")
    bad = [
        f"{i} is not in the register" for i in sorted(set(REG_ID_RE.findall(memo))) if i not in reg
    ]
    for r in f_rows(memo):
        if len(r) < 9 or r[8] == "new":
            continue
        f = reg.get(r[8])
        if f is None:
            bad.append(f"{r[0]}: {r[8]!r} is neither new nor a register id")
            continue
        screens = {str(s) for s in f["screens"]} if isinstance(f["screens"], list) else set()
        if not screens & set(r[2].split(", ")):
            bad.append(f"{r[0]}: {r[8]} names none of {r[2]}")
        if f.get("status") == "fixed":
            bad.append(f"{r[0]}: {r[8]} is fixed")
    return bad


def g_route(t: L.Tree) -> list[str]:
    """One named ticket or engineering-only per finding; tickets or the owner elsewhere."""
    memo = t.text("memo")
    bad = [
        f"{r[0]}: route {r[9]!r}" for r in f_rows(memo) if len(r) > 9 and not ROUTE_RE.match(r[9])
    ]
    for heading, col in (("## 7.", 3), ("## 8.", 4), ("### 13.2", 2), ("### 13.3", 2)):
        bad += [
            f"{r[0]}: owner {r[col]!r}"
            for r in rows_of(memo, heading)
            if len(r) <= col or not OWNER_RE.match(r[col])
        ]
    return bad


COUNTS_RE = re.compile(
    r"blocker (\d+) · major (\d+) · minor (\d+) · total (\d+); new to the register (\d+)"
    r"[^;]*; cited from it (\d+)\. Tasks: completable (\d+), blocker (\d+), not built at the sha"
    r" (\d+)\."
)


def g_counts(t: L.Tree) -> list[str]:
    """Section 3.1 equals the tables; G-ROWS and G-TASKS own the vocabularies."""
    memo = t.text("memo")
    rows, tasks = f_rows(memo), task_rows(memo)
    if any(len(r) < 9 or r[6] not in SEVERITIES for r in rows):
        return []
    if any(len(r) < 4 or r[3] not in VERDICTS for r in tasks):
        return []
    m = COUNTS_RE.search(L.section(memo, "### 3.1"))
    if m is None:
        return ["section 3.1 has no counts sentence"]
    want = [sum(1 for r in rows if r[6] == s) for s in SEVERITIES] + [len(rows)]
    new = sum(1 for r in rows if r[8] == "new")
    want += [new, len(rows) - new] + [sum(1 for r in tasks if r[3] == v) for v in VERDICTS]
    got = [int(g) for g in m.groups()]
    return [] if got == want else [f"counts {got}, tables say {want}"]


def g_sc(t: L.Tree) -> list[str]:
    """Section 3.2: every screened criterion has a row, a source and a status in the vocabulary."""
    rows = rows_of(t.text("memo"), "### 3.2")
    named = {sc for r in rows for sc in re.findall(r"\b\d\.\d+\.\d+\b", r[0])}
    bad = [f"{sc} has no row" for sc in SC_SCREEN if sc not in named]
    for r in rows:
        if len(r) != 4 or not r[2]:
            bad.append(f"{r[0]}: {len(r)} cells or no source")
        elif not r[3].startswith(SC_STATUS):
            bad.append(f"{r[0]}: status {r[3][:40]!r}")
    fids = {r[0] for r in f_rows(t.text("memo"))}
    bad += [f"{r[0]}: {f} is no F row" for r in rows for f in re.findall(r"F-\d+", r[3])
            if f not in fids]  # fmt: skip
    return bad


def g_t2(t: L.Tree) -> list[str]:
    """Section 3.3: the T2 standing gate is stated against every AD and TOP-1, TOP-2."""
    memo = t.text("memo")
    note = L.section(memo, "### 3.3 T2 applicability")
    if not note.strip():
        return ["section 3.3 (T2 applicability) is missing"]
    ads = [r[0] for r in rows_of(memo, "## 8.")]
    want = (*T2_ITEMS, *ads)
    return [f"section 3.3 does not name {w}" for w in want if w not in note]


@functools.cache
def d07_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("e47_d07_for_d01", ROOT / D07_TOOL_REL)
    if spec is None or spec.loader is None:
        raise L.AuditError(f"{D07_TOOL_REL} cannot be loaded")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(mod)
    return mod


def per_minute(n: int) -> str:
    v = n * 60_000 / WINDOW_MS
    return str(int(v)) if v == int(v) else f"{v:.1f}"


@functools.cache
def flood() -> dict[str, list[str]]:
    """Setting label -> the memo's three cells, re-derived by E47-D07's own replay."""
    mod, spec = d07_module(), base_text(D07_REL)
    doc = json.loads(base_text(D07_JSON_REL))
    fast = next(s for s in doc["scripts"] if s["id"] == "fast")
    script = {**fast, "duration_ms": WINDOW_MS}
    out: dict[str, list[str]] = {}
    for label, cell in FLOOD_ROWS.items():
        polite: list[int] = []
        assertive = 0
        for cad in CADENCES:
            st = {**fast["settings"], "reduce": False, **mod.CELLS[cell], "cadence_ms": cad}
            lines = [ln for ln in mod.replay(spec, doc, script, st).lines if ln.t < WINDOW_MS]
            polite.append(sum(1 for ln in lines if ln.channel == "polite"))
            assertive = sum(1 for ln in lines if ln.channel == "assertive")
        out[label] = [" / ".join(map(str, polite)), per_minute(polite[1]), str(assertive)]
    return out


def g_flood(t: L.Tree) -> list[str]:
    rows = {r[0]: r[1:4] for r in rows_of(t.text("memo"), "## 5.")}
    want = flood()
    bad = [] if list(rows) == list(want) else [f"settings {list(rows)}"]
    return bad + [f"{k}: {rows.get(k)} vs {v}" for k, v in want.items() if rows.get(k) != v]


def cites(memo: str) -> list[L.Cite]:
    out: list[L.Cite] = []
    for m in CITE_RE.finditer(memo):
        lo = int(m.group("first"))
        out.append(L.Cite(m.group("key"), lo, int(m.group("end") or lo), m.group(0)))
    return out


def g_cite(t: L.Tree) -> list[str]:
    found = cites(t.text("memo"))
    unknown = sorted({c.raw for c in found if docs().ref(c.doc) is None})
    return (
        unknown
        + L.check_cites(found, docs(), min_count=MIN_CITES)
        + L.check_key_cites(PINS, docs())
    )


def g_checklist(t: L.Tree) -> list[str]:
    items = re.findall(r"^\d+\. ", L.section(t.text("memo"), "## 12."), re.MULTILINE)
    return [] if 1 <= len(items) <= 10 else [f"{len(items)} checklist items, not 1..10"]


def g_noclose(t: L.Tree) -> list[str]:
    return L.closing_keywords(t.named("memo", "tool", "test"))


def g_public(t: L.Tree) -> list[str]:
    """No local path, host or name; URLs only in the public scan (section 6)."""
    memo = t.text("memo")
    scan = L.section(memo, "## 6.")
    rest = memo.replace(scan, "", 1) if scan else memo
    bad = L.scan_public([("memo", rest), *t.named("tool", "test")])
    bad += L.scan_public([("memo section 6", scan)], L.public_re(omit=("url", "www")))
    bad += L.comment_findings(t.named("memo"))
    return bad + L.whitespace_hygiene(t.named("memo", "tool", "test"))


def g_untouched(t: L.Tree) -> list[str]:
    return L.untouched(t.changed, OWN)


def g_mutlist(t: L.Tree) -> list[str]:
    return L.check_mutlist(t.text("memo"), "## 14.", MUTATIONS)


GATES = (
    L.Gate("G-AC", g_ac),
    L.Gate("G-BQ", g_bq),
    L.Gate("G-TASKS", g_tasks),
    L.Gate("G-ROWS", g_rows),
    L.Gate("G-KEYS", g_keys),
    L.Gate("G-D02", g_d02),
    L.Gate("G-ROUTE", g_route),
    L.Gate("G-COUNTS", g_counts),
    L.Gate("G-SC", g_sc),
    L.Gate("G-T2", g_t2),
    L.Gate("G-FLOOD", g_flood),
    L.Gate("G-CITE", g_cite),
    L.Gate("G-CHECKLIST", g_checklist),
    L.Gate("G-NOCLOSE", g_noclose),
    L.Gate("G-PUBLIC", g_public),
    L.Gate("G-UNTOUCHED", g_untouched),
    L.Gate("G-MUTLIST", g_mutlist),
)


# ---------- mutations -----------------------------------------------------------------------------
def _blocker_without_keys(t: L.Tree) -> L.Tree:
    """F-1 made a blocker with no keystrokes; the counts sentence follows, so only G-KEYS trips."""
    m = L.Mutation(
        "M-6",
        "G-KEYS",
        "",
        "memo",
        r"(\| T9 +\| )major(    \| — +\| new )",
        r"\1blocker\2",
        regex=True,
    )
    t = L.apply_mutation(t, m)
    return L.apply_mutation(
        t, L.Mutation("M-6", "G-KEYS", "", "memo", "blocker 0 · major 6", "blocker 1 · major 5")
    )


_M = L.Mutation
_PEND = BQ_HEADING.removeprefix("## ")
# fmt: off
MUTATIONS = (
    _M("M-1", "G-AC", "a scenario name reworded", "memo",
       '"Study executed against the real build"', '"Study run against the real build"'),
    _M("M-2", "G-BQ", "the BQ heading says RULED", "memo", _PEND,
       f"BQ list — RULED (comment {BQ_LIST})"),
    _M("M-3", "G-TASKS", "a task verdict outside the vocabulary", "memo",
       r"(\| SCR-013 \(CMP-094\) +\| )completable ", r"\1done        ", regex=True),
    _M("M-4", "G-ROWS", "a finding loses its heuristic label", "memo",
       "| F-1 | `(heuristic)` A trader", "| F-1 | A trader"),
    _M("M-5", "G-ROWS", "a finding with an unknown severity", "memo",
       r"\| major( +\| — +\| new +\| E47-S08)", r"| severe\1", regex=True),
    _M("M-6", "G-KEYS", "a blocker without its keystrokes", "memo", fn=_blocker_without_keys),
    _M("M-7", "G-D02", "a register id that does not exist", "memo",
       r"\| A11Y-F-0018( +\|)", r"| A11Y-F-0999\1", regex=True),
    _M("M-8", "G-ROUTE", "a finding routed to an agent", "memo",
       r"(\| new +\| )E47-S08 \(#1322\)", r"\1a design agent ", regex=True),
    _M("M-9", "G-COUNTS", "the baseline counts drift", "memo",
       "major 6 · minor 3", "major 7 · minor 3"),
    _M("M-10", "G-FLOOD", "a synthetic count edited by hand", "memo",
       "| 23 / 23 / 22 ", "| 20 / 23 / 22 "),
    _M("M-11", "G-CITE", "a cite past the end of its document", "memo", "`D13`:7", "`D13`:70000"),
    _M("M-12", "G-CHECKLIST", "an eleventh checklist item", "memo",
       "10. Comment `approved`", "11. One more.\n10. Comment `approved`"),
    _M("M-13", "G-NOCLOSE", "a closing keyword", "memo",
       "## 15. References", "Clo" + "ses #1300.\n\n## 15. References"),
    _M("M-14", "G-PUBLIC", "a local path", "memo",
       "Nothing is written under", "Nothing in /" + "home/x is written under"),
    _M("M-15", "G-PUBLIC", "a URL outside the public scan", "memo",
       "Nothing is written under", "See <" + "http" + "s://example.org>. Nothing is written under"),
    _M("M-16", "G-UNTOUCHED", "an owner document edited", "@changed",
       "", "docs/plan/05-accessibility-standard.md"),
    _M("M-17", "G-MUTLIST", "the list drifts", "memo", "| M-1  | G-AC ", "| M-1  | G-BQ "),
    _M("M-18", "G-ROWS", "a finding without its SC", "memo",
       r"(\| CMP-094 \| )2\.4\.6( +\| T9 )", r"\1     \2", regex=True),
    _M("M-19", "G-SC", "an AA criterion drops off the screen", "memo",
       "| 2.5.7 Dragging movements ", "| Dragging movements       "),
    _M("M-20", "G-T2", "the T2 applicability note is missing", "memo",
       "### 3.3 T2 applicability", "### 3.3 Notes"),
)
# fmt: on


# ---------- modes ---------------------------------------------------------------------------------
def read_tree() -> L.Tree:
    base = repo().diff_base(BASE)
    return L.Tree(
        files={
            k: (ROOT / rel).read_text(encoding="utf-8")
            for k, rel in zip(("memo", "tool", "test"), OWN, strict=True)
        },
        changed=repo().changed_paths(base),
    )


def check() -> int:
    return L.report(L.run_gates(GATES, read_tree()))


def self_test() -> int:
    disk = [ROOT / rel for rel in OWN]
    return L.self_test(read_tree(), GATES, MUTATIONS, disk, namespace=globals())


def main(argv: list[str]) -> int:
    return L.cli(argv, {"check": check, "self-test": self_test}, __doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
