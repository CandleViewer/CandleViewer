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
G-MATRIX, G-REDUCE, G-FLASH, G-REBUCKET, G-FRAME, G-PREFIX, G-CLIPS, G-BOARDS, G-T2, G-ENV,
G-PENPOT, G-RULING, G-RULED, G-NOCLOSE, G-PUBLIC, G-UNTOUCHED and G-MUTLIST (section 15.2 equals
this tool's list). Pins (G-RULED): each BQ bullet's sha256[:16] in `e19_d05_ruled_pins.txt`;
`--repin-ruled` is the only writer. The BQ list is comment 6583000168 on #500 and the ruling of
record comment 6585209632 (G-RULING checks each bullet's verdict and the cross-BQ points).

Usage (from the repo root):
  python3 -I -B docs/design/_tools/e19_d05_motion_audit.py --check | --self-test | --repin-ruled
  python3 -I -B docs/design/_tools/e19_d05_motion_audit.py --fill   (writes sections 8.1, 15.2)
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import functools
import hashlib
import json
import math
import re
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import ModuleType

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_audit_lib as L  # the shared helper sits beside this file

ROOT = Path(__file__).resolve().parents[3]
BASE = "95a625b09"  # origin/main; every plan and merged-spec cite is read here
D03_HEAD = "811292427"  # PR #5517 (E19-D03, #438) head; re-pinned to its merge commit
D03_PR = "#5517"
D02_HEAD = "bed73afaa"  # PR #5487 (E19-D02, #416) head; re-pinned to its merge commit
D02_PR = "#5487"
BQ_LIST = "6583000168"  # the BQ list on #500
RULING = "6585209632"  # the ruling of record on #500
# The verdict per BQ (comment 6585209632).
VERDICTS = (
    "ACCEPT",
    "ACCEPT",
    "ACCEPT",
    "ACCEPT + rider",
    "OVERRIDE",
    "ACCEPT + rider",
    "OVERRIDE",
    "OVERRIDE",
    "ACCEPT + rider",
    "ACCEPT + rider",
    "ACCEPT",
    "ACCEPT + rider",
    "ACCEPT",
    "ACCEPT",
    "ACCEPT + rider",
    "OVERRIDE",
)
CROSS = tuple(f"- **X-{i} " for i in range(1, 7))

SPEC_REL = "docs/design/E19/E19-D05.md"
TOOL_REL = "docs/design/_tools/e19_d05_motion_audit.py"
PIN_REL = "docs/design/_tools/e19_d05_ruled_pins.txt"
LIB_REL = "docs/design/_tools/spec_audit_lib.py"
OWN = (SPEC_REL, TOOL_REL, PIN_REL, LIB_REL)
LIB_SHA16 = "03007e3fc2be98f7"  # the shared helper, byte-identical in #439, #505 and #500's PR 1
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
        ("05", 248, "3 times per second"),
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
        # The ruling's sources (comment 6585209632).
        ("23", 3146, "value_area_high"),
        ("14", 1027, "<=300 ms"),
        ("D02", 310, '"Period: {mode}" once'),
        ("D02", 246, "the end of loading is silent"),
        ("E26-D02", 58, "Seeking is a client condition"),
        ("E15-D14", 80, "panel close"),
        ("E08-D11", 72, "latest-wins"),
        ("E05-D03", 114, "MR-2"),
        ("E11-D06", 99, "Shedding order"),
        ("E11-D06", 83, "41 %"),
        ("06", 25, "≤16.6ms/frame"),
        ("16", 234, "peak 0.25, decaying `fast`"),
        ("15", 2956, '"estimated"'),
        ("MEMO", 250, "No developing VAH / VAL path"),
        ("26", 24, "≤ 8 ms"),
    )
)

