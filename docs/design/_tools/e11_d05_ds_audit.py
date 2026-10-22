"""E11-D05 design-system audit: chart slots, OkLab ramps, density record, pattern registry.

Offline, `python3 -I`, UTF-8 stdout. The E11 lane's tool shape (E11-D02 / E11-D03): it imports the
loader of `packages/ui/tokens/tests/verify_tokens.py` (same alias resolution, same `themes.json`
layering), `contrast_ratio()` from `docs/design/_tools/contrast_check.py` and the Brettel / Vienot
`simulate()` of `docs/research/_tools/cvd_simulate.py`, so every chassis number agrees with E11-D02
§11.1 and E11-D03 to the hundredth. Nothing is re-implemented except the OkLab conversion, which
`tools/contrast` does not have (spec G-row).

What it prints, with a source label on every row:

1. the slot table of `docs/design/E11/E11-D05.md` §4 resolved per theme — every `color.chart.*`
   slot measured on the primitive its PROPOSED alias resolves to (`CR:` rows, the E11-D02 §11.4
   technique; `dim85:` rows for the stale state, `mut70:` for `opacity.muted`), plus the chassis
   rows the nine catalogue entries bind, against the role's bar (text 4.5:1, non-text 3:1,
   hc-text 7:1 in the high-contrast theme); the compare is UNROUNDED (`ratio >= threshold`, as
   `tools/contrast/generate.mjs`), and a value that would round onto a bar is printed to four
   decimals. `decorative` rows (`16` §6 rule 7), `rejected-*` rows and pairs already exempted in
   `tools/contrast/exemptions.json` are reported, never gated;
2. the OkLab module with its self-checks (white, black, a grey, the sRGB round trip of every colour
   token) and the ramp tables of spec §5: `ramp.delta`, `ramp.intensity.bid`, `ramp.intensity.ask`
   in the default and the CVD-safe palette, sampled at 16 stops in OkLab and, beside it, in the
   sRGB piecewise-linear lerp `tools/contrast/data-ink-lib.mjs` uses today — hex, L / a / b,
   chroma, the contrast on `color.surface.canvas`, the adjacent-sample ΔE76 and its evenness, and
   the adjacent-stop ΔE76 under protanopia / deuteranopia / tritanopia against the 5.0 JND floor;
3. the density record of spec §6 (E11-D02 D6, cited) echoed from one data literal;
4. the pattern / encoding registry of spec §7 echoed from one data literal;
5. every token name the nine `15` entries and the spec bind, resolved in all three themes or
   MISSING (the seven `color.chart.*` slots, `font.mono`, `color.text.muted`, `color.status.warn`,
   `color.chart.background`, `color.chart.grid` and `color.marker.*` are expected MISSING;
   `elevation.3` resolves as a primitive and is flagged: the semantic alias is
   `elevation.popover`);
6. which spec pairs `tools/contrast/pairs.mjs` registers (a text scan of its `fg` / `bg` literals),
   which `exemptions.json` exempts, which are PROPOSED, and whether `encodings.json` carries an
   `estimated`, `gap` or `reduced-detail` row;
7. the counts the Penpot boards quote.

Usage: python3 -I docs/design/_tools/e11_d05_ds_audit.py          (Markdown; exit 1 on a gated FAIL)
       python3 -I docs/design/_tools/e11_d05_ds_audit.py --json   (the boards' numbers)
       python3 -I docs/design/_tools/e11_d05_ds_audit.py --stops 16
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
import sys
from itertools import pairwise
from pathlib import Path
from types import ModuleType
from typing import TypedDict

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
PAIRS_MJS = ROOT / "tools" / "contrast" / "pairs.mjs"
EXEMPTIONS = ROOT / "tools" / "contrast" / "exemptions.json"
ENCODINGS = ROOT / "tools" / "contrast" / "encodings.json"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(TOKENS / "tests"))
verify = _load(TOKENS / "tests" / "verify_tokens.py", "verify_tokens")
contrast_check = _load(ROOT / "docs" / "design" / "_tools" / "contrast_check.py", "contrast_check")
cvd = _load(ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py", "cvd_simulate")

THEMES = ("dark", "light", "high-contrast")
DEFICIENCIES = ("protanopia", "deuteranopia", "tritanopia")
BAR: dict[str, float | None] = {
    "text": 4.5,
    "non-text": 3.0,
    "hc-text": 7.0,
    "decorative": None,
    "surface": None,
    "rejected-text": 4.5,
    "rejected-non-text": 3.0,
    "rejected-hc-text": 7.0,
}
GATED = ("text", "non-text", "hc-text")
BARS = (3.0, 4.5, 7.0)
JND = 5.0
CANVAS = "color.surface.canvas"


# ---------------------------------------------------------------- tokens --------------------------
def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(rgb: tuple[float, ...]) -> str:
    return "#" + "".join(f"{min(255, max(0, round(c))):02X}" for c in rgb)


def resolve_theme(name: str) -> dict[str, object]:
    prim = verify.load(verify.PRIMITIVES)
    allt = dict(prim)
    allt.update(verify.merged_set(verify.THEMES[name]))
    out: dict[str, object] = {}
    for key, val in allt.items():
        out[str(key)] = verify.resolve(val["$value"], allt)
    return out


T: dict[str, dict[str, object]] = {n: resolve_theme(n) for n in THEMES}
HEX6 = re.compile(r"^#[0-9A-Fa-f]{6}$")


def colour_tokens(theme: str) -> dict[str, str]:
    return {k: str(v) for k, v in T[theme].items() if isinstance(v, str) and HEX6.match(v)}


COLOURS: dict[str, dict[str, str]] = {n: colour_tokens(n) for n in THEMES}

# PROPOSED aliases measured on the primitive each would resolve to (never on an invented hex).
CR: dict[str, dict[str, str]] = {
    "CR:color.chart.axis": dict.fromkeys(THEMES, "color.text.tertiary"),
    "CR:color.chart.grid.major": dict.fromkeys(THEMES, "color.border.default"),
    "CR:color.chart.grid.minor": dict.fromkeys(THEMES, "color.grid.line"),
    "CR:color.chart.grid.minor@hc-alias": {
        "dark": "color.grid.line",
        "light": "color.grid.line",
        "high-contrast": "color.surface.canvas",
    },
    "CR:color.chart.crosshair": dict.fromkeys(THEMES, "color.crosshair"),
    "CR:color.chart.watermark": dict.fromkeys(THEMES, "color.border.default"),
    "CR:color.chart.pane.bg.default": dict.fromkeys(THEMES, "color.surface.canvas"),
    "CR:color.chart.pane.bg.focused": dict.fromkeys(THEMES, "color.surface.canvas"),
    "CR:color.chart.replay.border": {
        "dark": "palette.purple.400",
        "light": "palette.purple.600",
        "high-contrast": "palette.purple.400",
    },
    "CR:color.text.buy": {
        "dark": "palette.green.300",
        "light": "palette.light.green.700",
        "high-contrast": "palette.green.300",
    },
    "CR:color.text.sell": {
        "dark": "palette.red.300",
        "light": "palette.light.red.700",
        "high-contrast": "palette.red.300",
    },
}


def col(theme: str, token: str) -> str:
    """The resolved hex of a token, a `CR:` alias or a composite (`dim85:`, `mut70:`)."""
    if token in CR:
        return COLOURS[theme][CR[token][theme]]
    if token.startswith("dim85:"):  # the stale state: data-ink uniforms x 0.85 (E11-D02 D16)
        r, g, b = hex_to_rgb(col(theme, token[6:]))
        return rgb_to_hex((r * 0.85, g * 0.85, b * 0.85))
    if token.startswith("mut70:"):  # opacity.muted 0.7 over the canvas (the remote crosshair, D9)
        alpha = float(str(T[theme]["opacity.muted"]))
        f = hex_to_rgb(col(theme, token[6:]))
        u = hex_to_rgb(COLOURS[theme][CANVAS])
        return rgb_to_hex(tuple(alpha * a + (1 - alpha) * b for a, b in zip(f, u, strict=True)))
    return COLOURS[theme][token]


def ratio(fg: str, bg: str) -> float:
    return float(contrast_check.contrast_ratio(hex_to_rgb(fg), hex_to_rgb(bg)))


def fmt(value: float) -> str:
    """Two decimals, four where rounding to two would land on a bar the value does not clear."""
    two = round(value, 2)
    for bar in BARS:
        if two == bar and value != bar:
            return f"{value:.4f}"
    return f"{value:.2f}"


# ---------------------------------------------------------------- OkLab (Ottosson 2020) -----------
# sRGB -> linear -> LMS (M1 as published for linear sRGB) -> cube root -> Lab (M2). Confirmed
# against the
# public note on 2026-10-22 (the 2021-01-25 coefficients); the self-checks below stand on their own.
M1 = (
    (0.4122214708, 0.5363325363, 0.0514459929),
    (0.2119034982, 0.6806995451, 0.1073969566),
    (0.0883024619, 0.2817188376, 0.6299787005),
)
M2 = (
    (0.2104542553, 0.7936177850, -0.0040720468),
    (1.9779984951, -2.4285922050, 0.4505937099),
    (0.0259040371, 0.7827717662, -0.8086757660),
)
M2_INV = (
    (1.0, 0.3963377774, 0.2158037573),
    (1.0, -0.1055613458, -0.0638541728),
    (1.0, -0.0894841775, -1.2914855480),
)
M1_INV = (
    (4.0767416621, -3.3077115913, 0.2309699292),
    (-1.2684380046, 2.6097574011, -0.3413193965),
    (-0.0041960863, -0.7034186147, 1.7076147010),
)
Vec = tuple[float, float, float]


def matvec(m: tuple[Vec, Vec, Vec], v: Vec) -> Vec:
    return (
        m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
        m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
        m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
    )


def srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def linear_to_srgb(c: float) -> float:
    c = min(1.0, max(0.0, c))
    return c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def cbrt(x: float) -> float:
    return math.copysign(abs(x) ** (1 / 3), x)


def hex_to_oklab(h: str) -> Vec:
    r, g, b = (srgb_to_linear(c / 255) for c in hex_to_rgb(h))
    lms = matvec(M1, (r, g, b))
    return matvec(M2, (cbrt(lms[0]), cbrt(lms[1]), cbrt(lms[2])))


def oklab_to_srgb01(lab: Vec) -> Vec:
    lp, mp, sp = matvec(M2_INV, lab)
    lin = matvec(M1_INV, (lp**3, mp**3, sp**3))
    return (linear_to_srgb(lin[0]), linear_to_srgb(lin[1]), linear_to_srgb(lin[2]))


def oklab_to_hex(lab: Vec) -> str:
    return rgb_to_hex(tuple(c * 255 for c in oklab_to_srgb01(lab)))


def chroma(lab: Vec) -> float:
    return math.hypot(lab[1], lab[2])


def hue_deg(lab: Vec) -> float:
    return math.degrees(math.atan2(lab[2], lab[1])) % 360


def oklab_self_checks() -> dict[str, float]:
    """White, black and a grey land where OkLab puts them; every colour token round-trips."""
    white = hex_to_oklab("#FFFFFF")
    black = hex_to_oklab("#000000")
    grey = hex_to_oklab("#808080")
    worst = 0.0
    for theme in THEMES:
        for h in COLOURS[theme].values():
            back = oklab_to_srgb01(hex_to_oklab(h))
            orig = tuple(c / 255 for c in hex_to_rgb(h))
            worst = max(worst, *(abs(a - b) for a, b in zip(back, orig, strict=True)))
    return {
        "white_L": white[0],
        "white_ab": max(abs(white[1]), abs(white[2])),
        "black_L": abs(black[0]),
        "grey_ab": max(abs(grey[1]), abs(grey[2])),
        "round_trip_max_error": worst,
    }


def lerp(a: Vec, b: Vec, t: float) -> Vec:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


# ---------------------------------------------------------------- ramps (spec section 5) ----------
Stop = tuple[str, float]  # (token, position)
EPS = 1 / 8  # PROPOSED: the first visible stop at one eighth of each half (E47-S06's rule)
RAMPS: dict[str, dict[str, list[Stop]]] = {
    "ramp.delta": {
        "default": [
            ("color.sell.default", -1.0),
            ("color.heatmap.ask.1", -EPS),
            (CANVAS, 0.0),
            ("color.heatmap.bid.1", EPS),
            ("color.buy.default", 1.0),
        ],
        "cvd-safe": [
            ("color.cvd.sell", -1.0),
            ("color.cvd.heatmap.ask.1", -EPS),
            (CANVAS, 0.0),
            ("color.cvd.heatmap.bid.1", EPS),
            ("color.cvd.buy", 1.0),
        ],
    },
    "ramp.intensity.bid": {
        "default": [("color.heatmap.zero", 0.0)]
        + [(f"color.heatmap.bid.{i}", i / 5) for i in range(1, 6)],
        "cvd-safe": [("color.heatmap.zero", 0.0)]
        + [(f"color.cvd.heatmap.bid.{i}", i / 5) for i in range(1, 6)],
    },
    "ramp.intensity.ask": {
        "default": [("color.heatmap.zero", 0.0)]
        + [(f"color.heatmap.ask.{i}", i / 5) for i in range(1, 6)],
        "cvd-safe": [("color.heatmap.zero", 0.0)]
        + [(f"color.cvd.heatmap.ask.{i}", i / 5) for i in range(1, 6)],
    },
}
# The zero band: samples whose |position| lies inside the first visible stop carry no ink by design
# (`16` section 6 rule 3; data-ink-lib: the zero-delta midpoint always carries a text / sign
# channel).
FIRST_VISIBLE: dict[str, float] = {
    "ramp.delta": EPS,
    "ramp.intensity.bid": 1 / 5,
    "ramp.intensity.ask": 1 / 5,
}


class Sample(TypedDict):
    t: float
    oklab_hex: str
    oklab: Vec
    oklab_chroma: float
    srgb_hex: str
    srgb_lab: Vec
    srgb_chroma: float
    contrast_oklab: float
    contrast_srgb: float
    gated: bool


def interpolate(stops: list[tuple[Vec, float]], t: float) -> Vec:
    for (a, ta), (b, tb) in pairwise(stops):
        if ta <= t <= tb:
            f = 0.0 if tb == ta else (t - ta) / (tb - ta)
            return lerp(a, b, f)
    return stops[-1][0]


def sample_ramp(theme: str, ramp: str, palette: str, n: int) -> list[Sample]:
    stops = RAMPS[ramp][palette]
    canvas = COLOURS[theme][CANVAS]
    lab_stops = [(hex_to_oklab(COLOURS[theme][tok]), pos) for tok, pos in stops]
    rgb_stops = [
        (tuple(float(c) for c in hex_to_rgb(COLOURS[theme][tok])), pos) for tok, pos in stops
    ]
    lo, hi = stops[0][1], stops[-1][1]
    out: list[Sample] = []
    for i in range(n):
        t = lo + (hi - lo) * i / (n - 1)
        lab = interpolate(lab_stops, t)
        rgb = interpolate(
            [((r[0], r[1], r[2]), p) for r, p in rgb_stops],
            t,
        )
        ok_hex = oklab_to_hex(lab)
        s_hex = rgb_to_hex(rgb)
        out.append(
            {
                "t": t,
                "oklab_hex": ok_hex,
                "oklab": hex_to_oklab(ok_hex),
                "oklab_chroma": chroma(lab),
                "srgb_hex": s_hex,
                "srgb_lab": hex_to_oklab(s_hex),
                "srgb_chroma": chroma(hex_to_oklab(s_hex)),
                "contrast_oklab": ratio(ok_hex, canvas),
                "contrast_srgb": ratio(s_hex, canvas),
                "gated": abs(t) >= FIRST_VISIBLE[ramp] - 1e-9,
            }
        )
    return out


def de76(a: str, b: str) -> float:
    return float(cvd.delta_e76(a, b))


def sim(h: str, deficiency: str) -> str:
    return str(cvd.simulate(h, deficiency))


def adjacent_steps(hexes: list[str]) -> list[float]:
    return [de76(a, b) for a, b in pairwise(hexes)]


def evenness(steps: list[float]) -> float:
    """min / max of the adjacent-sample ΔE76 along a ramp: 1.0 is even, 0 is a dead step."""
    visible = [s for s in steps if s > 1e-9]
    return min(visible) / max(visible) if visible else 0.0


def stop_cvd(theme: str, ramp: str, palette: str) -> list[dict[str, float | str]]:
    """Adjacent stops (and the two ends of a diverging ramp) under each deficiency, JND 5.0."""
    stops = [tok for tok, _ in RAMPS[ramp][palette]]
    pairs = list(pairwise(stops))
    if ramp == "ramp.delta":
        pairs.append((stops[0], stops[-1]))
    rows: list[dict[str, float | str]] = []
    for a, b in pairs:
        ha, hb = COLOURS[theme][a], COLOURS[theme][b]
        row: dict[str, float | str] = {"a": a, "b": b, "normal": de76(ha, hb)}
        for d in DEFICIENCIES:
            row[d] = de76(sim(ha, d), sim(hb, d))
        row["worst"] = min(float(row[d]) for d in DEFICIENCIES)
        row["verdict"] = (
            "distinct" if float(row["worst"]) >= JND else "COLLAPSES (text / sign carries it)"
        )
        rows.append(row)
    return rows


def unanchored(theme: str, palette: str, n: int) -> dict[str, object]:
    """The rejected two-endpoint lerp (no zero stop): the mid-sample chroma and hue per space."""
    a, b = (
        ("color.sell.default", "color.buy.default")
        if palette == "default"
        else ("color.cvd.sell", "color.cvd.buy")
    )
    ha, hb = COLOURS[theme][a], COLOURS[theme][b]
    la, lb = hex_to_oklab(ha), hex_to_oklab(hb)
    ra = tuple(float(c) for c in hex_to_rgb(ha))
    rb = tuple(float(c) for c in hex_to_rgb(hb))
    mid = (n - 1) / 2
    ok_mid = lerp(la, lb, mid / (n - 1))
    s_mid_hex = rgb_to_hex(lerp((ra[0], ra[1], ra[2]), (rb[0], rb[1], rb[2]), mid / (n - 1)))
    s_mid = hex_to_oklab(s_mid_hex)
    ok_hexes = [oklab_to_hex(lerp(la, lb, i / (n - 1))) for i in range(n)]
    s_hexes = [
        rgb_to_hex(lerp((ra[0], ra[1], ra[2]), (rb[0], rb[1], rb[2]), i / (n - 1)))
        for i in range(n)
    ]
    return {
        "endpoints": [a, b],
        "oklab_mid_hex": oklab_to_hex(ok_mid),
        "oklab_mid_chroma": chroma(ok_mid),
        "oklab_mid_hue": hue_deg(ok_mid),
        "srgb_mid_hex": s_mid_hex,
        "srgb_mid_chroma": chroma(s_mid),
        "srgb_mid_hue": hue_deg(s_mid),
        "oklab_evenness": evenness(adjacent_steps(ok_hexes)),
        "srgb_evenness": evenness(adjacent_steps(s_hexes)),
        "endpoint_chroma": [chroma(la), chroma(lb)],
    }


# ------------------------------------------------------------- the measured pairs (spec section 10)
# element | fg | bg | role | source -- one record per line; a line indented by two spaces
# continues the
# record above it (so no physical line passes 100 columns). Slot rows first (every `color.chart.*`
# slot on the primitive its PROPOSED alias resolves to), then the series and ramp stops, then the
# chassis rows the nine entries bind (E11-D02 section 11.1 through the same functions, so they agree
# to the hundredth).


def rows(text: str) -> list[list[str]]:
    """Parse a pipe-separated text table; two-space-indented lines continue the record above."""
    records: list[str] = []
    for line in text.strip("\n").splitlines():
        if line.startswith("  ") and records:
            records[-1] += " " + line.strip()
        elif line.strip():
            records.append(line.strip())
    return [[f.strip() for f in r.split(" | ")] for r in records]


PAIRS_TABLE = """
slot color.chart.axis = {color.text.tertiary}: axis tick labels, mode / zone tags (CMP-188 / 189)
  | CR:color.chart.axis | color.surface.canvas | text | E11-D02 D7, CR-2
