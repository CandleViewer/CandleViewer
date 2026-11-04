#!/usr/bin/env python3
"""E49-D02 (#1331) audit: the unified empty, loading and error state patterns (SCR-150..159).

Offline and default-deny. The shared gates (git, cites, G-T2 markers, closing keywords, hygiene,
public text, R7, G-UNTOUCHED, the runner and the mutation harness) live in `spec_audit_lib.py`
beside this file; this file keeps only E49-D02's rows. It reads, AS TEXT at the pinned base, the
plan and design texts the pack cites, the token JSON, `pairs.mjs` and `contrast_check.py` (the only
repo code it runs, loaded by path), and, from the working tree, the pack and itself.

Gates: GATES below, listed in section 17.1; G-MUTLIST keeps section 17.2 equal to MUTATIONS. The BQ
list 6636147300 is ruled by comment 6640202848: G-BQ checks the RULED form (AMEND on BQ-3 and BQ-6).

Usage (from the repo root):
  python3 -I docs/design/_tools/e49_d02_state_audit.py --check | --self-test
Exit 0 = no FAIL; 1 = at least one FAIL.
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
BASE = "185be5deb"  # main at the ruling fold; every cite is read here
BQ_LIST = "6636147300"  # the BQ list on #1331
RULING = "6640202848"  # the ruling of record; BQ-3 and BQ-6 are AMEND
HEAD = "## The questions BQ-0 … BQ-9 — RULED"

SPEC_REL = "docs/design/E49/E49-D02.md"
TOOL_REL = "docs/design/_tools/e49_d02_state_audit.py"
OWN = (SPEC_REL, TOOL_REL)
BACKLOG_REL = "docs/plan/backlog/E49.json"
CONTRAST_REL = "docs/design/_tools/contrast_check.py"
PAIRS_REL = "tools/contrast/pairs.mjs"
PAIR_RE = re.compile(r'fg: "([^"]+)",\s*bg: "([^"]+)",\s*threshold: THRESHOLD\.(\w+)')

PLAN = {
    "04": "docs/plan/04-security-program.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "22": "docs/plan/22-api-openapi.yaml",
}
KEYED = {
    "D09": L.DocRef("docs/design/E09/E09-D09.md", BASE),
    "D03E42": L.DocRef("docs/design/E42/E42-D03.md", BASE),
    "D05E16": L.DocRef("docs/design/E16/E16-D05.md", BASE),
    "D10E08": L.DocRef("docs/design/E08/E08-D10.md", BASE),
    "D05E08": L.DocRef("docs/design/E08/E08-D05.md", BASE),
    "D03E10": L.DocRef("docs/design/E10/E10-D03.md", BASE),
    "D12E15": L.DocRef("docs/design/E15/E15-D12.md", BASE),
    "D02E17": L.DocRef("docs/design/E17/E17-D02.md", BASE),
    "D03E30": L.DocRef("docs/design/E30/E30-D03.md", BASE),
    "D04E47": L.DocRef("docs/design/E47/E47-D04.md", BASE),
    "D09E47": L.DocRef("docs/design/E47/E47-D09.md", BASE),
    "R32": L.DocRef(".claude/rules/32-design-specs.md", BASE),
    "README": L.DocRef("docs/design/README.md", BASE),
}
CITE_RE = L.cite_regex(KEYED, ranges=True, spaced=True)
MIN_CITES = 150  # a broken grammar parses far fewer

# `14` line numbers per pattern: (Components, Analytics, checklist)
# fmt: off
SCR_LINES = {
    150: (3094, 3097, 3100), 151: (3105, 3109, 3112), 152: (3134, 3137, 3138),
    153: (3149, 3153, 3156), 154: (3162, 3166, 3168), 155: (3173, 3177, 3179),
    156: (3184, 3188, 3190), 157: (3195, 3199, 3201), 158: (3207, 3211, 3212),
    159: (3218, 3222, 3224),
}
# fmt: on
GATED = frozenset({151, 152, 153, 157, 158, 159})  # BQ-0: the recipes that show a T2 control
EMPTY_ENUM_LINES = (333, 336)  # D10E08: the closed `reason` enumeration
TREATMENTS = ("T-1", "T-2", "T-3", "T-4")
NOTHING_YET = ("chart pane", "panel, row, card or table")  # rows with no content shown yet
ANTI = (
    "a bare spinner with no staged description",
    'a bare "No data" string',
    "an icon-only empty state",
    "a disabled control without the disabled-with-reason pattern CMP-079",
)
DISCLOSE = (
    "byte-identical to an unknown route's",
    "with no network call",
    "never a resource name",
    "Ask the owner",
    "only when a 403 body arrived",
    "no account or user id",
    "`security-reviewer`",
    "the pathname only, never the query or the hash",
    "the matched route pattern",
)
REPLAY = ("original intent id / `Idempotency-Key`", "a new id only after Discard")  # R158-5, C-2.10
ACCESS_OK = ("withdrew", "| A-1 ", "no endpoint")  # a line naming "Request access" says why not
CMP_RE = re.compile(r"CMP-\d{3}")
FRAME_RE = re.compile(r"`(SCR-15\d/[a-z0-9-]+)`")
STEP_RE = re.compile(r"R1[5]\d-\d+")
EVENT_RE = re.compile(r"`([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+|empty_state_shown)`")
ROW_ID_RE = re.compile(r"\b(?:C|A|G|OQ)-\d+\b")
OWNER_RE = re.compile(r"E\d\d-[A-Z]\d\d #\d+|the owner|catalogue owner")
TOKEN_RE = re.compile(
    r"`((?:color|space|size|type|font|opacity|border|motion|elevation|radius)"
    r"\.[A-Za-z0-9.*\-]+?)(\.\.\d+)?(\[\])?`"
)
RUBRIC_QS = 13  # Q1..Q13 (the a11y lens added Q11..Q13)
CLAUSE_RE = re.compile(r"(DQ-[A-Z]{2}-\d) \((P\d)\)")
# E49-D01 §4's floors, #5860 at 6138f6f81 (BQ-0 e; re-pinned when it merges)
FLOORS = {"DQ-BS-2": "P2", "DQ-BS-3": "P2", "DQ-CO-1": "P3", "DQ-CO-2": "P3", "DQ-AX-1": "P2"}
FLOORS |= {"DQ-AX-2": "P2", "DQ-AX-4": "P2", "DQ-AX-5": "P2", "DQ-TS-3": "P1"}
ARCH_RE = re.compile(r"D04E47 :(\d+) \((workspace|full-page form|dialog)\)")
ANALYTICS_RULED = {152: ({"ws.banner_suppressed"}, set()), 154: ({"rbac.denied"}, {"authz.denied"})}
MAP_RE = re.compile(r"^(?:frame `SCR-15\d/[a-z0-9-]+`|recipe R1[5]\d-\d|N/A — )")


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
def cmp_ids() -> frozenset[str]:
    lines = docs().lines("15") or ()
    return frozenset(m.group(1) for ln in lines if (m := re.match(r"### (CMP-\d{3})\b", ln)))


def entry_of(n: int) -> str:
    """The CMP id whose `15` entry holds line n."""
    lines = docs().lines("15") or ()
    for ln in reversed(lines[:n]):
        m = re.match(r"### (CMP-\d{3})\b", ln)
        if m:
            return m.group(1)
    return ""


@functools.cache
def contrast() -> ModuleType:
    return L.load_module(ROOT, CONTRAST_REL, "contrast_check")


@functools.cache
def theme(name: str) -> dict[str, str]:
    return L.resolve_theme(repo(), BASE, name)


def rgb(hexv: str) -> tuple[int, int, int]:
    h = hexv.lstrip("#")
    if len(h) < 6:
        raise L.AuditError(f"not a colour: {hexv!r}")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


@functools.cache
def registry() -> dict[tuple[str, str], tuple[int, float]]:
    src = repo().show(BASE, PAIRS_REL) or ""
    th = {"TEXT": 4.5, "NON_TEXT": 3.0, "HIGH_CONTRAST": 7.0}
    found = PAIR_RE.finditer(src)
    return {(m[1], m[2]): (src.count("\n", 0, m.start(1)) + 1, th[m[3]]) for m in found}


def ratio(fg: str, bg: str, name: str) -> float:
    t = theme(name)
    return float(contrast().contrast_ratio(rgb(t.get(fg, "")), rgb(t.get(bg, ""))))


# ---------- pack helpers --------------------------------------------------------------------------
def spec(t: L.Tree) -> str:
    return t.text("spec")


def sec(t: L.Tree, heading: str) -> str:
    return L.section(spec(t), heading)


def rows(t: L.Tree, heading: str) -> list[list[str]]:
    return L.table_rows(sec(t, heading))


def bullet(text: str, prefix: str) -> str:
    """A list item and its continuation lines."""
    out: list[str] = []
    for ln in text.split("\n"):
        if out and (ln.startswith("- ") or not ln.startswith("  ")):
            break
        if out or ln.startswith(prefix):
            out.append(ln)
    return "\n".join(out)


def pattern_sections(t: L.Tree) -> dict[int, str]:
    out: dict[int, str] = {}
    for ln in spec(t).split("\n"):
        m = re.match(r"(### 5\.\d+) SCR-(15\d) ", ln)
        if m:
            out[int(m.group(2))] = L.section(spec(t), m.group(1) + " ")
    return out


def recipe(block: str, k: int = 0) -> list[list[str]]:
    """The block's k-th table: 0 the recipe, 1 the checklist."""
    tables = L.all_tables(block)
    return tables[k] if len(tables) > k else []


