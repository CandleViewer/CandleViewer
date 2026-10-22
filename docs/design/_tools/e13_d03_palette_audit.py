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
the three `14` pointer lines and the optional PR draft are read as text. Composites are blended in
sRGB (the browser's and WebGL's default blend space). Exit 1 on a gated FAIL or a failed string
gate; `--json` prints only the counts and numbers the board check-nums script consumes.
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
NOT_GATED = ("decorative", "reported", "pill-text", "exempt")
# The eight slots (PROPOSED aliases; no hex is invented): dark alias, light alias; high-contrast
# inherits the dark alias (no semantic-hc line). The order alternates hue family (teal / purple /
# orange / blue) and lightness, so adjacent slots differ in hue and in luminance.
SLOTS = (
    ("palette.teal.400", "palette.teal.600"),
    ("palette.purple.500", "palette.purple.600"),
    ("palette.cvd.orange.4", "palette.cvd.light.orange.1"),
    ("palette.cvd.blue.1", "palette.cvd.light.blue.5"),
    ("palette.purple.400", "palette.purple.500"),
    ("palette.teal.600", "palette.teal.900"),
    ("palette.cvd.blue.4", "palette.cvd.blue.1"),
    ("palette.cvd.orange.1", "palette.cvd.light.orange.5"),
)
# Tokens that carry a meaning on the chart or in the chrome: a slot keeps CIE76 dE >= 8 from each.
_RESERVED_SRC = (
    "color.buy.default color.sell.default color.buy.hc color.sell.hc color.candle.up "
    "color.candle.down color.candle.wick color.status.success.default color.status.danger.default "
    "color.status.warning.default color.status.info.default color.status.success.strong "
    "color.status.danger.strong color.status.warning.strong color.status.info.strong "
    "color.env.demo color.env.live color.focus.ring color.action.primary.default "
    "color.drawing.default color.drawing.selected color.order.line color.position.entry "
    "color.position.sl color.position.tp color.profile.poc color.text.link color.cvd.buy "
    "color.cvd.sell"
)
RESERVED = _RESERVED_SRC.split()
_SHORT_SRC = (
    "app=color.surface.app canvas=color.surface.canvas raised=color.surface.raised "
    "overlay=color.surface.overlay sunken=color.surface.sunken hover=color.surface.hover "
    "selected=color.surface.selected t1=color.text.primary t2=color.text.secondary "
    "t3=color.text.tertiary tdis=color.text.disabled tinv=color.text.inverse "
    "ring=color.focus.ring bdef=color.border.default up=color.candle.up down=color.candle.down "
    "wick=color.candle.wick live=color.env.live demo=color.env.demo "
    "dsub=color.status.danger.subtle dstr=color.status.danger.strong "
    "ddef=color.status.danger.default wsub=color.status.warning.subtle "
    "wstr=color.status.warning.strong isub=color.status.info.subtle idef=color.status.info.default"
)
SHORT = dict(kv.split("=") for kv in _SHORT_SRC.split())
LADDER = ("solid 2 px", "solid 1 px", "solid 3 px", "dash 8-4 2 px", "dash 8-4 1 px", "dash-dot")
RESERVED_DASH = ("dash.4-4", "dash.2-6", "dash.2-2", "dash.4-3", "dash.3-3")
BANDS = ("upper", "middle", "lower")
# Draw calls per pane (26 section 4: grid 2, candles 2, heatmap 2, footprint 2, 1 per line series,
# 1 per band-fill pass, 1 per histogram, markers 1 per pane + DOM labels, orders 1, crosshair 1)
# and, for the ten-indicator frame, each pane's height and legend rows (the price row included).
SCENES = (
    ("B5 price pane", "grid 2 candles 2 heatmap 2 footprint 2 lines 3 orders 1 crosshair 1", 0, 0),
    ("stress price pane", "grid 2 candles 2 lines 7 bands 1 markers 1 crosshair 1", 422, 6),
    ("stress sub-pane A", "grid 2 lines 3 guides 1 crosshair 1", 141, 3),
    ("stress sub-pane B", "grid 2 lines 4 histograms 2 zero 1 crosshair 1", 141, 4),
)
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
PAIRS: list[tuple[str, str, str, str]] = [
    ("dialog / drawer / tooltip text; a disabled control's reason text", "t1", "overlay", "text"),
    ("dialog text, hc 7:1", "t1", "overlay", "hc-text"),
    ("hints, help lines, the preview caption on the overlay", "t2", "overlay", "text"),
    ("kickers, counts, the swatch's token-name label", "t3", "overlay", "text"),
    ("field borders, selection outline, bulk-bar edge (E13-D02)", "t3", "overlay", "non-text"),
    ("entry names, tree labels, chip / badge / kbd words on raised", "t1", "raised", "text"),
    ("sub-labels and tags on raised", "t2", "raised", "text"),
    ("group header, bulk bar, hovered row text", "t1", "hover", "text"),
    ("selected row / tab text", "t1", "selected", "text"),
    ("preview caption on sunken", "t2", "sunken", "text"),
    ("preview axis labels on sunken", "t3", "sunken", "text"),
    ("legend label, pane-header label, marker label (DOM)", "t1", "canvas", "text"),
    ("legend label, hc 7:1", "t1", "canvas", "hc-text"),
    ("legend value, 'computing...', pane-header values", "t2", "canvas", "text"),
    ("hidden row label, frozen stale value, gutter guide value", "t3", "canvas", "text"),
    (
        "disabled label - exempt (WCAG 1.4.3); the reason is gated above",
        "tdis",
        "overlay",
        "exempt",
    ),
    ("focus ring on the overlay (fields, swatch radios, buttons)", "ring", "overlay", "non-text"),
    ("focus ring on a raised option / tree row", "ring", "raised", "non-text"),
    ("focus ring on the canvas (legend row, count chip hit box)", "ring", "canvas", "non-text"),
    ("focus ring on a selected row / tab", "ring", "selected", "non-text"),
    ("focus ring on the preview tile (sunken)", "ring", "sunken", "non-text"),
    ("inline validation text on the danger band", "t1", "dsub", "text"),
    ("'Used by 2 armed rules' callout text", "t1", "wsub", "text"),
    ("invalid-field error glyph on the overlay", "dstr", "overlay", "non-text"),
    ("used-by-rules glyph on the overlay", "wstr", "overlay", "non-text"),
    ("errored legend row glyph on the canvas", "dstr", "canvas", "non-text"),
    ("count chip suffix glyph (error) on raised", "dstr", "raised", "non-text"),
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
            f"slot {_i} swatch on the overlay (radiogroup, tooltip dot)",
            f"s{_i}",
            "overlay",
            "non-text",
        ),
        (f"slot {_i} thumbnail tile / shape swatch on raised", f"s{_i}", "raised", "non-text"),
        (
            f"slot {_i} pill words: inverse if >= 4.5, else the neutral pill",
            "tinv",
            f"s{_i}",
            "pill-text",
        ),
        (
            f"slot {_i} vs the focus ring (adjacent on a focused swatch)",
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


def slot(theme: str, i: int) -> str:
    return hx(theme, SLOTS[i - 1][1 if theme == "light" else 0])


def canvas(theme: str) -> str:
    return hx(theme, "color.surface.canvas")


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
    p("## 1. Slot search: every primitive on the canvas per theme (ratio; min dE to a reserved)")
    p("")
    row("primitive", "dark", "light", "hc", "passes (>= 3:1 and dE >= 8)")
    row("---", "---", "---", "---", "---")
    for prim in sorted(k for k in T["dark"] if k.startswith("palette.")):
        cells, ok = [], ""
        for t in THEMES:
            h = hx(t, prim)
            r, d = ratio(h, canvas(t)), min(de(h, hx(t, x)) for x in RESERVED)
            cells.append(f"{h} {r:.2f} dE {d:.1f}")
            ok += t[0] if r >= 3.0 and d >= 8.0 else "-"
        row(f"`{prim}`", *cells, ok)


def palette() -> list[dict[str, object]]:
    p("")
    p("## 1b. The eight slots (PROPOSED aliases; gated: canvas >= 3:1, dE >= 8, every theme)")
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
        "verdict",
    )
    row(*["---"] * 11)
    out: list[dict[str, object]] = []
    for i in range(1, 9):
        rec: dict[str, object] = {"slot": i}
        for t in THEMES:
            h = slot(t, i)
            r = [ratio(h, hx(t, SHORT[s])) for s in ("canvas", "overlay", "raised")]
            d, near = min((de(h, hx(t, x)), x) for x in RESERVED)
            ok = r[0] >= 3.0 and d >= 8.0
            if not ok:
                FAILS.append(f"slot {i} {t}: canvas {r[0]:.2f}, dE {d:.1f}")
            alias = SLOTS[i - 1][1 if t == "light" else 0]
            rec[t] = {"alias": alias, "hex": h, "canvas": round(r[0], 2), "dE": round(d, 1)}
            rec[t + "_L"] = round(lstar(h), 1)
            row(
                i,
                t,
                f"`{alias}`",
                h,
                fmt(r[0]),
                fmt(r[1]),
                fmt(r[2]),
                f"{lum(h):.3f}",
                f"{lstar(h):.1f}",
                f"{d:.1f} (`{near}`)",
                "PASS" if ok else "FAIL",
            )
        out.append(rec)
    return out


