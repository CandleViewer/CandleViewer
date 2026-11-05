#!/usr/bin/env python3
"""E20-D03 (#575) audit: the Deep Stats hi-fi spec and the CMP-225 entry (text first).

Offline and default-deny. The shared gates (git, cites, pins, G-T2 vocabulary, closing keywords,
public text, R7, G-UNTOUCHED, the runner and the mutation harness) live in `spec_audit_lib.py`
beside this file, imported only when it matches its content pin, never copied; this file keeps
only E20-D03's rows. It reads, AS TEXT at the pinned base, the plan and design texts the spec
cites and the token JSON, E20-D02's boards PR at its pinned head, and, from the working tree, the
spec. The only other repo code it runs is `contrast_ratio()` of
`docs/design/_tools/contrast_check.py` and `simulate()`, `delta_e76()`, `srgb_to_xyz()` and
`xyz_to_lab()` of `docs/research/_tools/cvd_simulate.py`, each loaded by path.

Gates: G-CITE, G-QUOTE, G-VERSION, G-AC, G-BQ, G-RULED, G-BOARDS, G-PENPOT, G-TOKENS,
G-CONTRAST, G-CVD, G-REDLINE, G-GLYPH, G-FORMAT, G-T2, G-ENV, G-AROWS, G-NOCLOSE, G-PUBLIC,
G-UNTOUCHED and G-MUTLIST (section 13.3 equals this tool's list).
Pins (G-RULED): each BQ bullet's sha256[:16] in BQ_PINS below, no separate pins file;
`--repin` is the only writer, and it also prints where each pinned E20-D02 line now stands. The
BQ list is comment 6649847483 on #575; its ruling is pending (RULING is None until it lands).

Usage (from the repo root):
  python3 -I docs/design/_tools/e20_d03_hifi_audit.py --check | --self-test | --repin
  python3 -I docs/design/_tools/e20_d03_hifi_audit.py --fill   (writes 2.2, 2.3, 6.1, 4.2, 13.3)
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import functools
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from types import ModuleType

_LIB = Path(__file__).resolve().parent / "spec_audit_lib.py"
LIB_SHA256 = "62b56d6446b218cd300a9e2591e47b84f20962a6c33a58ebe9b8c2fbc83f48fd"
# The content pin is checked before the import, never after it.
if hashlib.sha256(_LIB.read_bytes()).hexdigest() != LIB_SHA256:
    sys.exit(f"{_LIB.name} is not the pinned helper; refusing to import it")
sys.path.insert(0, str(_LIB.parent))
import spec_audit_lib as L  # noqa: E402 - imported only after its content pin holds

ROOT = Path(__file__).resolve().parents[3]
BASE = "9a5ed9846a996ca2bfb953438ca03036190fd000"  # origin/main; every cite is read here
D02_HEAD = "a2023e217966e362942c779233647adbcdeb3e68"  # E20-D02's boards PR head; re-pin at merge
BQ_LIST = "6649847483"  # the BQ list on #575
RULING: str | None = None  # the ruling of record, once it lands
BQ_COUNT = 10
TICKET = "E20-D03"

SPEC_REL = "docs/design/E20/E20-D03.md"
TOOL_REL = "docs/design/_tools/e20_d03_hifi_audit.py"
OWN = (SPEC_REL, TOOL_REL)
BACKLOG_REL = "docs/plan/backlog/E20.json"

PLAN = {
    "04": "docs/plan/04-security-program.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "22": "docs/plan/22-api-openapi.yaml",
}
KEYED = {
    "D02": L.DocRef("docs/design/E20/E20-D02.md", BASE),
    "D02H": L.DocRef("docs/design/E20/E20-D02.md", D02_HEAD),
    "M": L.DocRef("docs/design/research/e20-deep-stats.md", BASE),
    "E20.json": L.DocRef(BACKLOG_REL, BASE),
    "D03E18": L.DocRef("docs/design/E18/E18-D03.md", BASE),
    "D05E11": L.DocRef("docs/design/E11/E11-D05.md", BASE),
    "D06E12": L.DocRef("docs/design/E12/E12-D06.md", BASE),
    "D09E09": L.DocRef("docs/design/E09/E09-D09.md", BASE),
    "D03E47": L.DocRef("docs/design/E47/E47-D03.md", BASE),
    "D04E47": L.DocRef("docs/design/E47/E47-D04.md", BASE),
    "CCM": L.DocRef("packages/ui/scripts/chart-color-modes.mjs", BASE),
    "R32": L.DocRef(".claude/rules/32-design-specs.md", BASE),
    "README": L.DocRef("docs/design/README.md", BASE),
}
CITE_RE = L.cite_regex(KEYED, ranges=True)
THEMES = tuple(L.THEME_PARTS)
PALETTES = ("standard", "cvd-safe")
DEFICIENCIES = ("deuteranopia", "protanopia", "tritanopia")

# ---------- section 2.1: the PROPOSED tokens (BQ-3, BQ-5: the matrix forces exactly these) -------
BUY_SHADE, SELL_SHADE, INFO_SHADE = (
    "color.buy.subtle",
    "color.sell.subtle",
    "color.status.info.subtle",
)
CVD_BUY_SHADE, CVD_SELL_SHADE = "color.cvd.buy.subtle", "color.cvd.sell.subtle"
PROPOSED: dict[str, tuple[str, str, str]] = {
    CVD_BUY_SHADE: ("`palette.blue.900`", "`palette.light.blue.700`", "`palette.blue.900`"),
    CVD_SELL_SHADE: ("`palette.amber.900`", "`palette.light.amber.900`", "`palette.amber.900`"),
}
# Names the ticket or `15` uses that are not shipped and not added: only on a "not shipped" line.
UNSHIPPED = frozenset({"font.mono", "font.feature.tabularNums", "color.neutral.default"})

# The cvd-safe remap of `chart-color-modes.mjs` (CCM:7-17): as shipped, every directional pair,
# `.subtle` included, takes the full CVD stop; the reading taken (C-3, A-9) remaps `.subtle` to
# the PROPOSED shades instead. "shipped" rows are measured and reported, never gated.
REMAP = {
    "color.buy.default": "color.cvd.buy",
    "color.sell.default": "color.cvd.sell",
    BUY_SHADE: CVD_BUY_SHADE,
    SELL_SHADE: CVD_SELL_SHADE,
}
REMAP_SHIPPED = {**REMAP, BUY_SHADE: "color.cvd.buy", SELL_SHADE: "color.cvd.sell"}

CANVAS, TEXT, SECONDARY, TERTIARY = (
    "color.surface.canvas",
    "color.text.primary",
    "color.text.secondary",
    "color.text.tertiary",
)
RING, OVERLAY, RAISED = "color.focus.ring", "color.surface.overlay", "color.surface.raised"
# Section 2.2, row by row: (pair, ink, against, floor). "@shipped" measures the shipped remap.
PAIRS: tuple[tuple[str, str, str, float], ...] = (
    ("cell value, neutral", TEXT, CANVAS, 4.5),
    ("cell value, buy shade", TEXT, BUY_SHADE, 4.5),
    ("cell value, sell shade", TEXT, SELL_SHADE, 4.5),
    ("cell value, unsigned shade", TEXT, INFO_SHADE, 4.5),
    ("cell value, buy shade as shipped", TEXT, BUY_SHADE + "@shipped", 4.5),
    ("cell value, sell shade as shipped", TEXT, SELL_SHADE + "@shipped", 4.5),
    ("row label, legend, forming word", SECONDARY, CANVAS, 4.5),
    ("unit suffix", TERTIARY, CANVAS, 4.5),
    ("T2 label, SCR-033", TERTIARY, OVERLAY, 4.5),
    ("T2 reason, SCR-033", SECONDARY, OVERLAY, 4.5),
    ("T2 label, SCR-045", TERTIARY, RAISED, 4.5),
    ("T2 reason, SCR-045", SECONDARY, RAISED, 4.5),
    ("hint chip", SECONDARY, "color.surface.selected", 4.5),
    ("validation message", TEXT, OVERLAY, 4.5),
    ("invalid field boundary", "color.status.danger.default", "color.surface.overlay", 3.0),
    ("buy sign glyph", "color.buy.default", CANVAS, 3.0),
    ("sell sign glyph", "color.sell.default", CANVAS, 3.0),
    ("buy sign glyph on its shade", "color.buy.default", BUY_SHADE, 3.0),
    ("sell sign glyph on its shade", "color.sell.default", SELL_SHADE, 3.0),
    ("breach glyph, buy shade", TEXT, BUY_SHADE, 3.0),
    ("breach glyph, sell shade", TEXT, SELL_SHADE, 3.0),
    ("breach glyph, unsigned shade", TEXT, INFO_SHADE, 3.0),
    ("presence mark", SECONDARY, CANVAS, 3.0),
    ("sparkline", TERTIARY, CANVAS, 3.0),
    ("forming ring", "color.candle.wick", CANVAS, 3.0),
    ("focus ring, gear and neutral cell", RING, CANVAS, 3.0),
    ("focus ring, inset on the buy shade", RING, BUY_SHADE, 3.0),
    ("focus ring, inset on the sell shade", RING, SELL_SHADE, 3.0),
    ("focus ring, inset on the unsigned shade", RING, INFO_SHADE, 3.0),
)


# ---------- section 6: redlines (BQ-3, BQ-6) ---------------------------------------------------
DENSITIES = ("compact", "comfortable")
ROW_SETS = (("Default", 5), ("AllRows", 12))
MONO_ADVANCE = 0.6  # JetBrains Mono's advance, 600 of 1,000 units/em (`16`:98 locks the family)
VALUE_CLASS = "type.num.sm"
# Section 4.2: the widest Total Notional strings at the PROPOSED ten-digit design bound (OQ-1).
WIDEST = (
    ("full, breached", "■ 9,999,999,999"),
    ("full", "9,999,999,999"),
    ("abbreviated, breached", "■ 9,999.9M"),
    ("abbreviated", "9,999.9M"),
)
SIGN_GLYPHS = frozenset({"▲", "▼"})
PRESENCE = "·"
BREACH = "■"
GEOMETRIC = range(0x25A0, 0x2600)  # the Geometric Shapes block, the sign glyphs' own
SIG_STATES = (
    "neutral, signed, buy",
    "neutral, signed, sell",
    "neutral, unsigned",
    "breached, signed, buy",
    "breached, signed, sell",
    "breached, unsigned",
    "collapsed, signed, buy",
    "collapsed, signed, sell",
    "collapsed, unsigned",
    "collapsed, breached, buy",
    "collapsed, breached, sell",
    "collapsed, breached, unsigned",
    "no order flow",
)
# G-AROWS: section C's A-rows each quote an owner line verbatim (Old) and say New.
AROW_COUNT = 8
# G-T2: verbs E09-D09 section 3.2 lacks, PROPOSED here and routed (A-11).
PROPOSED_VERBS = frozenset({"export market data"})
# G-RULED: sha256[:16] of each BQ bullet; `--repin` rewrites the block, nothing else.
PINS_OPEN = 'BQ_PINS = """\n'
PINS_CLOSE = '"""  # end of the BQ pins'
BQ_PINS = """
BQ-0 a15b4e45fe009776
BQ-1 fa8a379855a42285
BQ-2 ccaa9b8b9f784603
BQ-3 f7f097c2ad2552ea
BQ-4 ad357cbcb0e3bbab
BQ-5 1499291c58a26d60
BQ-6 9c43a1092e7236cf
BQ-7 a520c09653aa6cbf
BQ-8 ad1c65ae472431fd
BQ-9 28b658b5dc2344de
"""  # end of the BQ pins
# The E20-D02 lines this pack builds on: D02 at the base, D02H at the boards PR head.
KEY_CITES = (
    L.KeyCite("D02", 97, "Hand-off to E20-D03"),
    L.KeyCite("D02", 202, "the form is E20-D03's"),
    L.KeyCite("D02", 227, "No number is clipped, ellipsised or partial"),
    L.KeyCite("D02", 310, "E20-D03 draws it"),
    L.KeyCite("D02", 527, "**E20-D03**"),
    L.KeyCite("D02H", 576, "sizes the header row"),
    L.KeyCite("D02H", 580, "`color.surface.selected`"),
)


