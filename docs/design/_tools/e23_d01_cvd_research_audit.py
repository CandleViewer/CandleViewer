#!/usr/bin/env python3
"""E23-D01 (#610) audit: the UX-research memo on how traders read cumulative delta and divergence.

Offline and default-deny. The shared machinery (git, markdown tables, hygiene, the public-repo
scan, R7, G-T2 markers, the board cap, G-UNTOUCHED, the runner and the mutation harness) lives in
`spec_audit_lib.py`, imported from beside this file, never copied; this file keeps only E23-D01's
rows. It reads the memo and `14` from the working tree and every cited source AS TEXT at the base
pin (`git show BASE:path`); it executes no repo code.

Gates:
  G-SECTIONS  the H2 headings, in order (the BQ heading in its "ruling pending" form).
  G-CITE      every `KEY`:N, `KEY`:N-M and ", :N" tail names a declared key and resolves, on a
              non-blank line, at BASE; an undeclared backticked key before ":N" FAILs.
  G-QUOTE     every double-quoted string of QUOTE_MIN characters or more stands verbatim in a
              source its own line cites, or in this ticket's body; quotes pair on every line.
  G-AC        the three scenario names stand verbatim in the AC trace and in the ticket; every
              status cell is done, heuristic-only or open.
  G-BQ        the heading names the posted BQ comment; rows BQ-0..BQ-9, once each, in order.
  G-HEURISTIC every F row is `(heuristic)`, F-1..F-n in order; no participant, count, timing or
              rate is claimed anywhere; the header says no session was run.
  G-DEFAULTS  the section 6 rows carry the BQ list's ORCH-defaults, a cited evidence cell, a
              dissent with its override reason and the deciding probe.
  G-TESTABLE  AD-1..AD-12 in order; each has a satisfies clause, a "a wireframe violates it if"
              clause, a feeding F id and an owner ticket.
  G-R9        no R9 word in a display name, marker label or announcement; no direction or
              verdict word in a tooltip or popover cell; the word list equals R9_WORDS; the
              epic row and the tooltip's second line are cited.
  G-STATES    the eleven states in order, and the G-T2 markers in section 9.
  G-IDS       every id referenced is defined once (a table row's lead cell, or `Hn:`).
  G-OWNER     every `E23-Xnn #N` style pair matches the published map; owner cells name a
              ticket or the owner, never an agent.
  G-BOARDS    the board cap (spec_audit_lib.board_cap): at most ten, PENDING, named.
  G-WALK      the owner walkthrough has one to ten items and ends on `approved` on #610.
  G-HYGIENE   closing keywords, whitespace, public text, HTML comments, R7, no image embed, and
              "CVD" never written for colour vision.
  G-UNTOUCHED only the memo, this tool and `14` differ from the merge base; `14` gains exactly
              POINTER_LINE after SCR-052's sign-off checklist line.

Usage (from the repo root):
  python3 -I docs/design/_tools/e23_d01_cvd_research_audit.py --check | --self-test
Exit 0 = no FAIL; 1 = at least one FAIL. The report is ASCII.
"""

from __future__ import annotations

import functools
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_audit_lib as L  # the shared helper sits beside this file

ROOT = Path(__file__).resolve().parents[3]
BASE = "e7cc2dd2a1f8d70de462e0644a1e7e5aa02108a8"  # origin/main at the memo's base

MEMO_REL = "docs/design/research/e23-cvd-reading.md"
TOOL_REL = "docs/design/_tools/e23_d01_cvd_research_audit.py"
OWN = (MEMO_REL, TOOL_REL)
CAT_REL = "docs/plan/14-screens-catalogue.md"
TICKET_JSON = "docs/plan/backlog/E23.json"
PUBLISHED_JSON = "docs/plan/backlog/_tools/published.json"
TICKET_KEY = "E23-D01"
ISSUE = 610
BQ_COMMENT = "6652673585"
BQ_COUNT = 10
QUOTE_MIN = 12

