#!/usr/bin/env python3
"""E19-D05 (#500) audit: the profile motion spec (text first; PR 1 of 3).

Offline and default-deny. The shared gates (git, cites, pins, G-T2 vocabulary, closing keywords,
hygiene, public text, R7, G-UNTOUCHED, the runner and the mutation harness) live in
`spec_audit_lib.py`; this file keeps only E19-D05's rows. It reads, AS TEXT at a pinned commit,
the plan and design texts the spec cites at the base, E19-D03's spec and hand-off at PR #5517's
head and E19-D02's spec at PR #5487's head, and, from the working tree, the spec, the pins file
and this file. The only repo code it runs is `relative_luminance()` of
`docs/design/_tools/contrast_check.py`, loaded by path.

Gates: G-CITE, G-KEYCITE, G-QUOTE, G-VERSION, G-AC, G-CASES, G-TOKENS, G-THRESHOLD, G-CADENCE,
G-MATRIX, G-REDUCE, G-FLASH, G-CLIPS, G-BOARDS, G-T2, G-ENV, G-PENPOT, G-RULING, G-RULED,
G-NOCLOSE, G-PUBLIC, G-UNTOUCHED and G-MUTLIST (section 15.2 equals this tool's list).
Pins (G-RULED): each BQ bullet's sha256[:16] in `e19_d05_ruled_pins.txt`; `--repin-ruled` is the
only writer. The BQ list is comment 6583000168 on #500; no ruling yet (G-RULING checks the
"defaults built; ruling pending" form and flips with the ruling).

Usage (from the repo root):
  python3 -I -B docs/design/_tools/e19_d05_audit.py --check | --self-test | --repin-ruled
  python3 -I -B docs/design/_tools/e19_d05_audit.py --fill   (writes sections 8.1 and 15.2)
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import functools
import json
import math
import re
import sys
from pathlib import Path
from types import ModuleType

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_audit_lib as L  # the shared helper sits beside this file

ROOT = Path(__file__).resolve().parents[3]
BASE = "d23ec8bd7"  # origin/main; every plan and merged-spec cite is read here
D03_HEAD = "811292427"  # PR #5517 (E19-D03, #438) head; re-pinned to its merge commit
D03_PR = "#5517"
D02_HEAD = "bed73afaa"  # PR #5487 (E19-D02, #416) head; re-pinned to its merge commit
D02_PR = "#5487"
BQ_LIST = "6583000168"  # the BQ list on #500; no ruling yet

SPEC_REL = "docs/design/E19/E19-D05.md"
TOOL_REL = "docs/design/_tools/e19_d05_audit.py"
PIN_REL = "docs/design/_tools/e19_d05_ruled_pins.txt"
LIB_REL = "docs/design/_tools/spec_audit_lib.py"
OWN = (SPEC_REL, TOOL_REL, PIN_REL, LIB_REL)
BACKLOG_REL = "docs/plan/backlog/E19.json"

PLAN = {
    "05": "docs/plan/05-accessibility-standard.md",
    "06": "docs/plan/06-performance-and-load-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "23": "docs/plan/23-ws-protocol.md",
    "24": "docs/plan/24-internal-schemas.md",
    "26": "docs/plan/26-chart-engine-design.md",
}
_D = "docs/design/"
KEYED = {
    "D03": L.DocRef(_D + "E19/E19-D03.md", D03_HEAD),
    "D03H": L.DocRef(_D + "E19/E19-D03-handoff.md", D03_HEAD),
    "D02": L.DocRef(_D + "E19/E19-D02.md", D02_HEAD),
    "MEMO": L.DocRef(_D + "research/e19-profiles.md", BASE),
    "PRIM": L.DocRef("packages/ui/tokens/primitives.tokens.json", BASE),
    "flags.ts": L.DocRef("packages/chart-engine/src/core/flags.ts", BASE),
    "R32": L.DocRef(".claude/rules/32-design-specs.md", BASE),
    "README": L.DocRef(_D + "README.md", BASE),
    "D09E09": L.DocRef(_D + "E09/E09-D09.md", BASE),
    **{
        k: L.DocRef(f"{_D}{k[:3]}/{k}.md", BASE)
        for k in ("E05-D03", "E08-D11", "E11-D06", "E14-D09", "E15-D14", "E17-D02", "E26-D02")
    },
}
CITE_RE = L.cite_regex(KEYED, ranges=True)

# Load-bearing facts: (doc, line, the words that must stand there); the spec must cite that line.
KEY_PINS: tuple[L.KeyCite, ...] = tuple(
    L.KeyCite(d, n, w)
    for d, n, w in (
        ("23", 753, "1 000 ms"),
        ("23", 404, "`min_throttle_ms`"),
        ("23", 1346, "drop `heatmap` and `profile` to 1 000 ms"),
        ("24", 1004, "complete: bool"),
        ("24", 1019, "(default 60 000)"),
        ("26", 139, "≤ 1 ms"),
        ("26", 238, "< 2 px"),
        ("06", 78, "≤2ms"),
        ("11", 1724, "≥55 fps"),
        ("11", 1730, "≤10 Hz"),
        ("14", 1013, "5 000 rows"),
        ("05", 235, "3 times per second"),
        ("E26-D02", 49, "0.5 · 1 · 2 · 4 · 10 · 25 · 100"),
        ("E17-D02", 221, '"1 s refresh"'),
        ("E11-D06", 96, "no transition, ever"),
        ("E05-D03", 77, "no row puts `motion.duration.slow` on a data row"),
        ("E05-D03", 105, "At least 500 ms between flash starts"),
        ("E05-D03", 110, "21 824 px²"),
        ("D03", 235, "hidden by default"),
        ("D03", 267, "`complete` false"),
        ("D03", 314, "motion E19-D05's"),
        ("D03H", 114, "E19-D05's"),
        ("D02", 100, "≤ 1 Hz"),
        ("D02", 172, "Motion choreography is E19-D05's"),
        ("D09E09", 95, "`rbac.view_as`"),
    )
)

CASES = tuple(f"M-{i}" for i in range(1, 11))
CUT = "`motion.duration.instant` · `—`"
# The BQ defaults' token pair per moving row (BQ-4, -5, -6, -8).
MOVING = {
    "M-1": ("fast", "decelerate"),
    "M-2": ("normal", "accelerate"),
    "M-4": ("normal", "accelerate"),
    "M-8": ("normal", "accelerate"),
    "M-9": ("fast", "decelerate"),
}
BUDGET_US = 1000  # `26`:139, input and animations per frame
T_ROWS_WORST = 5000  # `14`:1013
HS1_GAP_MS = 500  # E05-D03:105
CADENCE = (1000, 250, 50)  # `23`:753 default, a request, `23`:404 floor
WINDOW_MS, REGION_H, REGION_W, AREA_CAP, MR1 = 1000, 256, 341, 21824, 3
# Section 8.1, row by row: (entry, token, peak opacity, starts in the worst 1 s, area per region).
FLASH: tuple[tuple[str, str, float, int, int], ...] = (
    ("M-2 trace", "color.profile.poc", 0.25, math.ceil(WINDOW_MS / HS1_GAP_MS), 4 * REGION_H),
    ("M-4 bracket", "color.profile.valuearea", 0.25, 1, 8 * REGION_H),
    ("M-8 ray fade", "color.profile.poc", 1.0, MR1, MR1 * REGION_W),
)
CLIPS = ("poc-jump", "developing-final")
THEMES, MODES, PHASES = ("dark", "light"), ("normal", "reduce"), ("start", "mid", "end")
TWINS = {"02", "03", "09"}  # BQ-13
AC6 = "**Replay above 1× or a seek: all profile motion is off**"
RULING_HEADING = (
    f"## The questions BQ-0 … BQ-15 — defaults built; ruling pending (comment {BQ_LIST})"
)


# ---------- sources and measurers -----------------------------------------------------------------
@functools.cache
def repo() -> L.Repo:
    return L.Repo(ROOT)


@functools.cache
def docs() -> L.Docs:
    return L.Docs(repo(), BASE, KEYED, plan=PLAN)


def line_of(key: str, n: int) -> str:
    return docs().line(key, n) or ""


@functools.cache
def contrast() -> ModuleType:
    return L.load_module(ROOT, "docs/design/_tools/contrast_check.py", "contrast_check")


@functools.cache
def theme(name: str) -> dict[str, str]:
    return L.resolve_theme(repo(), BASE, name)


@functools.cache
def prim() -> dict[str, dict[str, object]]:
    return L.token_file(repo(), BASE, "primitives")


def rgb(hexv: str) -> tuple[int, int, int]:
    h = hexv.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def step(name: str, token: str, alpha: float) -> float:
    """Relative-luminance step of `token` at `alpha` over the canvas, against the canvas."""
    t = theme(name)
    fg, bg = rgb(t[token]), rgb(t["color.surface.canvas"])
    peak = tuple(round(alpha * f + (1 - alpha) * b) for f, b in zip(fg, bg, strict=True))
    lum = contrast().relative_luminance
    return abs(float(lum(peak)) - float(lum(bg)))


def flash_row(entry: str, token: str, alpha: float, starts: int, area: int) -> list[str]:
    ok = starts <= MR1 and area <= AREA_CAP
    return [
        entry,
        f"`{token}` · {alpha:g}",
        *(f"{step(n, token, alpha):.3f}" for n in L.THEME_PARTS),
        str(starts),
        str(area),
        "pass" if ok else "FAIL",
    ]


def frames(ms: float) -> int:
    return round(ms * 60 / 1000)


def duration_ms(name: str) -> int:
    return int(str(prim()[f"motion.duration.{name}"]["$value"]).removesuffix("ms"))


# ---------- spec helpers --------------------------------------------------------------------------
def rows(block: str) -> list[list[str]]:
    return L.table_rows(block)


def sec(t: L.Tree, heading: str) -> str:
    return L.section(t.text("spec"), heading)


def case_rows(t: L.Tree) -> dict[str, list[str]]:
    return {r[0]: r for r in rows(sec(t, "## 2. The motion table"))}


def matrix_rows(t: L.Tree) -> dict[str, list[str]]:
    return {r[0]: r for r in rows(sec(t, "## 3. The suppression matrix"))}


def kv(t: L.Tree, heading: str) -> dict[str, str]:
    return {r[0]: r[1] for r in rows(sec(t, heading)) if len(r) > 1}


def number(cell: str) -> float:
    m = re.match(r"\s*([\d.]+)", cell.replace(" ", ""))
    if m is None:
        raise ValueError(f"no number in {cell!r}")
    return float(m.group(1))


# ---------- this spec's gates ---------------------------------------------------------------------
def g_cite(t: L.Tree) -> list[str]:
    bad = L.check_cites(L.extract_cites(t.text("spec"), CITE_RE), docs(), min_count=60)
    return [f"unresolved cites: {', '.join(b.split(' (')[0] for b in bad)}"] if bad else []


def g_keycite(t: L.Tree) -> list[str]:
    cites = L.extract_cites(t.text("spec"), CITE_RE)
    bad = L.check_key_cites(KEY_PINS, docs())
    for p in KEY_PINS:
        if not any(c.doc == p.doc and c.lo <= p.line <= c.hi for c in cites):
            bad.append(f"{p.doc}:{p.line} ({p.needle!r}) is not cited")
    return bad


def g_quote(t: L.Tree) -> list[str]:
    bad = []
    for r in rows(sec(t, "### 8.3 Copy deck")):
        if len(r) < 4 or not r[3].startswith("verbatim"):
            continue
        c = L.extract_cites(r[2], CITE_RE)
        if not c or L.unquote(r[1]) not in line_of(c[0].doc, c[0].lo):
            bad.append(r[0])
    return [f"not on the cited line: {', '.join(bad)}"] if bad else []


def g_version(t: L.Tree) -> list[str]:
    v, spec = sec(t, "### 15.3 Version line"), t.text("spec")
    need = (BASE, D03_HEAD, D03_PR, D02_HEAD, D02_PR, "re-pinned to the merge commit", BQ_LIST)
    miss = [n for n in need if n not in v]
    flat = " ".join(spec.split())
    for phrase in (
        f"Base `origin/main` `{BASE}`",
        f"read at the PR head `{D03_HEAD}`",
        f"read at the PR head `{D02_HEAD}`",
        "re-pin to their merge commits when they merge",
    ):
        if phrase not in flat:
            miss.append(phrase)
    return [f"missing: {', '.join(miss)}"] if miss else []


def g_ac(t: L.Tree) -> list[str]:
    tickets = json.loads(repo().show(BASE, BACKLOG_REL) or "[]")
    body = next(str(x.get("body", "")) for x in tickets if x.get("key") == "E19-D05")
    names = re.findall(r"Scenario: (.+)", body)
    trace = sec(t, "## Acceptance-criteria and DoD trace")
    miss = [n for n in names if f'AC "{n.strip()}"' not in trace]
    return [f"scenario names not verbatim: {miss or names}"] if len(names) != 6 or miss else []


def g_cases(t: L.Tree) -> list[str]:
    got = case_rows(t)
    bad = [] if tuple(got) == CASES else [f"rows {list(got)}"]
    for cid, r in got.items():
        if len(r) != 11 or any(not c or c == "—" for c in r):
            bad.append(f"{cid}: {len(r)} cells or an empty one")
            continue
        moving = r[3].startswith("yes")
        if moving != (cid in MOVING):
            bad.append(f"{cid} moves={moving}")
        elif moving and (r[6] == CUT or r[4] == "none" or not r[8].startswith("carries:")):
            bad.append(f"{cid}: a moving row needs a pair, a property and 'carries:'")
        elif not moving and (r[6] != CUT or not r[8].startswith("static is not worse:")):
            bad.append(f"{cid}: a cut reads the instant pair and 'static is not worse:'")
        if r[10] != "§3":
            bad.append(f"{cid} suppression")
    return bad


def g_tokens(t: L.Tree) -> list[str]:
    spec = t.text("spec")
    named = set(re.findall(r"`(motion\.[a-z.]+)`", spec))
    bad = [f"unknown {n}" for n in sorted(named - set(prim()))]
    bad += [f"unknown {n}" for n in L.check_token_refs(spec, L.token_names(repo(), BASE))]
    for heading in ("## 2. The motion table", "## 3. The suppression matrix"):
        if "`motion.duration.slow`" in sec(t, heading):
            bad.append(f"`slow` in {heading[3:]}")
    for cid, (dur, ease) in MOVING.items():
        r = case_rows(t).get(cid, [])
        want = f"`motion.duration.{dur}` · `motion.easing.{ease}`"
        if len(r) < 7 or r[6] != want:
            bad.append(f"{cid} is not {dur} / {ease}")
    return bad


def g_threshold(t: L.Tree) -> list[str]:
    tab = kv(t, "### 4.2 The threshold T_rows")
    share = number(tab.get("Profile motion share of it", "")) * 1000
    cost = number(tab.get("Planning cost per eased row", ""))
    t_rows = math.floor(share / cost)
    bad = []
    if (
        number(tab.get("Input and animations per frame", "")) * 1000 != BUDGET_US
        or share > BUDGET_US
    ):
        bad.append("the share leaves the 1 ms budget")
    if tab.get("T_rows = ⌊share ÷ cost⌋") != str(t_rows):
        bad.append(f"T_rows is {t_rows}")
    if tab.get("Bytes per frame at T_rows (4 B per instance)") != f"{4 * t_rows} B":
        bad.append(f"bytes are {4 * t_rows} B")
    worst = tab.get("Worst case per-row motion", "")
    if T_ROWS_WORST <= t_rows or not worst.startswith("none"):
        bad.append("the worst case still animates per row")
    m1 = case_rows(t).get("M-1", [""] * 8)
    if f"T_rows = {t_rows}" not in m1[7] or f"{4 * t_rows} B" not in sec(t, "## 10. Feasibility"):
        bad.append("M-1 or section 10 carries another T_rows")
    return bad


def g_cadence(t: L.Tree) -> list[str]:
    got = rows(sec(t, "### 4.1 Cadence"))
    bad = [] if len(got) == len(CADENCE) else [f"{len(got)} cadence rows"]
    for ms, r in zip(CADENCE, got, strict=False):
        gap = max(ms, HS1_GAP_MS)
        want = [str(frames(ms)), "runs" if ms >= HS1_GAP_MS else "cut", str(math.ceil(1000 / gap))]
        if len(r) < 4 or number(r[0]) != ms or r[1:4] != want:
            bad.append(f"{ms} ms: want {want}")
    para = sec(t, "### 4.1 Cadence")
    f_fast, f_norm = frames(duration_ms("fast")), frames(duration_ms("normal"))
    if (
        f"`motion.duration.fast` is {f_fast} frames and `motion.duration.normal` {f_norm}"
        not in para
    ):
        bad.append(f"frames {f_fast} / {f_norm}")
    return bad


def g_matrix(t: L.Tree) -> list[str]:
    got = matrix_rows(t)
    bad = [] if tuple(got) == CASES else [f"rows {list(got)}"]
    for cid, r in got.items():
        if len(r) != 7 or any(not c for c in r):
            bad.append(f"{cid}: {len(r)} cells")
        elif not r[4].startswith("off"):
            bad.append(f"{cid} (d) is not off")
    m1 = got.get("M-1", [""] * 7)
    if not (m1[2].startswith("cut") and m1[3].startswith("cut")):
        bad.append("M-1 not cut under (b) and (c)")
    if AC6 not in " ".join(sec(t, "## 3. The suppression matrix").split()):
        bad.append("the AC 6 sentence")
    return bad


def g_reduce(t: L.Tree) -> list[str]:
    got = matrix_rows(t)
    bad = []
    for cid in MOVING:
        a = got.get(cid, ["", ""])[1]
        if not a.startswith("cut ·"):
            bad.append(f"{cid} (a) names no carrier")
    s53 = sec(t, "### 5.3 Reduce forms")
    bad += [w for w in ("W-1", "D02 W-33", "D03 W-11", "end caps", "trees") if w not in s53]
    r6 = next((ln for ln in t.text("spec").split("\n") if ln.startswith("- **R-6 ")), "")
    return bad + ([] if "both modes" in r6 else ["R-6 both modes"])


def g_flash(t: L.Tree) -> list[str]:
    got = {r[0]: r for r in rows(sec(t, "### 8.1 Flash audit"))}
    bad = [] if len(got) == len(FLASH) else [f"{len(got)} flash rows"]
    for f in FLASH:
        want = flash_row(*f)
        if got.get(f[0]) != want:
            bad.append(f"{f[0]}: measured {want[1:]}")
        if want[-1] != "pass":
            bad.append(f"{f[0]} fails MR-1 or HS-1b")
    return bad


def g_clips(t: L.Tree) -> list[str]:
    s9 = sec(t, "## 9. Prototype and clips")
    n = len(CLIPS) * len(THEMES) * len(MODES) * len(PHASES)
    need = [f"`{w}`" for w in (*CLIPS, *THEMES, *MODES, *PHASES)] + [
        f"{n} captures",
        "`docs/design/E19/E19-D05-proto/captures/`",
        '"the prototype is not the engine, below class"',
        "5 000-row arm",
    ]
    bad = [w for w in need if w not in s9]
    return bad + ([] if "clip `poc-jump`" in sec(t, "## Acceptance") else ["AC 4 clip"])


def g_boards(t: L.Tree) -> list[str]:
    brows = rows(sec(t, "## 0. Status"))
    bad = L.board_cap(brows, "E19-D05", t.text("spec"))
    twins = {r[0] for r in brows if len(r) > 3 and "light" in r[3]}
    return bad + ([] if twins == TWINS else [f"light twins {sorted(twins)}, not BQ-13's"])


def g_t2(t: L.Tree) -> list[str]:
    spec, s14 = t.text("spec"), sec(t, "### 1.4 T2")
    d09 = repo().show(BASE, KEYED["D09E09"].rel) or ""
    bad = L.t2_markers(s14) + L.no_disabled_tokens(spec) + L.t2_reason_keys(spec, L.d09_keys(d09))
    return bad + [w for w in ("2a inline", "`rbac.view_as`", "No board of §0") if w not in s14]


def g_env(t: L.Tree) -> list[str]:
    s15 = sec(t, "### 1.5 C-2.11")
    need = ("No DEMO / LIVE surface", "never animate", "E11-D06:96", "never differs by environment")
    return [n for n in need if n not in s15]


def g_penpot(t: L.Tree) -> list[str]:
    return L.r7_findings(
        t.named("spec", "pins"), ("page `E19-D05`", "page id"), sec(t, "## 0. Status")
    )


def g_ruling(t: L.Tree) -> list[str]:
    return L.check_ruling(
        t.text("spec"),
        heading_line=RULING_HEADING,
        list_ref=f"comment {BQ_LIST} on #500",
        count=16,
        verdict=lambda _n: "Default built:",
        need=("Built as:",),
        forbid=("RULED:",),
    )


def g_ruled(t: L.Tree) -> list[str]:
    return L.check_hash_pins(t.text("spec"), t.text("pins"))


def g_noclose(t: L.Tree) -> list[str]:
    texts = t.named("spec", "pins", "tool")
    return L.closing_keywords(texts) + L.whitespace_hygiene(texts)


def g_public(t: L.Tree) -> list[str]:
    return L.scan_public(t.named("spec", "pins", "tool")) + L.comment_findings(t.named("spec"))


def g_untouched(t: L.Tree) -> list[str]:
    return L.untouched(t.changed, OWN)


def g_mutlist(t: L.Tree) -> list[str]:
    return L.check_mutlist(t.text("spec"), "### 15.2 Mutations", MUTATIONS)


# fmt: off
GATES = tuple(L.Gate("G-" + f.__name__[2:].upper(), f) for f in (
    g_cite, g_keycite, g_quote, g_version, g_ac, g_cases, g_tokens, g_threshold, g_cadence,
    g_matrix, g_reduce, g_flash, g_clips, g_boards, g_t2, g_env, g_penpot, g_ruling, g_ruled,
    g_noclose, g_public, g_untouched, g_mutlist,
))
# fmt: on

_M = L.Mutation
_V = "### 15.3 Version line\n"
# fmt: off
MUTATIONS: tuple[L.Mutation, ...] = (
    _M("M-1", "G-CITE", "a cite past the end of `26`", "spec", "(`26`:130)", "(`26`:99999)"),
    _M("M-2", "G-KEYCITE", "the replay presets cited off their line", "spec",
       "E26-D02:49's presets", "E26-D02:50's presets"),
    _M("M-3", "G-QUOTE", "D03 W-11 reworded off its line", "spec", '| "Final"', '| "Closed"'),
    _M("M-4", "G-VERSION", "the version line drops the re-pin", "spec",
       "each re-pinned to the merge commit when it merges", "each kept when it merges"),
    _M("M-5", "G-AC", "a scenario name reworded", "spec",
       'AC "A POC jump is not missed"', 'AC "A POC jump is seen"   '),
    _M("M-6", "G-CASES", "a cut claims to carry meaning", "spec",
       "static is not worse: easing would draw", "carries: easing would draw"),
    _M("M-7", "G-TOKENS", "`slow` on histogram ink", "spec",
       r"(\| M-1 [^\n]*?)`motion\.duration\.fast`", r"\1`motion.duration.slow`", regex=True),
    _M("M-8", "G-THRESHOLD", "T_rows drifts from the arithmetic", "spec",
       r"(\| T_rows = ⌊share ÷ cost⌋ +\| )120( +\|)", r"\g<1>150\2", regex=True),
    _M("M-9", "G-CADENCE", "growth runs at a 250 ms request", "spec",
       r"(\| 250 \(a request\) +\| 15 +\| )cut ", r"\1runs", regex=True),
    _M("M-10", "G-MATRIX", "the overlay fades in replay", "spec",
       "off · the overlay itself", "on · the overlay itself "),
    _M("M-11", "G-REDUCE", "the POC jump loses its reduce carrier", "spec",
       "| cut · W-1 and D02 W-33 ", "| cut                    "),
    _M("M-12", "G-FLASH", "a written luminance step drifts", "spec", "| 0.228 ", "| 0.128 "),
    _M("M-13", "G-CLIPS", "half the captures", "spec", "24 captures", "12 captures"),
    _M("M-14", "G-BOARDS", "a fourth light twin", "spec",
       r"(`E19-D05 / 04 live-growth`[^\n]*\| )dark( +\| PENDING)", r"\1light\2", regex=True),
    _M("M-15", "G-T2", "the opacity ban dropped", "spec",
       "never `color.text.disabled`, never `opacity.disabled` (G-T2.2)",
       "never `color.text.disabled` (G-T2.2)"),
    _M("M-16", "G-ENV", "motion differs by environment", "spec",
       "never differs by environment", "may differ by environment"),
    _M("M-17", "G-PENPOT", "a Penpot file id", "spec",
       "page `E19-D05`, cited", "page `E19-D05` (" + "file" + "-id=0), cited"),
    _M("M-18", "G-RULING", "the heading claims a ruling", "spec",
       "BQ-15 — defaults built; ruling pending", "BQ-15 — RULED"),
    _M("M-19", "G-RULED", "a BQ default edited without a re-pin", "spec",
       "a light twin (02, 03, 09)", "a light twin (02, 03, 08)"),
    _M("M-20", "G-NOCLOSE", "a closing keyword", "spec", _V, _V + "\n" + "Clo" + "ses #500.\n"),
    _M("M-21", "G-NOCLOSE", "a forbidden heading", "spec", "## 12. Heuristic evaluation",
       "## " + "What" + " this spec " + "fix" + "es\n\n## 12. Heuristic evaluation"),
    _M("M-22", "G-NOCLOSE", "a trailing blank", "spec", "### 15.3 Version line\n",
       "### 15.3 Version line \n"),
    _M("M-23", "G-PUBLIC", "a URL", "spec", "the Penpot file", "the Penpot (" + "http" + "s://x.org) file"),
    _M("M-24", "G-PUBLIC", "a local path", "spec", "(README:76–82)",
       "(" + "/" + "home/x/README:76–82)"),
    _M("M-25", "G-UNTOUCHED", "an owner document edited", "@changed",
       "", "docs/plan/05-accessibility-standard.md"),
    _M("M-26", "G-MUTLIST", "the list drifts", "spec", "| M-1  | G-CITE ", "| M-1  | G-AC   "),
)
# fmt: on


# ---------- modes ---------------------------------------------------------------------------------
def read_tree() -> L.Tree:
    def read(rel: str) -> str:
        p = ROOT / rel
        return p.read_text(encoding="utf-8") if p.exists() else ""

    return L.Tree(
        files={"spec": read(SPEC_REL), "pins": read(PIN_REL), "tool": read(TOOL_REL)},
        changed=repo().changed_paths(repo().diff_base(BASE)),
    )


def check() -> int:
    return L.report(L.run_gates(GATES, read_tree()))


def self_test() -> int:
    disk = [ROOT / rel for rel in OWN]
    return L.self_test(read_tree(), GATES, MUTATIONS, disk, namespace=globals())


def repin() -> int:
    lines = L.bq_hash_pins((ROOT / SPEC_REL).read_text(encoding="utf-8"))
    head = "# E19-D05 ruled pins: sha256[:16] of each BQ bullet; written by --repin-ruled only"
    L.write_pins(ROOT / PIN_REL, "\n".join([head, *lines]))
    print(f"pinned {len(lines)} BQ lines")
    return 0


def replace_table(spec: str, heading: str, table: str) -> str:
    t0 = spec.index("\n|", spec.index(heading)) + 1
    end = t0
    for line in spec[t0:].split("\n"):
        if not line.startswith("|"):
            break
        end += len(line) + 1
    return spec[:t0] + table + "\n" + spec[end:]


def fill() -> int:
    p = ROOT / SPEC_REL
    spec = p.read_text(encoding="utf-8")
    t81 = (
        "| Entry | Ink · peak | ΔL dark | ΔL light | ΔL high-contrast | Starts in any 1 s "
        "| Area per region (px²) | Verdict |\n| --- | --- | --- | --- | --- | --- | --- | --- |\n"
    ) + "\n".join("| " + " | ".join(flash_row(*f)) + " |" for f in FLASH)
    spec = replace_table(spec, "### 8.1 Flash audit", t81)
    spec = replace_table(spec, "### 15.2 Mutations", L.mutation_table(MUTATIONS))
    p.write_text(spec, encoding="utf-8", newline="\n")
    print("sections 8.1 and 15.2 written; run prettier on the spec")
    return 0


def main(argv: list[str]) -> int:
    modes = {"check": check, "self-test": self_test, "repin-ruled": repin, "fill": fill}
    return L.cli(argv, modes, __doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
