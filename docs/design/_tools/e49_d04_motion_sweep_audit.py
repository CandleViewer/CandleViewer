#!/usr/bin/env python3
"""E49-D04 (#1333) audit: the motion and reduced-motion sweep across every animated surface.

Offline and default-deny. The shared gates (git, cites, G-T2 markers, closing keywords, hygiene,
public text, R7, G-UNTOUCHED, the runner and the mutation harness) live in `spec_audit_lib.py`
beside this file; this file keeps only E49-D04's rows. It reads, AS TEXT at the pinned base, the
plan, design, register, lint and theme texts the pack cites and the token JSON, and, from the
working tree, the pack and itself. It runs no repo code.

Gates: GATES below, listed in section 19.1; G-MUTLIST keeps section 19.2 equal to MUTATIONS. The BQ
list 6642014735 is ruled by comment 6643526580: G-BQ checks the RULED form (AMEND on BQ-2, 5, 6).
G-DSET finds the motion specs at the base (a motion tool, or a motion heading over a same-form
table) and reads the delta set's motion tables there.

Usage (from the repo root):
  python3 -I docs/design/_tools/e49_d04_motion_sweep_audit.py --check | --self-test
Exit 0 = no FAIL; 1 = at least one FAIL.
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
BASE = "fe6b7fa8c"  # main at the design-read fold; every cite is read here
BQ_LIST = "6642014735"  # the BQ list on #1333
RULING = "6643526580"  # the ruling of record; BQ-2, BQ-5 and BQ-6 are AMEND
AMEND = (2, 5, 6)
HEAD = "## The questions BQ-0 … BQ-9 — RULED"

SPEC_REL = "docs/design/E49/E49-D04.md"
TOOL_REL = "docs/design/_tools/e49_d04_motion_sweep_audit.py"
OWN = (SPEC_REL, TOOL_REL)
BACKLOG_REL = "docs/plan/backlog/E49.json"

PLAN = {
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
}
_DS = "docs/design/"
KEYED = {
    "D08": L.DocRef(_DS + "E47/E47-D08.md", BASE),
    "E05D03": L.DocRef(_DS + "E05/E05-D03.md", BASE),
    "E08D10": L.DocRef(_DS + "E08/E08-D10.md", BASE),
    "E09D08": L.DocRef(_DS + "E09/E09-D08.md", BASE),
    "E10D04": L.DocRef(_DS + "E10/E10-D04.md", BASE),
    "E16D02": L.DocRef(_DS + "E16/E16-D02.md", BASE),
    "E17D02": L.DocRef(_DS + "E17/E17-D02.md", BASE),
    "E18D02": L.DocRef(_DS + "E18/E18-D02.md", BASE),
    "E18D04": L.DocRef(_DS + "E18/E18-D04.md", BASE),
    "E21D02": L.DocRef(_DS + "E21/E21-D02.md", BASE),
    "E21D03": L.DocRef(_DS + "E21/E21-D03.md", BASE),
    "E24D04": L.DocRef(_DS + "E24/E24-D04.md", BASE),
    "E25D03": L.DocRef(_DS + "E25/E25-D03.md", BASE),
    "E25D04": L.DocRef(_DS + "E25/E25-D04.md", BASE),
    "E26D02": L.DocRef(_DS + "E26/E26-D02.md", BASE),
    "E28D04": L.DocRef(_DS + "E28/E28-D04.md", BASE),
    "E29D04": L.DocRef(_DS + "E29/E29-D04.md", BASE),
    "E30D04": L.DocRef(_DS + "E30/E30-D04.md", BASE),
    "E36D03": L.DocRef(_DS + "E36/E36-D03.md", BASE),
    "E37D03": L.DocRef(_DS + "E37/E37-D03.md", BASE),
    "E39D03": L.DocRef(_DS + "E39/E39-D03.md", BASE),
    "REG": L.DocRef("docs/qa/a11y/e47-motion-exception-register.md", BASE),
    "MSCAN": L.DocRef("packages/ui/test/theme/motion-scan.test.ts", BASE),
    "THEME": L.DocRef("packages/ui/src/theme/theme.css", BASE),
    "E2E": L.DocRef("apps/web/e2e/motion-reduce.spec.ts", BASE),
    "R32": L.DocRef(".claude/rules/32-design-specs.md", BASE),
}
CITE_RE = L.cite_regex(KEYED, ranges=True, spaced=True)
MIN_CITES = 200  # a broken grammar parses far fewer

D08_ROWS = 41  # I-1 .. I-41, on D08 lines 141 .. 181
D08_FIRST = 140
DELTA_ROWS = 10  # X-1 .. X-10
CLASSES = 10  # MC-1 .. MC-10
WORDS = ("removed", "instant", "cross-fade")
WORD_RE = re.compile(r"^(removed|instant|cross-fade): \S.{9,}$")
AT_RE = re.compile(r"^(?:unverified|observed|not observable at base)(?: \([^()]+\))?$")
VERDICTS = (
    "conformant",
    "missing reduced-motion variant",
    "uses a hardcoded duration instead of a motion token",
    "animates a property that should never animate",
    "exceeds the vestibular-safety guidance",
)
V_IDS = tuple(f"V-{n}" for n in range(1, len(VERDICTS) + 1))
CLAUSE_RE = re.compile(r"(DQ-[A-Z]{2}-\d) \((P\d)\)")
# E49-D01 §4's floors, #5860 at aed6b1182 (BQ-7; re-pinned when it merges)
FLOORS = {"DQ-AX-4": "P2", "DQ-TV-1": "P3", "DQ-TS-1": "P1", "DQ-BS-3": "P2", "DQ-CO-1": "P3"}
V_MAP = {
    "V-1": ("pass (static: not-applicable)", "DQ-AX-4 (P2)"),
    "V-2": ("finding", "DQ-AX-4 (P2)"),
    "V-3": ("finding", "DQ-TV-1 (P3)"),
    "V-4": ("finding", "DQ-AX-4 (P2)"),
    "V-5": ("finding", "DQ-AX-4 (P2)"),
}
HOLD_NEED = (  # BQ-5 AMEND: reduced, not exempt
    '**No essential-motion exemption is claimed.**|carries the progress" (`15` :521)|elapsed hold'
    "|remaining hold|never shortens|no register row and no `16` §11.4 entry|E29D04 :332|A-3"
).split("|")
# BQ-2 AMEND: the delta set, every other merged motion spec -> its motion table's heading at BASE
DSET = {
    "E09-D08": "## 3. The motion spec table",
    "E10-D04": "## 4. The transition register",
    "E12-D10": "## 2. The moments at a glance",
    "E13-D04": "## 6. The motion spec table",
    "E14-D09": "## 2. The motion table",
    "E16-D02": "## 9. Motion and live updates",
    "E17-D02": "## 12. Motion spec",
    "E18-D04": "## 2. The motion table",
    "E19-D05": "## 3. The suppression matrix",
    "E22-D03": "## 9. Motion pairs",
    "E24-D04": "## 2. The moments at a glance",
    "E25-D03": "## 9. Motion pairs",
    "E25-D04": "## 8. Motion pairs",
    "E27-D04": "## 2. The choreography table",
    "E28-D04": "## 2. The choreography table",
    "E29-D04": "### 3.2 The motion table",
    "E30-D04": "## 19. The motion spec table",
    "E32-D06": "## 8. Motion: four transitions",
    "E33-D04": "### 7.2 The motion table",
    "E35-D02": "## 9. Motion (",
    "E35-D03": "## 12. Motion (",
    "E36-D03": "## 10. Motion spec",
    "E37-D03": "## 7. Motion pairs",
}
# D08 :137's eight owner tables, and D08 itself
D08_SCOPE = (
    "E05-D03",
    "E08-D11",
    "E11-D06",
    "E15-D14",
    "E22-D04",
    "E40-D02",
    "E42-D04",
    "E47-D05",
    "E47-D08",
)
# a found spec whose own motion heading names the table it carries -> that heading's words
CARRIED = {
    "E11-D03": "the motion spec proper is E11-D06",
    "E11-D09": "(E11-D06 §7, verbatim by tool)",
    "E24-D03": "motion is E24-D04's",
    "E32-D07": "(`D06` §8, `D06`:177-188, copied)",
}
TOOL_RE = re.compile(r"^docs/design/_tools/e(\d\d)_d(\d\d)_\w*motion\w*_audit\.py$")
SPEC_RE = re.compile(r"^docs/design/E\d\d/(E\d\d-D\d\d)\.md$")  # a spec, never a hand-off
MOTION_HEAD_RE = re.compile(r"^(#{2,3}) .*motion", re.IGNORECASE)
ROW_ID_CELL_RE = re.compile(r"^(?:[A-Za-z]{1,2}\d?-?)?\d+$")  # 7, M-1, T-01, Mo-3, D9-01, M1
ROSTER_RE = re.compile(r"\*\*Roster\.\*\* The (\d+) specs found at the base: ([^.]+)\.")
DSET_TOTAL = 309
T2_MORE = ("rendering 2a", "`color.border.default` hairline", "(G-T2.6)")
NUM_RULE = "any animated transition on the numeric value itself is a finding (V-4)"
FLASHING = ("I-5", "I-16", "I-21", "I-22", "I-24", "I-6")  # `05` :252's list plus D08 §4.2
PAUSE_D08 = (264, 265, 266, 267, 268)  # D08 §8's five auto-movers
TS_IDS = tuple(f"TS-{n}" for n in range(1, 6))
CLOCK_NEED = (
    "`14` :756, :761|E08D10 :244|`15` :190, :199, :447|E08-D10's T-1 and T-2|unifies none"
    "|E15-D12's boot and restore clocks|#5877's A-9|no second A-row"
).split("|")
ROW_ID_RE = re.compile(r"\b(?:C|A|G|OQ)-\d+\b")
OWNER_RE = re.compile(r"E\d\d-[A-Z]\d\d #\d+|the owner|catalogue owner|design-system owner")
TOKEN_RE = re.compile(
    r"`((?:color|space|size|type|font|opacity|border|motion|elevation|radius)"
    r"\.[A-Za-z0-9.*\-]+?)(\.\.\d+)?(\[\])?`"
)
FINDING_RE = re.compile(r"\bF-\d+\b")
NAMED_RE = re.compile(r"((?:[IX]-\d+)(?:(?:, | and )[IX]-\d+)*) (?:is|are) F-\d+")
CHECK_MAX = 10


# ---------- sources -------------------------------------------------------------------------------
@functools.cache
def repo() -> L.Repo:
    return L.Repo(ROOT)


@functools.cache
def docs() -> L.Docs:
    return L.Docs(repo(), BASE, KEYED, plan=PLAN)


def line_of(key: str, n: int) -> str:
    got = docs().line(key, n)
    if got is None:
        raise L.AuditError(f"{key}:{n} not readable at {BASE}")
    return got


@functools.cache
def ticket_body() -> str:
    tickets = json.loads(repo().show(BASE, BACKLOG_REL) or "[]")
    return next(str(x.get("body", "")) for x in tickets if x.get("key") == "E49-D04")


# ---------- pack helpers --------------------------------------------------------------------------
def spec(t: L.Tree) -> str:
    return t.text("spec")


def sec(t: L.Tree, heading: str) -> str:
    return L.section(spec(t), heading)


def rows(t: L.Tree, heading: str) -> list[list[str]]:
    return L.table_rows(sec(t, heading))


def prose(block: str) -> list[str]:
    """The block's paragraphs outside tables."""
    paras = re.split(
        r"\n\s*\n", "\n".join(ln for ln in block.split("\n") if not ln.startswith("|"))
    )
    return [p for p in paras if p.strip()]