def known_frames(t: L.Tree) -> set[str]:
    drawn = {f for r in rows(t, "## 0. Status") if len(r) > 2 for f in FRAME_RE.findall(r[2])}
    text = spec(t)
    start = text.find("**Not drawn")
    para = text[start : text.find("\n\n", start)] if start >= 0 else ""
    return drawn | set(FRAME_RE.findall(para))


# ---------- this pack's gates ---------------------------------------------------------------------
def g_cite(t: L.Tree) -> list[str]:
    bad = L.check_cites(L.extract_cites(spec(t), CITE_RE), docs(), min_count=MIN_CITES)
    return [f"unresolved cites: {', '.join(b.split(' (')[0] for b in bad)}"] if bad else []


def g_ac(t: L.Tree) -> list[str]:
    tickets = json.loads(repo().show(BASE, BACKLOG_REL) or "[]")
    body = next(str(x.get("body", "")) for x in tickets if x.get("key") == "E49-D02")
    names = [n.strip() for n in re.findall(r"Scenario: (.+)", body)]
    trace = sec(t, "## Acceptance-criteria and DoD trace")
    miss = [n for n in names if f'AC "{n}"' not in trace]
    return [f"scenario names not verbatim: {miss or names}"] if len(names) != 5 or miss else []


def g_bq(t: L.Tree) -> list[str]:
    return L.check_ruling(
        spec(t),
        heading_line=f"{HEAD} (comment {RULING})",
        list_ref=f"comment {BQ_LIST} on #1331; comment {RULING} is the ruling of record",
        count=10,
        verdict=lambda n: "RULED, AMEND:" if n in (3, 6) else "RULED, AGREE + rider:",
        forbid=("Built as:", "ruling pending"),
    )