def cvd_pairs() -> tuple[int, list[str], list[str]]:
    p("")
    p(f"## 1c. Slot pairs: CIE76 dE, normal and under the three dichromacies (JND {JND}); dL*")
    p("")
    row("pair", "theme", "normal", "protan", "deutan", "tritan", "dL*", "verdict")
    row(*["---"] * 8)
    n, collapses, grey = 0, [], []
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
                if abs(lstar(ha) - lstar(hb)) < JND:
                    grey.append(f"{a}-{b} {t}")
                if adjacent and d[0] < JND:
                    FAILS.append(f"adjacent slots {a}-{b} collapse in normal vision ({t})")
                v = "distinct" if not weak else "COLLAPSES under " + ", ".join(weak)
                v += "" if not weak else " (the ladder tier and the label carry it)"
                name = f"{a} vs {b}" + (" (adjacent)" if adjacent else "")
                dl = abs(lstar(ha) - lstar(hb))
                row(name, t, *[f"{x:.1f}" for x in d], f"{dl:.1f}", v)
    p("")
    p(
        f"Greyscale (hue removed): slot pairs under {JND} dL*, carried by the tier and the label: "
        + ("; ".join(grey) or "none")
    )
    return n, collapses, grey


def band_alpha() -> tuple[float, float]:
    p("")
    p("## 2. Band-fill alpha: the largest a (step 0.01) keeping candle up / down / wick >= 3:1")
    p("over slot-over-canvas (sRGB blend); the minimum over slots and themes, floored to 0.05")
    p("")
    row("slot", "theme", "max alpha", "worst candle ratio at it")
    row("---", "---", "---", "---")
    best_all = 1.0
    for i in range(1, 9):
        for t in THEMES:
            best, worst = 0.0, 0.0
            for k in range(100, 0, -1):
                comp = blend(slot(t, i), canvas(t), k / 100)
                r = min(ratio(hx(t, SHORT[c]), comp) for c in ("up", "down", "wick"))
                if r >= 3.0:
                    best, worst = k / 100, r
                    break
            best_all = min(best_all, best)
            row(i, t, f"{best:.2f}", f"{worst:.2f}")
    alpha = math.floor(best_all * 20 + 1e-9) / 20
    worst_at = 99.0
    for i in range(1, 9):
        for t in THEMES:
            comp = blend(slot(t, i), canvas(t), alpha)
            worst_at = min(
                worst_at, *[ratio(hx(t, SHORT[c]), comp) for c in ("up", "down", "wick")]
            )
    p("")
    p(f"opacity.indicator.fill = {alpha:.2f}; worst candle ratio over a fill {worst_at:.2f}:1.")
    return alpha, worst_at


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