def classes(t: L.Tree) -> dict[str, tuple[str, list[str]]]:
    """MC id -> (its reduce word, its member ids)."""
    out: dict[str, tuple[str, list[str]]] = {}
    for r in rows(t, "## 3. The reduced-motion mapping"):
        m = WORD_RE.match(r[2]) if len(r) > 3 else None
        members = re.findall(r"\b[IX]-\d+\b", r[3]) if len(r) > 3 else []
        out[r[0]] = (m.group(1) if m else "", members)
    return out


def check_rows(
    t: L.Tree, heading: str, prefix: str, count: int, mc: int, verdict: int, at: int
) -> list[str]:
    """A graded table: ids in order, a defined class that lists the row, a verdict, an At base
    cell, and a non-V-1 row named in the section's prose as "<id> is F-n"."""
    got = rows(t, heading)
    want = [f"{prefix}-{n}" for n in range(1, count + 1)]
    bad = [] if [r[0] for r in got] == want else [f"ids {[r[0] for r in got]}"]
    cls = classes(t)
    named = {
        x
        for m in NAMED_RE.finditer(" ".join(prose(sec(t, heading))))
        for x in re.findall(r"[IX]-\d+", m.group(1))
    }
    for r in got:
        if len(r) <= max(mc, verdict, at):
            bad.append(f"{r[0]}: short row")
            continue
        if r[mc] not in cls or r[0] not in cls[r[mc]][1]:
            bad.append(f"{r[0]}: class {r[mc]}")
        if r[verdict] not in V_IDS:
            bad.append(f"{r[0]}: verdict {r[verdict]!r}")
        if not AT_RE.match(r[at]):
            bad.append(f"{r[0]}: at base {r[at]!r}")
        if r[verdict] != "V-1" and r[0] not in named:
            bad.append(f"{r[0]}: {r[verdict]} names no finding")
    return bad