def g_boards(t: L.Tree) -> list[str]:
    return L.board_cap(rows(t, "## 0. Status"), "E49-D02", spec(t))


def g_t2(t: L.Tree) -> list[str]:
    r2 = bullet(sec(t, "### 1.4"), "- **R-2 ")
    bad = L.t2_markers(r2) + L.no_disabled_tokens(spec(t))
    if "G-T2.6" not in r2:
        bad.append("R-2 lacks G-T2.6")
    for scr, block in pattern_sections(t).items():
        steps = recipe(block)
        has_t2 = any("T2" in " ".join(r[2:]) for r in steps)
        gate = any(r[1] == "CMP-079" and "T2" in " ".join(r[2:]) for r in steps)
        lock = any(r[1] == "CMP-019" and "`lock`" in r[2] for r in steps)
        if scr in GATED and not (has_t2 and gate and lock):
            bad.append(f"SCR-{scr}: the T2 rows (CMP-079 and the CMP-019 `lock`)")
    return bad


def g_recipe(t: L.Tree) -> list[str]:
    bad: list[str] = []
    found = pattern_sections(t)
    if sorted(found) != sorted(SCR_LINES):
        bad.append(f"pattern sections {sorted(found)}")
    for scr, (comp, _, _) in SCR_LINES.items():
        steps = recipe(found.get(scr, ""))
        ids = [r[1] for r in steps if len(r) > 2]
        bad += [f"SCR-{scr}: {i} not in `15`" for i in ids if i not in cmp_ids()]
        want = set(CMP_RE.findall(line_of("14", comp)))
        bad += [f"SCR-{scr}: {i} from `14` missing" for i in sorted(want - set(ids))]
        if [r[0] for r in steps] != [f"R{scr}-{k}" for k in range(1, len(steps) + 1)]:
            bad.append(f"SCR-{scr}: step ids")
    return bad


