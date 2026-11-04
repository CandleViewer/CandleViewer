#!/usr/bin/env python3
"""E47-D01 (#1300) audit: the keyboard-only and screen-reader baseline research memo.

Offline and default-deny. The shared gates (git, cites, closing keywords, hygiene, public text,
G-UNTOUCHED, the runner and the mutation harness) live in `spec_audit_lib.py` on main; this file
keeps only E47-D01's rows. It reads, AS TEXT at the pinned base, the plan, design, register, QA
and code texts the memo cites; from the working tree, the memo and this tool. G-REVIEW loads one
repo module, the merged E47-D02 `catalogue.py`, and parses section 3 as the register will.

Gates: G-AC, G-BQ (the RULED heading and each verdict of the ruling of record), G-TASKS (T1..T10,
the verdict vocabulary, a T04 oracle per task), G-ROWS, G-KEYS, G-REVIEW, G-D02 (section 3.1's
cited ids against the register), G-ROUTE, G-COUNTS, G-SC, G-T2, G-FLOOD (section 5 quotes
E47-D07's matrix and spacing), G-SCAN (section 6's E19-D01 BQ-12 form), G-AT (the `05` section
8.1 rows and the four output channels), G-CITE, G-CHECKLIST, G-NOCLOSE, G-PUBLIC, G-UNTOUCHED and
G-MUTLIST (section 14 equals this tool's list).
The BQ list is comment 6634720172; its ruling of record is comment 6637509239.

Usage (from the repo root):
  python3 -I -B docs/design/_tools/e47_d01_research_audit.py --check | --self-test | --repin
`--repin` prints where each pinned cite's words stand now. Exit 0 = no FAIL; 1 = a FAIL.
"""

from __future__ import annotations

import functools
import json
import re
import sys
from pathlib import Path
from types import ModuleType

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_audit_lib as L  # the shared helper sits beside this file

ROOT = Path(__file__).resolve().parents[3]
BASE = "aa0a02b8c54c877c39718f101abf69467cb4a2d6"  # origin/main the memo cites
BQ_LIST = "6634720172"  # the BQ list on #1300
RULING = "6637509239"  # its ruling of record

MEMO_REL = "docs/research/a11y/47-keyboard-sr-baseline.md"
TOOL_REL = "docs/design/_tools/e47_d01_research_audit.py"
OWN = (MEMO_REL, TOOL_REL)
REG_REL = "docs/plan/a11y/47-audit-register.json"
CAT_TOOL_REL = "docs/plan/a11y/_tools/catalogue.py"
E47J_REL = "docs/plan/backlog/E47.json"
D07_REL = "docs/design/E47/E47-D07.md"
SR = "docs/qa/a11y/sr/scripts/"

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
    "XC": L.DocRef(SR + "00-cross-cutting.md", BASE),
    "CDC": L.DocRef(SR + "10-chart-data-cursor.md", BASE),
    "FPI": L.DocRef(SR + "20-footprint-inspection.md", BASE),
    "DOM": L.DocRef(SR + "30-dom-ladder.md", BASE),
    "RFE": L.DocRef(SR + "40-rule-form-editor.md", BASE),
    "README": L.DocRef("docs/design/README.md", BASE),
    "CONST": L.DocRef("CONSTITUTION.md", BASE),
}
# A backticked key, a colon, a line or an en-dash range: `05`:185, `KMAP`:615 to 618.
CITE_RE = re.compile(r"`(?P<key>\d\d|[A-Z][A-Z0-9]*)`:(?P<first>\d+)(?:\u2013(?P<end>\d+))?")
MIN_CITES = 90  # a broken grammar parses far fewer
PINS = (  # load-bearing cites: the needle must stand on the cited line (`--repin` moves them)
    L.KeyCite("05", 64, "Ctrl+Shift+F"),
    L.KeyCite("05", 185, "default 1 update / 2s per field"),
    L.KeyCite("05", 263, "NVDA 2024.x"),
    L.KeyCite("05", 266, "VoiceOver"),
    L.KeyCite("05", 278, "rule-engine flatten"),
    L.KeyCite("05", 282, "Defect severity bar"),
    L.KeyCite("05", 293, "counts"),
    L.KeyCite("10", 164, "screen reader or high zoom"),
    L.KeyCite("10", 250, "node-graph canvas"),
    L.KeyCite("CAT", 9, "4 blocker, 26 major, 64 minor, 12 info"),
    L.KeyCite("KMAP", 615, "positions.close_all"),
    L.KeyCite("KMAP", 337, "chart.table_toggle"),
    L.KeyCite("MODEL", 25, 'announce_prices: "significant"'),
    L.KeyCite("PW", 103, "significant = false"),
    L.KeyCite("D05", 382, "D05-G4"),
    L.KeyCite("D07", 638, "D07-Q2"),
    L.KeyCite("D07", 639, "5.47"),
    L.KeyCite("D09", 417, "D09-G1"),
    L.KeyCite("CHS", 31, "focus returns"),
    L.KeyCite("SRR", 28, "SURFACE PENDING"),
    L.KeyCite("SRR", 32, "Capture procedure"),
    L.KeyCite("XC", 36, "XC-04"),
    L.KeyCite("RFE", 38, "RFE-06"),
)