# ---------- this pack's gates ---------------------------------------------------------------------
def g_cite(t: L.Tree) -> list[str]:
    bad = L.check_cites(L.extract_cites(spec(t), CITE_RE), docs(), min_count=MIN_CITES)
    return [f"unresolved cites: {', '.join(b.split(' (')[0] for b in bad)}"] if bad else []


def g_ac(t: L.Tree) -> list[str]:
    names = [n.strip() for n in re.findall(r"Scenario: (.+)", ticket_body())]
    trace = sec(t, "## Acceptance-criteria and DoD trace")
    miss = [n for n in names if f'AC "{n}"' not in trace]
    return [f"scenario names not verbatim: {miss or names}"] if len(names) != 4 or miss else []


def g_bq(t: L.Tree) -> list[str]:
    return L.check_ruling(
        spec(t),
        heading_line=f"{HEAD} (comment {RULING})",
        list_ref=f"comment {BQ_LIST} on #1333; comment {RULING} is the ruling of record",
        count=10,
        verdict=lambda n: "RULED, AMEND:" if n in AMEND else "RULED, AGREE + rider:",
        forbid=("Default built",),
    )


def g_boards(t: L.Tree) -> list[str]:
    got = rows(t, "## 0. Status")
    bad = L.board_cap(got, "E49-D04", spec(t))
    for r in got:
        if r and r[0].isdigit() and f" MC-{int(r[0])} " not in r[1]:
            bad.append(f"board {r[0]} is not class MC-{int(r[0])}")
    return bad + ([] if len(got) == CLASSES else [f"{len(got)} boards for {CLASSES} classes"])