KEYED = {
    "E23.json": TICKET_JSON,
    "E25D01": "docs/design/E25/E25-D01.md",
    "E25D05": "docs/design/E25/E25-D05.md",
    "E11D04": "docs/design/E11/E11-D04.md",
    "E14D05": "docs/design/E14/E14-D05.md",
    "E24R": "docs/design/research/e24-deriv-reading.md",
    "E18R": "docs/research/digests/e18-footprint-cell-reading.md",
    "DG01": "docs/research/digests/01-tradingview-charting.digest.md",
    "DG04": "docs/research/digests/04-deepcharts-deepchart.digest.md",
    "DG08": "docs/research/digests/08-crypto-data-metrics.digest.md",
    "FXR": "packages/fixtures/bybit/2026-10-05/README.trades.md",
    "FXM": "packages/fixtures/bybit/2026-10-05/manifest.json",
    "CONF": "packages/fixtures/golden/bars/conformance/README.md",
    "VOC": "services/api/candleviewer/rules/vocabulary/metrics.py",
    "README": "docs/design/README.md",
}

BQ_HEADING = f"## BQ list — defaults built; ruling pending (comment {BQ_COMMENT})"
SECTIONS = (
    f"## Acceptance-criteria trace ({TICKET_KEY}, issue #{ISSUE})",
    "## Deviations",
    BQ_HEADING,
    "## 0. Research boards (Penpot) — PENDING",
    "## 1. Method note (agent-delivery adaptation, owner decision 2026-09-25)",
    "## 2. Research questions and pre-registered hypotheses",
    "## 3. Heuristic evaluation (every finding `(heuristic)`)",
    "## 4. Persona walkthrough",
    "## 5. Competitive review (public knowledge via the merged digests)",
    "## 6. Recommended defaults with their dissent",
    "## 7. Adopted decisions AD-1..AD-12 (ranked; heuristic, PROPOSED)",
    "## 8. Divergence copy and the `(estimated)` proposal (R9)",
    "## 9. States checklist for E23-D02",
    "## 10. Downstream feeds",
    "## 11. Owner session protocol (ready to run; nothing below has been run)",
    "## 12. Owner walkthrough checklist",
    "## 13. Contradictions, gaps and open questions",
    "## 14. References",
)
SCENARIOS = (
    "Defaults are evidence-backed",
    "The advice boundary is addressed",
    "The manual anchor gesture is validated",
)
STATUS = frozenset({"done", "heuristic-only", "open"})
DEFAULT_PINS = (
    ("Reset anchor", "`session`"),
    ("Display mode", "line + per-bar histogram"),
    ("Smoothing", "off"),
)
DISSENT_WORDS = ("overrid", "refused", "not proposed")
AD_COUNT = 12
VIOLATES = "a wireframe violates it if "
R9_WORDS = (
    "bearish",
    "bullish",
    "buy",
    "sell",
    "long",
    "short",
    "signal",
    "confirmed",
    "entry",
    "exit",
    "reversal",
    "strong",
    "weak",
)
R9_TOOLTIP = tuple(w for w in R9_WORDS if w != "confirmed")  # a swing may be confirmed
TOOLTIP_LINE2 = '"Enter opens Why estimated?" (`E25D05`:135)'
EPIC_ROW = "(`E23.json`:33)"
STATES = (
    "partial history",
    "stale",
    "recorder-empty",
    "gapped bar",
    "provisional bar",
    "reset marker",
    "loading",
    "streaming",
    "candles disabled",
    "detection off",
    "table alternative",
)
PARTICIPANT_RE = re.compile(
    r"participants? (?:said|chose|preferred|found|read|kept)|we observed|was observed"
    r"|\d+ ?% of (?:participants|sessions|traders)|discovery rate (?:was|of) \d"
    r"|\d+ (?:of|out of) \d+ (?:participants|sessions|traders)",
    re.IGNORECASE,
)
COLOUR_CVD_RE = re.compile(r"CVD[- ](?:safe|simulation|type|pass|validation)|colou?r[- ]CVD")
AGENT_RE = re.compile(r"\b(?:agent|worker|orchestrator|lane)\b", re.IGNORECASE)
POINTER_LINE = (
    "- **UX research:** [e23-cvd-reading.md](../design/research/e23-cvd-reading.md) (E23-D01;"
    " heuristic walkthrough, no participants: PROPOSED session anchor with its boundary named,"
    " line + per-bar histogram, smoothing off, observation-only divergence labels with the"
    " `(estimated)` copy, the manual-anchor paths and the states checklist for E23-D02;"
    " contradictions C1–C10 and gaps G1–G7 for their owners)."
)
PRE_POINTER = "- **Design sign-off acceptance checklist:** [ ] CVD line"