# ---------- sources and measurers -------------------------------------------------------------
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
def contrast() -> ModuleType:
    return L.load_module(ROOT, "docs/design/_tools/contrast_check.py", "contrast_check")


@functools.cache
def primitives() -> dict[str, str]:
    raw = L.token_file(repo(), BASE, "primitives")
    return {k: str(v.get("$value", "")) for k, v in raw.items()}


@functools.cache
def theme(name: str) -> dict[str, str]:
    t = dict(L.resolve_theme(repo(), BASE, name))
    idx = THEMES.index(name)
    for tok, vals in PROPOSED.items():
        t[tok] = primitives()[vals[idx].strip("`")]
    return t


@functools.cache
def numbers() -> dict[str, float]:
    """`space.1`, the row heights and the value class's font size, from the token JSON."""
    t = theme("dark")
    val = L.token_file(repo(), BASE, "semantic-dark")[VALUE_CLASS].get("$value")
    size_ref = str(val.get("fontSize", "")) if isinstance(val, dict) else ""
    return {
        "space.1": float(t["space.1"]),
        "compact": float(t["space.row.height.compact"]),
        "comfortable": float(t["space.row.height.comfortable"]),
        "font": float(t[size_ref.strip("{}")]),
    }


def ink(name: str, palette: str, tok: str) -> str:
    """The hex a token paints in a theme under a palette ("@shipped": the shipped remap)."""
    tok, _, how = tok.partition("@")
    if palette == "cvd-safe":
        tok = (REMAP_SHIPPED if how == "shipped" else REMAP).get(tok, tok)
    return theme(name)[tok]