def g_t2(t: L.Tree) -> list[str]:
    text = spec(t)
    start = text.find("- **R-2 T2")
    block = text[start : text.find("\n- **R-3", start)] if start >= 0 else ""
    bad = [f"R-2 lacks {m!r}" for m in L.t2_markers(block)] + L.no_disabled_tokens(text)
    return bad + [f"R-2 lacks {m!r}" for m in T2_MORE if m not in " ".join(block.split())]


def g_verdict(t: L.Tree) -> list[str]:
    got = rows(t, "## 2. The verdict scale")
    bad = [] if [r[0] for r in got] == list(V_IDS) else [f"ids {[r[0] for r in got]}"]
    body = ticket_body()
    for r, text in zip(got, VERDICTS, strict=False):
        if len(r) < 4 or r[1] != text or text not in body:
            bad.append(f"{r[0]}: not the ticket's verdict")
            continue
        word, clause = V_MAP.get(r[0], ("", ""))
        pairs = CLAUSE_RE.findall(r[3])
        if r[2] != word or r[3] != clause or any(FLOORS.get(c) != p for c, p in pairs):
            bad.append(f"{r[0]}: E49-D01 word, clause or floor")
    return bad


def g_mapping(t: L.Tree) -> list[str]:
    got = rows(t, "## 3. The reduced-motion mapping")
    want = [f"MC-{n}" for n in range(1, CLASSES + 1)]
    bad = [] if [r[0] for r in got] == want else [f"classes {[r[0] for r in got]}"]
    cls = classes(t)
    cells = [(r[0], r[2], r[0]) for r in got if len(r) > 2]
    cells += [(r[0], r[3], r[2]) for r in rows(t, "### 4.1") if len(r) > 3]
    cells += [(r[0], r[4], r[3]) for r in rows(t, "### 4.2") if len(r) > 4]
    for rid, cell, mc in cells:
        m = WORD_RE.match(cell)
        if not m:
            bad.append(f"{rid}: reduce cell {cell[:30]!r} states no word and outcome")
        elif m.group(1) == "cross-fade" and "ruled" not in cell:
            bad.append(f"{rid}: a cross-fade no owner spec rules")
        elif mc in cls and m.group(1) != cls[mc][0]:
            bad.append(f"{rid}: {m.group(1)} in a {cls[mc][0]} class")
    members = sorted(x for _, (_, ms) in cls.items() for x in ms)
    every = sorted([f"I-{n}" for n in range(1, D08_ROWS + 1)])
    every += sorted([f"X-{n}" for n in range(1, DELTA_ROWS + 1)])
    bad += ["E05D03 :427 is A-11's pre-image, never a ruling"] if "E05D03 :427" in spec(t) else []
    return bad + ([] if members == sorted(every) else ["class members are not every row once"])


def g_inventory(t: L.Tree) -> list[str]:
    bad = check_rows(t, "### 4.1", "I", D08_ROWS, 2, 4, 5)
    for n in range(1, D08_ROWS + 1):
        if not line_of("D08", D08_FIRST + n).startswith(f"| I-{n} "):
            bad.append(f"D08 :{D08_FIRST + n} is not I-{n}")
    return bad


def g_delta(t: L.Tree) -> list[str]:
    bad = check_rows(t, "### 4.2", "X", DELTA_ROWS, 3, 5, 6)
    for r in rows(t, "### 4.2"):
        if len(r) > 2 and not L.extract_cites(r[2], CITE_RE):
            bad.append(f"{r[0]}: no owner cite")
    return bad