SCENARIOS_RE = re.compile(r"^\s*Scenario: (.+)$", re.MULTILINE)
BQ_HEADING = f"## BQ list — RULED (comment {RULING})"
RULED = (  # the ruling of record's verdict per BQ-0..BQ-9
    "AGREE +rider", "AGREE", "AGREE +rider", "AGREE +rider", "AMEND",
    "AGREE +rider", "AGREE +rider", "AGREE", "AMEND", "AGREE +rider",
)  # fmt: skip
VERDICTS = ("completable", "blocker", "not built at the sha")
ORACLE_RE = re.compile(r"^(?:none|[A-Z]{2,3}-\d\d\b.*)$")
SEVERITIES = ("blocker", "major", "minor", "info")
SCR_RE = re.compile(r"^SCR-\d{3}(?:, SCR-\d{3})*$")
SC_RE = re.compile(r"^(?:\d\.\d+\.\d+(?:, \d\.\d+\.\d+)*|n/a \(usability, `\d\d`:\d+\))$")
REG_ID_RE = re.compile(r"A11Y-(?:F-\d{4}|R-E\d\d-D\d\d-F-\d\d)")
REMINT_RE = re.compile(r"A11Y-|\bD01-\d")  # a review row never carries another id scheme
KEYS_RE = re.compile(r"keystrokes: `[^`]+`")
TICKET = r"E\d\d-[A-Z]\d\d \(#\d+\)"
REVIEW_OWNER_RE = re.compile(r"^(?:E47-D(?:0[3-9]|10)|engineering-only \(.+\))$")
OWNER_RE = re.compile(rf"^(?:{TICKET}(?:, {TICKET})*|owner.*|E\d\d-[A-Z]\d\d, E\d\d-[A-Z]\d\d)$")
MARKER_RE = re.compile(r"<!-- audit:f=(\d+)/(\d+)/(\d+)/(\d+)/(\d+) -->", re.DOTALL)
MARKER_BODY = re.compile(r" audit:f=\d+/\d+/\d+/\d+/\d+ ", re.DOTALL)
SIM_CELL_RE = re.compile(r"^\| (?P<label>[^|]+?) +\|.*\| (?P<n>\d+)<!--=SIM:cell\.", re.DOTALL)
SIM_SPACING_RE = re.compile(r"(\d+\.\d+)<!--=SIM:fast\.spacing-[125]s-->", re.DOTALL)
SC_SCREEN = (  # the AA criteria that decide a keyboard and SR trading UI (section 3.3)
    "1.4.1", "1.4.3", "1.4.10", "2.1.1", "2.1.2", "2.4.3", "2.4.5", "2.4.6", "2.4.7", "2.4.11",
    "2.5.7", "2.5.8", "3.2.1", "3.2.2", "3.3.4", "3.3.8", "4.1.2", "4.1.3",
)  # fmt: skip
SC_STATUS = (
    "finding: F-", "register: A11Y-", "no finding (heuristic)", "not assessable at the sha",
    "not assessed: ",
)  # fmt: skip
T2_ITEMS = ("G-T2.1b", "G-T2.1c", "G-T2.3", "TOP-1", "TOP-2")
CHANNELS = ("CH-SPEECH", "CH-BRAILLE", "CH-SPEECH-VIEWER", "CH-AT-LOG")
AT_ROWS = {f"AT-{i}": (f"#{i}", f"`05`:{262 + i}") for i in range(1, 5)}  # 05 section 8.1
DATE_RE = re.compile(r"\b20\d\d-\d\d-\d\d\b")
URL_CELL_RE = re.compile(r"^<http[s]://[^ >]+>$")


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
    """Section 3's review table: F, Task, CMP, Evidence, Screen, Clause, Severity, Sentence,
    Owner."""
    return rows_of(memo, "## 3.")