def rgb(hexv: str) -> tuple[int, int, int]:
    return int(hexv[1:3], 16), int(hexv[3:5], 16), int(hexv[5:7], 16)


def ratio(a: str, b: str) -> float:
    return float(contrast().contrast_ratio(rgb(a), rgb(b)))


def pair_row(pair: str, fg: str, bg: str, floor: float) -> list[str]:
    vals = [f"{ratio(ink(n, p, fg), ink(n, p, bg)):.2f}" for n in THEMES for p in PALETTES]
    cell = f"{floor:g}, reported" if bg.endswith("@shipped") else f"{floor:g}"
    return [pair, f"`{fg}`", f"`{bg.split('@')[0]}`", cell, *vals]


def grey(hexv: str) -> float:
    return float(cvd().xyz_to_lab(cvd().srgb_to_xyz(hexv))[0])


def cvd_row(name: str, palette: str) -> list[str]:
    """Delta E76 after simulation: the sign inks, each shade against the canvas (the nearer),
    and the two side shades; then the greyscale |delta L*| of the same pairs (reported)."""
    b, s = ink(name, palette, "color.buy.default"), ink(name, palette, "color.sell.default")
    bs, ss = ink(name, palette, BUY_SHADE), ink(name, palette, SELL_SHADE)
    cv, info = ink(name, palette, CANVAS), ink(name, palette, INFO_SHADE)
    out = [name, palette]
    for d in DEFICIENCIES:

        def sim(h: str, d: str = d) -> str:
            return str(cvd().simulate(h, d))

        de = cvd().delta_e76
        out += [
            f"{de(sim(b), sim(s)):.1f}",
            f"{min(de(sim(x), sim(cv)) for x in (bs, ss, info)):.1f}",
            f"{de(sim(bs), sim(ss)):.1f}",
        ]
    out += [
        f"{abs(grey(b) - grey(s)):.1f}",
        f"{min(abs(grey(x) - grey(cv)) for x in (bs, ss, info)):.1f}",
    ]
    return out