def g_hold(t: L.Tree) -> list[str]:
    """BQ-5 AMEND: the hold ring is reduced, not exempt; no exemption, no register row, A-3."""
    s5 = " ".join(sec(t, "## 5. The hold ring").split())
    bad = [f"lacks {p!r}" for p in HOLD_NEED if p not in s5]
    bad += ["an exemption is claimed"] if re.search(r"\*\*EX-\d+ |MX-18", spec(t)) else []
    if classes(t).get("MC-9", ("", []))[1] != ["X-1"]:
        bad.append("MC-9 is not X-1 alone")
    a3 = [r for r in rows(t, "### 14.1") if r[0] == "A-3"]
    if not a3 or a3[0][1] != "`16` :119 (§2.6)" or a3[0][-1] != "design-system owner":
        bad.append("A-3, the hold-confirm token to the design-system owner, is missing")
    return bad


def g_numeric(t: L.Tree) -> list[str]:
    s6 = sec(t, "## 6. Numeric readouts never animate")
    bad = [] if NUM_RULE in s6 else ["the rule sentence"]
    got = rows(t, "## 6. Numeric readouts never animate")
    bad += [] if [r[0] for r in got] == [f"N-{n}" for n in range(1, 11)] else ["N ids"]
    for r in got:
        still = len(r) > 4 and r[2].startswith("never animates")
        want = "V-1" if still else "V-4"
        if len(r) < 5 or r[4] != want or not L.extract_cites(r[3], CITE_RE):
            bad.append(f"{r[0]}: graded {r[-1]!r}, its value {r[2][:24]!r}")
    return bad


def g_flash(t: L.Tree) -> list[str]:
    got = rows(t, "## 7. The flash-threshold check")
    seen = {r[0].split()[0] for r in got if r}
    bad = [f"{i} not checked" for i in FLASHING if i not in seen]
    for r in got:
        if len(r) < 4 or not L.extract_cites(r[1], CITE_RE) or r[3] not in V_IDS:
            bad.append(f"{r[0] if r else '?'}: no cited budget")
    tail = sec(t, "## 7. The flash-threshold check")
    return bad + [f"lacks D08 :{n}" for n in (227, 195) if f"D08 :{n}" not in tail]


def g_pause(t: L.Tree) -> list[str]:
    s10 = sec(t, "## 10. Trading-safety motion rules")
    bad = [f"lacks {i}" for i in TS_IDS if f"- **{i}** " not in s10]
    got = rows(t, "## 10. Trading-safety motion rules")
    cited = {c.lo for r in got for c in L.extract_cites(r[1] if len(r) > 1 else "", CITE_RE)}
    bad += [f"D08 :{n} not carried" for n in PAUSE_D08 if n not in cited]
    for r in got:
        f_ref = bool(len(r) > 1 and FINDING_RE.search(r[1]))
        if len(r) < 3 or (r[2] == "V-1") == f_ref or r[2] not in V_IDS:
            bad.append(f"{r[0]}: a pause, or a finding, per verdict")
    return bad


def g_clocks(t: L.Tree) -> list[str]:
    s9 = " ".join(sec(t, "## 9. The clocks of record").split())
    bad = [f"lacks {p!r}" for p in CLOCK_NEED if p not in s9]
    own = [r[0] for r in rows(t, "### 14.1") if len(r) > 1 and "`16` :217" in r[1]]
    return bad + [f"{a} re-files #5877's A-9" for a in own]


def g_walk(t: L.Tree) -> list[str]:
    """BQ-6 AMEND: E49-D02's G-1 answered over L-1 .. L-11, a clock or "none" each, none minted."""
    got = rows(t, "### 9.1")
    bad = [] if [r[0] for r in got] == [f"L-{n}" for n in range(1, 12)] else ["L ids"]
    for r in got:
        clock = len(r) > 3 and bool(L.extract_cites(r[2], CITE_RE))
        delay = len(r) > 3 and (
            bool(L.extract_cites(r[3], CITE_RE)) or "G-3" in r[3] or r[3].startswith("none needed")
        )
        if not (clock and delay):
            bad.append(f"{r[0]}: a clock of record, and a show-delay or its G-row")
    s91 = " ".join(sec(t, "### 9.1").split())
    return bad + ([] if "mints no threshold" in s91 and "A-4" in s91 else ["a threshold minted"])


def owner_ids(key: str) -> list[str]:
    """The motion table's id column, or each row's ordinal where the table has none."""
    text = repo().show(BASE, f"{_DS}{key[:3]}/{key}.md")
    if text is None:
        raise L.AuditError(f"{key} not readable at {BASE}")
    ids = [r[0] for r in L.table_rows(L.section(text, DSET[key]))]
    if all(ROW_ID_CELL_RE.match(i) for i in ids):
        return ids
    return [str(n) for n in range(1, len(ids) + 1)]