def g_checklist(t: L.Tree) -> list[str]:
    bad: list[str] = []
    frames = known_frames(t)
    for scr, block in pattern_sections(t).items():
        got, steps = recipe(block, 1), {r[0] for r in recipe(block)}
        body = line_of("14", SCR_LINES[scr][2]).split(":** ", 1)[-1]
        want = [x.strip() for x in body.split("[ ]") if x.strip()]
        if [r[1] for r in got if len(r) > 2] != want:
            bad.append(f"SCR-{scr}: checkboxes differ from `14`")
        for r in got:
            cell = r[2] if len(r) > 2 else ""
            if not MAP_RE.match(cell):
                bad.append(f"SCR-{scr} #{r[0]}: unmapped")
            bad += [
                f"SCR-{scr} #{r[0]}: {f} not planned"
                for f in FRAME_RE.findall(cell)
                if f not in frames
            ]
            bad += [
                f"SCR-{scr} #{r[0]}: {s} unknown" for s in STEP_RE.findall(cell) if s not in steps
            ]
    return bad


def g_analytics(t: L.Tree) -> list[str]:
    bad: list[str] = []
    for scr, block in pattern_sections(t).items():
        flat = " ".join(block.split())
        m = re.search(r"\*\*Analytics \(`14` :(\d+)\):\*\* (.*?)\*\*Budget", flat)
        if not m or int(m.group(1)) != SCR_LINES[scr][1]:
            bad.append(f"SCR-{scr}: the analytics line or its cite")
            continue
        add, drop = ANALYTICS_RULED.get(scr, (set(), set()))
        want = sorted(set(EVENT_RE.findall(line_of("14", SCR_LINES[scr][1]))) - drop | add)
        if sorted(set(EVENT_RE.findall(m.group(2)))) != want:
            bad.append(f"SCR-{scr}: events differ from `14` {want}")
    return bad


def g_empty(t: L.Tree) -> list[str]:
    lo, hi = EMPTY_ENUM_LINES
    enum = {L.cells(line_of("D10E08", n))[0].strip("`") for n in range(lo, hi + 1)}
    props = line_of("15", 313)
    got = rows(t, "### 2.1")
    bad = [] if len(got) == 4 else [f"{len(got)} class rows"]
    if [r[0][:3] for r in got[:3]] != ["E-1", "E-2", "E-3"]:
        bad.append("the three classes")
    for r in got:
        reason, variant = r[2].strip("`"), r[1].split(" ")[0]
        if reason not in enum:
            bad.append(f"{r[0]}: reason {reason} outside the merged enum")
        if f'"{variant.strip("`")}"' not in props:
            bad.append(f"{r[0]}: variant {variant} not CMP-026's")
    return bad


def g_loading(t: L.Tree) -> list[str]:
    got = rows(t, "## 4. The loading decision table")
    keys = [tuple(r[1:5]) for r in got if len(r) > 5]
    bad = [] if len(set(keys)) == len(keys) == len(got) else ["a duplicate key or a short row"]
    for r in got:
        if len(r) < 6 or r[5] not in TREATMENTS:
            bad.append(f"{r[0]}: not exactly one treatment")
        elif (r[5] == "T-1") != r[1].startswith("app boot"):
            bad.append(f"{r[0]}: T-1 is SCR-150's only")
        elif r[2] == "yes" and r[5] == "T-2":
            bad.append(f"{r[0]}: a refresh holds its frame; a skeleton is a first load's")
        elif r[1] in NOTHING_YET and r[2:5] == ["no", "no", "yes"] and r[5] != "T-2":
            bad.append(f"{r[0]}: unknown total, known layout is the skeleton")
    for s in NOTHING_YET:
        combos = {tuple(k[2:]) for k in keys if k[:2] == (s, "no")}
        if combos != {(a, b) for a in ("yes", "no") for b in ("yes", "no")}:
            bad.append(f"{s}: not every combination")
    if any("CMP-014" in c for r in got for c in r):
        bad.append("CMP-014 in a cell")
    t2 = bullet(sec(t, "## 4. The loading decision table"), "- **T-2 ")
    if "CMP-038" not in t2 or "never alone" not in t2:
        bad.append("T-2 without the words")
    return bad