CITE_RE = re.compile(
    r"`(?P<key>[A-Za-z0-9.]+)`:(?P<lo>\d+)(?:–(?P<hi>\d+))?(?P<more>(?:, :\d+(?:–\d+)?)*)"
)
MORE_RE = re.compile(r":(\d+)(?:–(\d+))?")
QUOTE_RE = re.compile(r'"([^"\n]*)"')
ID_RE = re.compile(r"(?<![\w-])(?:(F|AD|OQ|BQ)-(\d+)|(RQ|H|C|G|Q|W|A|L)(\d+))(?![\w])")
HDEF_RE = re.compile(r"(?<![\w-])H(\d+):")
PAIR_RE = re.compile(r"\b(E\d{2}-[DKQSTX]\d{2}) #(\d+)\b")


# ---------- sources -------------------------------------------------------------------------------
@functools.cache
def repo() -> L.Repo:
    return L.Repo(ROOT)


@functools.cache
def docs() -> L.Docs:
    return L.Docs(repo(), BASE, {k: L.DocRef(v, BASE) for k, v in KEYED.items()})


def at_base(rel: str) -> str:
    text = repo().show(BASE, rel)
    if text is None:
        raise L.AuditError(f"{rel} not readable at {BASE}")
    return text


def _strings(node: object) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in _strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in _strings(v)]
    return []


@functools.cache
def source_text(key: str) -> str:
    """A cited document's full text at BASE; the ticket JSON adds its decoded strings."""
    lines = docs().lines(key)
    if lines is None:
        return ""
    text = "\n".join(lines)
    if key == "E23.json":
        text += "\n" + "\n".join(_strings(json.loads(text)))
    return text


def ticket_body() -> str:
    for t in json.loads(at_base(TICKET_JSON)):
        if isinstance(t, dict) and t.get("key") == TICKET_KEY:
            return str(t.get("body", ""))
    raise L.AuditError(f"{TICKET_KEY} not in {TICKET_JSON}")


# ---------- markdown helpers ----------------------------------------------------------------------
def rows(memo: str, heading: str) -> list[list[str]]:
    return L.table_rows(L.section(memo, heading))


def lead(row: list[str]) -> str:
    return row[0].replace("*", "").replace("`", "").strip() if row else ""


def cites(text: str) -> list[tuple[str, int, int, str]]:
    out: list[tuple[str, int, int, str]] = []
    for m in CITE_RE.finditer(text):
        lo = int(m.group("lo"))
        out.append((m.group("key"), lo, int(m.group("hi") or lo), m.group(0)))
        for a, b in MORE_RE.findall(m.group("more") or ""):
            out.append((m.group("key"), int(a), int(b or a), m.group(0)))
    return out


def declared(key: str) -> bool:
    return key in KEYED or re.fullmatch(r"\d\d", key) is not None


# ---------- gates ---------------------------------------------------------------------------------
def g_sections(t: L.Tree) -> list[str]:
    got = [ln for ln in t.text("memo").split("\n") if ln.startswith("## ")]
    return [] if got == list(SECTIONS) else [f"H2 list differs: {got}"]


def g_cite(t: L.Tree) -> list[str]:
    found = cites(t.text("memo"))
    bad = [f"{raw} (undeclared key)" for key, _, _, raw in found if not declared(key)]
    good = [L.Cite(k, lo, hi, raw) for k, lo, hi, raw in found if declared(k)]
    return sorted(set(bad)) + L.check_cites(good, docs(), min_count=80)


def g_quote(t: L.Tree) -> list[str]:
    body = t.text("ticket")
    bad: list[str] = []
    for n, line in enumerate(t.text("memo").split("\n"), 1):
        if line.count('"') % 2:
            bad.append(f"line {n}: unpaired quote")
            continue
        keys = {k for k, _, _, _ in cites(line) if declared(k)}
        for q in QUOTE_RE.findall(line):
            if len(q) < QUOTE_MIN or q in body:
                continue
            if not any(q in source_text(k) for k in keys):
                bad.append(f"line {n}: {L.ascii_out(q[:50])!r} not verbatim in {sorted(keys)}")
    return bad


def g_ac(t: L.Tree) -> list[str]:
    table = rows(t.text("memo"), "## Acceptance-criteria trace")
    bad = [f"row {r[0][:30]!r}: status {r[2]!r}" for r in table if len(r) < 4 or r[2] not in STATUS]
    trace = "\n".join(r[0] for r in table)
    for name in SCENARIOS:
        if f'"{name}"' not in trace:
            bad.append(f"scenario {name!r} not in the trace")
        if f"Scenario: {name}" not in t.text("ticket"):
            bad.append(f"scenario {name!r} not in the ticket")
    return bad


