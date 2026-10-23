"""E14-D05 audit: Fibonacci levels, anchored VWAP bands, the (estimated) badge, the measure ribbon.

Offline, stdlib plus the repo's own token / contrast / CVD / keymap helpers (imported, never
re-done). Every number docs/design/E14/E14-D05.md and its boards quote is computed here and printed
with its source label: (1) the registries parsed as text (22 DrawingTool / DrawingGeometry /
DrawingStyle, 24 section 9's band formula, 26 B3 and section 3.7, the shipped keymap) and the
file:line anchors the spec pins; (2) the level-ladder geometry; (3) the label-collision walk run on
five fixed spans, the narrow-gutter, the inverted and the off-screen case, with the P0 / P1 survival
and determinism checks; (4) the glyph budget; (5) the anchored VWAP specimen and the band
composites; (6) the ribbon arithmetic; (7) the density study; (8) the measured matrix in three
themes; (9) the CVD rows and the greys; (10) the hotkey lint; (11) the token bindings; (12) the
string gates; (13) the counts. `--json` feeds the local board check.

Usage: python3 -I docs/design/_tools/e14_d05_levels_audit.py [--json] [--check] [--draft <file>]
Exit 1 on a gated FAIL (`--check` is the same gate, spelled out). No network anywhere.
"""

from __future__ import annotations

import importlib.util
import io
import json
import math
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
TOKENS, PLAN, DESIGN = ROOT / "packages/ui/tokens", ROOT / "docs/plan", ROOT / "docs/design"
E14 = DESIGN / "E14"
SPEC, HANDOFF = E14 / "E14-D05.md", E14 / "E14-D05-handoff.md"
D02, D03, E13 = E14 / "E14-D02.md", E14 / "E14-D03.md", DESIGN / "E13/E13-D03.md"
MEMO = DESIGN / "research/e14-drawing-mental-models.md"
D = Decimal
FAILS: list[str] = []
THEMES = ("dark", "light", "high-contrast")
BAR: dict[str, float] = {"text": 4.5, "non-text": 3.0, "data-ink": 3.0, "hc-text": 7.0}
MID = "·"  # the middle dot of every label and chip
SIGMA = "\u03c3"  # the sigma of the band names
ARROW = "→"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(TOKENS / "tests"))
verify = _load(TOKENS / "tests/verify_tokens.py", "verify_tokens")
contrast = _load(DESIGN / "_tools/contrast_check.py", "contrast_check")
cvd = _load(ROOT / "docs/research/_tools/cvd_simulate.py", "cvd_simulate")
keymap_lint = _load(ROOT / "scripts/keymap_lint.py", "keymap_lint")


def theme_tokens(name: str) -> dict[str, object]:
    allt = dict(verify.load(verify.PRIMITIVES))
    allt.update(verify.merged_set(verify.THEMES[name]))
    return {k: verify.resolve(v["$value"], allt) for k, v in allt.items()}


ALL = {n: theme_tokens(n) for n in THEMES}
NAMES = set(ALL["dark"])
HC_FILE = set(verify.load("semantic-hc.tokens.json"))


def col(theme: str, short: str) -> str:
    return str(ALL[theme]["color." + short])


def prim(name: str) -> str:
    return str(ALL["dark"][name])


def rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def mix(fg: str, alpha: float, bg: str) -> str:  # 8-bit sRGB alpha composite, as the canvas does
    f, b = rgb(fg), rgb(bg)
    out = [round(alpha * f[i] + (1 - alpha) * b[i]) for i in range(3)]
    return f"#{out[0]:02X}{out[1]:02X}{out[2]:02X}"


def ratio(fg: str, bg: str) -> float:
    return float(contrast.contrast_ratio(rgb(fg), rgb(bg)))


def grey(h: str) -> str:  # cvd_sim.py's to_greyscale: Rec. 601 luma, floored, as a hex grey
    r, g, b = rgb(h)
    return "#" + f"{max(0, min(255, int(0.299 * r + 0.587 * g + 0.114 * b))):02X}" * 3


def paint(expr: str, theme: str, under: str) -> str:  # "tok" | "tok@a" | "tok@3xa", over `under`
    name, _, alpha = expr.partition("@")
    hexv = col(theme, name)
    if not alpha:
        return hexv
    stack, _, a = alpha.rpartition("x")
    eff = 1 - (1 - float(a)) ** int(stack) if stack else float(a)
    return mix(hexv, eff, under)


def read(p: Path) -> str:
    if not p.exists():
        FAILS.append(f"missing file {p.name}")
        return ""
    return p.read_text(encoding="utf-8")


def q1(x: float) -> Decimal:  # quantise a kernel float to the tick on emit (24 section 9)
    return D(str(x)).quantize(TICK, rounding=ROUND_HALF_UP)