def same_form(header: list[str]) -> bool:
    """A motion-safe / motion-reduce pair, or E08-D11 §4's "Reduced-motion variant" column."""
    low = [c.lower() for c in header]
    pair = any("motion-safe" in c for c in low) and any("reduc" in c for c in low)
    return pair or "Reduced-motion variant" in header


@functools.cache
def found() -> dict[str, list[str]]:
    """Every spec at the base with a motion tool, or with a motion heading over a same-form
    table -> its motion headings."""
    listing = repo().git("ls-tree", "--name-only", BASE, _DS + "_tools/").split("\n")
    out: dict[str, list[str]] = {
        f"E{m.group(1)}-D{m.group(2)}": [] for ln in listing if (m := TOOL_RE.match(ln))
    }
    hits = repo().git("grep", "-l", "-i", "-E", r"^#{2,3} .*motion", BASE, "--", _DS)
    for rel in sorted({h.split(":", 1)[1] for h in hits.split("\n") if h}):
        if not (m := SPEC_RE.match(rel)):
            continue
        lines = (repo().show(BASE, rel) or "").split("\n")
        for i, ln in enumerate(lines):
            if not (h := MOTION_HEAD_RE.match(ln)):
                continue
            stop = re.compile(rf"^#{{1,{len(h.group(1))}}} ")
            head = next((x for x in lines[i + 1 :] if x.startswith("|") or stop.match(x)), "")
            if head.startswith("|") and same_form(L.cells(head)):
                out.setdefault(m.group(1), []).append(ln)
    return out


def g_dset(t: L.Tree) -> list[str]:
    """BQ-2 AMEND: the roster is the motion tools at the base; every tool is D08's scope or the
    delta set; each delta spec's rows are its motion table's ids, in order, each with a word, a
    verdict and, off V-1, a defined F-row."""
    s43 = sec(t, "### 4.3")
    specs = found()
    rm = ROSTER_RE.search(" ".join(s43.split()))
    roster = set(re.findall(r"E\d\d-D\d\d", rm.group(2))) if rm else set()
    bad = [] if rm and roster == set(specs) and int(rm.group(1)) == len(specs) else ["the roster"]
    bad += [f"{k}: in no scope" for k in sorted(specs) if k not in (*D08_SCOPE, *CARRIED, *DSET)]
    bad += [f"{k}: not found" for k in (*DSET, *CARRIED) if k not in specs]
    bad += [
        f"{k}: carries no owner" for k, w in CARRIED.items() if not any(w in h for h in specs[k])
    ]
    got = [r for tab in L.all_tables(s43) for r in tab]  # 1a's table, then 1b's
    defined = {r[0] for r in rows(t, "## 12. Findings")}
    for key in DSET:
        mine = [r for r in got if r and r[0].split()[0] == key]
        if [r[1] for r in mine if len(r) > 1] != owner_ids(key):
            bad.append(f"{key}: not its motion table's ids")
        for r in mine:
            ok = len(r) > 4 and r[2] in ("removed", "instant") and r[3] in V_IDS
            if not ok or (r[3] != "V-1" and r[4] not in defined) or r[4] not in defined | {"—"}:
                bad.append(f"{key} {r[1] if len(r) > 1 else '?'}: word, verdict or finding")
    if len(got) != DSET_TOTAL or f"{DSET_TOTAL} rows, by family" not in s43:
        bad.append(f"{len(got)} delta-set rows; want {DSET_TOTAL}")
    return bad


def g_tokens(t: L.Tree) -> list[str]:
    bad = L.check_token_refs(spec(t), L.token_names(repo(), BASE), TOKEN_RE)
    return [f"unknown: {', '.join(bad)}"] if bad else []


def g_rows(t: L.Tree) -> list[str]:
    defined: set[str] = set()
    for h in ("### 14.1", "### 14.2", "### 14.3", "## 16. Open questions"):
        defined |= {r[0] for r in rows(t, h)}
    bad: list[str] = []
    for r in rows(t, "## 12. Findings"):
        refs = ROW_ID_RE.findall(r[-1])
        if not refs and not OWNER_RE.search(r[-1]):
            bad.append(f"{r[0]}: routed nowhere")
        bad += [f"{r[0]} routed to undefined {x}" for x in refs if x not in defined]
        pairs = CLAUSE_RE.findall(r[-2]) if len(r) > 1 else []
        if len(pairs) != 1 or FLOORS.get(pairs[0][0]) != pairs[0][1]:
            bad.append(f"{r[0]}: clause or floor")
    for h in ("## 13. Adopted", "### 14.1", "### 14.3", "## 16. Open"):
        bad += [f"{r[0]}: owner {r[-1]!r}" for r in rows(t, h) if not OWNER_RE.search(r[-1])]
    return bad