def task_rows(memo: str) -> list[list[str]]:
    return rows_of(memo, "## 2.")


def task_ids(cell: str) -> list[str]:
    return [x.strip() for x in cell.split(",")]


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
    """The RULED heading; BQ-0..BQ-9 each carry the ruling of record's verdict."""
    memo = t.text("memo")
    bad = [] if BQ_HEADING + "\n" in memo else ["the BQ heading is not the RULED form"]
    rows = rows_of(memo, "## BQ list")
    if [r[0] for r in rows] != [f"BQ-{i}" for i in range(10)]:
        return [*bad, f"BQ rows {[r[0] for r in rows]}"]
    return bad + [
        f"{r[0]}: verdict {r[2]!r}, the ruling says {v!r}"
        for r, v in zip(rows, RULED, strict=True)
        if len(r) < 3 or r[2] != v
    ]


def g_tasks(t: L.Tree) -> list[str]:
    rows = task_rows(t.text("memo"))
    bad = [] if [r[0] for r in rows] == [f"T{i}" for i in range(1, 11)] else ["T1..T10 order"]
    for r in rows:
        if len(r) != 7:
            bad.append(f"{r[0]}: {len(r)} cells")
            continue
        if r[3] not in VERDICTS:
            bad.append(f"{r[0]}: verdict {r[3]!r}")
        if not ORACLE_RE.match(r[5]):
            bad.append(f"{r[0]}: T04 oracle {r[5]!r}")
    return bad


def g_rows(t: L.Tree) -> list[str]:
    memo = t.text("memo")
    tasks = {r[0] for r in task_rows(memo)}
    rows = f_rows(memo)
    bad = [] if [r[0] for r in rows] == [f"F-{i}" for i in range(1, len(rows) + 1)] else ["F ids"]
    for r in rows:
        if len(r) != 9:
            bad.append(f"{r[0]}: {len(r)} cells")
            continue
        fid, task, _cmp, _ev, scr, sc, sev, sentence, _owner = r
        if not sentence.startswith("`(heuristic)` "):
            bad.append(f"{fid}: not labelled (heuristic)")
        if REMINT_RE.search(" ".join(r)):
            bad.append(f"{fid}: carries a register or D01-nn id (cite it in 3.1, never re-mint)")
        if not SCR_RE.match(scr):
            bad.append(f"{fid}: Screen {scr!r}")
        if not SC_RE.match(sc):
            bad.append(f"{fid}: Clause {sc!r}")
        if task not in tasks:
            bad.append(f"{fid}: task {task!r}")
        if sev not in SEVERITIES:
            bad.append(f"{fid}: severity {sev!r}")
    return bad


def g_keys(t: L.Tree) -> list[str]:
    """AC4 and BQ-4: a blocker's Sentence carries the keystroke sequence that produced it."""
    return [
        f"{r[0]}: a blocker without keystrokes in its Sentence"
        for r in f_rows(t.text("memo"))
        if len(r) == 9 and r[6] == "blocker" and not KEYS_RE.search(r[7])
    ]