def draw_calls() -> tuple[int, int]:
    p("")
    p("## 6. Draw calls (26 section 4: <= 18 per pane, <= 40 per chart) and the legend overflow")
    p("")
    row("scene", "calls", "per pane", "legend rows visible / overflow")
    row("---", "---", "---", "---")
    totals: dict[str, int] = {}
    for name, calls, height, rows in SCENES:
        parts = calls.split()
        n = sum(int(parts[j + 1]) for j in range(0, len(parts), 2))
        totals[name] = n
        if n > 18:
            FAILS.append(f"{name}: {n} draw calls > 18")
        vis = max(3, math.floor(0.3 * height / 24)) if height else 0
        if not height:
            over = "-"
        elif rows > vis:
            over = f"{vis} of {rows}, '+{rows - vis} more'"
        else:
            over = f"{rows} of {rows}, no overflow"
        row(name, calls, n, over)
    stress = sum(v for k, v in totals.items() if k.startswith("stress"))
    if stress > 40:
        FAILS.append(f"stress scene {stress} > 40")
    p("")
    p(
        f"B5 total {totals['B5 price pane']} <= 40; ten-indicator scene total {stress} <= 40; "
        f"a 600 px compact pane shows {max(3, math.floor(0.3 * 600 / 24))} legend rows."
    )
    return totals["B5 price pane"], stress


def gates(texts: dict[str, str], constitution: str) -> list[str]:
    bad: list[str] = []
    for label, txt in texts.items():
        if label in ("spec", "draft") and "Period must be between 1 and 5000." not in txt:
            bad.append(f"{label}: the IR-07 string is missing")
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
        if (
            "/ho" + "me/" in txt
            or "SET-ME" in txt
        ):
            bad.append(f"{label}: a local path, user name or placeholder")
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
    pal = palette()
    n_cvd, collapses, grey = cvd_pairs()
    alpha, worst_at = band_alpha()
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
    b5, stress = draw_calls()
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
        "alpha": alpha,
        "worstCandleAtAlpha": round(worst_at, 2),
        "drawB5": b5,
        "drawStress": stress,
        "cRows": len(re.findall(r"^\| C-\d+ ", section(spec, "## 17.", "## 18."), re.MULTILINE)),
        "gRows": len(re.findall(r"^\| G-\d+ ", section(spec, "## 18.", "## 19."), re.MULTILINE)),
        "qRows": len(re.findall(r"^\| Q-\d+ ", section(spec, "## 19.", "## 20."), re.MULTILINE)),
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
            "pill": pill,
            "collapses": collapses,
            "grey": grey,
            "fails": FAILS,
        }
        print(json.dumps(out, indent=1, ensure_ascii=False))
        return 1 if FAILS else 0
    print("\n".join(OUT))
    print("\n## 7. String gates: " + ("all pass" if not gate_fails else "; ".join(gate_fails)))
    print(f"CVD collapses ({len(collapses)}): " + ("; ".join(collapses) or "none"))
    print("\n## 8. Counts\n" + json.dumps(counts, ensure_ascii=False))
    print(
        "\nGATED FAILURES: "
        + ("; ".join(FAILS) if FAILS else "none")
        + f"\nexit {1 if FAILS else 0}"
    )
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