def redline_rows() -> list[list[str]]:
    n = numbers()
    out = []
    for d in DENSITIES:
        h = n[d]
        units = h / n["space.1"]
        row = [d, f"`space.row.height.{d}`", f"{h:g}", f"{units:g}"]
        row += [f"{(k + 1) * h:g} ({(k + 1) * units:g})" for _, k in ROW_SETS]
        out.append(row)
    return out


def width_rows() -> list[list[str]]:
    n = numbers()
    adv = MONO_ADVANCE * n["font"]
    out = []
    for what, s in WIDEST:
        text = math.ceil(len(s) * adv * 10) / 10
        out.append(
            [what, f"`{s}`", str(len(s)), f"{text:g}", f"{math.ceil(text + 2 * n['space.1'])}"]
        )
    return out


# ---------- spec helpers ------------------------------------------------------------------------
def rows(block: str) -> list[list[str]]:
    return L.table_rows(block)


def sec(t: L.Tree, heading: str) -> str:
    return L.section(t.text("spec"), heading)


def squash(s: str) -> str:
    """Whitespace runs as one space: prettier collapses them inside table cells."""
    return " ".join(s.split())


def cited_text(cell: str, i: int = 0) -> str:
    c = L.extract_cites(cell, CITE_RE)
    if len(c) <= i:
        return ""
    return squash(" ".join(line_of(c[i].doc, k) for k in range(c[i].lo, c[i].hi + 1)))


def copy_deck(spec: str) -> list[list[str]]:
    return rows(L.section(spec, "## 9. Copy deck"))


def ticket_body() -> str:
    tickets = json.loads(repo().show(BASE, BACKLOG_REL) or "[]")
    return next(str(x.get("body", "")) for x in tickets if x.get("key") == TICKET)