CASES = tuple(f"M-{i}" for i in range(1, 11))
CUT = "`motion.duration.instant` · `—`"
# The BQ defaults' token pair per moving row (BQ-4, -5, -6, -8).
MOVING = {
    "M-1": ("fast", "standard"),  # X-3: `decelerate` front-loads a `fast` travel
    "M-2": ("normal", "accelerate"),
    "M-4": ("normal", "accelerate"),
    "M-8": ("normal", "accelerate"),
    "M-9": ("fast", "standard"),
}
BUDGET_US = 1000  # `26`:139, input and animations per frame
T_ROWS_WORST = 5000  # `14`:1013
HS1_GAP_MS = 500  # E05-D03:105
CADENCE = (1000, 250, 50)  # `23`:753 default, a request, `23`:404 floor
WINDOW_MS, REGION_H, REGION_W, AREA_CAP, MR1 = 1000, 256, 341, 21824, 3
PANEL_W = 280  # BQ-11's rider: the panel width a full-width band would span
MERGE_PX = 2  # `26`:238: rows merge under 2 px
# Section 8.1, row by row: (entry, token, peak opacity, starts in the worst 1 s, area per region).
FLASH: tuple[tuple[str, str, float, int, int], ...] = (
    ("M-2 trace", "color.profile.poc", 0.25, math.ceil(WINDOW_MS / HS1_GAP_MS), 4 * REGION_H),
    ("M-4 bracket", "color.profile.valuearea", 0.25, 1, 8 * REGION_H),
    ("M-8 ray fade", "color.profile.poc", 1.0, MR1, MR1 * REGION_W),
    # R-5's combined cap: the largest step (the ray) and the worst area three starts admit
    # (one bracket plus two traces).
    ("Combined M-2 + M-4 + M-8", "color.profile.poc", 1.0, MR1, 8 * REGION_H + 2 * 4 * REGION_H),
)
COMBINED = "together start at most 3 in any half-open 1 000 ms window per pane"
CLIPS = ("poc-jump", "developing-final")
THEMES, MODES, PHASES = ("dark", "light"), ("normal", "reduce"), ("start", "mid", "end")
TWINS = {"02", "03", "09"}  # BQ-13
AC6 = "**Replay above 1× or a seek: all profile motion is off**"
RULING_HEADING = f"## The questions BQ-0 … BQ-15 — RULED (comment {RULING})"
SEC61, SEC10 = "### 6.1 Re-bucket", "## 10. Feasibility"
_BARE_W = re.compile(r"(?<!D0\d )(?<![\w-])W-\d+[a-z]?\b")


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


def ease_share(name: str, dur: str) -> float:
    """Share of the travel a cubic-bezier easing token covers in the first 60 fps frame."""
    vals = prim()[f"motion.easing.{name}"]["$value"]
    if not isinstance(vals, list) or len(vals) != 4:
        raise ValueError(f"motion.easing.{name} is not a cubic bezier")
    x1, y1, x2, y2 = (float(v) for v in vals)
    x = (1000 / 60) / duration_ms(dur)

    def bez(a: float, b: float, s: float) -> float:
        return 3 * (1 - s) ** 2 * s * a + 3 * (1 - s) * s * s * b + s**3

    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if bez(x1, x2, mid) < x else (lo, mid)
    return 100 * bez(y1, y2, (lo + hi) / 2)


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
    need = (
        BASE,
        D03_HEAD,
        D03_PR,
        D02_HEAD,
        D02_PR,
        "re-pinned to the merge commit",
        BQ_LIST,
        RULING,
    )
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
    fast, norm = ease_share("decelerate", "fast"), ease_share("decelerate", "normal")
    r3 = next((p for p in spec.split("\n- ") if p.startswith("**R-3 ")), "")
    phrase = (
        f"`motion.easing.decelerate` puts {fast:.1f} % of a `motion.duration.fast` travel into the "
        f"first 60 fps frame ({norm:.1f} % at `motion.duration.normal`"
    )
    if phrase not in " ".join(r3.split()):
        bad.append(f"R-3 lacks the computed shares {fast:.1f} % / {norm:.1f} %")
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
    if f"rows before the `26`:238 merge ≤ T_rows = {t_rows} and no merge active" not in m1[7]:
        bad.append("M-1 does not gate on the rows before the merge (BQ-4)")
    pane = f"Rows a ≤ {MERGE_PX * t_rows} px pane draws after the merge ({MERGE_PX} px each)"
    if tab.get(pane) != str(t_rows):
        bad.append(f"no '{pane}' row of {t_rows}")
    if "(c) rows before the merge > T_rows or a merge active" not in sec(
        t, "## 3. The suppression"
    ):
        bad.append("column (c) is not on the merge basis")
    return bad