def g_anti(t: L.Tree) -> list[str]:
    got = rows(t, "## 6. The forbidden anti-patterns")
    names = tuple(r[1] for r in got)
    bad = [] if names == ANTI else [f"the four anti-patterns differ: {names}"]
    return bad + [f"{r[0]} not forbidden" for r in got if len(r) < 3 or r[2] != "forbidden"]


def g_disclose(t: L.Tree) -> list[str]:
    s7 = sec(t, "## 7. The 403 / 404 disclosure clauses")
    bad = [f"lacks {p!r}" for p in DISCLOSE if p not in s7]
    bad += [f"lacks D-{n}" for n in range(1, 8) if f"- **D-{n} " not in s7]
    for i, ln in enumerate(spec(t).split("\n"), 1):
        if "Request access" in ln and not any(ok in ln for ok in ACCESS_OK):
            bad.append(f"line {i} offers Request access")
    return bad


def g_replay(t: L.Tree) -> list[str]:
    r5 = [r for r in recipe(pattern_sections(t)[158]) if r[0] == "R158-5"]
    ad = [r for r in rows(t, "## 11. Adopted") if "R158-5" in r[1]]
    bad = [] if r5 else ["R158-5 missing"]
    bad += [f"R158-5 lacks {p!r}" for p in REPLAY if r5 and p not in r5[0][2]]
    return bad + ([] if ad else ["no AD row reuses the held intent's id"])


def g_contrast(t: L.Tree) -> list[str]:
    got = rows(t, "## 8. The theme axis")
    bad = [] if len(got) >= 12 else [f"{len(got)} pairs"]
    for r in got:
        m = re.fullmatch(r"`([a-z0-9.\-]+)` on `([a-z0-9.\-]+)`", r[0])
        if not m or len(r) < 4:
            bad.append(f"row {r[0]!r}")
            continue
        fg, bg, floor = m.group(1), m.group(2), float(r[1])
        if min(ratio(fg, bg, n) for n in L.THEME_PARTS) < floor:
            bad.append(f"{fg} on {bg} below {floor:g}")
        reg = registry().get((fg, bg))
        low = f" at {reg[1]:.1f} (A-8)" if reg and reg[1] < floor else ""
        want = f"`pairs.mjs` :{reg[0]}{low}" if reg else "proposed (A-8)"
        if r[2] != want:
            bad.append(f"{fg} on {bg}: registry {want!r}")
    return bad


def g_stories(t: L.Tree) -> list[str]:
    bad: list[str] = []
    for r in rows(t, "## 9. The Storybook matrix"):
        c = L.extract_cites(r[3] if len(r) > 3 else "", CITE_RE)
        if not c or c[0].doc != "15":
            bad.append(f"{r[0]} {r[1]}: no `15` cite")
            continue
        text = line_of("15", c[0].lo)
        if entry_of(c[0].lo) != r[1]:
            bad.append(f"{r[1]}: `15` :{c[0].lo} is not its entry")
        bad += [
            f"{r[1]}: story {s} not on `15` :{c[0].lo}"
            for s in (x.strip() for x in r[2].split(","))
            if not re.search(rf"\b{re.escape(s)}\b", text)
        ]
    return bad


def g_rubric(t: L.Tree) -> list[str]:
    want = [f"Q{n}" for n in range(1, RUBRIC_QS + 1)]
    got = rows(t, "## 2. The conformance rubric")
    bad = [] if [r[0] for r in got] == want else [f"rubric rows {[r[0] for r in got]}"]
    for r in got:
        pairs = CLAUSE_RE.findall(r[-1])
        joined = ", ".join(f"{c} ({p})" for c, p in pairs) or "none in E49-D01"
        if joined != r[-1] or any(FLOORS.get(c) != p for c, p in pairs):
            bad.append(f"{r[0]}: clause or floor")
    proof = [r[0] for r in rows(t, "### 2.2") if len(r) > 1 and r[1]]
    bad += [] if proof == want else [f"evidence rows {proof}"]
    focus = sorted(int(r[0][4:]) for r in rows(t, "### 3.2") if r[0].startswith("SCR-"))
    for r in (x for x in rows(t, "### 3.2") if x[0].startswith("SCR-")):
        m = ARCH_RE.search(r[-1])
        ln = line_of("D04E47", int(m[1])) if m else ""
        if not (m and r[0] in ln and m[2] in ln):
            bad.append(f"{r[0]}: its E47-D04 §5 archetype")
    return bad + ([] if focus == sorted(SCR_LINES) else [f"focus rows {focus}"])