slot color.chart.axis, the high-contrast 7:1 bar | CR:color.chart.axis | color.surface.canvas |
  hc-text | E11-D02 CR-2; 05 section 5 item 6
rejected for the axis slot: E05 color.axis.text (5.96:1 in high-contrast) | color.axis.text |
  color.surface.canvas | rejected-hc-text | E11-D02 section 11.1; E12-D06 section 8 binds it
  (C-row)
slot color.chart.grid.major = {color.border.default}: major gridlines, decorative by design |
  CR:color.chart.grid.major | color.surface.canvas | decorative | E11-D02 D1, CR-1; 16 section 6
  rule 7
slot color.chart.grid.minor = {color.grid.line}: minor gridlines, decorative; off in high-contrast
  (O-D) | CR:color.chart.grid.minor | color.surface.canvas | decorative | E11-D02 D1, CR-1
slot color.chart.grid.minor, the high-contrast alias alternative {color.surface.canvas} (off
  without an opacity token) | CR:color.chart.grid.minor@hc-alias | color.surface.canvas |
  decorative | ruling 2a; spec section 4
slot color.chart.crosshair = {color.crosshair}: the crosshair lines | CR:color.chart.crosshair |
  color.surface.canvas | non-text | E11-D02 D3, D9, CR-3
slot color.chart.crosshair over a major gridline | CR:color.chart.crosshair | color.border.default
  | non-text | E11-D02 D3