@functools.cache
def catalogue() -> ModuleType:
    return L.load_module(ROOT, CAT_TOOL_REL, "e47_d02_catalogue_for_d01")


@functools.cache
def register() -> dict[str, dict[str, object]]:
    reg = json.loads(base_text(REG_REL))
    return {str(f["id"]): f for f in reg["findings"]}


@functools.cache
def review_sev_map() -> dict[str, str]:
    reg = json.loads(base_text(REG_REL))
    return {str(k): str(v) for k, v in reg["severityMap"]["review"].items()}


def g_review(t: L.Tree) -> list[str]:
    """BQ-4: the merged catalogue parses section 3 into A11Y-R-E47-D01-F-n, counts included."""
    memo = t.text("memo")
    rows = f_rows(memo)
    if any(len(r) != 9 or r[6] not in SEVERITIES for r in rows):
        return []  # G-ROWS owns the shape and the vocabulary
    cat = catalogue()
    try:
        found: list[dict[str, object]] = cat.review_findings("E47-D01", memo, review_sev_map())
    except cat.CatalogueError as exc:
        return [f"catalogue.py refuses the memo: {exc}"]
    want = [f"A11Y-R-E47-D01-{r[0]}" for r in rows]
    bad = [] if [f["id"] for f in found] == want else [f"parsed {[f['id'] for f in found]}"]
    for r, f in zip(rows, found, strict=False):
        if f["screens"] != sorted(set(r[4].split(", "))):
            bad.append(f"{r[0]}: screens parse as {f['screens']}")
        if f["remediation"] != r[8]:
            bad.append(f"{r[0]}: owner parses as {f['remediation']!r}")
    return bad


def g_d02(t: L.Tree) -> list[str]:
    """Section 3.1 cites open register findings by id, with the register's severity and owner."""
    reg, memo = register(), t.text("memo")
    bad = [
        f"{i} is not in the register" for i in sorted(set(REG_ID_RE.findall(memo))) if i not in reg
    ]
    for r in rows_of(memo, "### 3.1"):
        f = reg.get(r[0])
        if f is None or len(r) != 6:
            bad.append(f"3.1 {r[0]}: not a register id, or {len(r)} cells")
            continue
        screens = {str(s) for s in f["screens"]} if isinstance(f["screens"], list) else set()
        if not set(r[1].split(", ")) <= screens:
            bad.append(f"3.1 {r[0]}: {r[1]} is not within the register's screens")
        if f.get("status") == "fixed":
            bad.append(f"3.1 {r[0]}: fixed in the register")
        if r[3] != f.get("severity") or r[4] != f.get("designOwner"):
            bad.append(f"3.1 {r[0]}: {r[3]} / {r[4]} differ from the register")
    return bad


def g_route(t: L.Tree) -> list[str]:
    """Review rows in the register's owner vocabulary; tickets or the owner elsewhere."""
    memo = t.text("memo")
    bad = [
        f"{r[0]}: owner {r[8]!r}"
        for r in f_rows(memo)
        if len(r) == 9 and not REVIEW_OWNER_RE.match(r[8])
    ]
    for heading, col in (("## 7.", 3), ("## 8.", 4), ("### 13.2", 2), ("### 13.3", 2)):
        bad += [
            f"{r[0]}: owner {r[col]!r}"
            for r in rows_of(memo, heading)
            if len(r) <= col or not OWNER_RE.match(r[col])
        ]
    return bad


COUNTS_RE = re.compile(
    r"D01 heuristic rows: blocker (\d+) · major (\d+) · minor (\d+) · info (\d+) · total (\d+);"
    r" register findings cited (\d+), never re-minted\. Tasks: completable (\d+), blocker (\d+),"
    r" not built at the sha (\d+)\."
)