def g_cadence(t: L.Tree) -> list[str]:
    got = rows(sec(t, "### 4.1 Cadence"))
    bad = [] if len(got) == len(CADENCE) else [f"{len(got)} cadence rows"]
    for ms, r in zip(CADENCE, got, strict=False):
        gap = max(ms, HS1_GAP_MS)
        trace = "0 (a cut)" if duration_ms("normal") > ms else str(math.ceil(1000 / gap))
        want = [str(frames(ms)), "runs" if ms >= HS1_GAP_MS else "cut", trace]
        if len(r) < 4 or number(r[0]) != ms or r[1:4] != want:
            bad.append(f"{ms} ms: want {want}")
    para = sec(t, "### 4.1 Cadence")
    f_fast, f_norm = frames(duration_ms("fast")), frames(duration_ms("normal"))
    if (
        f"`motion.duration.fast` is {f_fast} frames and `motion.duration.normal` {f_norm}"
        not in para
    ):
        bad.append(f"frames {f_fast} / {f_norm}")
    r2 = " ".join(
        next((p for p in t.text("spec").split("\n- ") if p.startswith("**R-2 ")), "").split()
    )
    rider = ("longer than the effective throttle", "retargets", "the latest winning", "E08-D11:72")
    return bad + [f"R-2 lacks {w!r}" for w in rider if w not in r2]


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
    s3 = " ".join(sec(t, "## 3. The suppression matrix").split())
    if AC6 not in s3:
        bad.append("the AC 6 sentence")
    return bad + [f"§3 lacks {w}" for w in ("E26-D02:58", "rung 0", "E11-D06:99") if w not in s3]


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
    r5 = next((ln for ln in t.text("spec").split("\n\n") if "- **R-5 " in ln), "")
    if COMBINED not in " ".join(r5.split()):
        bad.append("R-5 lacks the combined cap")
    m = re.search(r"\((\d+) px wide, PROPOSED\)", sec(t, "### 5.1 The POC jump"))
    lane = int(m.group(1)) if m else 0
    if not lane or lane * REGION_H > AREA_CAP or lane * REGION_H != FLASH[0][4]:
        bad.append(f"the M-2 band lane ({lane} px) leaves HS-1b's {AREA_CAP} px² or §8.1's area")
    span = AREA_CAP // PANEL_W + 1
    area = span * PANEL_W
    sentence = f"from a {span} px span ({span} × {PANEL_W} = {area:,} px²)".replace(",", " ")
    if sentence not in " ".join(sec(t, "### 8.1 Flash audit").split()):
        bad.append(f"§8.1 lacks the full-width band bound: {sentence}")
    return bad


def g_rebucket(t: L.Tree) -> list[str]:
    """BQ-7: D02's once-announcements, a silent end, the busy bar after `14`:1027's budget."""
    m = re.search(r"<=(\d+) ms", line_of("14", 1027))
    budget = m.group(1) if m else "?"
    s61 = " ".join(sec(t, SEC61).split())
    need = (f"pending after {budget} ms, `14`:1027", "D02:246", "D02:310", "never sweeps", "MR-2")
    bad = [f"§6.1 lacks {w!r}" for w in need if w not in s61]
    spec = t.text("spec")
    rest = spec.replace(L.section(spec, L.BQ_HEADING), "")
    if "Recalculated" in rest:
        bad.append('a "Recalculated" outside the BQ section')
    c9 = rows(sec(t, "### 11.1 Contradictions"))
    if not any(r[0] == "C-9" and "D02:310" in r[1] and f"{budget} ms" in r[1] for r in c9):
        bad.append("no C-9 row on D02:310")
    return bad


def g_frame(t: L.Tree) -> list[str]:
    """BQ-15: the pass line is the measured per-frame cost; ≥ 55 fps is never one."""
    flat = " ".join(t.text("spec").split())
    bad = [
        s[:60]
        for s in re.split(r"(?<=[.;])\s", flat)
        if "55 fps" in s and "pass line" in s and "not a pass line" not in s
    ]
    s10 = " ".join(sec(t, SEC10).split())
    if "The pass line is each motion's measured per-frame cost" not in s10:
        bad.append("§10 names another pass line")
    return bad