def g_bq(t: L.Tree) -> list[str]:
    memo = t.text("memo")
    bad = [] if BQ_HEADING in memo.split("\n") else ["heading"]
    if f"comment {BQ_COMMENT}" not in L.section(memo, "## BQ list"):
        bad.append("the BQ comment id")
    ids = [lead(r) for r in rows(memo, "## BQ list")]
    if ids != [f"BQ-{n}" for n in range(BQ_COUNT)]:
        bad.append(f"ids {ids}")
    return bad


def g_heuristic(t: L.Tree) -> list[str]:
    memo = t.text("memo")
    table = rows(memo, "## 3.")
    bad = [f"{r[0]} not (heuristic)" for r in table if not r[1].startswith("`(heuristic)`")]
    if [lead(r) for r in table] != [f"F-{n}" for n in range(1, len(table) + 1)]:
        bad.append("F ids not F-1..F-n in order")
    bad += [f"participant claim: {m.group(0)!r}" for m in PARTICIPANT_RE.finditer(memo)]
    if "No session was run" not in memo.split("\n## ")[0]:
        bad.append("the header does not say no session was run")
    return bad


def g_defaults(t: L.Tree) -> list[str]:
    table = rows(t.text("memo"), "## 6.")
    by = {lead(r): r for r in table}
    bad: list[str] = []
    for name, pin in DEFAULT_PINS:
        r = by.get(name)
        if r is None or len(r) < 6:
            bad.append(f"{name}: row missing")
            continue
        if not r[1].startswith(pin):
            bad.append(f"{name}: default is not {pin!r}")
        if not cites(r[2]):
            bad.append(f"{name}: evidence cites nothing")
    for r in table:
        if len(r) < 6 or not any(w in r[3] for w in DISSENT_WORDS):
            bad.append(f"{lead(r)}: no dissent with its override reason")
        elif not re.search(r"\bQ\d+\b", r[4]):
            bad.append(f"{lead(r)}: no deciding probe")
    return bad


def g_testable(t: L.Tree) -> list[str]:
    table = rows(t.text("memo"), "## 7.")
    bad: list[str] = []
    if [lead(r) for r in table] != [f"AD-{n}" for n in range(1, AD_COUNT + 1)]:
        bad.append("AD ids not AD-1..AD-12 in order")
    for r in table:
        if len(r) < 6:
            bad.append(f"{lead(r)}: short row")
            continue
        if not r[2].strip() or not r[3].startswith(VIOLATES):
            bad.append(f"{lead(r)}: no satisfies / violates clause")
        if not re.search(r"\bF-\d+\b", r[4]) or not PAIR_RE.search(r[5]):
            bad.append(f"{lead(r)}: no feeding finding or owner ticket")
    return bad


def _words(text: str, words: tuple[str, ...]) -> list[str]:
    return [w for w in words if re.search(rf"\b{w}\b", text, re.IGNORECASE)]


def g_r9(t: L.Tree) -> list[str]:
    memo = t.text("memo")
    sec = L.section(memo, "## 8.")
    bad: list[str] = []
    deck = rows(memo, "### 8.2")
    if len(deck) != 2:
        bad.append(f"{len(deck)} copy rows, not 2")
    for r in deck:
        if len(r) < 6:
            bad.append("short copy row")
            continue
        for i in (1, 2, 5):
            bad += [f"{lead(r)} col {i}: {w!r}" for w in _words(r[i], R9_WORDS)]
        for i in (3, 4):
            bad += [f"{lead(r)} col {i}: {w!r}" for w in _words(r[i], R9_TOOLTIP)]
    listed = L.section(memo, "### 8.3").strip().split("\n")[0].rstrip(".").split(" · ")
    if tuple(w.strip() for w in listed) != R9_WORDS:
        bad.append("the section 8.3 word list differs from R9_WORDS")
    for need in (EPIC_ROW, TOOLTIP_LINE2):
        if need not in sec:
            bad.append(f"section 8 lacks {need!r}")
    return bad


def g_states(t: L.Tree) -> list[str]:
    sec = L.section(t.text("memo"), "## 9.")
    got = [r[1] for r in L.table_rows(sec) if len(r) > 1]
    bad = [] if len(got) == len(STATES) else [f"{len(got)} states, not {len(STATES)}"]
    for i, (cell, want) in enumerate(zip(got, STATES, strict=False), 1):
        if not cell.startswith(want):
            bad.append(f"state {i} is {cell[:30]!r}, not {want!r}")
    return bad + [f"T2: {m}" for m in L.t2_markers(sec)]