def g_counts(t: L.Tree) -> list[str]:
    """Section 3.2 equals the tables; G-ROWS, G-TASKS and G-REVIEW own the rest."""
    memo = t.text("memo")
    rows, tasks = f_rows(memo), task_rows(memo)
    if any(len(r) != 9 or r[6] not in SEVERITIES for r in rows):
        return []
    if any(len(r) != 7 or r[3] not in VERDICTS for r in tasks):
        return []
    m = COUNTS_RE.search(L.section(memo, "### 3.2"))
    if m is None:
        return ["section 3.2 has no counts sentence"]
    want = [sum(1 for r in rows if r[6] == s) for s in SEVERITIES] + [len(rows)]
    want += [len(rows_of(memo, "### 3.1"))]
    want += [sum(1 for r in tasks if r[3] == v) for v in VERDICTS]
    got = [int(g) for g in m.groups()]
    return [] if got == want else [f"counts {got}, tables say {want}"]


def g_sc(t: L.Tree) -> list[str]:
    """Section 3.3: every screened criterion has a row, a source and a status in the vocabulary."""
    rows = rows_of(t.text("memo"), "### 3.3")
    named = {sc for r in rows for sc in re.findall(r"\b\d\.\d+\.\d+\b", r[0])}
    bad = [f"{sc} has no row" for sc in SC_SCREEN if sc not in named]
    for r in rows:
        if len(r) != 4 or not r[2]:
            bad.append(f"{r[0]}: {len(r)} cells or no source")
        elif not r[3].startswith(SC_STATUS):
            bad.append(f"{r[0]}: status {r[3][:40]!r}")
    fids = {r[0] for r in f_rows(t.text("memo"))}
    bad += [f"{r[0]}: {f} is no F row" for r in rows for f in re.findall(r"(?<![\w-])F-\d+", r[3])
            if f not in fids]  # fmt: skip
    return bad


def g_t2(t: L.Tree) -> list[str]:
    """Section 3.4: the T2 standing gate is stated against every AD and TOP-1, TOP-2."""
    memo = t.text("memo")
    note = L.section(memo, "### 3.4 T2 applicability")
    if not note.strip():
        return ["section 3.4 (T2 applicability) is missing"]
    ads = [r[0] for r in rows_of(memo, "## 8.")]
    want = (*T2_ITEMS, *ads)
    return [f"section 3.4 does not name {w}" for w in want if w not in note]


@functools.cache
def d07_quotes() -> tuple[list[list[str]], str]:
    """E47-D07's matrix rows (label, field reads) and its spacing sentence, at the base."""
    d07 = base_text(D07_REL)
    rows = [[m["label"], m["n"]] for ln in d07.split("\n") if (m := SIM_CELL_RE.match(ln))]
    spacing = " / ".join(SIM_SPACING_RE.findall(d07)[:3])  # 1 s, 2 s, 5 s
    return rows, spacing


def g_flood(t: L.Tree) -> list[str]:
    """BQ-6: section 5 quotes D07's matrix and spacing; it runs no simulator of its own."""
    section = L.section(t.text("memo"), "## 5.")
    want, spacing = d07_quotes()
    bad = [] if len(want) == 7 else [f"{len(want)} matrix rows in D07, not 7"]
    if L.table_rows(section) != want:
        bad.append(f"section 5 {L.table_rows(section)} vs D07 {want}")
    return bad + ([] if f"{spacing} s apart" in section else [f"spacing {spacing!r} not quoted"])


def g_scan(t: L.Tree) -> list[str]:
    """BQ-8: a URL and a fetched date per row, else "unsourced observation"."""
    bad: list[str] = []
    for r in rows_of(t.text("memo"), "## 6."):
        if "unsourced observation" in " ".join(r):
            continue
        if len(r) != 3 or not DATE_RE.search(r[0]) or not URL_CELL_RE.match(r[2]):
            bad.append(f"scan row {r[0][:40]!r}: no URL or fetched date")
    return bad


def g_at(t: L.Tree) -> list[str]:
    """The standing rider: `05` section 8.1 rows by number and the AT channels, stable names."""
    memo = t.text("memo")
    rows = {r[0]: r for r in rows_of(memo, "### 11.5")}
    bad = [] if list(rows) == list(AT_ROWS) else [f"AT rows {list(rows)}"]
    bad += [
        f"{k}: not {n}, {c}"
        for k, (n, c) in AT_ROWS.items()
        if k in rows and rows[k][1] != f"{n}, {c}"
    ]
    chans = [r[0] for r in rows_of(memo, "### 11.6")]
    return bad + ([] if chans == list(CHANNELS) else [f"channels {chans}"])


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
    return L.closing_keywords(t.named("memo", "tool"))