slot color.chart.crosshair over a minor gridline | CR:color.chart.crosshair | color.grid.line |
  non-text | E11-D02 D3
remote crosshair at opacity.muted (a linked chart) | mut70:color.crosshair | color.surface.canvas
  | non-text | E11-D02 D9 (E11-D01 Q3-c)
slot color.chart.watermark = {color.border.default}: the symbol · interval watermark (aria-hidden)
  | CR:color.chart.watermark | color.surface.canvas | decorative | E11-D02 D13, CR-3
slot color.chart.pane.bg.default = {color.surface.canvas} against the chrome rows
  (color.surface.raised) | CR:color.chart.pane.bg.default | color.surface.raised | surface |
  E11-D02 D13, CR-3
slot color.chart.pane.bg.focused = {color.surface.canvas}: identical to .default by design |
  CR:color.chart.pane.bg.focused | CR:color.chart.pane.bg.default | surface | E11-D02 D13
CR: color.chart.replay.border (CR-4's values; the name per ruling 2b): the 4 px replay frame |
  CR:color.chart.replay.border | color.surface.canvas | non-text | E11-D02 D16, CR-4; O-A
CR: color.text.buy on the tooltip overlay (E13 values) | CR:color.text.buy | color.surface.overlay
  | text | E11-D02 CR-5
CR: color.text.sell on the tooltip overlay | CR:color.text.sell | color.surface.overlay | text |
  E11-D02 CR-5
CR: color.text.buy on the canvas | CR:color.text.buy | color.surface.canvas | text | E11-D02 CR-5
CR: color.text.sell on the canvas | CR:color.text.sell | color.surface.canvas | text | E11-D02
  CR-5
series slot up = color.candle.up (data-ink) | color.candle.up | color.surface.canvas | non-text |
  E12-D06 D12
series slot down = color.candle.down | color.candle.down | color.surface.canvas | non-text |
  E12-D06 D12
series slot neutral = color.candle.wick (doji, zero line, gap edges) | color.candle.wick |
  color.surface.canvas | non-text | E12-D06 D12
CVD-safe up = color.cvd.buy (chart-color-modes.mjs remap) | color.cvd.buy | color.surface.canvas |
  non-text | E47-S06
CVD-safe down = color.cvd.sell | color.cvd.sell | color.surface.canvas | non-text | E47-S06
ramp.delta endpoint +1 = color.buy.default | color.buy.default | color.surface.canvas | non-text |
  data-ink-lib.mjs delta.positive
ramp.delta endpoint -1 = color.sell.default | color.sell.default | color.surface.canvas | non-text
  | data-ink-lib.mjs delta.negative
ramp.delta first visible stop +ε = color.heatmap.bid.1 | color.heatmap.bid.1 |
  color.surface.canvas | non-text | data-ink-lib.mjs; exemptions.json
ramp.delta first visible stop -ε = color.heatmap.ask.1 | color.heatmap.ask.1 |
  color.surface.canvas | non-text | data-ink-lib.mjs; exemptions.json
ramp.delta CVD-safe first visible stop +ε = color.cvd.heatmap.bid.1 | color.cvd.heatmap.bid.1 |
  color.surface.canvas | non-text | E47-S06
ramp.delta CVD-safe first visible stop -ε = color.cvd.heatmap.ask.1 | color.cvd.heatmap.ask.1 |
  color.surface.canvas | non-text | E47-S06
ramp.intensity zero stop = color.heatmap.zero (no data; exempted by design) | color.heatmap.zero |
  color.surface.canvas | non-text | exemptions.json
ramp.intensity.bid stop 2 = color.heatmap.bid.2 | color.heatmap.bid.2 | color.surface.canvas |
  non-text | 16 section 2.1; pairs.mjs
ramp.intensity.bid stop 3 = color.heatmap.bid.3 | color.heatmap.bid.3 | color.surface.canvas |
  non-text | 16 section 2.1; pairs.mjs
ramp.intensity.bid stop 4 = color.heatmap.bid.4 | color.heatmap.bid.4 | color.surface.canvas |
  non-text | 16 section 2.1; pairs.mjs
ramp.intensity.bid stop 5 = color.heatmap.bid.5 | color.heatmap.bid.5 | color.surface.canvas |
  non-text | 16 section 2.1; pairs.mjs
ramp.intensity.bid CVD-safe stop 2 = color.cvd.heatmap.bid.2 | color.cvd.heatmap.bid.2 |
  color.surface.canvas | non-text | E47-S06; pairs.mjs
ramp.intensity.bid CVD-safe stop 3 = color.cvd.heatmap.bid.3 | color.cvd.heatmap.bid.3 |
  color.surface.canvas | non-text | E47-S06; pairs.mjs
ramp.intensity.bid CVD-safe stop 4 = color.cvd.heatmap.bid.4 | color.cvd.heatmap.bid.4 |
  color.surface.canvas | non-text | E47-S06; pairs.mjs
ramp.intensity.bid CVD-safe stop 5 = color.cvd.heatmap.bid.5 | color.cvd.heatmap.bid.5 |
  color.surface.canvas | non-text | E47-S06; pairs.mjs
ramp.intensity.ask stop 2 = color.heatmap.ask.2 | color.heatmap.ask.2 | color.surface.canvas |
  non-text | 16 section 2.1; pairs.mjs
ramp.intensity.ask stop 3 = color.heatmap.ask.3 | color.heatmap.ask.3 | color.surface.canvas |
  non-text | 16 section 2.1; pairs.mjs
ramp.intensity.ask stop 4 = color.heatmap.ask.4 | color.heatmap.ask.4 | color.surface.canvas |
  non-text | 16 section 2.1; pairs.mjs
ramp.intensity.ask stop 5 = color.heatmap.ask.5 | color.heatmap.ask.5 | color.surface.canvas |
  non-text | 16 section 2.1; pairs.mjs
ramp.intensity.ask CVD-safe stop 2 = color.cvd.heatmap.ask.2 | color.cvd.heatmap.ask.2 |
  color.surface.canvas | non-text | E47-S06; pairs.mjs
ramp.intensity.ask CVD-safe stop 3 = color.cvd.heatmap.ask.3 | color.cvd.heatmap.ask.3 |
  color.surface.canvas | non-text | E47-S06; pairs.mjs
ramp.intensity.ask CVD-safe stop 4 = color.cvd.heatmap.ask.4 | color.cvd.heatmap.ask.4 |
  color.surface.canvas | non-text | E47-S06; pairs.mjs
ramp.intensity.ask CVD-safe stop 5 = color.cvd.heatmap.ask.5 | color.cvd.heatmap.ask.5 |
  color.surface.canvas | non-text | E47-S06; pairs.mjs
CMP-188 / 189 axis mode tag, zone tag | color.text.tertiary | color.surface.canvas | text |
  E11-D02 D7, D8
CMP-199 legend label, focused pane label; readout values | color.text.primary |
  color.surface.canvas | text | E11-D02 D12
CMP-199 legend value; loading text | color.text.secondary | color.surface.canvas | text | E11-D02
  section 11.1
CMP-199 hidden item label; unfocused pane label | color.text.tertiary | color.surface.canvas |
  text | E11-D02 D12
CMP-188 / 190 crosshair axis pill text | color.text.inverse | color.crosshair | text | E11-D02 D9
CMP-188 last-price pill text on the up fill | color.text.inverse | color.candle.up | text |
  E11-D02 D7
CMP-188 last-price pill text on the down fill | color.text.inverse | color.candle.down | text |
  E11-D02 D7
CMP-188 mark-price pill, lock badge, replay chip, aggregation chip text (neutral pill) |
  color.text.primary | color.surface.raised | text | E11-D02 D7, D16
CMP-188 mark-price line (short-dashed, meaning-carrying) | color.text.tertiary |
  color.surface.canvas | non-text | E11-D02 D7
CMP-189 session / day boundary line (dashed); splitter grip | color.text.tertiary |
  color.surface.canvas | non-text | E11-D02 D1, D8, D14
CMP-189 maintenance band edges = pattern.hatch.gap edges (dashed) | color.text.tertiary |
  color.surface.canvas | non-text | E11-D02 D8, CR-6
pattern.hatch.gap texture (color.border.strong), decorative | color.border.strong |
  color.surface.canvas | decorative | E11-D02 D8, CR-6
pattern.hatch.absent ink (the broken zone) | color.text.tertiary | color.surface.canvas | non-text
  | E25-D05 CR-1, C14
rejected as meaning-carrying hatch ink: color.border.strong | color.border.strong |
  color.surface.canvas | rejected-non-text | E25-D05 C14
pattern.outline.imbalance: 1.5 px solid color.footprint.imbalance | color.footprint.imbalance |
  color.surface.canvas | non-text | E06-D01 section 3
E12-D06 D8 data-gap band lines (color.border.default), decorative — the third gap geometry |
  color.border.default | color.surface.canvas | decorative | E12-D06 section 6
E12-D06 D8 data-gap band edges (color.candle.wick, dashed 3 / 3) | color.candle.wick |
  color.surface.canvas | non-text | E12-D06 section 6
CMP-189 go-to-date marker (dashed color.action.primary.default); CMP-199 pane focus bar |
  color.action.primary.default | color.surface.canvas | non-text | E11-D02 D8, D14
CMP-189 cluster pressed auto: text and check glyph | color.text.primary | color.surface.selected |
  text | E11-D02 D8
CMP-189 Paused at hh:mm pill text; CMP-226 warn text | color.text.primary |
  color.status.warning.subtle | text | E11-D02 D8, D11
CMP-189 Paused pill glyph; CMP-226 warn glyph | color.status.warning.strong |
  color.status.warning.subtle | non-text | E11-D02 D8, D11
CMP-197 tooltip title / values | color.text.primary | color.surface.overlay | text | E11-D02 D10
CMP-197 tooltip field labels | color.text.secondary | color.surface.overlay | text | E11-D02 D10
CMP-197 rejected: coloured up value | color.candle.up | color.surface.overlay | rejected-text |
  E11-D02 D10
CMP-197 rejected: coloured down value | color.candle.down | color.surface.overlay | rejected-text
  | E11-D02 D10
CMP-226 countdown normal (status row, raised) | color.text.secondary | color.surface.raised | text
  | E11-D02 D11
CMP-226 rejected: warning.strong as text | color.status.warning.strong | color.surface.raised |
  rejected-text | E11-D02 D11
CMP-226 closed / n/a text | color.text.tertiary | color.surface.raised | text | E11-D02 D11
CMP-039 ring on the canvas (today's tokens: hc = palette.white since #3896) | color.focus.ring |
  color.surface.canvas | non-text | E11-D02 section 11.1 (hc 7.05 pre-#3896); E06-D03 D10
CMP-039 ring on raised chrome | color.focus.ring | color.surface.raised | non-text | E11-D02
  section 11.1
CMP-180 corner badge text (Reduced detail — …) | color.text.primary | color.surface.raised | text
  | E11-D02 D16
CMP-180 corner badge glyph | color.status.warning.strong | color.surface.raised | non-text |
  E11-D02 D16
stale dim x 0.85: candle up | dim85:color.candle.up | color.surface.canvas | non-text | E11-D02
  D16; E11-D06 D13
stale dim x 0.85: candle down | dim85:color.candle.down | color.surface.canvas | non-text |
  E11-D02 D16
stale dim x 0.85: wick | dim85:color.candle.wick | color.surface.canvas | non-text | E11-D02 D16
stale dim x 0.85: imbalance outline | dim85:color.footprint.imbalance | color.surface.canvas |
  non-text | E11-D02 D16
"""
Pair = tuple[str, str, str, str, str]
PAIRS: list[Pair] = [(r[0], r[1], r[2], r[3], r[4]) for r in rows(PAIRS_TABLE)]

# CVD: pairs that must stay apart without their text (ΔE76 under each deficiency, JND 5.0).
CVD_PAIRS: list[tuple[str, str, str]] = [
    ("series up vs down", "color.candle.up", "color.candle.down"),
    ("CVD-safe up vs down", "color.cvd.buy", "color.cvd.sell"),
    ("replay border vs focus ring", "CR:color.chart.replay.border", "color.focus.ring"),
    ("replay border vs env DEMO", "CR:color.chart.replay.border", "color.env.demo"),
    ("pane focus accent vs focus ring", "color.action.primary.default", "color.focus.ring"),
    ("countdown warn glyph vs normal text", "color.status.warning.strong", "color.text.secondary"),
    ("text.buy vs text.sell (CR-5)", "CR:color.text.buy", "CR:color.text.sell"),
]


# ------------------------------------------------------------- density (spec section 6; E11-D02 D6)
DENSITY: dict[str, dict[str, int | str]] = {
    "comfortable": {
        "cellPadPx": 4,
        "fontSizeClass": 1,
        "fontSizeToken": "type.num.sm",
        "fontPx": 11,
        "axisFontSizeClass": 2,
        "axisFontToken": "type.num.base",
        "axisFontPx": 13,
        "lodBias": 1,
        "lodL0": 13,
        "lodL1": 11,
        "lodL2": 7,
        "gTime": 96,
        "gPrice": 48,
        "spacingToken": "space.3",
        "spacingPx": 12,
        "legendRow": 32,
        "uiDensity": "comfortable",
    },
    "compact": {
        "cellPadPx": 2,
        "fontSizeClass": 0,
        "fontSizeToken": "type.num.xs",
        "fontPx": 10,
        "axisFontSizeClass": 1,
        "axisFontToken": "type.num.sm",
        "axisFontPx": 11,
        "lodBias": 0,
        "lodL0": 12,
        "lodL1": 10,
        "lodL2": 6,
        "gTime": 80,
        "gPrice": 40,
        "spacingToken": "space.2",
        "spacingPx": 8,
        "legendRow": 24,
        "uiDensity": "compact",
    },
    "dense": {
        "cellPadPx": 1,
        "fontSizeClass": 0,
        "fontSizeToken": "type.num.xs",
        "fontPx": 10,
        "axisFontSizeClass": 0,
        "axisFontToken": "type.num.xs",
        "axisFontPx": 10,
        "lodBias": 0,
        "lodL0": 12,
        "lodL1": 10,
        "lodL2": 6,
        "gTime": 64,
        "gPrice": 32,
        "spacingToken": "space.1",
        "spacingPx": 4,
        "legendRow": 24,
        "uiDensity": "compact (per-panel override)",
    },
}
LOD_PROFILE_M0 = {"L0": 12, "L1": 10, "L2": 6}  # px; frozen, E06-D01 section 2

# ---------------------------------------------------------------- the registry (spec section 7) ---
Reg = dict[str, str]
REG_KEYS = ("id", "geometry", "ink", "opacity", "meaning", "consumers", "mirror", "cost", "source")
REGISTRY_TABLE = """
pattern.hatch.estimated | 45°, 2 px pitch | none of its own: over the present fill | 30 % |
  estimated | CMP-109 / CMP-182 cells; heatmap columns in resync (E17-D01 draws them at 40 %,
  C-row); CMP-227 marker | " (estimated)" appended | +1 draw per pane while visible (E11-D02 D19)
  | E06-D01 section 3 (frozen); E25-D05 CR-1; 26 section 5 rule 4
pattern.dashed.estimated | 1 px dashed 4 / 3 | the mark's own hue | 1.0 | estimated, at the series
  level | estimated series lines; the CMP-227 marker outline; a regime line at low confidence | "
  (estimated)" | 0 passes: a dash-pattern LUT stroke (26 section 3.10) | E25-D05 CR-1; 16 section
  6 rule 5
pattern.hatch.gap | 45°, 1 px lines, 6 px pitch; dashed 4 / 4 edges | lines color.border.strong
  (texture, decorative); edges color.text.tertiary | 1.0 | gap: absent coverage (maintenance
  window; 26 section 10 coverage gap) | CMP-189 maintenance band; replay coverage gaps (E26);
  recorder gaps (E16) | "exchange maintenance" / "no recorded data" in the readout and the label |
  +1 draw per pane while a window is in view | E11-D02 D8, CR-6
pattern.hatch.absent | pattern.hatch.gap's geometry: 45°, 1 px, 6 px pitch | color.text.tertiary
  (meaning-carrying) | 1.0 | absent / broken: a status | CMP-132 broken zone | the status word
  "broken" | +1 draw per pane while visible | E25-D05 CR-1, C14
pattern.dashed.tested | 1 px dashed 4 / 3 | the side hue at opacity.muted over the .subtle fill |
  0.7 | tested: a status, never a side | CMP-132 tested zone | the status word "tested" | 0 passes
  | E25-D05 CR-1, C17
pattern.outline.imbalance | 1.5 px solid border, squared corners | color.footprint.imbalance |
  1.0, independent of the fill | imbalance: a binary flag | CMP-109 / CMP-182 cells (26 section 4
  cell outline variants) | "Bid-stacked" / "Ask-stacked" | shared with the cell draw (26 section
  4) | E06-D01 section 3; the id is PROPOSED
glyph.notch.delta | 1 px triangular corner notch in the cell quad: up-right positive, down-left
  negative | the cell's delta colour | 1.0 | delta sign at L2, when text hides | CMP-109 / CMP-182
  at L2 | the signed delta | 0: baked into the quad geometry | E06-D01 section 3; the id is
  PROPOSED
indicator.reduced-detail | text, not a pattern | color.text.primary on color.surface.raised; glyph
  color.status.warning.strong | 1.0 | degraded detail: LOD tier, the 06 section 4.4 ladder, the
  render profile | CMP-180 corner badge; the cursor announcement; the aggregation chip |
  "footprint at low detail"; the badge words; "Aggregated — N bars per column" | DOM | E11-D02
  D16; 26 section 12; 06 section 4.4; E11-D01 D6
"""
REGISTRY: list[Reg] = [dict(zip(REG_KEYS, r, strict=True)) for r in rows(REGISTRY_TABLE)]
DASHES: list[tuple[str, str, str]] = [
    (
        "dash.4-4",
        "crosshair, session / day boundary, remote crosshair, pattern.hatch.gap edges",
        "E11-D02 D3, D8, D9",
    ),
    ("dash.2-6", "mark-price line", "E11-D02 D7"),
    ("dash.2-2", "forming-bar ring", "E12-D06 D5"),
    ("dash.4-3", "pattern.dashed.estimated, pattern.dashed.tested", "E25-D05 CR-1"),
    (
        "dash.3-3",
        "E12-D06 D8 data-gap edges (PROPOSED to adopt dash.4-4 with pattern.hatch.gap)",
        "E12-D06 D8",
    ),
]
ENCODING_ROWS: dict[str, dict[str, list[str]]] = {
    "estimated": {
        "CMP-227 chip": ["text", "glyph"],
        "chart marks": ["pattern", "text"],
        "footprint cells": ["pattern", "text"],
        "heatmap columns": ["pattern", "text"],
        "table cells": ["text"],
        "estimated series": ["pattern", "text"],
    },
    "gap": {"chart panes": ["pattern", "text"], "time axis": ["text"]},
    "reduced-detail": {
        "chart corner badge": ["text", "glyph"],
        "cursor announcement": ["text"],
        "aggregation chip": ["text"],
    },
}

# ---------------------------------------------------------------- stories (spec section 9) --------
STORIES: dict[str, list[str]] = {
    "ChartEngine/ChartRoot": [
        "EmptyChart",
        "SinglePane",
        "MultiPane",
        "ThemeSwitchDemo",
        "DensityComfortable",
        "DensityCompact",
        "DensityDense",
        "HighContrast",
        "ReducedMotion",
        "DegradedTwoD",
        "ContextLostRecovery",
        "SyncAnnouncement",
    ],
    "ChartEngine/PriceAxis": [
        "Linear",
        "Log",
        "Dragging (keyboard demo)",
        "Percent",
        "Inverted",
        "Locked",
        "TwoGutters",
        "LastPricePillUp",
        "LastPricePillDown",
        "MarkPill",
        "HighContrast",
        "Dense",
    ],
    "ChartEngine/TimeAxis": [
        "Default",
        "ZoomedIn",
        "ZoomedOut",
        "Decimation0_5PxPerBar",
        "Decimation3PxPerBar",
        "Decimation12PxPerBar",
        "Decimation50PxPerBar",
        "SessionBoundary",
        "MaintenanceBand",
        "ClusterLive",
        "ClusterPaused",
        "LoadingBand",
        "GoToDateMarker",
        "Replay",
        "HighContrast",
    ],
    "ChartEngine/Crosshair": [
        "Default",
        "SyncedAcrossPanes",
        "KeyboardDriven",
        "MagnetOn",
        "RemoteCrosshair",
        "CoincidentGridline",
        "HiddenDuringDrag",
        "KeyboardCursorColumn",
    ],
    "ChartEngine/ChartTooltip": [
        "OhlcvTooltip",
        "FootprintCellTooltip",
        "IndicatorTooltip",
        "FlipLeft",
        "FlipAbove",
        "ClearOfLastPrice",
        "Docked",
        "OverflowTwelveRows",
        "HighContrast",
    ],
    "ChartEngine/Watermark": [
        "Default",
        "HiddenBelow120px",
        "Replay",
        "Dense40px",
        "FocusDoesNotChangeFill",
    ],
    "ChartEngine/ChartLegend": [
        "Default",
        "ManyIndicators",
        "AllHidden",
        "PlusNMore",
        "PopoverOpen",
        "OneHidden",
        "Collapsed",
        "PaneLabelRowFocused",
        "Comfortable",
        "Compact",
        "Dense",
    ],
    "Atoms/BarCountdown": [
        "Normal",
        "Warning",
        "Closed",
        "NonTimeBar",
        "Comfortable",
        "HighContrast",
        "ReducedMotionIdentical",
    ],
}
FOCUS_RING_STORIES = [
    "RingOnButton",
    "RingOnCustomSurrogate",
    "RingOnCanvasData",
]  # CMP-039 (E05's atom)
ENTRIES = (
    "CMP-180",
    "CMP-188",
    "CMP-189",
    "CMP-190",
    "CMP-196",
    "CMP-197",
    "CMP-198",
    "CMP-199",
    "CMP-226",
)

# -------------------------------------------------------------- token bindings (spec sections 4, 8)
BOUND: list[tuple[str, str]] = [  # (name, where it is bound)
    ("color.chart.axis", "slot; CMP-188 / 189"),
    ("color.chart.grid.major", "slot; CMP-180"),
    ("color.chart.grid.minor", "slot; CMP-180"),
    ("color.chart.crosshair", "slot; CMP-190"),
    ("color.chart.watermark", "slot; CMP-198"),
    ("color.chart.pane.bg.default", "slot; CMP-180 / 198"),
    ("color.chart.pane.bg.focused", "slot; CMP-180 / 198"),
    ("color.chart.replay.border", "CR-4; CMP-180 / 189"),
    ("color.chart.background", "15 CMP-180 before this PR (drift)"),
    ("color.chart.grid", "15 CMP-180 before (drift)"),
    ("font.mono", "15 x33 before (drift; the token is font.family.mono)"),
    ("color.text.muted", "15 CMP-226 before (drift)"),
    ("color.status.warn", "15 CMP-226 before (drift)"),
    ("color.marker.*", "15 CMP-195 (drift; not this ticket's entry)"),
    ("elevation.3", "15 CMP-197 before (a primitive)"),
    ("color.text.tertiary", "axis labels, tags, boundary, grip"),
    ("color.text.secondary", "CMP-226 normal; legend values"),
    ("color.text.primary", "legend, tooltip, pills, badges"),
    ("color.text.inverse", "crosshair and last-price pill text"),
    ("color.border.default", "major grid, watermark, axis rule, splitter hairline"),
    ("color.border.strong", "pattern.hatch.gap texture; neutral pill border"),
    ("color.surface.canvas", "pane fill"),
    ("color.surface.raised", "chrome rows, neutral pills"),
    ("color.surface.overlay", "CMP-197 fill"),
    ("color.surface.selected", "cluster pressed fill"),
    ("color.surface.hover", "loading band"),
    ("color.crosshair", "CMP-190 lines and pills"),
    ("color.grid.line", "minor grid"),
    ("color.axis.text", "E05 token; alias or retire (CR-2)"),
    ("color.candle.up", "series slot up"),
    ("color.candle.down", "series slot down"),
    ("color.candle.wick", "series slot neutral"),
    ("color.footprint.imbalance", "pattern.outline.imbalance"),
    ("color.focus.ring", "CMP-039 ring, cursor column"),
    ("color.action.primary.default", "pane focus bar, go-to-date marker"),
    ("color.status.warning.subtle", "CMP-226 warn fill; Paused pill"),
    ("color.status.warning.strong", "warn glyphs"),
    ("color.buy.default", "ramp.delta +1"),
    ("color.sell.default", "ramp.delta -1"),
    ("color.heatmap.zero", "ramp.intensity zero"),
    ("color.heatmap.bid.1", "ramp.delta +ε"),
    ("color.heatmap.ask.1", "ramp.delta -ε"),
    ("color.cvd.buy", "CVD-safe +1"),
    ("color.cvd.sell", "CVD-safe -1"),
    ("color.cvd.heatmap.bid.1", "CVD-safe +ε"),
    ("color.cvd.heatmap.ask.1", "CVD-safe -ε"),
    ("color.env.demo", "env badge border (E30-D01)"),
    ("type.num.xs", "class 0"),
    ("type.num.sm", "class 1"),
    ("type.num.base", "class 2"),
    ("type.ui.caption", "mode tag, tooltip title"),
    ("type.ui.label", "legend label"),
    ("type.ui.body", "comfortable legend"),
    ("font.family.mono", "every number"),
    ("font.family.ui", "watermark"),
    ("font.weight.semibold", "watermark"),
    ("font.weight.medium", "CMP-226 warn"),
    ("elevation.popover", "CMP-197 shadow; legend popover"),
    ("radius.card", "CMP-197"),
    ("radius.xs", "axis pills"),
    ("radius.pill", "splitter grip"),
    ("space.inset.xs", "dense inset"),
    ("space.inset.sm", "compact inset"),
    ("space.inset.md", "comfortable inset"),
    ("space.1", "dense spacing step"),
    ("space.2", "compact spacing step"),
    ("space.3", "comfortable spacing step"),
    ("size.control.compact", "24 px rows"),
    ("size.control.comfortable", "32 px rows"),
    ("size.target.min", "24 px floor"),
    ("opacity.muted", "remote crosshair; pattern.dashed.tested"),
    ("opacity.scrim", "replay future dim"),
    ("border.focus", "ring width 2"),
    ("motion.duration.fast", "tooltip fade (E11-D06)"),
    ("motion.duration.normal", "stale dim (E11-D06 D13)"),
]


# ---------------------------------------------------------------- registries on disk --------------
def base_name(token: str) -> str:
    """The name a registry would list: a `CR:` alias → its dark alias; a composite → its base."""
    if token in CR:
        return CR[token]["dark"]
    for prefix in ("dim85:", "mut70:"):
        if token.startswith(prefix):
            return token[len(prefix) :]
    return token


def registered_pairs() -> set[tuple[str, str]]:
    text = PAIRS_MJS.read_text(encoding="utf-8")
    return set(re.findall(r'fg:\s*"([^"]+)",\s*bg:\s*"([^"]+)"', text))


def exempted_pairs() -> set[str]:
    data = json.loads(EXEMPTIONS.read_text(encoding="utf-8"))
    items = data["exemptions"] if isinstance(data, dict) else data
    return {str(e["pair"]) if "pair" in e else "token:" + str(e["token"]) for e in items}


def encodings_rows() -> dict[str, bool]:
    data = json.loads(ENCODINGS.read_text(encoding="utf-8"))
    enc = data.get("encodings", {})
    return {k: k in enc for k in ("estimated", "gap", "reduced-detail", "imbalance")}


class PairRow(TypedDict):
    element: str
    fg: str
    bg: str
    role: str
    source: str
    ratios: dict[str, float]
    hexes: dict[str, list[str]]
    verdict: str
    gated: bool
    registered: bool
    exempted: list[str]
    failing: list[str]


def measure(reg: set[tuple[str, str]], exempt: set[str]) -> list[PairRow]:
    rows: list[PairRow] = []
    for element, fg, bg, role, source in PAIRS:
        ratios = {t: ratio(col(t, fg), col(t, bg)) for t in THEMES}
        hexes = {t: [col(t, fg), col(t, bg)] for t in THEMES}
        bar = BAR[role]
        key = (base_name(fg), base_name(bg))
        ex = [t for t in THEMES if f"{t}:{key[0]} on {key[1]}" in exempt]
        if bar is None:
            verdict = (
                "decorative (reported, not gated)" if role == "decorative" else "surface (reported)"
            )
            bad: list[str] = []
        else:
            themes = ("high-contrast",) if role.endswith("hc-text") else THEMES
            bad = [t for t in themes if ratios[t] < bar]
            if role.startswith("rejected"):
                verdict = (
                    ("rejected: fails " + ", ".join(bad)) if bad else "rejected: passes, not used"
                )
            elif bad and all(t in ex for t in bad):
                verdict = "exempted (recorded debt, not gated): below the bar in " + ", ".join(bad)
            elif bad:
                verdict = "FAIL: " + ", ".join(bad)
            else:
                verdict = "PASS"
        failing = [t for t in bad if role in GATED and t not in ex]
        rows.append(
            {
                "element": element,
                "fg": fg,
                "bg": bg,
                "role": role,
                "source": source,
                "ratios": ratios,
                "hexes": hexes,
                "verdict": verdict,
                "gated": role in GATED and not (bad and all(t in ex for t in bad)),
                "registered": key in reg or (key[1], key[0]) in reg,
                "exempted": ex,
                "failing": failing,
            }
        )
    return rows


class TokenRow(TypedDict):
    name: str
    where: str
    values: dict[str, str]
    status: str


def bindings() -> list[TokenRow]:
    out: list[TokenRow] = []
    for name, where in BOUND:
        values: dict[str, str] = {}
        for t in THEMES:
            v = T[t].get(name)
            values[t] = "MISSING" if v is None else json.dumps(v, separators=(",", ":"))[:48]
        missing = all(v == "MISSING" for v in values.values())
        status = "MISSING" if missing else "resolves"
        if name == "elevation.3":
            status = "resolves as a primitive; the semantic alias is elevation.popover"
        if name == "color.axis.text":
            status = "resolves; CR-2: alias of color.text.tertiary or retired (E05 owner)"
        out.append({"name": name, "where": where, "values": values, "status": status})
    return out


def cvd_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for name, a, b in CVD_PAIRS:
        for t in THEMES:
            ha, hb = col(t, a), col(t, b)
            d = {"normal": de76(ha, hb)}
            for k in DEFICIENCIES:
                d[k] = de76(sim(ha, k), sim(hb, k))
            worst = min(d[k] for k in DEFICIENCIES)
            rows.append(
                {
                    "pair": name,
                    "theme": t,
                    **d,
                    "worst": worst,
                    "verdict": (
                        "distinct" if worst >= JND else "COLLAPSES (text / shape carries it)"
                    ),
                }
            )
    return rows


def ramp_report(n: int) -> dict[str, object]:
    out: dict[str, object] = {}
    for ramp, palettes in RAMPS.items():
        for palette in palettes:
            for t in THEMES:
                samples = sample_ramp(t, ramp, palette, n)
                ok_hexes = [s["oklab_hex"] for s in samples]
                s_hexes = [s["srgb_hex"] for s in samples]
                visible = [s for s in samples if s["gated"]]
                # evenness over the visible segments only: a step that crosses the zero band is a
                # jump into no ink by design and would dominate the whole-ramp number
                vis_ok = [
                    de76(a["oklab_hex"], b["oklab_hex"])
                    for a, b in pairwise(samples)
                    if a["gated"] and b["gated"] and (a["t"] * b["t"] > 0 or a["t"] == 0)
                ]
                vis_s = [
                    de76(a["srgb_hex"], b["srgb_hex"])
                    for a, b in pairwise(samples)
                    if a["gated"] and b["gated"] and (a["t"] * b["t"] > 0 or a["t"] == 0)
                ]
                out[f"{ramp}|{palette}|{t}"] = {
                    "stops": [[tok, pos] for tok, pos in palettes[palette]],
                    "stop_oklab": {
                        tok: list(hex_to_oklab(COLOURS[t][tok])) for tok, _ in palettes[palette]
                    },
                    "samples": samples,
                    "oklab_steps": adjacent_steps(ok_hexes),
                    "srgb_steps": adjacent_steps(s_hexes),
                    "oklab_evenness": evenness(adjacent_steps(ok_hexes)),
                    "srgb_evenness": evenness(adjacent_steps(s_hexes)),
                    "oklab_evenness_visible": evenness(vis_ok),
                    "srgb_evenness_visible": evenness(vis_s),
                    "oklab_steps_visible": vis_ok,
                    "srgb_steps_visible": vis_s,
                    "oklab_min_chroma": min(s["oklab_chroma"] for s in samples),
                    "srgb_min_chroma": min(s["srgb_chroma"] for s in samples),
                    "visible_min_contrast_oklab": min(
                        (s["contrast_oklab"] for s in visible), default=0.0
                    ),
                    "visible_min_contrast_srgb": min(
                        (s["contrast_srgb"] for s in visible), default=0.0
                    ),
                    "visible_below_3_oklab": sum(1 for s in visible if s["contrast_oklab"] < 3.0),
                    "visible_below_3_srgb": sum(1 for s in visible if s["contrast_srgb"] < 3.0),
                    "stop_cvd": stop_cvd(t, ramp, palette),
                    "unanchored": unanchored(t, palette, n) if ramp == "ramp.delta" else None,
                }
    return out


def counts(pairs: list[PairRow], tokens: list[TokenRow], n: int) -> dict[str, int]:
    gated = [p for p in pairs if p["gated"]]
    distinct = {(p["fg"], p["bg"]) for p in gated}
    missing = [t for t in tokens if t["status"] == "MISSING"]
    return {
        "slots": 7,
        "slotRows": sum(1 for p in pairs if p["element"].startswith("slot ")),
        "seriesSlots": 3,
        "rampEndpoints": 5,
        "ramps": len(RAMPS),
        "palettes": 2,
        "themes": 3,
        "densities": 3,
        "stops": n,
        "samples": n * len(RAMPS) * 2 * 3,
        "registryIds": len(REGISTRY),
        "dashIds": len(DASHES),
        "encodingRows": len(ENCODING_ROWS),
        "entries": len(ENTRIES),
        "storyGroups": len(STORIES),
        "storiesTotal": sum(len(v) for v in STORIES.values()),
        "focusRingStories": len(FOCUS_RING_STORIES),
        "pairsRows": len(pairs),
        "pairsGated": len(gated),
        "pairsDistinct": len(distinct),
        "pairsRegistered": sum(1 for p in gated if p["registered"]),
        "pairsProposed": len({(p["fg"], p["bg"]) for p in gated if not p["registered"]}),
        "pairsExempted": sum(1 for p in pairs if p["exempted"]),
        "pairsDecorative": sum(1 for p in pairs if p["role"] in ("decorative", "surface")),
        "pairsRejected": sum(1 for p in pairs if p["role"].startswith("rejected")),
        "pairsFailing": sum(1 for p in pairs if p["failing"]),
        "tokensBound": len(tokens) - len(missing),
        "tokensMissing": len(missing),
        "crRows": 9,
        "lodL0": LOD_PROFILE_M0["L0"],
        "lodL1": LOD_PROFILE_M0["L1"],
        "lodL2": LOD_PROFILE_M0["L2"],
        "hitTargetPx": 24,
        "ringPx": 2,
        "ringOffsetPx": 2,
        "haloPx": 1,
        "lutEntries": 256,
    }


def print_pairs(pairs: list[PairRow]) -> None:
    print("## A. Slot and chassis pairs (ratio per theme; bar per role; unrounded compare)\n")
    print("| Element | fg | bg | role | dark | light | hc | verdict | pairs.mjs | source |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for p in pairs:
        r = p["ratios"]
        reg = "registered" if p["registered"] else ("PROPOSED" if p["gated"] else "—")
        cells = [
            p["element"],
            f"`{p['fg']}`",
            f"`{p['bg']}`",
            p["role"],
            fmt(r["dark"]),
            fmt(r["light"]),
            fmt(r["high-contrast"]),
            p["verdict"],
            reg,
            p["source"],
        ]
        print("| " + " | ".join(cells) + " |")
    print("\n## B. Resolved values (dark / light / hc)\n")
    print("| token | dark | light | hc |")
    print("|---|---|---|---|")
    seen: list[str] = []
    for p in pairs:
        for tok in (p["fg"], p["bg"]):
            if tok not in seen:
                seen.append(tok)
                hexes = [col(t, tok) for t in THEMES]
                print(f"| `{tok}` | {hexes[0]} | {hexes[1]} | {hexes[2]} |")


def print_ramps(ramps: dict[str, object], n: int) -> None:
    for key, rep in ramps.items():
        if not isinstance(rep, dict):
            continue
        ramp, palette, theme = key.split("|")
        print(
            f"\n## D. {ramp} · {palette} palette · {theme} ({n} samples; OkLab beside the "
            "sRGB lerp)\n"
        )
        print(
            "| i | t | OkLab hex | L | a | b | C | on canvas | sRGB hex | L | a | b | C "
            "| on canvas | band |"
        )
        print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for i, s in enumerate(rep["samples"]):
            lab, slab = s["oklab"], s["srgb_lab"]
            band = "visible" if s["gated"] else "zero band (no ink)"
            cells = [
                str(i),
                f"{s['t']:+.3f}",
                s["oklab_hex"],
                f"{lab[0]:.4f}",
                f"{lab[1]:+.4f}",
                f"{lab[2]:+.4f}",
                f"{s['oklab_chroma']:.4f}",
                f"{s['contrast_oklab']:.2f}",
                s["srgb_hex"],
                f"{slab[0]:.4f}",
                f"{slab[1]:+.4f}",
                f"{slab[2]:+.4f}",
                f"{s['srgb_chroma']:.4f}",
                f"{s['contrast_srgb']:.2f}",
                band,
            ]
            print("| " + " | ".join(cells) + " |")
        ok_s, s_s = rep["oklab_steps"], rep["srgb_steps"]
        print(
            f"\nadjacent-sample ΔE76 — OkLab min / max / evenness: {min(ok_s):.2f} / "
            f"{max(ok_s):.2f} / "
            f"{rep['oklab_evenness']:.2f}; sRGB lerp: {min(s_s):.2f} / {max(s_s):.2f} / "
            f"{rep['srgb_evenness']:.2f}; over the visible segments only — OkLab "
            f"{rep['oklab_evenness_visible']:.2f}, sRGB {rep['srgb_evenness_visible']:.2f}; "
            f"visible samples below 3:1 — OkLab "
            f"{rep['visible_below_3_oklab']}, sRGB {rep['visible_below_3_srgb']}; min chroma — "
            f"OkLab {rep['oklab_min_chroma']:.4f}, sRGB {rep['srgb_min_chroma']:.4f}"
        )
        print("\n| stops | normal | protan | deutan | tritan | worst | verdict (JND 5.0) |")
        print("|---|---|---|---|---|---|---|")
        for row in rep["stop_cvd"]:
            vals = [f"{float(row[k]):.1f}" for k in ("normal", *DEFICIENCIES, "worst")]
            print(f"| {row['a']} vs {row['b']} | " + " | ".join(vals) + f" | {row['verdict']} |")
        un = rep["unanchored"]
        if isinstance(un, dict):
            print(
                f"\nrejected two-endpoint lerp {un['endpoints'][0]} → {un['endpoints'][1]} "
                f"(no zero stop): mid-sample sRGB {un['srgb_mid_hex']} chroma "
                f"{un['srgb_mid_chroma']:.4f} hue "
                f"{un['srgb_mid_hue']:.0f}°; OkLab {un['oklab_mid_hex']} chroma "
                f"{un['oklab_mid_chroma']:.4f} hue {un['oklab_mid_hue']:.0f}°; endpoint chroma "
                f"{un['endpoint_chroma'][0]:.4f} / {un['endpoint_chroma'][1]:.4f}; evenness sRGB "
                f"{un['srgb_evenness']:.2f} vs OkLab {un['oklab_evenness']:.2f}"
            )


def print_rest(tokens: list[TokenRow], enc: dict[str, bool], nums: dict[str, int]) -> None:
    print("\n## E. CVD pairs (ΔE76 under each deficiency; JND 5.0)\n")
    print("| pair | theme | normal | protan | deutan | tritan | verdict |")
    print("|---|---|---|---|---|---|---|")
    for c in cvd_rows():
        vals = [f"{float(str(c[k])):.1f}" for k in ("normal", *DEFICIENCIES)]
        print(f"| {c['pair']} | {c['theme']} | " + " | ".join(vals) + f" | {c['verdict']} |")
    print("\n## F. The density record (E11-D02 D6, cited whole)\n")
    print(
        "| mode | cellPadPx | fontSizeClass | axisFontSizeClass | lodBias | L0 / L1 / L2 px | "
        "G time / price | spacing | legend row | UI density |"
    )
    print("|---|---|---|---|---|---|---|---|---|---|")
    for mode, d in DENSITY.items():
        cells = [
            mode,
            str(d["cellPadPx"]),
            f"{d['fontSizeClass']} ({d['fontSizeToken']} {d['fontPx']} px)",
            f"{d['axisFontSizeClass']} ({d['axisFontToken']} {d['axisFontPx']} px)",
            f"+{d['lodBias']}",
            f"{d['lodL0']} / {d['lodL1']} / {d['lodL2']}",
            f"{d['gTime']} / {d['gPrice']}",
            f"{d['spacingToken']} ({d['spacingPx']})",
            str(d["legendRow"]),
            str(d["uiDensity"]),
        ]
        print("| " + " | ".join(cells) + " |")
    print("\n## G. The pattern / encoding registry\n")
    print("| " + " | ".join(REG_KEYS) + " |")
    print("|" + "---|" * len(REG_KEYS))
    for entry in REGISTRY:
        print("| " + " | ".join(entry[k] for k in REG_KEYS) + " |")
    print(
        "\nline-dash vocabulary (PROPOSED ids): "
        + "; ".join(f"{i} = {u} ({s})" for i, u, s in DASHES)
    )
    print("\nPROPOSED encodings.json rows: " + json.dumps(ENCODING_ROWS, ensure_ascii=False))
    print(f"\nencodings.json today: {enc}")
    print("\n## H. Token bindings (resolved in all three themes, or MISSING)\n")
    print("| token | bound by | dark | light | hc | status |")
    print("|---|---|---|---|---|---|")
    for tk in tokens:
        tv = tk["values"]
        cells = [
            f"`{tk['name']}`",
            tk["where"],
            tv["dark"],
            tv["light"],
            tv["high-contrast"],
            tk["status"],
        ]
        print("| " + " | ".join(cells) + " |")
    print("\n## I. Stories (PROPOSED)\n")
    for group, names in STORIES.items():
        print(f"- {group} ({len(names)}): {', '.join(names)}")
    print(
        f"- Atoms/FocusRing ({len(FOCUS_RING_STORIES)}; CMP-039, E05's atom): "
        + ", ".join(FOCUS_RING_STORIES)
    )
    print("\n## J. Counts\n")
    print(json.dumps(nums, indent=2))


def checks_ok(checks: dict[str, float]) -> bool:
    return (
        abs(checks["white_L"] - 1) < 1e-4
        and checks["black_L"] < 1e-4
        and checks["white_ab"] < 1e-4
        and checks["grey_ab"] < 1e-4
        and checks["round_trip_max_error"] < 1e-6
    )


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    n = int(argv[argv.index("--stops") + 1]) if "--stops" in argv else 16
    pairs = measure(registered_pairs(), exempted_pairs())
    tokens = bindings()
    checks = oklab_self_checks()
    ramps = ramp_report(n)
    enc = encodings_rows()
    nums = counts(pairs, tokens, n)
    ok = checks_ok(checks)
    if "--json" in argv:
        out = {
            "counts": nums,
            "pairs": pairs,
            "tokens": tokens,
            "oklab_checks": checks,
            "oklab_checks_ok": ok,
            "ramps": ramps,
            "cvd": cvd_rows(),
            "density": DENSITY,
            "registry": REGISTRY,
            "dashes": DASHES,
            "encoding_rows": ENCODING_ROWS,
            "encodings_today": enc,
            "stories": STORIES,
            "focus_ring_stories": FOCUS_RING_STORIES,
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        print_pairs(pairs)
        print("\n## C. OkLab self-checks (Ottosson 2020 matrices; tolerances 1e-4 and 1e-6)\n")
        for name, value in checks.items():
            print(f"- {name}: {value:.3e}")
        print(f"- all self-checks within tolerance: {ok}")
        print_ramps(ramps, n)
        print_rest(tokens, enc, nums)
        failing = nums["pairsFailing"]
        print(
            f"\n{'OK' if not failing and ok else 'FAIL'}: {nums['pairsGated']} gated rows over 3 "
            f"themes, {failing} failing; OkLab self-checks {'pass' if ok else 'FAIL'}; "
            f"{nums['tokensMissing']} names MISSING (expected drift and slots)"
        )
    return 0 if failing_count(nums) == 0 and ok else 1


def failing_count(nums: dict[str, int]) -> int:
    return nums["pairsFailing"]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
