"""E13-D03 indicator hi-fi audit: the palette search, the band-fill alpha, the measured matrix,
the token bindings, the catalogue facts, the draw-call arithmetic and the string gates.

Standalone, offline, stdlib only:
    python3 -I docs/design/_tools/e13_d03_palette_audit.py [--json] [--draft <pr-draft.md>]
Themes resolve exactly as `packages/ui/tokens/tests/verify_tokens.py` does (same loader, alias
resolution and `themes.json` layering); the contrast formula is `contrast_ratio()` from
`docs/design/_tools/contrast_check.py` and the dichromacy projection is
`docs/research/_tools/cvd_simulate.py` (Brettel / Vienot, CIE76), both imported, never
re-implemented, so the numbers agree with E13-D02's, E11-D05's and E30-D02's to the hundredth.
Nothing else in the repo is executed: `catalogue.py`, `limits.py`, `builtin_indicator_presets.py`,
`pairs.mjs`, `encodings.json`, `json-flat-rgba.js`, `color-math.mjs`, the spec, the handoff file,
the three `14` pointer lines and the optional PR draft are read as text. The reserved set is read
from the semantic token files by prefix (every `color.*` token except the surface tiers), never
hard-coded. Composites are blended in sRGB (the browser's and WebGL's default blend space), with
the fill under the candles and, as `26` section 3.1 layers bands, over them. Exit 1 on a gated
FAIL or a failed string gate; `--json` prints only the counts and numbers the board check-nums
script consumes.
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
DESIGN = ROOT / "docs" / "design"
API = ROOT / "services" / "api" / "candleviewer"
SPEC = DESIGN / "E13" / "E13-D03.md"
HANDOFF = DESIGN / "E13" / "E13-D03-handoff.md"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def find(pattern: str, text: str, flags: int = 0) -> str:
    m = re.search(pattern, text, flags)
    if m is None:
        raise ValueError(f"pattern not found: {pattern}")
    return m[1]


sys.path.insert(0, str(TOKENS / "tests"))
verify = _load(TOKENS / "tests" / "verify_tokens.py", "verify_tokens")
contrast_check = _load(DESIGN / "_tools" / "contrast_check.py", "contrast_check")
cvd = _load(ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py", "cvd_simulate")

THEMES = ("dark", "light", "high-contrast")
CVDS = ("protanopia", "deuteranopia", "tritanopia")
JND = float(find(r"CVD_JND_FLOOR = ([\d.]+)", read(ROOT / "tools/contrast/color-math.mjs")))
BAR = {"text": 4.5, "non-text": 3.0, "hc-text": 7.0}
NOT_GATED = ("decorative", "reported", "pill-text")
DE_FLOOR = (
    8.0  # the CIE76 distance verify_tokens.py enforces between danger and sell (16 section 2.1)
)
TIERS = 6  # the identity ladder's line tiers (spec section 4.1)
CAP = 20  # SR-E13-02: instances per chart
# The eight slots (PROPOSED aliases; no hex is invented): dark alias, light alias; high-contrast
# inherits the dark alias (no semantic-hc line). Chosen by the search below: every alias clears
# 3:1 on the canvas and the dE floor from every reserved token in its theme, and every slot keeps
# the same dE floor from every other slot of its theme (the first k slots always share a pane;
# gated in section 1c); the order alternates hue family and lightness (dark: a light step, a mid
# or dark step, ...; light: a strong dark step first). The pale tints the search also passes read
# as text and are not taken (spec section 3.2).
SLOTS = (
    ("palette.teal.500", "palette.teal.900"),
    ("palette.cyan.600", "palette.blue.400"),
    ("palette.amber.600", "palette.cyan.900"),
    ("palette.purple.600", "palette.purple.500"),
    ("palette.teal.600", "palette.amber.900"),
    ("palette.cvd.light.blue.3", "palette.teal.600"),
    ("palette.purple.400", "palette.purple.900"),
    ("palette.light.amber.300", "palette.cvd.blue.1"),
)
# The reserved set: every semantic colour token in the theme except the surface tiers (direction,
# status, environment, selection, focus, action, text, border, grid and chrome, the heatmap, CVD,
# footprint, profile and node families) - read from the semantic files, never listed by hand.
RESERVED_SKIP = ("color.surface.", "color.indicator.")
# Families a slot never aliases whatever its distance (design rule, spec section 3.2): the buy /
# sell / env / danger hues (16 section 6 rule 8) and the chrome greys (text, wick, border, guide).
EXCLUDED_FAMILIES = (
    "palette.green.",
    "palette.light.green.",
    "palette.red.",
    "palette.light.red.",
    "palette.neutral.",
    "palette.light.neutral.",
    "palette.white",
    "palette.black",
)
# Dichromacy collapses accepted as recorded residuals (spec section 3.5, C-28): (slot, theme,
# projection) -> the non-colour carrier. Any other protan / deutan collapse is a gated FAIL.
RESIDUALS: dict[tuple[int, str, str], str] = {
    (7, "dark", "deuteranopia"): (
        "per token: order.line - a series vs a full-width horizontal line with its DOM pill; "
        "focus.ring - a ring 2 px outside an element, in the chrome; text.link - underlined text "
        "in the chrome; the legend row"
    ),
    (7, "high-contrast", "deuteranopia"): (
        "per token: order.line - a series vs a full-width line with its DOM pill; "
        "action.primary.default - a button fill in the chrome; border.selected - a selected "
        "row's outline in the chrome; text.link - underlined text in the chrome; the legend row"
    ),
    (8, "dark", "protanopia"): (
        "cvd.heatmap.ask.1 - a series stroke vs a CVD-safe heatmap cell (an area); "
        "the legend swatch and label"
    ),
    (8, "high-contrast", "protanopia"): (
        "cvd.heatmap.ask.1 - a series stroke vs a CVD-safe heatmap cell; the legend row"
    ),
}
_SHORT_SRC = (
    "app=color.surface.app canvas=color.surface.canvas raised=color.surface.raised "
    "overlay=color.surface.overlay sunken=color.surface.sunken hover=color.surface.hover "
    "selected=color.surface.selected t1=color.text.primary t2=color.text.secondary "
    "t3=color.text.tertiary tdis=color.text.disabled tinv=color.text.inverse "
    "tonact=color.text.on-action tlink=color.text.link ring=color.focus.ring "
    "bdef=color.border.default bsel=color.border.selected aprim=color.action.primary.default "
    "asel=color.action.selected up=color.candle.up down=color.candle.down wick=color.candle.wick "
    "live=color.env.live demo=color.env.demo cbuy=color.cvd.buy csell=color.cvd.sell "
    "dsub=color.status.danger.subtle dstr=color.status.danger.strong "
    "ddef=color.status.danger.default wsub=color.status.warning.subtle "
    "wstr=color.status.warning.strong isub=color.status.info.subtle idef=color.status.info.default "
    "istr=color.status.info.strong"
)
SHORT = dict(kv.split("=") for kv in _SHORT_SRC.split())
LADDER = ("solid 2 px", "solid 1 px", "solid 3 px", "dash 8-4 2 px", "dash 8-4 1 px", "dash-dot")
RESERVED_DASH = ("dash.4-4", "dash.2-6", "dash.2-2", "dash.4-3", "dash.3-3", "dash.6-6")
BANDS = ("upper", "middle", "lower")
# Per indicator (spec section 5): line series, band fills, histograms, marker series.
KIND: dict[str, tuple[int, int, int, int]] = {
    "ema": (1, 0, 0, 0),
    "bollinger": (3, 1, 0, 0),
    "supertrend": (1, 0, 0, 1),
    "vwap": (1, 0, 0, 0),
    "rsi": (1, 0, 0, 0),
    "stochastic": (2, 0, 0, 0),
    "macd": (2, 0, 1, 0),
    "volume": (0, 0, 1, 0),
    "cvd": (1, 0, 0, 0),
}
# The ten-indicator frame (AC 3): pane, height, instances in add order, the pane's fixed draws
# (26 section 4: grid 2, candles 2, crosshair 1; E11-D02 line 678: one axis / legend / watermark
# text draw per pane; guide levels and the zero line one instanced draw each).
STRESS: tuple[tuple[str, int, tuple[tuple[str, str], ...], str], ...] = (
    (
        "price pane",
        422,
        (
            ("ema", "EMA 21"),
            ("ema", "EMA 50"),
            ("bollinger", "Bollinger 20 x2"),
            ("supertrend", "Supertrend 10 x3"),
            ("vwap", "VWAP session"),
        ),
        "grid 2 candles 2 crosshair 1 text 1",
    ),
    (
        "sub-pane A",
        141,
        (("rsi", "RSI 14"), ("stochastic", "Stochastic 14 1 3")),
        "grid 2 guides 1 crosshair 1 text 1",
    ),
    (
        "sub-pane B",
        141,
        (("macd", "MACD 12 26 9"), ("volume", "Volume"), ("cvd", "CVD session")),
        "grid 2 zero 1 crosshair 1 text 1",
    ),
)
# B5 (26 section 13): the price pane with candles, footprint, heatmap, 3 indicator lines and 50
# order lines; E11-D02 line 678's nominal fully-layered pane counts 18 with <= 1 indicator batch.
B5_FIXED = "grid 2 candles 2 heatmap 2 footprint 2 orders 1 crosshair 1 text 1"
B5_LINES = 3
NOMINAL_PANE = 18
NOMINAL_EXTRA_LINES = 3
PROPOSED_NAMES = re.compile(
    r"^(color\.indicator\.palette\.[1-8n]|opacity\.indicator\.fill|size\.stroke\.(thin|regular|bold)"
    r"|color\.marker\.\*|color\.chip\.\*|font\.mono|color\.border\.control|color\.text\.accent"
    r"|color\.text\.(buy|sell)|color\.chart\.[a-z.]+)$"
)
TOKEN_RE = re.compile(
    r"`((?:color|type|space|radius|elevation|size|opacity|font|border|palette|motion)"
    r"\.[a-z0-9.\-]+(?:\.\*)?)`"
)
# (element, fg, bg, role): fg / bg are SHORT keys, s<n> a slot, f<n> a slot's band fill at alpha.
# A slot's ink appears on color.surface.canvas only - on the plot, and off the plot inside a canvas
# tile (the thumbnail's chart inset, the swatch radio's tile, the shape swatch's tile; spec section
# 2) - so the gated slot pair is the canvas; the overlay / raised ratios around the tile are
# reported.
PAIRS: list[tuple[str, str, str, str]] = [
    ("dialog / drawer / tooltip text", "t1", "overlay", "text"),
    ("dialog text, hc 7:1", "t1", "overlay", "hc-text"),
    ("hints, help lines, the preview caption on the overlay", "t2", "overlay", "text"),
    ("kickers, counts, the swatch's token-name label", "t3", "overlay", "text"),
    ("field borders, selection outline, bulk-bar edge (E13-D02)", "t3", "overlay", "non-text"),
    ("entry names, tree labels, chip / badge / kbd words on raised", "t1", "raised", "text"),
    ("sub-labels, tags and the T2 reason sentence on raised", "t2", "raised", "text"),
    ("T2 disabled control: the full label and the lock glyph on raised", "t3", "raised", "text"),
    ("group header, bulk bar, hovered row text", "t1", "hover", "text"),
    ("selected row / tab text", "t1", "selected", "text"),
    ("hidden tree-row label on a selected row (adopted)", "t2", "selected", "text"),
    (
        "hidden tree-row label on a selected row - REJECTED text.tertiary",
        "t3",
        "selected",
        "rejected-text",
    ),
    ("preview caption on sunken", "t2", "sunken", "text"),
    ("preview axis labels on sunken", "t3", "sunken", "text"),
    ("legend label, pane-header label, marker label (DOM)", "t1", "canvas", "text"),
    ("legend label, hc 7:1", "t1", "canvas", "hc-text"),
    ("legend value, 'computing...', pane-header values", "t2", "canvas", "text"),
    ("hidden row label, frozen stale value, gutter guide value", "t3", "canvas", "text"),
    (
        "a disabled label in text.disabled - REJECTED (E09-D09 T2: never text.disabled)",
        "tdis",
        "raised",
        "rejected-text",
    ),
    ("primary button label (Add, Apply) on action.primary", "tonact", "aprim", "text"),
    ("focus ring on the overlay (fields, swatch radios, buttons)", "ring", "overlay", "non-text"),
    ("focus ring on a raised option / tree row", "ring", "raised", "non-text"),
    ("focus ring on the canvas (legend row, count chip hit box)", "ring", "canvas", "non-text"),
    ("focus ring on a selected row / tab", "ring", "selected", "non-text"),
    ("focus ring on the preview tile (sunken)", "ring", "sunken", "non-text"),
    ("the pressed star's inner ring on action.selected", "bsel", "asel", "non-text"),
    ("the selected swatch radio's inner ring on surface.selected", "bsel", "selected", "non-text"),
    ("inline validation text on the danger band", "t1", "dsub", "text"),
    ("'Used by 2 armed rules' callout text", "t1", "wsub", "text"),
    ("the validation band's glyph on danger.subtle", "dstr", "dsub", "non-text"),
    ("the Used-by tag's rule glyph on warning.subtle", "wstr", "wsub", "non-text"),
    ("invalid-field error glyph on the overlay", "dstr", "overlay", "non-text"),
    ("used-by-rules glyph on the overlay", "wstr", "overlay", "non-text"),
    ("the edited dot on the overlay", "idef", "overlay", "non-text"),
    ("'Manage all...' link on the popover overlay", "tlink", "overlay", "text"),
    ("errored legend row glyph on the canvas", "dstr", "canvas", "non-text"),
    ("count chip suffix glyph (error) on raised", "dstr", "raised", "non-text"),
    ("count chip suffix glyph (stale) on raised", "wstr", "raised", "non-text"),
    ("count chip suffix glyph (computing) on raised", "istr", "raised", "non-text"),
    ("count chip suffix glyph (hidden) and the chip border on raised", "t3", "raised", "non-text"),
    ("used-by-rules glyph on the legend row", "wstr", "canvas", "non-text"),
    (
        "'error' as danger text - REJECTED (text.primary + glyph)",
        "ddef",
        "canvas",
        "rejected-text",
    ),
    (
        "guide levels, zero lines, the VWAP reset mark: 1 px text.tertiary",
        "t3",
        "canvas",
        "non-text",
    ),
    ("legend eye / chevron glyphs on the canvas", "t2", "canvas", "non-text"),
    (
        "field border - REJECTED border.default (E13-D02)",
        "bdef",
        "overlay",
        "rejected-non-text",
    ),
    ("separators and card outlines (decorative)", "bdef", "overlay", "decorative"),
    (
        "selection fill vs raised (aria-selected + check carry it)",
        "selected",
        "raised",
        "decorative",
    ),
    ("hover fill vs raised", "hover", "raised", "decorative"),
    (
        "T2 fill vs the overlay it sits on (the state is text + glyph + aria)",
        "raised",
        "overlay",
        "decorative",
    ),
    ("candle up body; Volume up bars reuse it", "up", "canvas", "non-text"),
    ("candle down body; Volume down bars reuse it", "down", "canvas", "non-text"),
    ("candle wick", "wick", "canvas", "non-text"),
    ("LIVE badge icon on raised (blocked-removal rows)", "live", "raised", "non-text"),
    ("DEMO badge icon on raised", "demo", "raised", "non-text"),
    ("tag text on the hover fill ('Requires recorded history')", "t2", "hover", "text"),
    ("CMP-227 '(estimated)' word on the info fill (by reference)", "t1", "isub", "text"),
    ("CMP-227 outline and glyph on the info fill", "idef", "isub", "non-text"),
]
for _i in range(1, 9):
    PAIRS += [
        (f"slot {_i} line / bar / marker on the canvas", f"s{_i}", "canvas", "non-text"),
        (
            f"slot {_i} vs the overlay around its canvas tile (swatch radio, tooltip row)",
            f"s{_i}",
            "overlay",
            "reported",
        ),
        (
            f"slot {_i} vs raised around its canvas tile (thumbnail, tree-row swatch)",
            f"s{_i}",
            "raised",
            "reported",
        ),
        (
            f"slot {_i} pill words: inverse if >= 4.5, else the neutral pill",
            "tinv",
            f"s{_i}",
            "pill-text",
        ),
        (
            f"slot {_i} vs the focus ring (reported, not adjacent: a 2 px offset)",
            "ring",
            f"s{_i}",
            "reported",
        ),
        (
            f"slot {_i} band fill at the alpha vs the canvas (edges carry it)",
            f"f{_i}",
            "canvas",
            "decorative",
        ),
    ]


def resolve_theme(name: str) -> dict[str, object]:
    allt = dict(verify.load(verify.PRIMITIVES))
    allt.update(verify.merged_set(verify.THEMES[name]))
    return {k: verify.resolve(v["$value"], allt) for k, v in allt.items()}


T = {n: resolve_theme(n) for n in THEMES}
OUT: list[str] = []
FAILS: list[str] = []


def p(line: str) -> None:
    OUT.append(line)


def row(*cells: object) -> None:
    OUT.append("| " + " | ".join(str(c) for c in cells) + " |")


def is_hex(v: object) -> bool:
    return isinstance(v, str) and v.startswith("#") and len(v) == 7


def hx(theme: str, token: str) -> str:
    return str(T[theme][token])


def rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ratio(fg: str, bg: str) -> float:
    return float(contrast_check.contrast_ratio(rgb(fg), rgb(bg)))


def lum(h: str) -> float:
    return float(cvd.relative_luminance(h))


def lstar(h: str) -> float:
    return float(cvd.xyz_to_lab(cvd.srgb_to_xyz(h))[0])


def de(a: str, b: str) -> float:
    return float(cvd.delta_e76(a, b))


def sim(h: str, kind: str) -> str:
    return str(cvd.simulate(h, kind))


def blend(fg: str, bg: str, a: float) -> str:
    pairs = zip(rgb(fg), rgb(bg), strict=True)
    return "#" + "".join(f"{round(a * x + (1 - a) * y):02X}" for x, y in pairs)


def alias(theme: str, i: int) -> str:
    return SLOTS[i - 1][1 if theme == "light" else 0]


def slot(theme: str, i: int) -> str:
    return hx(theme, alias(theme, i))


def canvas(theme: str) -> str:
    return hx(theme, "color.surface.canvas")


def family(name: str) -> str:
    for part in name.split(".")[1:]:
        if part not in ("light", "cvd") and not part.isdigit():
            return part
    return name


def reserved(theme: str) -> list[str]:
    return sorted(
        k
        for k, v in T[theme].items()
        if k.startswith("color.") and not k.startswith(RESERVED_SKIP) and is_hex(v)
    )


RESERVED = {t: reserved(t) for t in THEMES}


def nearest(h: str, theme: str, kind: str | None = None) -> tuple[float, str]:
    best: tuple[float, str] = (999.0, "-")
    for x in RESERVED[theme]:
        hr = hx(theme, x)
        d = de(h, hr) if kind is None else de(sim(h, kind), sim(hr, kind))
        if d < best[0]:
            best = (d, x)
    return best


def fmt(x: float) -> str:
    return f"{x:.4f}" if any(abs(x - b) < 0.005 for b in (3.0, 4.5, 7.0)) else f"{x:.2f}"


def section(text: str, start: str, end: str) -> str:
    a = text.find(start)
    if a < 0:
        return ""
    b = text.find(end, a + 1)
    return text[a:] if b < 0 else text[a:b]


def key_hex(theme: str, key: str, alpha: float) -> str:
    if key in SHORT:
        return hx(theme, SHORT[key])
    if key[0] == "s":
        return slot(theme, int(key[1:]))
    return blend(slot(theme, int(key[1:])), canvas(theme), alpha)


def key_name(key: str) -> str:
    if key in SHORT:
        return SHORT[key]
    suffix = " at opacity.indicator.fill" if key[0] == "f" else ""
    return f"color.indicator.palette.{key[1:]}{suffix}"


def verdict(role: str, vals: list[float]) -> tuple[str, bool]:
    if role in NOT_GATED:
        return f"{role} (not gated)", False
    bar = BAR[role.replace("rejected-", "")]
    if role == "hc-text":
        bad = [THEMES[2]] if vals[2] < bar else []
    else:
        bad = [THEMES[i] for i, v in enumerate(vals) if v < bar]
    text = "PASS" if not bad else "FAIL: " + ", ".join(bad)
    if role.startswith("rejected"):
        return "rejected by design - would " + text, False
    return text, bool(bad)


def slot_search() -> None:
    p("## 1. Slot search: every primitive on the canvas per theme")
    p("")
    p(
        "Reserved tokens (every `color.*` except the surface tiers): "
        + ", ".join(f"{t} {len(RESERVED[t])}" for t in THEMES)
        + f". Letters: c canvas >= 3:1, d dE >= {DE_FLOOR:.0f} from every reserved token, "
        f"p / u protan / deutan dE >= {JND} from every reserved token; x = an excluded family "
        "(buy / sell / env / danger hues, the chrome greys)."
    )
    p("")
    row("primitive", "dark (hex ratio dE protan deutan tritan)", "light", "hc", "passes")
    row("---", "---", "---", "---", "---")
    for prim in sorted(k for k in T["dark"] if k.startswith("palette.")):
        cells, ok = [], ""
        excluded = prim.startswith(EXCLUDED_FAMILIES)
        for t in THEMES:
            h = hx(t, prim)
            if not is_hex(h):
                cells.append("-")
                ok += "-"
                continue
            r = ratio(h, canvas(t))
            d = nearest(h, t)[0]
            pr = [nearest(h, t, k)[0] for k in CVDS]
            cells.append(f"{h} {r:.2f} {d:.1f} {pr[0]:.1f} {pr[1]:.1f} {pr[2]:.1f}")
            flags = ("c" if r >= 3.0 else "-") + ("d" if d >= DE_FLOOR else "-")
            flags += ("p" if pr[0] >= JND else "-") + ("u" if pr[1] >= JND else "-")
            ok += ("x" if excluded else "") + flags + " "
        row(f"`{prim}`", *cells, ok.strip())


def palette() -> tuple[list[dict[str, object]], dict[str, list[str]]]:
    p("")
    p(f"## 1b. The eight slots (PROPOSED aliases; gated: canvas >= 3:1, dE >= {DE_FLOOR:.0f}, ")
    p(f"protan / deutan >= {JND} unless a recorded residual, every theme)")
    p("")
    row(
        "slot",
        "theme",
        "alias",
        "hex",
        "canvas",
        "overlay",
        "raised",
        "Y",
        "L*",
        "min dE",
        "protan",
        "deutan",
        "tritan",
        "verdict",
    )
    row(*["---"] * 14)
    out: list[dict[str, object]] = []
    words: dict[str, list[str]] = {t: [] for t in THEMES}
    for i in range(1, 9):
        rec: dict[str, object] = {"slot": i}
        for t in THEMES:
            h = slot(t, i)
            r = [ratio(h, hx(t, SHORT[s])) for s in ("canvas", "overlay", "raised")]
            d, near = nearest(h, t)
            proj = {k: nearest(h, t, k) for k in CVDS}
            notes: list[str] = []
            ok = r[0] >= 3.0 and d >= DE_FLOOR and not alias(t, i).startswith(EXCLUDED_FAMILIES)
            for k in CVDS[:2]:
                if proj[k][0] < JND:
                    if (i, t, k) in RESIDUALS:
                        notes.append(f"residual {k} vs `{proj[k][1]}` ({RESIDUALS[i, t, k]})")
                    else:
                        ok = False
                        notes.append(f"{k} collapse vs `{proj[k][1]}`")
            if not ok:
                FAILS.append(f"slot {i} {t}: canvas {r[0]:.2f}, dE {d:.1f}, {'; '.join(notes)}")
            rec[t] = {
                "alias": alias(t, i),
                "family": family(alias(t, i)),
                "hex": h,
                "canvas": round(r[0], 2),
                "overlay": round(r[1], 2),
                "raised": round(r[2], 2),
                "dE": round(d, 1),
                "nearest": near,
                "L": round(lstar(h), 1),
            }
            words[t].append(family(alias(t, i)))
            row(
                i,
                t,
                f"`{alias(t, i)}`",
                h,
                fmt(r[0]),
                fmt(r[1]),
                fmt(r[2]),
                f"{lum(h):.3f}",
                f"{lstar(h):.1f}",
                f"{d:.1f} (`{near}`)",
                *[f"{proj[k][0]:.1f} (`{proj[k][1]}`)" for k in CVDS],
                ("PASS" if ok else "FAIL") + ("; " + "; ".join(notes) if notes else ""),
            )
        out.append(rec)
    p("")
    p(
        "Family word per slot (the swatch radio names the colour of the active theme, CMP-031): "
        + "; ".join(f"{t}: " + " / ".join(words[t]) for t in THEMES)
    )
    return out, words


def cvd_pairs() -> tuple[int, list[str], list[str], dict[str, float], dict[str, float]]:
    p("")
    p(f"## 1c. Slot pairs: CIE76 dE, normal (gated >= {DE_FLOOR:.0f} for every pair: the first k ")
    p(f"slots always share a pane) and under the three dichromacies (JND {JND}); dL*")
    p("")
    row("pair", "theme", "normal", "protan", "deutan", "tritan", "dL*", "verdict")
    row(*["---"] * 8)
    n, collapses, grey = 0, [], []
    min_adj: dict[str, float] = {t: 999.0 for t in THEMES}
    min_de: dict[str, float] = {t: 999.0 for t in THEMES}
    for a in range(1, 9):
        for b in range(a + 1, 9):
            adjacent = b - a == 1 or (a, b) == (1, 8)
            for t in THEMES:
                ha, hb = slot(t, a), slot(t, b)
                d = [de(ha, hb)] + [de(sim(ha, k), sim(hb, k)) for k in CVDS]
                weak = [k for k, v in zip(("normal", *CVDS), d, strict=True) if v < JND]
                n += 1
                if weak:
                    collapses.append(f"{a}-{b} {t}: {', '.join(weak)}")
                dl = abs(lstar(ha) - lstar(hb))
                if dl < JND:
                    grey.append(f"{a}-{b} {t}")
                min_de[t] = min(min_de[t], d[0])
                if d[0] < DE_FLOOR:
                    FAILS.append(f"slots {a}-{b} under {DE_FLOOR:.0f} dE in normal vision ({t})")
                if adjacent:
                    min_adj[t] = min(min_adj[t], dl)
                    if d[0] < JND:
                        FAILS.append(f"adjacent slots {a}-{b} collapse in normal vision ({t})")
                    if dl < JND:
                        FAILS.append(f"adjacent slots {a}-{b} under {JND} L* ({t})")
                v = "distinct" if not weak else "COLLAPSES under " + ", ".join(weak)
                v += "" if not weak else " (the ladder tier and the label carry it)"
                if d[0] < DE_FLOOR:
                    v = f"FAIL: under {DE_FLOOR:.0f} dE in normal vision; " + v
                name = f"{a} vs {b}" + (" (adjacent)" if adjacent else "")
                row(name, t, *[f"{x:.1f}" for x in d], f"{dl:.1f}", v)
    p("")
    p(
        f"Greyscale (hue removed): slot pairs under {JND} dL*, carried by the tier and the label: "
        + ("; ".join(grey) or "none")
        + ". Smallest adjacent dL*: "
        + "; ".join(f"{t} {min_adj[t]:.1f}" for t in THEMES)
        + ". Smallest slot-vs-slot dE in normal vision (every pair gated >= "
        + f"{DE_FLOOR:.0f}): "
        + "; ".join(f"{t} {min_de[t]:.1f}" for t in THEMES)
        + "."
    )
    return n, collapses, grey, min_adj, min_de


def slot_vs_reserved() -> tuple[int, dict[str, int], list[str]]:
    p("")
    p(f"## 1d. Every slot vs every reserved token under the three projections (JND {JND})")
    p("")
    row("slot", "theme", "protan < JND", "deutan < JND", "tritan < JND (count; the nearest)")
    row(*["---"] * 5)
    rows, counts, listed = 0, {k: 0 for k in CVDS}, []
    for i in range(1, 9):
        for t in THEMES:
            h = slot(t, i)
            cells = []
            for k in CVDS:
                hits = [(de(sim(h, k), sim(hx(t, x), k)), x) for x in RESERVED[t]]
                rows += len(hits)
                under = sorted(v for v in hits if v[0] < JND)
                counts[k] += len(under)
                if k != "tritanopia":
                    for d, x in under:
                        listed.append(f"slot {i} {t} vs {x} under {k}: {d:.1f}")
                    cells.append("; ".join(f"`{x}` {d:.1f}" for d, x in under) or "none")
                else:
                    cells.append(
                        f"{len(under)}" + (f"; `{under[0][1]}` {under[0][0]:.1f}" if under else "")
                    )
            row(i, t, *cells)
    p("")
    p(
        f"{rows} slot x reserved x projection rows; collapses: "
        + ", ".join(f"{k} {counts[k]}" for k in CVDS)
        + f"; protan / deutan collapses are the recorded residuals ({len(RESIDUALS)}), "
        + "tritanopia is reported."
    )
    return rows, counts, listed


def assign(
    instances: list[tuple[str, int, int]], indicator: str, preset: int | None
) -> tuple[int, int]:
    """The section 3.4 function: per pane, the lowest free hue, D4's tier, a preset's hue wins."""
    pairs = {(s, t) for _, s, t in instances}
    hues = {s for _, s, _ in instances}
    sibling_tiers = {t for ind, _, t in instances if ind == indicator}
    tier = next((t for t in range(TIERS) if t not in sibling_tiers), 0)
    chosen: int | None = None
    if preset is not None and any((preset, t) not in pairs for t in range(TIERS)):
        chosen = preset
    else:
        free = [s for s in range(1, 9) if s not in hues]
        chosen = free[0] if free else None
    if chosen is None:  # every hue on the pane: the lowest free (slot, tier) pair from this tier on
        for k in range(TIERS):
            t = (tier + k) % TIERS
            free = [s for s in range(1, 9) if (s, t) not in pairs]
            if free:
                chosen, tier = free[0], t
                break
    if chosen is None:
        raise ValueError("no free pair")
    while (chosen, tier) in pairs:
        tier = (tier + 1) % TIERS
    return chosen, tier


def assignment() -> tuple[int, list[list[int]]]:
    p("")
    p("## 1e. The assignment function (spec section 3.4) simulated: no duplicate (slot, tier) pair")
    p("")
    checks = 0

    def check(pane: list[tuple[str, int, int]], label: str, hues_unique: bool) -> None:
        nonlocal checks
        checks += 1
        pairs = [(s, t) for _, s, t in pane]
        if len(set(pairs)) != len(pairs):
            FAILS.append(f"assignment: duplicate pair in {label}: {pairs}")
        if hues_unique and len({s for s, _ in pairs}) != len(pairs):
            FAILS.append(f"assignment: a hue repeats within eight in {label}: {pairs}")

    def add(pane: list[tuple[str, int, int]], ind: str, preset: int | None = None) -> None:
        s, t = assign(pane, ind, preset)
        pane.append((ind, s, t))

    # (a) nine unrelated instances, the slot-1 tier-0 one removed, another added
    pane: list[tuple[str, int, int]] = []
    for ind in ("ema", "rsi", "atr", "cci", "obv", "mfi", "cmf", "wma", "dema"):
        add(pane, ind)
    row("scenario", "pairs (slot, tier) in add order", "verdict")
    row("---", "---", "---")
    row(
        "(a) nine unrelated",
        [(s, t) for _, s, t in pane],
        "all distinct" if len({(s, t) for _, s, t in pane}) == 9 else "DUPLICATE",
    )
    pane = [x for x in pane if (x[1], x[2]) != (1, 0)]
    add(pane, "tema")
    check(pane, "(a) remove (1, 0), add", False)
    row(
        "(a) after removing (1, 0) and adding one",
        [(s, t) for _, s, t in pane],
        "the new one " + str(pane[-1][1:]),
    )
    # (b) nine EMAs, then twelve (a Guppy set)
    pane = []
    for _ in range(12):
        add(pane, "ema")
        check(pane, f"(b) {len(pane)} EMAs", len(pane) <= 8)
    row(
        "(b) twelve EMAs (D4: the tier differs up to six siblings, then the hue carries it)",
        [(s, t) for _, s, t in pane],
        "all distinct",
    )
    # (c) a preset whose colour is slot 1 beside an RSI in slot 1
    pane = []
    add(pane, "rsi")
    add(pane, "ema", preset=1)
    check(pane, "(c) preset slot 1 beside slot 1", False)
    row(
        "(c) RSI then a preset in slot 1",
        [(s, t) for _, s, t in pane],
        "the preset keeps its hue at tier " + str(pane[-1][2]),
    )
    # (d) seven presets all in slot 1: the seventh yields to the function
    pane = []
    for _ in range(7):
        add(pane, "sma", preset=1)
    check(pane, "(d) seven presets in slot 1", False)
    row(
        "(d) seven presets in slot 1 (six tiers)",
        [(s, t) for _, s, t in pane],
        "the seventh takes the next free hue",
    )
    # (e) 2,000 seeded add / remove / undo / preset sequences up to the 20-instance cap
    seed, inds, steps = 20261022, ("ema", "sma", "rsi", "macd", "vwap", "atr", "cci", "obv"), 0
    for _ in range(2000):
        pane, removed = [], None
        for _s in range(40):
            seed = (seed * 1103515245 + 12345) % 2**31
            op = seed % 10
            if op < 6 and len(pane) < CAP:
                preset = (seed // 10) % 8 + 1 if (seed // 100) % 5 == 0 else None
                add(pane, inds[(seed // 1000) % len(inds)], preset)
            elif op < 8 and pane:
                removed = pane.pop((seed // 10) % len(pane))
            elif removed is not None and len(pane) < CAP:
                if (removed[1], removed[2]) in {(s, t) for _, s, t in pane}:
                    add(pane, removed[0])  # the pair was taken meanwhile: undo re-assigns as an add
                else:
                    pane.append(removed)  # undo re-takes the same pair
                removed = None
            steps += 1
            check(pane, f"(e) random step {steps}", False)
    row(
        "(e) 2,000 seeded sequences of add / remove / undo / preset (<= 20 per pane)",
        f"{steps} steps checked",
        "no duplicate pair",
    )
    # the ten-indicator frame's assignment (board 13, spec section 11)
    stress: list[list[int]] = []
    p("")
    p("Ten-indicator frame (spec section 11; board 13): instance -> (slot, tier), per pane:")
    for pane_name, _h, instances, _fixed in STRESS:
        pane = []
        parts = []
        for ind, label in instances:
            add(pane, ind)
            stress.append([pane[-1][1], pane[-1][2]])
            parts.append(f"{label} ({pane[-1][1]}, {pane[-1][2]})")
        p(f"- {pane_name}: " + " · ".join(parts))
    return checks, stress


def band_alpha() -> tuple[float, dict[str, float], dict[str, float]]:
    p("")
    p("## 2. Band-fill alpha: the largest a (step 0.01) keeping the candles >= 3:1 against the")
    p("fill composited on the canvas (sRGB blend) - under the candles (opaque candle vs composite)")
    p("and over them (26 section 3.1 layers bands above series[]: tinted candle vs composite),")
    p("in the default and the CVD-safe palette; the minimum over slots, themes and models,")
    p("floored to 0.05")
    p("")
    row(
        "slot",
        "theme",
        "max a (under)",
        "max a (over)",
        "max a (CVD-safe under)",
        "max a (CVD-safe over)",
    )
    row(*["---"] * 6)
    models = {
        "under": (("up", "down", "wick"), False),
        "over": (("up", "down", "wick"), True),
        "cvd-under": (("cbuy", "csell", "wick"), False),
        "cvd-over": (("cbuy", "csell", "wick"), True),
    }

    def worst(i: int, t: str, a: float, cands: tuple[str, ...], over: bool) -> float:
        comp = blend(slot(t, i), canvas(t), a)
        vals = []
        for c in cands:
            cand = hx(t, SHORT[c])
            vals.append(ratio(blend(slot(t, i), cand, a) if over else cand, comp))
        return min(vals)

    best_all = 1.0
    for i in range(1, 9):
        for t in THEMES:
            cells = []
            for cands, over in models.values():
                best = 0.0
                for k in range(100, 0, -1):
                    if worst(i, t, k / 100, cands, over) >= 3.0:
                        best = k / 100
                        break
                best_all = min(best_all, best)
                cells.append(f"{best:.2f}")
            row(i, t, *cells)
    alpha = math.floor(best_all * 20 + 1e-9) / 20
    worst_at = {
        name: min(worst(i, t, alpha, cands, over) for i in range(1, 9) for t in THEMES)
        for name, (cands, over) in models.items()
    }
    stacked: dict[str, float] = {}
    for k in (2, 3):
        a_k = 1 - (1 - alpha) ** k
        stacked[f"{k} fills"] = min(
            worst(i, t, a_k, ("up", "down", "wick"), over)
            for i in range(1, 9)
            for t in THEMES
            for over in (False, True)
        )
    p("")
    p(
        f"opacity.indicator.fill = {alpha:.2f}; the worst candle ratio over one fill: "
        + ", ".join(f"{k} {v:.2f}:1" for k, v in worst_at.items())
        + ". Stacked fills at that alpha (effective alpha 1 - (1 - a)^n) would FAIL the 3:1 bar: "
        + ", ".join(
            f"{k} (a = {1 - (1 - alpha) ** int(k[0]):.2f}) {v:.2f}:1" for k, v in stacked.items()
        )
        + " - so fills never compound (spec section 4.3): one coverage stencil per pane, "
        + "a pixel takes one tint."
    )
    return alpha, worst_at, stacked


def matrix(
    alpha: float, registered: set[tuple[str, str]]
) -> tuple[dict[str, int], dict[str, list[str]]]:
    p("")
    p("## 3. Measured matrix (WCAG 2.x ratio per theme; unrounded compare; bar per role)")
    p("")
    row("element", "fg", "bg", "role", "dark", "light", "hc", "verdict", "pairs.mjs")
    row(*["---"] * 9)
    mx = {"rows": 0, "gated": 0, "registered": 0, "proposed": 0, "fail": 0}
    pill: dict[str, list[str]] = {}
    for element, fg, bg, role in PAIRS:
        vals = [ratio(key_hex(t, fg, alpha), key_hex(t, bg, alpha)) for t in THEMES]
        v, bad = verdict(role, vals)
        gated = role in BAR
        reg = (
            "registered"
            if (key_name(fg), key_name(bg)) in registered
            else ("PROPOSED" if gated else "-")
        )
        mx["rows"] += 1
        mx["gated"] += int(gated)
        mx["registered"] += int(reg == "registered")
        mx["proposed"] += int(reg == "PROPOSED")
        mx["fail"] += int(bad)
        if role == "pill-text":
            pill[bg] = ["inverse" if x >= 4.5 else "neutral" for x in vals]
        row(
            element, f"`{key_name(fg)}`", f"`{key_name(bg)}`", role, *[fmt(x) for x in vals], v, reg
        )
    if mx["fail"]:
        FAILS.append(f"matrix FAIL rows: {mx['fail']}")
    p("")
    p(
        f"Matrix: {mx['rows']} rows, {mx['gated']} gated, FAIL {mx['fail']}, "
        f"{mx['registered']} registered in pairs.mjs, {mx['proposed']} PROPOSED rows."
    )
    p(
        "Price-scale pill per slot (dark / light / hc): "
        + "; ".join(f"slot {k[1:]}: {' / '.join(v)}" for k, v in pill.items())
    )
    return mx, pill


def bindings(text: str) -> tuple[int, list[str]]:
    found = set(
        TOKEN_RE.findall(text)
    )  # a `.*` / trailing-dot / `..` mention is a family, not a binding
    bound = sorted(n for n in found if not n.endswith((".*", ".")) and ".." not in n)
    p("")
    p("## 4. Token bindings (every name the spec, the handoff and the 14 lines bind)")
    p("")
    row("token", "dark", "light", "hc")
    row("---", "---", "---", "---")
    missing = []
    for name in bound:
        vals = [T[t].get(name) for t in THEMES]
        if vals[0] is None:
            missing.append(name)
            if not PROPOSED_NAMES.match(name):
                FAILS.append(f"binding {name} is MISSING and not a PROPOSED name")
        cells = [
            "MISSING" if v is None else (v if isinstance(v, str) else json.dumps(v))[:40]
            for v in vals
        ]
        row(f"`{name}`", *cells)
    return len(bound), missing


def catalogue() -> list[tuple[str, list[str], bool]]:
    cat = read(API / "orderflow" / "indicators" / "catalogue.py")
    names = re.findall(r"[A-Z_]+", find(r"V1_INDICATORS[^=]*= \((.*?)\)", cat, re.DOTALL))
    starts = [
        (m.start(), m[1]) for m in re.finditer(r"^([A-Z_]+)(?:: [^=\n]+)? = ", cat, re.MULTILINE)
    ]
    out: list[tuple[str, list[str], bool]] = []
    for name in names:
        k = next(j for j, (_, n) in enumerate(starts) if n == name)
        block = cat[starts[k][0] : starts[k + 1][0] if k + 1 < len(starts) else len(cat)]
        if block.startswith(f"{name} = _server("):
            kernel = find(r"_server\(\s*(\w+)Kernel", block).lower()
            out.append((kernel, list(dict.fromkeys(re.findall(r'"(\w+)":', block))), True))
            continue
        iid = find(r'IndicatorDef\(\s*"(\w+)"', block)
        if "_outputs(*_BANDS)" in block:
            outs = list(BANDS)
        elif "OutputSpec(" in block:
            outs = re.findall(r'OutputSpec\("(\w+)"', block)
        else:
            outs = re.findall(
                r'\("([a-z]\w*)", "', find(r"_outputs\((.*?)\)\)\s*,", block, re.DOTALL)
            )
        out.append((iid, outs, False))
    return out


def count(calls: str) -> int:
    parts = calls.split()
    return sum(int(parts[j + 1]) for j in range(0, len(parts), 2))


def draw_calls() -> dict[str, int]:
    p("")
    p("## 6. Draw calls (26 section 4: <= 18 per pane, <= 40 per chart), the merge rule, the")
    p("legend overflow")
    p("")
    p(
        "Merge rule (E11-D02 line 678 hands it to E13): every indicator line series of a pane "
        "is one instanced line draw - colour index, width and dash index are per-instance "
        "attributes (26 section 3.10) - so lines cost 1 per pane (the unmerged 1-per-series "
        "count of 26 section 4 is reported); a band is one stencil-tested fill pass, a histogram "
        "one instanced bar draw, the markers of a pane one instanced glyph draw, the axis / "
        "legend / watermark text one SDF draw."
    )
    p("")
    row("scene", "calls (merged)", "per pane", "unmerged", "legend rows visible / overflow")
    row("---", "---", "---", "---", "---")
    totals: dict[str, int] = {}
    b5 = count(B5_FIXED) + 1
    totals["B5 price pane"] = b5
    totals["B5 price pane unmerged"] = count(B5_FIXED) + B5_LINES
    row(
        "B5 price pane (candles + footprint + heatmap + 3 indicator lines + 50 order lines)",
        f"{B5_FIXED} lines 1",
        b5,
        totals["B5 price pane unmerged"],
        "-",
    )
    totals["nominal pane + 3"] = NOMINAL_PANE
    totals["nominal pane + 3 unmerged"] = NOMINAL_PANE + NOMINAL_EXTRA_LINES - 1
    row(
        "E11-D02's nominal fully-layered pane (18, <= 1 indicator batch) + three indicator lines",
        "18 + 0",
        NOMINAL_PANE,
        totals["nominal pane + 3 unmerged"],
        "-",
    )
    stress_total, stress_unmerged = 0, 0
    for name, height, instances, fixed in STRESS:
        lines = sum(KIND[i][0] for i, _ in instances)
        bands = sum(KIND[i][1] for i, _ in instances)
        hists = sum(KIND[i][2] for i, _ in instances)
        markers = 1 if any(KIND[i][3] for i, _ in instances) else 0
        extra = (
            f" lines {1 if lines else 0}"
            + (f" bands {bands}" if bands else "")
            + (f" histograms {hists}" if hists else "")
            + (f" markers {markers}" if markers else "")
        )
        n = count(fixed + extra)
        n_un = n - (1 if lines else 0) + lines
        totals[f"stress {name}"] = n
        stress_total += n
        stress_unmerged += n_un
        if n > 18:
            FAILS.append(f"stress {name}: {n} draw calls > 18")
        rows = len(instances) + (1 if name == "price pane" else 0)
        vis = max(3, math.floor(0.3 * height / 24))
        over = (
            f"{vis} of {rows}, '+{rows - vis} more'"
            if rows > vis
            else f"{rows} of {rows}, no overflow"
        )
        labels = ", ".join(lbl for _, lbl in instances)
        row(
            f"ten-indicator frame, {name} ({labels}) at {height} px",
            fixed + extra,
            n,
            n_un,
            over,
        )
    totals["stress total"] = stress_total
    totals["stress total unmerged"] = stress_unmerged
    if stress_total > 40:
        FAILS.append(f"stress scene {stress_total} > 40")
    p("")
    p(
        f"B5 total {b5} <= 40 ({totals['B5 price pane unmerged']} unmerged); ten-indicator "
        f"scene total {stress_total} <= 40 ({stress_unmerged} unmerged), every pane <= 18; "
        f"a 600 px compact pane shows {max(3, math.floor(0.3 * 600 / 24))} legend rows."
    )
    return totals


def gates(texts: dict[str, str], constitution: str) -> list[str]:
    bad: list[str] = []
    for label, txt in texts.items():
        if label in ("spec", "draft") and "Period must be between 1 and 5000." not in txt:
            bad.append(f"{label}: the IR-07 string is missing")
        if label == "spec" and "fills never compound" not in txt:
            bad.append("spec: the no-compounding fill rule is missing")
        for m in re.findall(r"between 1 and (\d+)", txt):
            if m != "5000":
                bad.append(f"{label}: 'between 1 and {m}'")
        if re.search(r"\(est(?!imated\))", txt) or "Est." in txt:
            bad.append(f"{label}: an abbreviated '(estimated)'")
        for line in txt.splitlines():
            if (
                re.search(r"dash", line, re.IGNORECASE)
                and re.search(r"\bleg\b", line)
                and "provisional" not in line
            ):
                bad.append(f"{label}: a dashed leg without 'provisional': {line[:60]!r}")
        if "/ho" + "me/" in txt or "SET-ME" in txt:
            bad.append(f"{label}: a local path or placeholder")
        if re.search(r"penpot\.[a-z0-9-]+\.[a-z]{2,}", txt):
            bad.append(f"{label}: a Penpot hostname")
        for c in sorted(set(re.findall(r"C-\d+\.\d+", txt))):
            if not re.search(rf"(?<![\w.]){re.escape(c)}(?!\d)", constitution):
                bad.append(f"{label}: {c} is not in CONSTITUTION.md")
    return bad


def table_rows(text: str) -> int:
    return max(0, len(re.findall(r"^\| ", text, re.MULTILINE)) - 2)


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # the reference machine's console is cp1252
    spec, handoff = read(SPEC), read(HANDOFF)
    lines14 = [
        ln
        for ln in read(ROOT / "docs/plan/14-screens-catalogue.md").splitlines()
        if "E13-D03" in ln
    ]
    registered = set(
        re.findall(r'fg:\s*"([^"]+)",\s*bg:\s*"([^"]+)"', read(ROOT / "tools/contrast/pairs.mjs"))
    )
    slot_search()
    pal, words = palette()
    n_cvd, collapses, grey, min_adj, min_de = cvd_pairs()
    n_proj, proj_counts, proj_listed = slot_vs_reserved()
    for line in proj_listed:
        p(f"- {line}")
    n_checks, stress_assign = assignment()
    alpha, worst_at, stacked = band_alpha()
    m = re.search(r"`opacity\.indicator\.fill` = (\d\.\d\d)", spec)
    if m is None or float(m[1]) != alpha:
        FAILS.append(
            f"the spec's opacity.indicator.fill ({m[1] if m else 'missing'}) != {alpha:.2f}"
        )
    mx, pill = matrix(alpha, registered)
    n_bound, missing = bindings(spec + handoff + "\n".join(lines14))
    files = ("primitives", "semantic-dark", "semantic-light", "semantic-hc")
    counts_files = {f: read(TOKENS / f"{f}.tokens.json").count('"$value"') for f in files}
    prefixes = read(ROOT / "tools/style-dictionary/formats/json-flat-rgba.js")
    p("")
    p(
        f"Token counts {counts_files}; MISSING (all PROPOSED names): {missing}; "
        f"`color.indicator.` in ENGINE_CATEGORY_PREFIXES: {'color.indicator.' in prefixes}"
    )
    cat = catalogue()
    sec5 = section(spec, "## 5.", "## 6.")
    uncovered = [f"{iid}.{o}" for iid, outs, _ in cat for o in outs if f"`{o}`" not in sec5]
    if uncovered:
        FAILS.append(f"outputs not in the spec's section 5 table: {uncovered}")
    limits = read(API / "orderflow" / "indicators" / "limits.py")
    period = [int(find(rf"PERIOD_{k}: Final = (\d+)", limits)) for k in ("MIN", "MAX")]
    builtins_text = read(API / "db" / "builtin_indicator_presets.py")
    builtins = re.findall(
        r'_row\(\s*"[0-9a-f-]+",\s*"[a-z_]+",\s*"([^"]+)"', builtins_text, re.DOTALL
    )
    enc = json.loads(read(ROOT / "tools/contrast/encodings.json"))["encodings"]
    n_out = sum(len(o) for _, o, _ in cat)
    p("")
    p(
        f"## 5. Catalogue: {len(cat)} definitions, {sum(s for _, _, s in cat)} server, {n_out} out"
        f"puts, {n_out - len(uncovered)} in spec section 5; period {period[0]}..{period[1]}; "
        f"{len(builtins)} built-ins; encodings.json keys {sorted(enc)}; indicator-series row: "
        f"{'indicator-series' in enc}"
    )
    p("")
    for iid, outs, server in cat:
        p(f"- `{iid}`{' (server)' if server else ''}: " + ", ".join(f"`{o}`" for o in outs))
    draws = draw_calls()
    texts = {"spec": spec, "handoff": handoff, "14 lines": "\n".join(lines14)}
    if "--draft" in argv:
        texts["draft"] = read(Path(argv[argv.index("--draft") + 1]))
    gate_fails = gates(texts, read(ROOT / "CONSTITUTION.md"))
    if re.search(r"^- \[ \] \*\*[^*]+\*\*\s*$", handoff, re.MULTILINE):
        gate_fails.append("handoff: a blank checklist line")
    FAILS.extend(gate_fails)
    counts: dict[str, object] = {
        "slots": 8,
        "lineTiers": len(LADDER),
        "reservedDash": len(RESERVED_DASH),
        "reservedTokens": {t: len(RESERVED[t]) for t in THEMES},
        "descriptors": len(cat),
        "server": sum(s for _, _, s in cat),
        "outputs": n_out,
        "outputsCovered": n_out - len(uncovered),
        "builtins": len(builtins),
        "periodMin": period[0],
        "periodMax": period[1],
        "legendStates": table_rows(section(spec, "### 7.1", "### 7.2")),
        "boards": table_rows(section(spec, "## 0.", "## 1.")),
        "frames": 12,
        "vocabularyKeys": table_rows(section(spec, "## 9.", "## 10.")),
        "matrixRows": mx["rows"],
        "matrixGated": mx["gated"],
        "matrixRegistered": mx["registered"],
        "matrixProposed": mx["proposed"],
        "matrixFail": mx["fail"],
        "cvdPairs": n_cvd,
        "cvdCollapses": len(collapses),
        "greyPairsUnderJnd": len(grey),
        "minAdjacentDL": round(min(min_adj.values()), 1),
        "minSlotPairDE": round(min(min_de.values()), 1),
        "projectionRows": n_proj,
        "protanCollapses": proj_counts["protanopia"],
        "deutanCollapses": proj_counts["deuteranopia"],
        "tritanCollapses": proj_counts["tritanopia"],
        "residuals": len(RESIDUALS),
        "assignmentChecks": n_checks,
        "alpha": alpha,
        "worstCandleAtAlpha": round(worst_at["under"], 2),
        "worstCandleOverFill": round(worst_at["over"], 2),
        "worstCandleCvdSafe": round(min(worst_at["cvd-under"], worst_at["cvd-over"]), 2),
        "worstTwoFills": round(stacked["2 fills"], 2),
        "worstThreeFills": round(stacked["3 fills"], 2),
        "drawB5": draws["B5 price pane"],
        "drawB5Unmerged": draws["B5 price pane unmerged"],
        "drawNominal": draws["nominal pane + 3"],
        "drawNominalUnmerged": draws["nominal pane + 3 unmerged"],
        "drawStress": draws["stress total"],
        "drawStressUnmerged": draws["stress total unmerged"],
        "drawStressPrice": draws["stress price pane"],
        "drawStressSubA": draws["stress sub-pane A"],
        "drawStressSubB": draws["stress sub-pane B"],
        "cRows": len(re.findall(r"^\| C-\d+ ", section(spec, "## 17.", "## 18."), re.MULTILINE)),
        "gRows": len(re.findall(r"^\| G-\d+ ", section(spec, "## 18.", "## 19."), re.MULTILINE)),
        "qRows": len(re.findall(r"^\| Q-\d+ ", section(spec, "## 19.", "## 20."), re.MULTILINE)),
        "crRows": len(
            re.findall(r"^\| CR-\d+ ", section(spec, "### 10.5", "## 11."), re.MULTILINE)
        ),
        "amendmentRows": table_rows(section(spec, "## 16.", "## 17.")),
        "handoffBlocks": handoff.count("## Handoff checklist"),
        "tokensBound": n_bound,
        "tokensMissing": len(missing),
        "jnd": JND,
        "tokenFiles": counts_files,
    }
    if "--json" in argv:
        out = {
            "counts": counts,
            "palette": pal,
            "familyWords": words,
            "pill": pill,
            "collapses": collapses,
            "grey": grey,
            "stressAssignment": stress_assign,
            "fails": FAILS,
        }
        print(json.dumps(out, indent=1, ensure_ascii=False))
        return 1 if FAILS else 0
    print("\n".join(OUT))
    print("\n## 7. String gates: " + ("all pass" if not gate_fails else "; ".join(gate_fails)))
    print(
        "CVD slot-pair collapses (" + str(len(collapses)) + "): " + ("; ".join(collapses) or "none")
    )
    print("\n## 8. Counts\n" + json.dumps(counts, ensure_ascii=False))
    print(
        "\nGATED FAILURES: "
        + ("; ".join(FAILS) if FAILS else "none")
        + f"\nexit {1 if FAILS else 0}"
    )
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