def g_rows(t: L.Tree) -> list[str]:
    defined = set()
    for h in ("### 12.1", "### 12.2", "### 12.3", "## 14. Open questions"):
        defined |= {r[0] for r in rows(t, h)}
    bad: list[str] = []
    for r in rows(t, "## 10. Findings"):
        refs = ROW_ID_RE.findall(r[-1])
        bad += [f"{r[0]} routed to undefined {x}" for x in refs if x not in defined]
    for h, col in (("## 11. Adopted", -1), ("### 12.1", -1), ("### 12.3", -1), ("## 14. Open", -1)):
        bad += [f"{r[0]}: owner {r[col]!r}" for r in rows(t, h) if not OWNER_RE.search(r[col])]
    return bad


def g_tokens(t: L.Tree) -> list[str]:
    bad = L.check_token_refs(spec(t), L.token_names(repo(), BASE), TOKEN_RE)
    return [f"unknown: {', '.join(bad)}"] if bad else []


def g_penpot(t: L.Tree) -> list[str]:
    return L.r7_findings(t.named("spec", "tool"), ("page `E49-D02`",), sec(t, "## 0. Status"))


def g_noclose(t: L.Tree) -> list[str]:
    named = t.named("spec", "tool")
    return L.closing_keywords(named) + L.whitespace_hygiene(named)


def g_public(t: L.Tree) -> list[str]:
    return L.scan_public(t.named("spec", "tool")) + L.comment_findings(t.named("spec"))


def g_untouched(t: L.Tree) -> list[str]:
    return L.untouched(t.changed, OWN)


def g_mutlist(t: L.Tree) -> list[str]:
    return L.check_mutlist(spec(t), "### 17.2", MUTATIONS)


# fmt: off
GATES = tuple(L.Gate("G-" + f.__name__[2:].upper().replace("_", "-"), f) for f in (
    g_cite, g_ac, g_bq, g_boards, g_t2, g_recipe, g_checklist, g_analytics, g_empty, g_loading,
    g_anti, g_disclose, g_replay, g_contrast, g_stories, g_rubric, g_rows, g_tokens, g_penpot,
    g_noclose, g_public, g_untouched, g_mutlist,
))
# fmt: on