def g_checklist(t: L.Tree) -> list[str]:
    block = sec(t, "### 17.3")
    nums = [int(m) for m in re.findall(r"^(\d+)\. ", block, re.MULTILINE)]
    ok = nums == list(range(1, len(nums) + 1)) and 0 < len(nums) <= CHECK_MAX
    return [] if ok else [f"{len(nums)} items; want 1..{CHECK_MAX} in order"]


def g_penpot(t: L.Tree) -> list[str]:
    return L.r7_findings(t.named("spec", "tool"), ("page `E49-D04`",), sec(t, "## 0. Status"))


def g_noclose(t: L.Tree) -> list[str]:
    named = t.named("spec", "tool")
    return L.closing_keywords(named) + L.whitespace_hygiene(named)


def g_public(t: L.Tree) -> list[str]:
    return L.scan_public(t.named("spec", "tool")) + L.comment_findings(t.named("spec"))


def g_untouched(t: L.Tree) -> list[str]:
    return L.untouched(t.changed, OWN)


def g_mutlist(t: L.Tree) -> list[str]:
    return L.check_mutlist(spec(t), "### 19.2", MUTATIONS)


# fmt: off
GATES = tuple(L.Gate("G-" + f.__name__[2:].upper().replace("_", "-"), f) for f in (
    g_cite, g_ac, g_bq, g_boards, g_t2, g_verdict, g_mapping, g_inventory, g_delta, g_hold,
    g_numeric, g_flash, g_pause, g_clocks, g_walk, g_dset, g_tokens, g_rows, g_checklist, g_penpot,
    g_noclose, g_public, g_untouched, g_mutlist,
))
# fmt: on