def g_public(t: L.Tree) -> list[str]:
    """No local path, host or name; URLs only in the public scan (section 6, BQ-8's regex);
    the one HTML comment is the review count marker."""
    memo = t.text("memo")
    scan = L.section(memo, "## 6.")
    rest = memo.replace(scan, "", 1) if scan else memo
    bad = L.scan_public([("memo", rest), *t.named("tool")])
    bad += L.scan_public([("memo section 6", scan)], L.public_re(omit=("url", "www")))
    bad += L.comment_findings(t.named("memo"), MARKER_BODY)
    bad += [] if len(MARKER_RE.findall(memo)) == 1 else ["not exactly one count marker"]
    return bad + L.whitespace_hygiene(t.named("memo", "tool"))


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
    L.Gate("G-REVIEW", g_review),
    L.Gate("G-D02", g_d02),
    L.Gate("G-ROUTE", g_route),
    L.Gate("G-COUNTS", g_counts),
    L.Gate("G-SC", g_sc),
    L.Gate("G-T2", g_t2),
    L.Gate("G-FLOOD", g_flood),
    L.Gate("G-SCAN", g_scan),
    L.Gate("G-AT", g_at),
    L.Gate("G-CITE", g_cite),
    L.Gate("G-CHECKLIST", g_checklist),
    L.Gate("G-NOCLOSE", g_noclose),
    L.Gate("G-PUBLIC", g_public),
    L.Gate("G-UNTOUCHED", g_untouched),
    L.Gate("G-MUTLIST", g_mutlist),
)


# ---------- mutations -----------------------------------------------------------------------------
def _blocker_without_keys(t: L.Tree) -> L.Tree:
    """F-1 made a blocker with no keystrokes; the marker and the counts follow, so only G-KEYS
    trips."""
    for find, repl, rx in (
        (r"(\| SCR-013 +\| 2\.4\.6 +\| )major", r"\1blocker", True),
        ("audit:f=4/0/3/1/0", "audit:f=4/1/2/1/0", False),
        ("blocker 0 · major 3", "blocker 1 · major 2", False),
    ):
        t = L.apply_mutation(t, L.Mutation("M-10", "G-KEYS", "", "memo", find, repl, regex=rx))
    return t