def defined_ids(memo: str) -> tuple[set[str], list[str]]:
    seen: list[str] = []
    for line in memo.split("\n"):
        if line.startswith("|"):
            m = ID_RE.fullmatch(lead(L.cells(line)))
            if m:
                seen.append(m.group(0))
        seen += [f"H{n}" for n in HDEF_RE.findall(line)]
    return set(seen), [x for x in set(seen) if seen.count(x) > 1]


def g_ids(t: L.Tree) -> list[str]:
    memo = t.text("memo")
    have, dup = defined_ids(memo)
    used = {m.group(0) for m in ID_RE.finditer(memo)}
    return [f"{x} defined twice" for x in sorted(dup)] + [
        f"{x} referenced, never defined" for x in sorted(used - have)
    ]


def g_owner(t: L.Tree) -> list[str]:
    memo = t.text("memo")
    pub = json.loads(t.text("published"))
    bad = [
        f"{k} #{n} (published #{pub.get(k, {}).get('number')})"
        for k, n in PAIR_RE.findall(memo)
        if pub.get(k, {}).get("number") != int(n)
    ]
    owner_cells = [
        r[-1]
        for h in ("## 7.", "### 13.1", "### 13.2", "### 13.3", "### 13.4")
        for r in rows(memo, h)
    ]
    owner_cells += [r[0] for r in rows(memo, "## 10.")]
    for cell in owner_cells:
        if AGENT_RE.search(cell) or not (PAIR_RE.search(cell) or "owner" in cell):
            bad.append(f"owner cell {cell[-40:]!r}")
    return sorted(set(bad))


def g_boards(t: L.Tree) -> list[str]:
    memo = t.text("memo")
    return L.board_cap(rows(memo, "## 0."), TICKET_KEY, memo)


def g_walk(t: L.Tree) -> list[str]:
    items = re.findall(r"^(\d+)\. (.*)$", L.section(t.text("memo"), "## 12."), re.MULTILINE)
    bad = [] if 1 <= len(items) <= 10 else [f"{len(items)} items"]
    if [int(n) for n, _ in items] != list(range(1, len(items) + 1)):
        bad.append("items not numbered 1..n")
    if not items or f"`approved` on #{ISSUE}" not in items[-1][1]:
        bad.append(f"the last item is not `approved` on #{ISSUE}")
    return bad


def g_hygiene(t: L.Tree) -> list[str]:
    named = t.named("memo")
    memo = t.text("memo")
    bad = (
        L.closing_keywords(named)
        + L.whitespace_hygiene(named)
        + L.scan_public(named)
        + L.comment_findings(named)
        + L.r7_findings(named)
    )
    bad += ["image embed"] if "![" in memo else []
    return bad + [f"colour-vision 'CVD': {m.group(0)!r}" for m in COLOUR_CVD_RE.finditer(memo)]


def g_untouched(t: L.Tree) -> list[str]:
    bad = L.untouched(t.changed, OWN, budgets={CAT_REL: (1, 0)}, numstat=t.numstat)
    base = t.text("base_cat").split("\n")
    idx = [i for i, ln in enumerate(base) if ln.startswith(PRE_POINTER)]
    if len(idx) != 1:
        return bad + ["SCR-052's checklist line not found once at BASE"]
    want = base[: idx[0] + 1] + [POINTER_LINE] + base[idx[0] + 1 :]
    if t.text("cat").split("\n") != want:
        bad.append("`14` differs from BASE plus the one pointer line")
    return bad


GATES: tuple[L.Gate, ...] = (
    L.Gate("G-SECTIONS", g_sections),
    L.Gate("G-CITE", g_cite),
    L.Gate("G-QUOTE", g_quote),
    L.Gate("G-AC", g_ac),
    L.Gate("G-BQ", g_bq),
    L.Gate("G-HEURISTIC", g_heuristic),
    L.Gate("G-DEFAULTS", g_defaults),
    L.Gate("G-TESTABLE", g_testable),
    L.Gate("G-R9", g_r9),
    L.Gate("G-STATES", g_states),
    L.Gate("G-IDS", g_ids),
    L.Gate("G-OWNER", g_owner),
    L.Gate("G-BOARDS", g_boards),
    L.Gate("G-WALK", g_walk),
    L.Gate("G-HYGIENE", g_hygiene),
    L.Gate("G-UNTOUCHED", g_untouched),
)