# ---------- this spec's gates ---------------------------------------------------------------------
def g_cite(t: L.Tree) -> list[str]:
    bad = L.check_cites(L.extract_cites(t.text("spec"), CITE_RE), docs(), min_count=80)
    return [f"unresolved cites: {', '.join(b.split(' (')[0] for b in bad)}"] if bad else []


def g_quote(t: L.Tree) -> list[str]:
    bad = []
    for r in copy_deck(t.text("spec")):
        if len(r) < 5:
            bad.append(f"{r[0] if r else '?'} cells")
            continue
        s = squash(L.unquote(r[2]))
        if r[4].startswith("lead verbatim"):
            s, _, rest = s.partition(". ")
            s += "."
            if not rest or rest not in cited_text(r[3], 1):
                bad.append(r[0] + " (second sentence)")
        elif not r[4].startswith("verbatim"):
            continue
        if s not in cited_text(r[3]):
            bad.append(r[0])
    return [f"not on the cited line: {', '.join(bad)}"] if bad else []


def g_version(t: L.Tree) -> list[str]:
    v, spec = sec(t, "### 13.1 Version line"), t.text("spec")
    miss = [n for n in (BASE[:9], D02_HEAD[:9], "#5903", "re-pin", BQ_LIST) if n not in v]
    if f"Base `origin/main` `{BASE[:9]}`" not in spec:
        miss.append("Inputs pinned base")
    return [f"missing: {', '.join(miss)}"] if miss else []


def g_ac(t: L.Tree) -> list[str]:
    body = ticket_body()
    names = re.findall(r"Scenario: (.+)", body)
    dod = re.findall(r"- \[ \] (.+)", body)
    first = [squash(r[0]) for r in rows(sec(t, "## Acceptance-criteria and DoD trace"))]
    miss = [n for n in names if f'AC "{n.strip()}"' not in first]
    miss += [d for d in dod if squash(f"DoD {d.strip()}") not in first]
    if len(names) != 3 or len(dod) != 5:
        miss.append(f"{len(names)} scenarios, {len(dod)} DoD items")
    return [f"not traced verbatim: {miss}"] if miss else []


def g_bq(t: L.Tree) -> list[str]:
    spec = t.text("spec")
    if RULING is None:
        head = f"## The questions BQ-0 … BQ-9 — defaults built; ruling pending (comment {BQ_LIST})"
        verdict, forbid = "**ORCH-default.**", ("RULED",)
    else:
        head = f"## The questions BQ-0 … BQ-9 — RULED (comment {RULING}, on the BQ list {BQ_LIST})"
        verdict, forbid = "**RULED", ("ORCH-default.",)
    bad = L.check_ruling(
        spec,
        heading_line=head,
        list_ref=f"comment {BQ_LIST} on #575",
        count=BQ_COUNT,
        verdict=lambda n: verdict,
        need=("Built as:",),
        forbid=forbid,
    )
    walk = sec(t, "## 12. Owner walkthrough")
    if f"comment {BQ_LIST}" not in walk:
        bad.append("the walkthrough's BQ item")
    return bad


def g_ruled(t: L.Tree) -> list[str]:
    return L.check_hash_pins(t.text("spec"), BQ_PINS) + L.check_key_cites(KEY_CITES, docs())


def g_boards(t: L.Tree) -> list[str]:
    got = rows(sec(t, "## 0. Status"))
    bad = L.board_cap(got, TICKET, t.text("spec"))
    hc = sum(1 for r in got if len(r) > 3 and r[3] == "high-contrast")
    return bad + ([] if hc == 1 else [f"{hc} high-contrast boards"])


def g_penpot(t: L.Tree) -> list[str]:
    return L.r7_findings(t.named("spec"), ("page `E20-D03`", "page id"), sec(t, "## 0. Status"))


def g_tokens(t: L.Tree) -> list[str]:
    names = L.token_names(repo(), BASE)
    bad = []
    for line in t.text("spec").split("\n"):
        for name in L.check_token_refs(line, names):
            if name in PROPOSED or (name in UNSHIPPED and "not shipped" in line):
                continue
            bad.append(name)
    got = {r[0].strip("`"): r for r in rows(sec(t, "### 2.1 The token map"))}
    for name, vals in PROPOSED.items():
        r = got.get(name, [])
        if len(r) < 6 or tuple(r[2:5]) != vals or r[5] != "PROPOSED":
            bad.append(f"{name} row differs from the tool")
        for v in vals:
            if v.strip("`") not in primitives():
                bad.append(f"{v} is not a primitive")
    return sorted(set(bad))


