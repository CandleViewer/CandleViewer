#!/usr/bin/env python3
"""E18-D03 (#497) audit: the footprint hi-fi spec and design-system contribution (text first).

Offline and default-deny. The shared gates (git, cites, pins, G-T2 vocabulary, closing keywords,
public text, R7, G-UNTOUCHED, the runner and the mutation harness) live in `spec_audit_lib.py`;
this file keeps only E18-D03's rows. It reads, AS TEXT at the pinned base, the plan and design
texts the spec cites and the token JSON, and, from the working tree, the spec and its hand-off. The only repo code it runs is `contrast_ratio()`, `simulate()`, `delta_e76()`,
`srgb_to_xyz()` and `xyz_to_lab()` of `docs/research/_tools/cvd_simulate.py`, loaded by path.

Gates: G-CITE, G-QUOTE, G-VERSION, G-AC, G-BQ, G-RULED, G-BOARDS, G-PENPOT, G-TOKENS,
G-CONTRAST, G-CVD, G-AC1, G-GLYPH, G-FORMAT, G-SAMPLES, G-T2, G-ENV, G-NOCLOSE, G-PUBLIC,
G-UNTOUCHED and G-MUTLIST (section 16.3 equals this tool's list). Slice 1c adds G-AROWS and
G-HANDOFF with section C and the hand-off.
Pins (G-RULED): each BQ bullet's sha256[:16] in RULED_PINS below, no separate pins file (the
hand-off-pack rule 2, R370 02b); `--repin-ruled` is the only writer, and it also prints where each
pinned D02 line now stands (BQ-1). The BQ list is comment 6599273411 on #497, RULED by comment
6608046466 (G-BQ).

Usage (from the repo root):
  python3 -I docs/design/_tools/e18_d03_hifi_audit.py --check | --self-test | --repin-ruled
  python3 -I docs/design/_tools/e18_d03_hifi_audit.py --fill   (writes 2.3, 2.4, 2.5 and 16.3)
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
BASE = "136142433"  # origin/main at the ruling fold; every cite is read here
BQ_LIST = "6599273411"  # the BQ list on #497
RULING = "6608046466"  # the orchestrator's ruling of record on it
AGREE = frozenset({0, 1, 3, 5, 6, 7, 8})  # the rest are AMEND: 2, 4, 9
BQ_COUNT = 10

SPEC_REL = "docs/design/E18/E18-D03.md"
HANDOFF_REL = "docs/design/E18/E18-D03-handoff.md"
TOOL_REL = "docs/design/_tools/e18_d03_hifi_audit.py"
LIB_REL = "docs/design/_tools/spec_audit_lib.py"
OWN = (SPEC_REL, HANDOFF_REL, TOOL_REL, LIB_REL)
BACKLOG_REL = "docs/plan/backlog/E18.json"

PLAN = {
    "02": "docs/plan/02-definition-of-ready-done.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "24": "docs/plan/24-internal-schemas.md",
    "26": "docs/plan/26-chart-engine-design.md",
}
KEYED = {
    "D02": L.DocRef("docs/design/E18/E18-D02.md", BASE),
    "M": L.DocRef("docs/research/digests/e18-footprint-cell-reading.md", BASE),
    "D01E06": L.DocRef("docs/design/E06/E06-D01.md", BASE),
    "D02E11": L.DocRef("docs/design/E11/E11-D02.md", BASE),
    "D05E11": L.DocRef("docs/design/E11/E11-D05.md", BASE),
    "D05E25": L.DocRef("docs/design/E25/E25-D05.md", BASE),
    "D04E21": L.DocRef("docs/design/E21/E21-D04.md", BASE),
    "D09E09": L.DocRef("docs/design/E09/E09-D09.md", BASE),
    "D04E47": L.DocRef("docs/design/E47/E47-D04.md", BASE),
    "D06E47": L.DocRef("docs/design/E47/E47-D06.md", BASE),
    "D09E47": L.DocRef("docs/design/E47/E47-D09.md", BASE),
    "R32": L.DocRef(".claude/rules/32-design-specs.md", BASE),
    "README": L.DocRef("docs/design/README.md", BASE),
    "SD": L.DocRef("packages/ui/tokens/semantic-dark.tokens.json", BASE),
    "SL": L.DocRef("packages/ui/tokens/semantic-light.tokens.json", BASE),
    "PM": L.DocRef("tools/contrast/pairs.mjs", BASE),
}
CITE_RE = L.cite_regex(KEYED, ranges=True)
THEMES = tuple(L.THEME_PARTS)
DEFICIENCIES = ("deuteranopia", "protanopia", "tritanopia")
DENSITIES = (
    ("comfortable", "`type.num.sm`"),
    ("compact", "`type.num.xs`"),
    ("dense", "`type.num.xs`"),
)
CANVAS = "color.surface.canvas"
TEXT = "color.text.primary"
HALO = "color.footprint.text.outline"
OUTLINE_OPACITY = "opacity.footprint.outline"
FORMING_OPACITY = "opacity.footprint.forming"
HALO_BG = "halo over the heat"
PANEL = "color.surface.raised"
OVERLAY = "color.surface.overlay"
FILL_STOPS = 4

# The PROPOSED tokens of section 2.1, theme by theme (BQ-4): a primitive, an opacity or a width.
PROPOSED: dict[str, tuple[str, str, str]] = {
    HALO: ("`palette.neutral.0`", "`palette.light.neutral.0`", "`palette.neutral.0`"),
    OUTLINE_OPACITY: ("0.80", "0.80", "0.90"),
    FORMING_OPACITY: ("0.80", "0.80", "0.80"),
    "border.footprint.bracket.active": ("3 px", "3 px", "3 px"),
    "border.footprint.bracket.tested": ("2 px", "2 px", "2 px"),
    "border.footprint.bracket.broken": ("1 px", "1 px", "1 px"),
    "color.footprint.poc": (
        "`palette.amber.500`",
        "`palette.light.amber.700`",
        "`palette.amber.500`",
    ),
}
# The ticket's names this pack does not add: allowed only on a line saying "not shipped".
UNSHIPPED = frozenset({"font.mono.xs", "color.footprint.valuearea"})

# `ramp.delta` (D05E11:176), the four inked stops plus the imbalance ink, per palette (BQ-5).
# The imbalance ink is an outline, never a cell fill (R-2), so `fills` takes the stops only.
RAMPS: dict[str, tuple[str, ...]] = {
    "standard": (
        "color.sell.default",
        "color.heatmap.ask.1",
        "color.heatmap.bid.1",
        "color.buy.default",
        "color.footprint.imbalance",
    ),
    "cvd-safe": (
        "color.cvd.sell",
        "color.cvd.heatmap.ask.1",
        "color.cvd.heatmap.bid.1",
        "color.cvd.buy",
        "color.cvd.imbalance",
    ),
}
# Section 2.4, row by row: (mark, ink, against, floor). An ink "token@opacity" is that token at
# the opacity over what it meets (the registry's tested ink, C-7).
MUTED = "opacity.muted"
MARKS: tuple[tuple[str, str, str, float], ...] = (
    ("imbalance outline", "color.footprint.imbalance", HALO_BG, 3.0),
    ("imbalance outline, CVD-safe", "color.cvd.imbalance", HALO_BG, 3.0),
    ("POC rail", "color.footprint.poc", HALO_BG, 3.0),
    ("POC rail, the profile value", "color.profile.poc", HALO_BG, 3.0),
    ("level box, two-tone (F-2)", "color.chart.focus.ring", CANVAS, 3.0),
    ("VA tick", "color.profile.valuearea", CANVAS, 3.0),
    ("sell bracket", "color.sell.default", CANVAS, 3.0),
    ("buy bracket", "color.buy.default", CANVAS, 3.0),
    ("sell bracket, CVD-safe", "color.cvd.sell", CANVAS, 3.0),
    ("buy bracket, CVD-safe", "color.cvd.buy", CANVAS, 3.0),
    ("tested bracket, sell, the registry's ink", f"color.sell.default@{MUTED}", CANVAS, 3.0),
    ("tested bracket, buy, the registry's ink", f"color.buy.default@{MUTED}", CANVAS, 3.0),
    ("broken lane hatch", "color.chart.boundary", CANVAS, 3.0),
    ("forming cap", "color.text.secondary", CANVAS, 3.0),
    ("bracket label text", TEXT, CANVAS, 4.5),
    ("SCR-056 side glyph, buy", "color.buy.default", PANEL, 3.0),
    ("SCR-056 side glyph, sell", "color.sell.default", PANEL, 3.0),
    ("SCR-056 side and status words", TEXT, PANEL, 4.5),
    ("SCR-056 selection", "color.border.selected", PANEL, 3.0),
    ("T2 label", "color.text.tertiary", OVERLAY, 4.5),
    ("T2 reason", "color.text.secondary", OVERLAY, 4.5),
)
# Measured, not gated: BQ-4's test of the profile POC on the cell fill, and the registry's tested
# ink on the canvas lane, which the lane does not use (section 2.4; C-7).
REPORTED = frozenset(
    {"color.profile.poc", f"color.sell.default@{MUTED}", f"color.buy.default@{MUTED}"}
)
SIG_STATES = (
    "no flag",
    "buy flag, L0",
    "sell flag, L0",
    "buy flag, L1",
    "sell flag, L1",
    "buy stack, active",
    "buy stack, tested",
    "buy stack, broken",
    "sell stack, active",
    "sell stack, tested",
    "sell stack, broken",
)
WEIGHTS = {"active": "3 px", "tested": "2 px", "broken": "1 px"}
# BQ-2 (RULED): the registered patterns win where the meaning is the same (D05E11 section 7).
STATE_IDS = {"tested": "`pattern.dashed.tested`", "broken": "`pattern.hatch.absent`"}
# 26:282: printable ASCII plus the three mono extras; the canvas never needs another glyph.
CANVAS_GLYPHS = frozenset(chr(c) for c in range(0x20, 0x7F)) | {"×", "▲", "▼"}
COMPACT_RE = re.compile(r"\d(?:\.\d+)?[KMB]\b")
FORMAT_ROWS = 7
INVALIDATIONS = 5
MODES = ("Bid × Ask", "Volume", "Delta", "Delta / Total")
BAN_RE = re.compile(r"\b(?:dash(?:ed)?|hatch(?:ed)?)\b", re.IGNORECASE)
# G-RULED: sha256[:16] of each RULED BQ bullet; `--repin-ruled` rewrites the block, nothing else.
PINS_OPEN = 'RULED_PINS = """\n'
PINS_CLOSE = '"""  # end of the ruled pins'
RULED_PINS = """
BQ-0 30751ee038b0c596
BQ-1 e4d1b7385446bf6b
BQ-2 96794f3c0610d583
BQ-3 851fd69660ce6b30
BQ-4 e4bcdae43d3e6df0
BQ-5 3130f065ff4ffb0b
BQ-6 4f40a7ea895c8f39
BQ-7 6a3870e8ef137e06
BQ-8 4f526ff9bad0e4b7
BQ-9 71a834638c3b1dac
"""  # end of the ruled pins
# BQ-1: D02 lines this pack builds on, re-pinned when #496's boards PR moves them.
KEY_CITES = (
    L.KeyCite("D02", 155, "D5  | Imbalance"),
    L.KeyCite("D02", 157, "alpha is E18-D03's"),
    L.KeyCite("D02", 289, "3 px active, 2 px tested, 1 px broken"),
    L.KeyCite("D02", 877, "A-25"),
    L.KeyCite("D02", 935, "E18-D03 (#497)"),
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
def cvd() -> ModuleType:
    return L.load_module(ROOT, "docs/research/_tools/cvd_simulate.py", "cvd_simulate")


@functools.cache
def primitives() -> dict[str, str]:
    raw = L.token_file(repo(), BASE, "primitives")
    return {k: str(v.get("$value", "")) for k, v in raw.items()}


@functools.cache
def theme(name: str) -> dict[str, str]:
    t = dict(L.resolve_theme(repo(), BASE, name))
    idx = THEMES.index(name)
    for tok in (HALO, "color.footprint.poc"):
        t[tok] = primitives()[PROPOSED[tok][idx].strip("`")]
    return t


def opacity(tok: str, name: str) -> float:
    return float(PROPOSED[tok][THEMES.index(name)])


def blend(fg: str, bg: str, a: float) -> str:
    f = [int(fg[i : i + 2], 16) for i in (1, 3, 5)]
    b = [int(bg[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(a * x + (1 - a) * y):02X}" for x, y in zip(f, b, strict=True))


def ratio(a: str, b: str) -> float:
    return float(cvd().contrast_ratio(a, b))


def fills(name: str, palette: str | None = None) -> list[tuple[str, str]]:
    """Every fill a cell can reach (BQ-8): one palette's stops (both when None), the canvas, and
    each stop at the forming opacity; never the imbalance ink, an outline (R-2); (label, hex)."""
    t = theme(name)
    out = [(CANVAS, t[CANVAS])]
    for pal, stops in RAMPS.items():
        if palette not in (None, pal):
            continue
        for s in stops[:FILL_STOPS]:
            out.append((s, t[s]))
            out.append((f"{s} forming", blend(t[s], t[CANVAS], opacity(FORMING_OPACITY, name))))
    return out


def halo_over(name: str, fill_hex: str) -> str:
    return blend(theme(name)[HALO], fill_hex, opacity(OUTLINE_OPACITY, name))


def text_row(name: str, palette: str, density: str, size: str) -> list[str]:
    t = theme(name)
    bare = min(fills(name, palette), key=lambda f: ratio(t[TEXT], f[1]))
    lined = min(fills(name, palette), key=lambda f: ratio(t[TEXT], halo_over(name, f[1])))
    return [
        name,
        palette,
        density,
        size,
        f"`{bare[0].removesuffix(' forming')}`" + (" forming" if "forming" in bare[0] else ""),
        f"{ratio(t[TEXT], bare[1]):.2f}",
        f"`{lined[0].removesuffix(' forming')}`" + (" forming" if "forming" in lined[0] else ""),
        f"{ratio(t[TEXT], halo_over(name, lined[1])):.2f}",
        "4.5",
    ]


def mark_value(name: str, ink: str, against: str) -> float:
    t = theme(name)
    tok, _, alpha = ink.partition("@")
    if against == HALO_BG:
        return min(ratio(t[tok], halo_over(name, f[1])) for f in fills(name))
    fg = blend(t[tok], t[against], float(primitives()[alpha])) if alpha else t[tok]
    return ratio(fg, t[against])


def mark_row(mark: str, ink: str, against: str, floor: float) -> list[str]:
    bg = against if against == HALO_BG else f"`{against}`"
    vals = [f"{mark_value(n, ink, against):.2f}" for n in THEMES]
    cell = f"{floor:g}, reported" if ink in REPORTED else f"{floor:g}"
    tok, _, alpha = ink.partition("@")
    shown = f"`{tok}` at `{alpha}`" if alpha else f"`{tok}`"
    return [mark, shown, bg, cell, *vals]


def grey(hexv: str) -> float:
    return float(cvd().xyz_to_lab(cvd().srgb_to_xyz(hexv))[0])


def cvd_row(name: str, palette: str) -> list[str]:
    t = theme(name)
    s1, se, be, b1, im = (t[k] for k in RAMPS[palette])
    out = [name, palette]
    for d in DEFICIENCIES:

        def sim(h: str, d: str = d) -> str:
            return str(cvd().simulate(h, d))

        de = cvd().delta_e76
        out += [
            f"{de(sim(s1), sim(b1)):.1f}",
            f"{de(sim(se), sim(be)):.1f}",
            f"{min(de(sim(im), sim(s1)), de(sim(im), sim(b1))):.1f}",
        ]
    out += [
        f"{abs(grey(s1) - grey(b1)):.1f}",
        f"{abs(grey(se) - grey(be)):.1f}",
        f"{min(abs(grey(im) - grey(s1)), abs(grey(im) - grey(b1))):.1f}",
    ]
    return out


# ---------- spec helpers --------------------------------------------------------------------------
def rows(block: str) -> list[list[str]]:
    return L.table_rows(block)


def sec(t: L.Tree, heading: str, label: str = "spec") -> str:
    return L.section(t.text(label), heading)


def copy_deck(spec: str) -> dict[str, list[str]]:
    return {r[0]: r for r in rows(L.section(spec, "## 11. Copy deck"))}


def cited_text(cell: str) -> str:
    c = L.extract_cites(cell, CITE_RE)
    if not c:
        return ""
    lines = [line_of(c[0].doc, n) for n in range(c[0].lo, c[0].hi + 1)]
    return squash(" ".join(lines))


def squash(s: str) -> str:
    """Whitespace runs as one space: prettier collapses them inside table cells."""
    return " ".join(s.split())


# ---------- this spec's gates ---------------------------------------------------------------------
def g_cite(t: L.Tree) -> list[str]:
    texts = t.text("spec") + "\n" + t.text("handoff")
    bad = L.check_cites(L.extract_cites(texts, CITE_RE), docs(), min_count=60)
    return [f"unresolved cites: {', '.join(b.split(' (')[0] for b in bad)}"] if bad else []


def g_quote(t: L.Tree) -> list[str]:
    bad = []
    for r in copy_deck(t.text("spec")).values():
        if len(r) < 5 or not r[4].startswith("verbatim"):
            continue
        if squash(L.unquote(r[2])) not in cited_text(r[3]):
            bad.append(r[0])
    return [f"not on the cited line: {', '.join(bad)}"] if bad else []


def g_version(t: L.Tree) -> list[str]:
    v, spec = sec(t, "### 16.1 Version line"), t.text("spec")
    miss = [n for n in (BASE, "re-pinned", "#496", "--repin-ruled") if n not in v]
    if f"Base `origin/main` `{BASE}`" not in spec:
        miss.append("Inputs pinned base")
    return [f"missing: {', '.join(miss)}"] if miss else []


def g_ac(t: L.Tree) -> list[str]:
    tickets = json.loads(repo().show(BASE, BACKLOG_REL) or "[]")
    body = next(str(x.get("body", "")) for x in tickets if x.get("key") == "E18-D03")
    names = re.findall(r"Scenario: (.+)", body)
    dod = re.findall(r"- \[ \] (.+)", body)
    trace = sec(t, "## Acceptance-criteria and DoD trace")
    first = [r[0] for r in rows(trace)]
    miss = [n for n in names if f'AC "{n.strip()}"' not in first]
    miss += [d for d in dod if f"DoD {d.strip()}" not in first]
    ac3 = next((r for r in rows(trace) if r[0].startswith('AC "Every cell mode')), [])
    if len(ac3) < 3 or not ac3[2].startswith("done under the ruling") or RULING not in ac3[2]:
        miss.append("AC 3 not traced done under the ruling")
    if len(names) != 3 or len(dod) != 6:
        miss.append(f"{len(names)} scenarios, {len(dod)} DoD items")
    return [f"not traced verbatim: {miss}"] if miss else []


def g_bq(t: L.Tree) -> list[str]:
    bad = L.check_ruling(
        t.text("spec"),
        heading_line=(
            f"## The questions BQ-0 … BQ-{BQ_COUNT - 1} — RULED (comment {RULING}, "
            f"on the BQ list {BQ_LIST})"
        ),
        list_ref=f"comment {BQ_LIST} on #497",
        count=BQ_COUNT,
        verdict=lambda n: "**RULED: AGREE" if n in AGREE else "**RULED: AMEND.**",
        need=("Applied:",),
        forbid=("PENDING", "ORCH-default"),
    )
    if f"comment {RULING}" not in L.section(t.text("spec"), L.BQ_HEADING):
        bad.append("the ruling id")
    walk = sec(t, "## 15. Owner walkthrough")
    if f"comment {BQ_LIST}) is RULED (comment {RULING})" not in walk:
        bad.append("the walkthrough's BQ item")
    return bad


def g_ruled(t: L.Tree) -> list[str]:
    return L.check_hash_pins(t.text("spec"), RULED_PINS) + L.check_key_cites(KEY_CITES, docs())


def g_boards(t: L.Tree) -> list[str]:
    return L.board_cap(rows(sec(t, "## 0. Status")), "E18-D03", t.text("spec"))


def g_penpot(t: L.Tree) -> list[str]:
    return L.r7_findings(
        t.named("spec", "handoff"), ("page `E18-D03`", "page id"), sec(t, "## 0. Status")
    )


def g_tokens(t: L.Tree) -> list[str]:
    names = L.token_names(repo(), BASE)
    bad = []
    for label in ("spec", "handoff"):
        for line in t.text(label).split("\n"):
            for name in L.check_token_refs(line, names):
                if name in PROPOSED:
                    continue
                if name in UNSHIPPED and "not shipped" in line:
                    continue
                bad.append(f"{label}: {name}")
    got = {r[0].strip("`"): r for r in rows(sec(t, "### 2.1 The token map"))}
    for name, vals in PROPOSED.items():
        r = got.get(name, [])
        if len(r) < 6 or tuple(r[2:5]) != vals or r[5] != "PROPOSED":
            bad.append(f"{name} row differs from the tool")
        for v in vals:
            if v.startswith("`palette.") and v.strip("`") not in primitives():
                bad.append(f"{v} is not a primitive")
    return sorted(set(bad))


def g_contrast(t: L.Tree) -> list[str]:
    bad = []
    want = [text_row(n, p, d, s) for n in THEMES for p in RAMPS for d, s in DENSITIES]
    got = rows(sec(t, "### 2.3 Cell text over the heat"))
    if got != want:
        bad.append("section 2.3 differs from the measurement (run --fill)")
    bad += [f"{w[0]} {w[1]} {w[2]} outlined {w[7]} < 4.5" for w in want if float(w[7]) < 4.5]
    marks = [mark_row(*m) for m in MARKS]
    if rows(sec(t, "### 2.4 Marks over the heat")) != marks:
        bad.append("section 2.4 differs from the measurement (run --fill)")
    for m in marks:
        if m[3].endswith("reported"):
            continue
        if min(float(v) for v in m[4:]) < float(m[3]):
            bad.append(f"{m[0]} below {m[3]}")
    return bad


def g_cvd(t: L.Tree) -> list[str]:
    want = [cvd_row(n, p) for n in THEMES for p in RAMPS]
    bad = [] if rows(sec(t, "### 2.5 Colour vision")) == want else ["section 2.5 differs (--fill)"]
    for w in want:
        low = min(float(v) for v in w[2:11])
        if low < 5.0:
            bad.append(f"{w[0]} {w[1]} has a pair at {low} < 5.0")
    return bad


def g_ac1(t: L.Tree) -> list[str]:
    got = rows(sec(t, "### 3.1 The imbalance signatures"))
    bad = [] if [r[0] for r in got] == list(SIG_STATES) else [f"states {[r[0] for r in got]}"]
    sigs = [tuple(r[1:5]) for r in got if len(r) >= 6]
    if len(set(sigs)) != len(sigs):
        bad.append("two states share a non-colour signature")
    for r in got:
        if len(r) < 6:
            bad.append(f"{r[0]} cells")
            continue
        state = r[0].rsplit(", ", 1)[-1]
        if state in WEIGHTS and r[3] != WEIGHTS[state]:
            bad.append(f"{r[0]} weight {r[3]}")
        sig = " ".join(r[1:5])
        if state in STATE_IDS and STATE_IDS[state] not in sig:
            bad.append(f"{r[0]} lacks {STATE_IDS[state]}")
        for sid in STATE_IDS.values():
            sig = sig.replace(sid, "")
        if state in STATE_IDS:
            sig = sig.replace("dashed 4 / 3" if state == "tested" else "hatched", "")
        if BAN_RE.search(sig):
            bad.append(f"{r[0]} uses an unregistered dash or hatch")
    if "3 px active, 2 px tested, 1 px broken" not in line_of("D02", 289):
        bad.append("D02:289 weights moved")
    return bad


def g_glyph(t: L.Tree) -> list[str]:
    bad = []
    for r in copy_deck(t.text("spec")).values():
        if len(r) > 2 and r[1].startswith("canvas"):
            out = sorted({c for c in L.unquote(r[2]) if c not in CANVAS_GLYPHS})
            if out:
                bad.append(f"{r[0]} needs {out}")
    for r in rows(sec(t, "### 4.1 The formats")):
        out = sorted({c for c in r[3].strip("`") if c not in CANVAS_GLYPHS}) if len(r) > 3 else []
        if out:
            bad.append(f"format {r[0]} needs {out}")
    return bad


def g_format(t: L.Tree) -> list[str]:
    s4 = sec(t, "## 4. Number formats")
    got = rows(sec(t, "### 4.1 The formats"))
    bad = [] if len(got) == FORMAT_ROWS else [f"{len(got)} format rows"]
    bad += [f"{r[0]} compact" for r in got if len(r) > 3 and COMPACT_RE.search(r[3])]
    inval = rows(sec(t, "### 4.2 What invalidates a glyph run"))
    if len(inval) != INVALIDATIONS:
        bad.append(f"{len(inval)} invalidating events")
    for need in ("never compact", "U+2212", "one text pass"):
        if need not in s4:
            bad.append(need)
    return bad


def g_samples(t: L.Tree) -> list[str]:
    got = rows(sec(t, "## 9. Rendered samples"))
    want = [(m, d) for m in MODES for d, _ in DENSITIES]
    have = [(r[0], r[1]) for r in got if len(r) > 3]
    bad = [] if have == want else [f"{len(have)} sample rows for {len(want)}"]
    bad += [f"{r[0]} {r[1]} not SYNTHETIC" for r in got if len(r) > 3 and "SYNTHETIC" not in r[3]]
    return bad


def g_t2(t: L.Tree) -> list[str]:
    spec = t.text("spec")
    r4 = next((ln for ln in spec.split("\n") if ln.startswith("- **R-4 ")), "")
    bad = L.t2_markers(r4) + L.no_disabled_tokens(spec) + L.no_disabled_tokens(t.text("handoff"))
    d09 = repo().show(BASE, KEYED["D09E09"].rel) or ""
    keys = L.d09_keys(d09)
    bad += L.t2_reason_keys(spec, keys)
    for r in rows(sec(t, "### 1.4 The gated controls")):
        if len(r) < 4 or r[1].split(":")[0] not in ("2a", "sentence form"):
            bad.append(f"{r[0] if r else '?'} rendering")
        elif not re.search(r"W-\d+", r[2]):
            bad.append(f"{r[0]} reason")
    return bad


def g_env(t: L.Tree) -> list[str]:
    r1 = next((ln for ln in t.text("spec").split("\n") if ln.startswith("- **R-1 ")), "")
    need = ("C-2.11", "hard constraint", "public market data", "no environment")
    return [n for n in need if n not in r1]


def g_noclose(t: L.Tree) -> list[str]:
    return L.closing_keywords(t.named("spec", "handoff"))


def g_public(t: L.Tree) -> list[str]:
    named = t.named("spec", "handoff")
    return L.scan_public(named) + L.comment_findings(named) + L.whitespace_hygiene(named)


def g_untouched(t: L.Tree) -> list[str]:
    return L.untouched(t.changed, OWN, ("docs/design/E18/img/E18-D03-*.png",), {}, t.numstat)


def g_mutlist(t: L.Tree) -> list[str]:
    return L.check_mutlist(t.text("spec"), "### 16.3", MUTATIONS)


# fmt: off
GATES = tuple(L.Gate("G-" + f.__name__[2:].upper(), f) for f in (
    g_cite, g_quote, g_version, g_ac, g_bq, g_ruled, g_boards, g_penpot, g_tokens, g_contrast,
    g_cvd, g_ac1, g_glyph, g_format, g_samples, g_t2, g_env, g_noclose, g_public, g_untouched,
    g_mutlist,
))
# fmt: on

_M = L.Mutation
_V = "### 16.1 Version line\n"
# fmt: off
MUTATIONS: tuple[L.Mutation, ...] = (
    _M("M-1", "G-CITE", "a cite past the end of `26`", "spec", "`26`:295", "`26`:99999"),
    _M("M-2", "G-QUOTE", "W-8 reworded off its line", "spec",
       '"Reduced detail — footprint text hidden · zoom in for numbers"',
       '"Reduced detail — text hidden · zoom in for numbers"'),
    _M("M-3", "G-VERSION", "the version line drops the re-pin", "spec",
       "D02 lines re-pinned with `--repin-ruled`", "D02 lines kept"),
    _M("M-4", "G-AC", "a scenario name reworded", "spec",
       'AC "Imbalance survives greyscale"', 'AC "Imbalance survives grey"'),
    _M("M-5", "G-AC", "AC 3 traced open", "spec",
       "| done under the ruling (comment", "| open under the ruling (comment"),
    _M("M-6", "G-BQ", "the heading drops the ruling", "spec",
       "— RULED (comment 6608046466, on the BQ list", "— defaults built (comment 6608046466, on"),
    _M("M-7", "G-RULED", "a ruled bullet edited without a re-pin", "spec",
       "ten boards, one light and one high-contrast", "nine boards, one light and one high-contrast"),
    _M("M-8", "G-BOARDS", "an eleventh board", "spec",
       r"(\| 10 +\| `E18-D03 / 10 [^\n]*\n)",
       r"\1| 11  | `E18-D03 / 11 extra` | x | dark | PENDING |\n", regex=True),
    _M("M-9", "G-BOARDS", "a board marked drawn", "spec",
       r"(`E18-D03 / 10 [^\n]*\| )PENDING", r"\1DRAWN  ", regex=True),
    _M("M-10", "G-PENPOT", "a Penpot file id", "spec",
       "page `E18-D03`, cited", "page `E18-D03` (" + "file" + "-id=0), cited"),
    _M("M-11", "G-TOKENS", "an unshipped token bound", "spec",
       "the ring is `color.chart.focus.ring`", "the ring is `color.chart.focus.halo`"),
    _M("M-12", "G-TOKENS", "a PROPOSED value drifts from the tool", "spec",
       r"(`opacity\.footprint\.outline` *\|[^|]*\| )0\.80", r"\g<1>0.70", regex=True),
    _M("M-13", "G-CONTRAST", "a written text ratio drifts", "spec",
       r"(\| dark +\| standard +\| compact +\|[^\n]*\| )(\d+\.\d\d)( +\| 4\.5)", r"\g<1>99.99\3",
       regex=True),
    _M("M-14", "G-CVD", "a written distance drifts", "spec",
       r"(\| light +\| standard +\| )(\d+\.\d)", r"\g<1>0.1", regex=True),
    _M("M-15", "G-AC1", "two states share a signature", "spec",
       r"\| buy stack, broken( +)\| — ", r"| buy stack, tested\1| — ", regex=True),
    _M("M-16", "G-AC1", "an active bracket drawn dashed", "spec",
       r"(\| sell stack, active \| —\s+\| left lane, )solid", r"\1dashed", regex=True),
    _M("M-17", "G-AC1", "tested loses its registered pattern", "spec",
       r"(\| sell stack, tested \| —\s+\| left lane, )dashed 4 / 3 \(`pattern\.dashed\.tested`\)",
       r"\1solid", regex=True),
    _M("M-18", "G-GLYPH", "a canvas format needs U+2212", "spec",
       "`▲ +812.5`", "`▲ \u2212812.5`"),
    _M("M-19", "G-FORMAT", "a compact form returns", "spec", "`12,450`", "`12.4K`"),
    _M("M-20", "G-SAMPLES", "a sample no longer SYNTHETIC", "spec",
       r"(\| Volume +\| dense +\| [^|]*\| )SYNTHETIC", r"\1recorded ", regex=True),
    _M("M-21", "G-T2", "R-4 loses the opacity ban", "spec",
       "never `color.text.disabled`, never `opacity.disabled`", "never `color.text.disabled`"),
    _M("M-22", "G-T2", "a reason from a key E09-D09 lacks", "spec",
       "`rbac.owner_only`", "`rbac.owner_rule`"),
    _M("M-23", "G-ENV", "C-2.11 no longer hard", "spec",
       "C-2.11 is a hard constraint", "C-2.11 is a preference"),
    _M("M-24", "G-NOCLOSE", "a closing keyword", "spec", _V, _V + "\n" + "Clo" + "ses #497.\n"),
    _M("M-25", "G-PUBLIC", "a URL", "spec",
       "Penpot: the file", "Penpot (" + "http" + "s://example.org): the file"),
    _M("M-26", "G-UNTOUCHED", "an owner document edited", "@changed",
       "", "docs/plan/15-component-catalogue.md"),
    _M("M-27", "G-MUTLIST", "the list drifts", "spec", "| M-1  | G-CITE ", "| M-1  | G-AC   "),
)
# fmt: on


# ---------- modes ---------------------------------------------------------------------------------
def read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def read_tree() -> L.Tree:
    base = repo().diff_base(BASE)
    return L.Tree(
        files={"spec": read(SPEC_REL), "handoff": read(HANDOFF_REL)},
        changed=repo().changed_paths(base),
    )


def check() -> int:
    return L.report(L.run_gates(GATES, read_tree()))


def self_test() -> int:
    disk = [ROOT / rel for rel in OWN]
    return L.self_test(read_tree(), GATES, MUTATIONS, disk, namespace=globals())


def repin() -> int:
    lines = L.bq_hash_pins(read(SPEC_REL))
    tool = read(TOOL_REL)
    a = tool.index(PINS_OPEN) + len(PINS_OPEN)
    b = tool.index(PINS_CLOSE, a)
    L.write_pins(ROOT / TOOL_REL, tool[:a] + "\n".join(lines) + "\n" + tool[b:])
    print(f"pinned {len(lines)} BQ lines")
    for kc, now in L.repin_key_cites(KEY_CITES, docs()):
        print(f"{kc.doc}:{kc.line} -> {now if now is not None else 'GONE'} ({kc.needle!r})")
    return 0


def table(head: list[str], body: list[list[str]]) -> str:
    out = ["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
    return "\n".join(out + ["| " + " | ".join(r) + " |" for r in body])


def replace_table(spec: str, heading: str, text: str) -> str:
    t0 = spec.index("\n|", spec.index(heading)) + 1
    end = t0
    for line in spec[t0:].split("\n"):
        if not line.startswith("|"):
            break
        end += len(line) + 1
    return spec[:t0] + text + "\n" + spec[end:]


def fill() -> int:
    p = ROOT / SPEC_REL
    spec = p.read_text(encoding="utf-8")
    h23 = ["Theme", "Palette", "Density", "Size class", "Worst fill, bare", "Bare"]
    t23 = table(
        h23 + ["Worst fill, outlined", "Outlined", "Floor"],
        [text_row(n, p, d, s) for n in THEMES for p in RAMPS for d, s in DENSITIES],
    )
    t24 = table(
        ["Mark", "Ink", "Against", "Floor", "dark", "light", "high-contrast"],
        [mark_row(*m) for m in MARKS],
    )
    h25 = ["Theme", "Palette"] + [
        f"{d[:4].title()} {p}" for d in DEFICIENCIES for p in ["±1", "±ε", "imb"]
    ]
    t25 = table(
        h25 + ["Grey ±1", "Grey ±ε", "Grey imb"], [cvd_row(n, q) for n in THEMES for q in RAMPS]
    )
    spec = replace_table(spec, "### 2.3 Cell text over the heat", t23)
    spec = replace_table(spec, "### 2.4 Marks over the heat", t24)
    spec = replace_table(spec, "### 2.5 Colour vision", t25)
    spec = replace_table(spec, "### 16.3", L.mutation_table(MUTATIONS))
    p.write_text(spec, encoding="utf-8", newline="\n")
    print("sections 2.3, 2.4, 2.5 and 16.3 written")
    return 0


def main(argv: list[str]) -> int:
    modes = {"check": check, "self-test": self_test, "repin-ruled": repin, "fill": fill}
    return L.cli(argv, modes, __doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