_M = L.Mutation
_KEYWORD = "Clo" + f"ses #{ISSUE}."
# fmt: off
MUTATIONS: tuple[L.Mutation, ...] = (
    _M("M-1", "G-SECTIONS", "rename section 4", "memo",
       "## 4. Persona walkthrough", "## 4. Persona walk"),
    _M("M-2", "G-CITE", "point a cite past the end of `11`", "memo", "(`11`:2314)", "(`11`:99999)"),
    _M("M-3", "G-QUOTE", "paraphrase a quote of `11`", "memo",
       '"the raw series remains visible"', '"the raw series stays visible"'),
    _M("M-4", "G-AC", "a trace status outside the key", "memo",
       r"(\| heuristic-only )", r"| done (text)    ", regex=True),
    _M("M-5", "G-BQ", "drop BQ-7", "memo", r"\n\| BQ-7 [^\n]*", "", regex=True),
    _M("M-6", "G-HEURISTIC", "claim an observation", "memo",
       "So no number below is market evidence", "Two participants said so; no number"),
    _M("M-7", "G-DEFAULTS", "smoothing on by default", "memo",
       r"(\| Smoothing +\| )off;", r"\1on; ", regex=True),
    _M("M-8", "G-TESTABLE", "AD-2 loses its violates clause", "memo",
       "a wireframe violates it if a Rolling option", "violates if a Rolling option"),
    _M("M-9", "G-R9", "a verdict word in a display name", "memo",
       "| Delta disagreement ", "| Bearish delta "),
    _M("M-10", "G-STATES", "drop the recorder-empty state", "memo",
       r"\n\| 3 +\| recorder-empty[^\n]*", "", regex=True),
    _M("M-11", "G-STATES", "drop a T2 marker", "memo",
       "never `opacity.disabled`", "never faded"),
    _M("M-12", "G-IDS", "reference an undefined finding", "memo",
       "smoothing off), or override", "smoothing off, F-99), or override"),
    _M("M-13", "G-OWNER", "a wrong issue number", "memo", "E23-D03 #612", "E23-D03 #611"),
    _M("M-14", "G-BOARDS", "a board drawn before its slice", "memo",
       r"(\| 08 [^\n]*)PENDING", r"\1DRAWN  ", regex=True),
    _M("M-15", "G-WALK", "an eleventh walkthrough item", "memo",
       "rework notes citing F, AD, C, G or OQ ids.",
       "rework notes citing F, AD, C, G or OQ ids.\n11. Sign off."),
    _M("M-16", "G-HYGIENE", "a closing keyword before the issue", "memo",
       "## 14. References\n", "## 14. References\n\n" + _KEYWORD + "\n"),
    _M("M-17", "G-HYGIENE", "CVD for colour vision", "memo",
       "never uses it so;", "never writes CVD-safe;"),
    _M("M-18", "G-UNTOUCHED", "an owner document edited", "@changed", "",
       "docs/plan/15-component-catalogue.md"),
    _M("M-19", "G-UNTOUCHED", "the pointer line carries a decision", "cat",
       "(E23-D01; heuristic walkthrough", "(E23-D01; binding decisions"),
)
# fmt: on


# ---------- modes ---------------------------------------------------------------------------------
def read_tree() -> L.Tree:
    base = repo().diff_base(BASE)
    changed = repo().changed_paths(base)
    return L.Tree(
        files={
            "memo": (ROOT / MEMO_REL).read_text(encoding="utf-8"),
            "cat": (ROOT / CAT_REL).read_text(encoding="utf-8"),
            "base_cat": at_base(CAT_REL),
            "ticket": ticket_body(),
            "published": at_base(PUBLISHED_JSON),
        },
        changed=changed,
        numstat={p: repo().numstat(base, p) for p in changed if p == CAT_REL},
    )


def check() -> int:
    return L.report(L.run_gates(GATES, read_tree()))


def self_test() -> int:
    disk = [ROOT / rel for rel in (*OWN, CAT_REL)]
    return L.self_test(read_tree(), GATES, MUTATIONS, disk, namespace=globals())


def main(argv: list[str]) -> int:
    return L.cli(argv, {"check": check, "self-test": self_test}, __doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