def g_contrast(t: L.Tree) -> list[str]:
    want = [pair_row(*p) for p in PAIRS]
    bad = [] if rows(sec(t, "### 2.2 The contrast matrix")) == want else ["2.2 differs (--fill)"]
    for w in want:
        if w[3].endswith("reported"):
            continue
        low = min(float(v) for v in w[4:])
        if low < float(w[3]):
            bad.append(f"{w[0]} at {low} < {w[3]}")
    return bad


def g_cvd(t: L.Tree) -> list[str]:
    want = [cvd_row(n, p) for n in THEMES for p in PALETTES]
    bad = [] if rows(sec(t, "### 2.3 Colour vision")) == want else ["2.3 differs (--fill)"]
    for w in want:
        sign = min(float(w[i]) for i in (2, 5, 8))
        if sign < 5.0:
            bad.append(f"{w[0]} {w[1]}: the sign inks at {sign} < 5.0")
    return bad


def g_redline(t: L.Tree) -> list[str]:
    bad = [] if rows(sec(t, "### 6.1 Rows and the strip")) == redline_rows() else ["6.1 differs"]
    for r in redline_rows():
        if not float(r[3]).is_integer():
            bad.append(f"{r[0]} row is not a whole number of space.1")
    if rows(sec(t, "### 4.2 Abbreviation")) != width_rows():
        bad.append("4.2's widths differ from the measurement (--fill)")
    return bad


def g_glyph(t: L.Tree) -> list[str]:
    got = rows(sec(t, "### 3.1 The encoding"))
    bad = [] if [r[0] for r in got] == list(SIG_STATES) else [f"states {[r[0] for r in got]}"]
    sigs = [tuple(squash(c) for c in r[1:5]) for r in got if len(r) >= 6]
    if len(set(sigs)) != len(sigs) or len(sigs) != len(got):
        bad.append("two states share a non-colour signature")
    if BREACH in SIGN_GLYPHS | {PRESENCE} or ord(BREACH) not in GEOMETRIC:
        bad.append("the breach glyph collides or leaves the sign glyphs' block")
    for r in got:
        if len(r) < 6:
            continue
        breached = "breached" in r[0]
        if breached != (r[1] == BREACH):
            bad.append(f"{r[0]}: breach glyph {r[1]!r}")
        if r[2] not in SIGN_GLYPHS | {PRESENCE, "—"}:
            bad.append(f"{r[0]}: sign slot {r[2]!r}")
    return bad


def g_format(t: L.Tree) -> list[str]:
    s4 = sec(t, "## 4. Numeric typography")
    bad = [] if "…" not in s4 and "..." not in s4 else ["an ellipsis in a format"]
    for need in ("never truncated", "U+2212", "tabular", "column-header suffix", "never per cell"):
        if need not in s4:
            bad.append(need)
    for r in rows(sec(t, "### 4.1 The formats")):
        if len(r) < 5 or re.search(r"\d\s?(?:BTC|USDT|%)`", r[4]):
            bad.append(f"{r[0] if r else '?'}: a unit in the cell")
    return bad


def g_t2(t: L.Tree) -> list[str]:
    spec = t.text("spec")
    r4 = next((ln for ln in spec.split("\n") if ln.startswith("- **R-4 ")), "")
    bad = L.t2_markers(r4) + L.no_disabled_tokens(spec)
    d09 = repo().show(BASE, KEYED["D09E09"].rel) or ""
    bad += L.t2_reason_keys(spec, L.d09_keys(d09))
    verbs = L.d09_verbs(d09)
    for line in spec.split("\n"):
        for v in re.findall(r'verb "([^"]+)"', line):
            if v not in verbs.values() and not (v in PROPOSED_VERBS and "PROPOSED" in line):
                bad.append(f"verb {v!r}")
    for r in rows(sec(t, "### 1.4 The gated controls")):
        if len(r) < 4 or r[1].split(":")[0] not in ("2a", "sentence form"):
            bad.append(f"{r[0] if r else '?'} rendering")
        elif not re.search(r"W-\d+", r[2]):
            bad.append(f"{r[0]} reason")
    return bad


def g_env(t: L.Tree) -> list[str]:
    r1 = next((ln for ln in t.text("spec").split("\n") if ln.startswith("- **R-1 ")), "")
    need = ("C-2.11", "hard constraint", "market data only", "no environment")
    return [n for n in need if n not in r1]