def g_prefix(t: L.Tree) -> list[str]:
    """X-2: every W-n carries its file (D05, D03 or D02)."""
    bare = sorted({m.group(0) for m in _BARE_W.finditer(" ".join(t.text("spec").split()))})
    return [f"bare {', '.join(bare)}"] if bare else []


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
    spec = t.text("spec")
    bad = L.check_ruling(
        spec,
        heading_line=RULING_HEADING,
        list_ref=f"comment {RULING} on #500",
        count=16,
        verdict=lambda n: f"RULED: {VERDICTS[n]}.",
        need=("Built as:",),
        forbid=("Default built:", "ruling pending"),
    )
    for b in L.bq_bullets(spec):
        n = int(b[7:].split(" ", 1)[0])
        if ("rider" in VERDICTS[n]) != ("Rider:" in b):
            bad.append(f"BQ-{n} rider")
    sect = L.section(spec, L.BQ_HEADING)
    return bad + [f"no {x.strip()}" for x in CROSS if x not in sect]


def g_ruled(t: L.Tree) -> list[str]:
    return L.check_hash_pins(t.text("spec"), t.text("pins"))


def g_noclose(t: L.Tree) -> list[str]:
    texts = t.named("spec", "pins", "tool")
    return L.closing_keywords(texts) + L.whitespace_hygiene(texts)


def g_public(t: L.Tree) -> list[str]:
    return L.scan_public(t.named("spec", "pins", "tool")) + L.comment_findings(t.named("spec"))


def g_untouched(t: L.Tree) -> list[str]:
    sha = hashlib.sha256(t.text("lib").encode("utf-8")).hexdigest()[:16]
    return L.untouched(t.changed, OWN) + ([] if sha == LIB_SHA16 else [f"helper is {sha}"])


def g_mutlist(t: L.Tree) -> list[str]:
    return L.check_mutlist(t.text("spec"), "### 15.2 Mutations", MUTATIONS)


# fmt: off
GATES = tuple(L.Gate("G-" + f.__name__[2:].upper(), f) for f in (
    g_cite, g_keycite, g_quote, g_version, g_ac, g_cases, g_tokens, g_threshold, g_cadence,
    g_matrix, g_reduce, g_flash, g_rebucket, g_frame, g_prefix, g_clips, g_boards, g_t2, g_env,
    g_penpot, g_ruling, g_ruled, g_noclose, g_public, g_untouched, g_mutlist,
))
# fmt: on

_M = L.Mutation


def _repinned(find: str, repl: str, count: int = 1) -> Callable[[L.Tree], L.Tree]:
    """Edit a BQ bullet and re-pin it, so only the gate that reads the verdict can fail."""

    def fn(t: L.Tree) -> L.Tree:
        spec = t.text("spec")
        if find not in spec:
            raise L.AuditError(f"anchor not found: {find!r}")
        spec = spec.replace(find, repl, count)
        pins = "\n".join([t.text("pins").split("\n", 1)[0], *L.bq_hash_pins(spec)]) + "\n"
        return replace(t, files={**t.files, "spec": spec, "pins": pins})

    return fn