_M = L.Mutation
# fmt: off
MUTATIONS: tuple[L.Mutation, ...] = (
    _M("M-1", "G-CITE", "a cite past the end of `14`", "spec", "(`14` :3088);", "(`14` :99999);"),
    _M("M-2", "G-AC", "a scenario name reworded", "spec",
       'AC "Loading choice is deterministic"', 'AC "Loading choice is fixed"'),
    _M("M-3", "G-BQ", "the heading still pending", "spec",
       "BQ-9 — RULED (comment", "BQ-9 — defaults built; ruling pending (comment"),
    _M("M-4", "G-BQ", "an AMEND read as AGREE", "spec",
       "**BQ-6 — one answer per loading cell.** RULED, AMEND:",
       "**BQ-6 — one answer per loading cell.** RULED, AGREE + rider:"),
    _M("M-5", "G-BOARDS", "a board claimed drawn", "spec",
       r"(\| dark\s+\| )PENDING", r"\1drawn  ", regex=True),
    _M("M-6", "G-T2", "the opacity ban dropped", "spec",
       "never `opacity.disabled`", "or `opacity.disabled`"),
    _M("M-7", "G-T2", "a gated recipe loses its lock glyph", "spec",
       r"(\| R152-7 \| CMP-019 \| )`lock`", r"\1`info`", regex=True),
    _M("M-8", "G-RECIPE", "an unknown CMP id replaces a `14` id", "spec",
       "| R155-3 | CMP-001 |", "| R155-3 | CMP-999 |"),
    _M("M-9", "G-CHECKLIST", "a checkbox reworded", "spec",
       "likely destinations offered", "likely routes offered"),
    _M("M-10", "G-CHECKLIST", "a mapped frame not on any board", "spec",
       "frame `SCR-156/repeated`;", "frame `SCR-156/crash-loop`;"),
    _M("M-11", "G-ANALYTICS", "an event dropped", "spec",
       "`degraded.entered`, `degraded.exited`.", "`degraded.entered`."),
    _M("M-12", "G-EMPTY", "a new reason key", "spec",
       r"\| `no_matches`(\s+)\|", r"| `no_filter`\1   |", regex=True),
    _M("M-13", "G-LOADING", "a cell with two answers", "spec",
       r"(\| L-6 [^\n]*\| )T-2(\s+\|)", r"\1T-2 or T-3\2", regex=True),
    _M("M-14", "G-LOADING", "a combination left out", "spec",
       r"(\| L-5 [^\n]*?\| yes\s+\| )no(\s+\|)", r"\1yes\2", regex=True),
    _M("M-15", "G-ANTI", "an anti-pattern reworded", "spec",
       "| an icon-only empty state", "| an icon-led empty state"),
    _M("M-16", "G-DISCLOSE", "the 404 is only similar", "spec",
       "byte-identical to an unknown route's for the same session",
       "similar to an unknown route's for the same session"),
    _M("M-17", "G-DISCLOSE", "a request path offered", "spec",
       "- **D-6 Nothing elsewhere", '- **D-7** Offer "Request access".\n- **D-6 Nothing elsewhere'),
    _M("M-18", "G-CONTRAST", "a registry line retyped", "spec", "s.mjs` :29 ", "s.mjs` :9 "),
    _M("M-19", "G-STORIES", "a story the catalogue lacks", "spec",
       "PanelLevel, RouteLevel, AppLevel", "PanelLevel, RouteCrash, AppLevel"),
    _M("M-20", "G-ROWS", "a decision owned by no ticket", "spec",
       r"(\| AD-3 [^\n]*\| )E49-Q04 #1362", r"\1the QA lane   ", regex=True),
    _M("M-21", "G-ROWS", "a finding routed to an undefined row", "spec",
       r"(\| F-8 [^\n]*\| )C-5(\s+\|)", r"\1C-9\2", regex=True),
    _M("M-22", "G-TOKENS", "an unshipped token", "spec", "`size.row.height`", "`size.row.tall`"),
    _M("M-23", "G-PENPOT", "a Penpot file id", "spec",
       "Penpot page `E49-D02` (its page id",
       "Penpot page `E49-D02` (" + "file" + "-id=0; its page id"),
    _M("M-24", "G-NOCLOSE", "a closing keyword", "spec",
       "## 16. Deviations", "Clo" + "ses #1331.\n\n## 16. Deviations"),
    _M("M-25", "G-PUBLIC", "a URL", "spec",
       "(IBM Carbon, Atlassian)", "(IBM Carbon, " + "http" + "s://example.org)"),
    _M("M-26", "G-UNTOUCHED", "an owner document edited", "@changed",
       "", "docs/plan/15-component-catalogue.md"),
    _M("M-27", "G-MUTLIST", "the list drifts", "spec", "| M-1  | G-CITE ", "| M-1  | G-AC   "),
    _M("M-28", "G-RUBRIC", "a check loses its evidence", "spec",
       r"\n\| Q12 \| a fake-clock[^\n]*", "", regex=True),
    _M("M-29", "G-RUBRIC", "a pattern loses its focus row", "spec",
       r"\n\| SCR-153 \| unchanged [^\n]*", "", regex=True),
    _M("M-30", "G-DISCLOSE", "the echo keeps the query", "spec",
       "the pathname only, never the query or the hash", "the path with its query"),
    _M("M-31", "G-REPLAY", "a replay mints a new id", "spec",
       "Replay carries the original intent id", "Replay mints a new intent id"),
    _M("M-32", "G-REPLAY", "the replay decision unowned", "spec",
       "the held intent's id (R158-5)", "the held intent's id (R158-x)"),
    _M("M-33", "G-ANALYTICS", "SCR-154 keeps the stale audit name", "spec",
       "**Analytics (`14` :3166):** `rbac.denied`", "**Analytics (`14` :3166):** `authz.denied`"),
    _M("M-34", "G-LOADING", "a refresh gets a skeleton", "spec",
       r"(\| L-10 [^\n]*\| )T-3(\s+\|)", r"\1T-2\2", regex=True),
    _M("M-35", "G-RUBRIC", "a focus row names the wrong archetype", "spec",
       "D04E47 :202 (dialog)", "D04E47 :202 (workspace)"),
    _M("M-36", "G-RUBRIC", "a clause floor lowered", "spec", "DQ-TS-3 (P1)", "DQ-TS-3 (P3)"),
    _M("M-37", "G-CONTRAST", "an unregistered pair claimed registered", "spec",
       "| proposed (A-8) ", "| `pairs.mjs` :1 "),
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