_M = L.Mutation
# fmt: off
MUTATIONS: tuple[L.Mutation, ...] = (
    _M("M-1", "G-MAPPING", 'a reduce cell says only "disabled"', "spec",
       "| removed: the static two-tone fill; the host's words after 5 s ", "| disabled "),
    _M("M-2", "G-NUMERIC", "a numeric value animates, graded conformant", "spec",
       "never animates: an overlay layer on the cell", "a count-up to the new value"),
    _M("M-3", "G-CITE", "a cite past the end of `14`", "spec", "(`14` :1942)", "(`14` :99999)"),
    _M("M-4", "G-AC", "a scenario name reworded", "spec",
       'AC "Numeric readouts do not animate"', 'AC "Numbers do not animate"'),
    _M("M-5", "G-BQ", "the heading reverts to pending", "spec",
       "BQ-9 — RULED (comment", "BQ-9 — defaults built; ruling pending (comment"),
    _M("M-6", "G-BQ", "an AMEND read as AGREE", "spec",
       "**BQ-5 — the hold ring.** RULED, AMEND:",
       "**BQ-5 — the hold ring.** RULED, AGREE + rider:"),
    _M("M-7", "G-BOARDS", "a board claimed drawn", "spec",
       r"(\| dark\s+\| )PENDING", r"\1drawn  ", regex=True),
    _M("M-8", "G-T2", "the opacity ban dropped", "spec",
       "never `opacity.disabled`", "or `opacity.disabled`"),
    _M("M-9", "G-VERDICT", "a verdict reworded", "spec",
       "| exceeds the vestibular-safety guidance ", "| exceeds the comfort guidance          "),
    _M("M-10", "G-VERDICT", "a floor lowered", "spec",
       r"(\| V-2 [^\n]*\| )DQ-AX-4 \(P2\)", r"\1DQ-AX-4 (P3)", regex=True),
    _M("M-11", "G-MAPPING", "a cross-fade no owner rules", "spec",
       r"(\| I-2 [^\n]*?\| )instant: the scrim and the card at frame 0",
       r"\1cross-fade: the scrim and the card at frame 0", regex=True),
    _M("M-12", "G-INVENTORY", "a D08 row dropped", "spec",
       r"\n\| I-27 [^\n]*", "", regex=True),
    _M("M-13", "G-INVENTORY", "a row's class is not its class", "spec",
       r"(\| I-23 +\|[^|]*\| )MC-8 ", r"\1MC-4 ", regex=True),
    _M("M-14", "G-DELTA", "a delta row with no owner cite", "spec",
       r"(\| X-8 +\|[^|]*\| )E21D02 :50; E21D03 :461", r"\1the ladder spec", regex=True),
    _M("M-15", "G-DELTA", "a delta finding with no F-row", "spec",
       "X-8 is F-11;", "X-8 is open;"),
    _M("M-16", "G-HOLD", "the reduced ring loses the remaining hold", "spec",
       r"(the elapsed hold \(the percentage\) and )the remaining hold", r"\1the hold left",
       regex=True),
    _M("M-17", "G-HOLD", "an exemption claimed", "spec",
       "**No essential-motion exemption is claimed.**", "**EX-1 — the hold ring is exempt.**"),
    _M("M-18", "G-FLASH", "a flashing surface left out", "spec",
       r"\n\| I-24 liquidation flash [^\n]*", "", regex=True),
    _M("M-19", "G-PAUSE", "an auto-mover with no pause and no finding", "spec",
       "| none named (F-10, G-1)", "| none named            "),
    _M("M-20", "G-CLOCKS", "the shimmer's A-row filed twice", "spec",
       "\n\n### 14.2 C-rows",
       "\n| A-7 | `16` :217 (skeleton) | looping | stops by 5 s | catalogue owner |"
       "\n\n### 14.2 C-rows"),
    _M("M-21", "G-CLOCKS", "a clock unified", "spec", "unifies none:", "unifies them:"),
    _M("M-22", "G-TOKENS", "an unshipped motion token", "spec",
       "tokens: `motion.duration.instant`,", "tokens: `motion.duration.instantly`,"),
    _M("M-23", "G-ROWS", "a finding routed to an undefined row", "spec",
       r"(\| F-11 [^\n]*\| )G-2(\s+\|)", r"\1G-9\2", regex=True),
    _M("M-24", "G-ROWS", "a decision owned by no ticket", "spec",
       r"(\| AD-4 [^\n]*\| )E49-S04 #1384", r"\1the QA lane  ", regex=True),
    _M("M-25", "G-ROWS", "a finding's floor lowered", "spec",
       r"(\| F-10 [^\n]*\| )DQ-AX-4 \(P2\)", r"\1DQ-AX-4 (P3)", regex=True),
    _M("M-26", "G-CHECKLIST", "an eleventh walkthrough item", "spec",
       "\n\n## 18. Deviations", "\n11. one more item.\n\n## 18. Deviations"),
    _M("M-27", "G-PENPOT", "a Penpot file id", "spec",
       "Penpot page `E49-D04` (its page id",
       "Penpot page `E49-D04` (" + "file" + "-id=0; its page id"),
    _M("M-28", "G-NOCLOSE", "a closing keyword", "spec",
       "## 18. Deviations", "Clo" + "ses #1333.\n\n## 18. Deviations"),
    _M("M-29", "G-PUBLIC", "a URL", "spec",
       "(Apple's reduce-motion setting,", "(" + "http" + "s://example.org,"),
    _M("M-30", "G-UNTOUCHED", "an owner document edited", "@changed",
       "", "docs/plan/16-design-system-brief.md"),
    _M("M-31", "G-MUTLIST", "the list drifts", "spec",
       "| M-3  | G-CITE      |", "| M-3  | G-AC        |"),
    _M("M-32", "G-WALK", "a show-delay minted for L-6", "spec",
       r"(\| L-6 [^\n]*\| )none outside E08-D10: G-3", r"\1450 ms                   ", regex=True),
    _M("M-33", "G-DSET", "a delta-set row dropped", "spec",
       r"\n\| E33-D04 §7\.2 +\| Mo-4 [^\n]*", "", regex=True),
    _M("M-34", "G-DSET", "a V-3 row with no finding", "spec",
       r"(\| E10-D04 §4 +\| T-28 +\| removed +\| V-3 +\| )F-8", r"\1—  ", regex=True),
    _M("M-35", "G-DSET", "the roster drops a found spec", "spec", "E35-D03, E36-D03,", "E35-D03,"),
    _M("M-36", "G-DSET", "a delta row graded with a cross-fade", "spec",
       r"(\| E12-D10 §2 +\| M-07 +\| )removed ", r"\1cross-fade ", regex=True),
    _M("M-37", "G-DSET", "an ordinal row out of its owner's order", "spec",
       r"(\| E35-D02 §9 +\| )2( +\|)", r"\g<1>9\2", regex=True),
    _M("M-38", "G-DSET", "the newly merged spec's rows dropped", "spec",
       r"\n\| E18-D04 §2 +\| M-16 [^\n]*", "", regex=True),
    _M("M-39", "G-T2", "the T2-in-every-frame clause dropped", "spec", " (G-T2.6)", ""),
    _M("M-40", "G-MAPPING", "the pre-image cited as a ruling", "spec",
       "(E05D03 :433)", "(E05D03 :427)"),
)
# fmt: on


# ---------- modes ---------------------------------------------------------------------------------
def read_tree() -> L.Tree:
    base = repo().diff_base(BASE)
    return L.Tree(
        files={
            "spec": (ROOT / SPEC_REL).read_text(encoding="utf-8"),
            "tool": (ROOT / TOOL_REL).read_text(encoding="utf-8"),
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