_V = "### 15.3 Version line\n"
# fmt: off
MUTATIONS: tuple[L.Mutation, ...] = (
    _M("M-1", "G-CITE", "a cite past the end of `26`", "spec", "(`26`:130)", "(`26`:99999)"),
    _M("M-2", "G-KEYCITE", "the replay presets cited off their line (re-pinned)",
       fn=_repinned("E26-D02:49", "E26-D02:50", count=-1)),
    _M("M-3", "G-QUOTE", "D03 W-11 reworded off its line", "spec", '| "Final"', '| "Closed"'),
    _M("M-4", "G-VERSION", "the version line drops the re-pin", "spec",
       "re-pinned to the merge commit when it merges", "kept when it merges"),
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
       "| cut · D05 W-1 and D02 W-33 ", "| cut                        "),
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
    _M("M-18", "G-RULING", "the heading cites the BQ list, not the ruling", "spec",
       f"BQ-15 — RULED (comment {RULING})", f"BQ-15 — RULED (comment {BQ_LIST})"),
    _M("M-19", "G-RULED", "a BQ default edited without a re-pin", "spec",
       "a light twin (02, 03, 09)", "a light twin (02, 03, 08)"),
    _M("M-20", "G-NOCLOSE", "a closing keyword", "spec", _V, _V + "\n" + "Clo" + "ses #500.\n"),
    _M("M-21", "G-NOCLOSE", "a forbidden heading", "spec", "## 12. Heuristic evaluation",
       "## " + "What" + " this spec " + "fix" + "es\n\n## 12. Heuristic evaluation"),
    _M("M-22", "G-NOCLOSE", "a trailing blank", "spec", "### 15.3 Version line\n",
       "### 15.3 Version line \n"),
    _M("M-23", "G-PUBLIC", "a URL", "spec", "the Penpot file",
       "the Penpot (" + "http" + "s://x.org) file"),
    _M("M-24", "G-PUBLIC", "a local path", "spec", "(README:76–82)",
       "(" + "/" + "home/x/README:76–82)"),
    _M("M-25", "G-UNTOUCHED", "an owner document edited", "@changed",
       "", "docs/plan/05-accessibility-standard.md"),
    _M("M-26", "G-MUTLIST", "the list drifts", "spec", "| M-1  | G-CITE ", "| M-1  | G-AC   "),
    _M("M-27", "G-FLASH", "the combined start cap dropped", "spec",
       "together start at most 3", "together start at most 6"),
    _M("M-28", "G-RULING", "a rider dropped (re-pinned)", fn=_repinned(
        "Rider: E15-D14 I-13", "Also: E15-D14 I-13")),
    _M("M-29", "G-TOKENS", "the easing share misstated", "spec",
       "puts 57.5 % of a", "puts 41.0 % of a"),
    _M("M-30", "G-THRESHOLD", "growth gated on drawn rows", "spec",
       "| changed rows only; rows before the `26`:238 merge",
       "| changed rows only; drawn rows before the merge"),
    _M("M-31", "G-THRESHOLD", "the merged-pane arithmetic drifts", "spec",
       "| Rows a ≤ 240 px pane draws", "| Rows a ≤ 200 px pane draws"),
    _M("M-32", "G-CADENCE", "the trace runs at the 50 ms floor", "spec",
       r"(\| 50 \(the floor\) +\| 3 +\| cut +\| )0 \(a cut\)", r"\g<1>2        ", regex=True),
    _M("M-33", "G-CADENCE", "R-2 loses the retarget rider", "spec",
       "that lands mid-entry retargets it", "that lands mid-entry restarts it"),
    _M("M-34", "G-MATRIX", "the shed order unplaced", "spec",
       "join E11-D06 D23's rung 0", "join E11-D06 D23's ladder"),
    _M("M-35", "G-FLASH", "the band widened past HS-1b", "spec",
       "(4 px wide, PROPOSED)", "(90 px wide, PROPOSED)"),
    _M("M-36", "G-FLASH", "the full-width band bound misstated", "spec",
       "from a 78 px span", "from a 68 px span"),
    _M("M-37", "G-REBUCKET", "a new settle word", "spec",
       '"Period: {mode}" said once, the end silent.', '"Recalculated" said once.'),
    _M("M-38", "G-REBUCKET", "the busy bar off the re-bucket budget", "spec",
       "pending after 300 ms, `14`:1027's", "pending after 200 ms, `14`:1027's"),
    _M("M-39", "G-FRAME", "the story floor made the pass line", "spec",
       "floor, not a pass line, and an fps read", "floor and the pass line, and an fps read"),
    _M("M-40", "G-PREFIX", "a bare W-n", "spec",
       "came from (M-2) and D05 W-1", "came from (M-2) and W-1"),
    _M("M-41", "G-UNTOUCHED", "the shared helper edited", "lib",
       "from __future__", "from  __future__"),
)
# fmt: on


# ---------- modes ---------------------------------------------------------------------------------
def read_tree() -> L.Tree:
    def read(rel: str) -> str:
        p = ROOT / rel
        return p.read_text(encoding="utf-8") if p.exists() else ""

    return L.Tree(
        files={
            "spec": read(SPEC_REL),
            "pins": read(PIN_REL),
            "tool": read(TOOL_REL),
            "lib": read(LIB_REL),
        },
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