_M = L.Mutation
# fmt: off
MUTATIONS = (
    _M("M-1", "G-AC", "a scenario name reworded", "memo",
       '"Study executed against the real build"', '"Study run against the real build"'),
    _M("M-2", "G-BQ", "the BQ heading back to pending", "memo", BQ_HEADING,
       f"## BQ list — defaults built; ruling pending (comment {BQ_LIST})"),
    _M("M-3", "G-BQ", "a verdict that differs from the ruling", "memo",
       r"(\| Finding shape, severity, routing +\| )AMEND", r"\1AGREE", regex=True),
    _M("M-4", "G-TASKS", "a task verdict outside the vocabulary", "memo",
       r"(\| SCR-013 \(CMP-094\) +\| )completable ", r"\1done        ", regex=True),
    _M("M-5", "G-TASKS", "a task without its T04 oracle", "memo",
       r"\| XC-04 \(`XC`:36\)", "| see T04         ", regex=True),
    _M("M-6", "G-ROWS", "a finding loses its heuristic label", "memo",
       "`(heuristic)` A trader", "A trader"),
    _M("M-7", "G-ROWS", "a finding with an unknown severity", "memo",
       r"(\| 3\.3\.4 +\| )major", r"\1severe", regex=True),
    _M("M-8", "G-ROWS", "a finding without its SC", "memo",
       r"(\| SCR-013 +\| )2\.4\.6", r"\1     ", regex=True),
    _M("M-9", "G-ROWS", "a review row re-mints a register id", "memo",
       "hears no ambient price at all:", "hears no ambient price at all (A11Y-F-0018):"),
    _M("M-10", "G-KEYS", "a blocker without its keystrokes", "memo", fn=_blocker_without_keys),
    _M("M-11", "G-REVIEW", "the review table's Sentence column renamed", "memo",
       r"(\| Severity \| )Sentence( +\| Owner)", r"\1Finding \2", regex=True),
    _M("M-12", "G-D02", "a register id that does not exist", "memo",
       r"\| A11Y-F-0018( +\|)", r"| A11Y-F-0999\1", regex=True),
    _M("M-13", "G-D02", "a cited severity differs from the register", "memo",
       r"(\| A11Y-F-0029 +\| SCR-123 +\| T8 +\| )minor", r"\1major", regex=True),
    _M("M-14", "G-ROUTE", "a review row routed outside the register's vocabulary", "memo",
       r"(\| )E47-D07( +\|\n\| F-4)", r"\1E47-S07\2", regex=True),
    _M("M-15", "G-COUNTS", "the baseline counts drift", "memo",
       "major 3 · minor 1", "major 4 · minor 1"),
    _M("M-16", "G-FLOOD", "a quoted D07 count edited by hand", "memo",
       r"(\| Always · Normal +\| )22", r"\g<1>20", regex=True),
    _M("M-17", "G-SCAN", "a scan row without its fetched date", "memo",
       "Browse Mode (2026-10-22, the E11-D07", "Browse Mode (the E11-D07"),
    _M("M-18", "G-AT", "an AT output channel dropped", "memo",
       r"\| CH-BRAILLE( +\|)", r"| CH-DISPLAY\1", regex=True),
    _M("M-19", "G-SC", "an AA criterion drops off the screen", "memo",
       "| 2.5.7 Dragging movements ", "| Dragging movements       "),
    _M("M-20", "G-T2", "the T2 applicability note is missing", "memo",
       "### 3.4 T2 applicability", "### 3.4 Notes"),
    _M("M-21", "G-CITE", "a cite past the end of its document", "memo", "`D13`:7", "`D13`:70000"),
    _M("M-22", "G-CHECKLIST", "an eleventh checklist item", "memo",
       "10. Comment `approved`", "11. One more.\n10. Comment `approved`"),
    _M("M-23", "G-NOCLOSE", "a closing keyword", "memo",
       "## 15. References", "Clo" + "ses #1300.\n\n## 15. References"),
    _M("M-24", "G-PUBLIC", "a local path", "memo",
       "Nothing is written under", "Nothing in /" + "home/x is written under"),
    _M("M-25", "G-PUBLIC", "a URL outside the public scan", "memo",
       "Nothing is written under", "See <" + "http" + "s://example.org>. Nothing is written under"),
    _M("M-26", "G-UNTOUCHED", "the register edited by this PR", "@changed", "", REG_REL),
    _M("M-27", "G-MUTLIST", "the list drifts", "memo", "| M-1  | G-AC ", "| M-1  | G-BQ "),
)
# fmt: on


# ---------- modes ---------------------------------------------------------------------------------
def read_tree() -> L.Tree:
    base = repo().diff_base(BASE)
    return L.Tree(
        files={
            k: (ROOT / rel).read_text(encoding="utf-8")
            for k, rel in zip(("memo", "tool"), OWN, strict=True)
        },
        changed=repo().changed_paths(base),
    )


def check() -> int:
    return L.report(L.run_gates(GATES, read_tree()))


def self_test() -> int:
    disk = [ROOT / rel for rel in OWN]
    return L.self_test(read_tree(), GATES, MUTATIONS, disk, namespace=globals())


def repin() -> int:
    for pin, now in L.repin_key_cites(PINS, docs()):
        print(f"{pin.doc}:{pin.line} -> {'gone' if now is None else now} {pin.needle!r}")
    return 0


def main(argv: list[str]) -> int:
    return L.cli(argv, {"check": check, "self-test": self_test, "repin": repin}, __doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