# ---- 1. the scenario (one literal block; spec section 1.4) ---------------------------------------
SC: dict[str, float] = {
    "pane_w": 1280,
    "pane_h": 800,
    "rail": 24,
    "toolbar": 24,
    "status": 24,
    "timestrip": 24,
    "gutter": 56,
    "bar_px": 12,
    "cell_px": 12,
    "rows": 25,
    "anchor1_frac": 0.30,
    "anchor2_frac": 0.55,
    "fib_span_px": 400,
    "tick": 0.1,
    "label_pt": 11,
    "label_lh": 1.2,
    "halo": 1,
    "gap": 2,
    "inset": 8,
    "target": 24,
    "narrow_room": 64,
    "narrow_left": 40,
    "side_room": 60,
    "inside_room": 30,
    "left_room": 300,
    "interval_min": 1,
    "gap_bars": 5,
    "budget_fraction": 0.25,
    "fill_default": 0.05,
    "fill_ceiling": 0.20,
}
TIMES = {"anchor1": "13:40", "anchor2": "14:05", "vwap": "12:00", "ticks": "12:40", "gap": "13:50"}
PRICES = {"anchor1": D("63900.0"), "anchor2": D("64420.0"), "vwap": D("64010.0")}
SPANS = (400, 120, 60, 30, 12)
DEFAULT_LEVELS = ("0", "0.236", "0.382", "0.5", "0.618", "0.786", "1")  # 11:1230
CUSTOM_LEVEL = "0.886"  # 11:1232
TIMEZONE_SET = (0, 1, 2, 3, 5, 8, 13, 21)  # Q10 default: the Fibonacci integers, eight levels
PLOT_W = SC["pane_w"] - SC["rail"] - SC["gutter"]
PLOT_H = SC["pane_h"] - SC["toolbar"] - SC["status"] - SC["timestrip"]
BARS_VISIBLE = int(PLOT_W // SC["bar_px"])
CELLS = BARS_VISIBLE * int(SC["rows"])
X1, X2 = PLOT_W * SC["anchor1_frac"], PLOT_W * SC["anchor2_frac"]
RIGHT_ROOM = PLOT_W - X2 - SC["target"]
TICK = D(str(SC["tick"]))
PX_PER_PRICE = SC["fib_span_px"] / float(PRICES["anchor2"] - PRICES["anchor1"])
LINE_BOX = math.ceil(SC["label_pt"] * SC["label_lh"])
H = LINE_BOX + 2 * SC["halo"]  # the label box: the caption line box plus the 1 px pane halo
G = SC["gap"]

# ---- the registries parsed as text (22 / 24 / 26) -----------------------------------------------
Y = (PLAN / "22-api-openapi.yaml").read_text(encoding="utf-8")
S24 = (PLAN / "24-internal-schemas.md").read_text(encoding="utf-8")
S26 = (PLAN / "26-chart-engine-design.md").read_text(encoding="utf-8")
KEYMAP = json.loads((ROOT / "apps/web/src/keymap/keymap.json").read_text(encoding="utf-8"))
TB = Y[Y.index("    DrawingTool:") : Y.index("    DrawingPoint:")]
GEOM = Y[Y.index("    DrawingGeometry:") : Y.index("    DrawingInput:")]
LEV = GEOM[GEOM.index("        levels:") : GEOM.index("        bands:")]
BND = GEOM[GEOM.index("        bands:") : GEOM.index("        text:")]


def counts_of(label: str) -> list[str]:
    m = re.search(rf"- {re.escape(label)}:((?:[^\n]*\n)(?:\s+`[^\n]*\n)*)", TB)
    return re.findall(r"`(\w+)`", m.group(1)) if m else []


REG_LISTS: dict[str, list[str]] = {
    "DrawingTool enum": re.findall(r"^        - (\w+)$", TB, re.MULTILINE),
    "exactly 1": counts_of("exactly 1"),
    "exactly 2": counts_of("exactly 2"),
    "exactly 3": counts_of("exactly 3"),
}
REG_RULES: dict[str, bool] = {
    "levels rule": "`levels` only for `fib_retracement`, `fib_extension`, `fib_timezone`" in TB,
    "bands rule": "`bands` only for\n        `anchored_vwap`" in TB,
    "extend rule": "`extend_left` / `extend_right` are allowed on every tool" in TB,
}
MINMAX = r"minItems: (\d+)\n\s+maxItems: (\d+)"
BOUNDS: dict[str, list[tuple[str, str]] | list[str]] = {
    "levels": re.findall(MINMAX, LEV),
    "levels range": re.findall(r"minimum: (-?\d+)\n\s+maximum: (\d+)", LEV),
    "bands": re.findall(MINMAX, BND),
    "bands enum": re.findall(r"items: \{ type: integer, enum: \[([^\]]+)\] \}", BND),
    "width": re.findall(r"width: \{ type: integer, minimum: (\d+), maximum: (\d+) \}", GEOM),
    "dash": re.findall(r"dash: \{ type: string, enum: \[([^\]]+)\] \}", GEOM),
    "font_size": re.findall(
        r"font_size: \{ type: integer, minimum: (\d+), maximum: (\d+) \}", GEOM
    ),
    "fill_opacity": re.findall(
        r"fill_opacity:\n\s+type: number\n\s+minimum: (\d)\n\s+maximum: (\d)", GEOM
    ),
}
BAND_FORMULA = re.search(r"\| SD bands\s+\| ([^|]+)\|", S24)
B3 = re.search(
    r"\| B3 +\| Footprint, ([\d,]+) visible cells with text +\| ≤ (\d+) ms +\| ([^|]+)\|", S26
)
GLYPH_CASE = re.search(r"Measured budget: ([\d,]+) glyphs \([^)]*≈ ([\d,]+) glyphs", S26)
DRAW_CALLS = re.search(r"drawing labels a third\. Target ≤ (\d+) text draw calls", S26)
EXPECT_TOOLS = {"fib_retracement": 2, "fib_extension": 3, "fib_timezone": 2, "anchored_vwap": 1}
EXPECT_TOOLS |= {"measure": 2, "pitchfork": 3}
EXPECT_BOUNDS: dict[str, list[tuple[str, str]] | list[str]] = {
    "levels": [("1", "24")],
    "levels range": [("-1000", "1000")],
    "bands": [("1", "3")],
    "bands enum": ["1, 2, 3"],
    "width": [("1", "8")],
    "dash": ["solid, dashed, dotted"],
    "font_size": [("8", "48")],
    "fill_opacity": [("0", "1")],
}


def check_registries() -> None:
    if len(REG_LISTS["DrawingTool enum"]) != 25:
        FAILS.append("DrawingTool enum: not 25 values parsed")
    for tool, n in EXPECT_TOOLS.items():
        if tool not in REG_LISTS[f"exactly {n}"]:
            FAILS.append(f"22: {tool} is not under 'exactly {n}'")
    for k, ok in REG_RULES.items():
        if not ok:
            FAILS.append(f"22 key rule not found as quoted: {k}")
    for k, v in EXPECT_BOUNDS.items():
        if BOUNDS[k] != v:
            FAILS.append(f"22 bound {k}: parsed {BOUNDS[k]!r}, expected {v!r}")
    if not BAND_FORMULA or f"vwap ± k{SIGMA}" not in BAND_FORMULA.group(1):
        FAILS.append("24 section 9: the SD-band formula row was not parsed")
    if not B3 or int(B3.group(1).replace(",", "")) != CELLS:
        FAILS.append(f"26 B3: 2,500 cells expected; the scenario grid has {CELLS}")
    if not GLYPH_CASE or not DRAW_CALLS:
        FAILS.append("26 section 3.7: the glyph case or the draw-call target was not parsed")


# ---- 2. the level ladder: prices, labels, widths; 3. the collision walk --
LEVELS = [D(x) for x in (*DEFAULT_LEVELS, CUSTOM_LEVEL)]


def level_price(lvl: Decimal) -> Decimal:
    p0, p1 = PRICES["anchor1"], PRICES["anchor2"]
    return (p0 + lvl * (p1 - p0)).quantize(TICK, rounding=ROUND_HALF_UP)


def pct(lvl: Decimal) -> str:
    return f"{(lvl * 100).normalize():f}"


def fmt_price(p: Decimal) -> str:
    return f"{p:,.1f}"


def name_price(p: Decimal) -> str:  # D07's rule for names: a whole tick prints without decimals
    whole, _, frac = f"{p:,.1f}".partition(".")
    frac = frac.rstrip("0")
    return whole + (f".{frac}" if frac else "")


def full_label(lvl: Decimal) -> str:
    return f"{pct(lvl)} % {MID} {fmt_price(level_price(lvl))}"


def short_label(lvl: Decimal) -> str:
    return f"{pct(lvl)} %"


def width_px(label: str, pt: float = SC["label_pt"]) -> int:  # the stated estimate: 0.6 em per
    em = sum(0.3 if ch in f" .,{MID}" else 0.6 for ch in label)  # glyph, 0.3 em for the thin ones
    return math.ceil(em * pt)


def glyphs(label: str) -> int:
    return sum(ch != " " for ch in label)


def cls(lvl: Decimal) -> int:
    if lvl in (D(0), D(1)):
        return 0
    if lvl == D("0.5"):
        return 1
    if lvl in (D("0.382"), D("0.618")):
        return 2
    if lvl in (D("0.236"), D("0.786")):
        return 3
    return 4


def priority(levels: list[Decimal]) -> list[Decimal]:  # P0 {0, 1} > P1 {0.5} > P2 > P3 > P4,
    return sorted(levels, key=lambda lv: (cls(lv), -abs(lv - D("0.5")), lv))  # far from 0.5 first


@dataclass
class Placed:
    level: str
    column: int
    top: float


@dataclass
class Walk:
    abbreviated: bool
    form: str
    drawn: int
    dropped: list[str]
    rows: list[Placed]
    columns: int
    side: str = "right"

    def kept(self) -> set[str]:
        return {r.level for r in self.rows}


@dataclass
class Case(Walk):
    span: int = 0
    cap: int = 0
    inverted_rows: list[Placed] | None = None


Cols = list[list[tuple[float, float]]]  # the occupied intervals per column (column 1 first)
WIDEST_FULL = max(width_px(full_label(lv)) for lv in LEVELS)
WIDEST_SHORT = max(width_px(short_label(lv)) for lv in LEVELS)


def side_of(room_right: float, room_left: float, ladder_w: float) -> tuple[str, bool]:
    """Spec section 2.4: right -> left in the full form; else the wider side in the short form;
    else inside (above the line, inside the ladder's own width). Returns (side, abbreviated)."""
    need_full, need_short = WIDEST_FULL + SC["inset"], WIDEST_SHORT + SC["inset"]
    if room_right >= need_full:
        return "right", False
    if room_left >= need_full:
        return "left", False
    wider, wider_room = ("right", room_right) if room_right >= room_left else ("left", room_left)
    if wider_room >= need_short:
        return wider, True
    return "inside", ladder_w < need_full


def label_x(side: str, column: int, w: float, x_start: float, x_end: float) -> float:
    """The label box's left edge in pane px; column 2+ is INWARD (toward the ladder) on every side:
    right: left-aligned 8 px right of the ladder's end; left: right-aligned 8 px left of its start;
    inside: right-aligned 8 px inside the ladder's end. Each further column steps w_max + g inward.
    """
    step = (column - 1) * (WIDEST_FULL + G)
    if side == "right":
        return x_end + SC["inset"] - step
    if side == "left":
        return x_start - SC["inset"] - w + step
    return x_end - SC["inset"] - w - step


def _place(
    levels: list[Decimal],
    y_of: Callable[[Decimal], float],
    cols: Cols,
    clamp: tuple[float, float] | None,
    classes: set[int],
    inside: bool,
    placed: dict[Decimal, tuple[int, float]],
    dropped: list[Decimal],
) -> None:
    """The priority walk over a shared column list: P0 (outward when they meet, flipped inward
    when the pane clamps them) and P1 take the first free column and never drop; P2-P4 take
    column 1 or drop. Boxes are centred on the line (inside: above it) and clamped to the plot's
    inner margin. `cols` may be shared by several ladders (pane-level, spec section 3 step 9)."""

    def free(c: int, top: float) -> bool:
        while len(cols) <= c:
            cols.append([])
        return all(top >= b + G or top + H <= t - G for t, b in cols[c])

    def clamp_top(top: float) -> tuple[float, bool]:
        if clamp is None:
            return top, False
        lo, hi = clamp[0] + SC["inset"], clamp[1] - SC["inset"] - H
        c = min(max(top, lo), hi)
        return c, c != top

    def take(lv: Decimal, top: float, never_drop: bool) -> bool:
        c = 0
        while not free(c, top):
            if not never_drop:
                return False
            c += 1  # P0 / P1: the next column inward
        cols[c].append((top, top + H))
        placed[lv] = (c + 1, top)
        return True

    def box_top(lv: Decimal) -> float:
        return y_of(lv) - (H if inside else H / 2)

    order = priority(levels)
    if 0 in classes:
        p0 = [lv for lv in order if cls(lv) == 0]
        tops = {lv: box_top(lv) for lv in p0}
        if len(p0) == 2:
            upper, lower = sorted(p0, key=y_of)
            if tops[lower] < tops[upper] + H + G:  # the boxes collide: both move outward
                tops[upper], tops[lower] = y_of(upper) - H, y_of(lower)
            for lv, inward in ((upper, y_of(upper)), (lower, y_of(lower) - H)):
                t, moved = clamp_top(tops[lv])
                tops[lv] = inward if moved else t  # a clamped outward box flips inward
        for lv in p0:
            take(lv, clamp_top(tops[lv])[0], True)
    for lv in order:
        k = cls(lv)
        if k == 0 or k not in classes:
            continue
        if not take(lv, clamp_top(box_top(lv))[0], k == 1):
            dropped.append(lv)


def collide(
    levels: list[Decimal],
    y_of: Callable[[Decimal], float],
    room: float,
    room_left: float = 0.0,
    ladder_w: float = X2 - X1,
    clamp: tuple[float, float] | None = None,
) -> Walk:
    """Q9's walk for one ladder: the side and the form (spec section 2.4 / section 3 step 1), then
    the priority walk; P0 outward, P1 to the next inward column; the boxes clamped to the plot."""
    side, abbrev = side_of(room, room_left, ladder_w)
    cols: Cols = [[]]
    placed: dict[Decimal, tuple[int, float]] = {}
    dropped: list[Decimal] = []
    _place(levels, y_of, cols, clamp, {0, 1, 2, 3, 4}, side == "inside", placed, dropped)
    rows = [Placed(str(lv), placed[lv][0], round(placed[lv][1], 1)) for lv in sorted(placed)]
    columns = sum(1 for c in cols if c)
    form = "short" if abbrev else "full"
    return Walk(abbrev, form, len(placed), [str(lv) for lv in sorted(dropped)], rows, columns, side)


@dataclass
class Ladder:  # one ladder of a pane-level walk (spec section 3 step 9): pane-px geometry
    name: str
    levels: list[Decimal]
    top_px: float
    span_px: float
    selected: bool
    z_index: int


def collide_many(ladders: list[Ladder], room: float) -> dict[str, Walk]:
    """Several ladders sharing one gutter: one shared interval list per column; the selected
    ladder first, then descending z-order; pass A places every ladder's P0 / P1, pass B the rest."""
    order = sorted(ladders, key=lambda ld: (not ld.selected, -ld.z_index))
    cols: Cols = [[]]
    placed: dict[str, dict[Decimal, tuple[int, float]]] = {ld.name: {} for ld in ladders}
    dropped: dict[str, list[Decimal]] = {ld.name: [] for ld in ladders}
    side, abbrev = side_of(room, 0.0, X2 - X1)
    for classes in ({0, 1}, {2, 3, 4}):
        for ld in order:

            def y_of(lv: Decimal, ld: Ladder = ld) -> float:
                return ld.top_px + ld.span_px * float(1 - lv)

            _place(ld.levels, y_of, cols, None, classes, False, placed[ld.name], dropped[ld.name])
    out: dict[str, Walk] = {}
    for ld in ladders:
        pl = placed[ld.name]
        rows = [Placed(str(lv), pl[lv][0], round(pl[lv][1], 1)) for lv in sorted(pl)]
        out[ld.name] = Walk(
            abbrev,
            "short" if abbrev else "full",
            len(pl),
            [str(lv) for lv in sorted(dropped[ld.name])],
            rows,
            sum(1 for c in cols if c),
            side,
        )
    return out


def cap(span: float) -> int:  # the labelled-level cap of one column between the anchors
    return math.floor((span + G) / (H + G))


def y_normal(span: float) -> Callable[[Decimal], float]:  # low -> high: 100 % at the top
    return lambda lv: span * float(1 - lv)


def y_inverted(span: float) -> Callable[[Decimal], float]:  # high -> low: 0 at the first anchor
    return lambda lv: span * float(lv)


def lcg_shuffle(items: list[Decimal], seed: int = 7) -> list[Decimal]:  # deterministic, no random
    out, x = list(items), seed
    for i in range(len(out) - 1, 0, -1):
        x = (1103515245 * x + 12345) % 2147483648
        j = x % (i + 1)
        out[i], out[j] = out[j], out[i]
    return out


def cases() -> list[Case]:
    out: list[Case] = []
    for span in SPANS:
        res = collide(LEVELS, y_normal(span), RIGHT_ROOM)
        inv = collide(LEVELS, y_inverted(span), RIGHT_ROOM)
        shuffled = collide(lcg_shuffle(LEVELS), y_normal(span), RIGHT_ROOM)
        for must in ("0", "0.5", "1"):
            if must not in res.kept():
                FAILS.append(f"case {span} px: level {must} dropped")
        if shuffled != res:
            FAILS.append(f"case {span} px: the walk is not deterministic under a shuffled input")
        if inv.kept() != res.kept():
            FAILS.append(f"case {span} px: the inverted drag keeps a different label set")
        out.append(
            Case(
                res.abbreviated,
                res.form,
                res.drawn,
                res.dropped,
                res.rows,
                res.columns,
                span=span,
                cap=cap(span),
                inverted_rows=inv.rows,
            )
        )
    return out


CASES = cases()
NARROW = collide(LEVELS, y_normal(120), SC["narrow_room"], SC["narrow_left"])  # both sides narrow
if not NARROW.abbreviated or NARROW.side != "right":
    FAILS.append("the narrow-gutter case did not abbreviate on the right")
# the side cases (spec section 3 step 1; the lens round 1 F-4): the left side, the inside side
LEFT = collide(LEVELS, y_normal(120), SC["side_room"], SC["left_room"])
INSIDE = collide(LEVELS, y_normal(120), SC["inside_room"], SC["narrow_left"])
if LEFT.side != "left" or LEFT.form != "full":
    FAILS.append("the left-side case did not take the left side in the full form")
if INSIDE.side != "inside" or INSIDE.form != "full":
    FAILS.append("the inside case did not take the inside side in the full form")
# the pane-edge clamp (step 8): the ladder's top anchor at the plot's top edge, a 12 px span
EDGE = collide(LEVELS, y_normal(12), RIGHT_ROOM, clamp=(0.0, PLOT_H))
# two ladders sharing one gutter (step 9): the selected scenario ladder and a second one
LADDER_B = (D("63980.0"), D("64300.0"))  # the second ladder's anchors (prices)
TWO = collide_many(
    [
        Ladder("A (selected)", LEVELS, 0.0, SC["fib_span_px"], True, 1),
        Ladder(
            "B",
            LEVELS,
            round(float(PRICES["anchor2"] - LADDER_B[1]) * PX_PER_PRICE, 1),
            round(float(LADDER_B[1] - LADDER_B[0]) * PX_PER_PRICE, 1),
            False,
            2,
        ),
    ],
    RIGHT_ROOM,
)
for _nm, _w in (("left", LEFT), ("inside", INSIDE), ("edge", EDGE), *TWO.items()):
    for must in ("0", "0.5", "1"):
        if must not in _w.kept():
            FAILS.append(f"case {_nm}: level {must} dropped")
OFFSCREEN_SHIFT = 700.0  # the second anchor pushed past the price axis (board 03)
CLAMP_X = PLOT_W - SC["inset"] - WIDEST_FULL
COL_X = {  # the label columns' left edges in pane px for the scenario ladder (spec section 2.4)
    "right": [label_x("right", c, WIDEST_FULL, X1, X2) for c in (1, 2)],
    "left": [label_x("left", c, WIDEST_FULL, X1, X2) for c in (1, 2)],
    "inside": [label_x("inside", c, WIDEST_FULL, X1, X2) for c in (1, 2)],
}


# ---- 4b. the time zones: the x-axis walk on the Fibonacci integers (Q10) --
TZ_CLASS = {0: 0, 1: 0, 2: 1, 3: 2, 5: 2, 8: 3, 13: 3, 21: 4}


@dataclass
class TzCase:
    gap_bars: int
    spacing_px: float
    visible: list[int]
    drawn: list[int]
    dropped: list[int]
    label_w: int


def tz_walk(gap_bars: int) -> TzCase:
    """The interval walk on the x axis: label width for h, 0 and 1 outward, no second column."""
    spacing = gap_bars * SC["bar_px"]
    xs = {n: X1 + n * spacing for n in TIMEZONE_SET}
    visible = [n for n in TIMEZONE_SET if xs[n] <= PLOT_W]
    w = max(width_px(str(n)) for n in TIMEZONE_SET) + 2 * int(SC["halo"])
    kept: list[tuple[float, float]] = []
    drawn: list[int] = []
    order = sorted(visible, key=lambda n: (TZ_CLASS[n], n))
    for n in order:
        left = xs[n] - w / 2
        if (
            TZ_CLASS[n] == 0
            and len([m for m in visible if TZ_CLASS[m] == 0]) == 2
            and spacing < w + G
        ):
            left = xs[n] - w if n == 0 else xs[n]  # outward: 0 left of its line, 1 right of it
        if all(left >= b + G or left + w <= a - G for a, b in kept):
            kept.append((left, left + w))
            drawn.append(n)
    dropped = [n for n in visible if n not in drawn]
    return TzCase(gap_bars, spacing, visible, sorted(drawn), dropped, w)


TZ_CASES = [tz_walk(g) for g in (25, 2, 1)]
for _c in TZ_CASES:
    if 0 not in _c.drawn or 1 not in _c.drawn:
        FAILS.append(f"time zones at {_c.gap_bars} bars: 0 or 1 dropped")


# ---- 5. the anchored VWAP specimen (24 section 9; the kernel's running sums) --
def minutes(hhmm: str) -> int:
    hh, mm = hhmm.split(":")
    return int(hh) * 60 + int(mm)


@dataclass
class Vwap:
    bars: int
    vwap: Decimal
    sigma: Decimal
    bands: dict[int, tuple[Decimal, Decimal]]
    sigma_px: float
    prefix_bars: int
    prefix_px: float
    last_price: Decimal
    legend: str


def vwap_specimen() -> Vwap:
    """A deterministic synthetic 1-minute series from the VWAP anchor to the second fib anchor.

    Prices wander around the anchor price on two sines, volumes on a third. Nothing here is market
    data: the series exists so the tail chip, the band legend and the sigma in px are computed,
    never typed. The running sums are the kernel's (floats, quantised on emit; 24 section 9).
    """
    n = minutes(TIMES["anchor2"]) - minutes(TIMES["vwap"]) + 1
    base = float(PRICES["vwap"])
    spv = sv = svpp = 0.0
    vwap = sigma = last = 0.0
    for i in range(n):
        p = round(base + 180 * math.sin(i / 20) + 40 * math.sin(i / 7), 1)
        v = round(100 + 60 * (1 + math.sin(i / 5)), 3)
        spv, sv, svpp, last = spv + p * v, sv + v, svpp + v * p * p, p
        vwap = spv / sv
        sigma = math.sqrt(max(0.0, svpp / sv - vwap * vwap))  # sqrt(sum(v (p - vwap)^2) / sum v)
    bands = {k: (q1(vwap - k * sigma), q1(vwap + k * sigma)) for k in (1, 2, 3)}
    prefix = minutes(TIMES["ticks"]) - minutes(TIMES["vwap"])
    legend = (
        f"Anchored VWAP {TIMES['vwap']} {fmt_price(q1(vwap))} {MID} ±1{SIGMA} "
        f"{fmt_price(bands[1][0])} / {fmt_price(bands[1][1])}"
    )
    px = round(sigma * PX_PER_PRICE, 1)
    return Vwap(n, q1(vwap), q1(sigma), bands, px, prefix, prefix * SC["bar_px"], q1(last), legend)


VWAP = vwap_specimen()


@dataclass
class BandRow:
    alpha: float
    mode: str
    effective: float
    theme: str
    worst_over: float
    worst_ink: str
    worst_under: float


def band_composites() -> list[BandRow]:
    """The k-sigma zone fills at the default and the ceiling, stacked and flattened (D04 §5)."""
    rows: list[BandRow] = []
    inks = ("up", "down", "wick")
    for alpha in (SC["fill_default"], SC["fill_ceiling"]):
        for mode, stack in (("three-stack", 3), ("flattened", 1)):
            eff = 1 - (1 - alpha) ** stack
            for theme in THEMES:
                fill, canvas = col(theme, "drawing.default"), col(theme, "surface.canvas")
                tc = mix(fill, eff, canvas)
                over = min((ratio(mix(fill, eff, col(theme, f"candle.{k}")), tc), k) for k in inks)
                under = min(ratio(col(theme, f"candle.{k}"), tc) for k in inks)
                rows.append(
                    BandRow(
                        alpha,
                        mode,
                        round(eff, 4),
                        theme,
                        round(over[0], 2),
                        over[1],
                        round(under, 2),
                    )
                )
    return rows


BANDS = band_composites()


def fill_ceiling_default() -> float:  # the largest 0.05 step at which every candle ink keeps 3:1
    best = 0.0
    for step in range(1, 21):  # 0.05 .. 1.00; the search stops at the first failing step
        alpha, ok = step * 0.05, True
        for theme in THEMES:
            fill, canvas = col(theme, "drawing.default"), col(theme, "surface.canvas")
            tc = mix(fill, alpha, canvas)
            for k in ("up", "down", "wick"):
                ok = ok and ratio(mix(fill, alpha, col(theme, f"candle.{k}")), tc) >= 3
        if not ok:
            break
        best = alpha
    return round(best, 2)


CEILING_DEFAULT = fill_ceiling_default()


# ---- 6. the ribbon arithmetic; 4. the glyph budget; 7. the density study --
@dataclass
class Ribbon:
    delta: str
    pct: str
    bars: int
    minutes: int
    line1: str
    line2: str
    line2_gap: str
    gap_bars: int
    chip_w: int
    chip_h: int
    chip_h_comfortable: int
    box_w: int
    box_h: int
    name: str
    surrogate: str


def ribbon() -> Ribbon:
    p1, p2 = PRICES["anchor1"], PRICES["anchor2"]
    delta = (p2 - p1).quantize(TICK)
    pct_ = (delta / p1 * 100).quantize(D("0.01"), rounding=ROUND_HALF_UP)
    span_min = minutes(TIMES["anchor2"]) - minutes(TIMES["anchor1"])
    bars = span_min // int(SC["interval_min"]) + 1  # loaded bars, both anchor bars included
    sign = "+" if delta >= 0 else "\u2212"  # the minus U+2212
    line1 = f"{sign}{abs(delta):,.1f} {MID} {sign}{abs(pct_)} %"
    line2 = f"{bars} bars {MID} {span_min} min"
    gap_bars = bars - int(SC["gap_bars"])
    line2_gap = f"{gap_bars} bars (gap) {MID} {span_min} min"
    chars = max(len(line1), len(line2_gap))
    chip_w = math.ceil(chars * SC["label_pt"] * 0.6) + 16  # type.num.sm mono at 0.6 em, 8 px pads
    chip_h = 2 * LINE_BOX + 8
    chip_h_comfortable = chip_h - 4  # D06 :134's direction for canvas chips: 24 -> 20, so 36 -> 32
    name = (
        f"Measure {TIMES['anchor1']} {name_price(p1)} {ARROW} {TIMES['anchor2']} {name_price(p2)}"
    )
    surrogate = f"Measure, {bars} bars, plus {abs(delta):,.1f}"
    box_w, box_h = round(X2 - X1), round(float(abs(delta)) * PX_PER_PRICE)
    return Ribbon(
        f"{sign}{abs(delta):,.1f}", f"{sign}{abs(pct_)} %", bars, span_min, line1, line2,
        line2_gap, gap_bars, chip_w, chip_h, chip_h_comfortable, box_w, box_h, name, surrogate,
    )  # fmt: skip


RIBBON = ribbon()
TAIL_CHIP = f"{fmt_price(VWAP.vwap)} (estimated)"
MARKER_CAPTION = (
    "(estimated)"  # the word beside the CMP-227 marker (15:2669: a label beside the mark)
)
TAIL_CHIP_W = width_px(TAIL_CHIP) + 16  # the chip box: the glyph run plus 8 px pads
VWAP_CLAMP = {  # the follow-viewport rule (spec section 5.1 / section 6.2): pane px
    "chip_x": PLOT_W
    - SC["inset"]
    - TAIL_CHIP_W,  # the tail chip's left edge at the inner right margin
    "marker_x": SC["inset"] + 10,  # the marker's centre at the inner left margin (a 20 px pill)
    "caption_x": SC["inset"] + 20 + 4,  # the caption 4 px right of the clamped marker
}
ANCHORS = (
    f"{TIMES['anchor1']} {name_price(PRICES['anchor1'])} {ARROW} "
    f"{TIMES['anchor2']} {name_price(PRICES['anchor2'])}"
)
# D07's templates (if PR 4270 merges as is) rendered for the scenario; the tree row = the name
NAMES_D07 = {
    "fib_retracement": f"Fib retracement {ANCHORS} {MID} {len(LEVELS)} levels",
    "fib_timezone": f"Fib time zones {ANCHORS} {MID} {len(TIMEZONE_SET)} levels",
    "anchored_vwap": (
        f"Anchored VWAP {TIMES['vwap']} {name_price(PRICES['vwap'])} "
        f"{MID} 1{SIGMA} 2{SIGMA} 3{SIGMA}"
    ),
    "measure": RIBBON.name,
    "badge": "Estimated, Anchored VWAP, volume approximated from bars",
    "ribbon_surrogate": RIBBON.surrogate,
}


@dataclass
class Budget:
    measured_case: int
    fraction: float
    budget: int
    additive_pct: int
    fib_full: int
    fib_short: int
    fib24_full: int
    chip: int
    caption: int
    ribbon: int
    fibs_full: int
    fibs24_full: int
    p0p1_short: int
    stages_200: dict[str, int]
    holds_at: str


def glyph_budget() -> Budget:
    measured = int(GLYPH_CASE.group(2).replace(",", "")) if GLYPH_CASE else 0
    budget = int(measured * SC["budget_fraction"])
    additive = (
        round(100 * (measured + budget) / measured) if measured else 0
    )  # % of the measured case
    full = {lv: glyphs(full_label(lv)) for lv in LEVELS}
    short = {lv: glyphs(short_label(lv)) for lv in LEVELS}
    fib_full, fib_short = sum(full.values()), sum(short.values())
    p0p1_short = sum(g for lv, g in short.items() if cls(lv) <= 1)
    stages = {
        "full": 200 * fib_full,
        "drop P4": 200 * sum(g for lv, g in full.items() if cls(lv) <= 3),
        "drop P3": 200 * sum(g for lv, g in full.items() if cls(lv) <= 2),
        "drop P2": 200 * sum(g for lv, g in full.items() if cls(lv) <= 1),
        "short form": 200 * p0p1_short,
    }
    holds = next((k for k, v in stages.items() if v <= budget), "none")
    if holds == "none":
        FAILS.append("the glyph budget does not hold at 200 fibs after the thinning order")
    rib = glyphs(RIBBON.line1) + glyphs(RIBBON.line2)
    fib24 = 24 * max(full.values())
    return Budget(
        measured, SC["budget_fraction"], budget, additive, fib_full, fib_short, fib24,
        glyphs(TAIL_CHIP), glyphs(MARKER_CAPTION), rib, budget // fib_full, budget // fib24,
        p0p1_short, stages, holds,
    )  # fmt: skip


BUDGET = glyph_budget()


@dataclass
class Density:
    field_px2: float
    opaque_pct: float
    tinted_pct: float
    per: dict[str, float]


def density() -> Density:
    field = PLOT_W * SC["rows"] * SC["cell_px"]  # 100 bars x 25 rows of 12 x 12 px cells

    def pc(a: float) -> float:
        return round(100 * a / field, 2)

    fib_lines = sum((2 if cls(lv) <= 1 else 1) * (X2 - X1) for lv in LEVELS)
    fib_labels = sum(width_px(full_label(lv)) * H for lv in LEVELS)
    curve = 2 * PLOT_W + 2 * SC["halo"] * PLOT_W
    edges = 6 * PLOT_W
    band_zone = min(field, 6 * VWAP.sigma_px * PLOT_W)
    rib_outline = 2 * (RIBBON.box_w + RIBBON.box_h)
    chip = RIBBON.chip_w * RIBBON.chip_h
    tail = TAIL_CHIP_W * 24
    caption_ink = (width_px(MARKER_CAPTION) + 2) * H  # the word beside the marker, with its outline
    rib_fill = RIBBON.box_w * RIBBON.box_h
    per = {
        "fib lines": pc(fib_lines),
        "fib labels": pc(fib_labels),
        "VWAP curve + halo": pc(curve),
        "band edges": pc(edges),
        "ribbon outline": pc(rib_outline),
        "ribbon chip": pc(chip),
        "tail chip": pc(tail),
        "marker caption": pc(caption_ink),
        "band fills (tinted)": pc(band_zone),
        "ribbon fill (tinted)": pc(rib_fill),
    }
    opaque = fib_lines + fib_labels + curve + edges + rib_outline + chip + tail + caption_ink
    return Density(field, pc(opaque), pc(min(field, band_zone + rib_fill)), per)


DENSITY = density()


# ---- the two theme decisions the spec states per theme (Q7; the lesser default on the label ink --
def label_ink() -> (
    dict[str, str]
):  # the drawing colour if it reads as text on the canvas, else text
    out: dict[str, str] = {}
    for t in THEMES:
        ok = ratio(col(t, "drawing.default"), col(t, "surface.canvas")) >= BAR["text"]
        out[t] = "drawing.default" if ok else "text.primary"
    return out


LABEL_INK = label_ink()
MUTED_RATIOS = {
    t: round(
        ratio(paint("drawing.default@0.7", t, col(t, "surface.canvas")), col(t, "surface.canvas")),
        2,
    )
    for t in THEMES
}
MUTED_OK = all(v >= BAR["non-text"] for v in MUTED_RATIOS.values())
INTER_ALPHA = (
    0.7 if MUTED_OK else 1.0
)  # Q7: opacity.muted only if every theme keeps 3:1, else weight only

# ---- 8. the measured matrix (element, fg, bg, role; "tok@a" / "tok@NxA" composites) ------------
P3 = "drawing.default@3x0.05"
PAIRS: list[tuple[str, str, str, str]] = [
    (
        "level and time-zone label ink, decided per theme, on the canvas",
        "LABEL_INK",
        "surface.canvas",
        "text",
    ),
    (
        "level label in the drawing colour on the canvas (the candidate)",
        "drawing.default",
        "surface.canvas",
        "candidate",
    ),
    (
        "2 px level line, VWAP curve, ribbon and hover outline, dashed prefix",
        "drawing.default",
        "surface.canvas",
        "non-text",
    ),
    (
        "1 px level line and band edge as decided (INTER_ALPHA)",
        "drawing.default@INTER",
        "surface.canvas",
        "non-text",
    ),
    (
        "1 px level line at opacity.muted (the candidate Q7 tests)",
        "drawing.default@0.7",
        "surface.canvas",
        "candidate",
    ),
    (
        "selected outline 1 px on the canvas (D06 :504 reproduced)",
        "drawing.selected",
        "surface.canvas",
        "non-text",
    ),
    ("anchor marker dot on the canvas", "text.primary", "surface.canvas", "non-text"),
    (
        "anchor marker ring on the canvas: structure, with the dot",
        "border.strong",
        "surface.canvas",
        "decorative",
    ),
    (
        "tail chip, ribbon chip, label-chip text on the raised fill",
        "text.primary",
        "surface.raised",
        "text",
    ),
    (
        "chip hairline on the canvas: structure only",
        "border.default",
        "surface.canvas",
        "decorative",
    ),
    (
        "CMP-227 marker outline and glyph (E25-D05 :322 reproduced)",
        "status.info.default",
        "surface.canvas",
        "non-text",
    ),
    (
        "CMP-227 inline word on the info-subtle fill (15 reproduced)",
        "text.primary",
        "status.info.subtle",
        "text",
    ),
    (
        "T2 Pin: the full label and the lock glyph on the raised fill",
        "text.tertiary",
        "surface.raised",
        "text",
    ),
    (
        "T2 Pin: the reason under the label on the raised fill",
        "text.secondary",
        "surface.raised",
        "text",
    ),
    ("focus ring on the canvas (the DOM surrogates)", "focus.ring", "surface.canvas", "non-text"),
    (
        "focus ring on the raised chip (Pin, the badge button)",
        "focus.ring",
        "surface.raised",
        "non-text",
    ),
    ("up candle body over the three-stack band fill at 0.05", "candle.up", P3, "data-ink"),
    ("down candle body over the three-stack band fill at 0.05", "candle.down", P3, "data-ink"),
    ("wick over the three-stack band fill at 0.05", "candle.wick", P3, "data-ink"),
    (
        "up candle body over the ribbon fill at 0.05",
        "candle.up",
        "drawing.default@0.05",
        "data-ink",
    ),
    (
        "down candle body over the ribbon fill at 0.05",
        "candle.down",
        "drawing.default@0.05",
        "data-ink",
    ),
    ("wick over the ribbon fill at 0.05", "candle.wick", "drawing.default@0.05", "data-ink"),
    (
        "up candle body over the flattened fill at this hue's ceiling",
        "candle.up",
        "drawing.default@CEIL",
        "data-ink",
    ),
    (
        "down candle body over the flattened fill at this hue's ceiling",
        "candle.down",
        "drawing.default@CEIL",
        "data-ink",
    ),
    (
        "wick over the flattened fill at this hue's ceiling",
        "candle.wick",
        "drawing.default@CEIL",
        "data-ink",
    ),
    (
        "up candle body over the flattened fill at D04's 0.20 (reported)",
        "candle.up",
        "drawing.default@0.2",
        "reported",
    ),
    (
        "down candle body over the flattened fill at D04's 0.20 (reported)",
        "candle.down",
        "drawing.default@0.2",
        "reported",
    ),
    (
        "wick over the flattened fill at D04's 0.20 (reported)",
        "candle.wick",
        "drawing.default@0.2",
        "reported",
    ),
    (
        "drawing line over the up candle body (adjacent; the halo rule)",
        "drawing.default",
        "candle.up",
        "adjacent",
    ),
    (
        "drawing line over the down candle body (adjacent; the halo rule)",
        "drawing.default",
        "candle.down",
        "adjacent",
    ),
    (
        "drawing line over the bid cell fill (adjacent; the halo rule)",
        "drawing.default",
        "footprint.bid",
        "adjacent",
    ),
    (
        "drawing line over the ask cell fill (adjacent; the halo rule)",
        "drawing.default",
        "footprint.ask",
        "adjacent",
    ),
    (
        "drawing line over the imbalance cell fill (adjacent)",
        "drawing.default",
        "footprint.imbalance",
        "adjacent",
    ),
    (
        "cell text ink on the bid cell fill (E06-D01's pair; reported)",
        "text.primary",
        "footprint.bid",
        "reported",
    ),
    ("cell text ink on the ask cell fill (reported)", "text.primary", "footprint.ask", "reported"),
    (
        "cell text ink on the imbalance cell fill (reported)",
        "text.primary",
        "footprint.imbalance",
        "reported",
    ),
    # the cell text UNDER the drawing fills, against its own outline (AC 4; the lens round 1 F-5):
    # E06-D01 section 5's outline (palette.neutral.0 at 0.8 over the cell fill; dark and hc — the
    # worst of the three fills) and, where E06-D01 measures no pair, the pane colour (light)
    (
        "cell text ink under the three-stack band fill at 0.05, against its outline",
        "text.primary",
        P3 + "|outline",
        "text",
    ),
    (
        "cell text ink under the ribbon fill at 0.05, against its outline",
        "text.primary",
        "drawing.default@0.05|outline",
        "text",
    ),
    (
        "cell text ink under the flattened fill at the 0.20 ceiling, against its outline",
        "text.primary",
        "drawing.default@CEIL|outline",
        "text",
    ),
    (
        "cell text ink under a three-stack at 0.20 (reported; behind the flatten switch)",
        "text.primary",
        "drawing.default@3x0.2|outline",
        "reported",
    ),
]
MJS = re.sub(r"\s+", " ", (ROOT / "tools" / "contrast" / "pairs.mjs").read_text(encoding="utf-8"))
REGISTERED = set(re.findall(r'fg: "([^"]+)", bg: "([^"]+)"', MJS))
OUTLINE_INK = prim("palette.neutral.0")  # E06-D01 section 5: the cell text outline, at 0.8
CELL_OUTLINES = {  # the outline colour(s) the cell text is read against, per theme
    t: (
        [col(t, "surface.canvas")]
        if t == "light"
        else [mix(OUTLINE_INK, 0.8, col(t, f"footprint.{k}")) for k in ("bid", "ask", "imbalance")]
    )
    for t in THEMES
}


def paint2(expr: str, theme: str, under: str) -> str:  # paint() plus the two decided expressions
    if expr == "LABEL_INK":
        return col(theme, LABEL_INK[theme])
    expr = expr.replace("@INTER", f"@{INTER_ALPHA}").replace("@CEIL", f"@{CEILING_DEFAULT}")
    return paint(expr, theme, under)


def pair_value(fg: str, bg: str, theme: str) -> float:
    """One pair in one theme. A composite bg ("tok@a") is the fill over the canvas; a pure fg under
    it is composited in the layer order the spec uses — the fill OVER the ink (drawings sit above
    the series, 26 section 3.1) — so both sides of the pair carry the tint. "|outline" reads the
    cell text against its outline instead of the canvas (the worst of the outline colours)."""
    bexpr, _, flag = bg.partition("|")
    unders = CELL_OUTLINES[theme] if flag == "outline" else [col(theme, "surface.canvas")]
    vals: list[float] = []
    for under in unders:
        bgh = paint2(bexpr, theme, under)
        over = "@" in bexpr and "@" not in fg and fg != "LABEL_INK"
        fgh = paint2(bexpr, theme, col(theme, fg)) if over else paint2(fg, theme, bgh)
        vals.append(ratio(fgh, bgh))
    return round(min(vals), 2)


@dataclass
class PairRow:
    element: str
    fg: str
    bg: str
    role: str
    values: list[float]
    verdict: str
    status: str


def matrix() -> list[PairRow]:
    rows: list[PairRow] = []
    for el, fg, bg, role in PAIRS:
        vals = [pair_value(fg, bg, t) for t in THEMES]
        bar = BAR.get(role)
        if bar is None:
            verdict = f"{role} (not gated)"
        else:
            bad = [THEMES[i] for i, v in enumerate(vals) if v < bar]
            verdict = "PASS" if not bad else "FAIL: " + ", ".join(bad)
            if bad:
                FAILS.append(f"pair below the bar: {el}")
        pure = "@" not in fg and "@" not in bg and fg != "LABEL_INK"
        if not pure:
            status = "composite (no pairs.mjs row)"
        elif ("color." + fg, "color." + bg) in REGISTERED:
            status = "registered"
        else:
            status = "PROPOSED"
        if fg == "LABEL_INK":
            fg = " / ".join(LABEL_INK[t] for t in THEMES)
        rows.append(
            PairRow(
                el,
                fg,
                bg.replace("|outline", " over the cell outline"),
                role,
                vals,
                verdict,
                status,
            )
        )
    return rows


MATRIX = matrix()
GATED = [r for r in MATRIX if r.role in BAR]
FAIL_BY_THEME = {
    t: sum(1 for r in GATED if r.values[i] < BAR[r.role]) for i, t in enumerate(THEMES)
}
REG_N = sum(r.status == "registered" for r in MATRIX)
PROP_N = sum(r.status == "PROPOSED" for r in MATRIX)
HALO_NEEDED = {
    t: [
        k
        for k in ("bid", "ask", "imbalance")
        if ratio(col(t, "drawing.default"), col(t, f"footprint.{k}")) < 3
    ]
    for t in THEMES
}
HC_DRAWING = sorted(n for n in NAMES if n.startswith("color.drawing.") and n not in HC_FILE)
VERIFY_SRC = (TOKENS / "tests/verify_tokens.py").read_text(encoding="utf-8").splitlines()
HC_EXEMPT_LINE = next((i + 1 for i, ln in enumerate(VERIFY_SRC) if '"color.drawing.",' in ln), 0)

# ---- 9. the CVD rows (the eight PROPOSED palette aliases from E13-D03's table, never typed) ------
SLOT_RE = re.compile(
    r"^\| `color\.indicator\.palette\.(\d)` +\| `([^`]+)` / `([^`]+)` +\| `(#[0-9A-Fa-f]{6})` / "
    r"`(#[0-9A-Fa-f]{6})` / `(#[0-9A-Fa-f]{6})`",
    re.MULTILINE,
)


def slots() -> dict[str, dict[int, str]]:
    out: dict[str, dict[int, str]] = {t: {} for t in THEMES}
    for m in SLOT_RE.finditer(read(E13)):
        n, a_dark, a_light = int(m.group(1)), m.group(2), m.group(3)
        hx = {
            "dark": m.group(4).upper(),
            "light": m.group(5).upper(),
            "high-contrast": m.group(6).upper(),
        }
        for t, alias in (("dark", a_dark), ("light", a_light), ("high-contrast", a_dark)):
            resolved = str(ALL["dark"].get(alias, "")).upper()
            if resolved != hx[t]:
                FAILS.append(f"E13-D03 slot {n} {t}: {alias} resolves to {resolved}, not {hx[t]}")
            out[t][n] = hx[t]
    if any(len(v) != 8 for v in out.values()):
        FAILS.append("E13-D03 section 3.1: eight slots were not parsed")
    return out


SLOTS = slots()


def hex_of(expr: str, theme: str) -> str:  # "slot.N" | a colour token's short name
    if expr.startswith("slot."):
        return SLOTS[theme][int(expr[5:])]
    return col(theme, expr)


CVD_PAIRS: list[tuple[str, str, str]] = [
    ("drawing default vs selected", "drawing.default", "drawing.selected")
]
CVD_PAIRS += [
    (f"slot {a} vs slot {b}", f"slot.{a}", f"slot.{b}")
    for a in range(1, 9)
    for b in range(a + 1, 9)
]
CVD_PAIRS += [
    (f"slot {n} vs candle {k}", f"slot.{n}", f"candle.{k}")
    for n in range(1, 9)
    for k in ("up", "down")
]
CVD_PAIRS += [
    ("badge info hue vs candle up", "status.info.default", "candle.up"),
    ("badge info hue vs candle down", "status.info.default", "candle.down"),
    ("badge info hue vs drawing default", "status.info.default", "drawing.default"),
]
DEFICIENCIES = ("protanopia", "deuteranopia", "tritanopia")


@dataclass
class CvdRow:
    pair: str
    theme: str
    deltas: list[float]
    verdict: str


def cvd_rows() -> list[CvdRow]:
    out: list[CvdRow] = []
    for name, a, b in CVD_PAIRS:
        for t in THEMES:
            ha, hb = hex_of(a, t), hex_of(b, t)
            d = [round(float(cvd.delta_e76(ha, hb)), 1)]
            for kind in DEFICIENCIES:
                sa, sb = str(cvd.simulate(ha, kind)), str(cvd.simulate(hb, kind))
                d.append(round(float(cvd.delta_e76(sa, sb)), 1))
            verdict = (
                "distinct" if min(d) >= 5.0 else "COLLAPSES (weight / label / anchor carries it)"
            )
            out.append(CvdRow(name, t, d, verdict))
    return out


CVD = cvd_rows()
COLLAPSES = sum(c.verdict != "distinct" for c in CVD)
GREY_TOKENS = (
    "surface.canvas",
    "surface.raised",
    "drawing.default",
    "drawing.selected",
    "text.primary",
    "border.strong",
    "status.info.default",
    "candle.up",
    "candle.down",
    "candle.wick",
)


def grey_rows() -> (
    list[tuple[str, str, str, str, float]]
):  # token, theme, hex, grey, grey on grey canvas
    rows: list[tuple[str, str, str, str, float]] = []
    for t in THEMES:
        gc = grey(col(t, "surface.canvas"))
        for k in GREY_TOKENS:
            h = col(t, k)
            rows.append((k, t, h, grey(h), round(ratio(grey(h), gc), 2)))
    return rows


GREYS = grey_rows()

# ---- 10. the hotkey lint and the key gate; 11. the token bindings -------------------------------
LINT_ERRORS: list[str] = keymap_lint.lint_keymap(KEYMAP)
COMMANDS = KEYMAP["commands"]
KEY_RE = re.compile(
    r"`((?:(?:Ctrl|Alt|Shift|Meta)\+)+[^`\s]+|Enter|Esc|Escape|Space|Tab|Del|Backspace|Home|End|"
    r"PageUp|PageDown|F2|[↑↓←→](?: / [↑↓←→])?)`"
)
TOKEN_RE = re.compile(
    r"`((?:color|space|size|radius|border|type|elevation|opacity|motion|font|pattern)"
    r"\.[a-z0-9][a-z0-9.-]*[a-z0-9])`"
)
PROPOSED_PREFIXES = ("size.stroke.", "opacity.indicator.", "color.drawing.palette.", "pattern.")
TOOL_ROW = re.compile(
    r"^\| (?:fib_retracement|fib_extension|fib_timezone|anchored_vwap|measure) +\|", re.MULTILINE
)


def section(md: str, start: str, end: str) -> str:
    i = md.find(start)
    if i < 0:
        return ""
    j = md.find(end, i + len(start))
    return md[i:] if j < 0 else md[i:j]


def key_gate(spec: str) -> dict[str, int]:
    d02 = read(D02)
    allowed = set(KEY_RE.findall(section(d02, "## 9. The keyboard-creation path", "## 10.")))
    allowed |= set(KEY_RE.findall(section(d02, "### 5.3", "### 5.4")))
    allowed |= set(KEY_RE.findall(section(d02, "### 2.2", "### 2.3")))
    for c in COMMANDS:
        for b in [c.get("defaultBinding", ""), *c.get("altBindings", [])]:
            if b:
                allowed.add(str(b))
    allowed |= {"Esc", "Escape", "Enter", "Space", "Tab"}  # the shipped names of the same keys
    used = set(KEY_RE.findall(section(spec, "## 9. Keyboard", "## 10.")))
    for k in sorted(used - allowed):
        FAILS.append(
            f"spec section 9 names a key outside D02 section 9 and the shipped keymap: {k}"
        )
    return {"commands": len(COMMANDS), "errors": len(LINT_ERRORS), "spec_keys": len(used)}


def token_gate(spec: str, hand: str) -> dict[str, int]:
    bound: set[str] = set()
    proposed: set[str] = set()
    for name, txt in (("spec", spec), ("handoff", hand)):
        for ln in txt.splitlines():
            for tok in TOKEN_RE.findall(ln):
                if tok == "color.text.disabled":
                    if "never" not in ln:
                        FAILS.append(
                            f"{name}: color.text.disabled bound outside a 'never' sentence"
                        )
                    continue
                if tok in NAMES:
                    bound.add(tok)
                elif "PROPOSED" in ln and tok.startswith(PROPOSED_PREFIXES):
                    proposed.add(tok)
                else:
                    FAILS.append(f"{name}: unknown token {tok} (not in the dark set, not PROPOSED)")
    return {"bound": len(bound), "proposed": len(proposed)}


# ---- 12. the string gates and 13. the counts ----------------------------------------------------
PATH_RE = re.compile(r"/(?:home|Users)/[^/\s]+/")
HOST_RE = re.compile(r"\bpenpot\.[a-z0-9-]+\.[a-z]{2,}", re.IGNORECASE)
HOME_USER = Path.home().name
FORBID = [
    "team-" + "id=",
    "file-" + "id=",
    "#/work" + "space",
    "SET-" + "ME",
    "TO" + "DO",
    "T" + "BD",
]
T2_SENTENCE = (
    "Every role-, grant-, environment-, session- or state-gated control on these surfaces is"
)
CAP_FORMULA = "floor((span + g) / (h + g))"
POINTER = "- **Hi-fi (fib, VWAP, measure):** [E14-D05.md](../design/E14/E14-D05.md)"
APPROX_MARKERS = (
    "US-DRAW-005",
    "11:1256",
    "D02 §11",
    "D07",
    "tree.tag.approximate",
    "C-",
    "ticket",
    "the story",
    "AC 3",
    "Q5",
    "drawing.vwap_approximate_shown",
    "volume approximated",
    "display name",
    "the word",
)
FRAME_RE = re.compile(r"`(SCR-03[07]/[a-z0-9-]+)`")
REG_QUOTES = (
    "`levels` 1..24",
    "`bands` ⊆ {1, 2, 3}",
    "`width` 1..8",
    "`dash` solid / dashed / dotted",
    "`font_size` 8..48",
    "`anchored_vwap` exactly 1",
    "`fib_extension` and `pitchfork` exactly 3",
    "`fib_retracement`, `fib_timezone` and `measure` exactly 2",
)
GATED_STRINGS = ("never persists", "until pinned", "deferred", "(estimated)", "`rbac.view_as`")
# 26 section 3.7's SDF glyph set, parsed from its line (the lens round 1 F-2): every string drawn
# on the canvas by these tools is checked against it; a glyph outside the set must be named in
# the spec's A-row to 26 section 3.7 (section 16.2) until the atlas gains it
GLYPH_LINE = re.search(r"\*\*Glyph set\*\*: digits, ([^—]+?) for labels", S26)
GLYPH_SET: set[str] = set("0123456789 ")
if GLYPH_LINE:
    for tok in re.findall(r"`([^`]+)`", GLYPH_LINE.group(1)):
        GLYPH_SET.update(tok)
    if "`A`\u2013`Z`" in GLYPH_LINE.group(1):
        GLYPH_SET.update(chr(c) for c in range(ord("A"), ord("Z") + 1))
    if "`a`\u2013`z`" in GLYPH_LINE.group(1):
        GLYPH_SET.update(chr(c) for c in range(ord("a"), ord("z") + 1))
else:
    FAILS.append("26 section 3.7: the glyph-set line was not parsed")
ON_CANVAS: list[str] = [
    *(full_label(lv) for lv in LEVELS),
    *(short_label(lv) for lv in LEVELS),
    *(str(n) for n in TIMEZONE_SET),
    f"{fmt_price(VWAP.vwap)}",
    TAIL_CHIP,
    MARKER_CAPTION,
    RIBBON.line1,
    RIBBON.line2,
    RIBBON.line2_gap,
    RIBBON.line1.replace("+", "\u2212"),
]
GLYPHS_OUTSIDE = sorted({ch for s in ON_CANVAS for ch in s if ch not in GLYPH_SET})


def glyph_gate(spec: str) -> dict[str, object]:
    a_rows = section(spec, "### 16.2", "### 16.3")
    glyph_row = " ".join(ln for ln in a_rows.splitlines() if "glyph set" in ln.lower())
    if not glyph_row:
        FAILS.append("section 16.2 has no A-row about 26 section 3.7's glyph set")
    for ch in GLYPHS_OUTSIDE:
        name = f"U+{ord(ch):04X}"
        if ch not in glyph_row and name not in glyph_row:
            FAILS.append(
                f"on-canvas glyph {ch!r} ({name}) is outside 26:220's set; "
                "the glyph-set A-row lacks it"
            )
    return {
        "set_size": len(GLYPH_SET),
        "strings": len(ON_CANVAS),
        "outside": [f"{ch} U+{ord(ch):04X}" for ch in GLYPHS_OUTSIDE],
    }


def rows_of(md: str) -> list[list[str]]:
    out: list[list[str]] = []
    for ln in md.splitlines():
        if ln.startswith("|") and not re.match(r"^\|\s*-", ln):
            out.append([c.strip() for c in ln.strip().strip("|").split("|")])
    return out


def hygiene(name: str, txt: str) -> None:
    for bad in FORBID:
        if bad in txt:
            FAILS.append(f"{name}: forbidden text {bad!r}")
    if PATH_RE.search(txt) or (HOME_USER and HOME_USER in txt) or HOST_RE.search(txt):
        FAILS.append(f"{name}: a local path, the local user or a Penpot host")
    if "same as dark" in txt.lower():
        FAILS.append(f"{name}: 'same as dark'")
    if name not in ("spec", "handoff") and re.search(r"<[a-z][^>]*>", txt):
        FAILS.append(f"{name}: an unfilled <…> placeholder")


def string_gates(spec: str, hand: str, extra: list[Path]) -> dict[str, int]:
    const = (ROOT / "CONSTITUTION.md").read_text(encoding="utf-8")
    for name, txt in [("spec", spec), ("handoff", hand), *((p.name, read(p)) for p in extra)]:
        hygiene(name, txt)
    ids = set(re.findall(r"\bC-\d+\.\d+\b", spec + hand))
    for cid in sorted(ids):
        if not re.search(rf"(?<![\w.]){re.escape(cid)}(?![\w.])", const):
            FAILS.append(f"dangling rule id {cid}")
    d02 = read(D02)
    for t in sorted(set(re.findall(r"\bT\d\d\b", spec))):
        if f"| {t} " not in d02:
            FAILS.append(f"D02 transition {t} not found")
    if spec.count(T2_SENTENCE) != 1:
        FAILS.append(f"the T2 rule sentence appears {spec.count(T2_SENTENCE)} times, not once")
    if spec.count(CAP_FORMULA) != 1:
        FAILS.append(f"the cap formula appears {spec.count(CAP_FORMULA)} times, not once")
    for s_ in (*GATED_STRINGS, "`rbac.permission`", *REG_QUOTES):
        if s_ not in spec:
            FAILS.append(f"spec lacks the gated string {s_!r}")
    legs = [ln for ln in spec.splitlines() if "`rbac.view_as`" in ln and "`rbac.permission`" in ln]
    if not legs or any(ln.index("`rbac.view_as`") > ln.index("`rbac.permission`") for ln in legs):
        FAILS.append("the view-as leg is not first on every line that names both legs")
    for ln in spec.splitlines():
        if "pitchfork" in ln.lower() and "deferred" not in ln.lower():
            FAILS.append(f"pitchfork without 'deferred': {ln[:60]!r}")
        if re.search(r"\bapproximate\b", ln) and not any(m in ln for m in APPROX_MARKERS):
            FAILS.append(f"the word 'approximate' outside its allowed homes: {ln[:60]!r}")
    frames = set(FRAME_RE.findall(spec))
    for f in frames:
        if "pitchfork" in f or "approx" in f:
            FAILS.append(f"frame name {f}: a deferred tool or the superseded word")
    est_frames = [f for f in frames if "estimated" in f]
    if not est_frames:
        FAILS.append("no fallback frame is named with 'estimated'")
    for must in (
        "SCR-037/vwap-estimated-panned",
        "SCR-037/vwap-estimated-locked",
        "SCR-037/vwap-panned",
    ):
        if must not in frames:
            FAILS.append(f"the frame {must} is missing (the lens round 1 F-1 / F-3 / F-11)")
    if spec.count(MARKER_CAPTION) < 2 or "beside the mark" not in spec:
        FAILS.append("the marker's caption word is not specified beside the mark")
    fallback_rows = [r for r in rows_of(spec) if any(c.lower().startswith("fallback") for c in r)]
    for r in fallback_rows:
        if "(estimated)" not in " ".join(r):
            FAILS.append(f"fallback row without '(estimated)': {r[0][:50]!r}")
    pin_rows = [r for r in rows_of(spec) if r and "pin" in r[0].lower() and len(r) > 1]
    t2_pin = [r for r in pin_rows if any("T2" in c for c in r)]
    if len(t2_pin) < 2:
        FAILS.append(f"Pin has {len(t2_pin)} T2 rows (view-as and viewer expected)")
    s14 = (PLAN / "14-screens-catalogue.md").read_text(encoding="utf-8").splitlines()
    if sum(ln.startswith(POINTER) for ln in s14) != 1:
        FAILS.append("the 14 pointer line is not present exactly once")
    if hand.count("## Handoff checklist") != 3:
        FAILS.append("the handoff does not hold three blocks")
    blank = [ln for ln in hand.splitlines() if ln.startswith("- [ ]") and "N/A" not in ln]
    FAILS.extend(f"handoff: blank checklist line {ln[:40]!r}" for ln in blank)
    return {
        "fallback_rows": len(fallback_rows),
        "estimated_frames": len(est_frames),
        "pin_t2_rows": len(t2_pin),
        "frames_named": len(frames),
        "rule_ids": len(ids),
    }


def counts(spec: str, hand: str) -> dict[str, object]:
    def ids(prefix: str, start: str, end: str) -> int:
        rows = rows_of(section(spec, start, end))
        return len({r[0] for r in rows if re.fullmatch(rf"{prefix}\d+", r[0])})

    s0 = section(spec, "## 0.", "## 1.")
    board_rows = [r for r in rows_of(s0) if re.fullmatch(r"\d\d", r[0])]
    frames = {r[0]: len(FRAME_RE.findall("|".join(r))) for r in board_rows}
    planned, named = set(FRAME_RE.findall(s0)), set(FRAME_RE.findall(spec.replace(s0, "")))
    for f in sorted(planned ^ named):
        why = "planned but never named" if f in planned else "named but not planned"
        FAILS.append(f"frame {f} is {why}")
    tools = ("fib", "tz", "vwap", "measure")
    by_tool = {k: len([f for f in named if f.startswith(f"SCR-037/{k}-")]) for k in tools}
    stories = re.findall(r"`([A-Z][A-Za-z0-9]+)`", section(spec, "### 12.1", "### 12.2"))
    events = set(re.findall(r"`(drawing\.[a-z_]+)", section(spec, "## 13.", "## 14.")))
    return {
        "boards": len(board_rows),
        "twins": len([r for r in board_rows if "light" in r[1]]),
        "frames": frames,
        "frames_total": len(planned),
        "states": by_tool,
        "stories": len(stories),
        "events": len(events),
        "announcements": len(
            re.findall(r'^\| "', section(spec, "### 9.4", "### 9.5"), re.MULTILINE)
        ),
        "A": ids("A", "### 16.2", "### 16.3"),
        "C": ids("C", "### 16.3", "### 16.4"),
        "G": ids("G", "### 16.4", "### 16.5"),
        "Q": ids("Q", "### 16.5", "### 16.6"),
        "handoff_blocks": hand.count("## Handoff checklist"),
        "handoff_lines": len([ln for ln in hand.splitlines() if ln.startswith("- [")]),
    }


SCRIPT_TOKENS = {
    "canvas": "surface.canvas",
    "raised": "surface.raised",
    "hover": "surface.hover",
    "overlay": "surface.overlay",
    "app": "surface.app",
    "sunken": "surface.sunken",
    "text": "text.primary",
    "text2": "text.secondary",
    "text3": "text.tertiary",
    "border": "border.default",
    "borderStrong": "border.strong",
    "focus": "focus.ring",
    "drawDefault": "drawing.default",
    "drawSelected": "drawing.selected",
    "candleUp": "candle.up",
    "candleDown": "candle.down",
    "candleWick": "candle.wick",
    "fpBid": "footprint.bid",
    "fpAsk": "footprint.ask",
    "fpImb": "footprint.imbalance",
    "grid": "grid.line",
    "axis": "axis.text",
    "crosshair": "crosshair",
    "info": "status.info.default",
    "infoSubtle": "status.info.subtle",
    "infoStrong": "status.info.strong",
    "warningSubtle": "status.warning.subtle",
    "warningStrong": "status.warning.strong",
    "danger": "status.danger.default",
    "buy": "buy.default",
    "sell": "sell.default",
}


def fmt_rows(rows: list[Placed]) -> str:
    return "; ".join(f"{r.level} c{r.column} top {r.top:g}" for r in rows)


def table(p: Callable[[str], None], header: list[str], rows: list[list[object]]) -> None:
    p("| " + " | ".join(header) + " |")
    p("|" + "---|" * len(header))
    for r in rows:
        p("| " + " | ".join(str(c) for c in r) + " |")


def report(p: Callable[[str], None]) -> None:  # the plain text sections 1 to 9
    check_registries()
    p("## 1. Registries parsed as text (22, 24 section 9, 26)\n")
    for k, v in REG_LISTS.items():
        p(f"- {k}: {len(v)} — {', '.join(v)}")
    p(f"- key rules found as quoted: {REG_RULES}")
    p(f"- bounds: {BOUNDS}")
    p(f"- 24 SD bands: {BAND_FORMULA.group(1).strip() if BAND_FORMULA else 'UNPARSED'}")
    p(f"- 26 B3: {B3.group(0).strip() if B3 else 'UNPARSED'}")
    glyph_case = GLYPH_CASE.group(2) if GLYPH_CASE else "?"
    calls = DRAW_CALLS.group(1) if DRAW_CALLS else "?"
    p(f"- 26 section 3.7: measured case {glyph_case} glyphs; text draw calls ≤ {calls}")
    d02n, d03n = len(TOOL_ROW.findall(read(D02))), len(TOOL_ROW.findall(read(D03)))
    p(f"- D02 / D03 rows for the five tools: {d02n} / {d03n}")
    p("\n## 2. The scenario and the level ladder\n")
    p(f"scenario: {SC}")
    p(f"plot {PLOT_W:g} by {PLOT_H:g} px; {BARS_VISIBLE} bars by {int(SC['rows'])} rows")
    p(f"= {CELLS} cells; anchors x {X1:g} / {X2:g}; right room {RIGHT_ROOM:g} px")
    p(f"px per price unit {PX_PER_PRICE:.4f}; label box h = {LINE_BOX} + 2 halo = {H:g}")
    p(f"gap g = {G:g} px\n")
    hdr = ["level", "class", "price", "full label", "short", "width px (0.6 em)", "glyphs"]
    lv_rows: list[list[object]] = []
    for lv in LEVELS:
        full = full_label(lv)
        lv_rows.append(
            [
                lv,
                f"P{cls(lv)}",
                fmt_price(level_price(lv)),
                full,
                short_label(lv),
                width_px(full),
                glyphs(full),
            ]
        )
    table(p, hdr, lv_rows)
    p(f"\npriority order: {', '.join(str(lv) for lv in priority(LEVELS))}")
    p(f"label ink per theme (≥ 4.5 on the canvas keeps the drawing colour): {LABEL_INK}")
    muted = "accepted" if MUTED_OK else "rejected; weight-only hierarchy"
    p(f"opacity.muted candidate for the 1 px lines: {MUTED_RATIOS} → {muted}")
    p(f"INTER_ALPHA {INTER_ALPHA}")
    p("\n## 3. The collision walk: five spans, the narrow gutter, inverted, off-screen\n")
    hdr = [
        "span px",
        "cap",
        "form",
        "drawn",
        "dropped",
        "columns",
        "rows (level, column, top)",
        "inverted",
    ]
    case_rows: list[list[object]] = []
    for c in CASES:
        drop = ", ".join(c.dropped) or "—"
        inv = fmt_rows(c.inverted_rows or [])
        case_rows.append([c.span, c.cap, c.form, c.drawn, drop, c.columns, fmt_rows(c.rows), inv])
    table(p, hdr, case_rows)
    p(
        f"\nnarrow gutter ({SC['narrow_room']:g} px right / {SC['narrow_left']:g} px left "
        "at 120 px):"
    )
    p(
        f"side {NARROW.side}, form {NARROW.form}, drawn {NARROW.drawn}, "
        f"dropped {', '.join(NARROW.dropped) or '—'}"
    )
    for nm, w in (
        ("left side", LEFT),
        ("inside", INSIDE),
        ("pane-edge clamp (12 px at the top)", EDGE),
    ):
        p(
            f"{nm}: side {w.side}, form {w.form}, drawn {w.drawn}, columns {w.columns}, "
            f"dropped {', '.join(w.dropped) or '—'}; rows {fmt_rows(w.rows)}"
        )
    for nm, w in TWO.items():
        p(
            f"two ladders — {nm}: drawn {w.drawn}, columns {w.columns}, "
            f"dropped {', '.join(w.dropped) or '—'}; rows (pane px) {fmt_rows(w.rows)}"
        )
    p(f"label columns' left edges (pane px; column 2 inward): {COL_X}")
    p(f"off-screen: the second anchor {OFFSCREEN_SHIFT:g} px past the axis; clamp x = {CLAMP_X:g}")
    p("P0 / P1 survival and the shuffled-input determinism are asserted per case (see FAILS)")
    p("\n## 4. The glyph budget (26 section 3.7 / B3)\n")
    p(f"measured case {BUDGET.measured_case:,} by the fraction {BUDGET.fraction} (PROPOSED)")
    p(
        f"= {BUDGET.budget:,} glyphs per pane for drawing labels — ADDITIVE to the cell batch: "
        "the two"
    )
    p(
        f"batches sum to {BUDGET.additive_pct} % of the measured case "
        "(no measured case covers the sum)"
    )
    p(f"an 8-level fib: full {BUDGET.fib_full} / short {BUDGET.fib_short}; 24: {BUDGET.fib24_full}")
    p(f"tail chip {BUDGET.chip}; marker caption {BUDGET.caption}; ribbon {BUDGET.ribbon}")
    p(f"fibs in budget {BUDGET.fibs_full} (8 levels) / {BUDGET.fibs24_full} (24 levels)")
    p(f"200 fibs by thinning stage: {BUDGET.stages_200}; holds at stage '{BUDGET.holds_at}'")
    p(f"on-canvas glyphs outside 26:220's set: {[f'{c} U+{ord(c):04X}' for c in GLYPHS_OUTSIDE]}")
    p("\n## 4b. The time zones (the Fibonacci integers on the x axis)\n")
    hdr = ["anchor gap (bars)", "spacing px", "visible of 8", "labels drawn", "dropped", "label w"]
    tz_rows: list[list[object]] = []
    for tz in TZ_CASES:
        vis = f"{len(tz.visible)} ({', '.join(map(str, tz.visible))})"
        drawn = ", ".join(map(str, tz.drawn))
        tz_rows.append(
            [
                tz.gap_bars,
                f"{tz.spacing_px:g}",
                vis,
                drawn,
                ", ".join(map(str, tz.dropped)) or "—",
                tz.label_w,
            ]
        )
    table(p, hdr, tz_rows)
    p("\n## 5. The anchored VWAP specimen and the band composites (24 section 9; D04 section 5)\n")
    bands = {k: (fmt_price(a), fmt_price(b)) for k, (a, b) in VWAP.bands.items()}
    p(f"series {VWAP.bars} one-minute bars from {TIMES['vwap']}; VWAP {fmt_price(VWAP.vwap)}")
    p(f"sigma {VWAP.sigma} = {VWAP.sigma_px} px; bands {bands}; last {fmt_price(VWAP.last_price)}")
    p(f"approximated prefix {VWAP.prefix_bars} bars = {VWAP.prefix_px:g} px")
    p(f"(anchor {TIMES['vwap']} → first recorded print {TIMES['ticks']})")
    p(
        f'tail chip "{TAIL_CHIP}" ({TAIL_CHIP_W} px); marker caption "{MARKER_CAPTION}"; '
        f'legend "{VWAP.legend}"'
    )
    p(f"follow-viewport clamps (pane px): {VWAP_CLAMP}\n")
    hdr = ["alpha", "mode", "effective", "theme", "worst candle ink over the fill", "worst under"]
    band_rows: list[list[object]] = []
    for b in BANDS:
        band_rows.append(
            [
                b.alpha,
                b.mode,
                b.effective,
                b.theme,
                f"{b.worst_over} ({b.worst_ink})",
                b.worst_under,
            ]
        )
    table(p, hdr, band_rows)
    p(f"\nthis hue's flatten ceiling (largest 0.05 step at 3:1, every candle): {CEILING_DEFAULT}")
    p("\n## 6. The ribbon arithmetic\n")
    p(f"Δ {RIBBON.delta} · {RIBBON.pct} · {RIBBON.bars} bars · {RIBBON.minutes} min")
    p(f'line 1 "{RIBBON.line1}" / line 2 "{RIBBON.line2}"')
    p(f'across a gap of {SC["gap_bars"]:g} bars: "{RIBBON.line2_gap}"')
    p(
        f"chip {RIBBON.chip_w} by {RIBBON.chip_h} px ({RIBBON.chip_h_comfortable} comfortable); "
        f"box {RIBBON.box_w} by {RIBBON.box_h} px"
    )
    p(f"names (D07's templates for the scenario): {NAMES_D07}")
    p("\n## 7. The density study (coverage of the 2,500-cell field)\n")
    p(f"field {DENSITY.field_px2:,.0f} px²; opaque ink {DENSITY.opaque_pct} %")
    p(f"tinted {DENSITY.tinted_pct} %; per element: {DENSITY.per}")
    p(f"halo needed over the cell fills (the drawing colour under 3:1 against): {HALO_NEEDED}")
    p("\n## 8. The measured matrix (ratio per theme; the bar per role; pairs.mjs status)\n")
    hdr = ["element", "fg", "bg", "role", "dark", "light", "hc", "verdict", "pairs.mjs"]
    mx_rows: list[list[object]] = []
    for r in MATRIX:
        vals = [f"{v:.2f}" for v in r.values]
        mx_rows.append([r.element, f"`{r.fg}`", f"`{r.bg}`", r.role, *vals, r.verdict, r.status])
    table(p, hdr, mx_rows)
    p(f"\nrows {len(MATRIX)}, gated {len(GATED)}, FAIL per theme {FAIL_BY_THEME}")
    p(f"registered {REG_N}, PROPOSED {PROP_N}")
    p(f"no hc override (verify_tokens.py line {HC_EXEMPT_LINE} lists the family as exempt):")
    p(", ".join(HC_DRAWING))
    p("\n## 9. CVD (ΔE76 normal / protan / deutan / tritan; JND 5.0) and the Rec. 601 greys\n")
    cvd_rows_: list[list[object]] = []
    for c_ in CVD:
        cvd_rows_.append([c_.pair, c_.theme, " / ".join(f"{d:.1f}" for d in c_.deltas), c_.verdict])
    table(p, ["pair", "theme", "ΔE", "verdict"], cvd_rows_)
    p(f"\nCVD rows {len(CVD)} ({len(CVD_PAIRS)} pairs by 3 themes), collapses {COLLAPSES}\n")
    grey_rows_: list[list[object]] = []
    for k, t, h, g, rr in GREYS:
        grey_rows_.append([f"`color.{k}`", t, h, g, f"{rr:.2f}"])
    table(p, ["token", "theme", "hex", "grey", "grey on the grey canvas"], grey_rows_)


def summary(
    keys: dict[str, int],
    toks: dict[str, int],
    gates: dict[str, int],
    cnt: dict[str, object],
    gl: dict[str, object],
) -> str:
    levels: list[dict[str, object]] = []
    for lv in LEVELS:
        full = full_label(lv)
        levels.append(
            {
                "level": str(lv),
                "cls": cls(lv),
                "price": fmt_price(level_price(lv)),
                "full": full,
                "short": short_label(lv),
                "width": width_px(full),
                "glyphs": glyphs(full),
            }
        )
    cases_: list[dict[str, object]] = []
    for c in CASES:
        cases_.append(
            {
                "span": c.span,
                "cap": c.cap,
                "form": c.form,
                "drawn": c.drawn,
                "dropped": c.dropped,
                "columns": c.columns,
                "rows": [vars(r) for r in c.rows],
                "inverted": [vars(r) for r in c.inverted_rows or []],
            }
        )
    vwap: dict[str, object] = {
        "bars": VWAP.bars,
        "vwap": fmt_price(VWAP.vwap),
        "sigma": str(VWAP.sigma),
        "sigma_px": VWAP.sigma_px,
        "bands": {k: [fmt_price(a), fmt_price(b)] for k, (a, b) in VWAP.bands.items()},
        "prefix_bars": VWAP.prefix_bars,
        "prefix_px": VWAP.prefix_px,
        "last": fmt_price(VWAP.last_price),
        "chip": TAIL_CHIP,
        "chip_w": TAIL_CHIP_W,
        "caption": MARKER_CAPTION,
        "legend": VWAP.legend,
    }
    ladder: dict[str, object] = {
        "h": H,
        "g": G,
        "px_per_price": round(PX_PER_PRICE, 4),
        "label_ink": LABEL_INK,
        "inter_alpha": INTER_ALPHA,
        "muted": MUTED_RATIOS,
    }
    matrix_: dict[str, object] = {
        "rows": len(MATRIX),
        "gated": len(GATED),
        "fail": FAIL_BY_THEME,
        "registered": REG_N,
        "proposed": PROP_N,
        "pairs": [vars(r) for r in MATRIX],
        "hc_missing": HC_DRAWING,
    }
    cvd_: dict[str, object] = {
        "rows": len(CVD),
        "pairs": len(CVD_PAIRS),
        "collapses": COLLAPSES,
        "items": [vars(c) for c in CVD],
    }
    out: dict[str, object] = {
        "scenario": SC,
        "times": TIMES,
        "prices": {k: str(v) for k, v in PRICES.items()},
        "plot": {
            "w": PLOT_W,
            "h": PLOT_H,
            "bars": BARS_VISIBLE,
            "cells": CELLS,
            "x1": X1,
            "x2": X2,
        },
        "room": RIGHT_ROOM,
        "ladder": ladder,
        "levels": levels,
        "priority": [str(lv) for lv in priority(LEVELS)],
        "cases": cases_,
        "narrow": {
            "room": SC["narrow_room"],
            "room_left": SC["narrow_left"],
            "side": NARROW.side,
            "form": NARROW.form,
            "drawn": NARROW.drawn,
        },
        "side_cases": {
            k: {
                "side": w.side,
                "form": w.form,
                "drawn": w.drawn,
                "columns": w.columns,
                "dropped": w.dropped,
                "rows": [vars(r) for r in w.rows],
            }
            for k, w in (("left", LEFT), ("inside", INSIDE), ("edge", EDGE))
        },
        "two_ladders": {
            k: {
                "drawn": w.drawn,
                "columns": w.columns,
                "dropped": w.dropped,
                "rows": [vars(r) for r in w.rows],
            }
            for k, w in TWO.items()
        },
        "ladder_b": [str(x) for x in LADDER_B],
        "col_x": COL_X,
        "offscreen": {"shift": OFFSCREEN_SHIFT, "clamp_x": CLAMP_X},
        "vwap_clamp": VWAP_CLAMP,
        "glyphs": gl,
        "budget": vars(BUDGET),
        "timezone_set": list(TIMEZONE_SET),
        "tz_cases": [vars(c) for c in TZ_CASES],
        "vwap": vwap,
        "bands": [vars(b) for b in BANDS],
        "ceiling": CEILING_DEFAULT,
        "ribbon": vars(RIBBON),
        "names": NAMES_D07,
        "density": vars(DENSITY),
        "halo_needed": HALO_NEEDED,
        "matrix": matrix_,
        "cvd": cvd_,
        "slots": {t: {str(k): v for k, v in d.items()} for t, d in SLOTS.items()},
        "grey": [list(g) for g in GREYS],
        "lint": keys,
        "tokens_gate": toks,
        "gates": gates,
        "counts": cnt,
        "tokens": {t: {k: col(t, v) for k, v in SCRIPT_TOKENS.items()} for t in THEMES},
        "fails": FAILS,
    }
    return json.dumps(out, ensure_ascii=False)


def main() -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    extra = [Path(a) for a in args if not a.startswith("--")]
    out: list[str] = []
    report(out.append)
    spec, hand = read(SPEC), read(HANDOFF)
    keys, toks = key_gate(spec), token_gate(spec, hand)
    gates, cnt, gl = string_gates(spec, hand, extra), counts(spec, hand), glyph_gate(spec)
    out.append(
        f"\n## 10. Hotkey lint\n\nkeymap: {keys['commands']} commands, {keys['errors']} lint errors"
    )
    out.append(
        f"the spec's section 9 names {keys['spec_keys']} keys, all in D02 section 9 or the keymap"
    )
    out.append(
        f"\n## 11. Token bindings\n\n{toks}\n\n## 12. String gates\n\n{gates}\n\nglyphs: {gl}"
    )
    out.append(f"\n## 13. Counts\n\n{json.dumps(cnt, ensure_ascii=False)}")
    out.append(f"\nFAIL count (gated rows only): {len(FAILS)}" + "".join("\n- " + f for f in FAILS))
    print(summary(keys, toks, gates, cnt, gl) if "--json" in args else "\n".join(out))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