def g_arows(t: L.Tree) -> list[str]:
    got = rows(sec(t, "## C. The CMP-225 entry"))
    bad = [] if len(got) == AROW_COUNT else [f"{len(got)} A-rows"]
    for r in got:
        if len(r) < 4 or not r[0].startswith("A-"):
            bad.append(f"{r[0] if r else '?'} cells")
            continue
        old = squash(L.unquote(r[2]))
        if old != "(new line)" and old not in cited_text(r[1]):
            bad.append(f"{r[0]} Old is not on {r[1]}")
        if not r[3].strip() or r[3] == r[2]:
            bad.append(f"{r[0]} New")
    return bad


def g_noclose(t: L.Tree) -> list[str]:
    return L.closing_keywords(t.named("spec"))


def g_public(t: L.Tree) -> list[str]:
    named = t.named("spec")
    return L.scan_public(named) + L.comment_findings(named) + L.whitespace_hygiene(named)


def g_untouched(t: L.Tree) -> list[str]:
    return L.untouched(t.changed, OWN, (), {}, t.numstat)


def g_mutlist(t: L.Tree) -> list[str]:
    return L.check_mutlist(t.text("spec"), "### 13.3", MUTATIONS)


# fmt: off
GATES = tuple(L.Gate("G-" + f.__name__[2:].upper(), f) for f in (
    g_cite, g_quote, g_version, g_ac, g_bq, g_ruled, g_boards, g_penpot, g_tokens, g_contrast,
    g_cvd, g_redline, g_glyph, g_format, g_t2, g_env, g_arows, g_noclose, g_public, g_untouched,
    g_mutlist,
))
# fmt: on

_M = L.Mutation
_V = "### 13.1 Version line\n"
# fmt: off
MUTATIONS: tuple[L.Mutation, ...] = (
    _M("M-1", "G-CITE", "a cite past the end of `15`", "spec", "`15`:2938", "`15`:99999"),
    _M("M-2", "G-QUOTE", "W-8 reworded off its line", "spec",
       '"Order flow from <ts>; earlier bars from exchange klines"',
       '"Order flow since <ts>; earlier bars from exchange klines"'),
    _M("M-3", "G-QUOTE", "the ticket's sentence reworded", "spec",
       '"Threshold must be between 0 and 100 %.', '"Threshold must lie between 0 and 100 %.'),
    _M("M-4", "G-VERSION", "the version line drops the boards PR", "spec",
       "E20-D02's boards PR #5903", "E20-D02's boards PR"),
    _M("M-5", "G-AC", "a scenario name reworded", "spec",
       'AC "Threshold encoding survives desaturation"', 'AC "Threshold encoding survives grey"'),
    _M("M-6", "G-BQ", "the heading claims a ruling", "spec",
       "— defaults built; ruling pending (comment", "— RULED; ruling pending (comment"),
    _M("M-7", "G-RULED", "a BQ bullet edited without a re-pin", "spec",
       "ten boards, dark-first", "nine boards, dark-first"),
    _M("M-8", "G-BOARDS", "an eleventh board", "spec",
       r"(\| 10 +\| `E20-D03 / 10 [^\n]*\n)",
       r"\1| 11  | `E20-D03 / 11 extra` | x | dark | PENDING |\n", regex=True),
    _M("M-9", "G-BOARDS", "a board marked drawn", "spec",
       r"(`E20-D03 / 10 [^\n]*\| )PENDING", r"\1DRAWN  ", regex=True),
    _M("M-10", "G-PENPOT", "a Penpot file id", "spec",
       "page `E20-D03`, cited", "page `E20-D03` (" + "file" + "-id=0), cited"),
    _M("M-11", "G-TOKENS", "an unshipped token bound", "spec",
       "rows at `space.row.height.compact`", "rows at `space.row.compact`"),
    _M("M-12", "G-TOKENS", "a PROPOSED value drifts from the tool", "spec",
       r"(`color\.cvd\.buy\.subtle` *\|[^|]*\| )`palette\.blue\.900`", r"\g<1>`palette.blue.700`",
       regex=True),
    _M("M-13", "G-CONTRAST", "a written ratio drifts", "spec",
       r"(\| cell value, neutral +\|[^\n]*?\| 4\.5 +\| )(\d+\.\d\d)", r"\g<1>99.99", regex=True),
    _M("M-14", "G-CVD", "a written distance drifts", "spec",
       r"(\| light +\| standard +\| )(\d+\.\d)", r"\g<1>0.1", regex=True),
    _M("M-15", "G-REDLINE", "a row height off the space.1 grid", "spec",
       r"(\| compact +\| `space\.row\.height\.compact` +\| )24", r"\g<1>26", regex=True),
    _M("M-16", "G-REDLINE", "the widest value narrowed", "spec",
       r"(\| full +\| `9,999,999,999` +\| 13 +\| )(\d+(?:\.\d)?)", r"\g<1>12", regex=True),
    _M("M-17", "G-GLYPH", "two states share a signature", "spec",
       r"\| collapsed, breached, unsigned \| ■ +\| ·", "| collapsed, breached, unsigned | ■ | ▲",
       regex=True),
    _M("M-18", "G-GLYPH", "the breach glyph dropped from a breached state", "spec",
       r"\| breached, unsigned( +)\| ■", r"| breached, unsigned\1| —", regex=True),
    _M("M-19", "G-FORMAT", "an ellipsis returns", "spec",
       "No value is ever truncated", "No value is ever truncated (or 1,23…)"),
    _M("M-20", "G-FORMAT", "a unit printed in the cell", "spec",
       r"(\| Total Notional +\|[^\n]*?)`9,999,999,999`", r"\1`9,999,999,999 USDT`", regex=True),
    _M("M-21", "G-T2", "R-4 loses the opacity ban", "spec",
       "never `color.text.disabled`, never `opacity.disabled`", "never `color.text.disabled`"),
    _M("M-22", "G-T2", "a reason from a key E09-D09 lacks", "spec",
       "`rbac.permission` with", "`rbac.export_denied` with"),
    _M("M-23", "G-T2", "an unrouted verb", "spec",
       'verb "export market data" (PROPOSED', 'verb "export data" (PROPOSED'),
    _M("M-24", "G-ENV", "C-2.11 no longer hard", "spec",
       "C-2.11 is a hard constraint", "C-2.11 is a preference"),
    _M("M-25", "G-AROWS", "an A-row's Old quote drifts", "spec",
       '"`font.mono`, `color.status.*`, `space.1`."', '"`font.mono`, `space.1`."'),
    _M("M-26", "G-NOCLOSE", "a closing keyword", "spec", _V, _V + "\n" + "Clo" + "ses #575.\n"),
    _M("M-27", "G-PUBLIC", "a URL", "spec",
       "Penpot: the file", "Penpot (" + "http" + "s://example.org): the file"),
    _M("M-28", "G-UNTOUCHED", "an owner document edited", "@changed",
       "", "docs/plan/15-component-catalogue.md"),
    _M("M-29", "G-MUTLIST", "the list drifts", "spec", "| M-1  | G-CITE ", "| M-1  | G-AC   "),
    _M("M-30", "G-QUOTE", "D02's second sentence reworded", "spec",
       '{row}: enter a value from 0 to 100 %."', '{row}: enter a value of 0 to 100 %."'),
)
# fmt: on


