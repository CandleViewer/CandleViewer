"""E25-D03 hi-fi audit: every number the SCR-055 / SCR-056 / SCR-057 hi-fi spec states, computed.

Standalone, offline, stdlib only (`python3 -I`). Themes resolve exactly as
`packages/ui/tokens/tests/verify_tokens.py` resolves them and contrast is `contrast_ratio()` from
`docs/design/_tools/contrast_check.py` (both imported with one loader, never re-implemented). The
greyscale and deuteranopia maths are `docs/design/_tools/cvd_sim.py`'s (Rec. 601 luma, the Machado
2009 matrix), re-stated here on single colours so the tool needs no numpy. Nothing here reads a
fixture or a network.

Sections: A the resolved tokens every binding names (a name that does not resolve is a FAIL);
B the contrast matrix, every pair in dark / light / high-contrast compared unrounded against its
bar, composited rows (the 0.85 stale dim, `opacity.muted`) by the E22-D03 `over()` method; C the
E25 number-format sheet (BQ-04), every sample rendered by the formatter; D the greyscale /
deuteranopia statement; E the board plan (<= 10 boards, light twins <= one third, ids PENDING in
PR 1); F the spec's own tables and strings (the chip bindings equal their catalogue entries, no
dashed line on SCR-055, no trend glyph on SCR-057, the motion pairs, the spoken announcement
forms, the E25-D02 strings carried verbatim, the hygiene patterns, the rule ids).

Usage: python3 -I docs/design/_tools/e25_d03_panels_hifi_audit.py [--json]
       python3 -I docs/design/_tools/e25_d03_panels_hifi_audit.py --check [SPEC]
       python3 -I docs/design/_tools/e25_d03_panels_hifi_audit.py --self-test [SPEC]
`--check` exits 1 on a gated FAIL, a lost reproduction, a failed table or string gate, or a number
the tool prints that the spec's own text does not carry (section G, drift). `--self-test` applies
MUTATIONS to the spec in memory (the file is never written): each must raise exactly one new FAIL,
no two the same, and the clean spec must pass before and after. Stdout is UTF-8.
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
TOOLS = ROOT / "docs" / "design" / "_tools"
SPEC = ROOT / "docs" / "design" / "E25" / "E25-D03.md"
CONSTITUTION = ROOT / "CONSTITUTION.md"
THEMES = ("dark", "light", "high-contrast")
BAR: dict[str, float | None] = {"text": 4.5, "non-text": 3.0}
BAR.update({"decorative": None, "reported": None, "rejected-text": 4.5, "rejected-non-text": 3.0})
GATED = {"text", "non-text"}


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(TOKENS / "tests"))
verify = _load(TOKENS / "tests" / "verify_tokens.py", "verify_tokens")
contrast_check = _load(TOOLS / "contrast_check.py", "contrast_check")


def resolve_theme(name: str) -> dict[str, Any]:
    allt: dict[str, Any] = dict(verify.load(verify.PRIMITIVES))
    allt.update(verify.merged_set(verify.THEMES[name]))
    out: dict[str, Any] = {}
    for k, v in allt.items():
        if isinstance(v, dict) and "$value" in v:
            raw = v["$value"]
            out[k] = verify.resolve(raw, allt) if isinstance(raw, str) else "composite"
    return out


T = {n: resolve_theme(n) for n in THEMES}


def rows_of(txt: str, sep: str = "|") -> list[list[str]]:
    return [[c.strip() for c in ln.split(sep)] for ln in txt.strip().splitlines()]


TOK = dict(rows_of("""canvas|color.surface.canvas
raised|color.surface.raised
overlay|color.surface.overlay
hover|color.surface.hover
selected|color.surface.selected
app|color.surface.app
t1|color.text.primary
t2|color.text.secondary
t3|color.text.tertiary
b.default|color.border.default
b.strong|color.border.strong
b.selected|color.border.selected
ring|color.focus.ring
buy|color.buy.default
sell|color.sell.default
buy.subtle|color.buy.subtle
sell.subtle|color.sell.subtle
n.subtle|color.neutral.subtle
warn.default|color.status.warning.default
warn.subtle|color.status.warning.subtle
warn.strong|color.status.warning.strong
info.default|color.status.info.default
info.subtle|color.status.info.subtle
info.strong|color.status.info.strong
danger.subtle|color.status.danger.subtle
danger.strong|color.status.danger.strong
a.selected|color.action.selected
a.secondary|color.action.secondary.default
stale.text|color.data-confidence.stale.text
stale.indicator|color.data-confidence.stale.indicator
stale.surface|color.data-confidence.stale.surface"""))


def rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def hexs(c: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{min(255, max(0, round(v))):02X}" for v in c)


def ratio(fg: str, bg: str) -> float:
    return float(contrast_check.contrast_ratio(rgb(fg), rgb(bg)))


def col(theme: str, short: str) -> str:
    return str(T[theme][TOK.get(short, short)])


def over(theme: str, short: str, alpha: float, under: str) -> str:
    """Ink drawn at `alpha` over a surface: the colour the eye meets (E22-D03's method)."""
    top, base = rgb(col(theme, short)), rgb(col(theme, under))
    mix = [alpha * t + (1 - alpha) * u for t, u in zip(top, base, strict=True)]
    return hexs((mix[0], mix[1], mix[2]))


def fg_of(theme: str, spec: str, under: str) -> str:
    """`tok` or `tok@alpha` (composited over `under`)."""
    if "@" in spec:
        tok, a = spec.split("@")
        return over(theme, tok, float(a), under)
    return col(theme, spec)


def fmt3(vals: list[float], bar: float | None) -> str:
    """Two decimals; four where a value would round onto its bar (the unrounded compare)."""
    out = []
    shown = 3.0 if bar is None else bar  # a decorative / reported row prints against the 3:1 bar
    for v in vals:
        if round(v, 2) == shown and abs(v - shown) > 1e-9:
            out.append(f"{v:.4f}")
        else:
            out.append(f"{v:.2f}")
    return " / ".join(out)


# A. the tokens the spec binds: every backticked token-like name must resolve in every theme
TOKEN_RX = re.compile(
    r"`((?:color|type|space|size|radius|border|motion|opacity|font|elevation)\.[a-z0-9.-]+)`"
)


def tokens(spec: str) -> dict[str, Any]:
    names = sorted(set(TOKEN_RX.findall(spec)))
    missing = [n for n in names if any(n not in T[t] for t in THEMES)]
    return {"named": len(names), "missing": missing}


# B. the matrix: id | element | fg | bg | role | pairs.mjs status
PAIRS = rows_of(
    """P1|SCR-055 readout number and unit; SCR-056 cells; SCR-057 evidence number (t1 on raised)|t1|raised|text|registered
P2|baseline sentence, second unit line, Delayed tag, T2 reason, breakdown labels (t2 on raised)|t2|raised|text|registered
P3|window tag, tick labels, T2 label, broken status word, inset kicker (t3 on raised)|t3|raised|text|registered
P4|band chip neutral word (CMP-011 neutral)|t2|n.subtle|text|unregistered (E05)
P5|band chip extreme word (CMP-011 warning)|t1|warn.subtle|text|registered
P6|band chip warning glyph (CMP-011 warning)|warn.strong|warn.subtle|non-text|registered
P7|extreme segment and alert line on the panel (decorative: thickness and label carry)|warn.default|raised|decorative|never (E25-D05 CR-5)
P8|extreme segment and alert line on the CMP-187 pane|warn.default|canvas|non-text|PROPOSED (CR-1)
P9|usual-rate line and ticks on the pane; broken-zone hatch|t3|canvas|non-text|PROPOSED (CR-1)
P10|needle on the pane (non-text, passes 3:1 too); odd-row cells and zone label on the canvas (text, the stricter bar graded)|t1|canvas|text|registered
P11|strip line on the panel|t2|raised|non-text|registered
P12|strip line on the pane|t2|canvas|non-text|registered
P13|side split buy half, SCR-056 buy glyph, CMP-134 buy glyph (on raised)|buy|raised|non-text|PROPOSED (CR-1)
P14|side split sell half, SCR-056 sell glyph, CMP-134 sell glyph (on raised)|sell|raised|non-text|PROPOSED (CR-1)
P15|CMP-132 buy outline and glyph on the canvas|buy|canvas|non-text|registered
P16|CMP-132 sell outline and glyph on the canvas|sell|canvas|non-text|registered
P17|CMP-239 stale text|stale.text|stale.surface|text|registered
P18|CMP-239 stale indicator dot and strong-chip outline|stale.indicator|stale.surface|non-text|registered
P19|focus ring on raised|ring|raised|non-text|registered
P20|focus ring on the canvas|ring|canvas|non-text|registered
P21|window control selected segment label (CMP-003)|t1|a.selected|text|registered
P22|window control selected 2 px inner outline (CMP-003)|b.selected|a.selected|non-text|PROPOSED (CR-1)
P23|CMP-001 secondary label (Sync footprint, Keep separate, Recompute history T1)|t1|a.secondary|text|PROPOSED (CR-1)
P24|sync prompt title (CMP-028 info); CMP-227 word; regime pill word|t1|info.subtle|text|registered
P25|sync prompt edge and glyph (CMP-028 info)|info.strong|info.subtle|non-text|PROPOSED (CR-1)
P26|CMP-227 and regime pill glyph on the fill|info.default|info.subtle|non-text|PROPOSED (CR-1)
P27|CMP-227 outline, regime pill outline, CMP-032 filled dot (on raised)|info.default|raised|non-text|PROPOSED (CR-1)
P28|CMP-227 marker on the canvas|info.default|canvas|non-text|PROPOSED (CR-1)
P29|CMP-032 empty dot outline|t3|raised|non-text|registered
P30|column header label (CMP-049 header)|t1|hover|text|PROPOSED (CR-1)
P31|selected row and selected card text|t1|selected|text|registered
P32|CMP-132 selected outline on the canvas|b.selected|canvas|non-text|PROPOSED (CR-1)
P33|panel banner title (CMP-028 connection-disconnected)|t1|danger.subtle|text|registered
P34|panel banner edge and glyph (CMP-028 connection-disconnected)|danger.strong|danger.subtle|non-text|PROPOSED (CR-1)
P35|CMP-134 flat card border; T2 hairline; chip stroke (decorative)|b.default|raised|decorative|—
P36|last-price divider hairline (decorative: the price carries)|b.strong|raised|decorative|—
P37|CMP-132 active buy fill (decorative: the outline carries)|buy.subtle|canvas|decorative|—
P38|CMP-132 active sell fill (decorative: the outline carries)|sell.subtle|canvas|decorative|—
P39|CMP-132 broken outline (decorative: the hatch and the word carry)|b.default|canvas|decorative|—
P40|stale 0.85 dim: t1 on raised|t1@0.85|raised|reported|—
P41|stale 0.85 dim: t2 on raised|t2@0.85|raised|reported|—
P42|stale 0.85 dim: t3 on raised|t3@0.85|raised|reported|—
P43|stale 0.85 dim: t1 on the canvas|t1@0.85|canvas|reported|—
P44|stale 0.85 dim: buy on the canvas (E22-D03 reproduced)|buy@0.85|canvas|reported|—
P45|stale 0.85 dim: sell on the canvas (E22-D03 reproduced)|sell@0.85|canvas|reported|—
P46|recomputing rows: t1 at opacity.muted on raised (D02 S56-3, reported)|t1@0.7|raised|reported|—
P47|CMP-132 tested buy outline at opacity.muted on the canvas (reported)|buy@0.7|canvas|reported|—
P48|CMP-132 tested sell outline at opacity.muted on the canvas (reported)|sell@0.7|canvas|reported|—
P49|rejected: the side word in the sell hue on raised|sell|raised|rejected-text|—
P50|rejected: the side word in the buy hue on raised|buy|raised|rejected-text|—
P51|rejected: a hued regime word (info.strong on info.subtle)|info.strong|info.subtle|rejected-text|—
P52|rejected: a hued extreme word (warning.strong on warning.subtle)|warn.strong|warn.subtle|rejected-text|—
P53|rejected: D05's 2 px warning outline on the chip (the light value)|warn.default|raised|rejected-non-text|—"""
)

# Reproductions (to the hundredth; 2.9992 to the ten-thousandth): E25-D05 §12.1, E22-D03 §8.1,
# E25-D02 §16. A lost reproduction is a FAIL: the sibling specs and this one must print one value.
REPRO: dict[str, tuple[float, float, float]] = {
    "P1": (14.35, 15.62, 16.25),
    "P2": (8.81, 8.98, 14.35),
    "P3": (5.62, 5.92, 11.21),
    "P4": (7.50, 8.26, 12.22),
    "P5": (9.86, 15.62, 11.16),
    "P6": (7.56, 4.11, 7.56),
    "P7": (7.98, 2.9992, 7.98),
    "P8": (8.45, 3.22, 8.45),
    "P9": (5.96, 6.36, 11.87),
    "P10": (15.20, 16.78, 17.21),
    "P12": (9.33, 9.65, 15.20),
    "P13": (7.03, 4.68, 9.40),
    "P14": (4.42, 4.51, 7.17),
    "P15": (7.45, 5.03, 9.96),
    "P16": (4.68, 4.85, 7.60),
    "P17": (10.69, 7.37, 17.42),
    "P18": (13.36, 3.37, 13.36),
    "P19": (6.66, 5.86, 17.30),
    "P20": (7.05, 6.30, 18.32),
    "P24": (10.74, 15.44, 12.16),
    "P26": (4.64, 3.44, 4.64),
    "P27": (6.20, 3.48, 6.20),
    "P28": (6.57, 3.74, 6.57),
    "P30": (12.22, 14.37, 13.83),
    "P31": (10.17, 12.82, 11.51),
    "P32": (5.18, 4.44, 7.05),
    "P35": (1.41, 1.22, 2.86),
    "P44": (5.69, 3.80, 7.44),
    "P45": (3.66, 3.89, 5.77),
    "P51": (7.30, 4.34, 7.30),
}


def matrix(problems: list[str]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    fails = gated = 0
    repro_ok = repro_n = 0
    for pid, element, fg, bg, role, reg in PAIRS:
        bar = BAR[role]
        vals = [ratio(fg_of(t, fg, bg), col(t, bg)) for t in THEMES]
        verdict = "—"
        if role in GATED:
            gated += 1
            bad = [t for t, v in zip(THEMES, vals, strict=True) if v < (bar or 0)]
            verdict = "PASS" if not bad else "FAIL " + ", ".join(bad)
            if bad:
                fails += 1
                problems.append(f"contrast FAIL {pid} {element}: {fmt3(vals, bar)}")
        elif role.startswith("rejected"):
            bad = [t for t, v in zip(THEMES, vals, strict=True) if v < (bar or 0)]
            verdict = "rejected: fails " + ", ".join(bad) if bad else "rejected by design"
        else:
            verdict = role
        if pid in REPRO:
            repro_n += 1
            exp = REPRO[pid]
            ok = all(
                abs(round(v, 4 if e == 2.9992 else 2) - e) < 1e-9
                for v, e in zip(vals, exp, strict=True)
            )
            repro_ok += int(ok)
            if not ok:
                problems.append(f"reproduction lost {pid}: {fmt3(vals, bar)} vs {exp}")
        rows.append(
            {
                "id": pid,
                "element": element,
                "fg": TOK.get(fg.split("@")[0], fg)
                + (("@" + fg.split("@")[1]) if "@" in fg else ""),
                "bg": TOK[bg],
                "role": role,
                "dark": vals[0],
                "light": vals[1],
                "hc": vals[2],
                "text": fmt3(vals, bar),
                "verdict": verdict,
                "pairs_mjs": reg,
            }
        )
    return {
        "pairs": len(rows),
        "gated": gated,
        "fail": fails,
        "repro_ok": repro_ok,
        "repro_n": repro_n,
        "rows": rows,
    }


# C. the E25 number-format sheet (BQ-04, RULED as the format of record)
THIN = "\u2009"  # the typeset space before % (the text of E25-D02 and this spec carries U+0020)
MINUS = "\u2212"
SIGMA = "\u03c3"


def fmt_int(v: float) -> str:
    return f"{round(v):,d}"


def fmt_trades(v: float) -> str:
    return f"{fmt_int(v)} trades/s"


def fmt_abbrev(v: float) -> str:
    for cut, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if v >= cut:
            return f"{v / cut:.1f}{suffix}"
    return fmt_int(v)


def fmt_notional(v: float) -> str:
    return f"{fmt_abbrev(v)} USDT/s"


def fmt_z(z: float) -> str:
    word = "below" if z < 0 else "above"
    return f"{abs(z):.1f} {SIGMA} {word}"


def fmt_conf(c: float) -> str:
    return f"{c:.2f}"


def fmt_ratio(pct: float, typeset: bool = False) -> str:
    return f"{fmt_int(pct)}{THIN if typeset else ' '}%"


def fmt_price(p: float, decimals: int = 1) -> str:
    return f"{p:,.{decimals}f}"


def fmt_range(a: float, b: float) -> str:
    return f"{fmt_int(a)}\u2013{fmt_int(b)}"


def fmt_warmup(sec: int) -> str:
    return f"{sec // 60} min {sec % 60} s"


def fmt_age(minutes: int) -> str:
    return f"{minutes} m"


def fmt_distance(ticks: int) -> str:
    return f"{fmt_int(abs(ticks))} ticks {'below' if ticks < 0 else 'above'}"


def fmt_value(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s if s else "0"


def fmt_weight(w: float) -> str:
    return f"{w:.2f}"


def fmt_contribution(c: float) -> str:
    sign = MINUS if c < 0 else "+"
    return f"{sign}{abs(c):.2f}"


SAMPLES: list[tuple[str, str]] = [
    ("trades 42", fmt_trades(42)),
    ("trades 312", fmt_trades(312)),
    ("trades 1240", fmt_trades(1240)),
    ("notional 950", fmt_notional(950)),
    ("notional 13 400", fmt_notional(13_400)),
    ("notional 1 234 567", fmt_notional(1_234_567)),
    ("notional 999 949 999", fmt_notional(999_949_999)),
    ("notional 2 000 000 000", fmt_notional(2_000_000_000)),
    ("z 3.1", fmt_z(3.1)),
    ("z -1.2", fmt_z(-1.2)),
    ("confidence 0.71", fmt_conf(0.71)),
    ("confidence 0.305", fmt_conf(0.305)),
    ("ratio 420", fmt_ratio(420)),
    ("ratio 2000", fmt_ratio(2000)),
    ("price 63118.0", fmt_price(63118.0)),
    ("range 64060-64090", fmt_range(64060, 64090)),
    ("warm-up 292 s", fmt_warmup(292)),
    ("age 12", fmt_age(12)),
    ("distance -150", fmt_distance(-150)),
    ("distance 350", fmt_distance(350)),
    ("signal value 31", fmt_value(31)),
    ("signal value 0.61", fmt_value(0.61)),
    ("signal value 1.234", fmt_value(1.234)),
    ("signal weight 0.25", fmt_weight(0.25)),
    ("signal contribution 0.18", fmt_contribution(0.18)),
    ("signal contribution -0.05", fmt_contribution(-0.05)),
]
ABBREV_MAX = 8  # mono chars for the abbreviated notional (E22-D03's Notional column)
NUM_LG_PX = 16  # type.num.lg = font.size.lg
MONO_EM = 0.62  # the lane's mono advance
PRIMARY_LINE = "312 trades/s over 5 s"  # the readout's mono primary line at a three-digit burst
# E25-D02 §11 derives the 401 px SCR-055 minimum from the controls row; its tool excludes the
# readout ("The readout may always wrap."), so the primary line's width is measured, never added.


def formats(problems: list[str]) -> dict[str, Any]:
    abbrev = [fmt_abbrev(v) for v in (950, 13_400, 1_234_567, 999_949_999, 2_000_000_000)]
    worst = max(len(a) for a in abbrev)
    if worst > ABBREV_MAX:
        problems.append(f"notional abbreviation exceeds {ABBREV_MAX} mono chars: {worst}")
    if int(T["dark"]["font.size.lg"]) != NUM_LG_PX:
        problems.append("type.num.lg is no longer 16 px; the readout width line is stale")
    char_px = round(NUM_LG_PX * MONO_EM)
    return {
        "samples": SAMPLES,
        "abbrev_max_chars": worst,
        "readout_char_px": char_px,
        "primary_line_chars": len(PRIMARY_LINE),
        "primary_line_px": math.ceil(len(PRIMARY_LINE) * NUM_LG_PX * MONO_EM),
        "thin_space": "U+2009",
        "minus": "U+2212",
    }


# D. greyscale and deuteranopia (cvd_sim.py's maths on single colours)
DEUT = (
    (0.367322, 0.860646, -0.227968),
    (0.280085, 0.672501, 0.047413),
    (-0.011820, 0.042940, 0.968881),
)


def grey(h: str) -> str:
    r, g, b = rgb(h)
    y = r * 0.299 + g * 0.587 + b * 0.114
    return hexs((y, y, y))


def deut(h: str) -> str:
    c = rgb(h)
    out = tuple(sum(m * v for m, v in zip(row, c, strict=True)) for row in DEUT)
    return hexs((out[0], out[1], out[2]))


CVD_PAIRS = rows_of("""buy vs sell (side hue; glyph + word carry)|buy|sell
info vs raised (the pill; outline + glyph + word carry)|info.default|raised
warning vs raised (the segment; thickness + label carry)|warn.default|raised
selected outline vs canvas (the 2 px outline carries)|b.selected|canvas
stale indicator vs stale surface (dot + word carry)|stale.indicator|stale.surface""")
E22_D03_CVD = {  # E22-D03 §8.3 dark: hexes and the hue separation normal / greyscale / deuteranopia
    "buy": ("#878787", "#9F905E"),
    "sell": ("#787878", "#81744B"),
    "sep": (1.59, 1.23, 1.46),
}


def cvd(problems: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {"pairs": []}
    for label, a, b in CVD_PAIRS:
        per_theme = {}
        for t in THEMES:
            ha, hb = col(t, a), col(t, b)
            per_theme[t] = {
                "a": ha,
                "b": hb,
                "a_grey": grey(ha),
                "a_deut": deut(ha),
                "b_grey": grey(hb),
                "b_deut": deut(hb),
                "sep": (ratio(ha, hb), ratio(grey(ha), grey(hb)), ratio(deut(ha), deut(hb))),
            }
        out["pairs"].append({"pair": label, "a": TOK[a], "b": TOK[b], "themes": per_theme})
    d = out["pairs"][0]["themes"]["dark"]
    got = (d["a_grey"], d["a_deut"], d["b_grey"], d["b_deut"])
    exp = E22_D03_CVD["buy"] + E22_D03_CVD["sell"]
    sep = tuple(round(v, 2) for v in d["sep"])
    ok = got == exp and sep == E22_D03_CVD["sep"]
    out["e22_d03_reproduced"] = ok
    if not ok:
        problems.append(f"E22-D03 §8.3 greyscale / deuteranopia not reproduced: {got} {sep}")
    return out


# E. the board plan and the spec's id tables
BOARD_RX = re.compile(r"^\| (0[1-9]|1[0-9]) +\| `")
S_RX = {"S55": re.compile(r"^\| S55-\d+ "), "S56": re.compile(r"^\| S56-\d+ ")}
S_RX["S57"] = re.compile(r"^\| S57-\d+ ")
EXPECT_STATES = {"S55": 14, "S56": 13, "S57": 12}  # E25-D02 §9 (the frame counts, carried)
MAX_BOARDS = 10


def cells(ln: str) -> list[str]:
    return [c.strip() for c in ln.strip().strip("|").split("|")]


def section(spec: str, start: str, end: str) -> str:
    i, j = spec.find(start), spec.find(end)
    return spec[i:j] if i >= 0 and j > i else ""


def boards(spec: str, problems: list[str]) -> dict[str, Any]:
    rows = [cells(ln) for ln in spec.splitlines() if BOARD_RX.match(ln)]
    slugs = [r[1] for r in rows]
    themes = [r[3].lower() for r in rows]
    twins = sum(1 for t in themes if t.startswith("light"))
    if len(rows) > MAX_BOARDS:
        problems.append(f"board plan: {len(rows)} boards, over {MAX_BOARDS}")
    if twins > len(rows) // 3:
        problems.append(f"board plan: {twins} light twins of {len(rows)}, over one third")
    if len(set(slugs)) != len(slugs):
        problems.append("board plan: a slug repeats")
    pending = [r for r in rows if len(r) < 6 or r[5] != "PENDING"]
    if pending:
        problems.append("board plan: a board row is not PENDING in PR 1")
    if len(rows) <= MAX_BOARDS and f"{len(rows)} boards" not in spec:
        problems.append(f"board plan: the spec does not state {len(rows)} boards")
    if twins <= len(rows) // 3 and f"{twins} light twins" not in spec:
        problems.append(f"board plan: the spec does not state {twins} light twins")
    return {"boards": len(rows), "light_twins": twins, "slugs": slugs}


def counts(spec: str, problems: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, rx in S_RX.items():
        out[k] = sum(1 for ln in spec.splitlines() if rx.match(ln))
        if out[k] != EXPECT_STATES[k]:
            problems.append(f"{k} rows: {out[k]} (E25-D02 carries {EXPECT_STATES[k]})")
    for k, rx in (
        ("M", r"^\| M-\d+ "),
        ("A", r"^\| A-\d+ "),
        ("CR", r"^\| CR-\d+ "),
        ("HO", r"^\| HO-\d+ "),
        ("AN", r"^\| AN-\d+ "),
        ("C", r"^\| D03-C\d+ "),
        ("G", r"^\| D03-G\d+ "),
        ("H", r"^\| H-\d+ "),
    ):
        out[k] = sum(1 for ln in spec.splitlines() if re.match(rx, ln))
    return out


# F. the spec's tables and strings
CHIP_RULES = rows_of(
    """Band chip, calm / elevated|color.neutral.subtle|color.border.default|color.text.secondary
Band chip, extreme|color.status.warning.subtle|color.text.primary|color.status.warning.strong
Regime chip|color.status.info.subtle|color.status.info.default|color.text.primary
Stale chip (CMP-239)|color.data-confidence.stale.surface|color.data-confidence.stale.text|color.data-confidence.stale.indicator
Confidence dots (CMP-032)|color.status.info.default|color.text.tertiary|type.ui.caption"""
)
NEGATED = re.compile(
    r"\b(no|never|not|forbidden|crossed out|drops?|dropped|rejected)\b", re.IGNORECASE
)
GLYPH_RX = re.compile(r"[\u2191\u2193\u2192\u25b2\u25bc^]|trend-up|trend-down|arrow", re.IGNORECASE)
SPOKEN_FORBIDDEN = ("/s", SIGMA, "5-min ", "5-min.")
MUST = (  # E25-D02 strings the hi-fi carries verbatim (changes no word)
    "Tape speed BTCUSDT",
    "42 trades/s over 5 s · 3.1 σ above the 5-min mean",
    "Warming up — 4 min 52 s to go",
    "Updates every 1 s, ×4 slower",
    "Detector error — last value 13:58:02",
    "0 /s · quiet",
    "Create alert from this threshold",
    "cooldown 60 s",
    "Imbalances BTCUSDT 1m",
    "Ratio ≥ 300 %",
    "Stack ≥ 3",
    "Sync footprint",
    "Create alert at this level",
    "no imbalances above 3:1 in this range",
    "Recomputing…",
    "History not recomputed",
    "Recompute history",
    "Recomputing history…",
    "History recomputed.",
    "Only the owner can change recording.",
    "Imbalance thresholds changed — apply the same to the footprint?",
    "Keep separate",
    "Nearest first",
    "Newest first",
    "Regime (estimated) BTCUSDT",
    "Trending up (estimated) · medium",
    "Insufficient data (estimated)",
    "Confidence 0.71 (sub-signal agreement)",
    "Confidence — not supplied",
    "210 of 512 bars",
    "Why this classification?",
    "transitions: — (no data source)",
    "Sensitivity — not in the contract",
    "Not available on this server — the stop-run detector is behind a feature flag",
    "Off — turn on in Detector settings",
    "Read-only while viewing as {user}.",
    "Your role can't change alerts.",
    "Read-only — your role can't change settings.",
    "Sell stack ×3, 64,060 to 64,090, ratio 310 percent, tested, 350 ticks above",
)
# the patterns are assembled so that this file does not itself carry the words it forbids
FORBIDDEN = {
    "local path": re.compile("/ho" + r"me/\w+|/Us" + r"ers/\w+|C:\\\\"),
    "worker name": re.compile(r"\b[a-z]{2,5}-worker-\d+\b|wt-no" + r"tes|\bAgent [A-C]\b"),
    "host or url": re.compile(r"https?://|penpot\.[a-z]|\.candleviewer\.com"),
    "colour emoji": re.compile("[\U0001f300-\U0001faff\u2600-\u26ff]"),
    "page id or uuid": re.compile(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
    ),
}
RULE_RX = re.compile(r"\bC-\d+\.\d+\b")


def window(text: str, i: int, j: int, span: int = 60) -> str:
    """The text around a match: a pattern word is negated only by a word near it."""
    return text[max(0, i - span) : j + span]


def table_gates(spec: str, problems: list[str]) -> dict[str, Any]:
    lines = spec.splitlines()
    out: dict[str, Any] = {}
    # chips carry exactly their catalogue binding
    for name, *toks in CHIP_RULES:
        row = next((ln for ln in lines if ln.startswith("| ") and cells(ln)[0] == name), None)
        if row is None:
            problems.append(f"chip binding row missing: {name}")
            continue
        lost = [t for t in toks if f"`{t}`" not in row]
        if lost:
            problems.append(f"chip binding {name} lacks {lost}")
    # no dashed line on SCR-055; no trend glyph on SCR-057
    s055 = section(spec, "\n## 3.", "\n## 4.")
    s057 = section(spec, "\n## 5.", "\n## 6.")
    if not s055 or not s057:
        problems.append("sections 3 (SCR-055) or 5 (SCR-057) not found")
    if any(
        not NEGATED.search(window(s055, m.start(), m.end())) for m in re.finditer("dashed", s055)
    ):
        problems.append("SCR-055 section draws a dashed line")
    if any(not NEGATED.search(window(s057, m.start(), m.end())) for m in GLYPH_RX.finditer(s057)):
        problems.append("SCR-057 section draws a trend glyph or arrow")
    # motion pairs: every row has both cells; exactly two timed rows; the flashes row reads 0
    m_rows = [cells(ln) for ln in lines if re.match(r"^\| M-\d+ ", ln)]
    timed = [r[0] for r in m_rows if "motion.duration." in r[2]]
    out["motion_rows"] = len(m_rows)
    out["timed_rows"] = timed
    if any(not r[2] or not r[3] for r in m_rows):
        problems.append("motion table: a row lacks its motion-safe or motion-reduce cell")
    if len(timed) != 2:
        problems.append(f"motion table: {len(timed)} timed transitions, the spec allows two")
    flash = [r for r in m_rows if "flash" in r[1].lower()]
    if not flash or not all(r[2].startswith("0 flashes") for r in flash):
        problems.append("motion table: the flash row does not read 0 flashes")
    # announcements: the spoken forms only
    an_rows = [cells(ln) for ln in lines if re.match(r"^\| AN-\d+ ", ln)]
    out["announcement_rows"] = len(an_rows)
    for r in an_rows:
        if any(f in r[2] for f in SPOKEN_FORBIDDEN):
            problems.append(f"announcement {r[0]} is not in the spoken form")
    # E25-D02 strings verbatim
    missing = [s for s in MUST if s not in spec]
    problems += [f"E25-D02 string missing: {s!r}" for s in missing]
    out["must"] = len(MUST)
    # hygiene and rule ids
    for name, rx in FORBIDDEN.items():
        if rx.search(spec):
            problems.append(f"hygiene: {name}")
    constitution = CONSTITUTION.read_text(encoding="utf-8")
    ids = sorted(set(RULE_RX.findall(spec)))
    absent = [i for i in ids if not re.search(rf"\b{re.escape(i)}\b", constitution)]
    problems += [f"{i} not in CONSTITUTION.md" for i in absent]
    out["rule_ids"] = len(ids)
    return out


# G. drift: every number the tool prints that the spec must carry
def drift(
    spec: str, mx: dict[str, Any], fm: dict[str, Any], bd: dict[str, Any], cv: dict[str, Any]
) -> list[str]:
    need: list[str] = []
    for r in mx["rows"]:
        need.append(r["text"])
    need += [f"{mx['pairs']} pairs × 3 themes", f"{mx['gated']} gated", f"FAIL {mx['fail']}"]
    need.append(f"{mx['repro_ok']} of {mx['repro_n']} reproductions")
    need += [s for _, s in fm["samples"]]
    need += [f"{fm['readout_char_px']} px", f"{fm['primary_line_px']} px"]
    need.append(f"{fm['primary_line_chars']} mono chars")
    d = cv["pairs"][0]["themes"]
    for t in THEMES:
        sep = d[t]["sep"]
        need.append(f"{sep[0]:.2f} / {sep[1]:.2f} / {sep[2]:.2f}")
    return [n for n in need if n not in spec]


def evaluate(spec: str) -> tuple[list[str], dict[str, Any]]:
    problems: list[str] = []
    out: dict[str, Any] = {}
    out["tokens"] = tokens(spec)
    problems += [f"token does not resolve: {n}" for n in out["tokens"]["missing"]]
    out["matrix"] = matrix(problems)
    out["formats"] = formats(problems)
    out["cvd"] = cvd(problems)
    out["boards"] = boards(spec, problems)
    out["counts"] = counts(spec, problems)
    out["gates"] = table_gates(spec, problems)
    out["drift"] = drift(spec, out["matrix"], out["formats"], out["boards"], out["cvd"])
    problems += [f"drift: the spec does not carry {n!r}" for n in out["drift"]]
    out["problems"] = problems
    return problems, out


# ------------------------------------------------------------------ self-test -------------------
MUTATIONS: tuple[tuple[str, ...], ...] = (  # (name, old, new[, occurrences])
    ("a contrast value drifts", "14.35 / 15.62 / 16.25", "14.36 / 15.62 / 16.25"),
    ("a token name is invented", "`color.neutral.subtle` fill", "`color.neutral.subtler` fill"),
    ("a format sample drifts", "`999.9M USDT/s`", "`999.9 M USDT/s`"),
    (
        "an eleventh board",
        "| 10  | `contrast-cvd-motion-ds-requests`",
        "| 11  | `extra` | x | dark | — | PENDING |\n| 10  | `contrast-cvd-motion-ds-requests`",
    ),
    (
        "an E25-D02 string changes",
        "apply the same to the footprint?",
        "apply the same to the footprint.",
    ),
    (
        "a dashed line on SCR-055",
        "a **solid** 1 px `color.status.warning.default` line labelled",
        "a dashed 1 px `color.status.warning.default` line labelled",
    ),
    (
        "a trend glyph on SCR-057",
        "The pill text carries the regime word alone.",
        "The pill text carries the regime word with a \u25b2 trend glyph.",
    ),
    (
        "a chip loses its binding",
        "`color.status.warning.subtle` (extreme fill)",
        "`color.status.warning.default` (extreme fill)",
    ),
    (
        "a third timed transition",
        "instant (no height animation)",
        "`motion.duration.fast` reveal (no height animation)",
    ),
    (
        "an announcement in the written form",
        "3.1 sigma above the 5-minute mean",
        "3.1 \u03c3 above the 5-minute mean",
    ),
    ("a flash appears", "| 0 flashes (", "| 1 flash ("),
    ("a local path leaks", "## 20. Summary", "## 20. Summary (/ho" + "me/someone/notes)"),
    ("a state row is lost", "| S57-12 |", "| S57-12x |"),
    (
        "two more light twins (over one third)",
        "| dark              | —      | PENDING |",
        "| light             | —      | PENDING |",
        "2",
    ),
    ("a dangling rule cite", "Honesty (C-2.13)", "Honesty (C-9.99)"),
    ("a board id is not PENDING", "| —      | PENDING |\n| 02  |", "| —      | DRAWN   |\n| 02  |"),
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def self_test(spec_path: Path) -> int:
    spec = read(spec_path)
    before = spec_path.read_bytes()
    base, _ = evaluate(spec)
    ok = not base
    print(f"clean spec: rc {1 if base else 0} ({len(base)} problem(s))")
    for p in base:
        print(f"  {p}")
    seen: dict[str, str] = {}
    for no, (name, old, new, *rest) in enumerate(MUTATIONS, start=1):
        times = int(rest[0]) if rest else 1
        if spec.count(old) < times:
            ok = False
            print(f"mutation {no:02d} {name}: DOES NOT APPLY (the text to mutate is gone)")
            continue
        got, _ = evaluate(spec.replace(old, new, times))
        fresh = [p for p in got if p not in base]
        rc = 1 if got else 0
        dup = [p for p in fresh if p in seen]
        caught = rc == 1 and len(fresh) == 1 and not dup
        ok = ok and caught
        flag = "" if caught else (" - DUPLICATE FAIL" if dup else " - NOT CAUGHT EXACTLY ONCE")
        print(f"mutation {no:02d} {name}: rc {rc}, {len(fresh)} new FAIL{flag}")
        for p in fresh:
            print(f"  {p}")
            seen.setdefault(p, name)
    restored, _ = evaluate(spec)
    same = spec_path.read_bytes() == before
    ok = ok and not restored and same
    print(
        f"restore: rc {1 if restored else 0}; spec file byte-identical: {same}; "
        f"--self-test: {'ok' if ok else 'FAIL'} - {len(MUTATIONS)} mutations in memory, "
        f"{len(seen)} distinct FAILs"
    )
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    argv = sys.argv[1:] if argv is None else argv
    spec_path = SPEC
    for flag in ("--check", "--self-test"):
        if flag in argv:
            i = argv.index(flag)
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                spec_path = Path(argv[i + 1])
    if "--self-test" in argv:
        return self_test(spec_path)
    spec = read(spec_path) if spec_path.exists() else ""
    problems, out = evaluate(spec)
    if "--json" in argv:
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    else:
        mx = out["matrix"]
        print(f"A. tokens named {out['tokens']['named']}, missing {out['tokens']['missing']}")
        print(
            f"B. matrix: {mx['pairs']} pairs × 3 themes, {mx['gated']} gated, FAIL {mx['fail']}, "
            f"{mx['repro_ok']} of {mx['repro_n']} reproductions"
        )
        for r in mx["rows"]:
            print(
                f"   {r['id']:<4} {r['role']:<17} {r['text']:<24} {r['verdict']:<28} {r['element']}"
            )
        print("C. formats:")
        for k, s in out["formats"]["samples"]:
            print(f"   {k:<28} {s}")
        fm = out["formats"]
        print(
            f"   abbreviation <= {fm['abbrev_max_chars']} chars; a mono char at type.num.lg is "
            f"{fm['readout_char_px']} px; the primary line at {fm['primary_line_chars']} mono chars "
            f"is {fm['primary_line_px']} px"
        )
        print("D. CVD (dark):")
        for p in out["cvd"]["pairs"]:
            d = p["themes"]["dark"]
            sep = d["sep"]
            print(
                f"   {p['pair']}: {d['a']} -> {d['a_grey']} / {d['a_deut']}; {d['b']} -> "
                f"{d['b_grey']} / {d['b_deut']}; separation {sep[0]:.2f} / {sep[1]:.2f} / {sep[2]:.2f}"
            )
        print(f"E. boards {out['boards']['boards']}, light twins {out['boards']['light_twins']}")
        print(f"F. counts {out['counts']}; gates {out['gates']}")
        print(f"G. drift {len(out['drift'])}")
        for p in problems:
            print(f"FAIL {p}")
        print(f"rc {1 if problems else 0}")
    if "--check" in argv or "--json" in argv:
        return 1 if problems else 0
    own = ("contrast FAIL", "reproduction lost", "notional abbreviation", "type.num.lg", "E22-D03")
    return 1 if [p for p in problems if p.startswith(own)] else 0


if __name__ == "__main__":
    raise SystemExit(main())