# ---------- modes ---------------------------------------------------------------------------------
def read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def read_tree() -> L.Tree:
    base = repo().diff_base(BASE)
    return L.Tree(files={"spec": read(SPEC_REL)}, changed=repo().changed_paths(base))


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
    cols = [f"{n} {q}" for n in ("dark", "light", "HC") for q in ("std", "cvd")]
    t22 = table(["Pair", "Ink", "Against", "Floor", *cols], [pair_row(*x) for x in PAIRS])
    h23 = ["Theme", "Palette"] + [
        f"{d[:4].title()} {k}" for d in DEFICIENCIES for k in ("signs", "shade", "sides")
    ]
    t23 = table(
        [*h23, "Grey signs", "Grey shade"], [cvd_row(n, q) for n in THEMES for q in PALETTES]
    )
    h61 = [
        "Density",
        "Token",
        "px",
        "\N{MULTIPLICATION SIGN} `space.1`",
        "Default + header",
        "AllRows + header",
    ]
    t42 = table(["Total Notional", "String", "Characters", "Text px", "Cell px"], width_rows())
    spec = replace_table(spec, "### 2.2 The contrast matrix", t22)
    spec = replace_table(spec, "### 2.3 Colour vision", t23)
    spec = replace_table(spec, "### 6.1 Rows and the strip", table(h61, redline_rows()))
    spec = replace_table(spec, "### 4.2 Abbreviation", t42)
    spec = replace_table(spec, "### 13.3", L.mutation_table(MUTATIONS))
    p.write_text(spec, encoding="utf-8", newline="\n")
    print("sections 2.2, 2.3, 4.2, 6.1 and 13.3 written")
    return 0


def main(argv: list[str]) -> int:
    modes = {"check": check, "self-test": self_test, "repin": repin, "fill": fill}
    return L.cli(argv, modes, __doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
