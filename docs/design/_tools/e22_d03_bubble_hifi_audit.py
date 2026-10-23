"""E22-D03 hi-fi audit: every number the SCR-053 hi-fi spec and the CMP-112 entry claim, computed.

Standalone, offline, stdlib only (`python3 -I`). Themes resolve exactly as
`packages/ui/tokens/tests/verify_tokens.py` resolves them; contrast is `contrast_ratio()` from
`docs/design/_tools/contrast_check.py`; the radius laws, the memo 3.9 simulation and the scrim
composition are the functions of `docs/design/_tools/e22_d02_tape_wires_audit.py` (`radii`,
`simulate`, `scrimmed`, `resolve_theme`), imported through one loader and never re-implemented (its
module-level run builds nothing but its tables). This tool reads no fixture, contacts nothing and
imports nothing from the `candleviewer` package. Every section names its source and every ratio is
compared unrounded against its bar (4 decimals printed where a value would round onto a bar).

Usage: python3 -I docs/design/_tools/e22_d03_bubble_hifi_audit.py [--json] [--check]
       [--spec P] [--draft P]
Exit 1 on a gated contrast FAIL, a law that no longer reproduces E22-D02 / the memo, a derived
constant that no longer reproduces the anchors, a changed MISSING set, a lost `pairs.mjs`
registration or a failed string gate; `--check` also gates the printed numbers against the spec's
own sentences (section I) and exits 1 on drift. Reported rows (aged bands, scrim) and rejected
pairs (the validity-look label among them) never gate. Stdout is UTF-8.
"""

from __future__ import annotations

import argparse
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
THEMES = ("dark", "light", "high-contrast")
BAR: dict[str, float | None] = {"text": 4.5, "non-text": 3.0, "decorative": None}
BAR.update({"rej-t": 4.5, "rej-nt": 3.0, "reported": 3.0})
BAR.update({"reported-text": 4.5, "glyph": 3.0})


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(TOKENS / "tests"))
contrast_check = _load(TOOLS / "contrast_check.py", "contrast_check")
d02 = _load(TOOLS / "e22_d02_tape_wires_audit.py", "e22_d02_tape_wires_audit")
T: dict[str, dict[str, Any]] = d02.T  # the three themes, resolved as verify_tokens.py resolves them


def rows_of(txt: str, sep: str = "|") -> list[list[str]]:
    return [ln.split(sep) for ln in txt.strip().splitlines()]


TOK = dict(d02.TOK)
TOK_MORE = """app|color.surface.app
inverse|color.text.inverse
cvd.buy|color.cvd.buy
cvd.sell|color.cvd.sell
info.subtle|color.status.info.subtle
info.default|color.status.info.default
ring|color.focus.ring
b.subtle|color.border.subtle
n.subtle|color.neutral.subtle
warn.strong|color.status.warning.strong"""
TOK.update(dict(rows_of(TOK_MORE)))


def rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def hexs(c: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{min(255, max(0, round(v))):02X}" for v in c)


def ratio(fg: str, bg: str) -> float:
    return float(contrast_check.contrast_ratio(rgb(fg), rgb(bg)))


def col(theme: str, short: str) -> str:
    return str(T[theme][TOK.get(short, short)])


def over(theme: str, short: str, alpha: float, under: str = "canvas") -> str:
    """A mark drawn at `alpha` over a surface: the colour the eye meets (D02's `scrimmed()` method
    with the mark on top instead of the scrim)."""
    top, base = rgb(col(theme, short)), rgb(col(theme, under))
    mix = [alpha * t + (1 - alpha) * u for t, u in zip(top, base, strict=True)]
    return hexs((mix[0], mix[1], mix[2]))


# A. the laws (E22-D02 D21 at 4ce8f438; memo 3.5): r_min 3 -> r_max 24 px over 1x .. 4x the class's
# big threshold. The ticket's forms (T:46) are honoured as derived constants per class (D-1, BQ-11).
R_MIN, R_MAX, CAP_MULT, GLYPH_R = 3.0, 24.0, 4.0, 10.0
ANCHORS = (1.0, 1.5, 2.0, 3.0, 4.0)
D02_RADII = {  # E22-D02 line 249 / memo 3.5, to the tenth
    "sqrt": [3.0, 10.2, 14.1, 19.7, 24.0],
    "log": [3.0, 9.1, 13.5, 19.6, 24.0],
    "linear": [3.0, 6.5, 10.0, 17.0, 24.0],
}
D02_SIDES = {"r3": 5.3, "r10": 17.7, "r24": 42.5}
CLASSES = {"majors": 250_000, "mid-caps": 50_000, "new listing": 2_000}  # memo 3.5 (seeds, Q6)
R_MIN_CANDIDATES = (3.0, 4.0, 5.0)  # the r_min call D02 handed over (BQ-12)


def law(k: float, r_min: float = R_MIN, r_max: float = R_MAX) -> dict[str, float]:
    """The three laws for any r_min / r_max: at the D02 anchors `law(k)` equals `d02.radii(k)`."""
    span, u = r_max - r_min, (k - 1) / (CAP_MULT - 1)
    out = {
        "linear": r_min + span * u,
        "sqrt": math.sqrt(r_min**2 + (r_max**2 - r_min**2) * u),
        "log": r_min + span * math.log(k) / math.log(CAP_MULT),
    }
    return {name: round(min(r_max, max(r_min, v)), 1) for name, v in out.items()}


def ticket_constants(threshold: int) -> dict[str, float]:
    """The ticket's `linear: r = r_min + k*notional` and `log: r = r_min + k*ln(1 + notional/n0)`
    as constants of the class threshold T, written so the D02 anchors reproduce exactly:
    both laws take `notional - T` (the floor is the threshold, k = 1), `n0 = T`,
    `k_lin = (r_max - r_min) / (3 T)` px per USDT and `k_log = (r_max - r_min) / ln 4` px."""
    k_lin = (R_MAX - R_MIN) / ((CAP_MULT - 1) * threshold)
    k_log = (R_MAX - R_MIN) / math.log(CAP_MULT)
    return {"T": float(threshold), "n0": float(threshold), "k_lin": k_lin, "k_log": k_log}


def ticket_radius(law_name: str, notional: float, c: dict[str, float]) -> float:
    x = max(0.0, notional - c["T"])
    if law_name == "linear":
        r = R_MIN + c["k_lin"] * x
    elif law_name == "log":
        r = R_MIN + c["k_log"] * math.log(1 + x / c["n0"])
    else:  # sqrt: equal area per equal notional step
        r = math.sqrt(R_MIN**2 + (R_MAX**2 - R_MIN**2) * x / ((CAP_MULT - 1) * c["T"]))
    return round(min(R_MAX, max(R_MIN, r)), 1)


# B. the matrix (spec 8.1): element | fg | bg | role | note. Roles: text 4.5 / non-text 3 gated;
# glyph = the side glyph inside the mark (gated 3:1, the 4.5 bar also printed); reported /
# reported-text / rej-* / decorative never gate; a rejected row is graded at the bar of the role
# it would have had (rej-nt = non-text 3:1, rej-t = text 4.5:1). "alpha=" rows composite fg over bg.
PAIRS_TXT = """mark: buy disc on canvas (fresh)|buy|canvas|non-text|pairs.mjs registered
mark: sell square on canvas (fresh)|sell|canvas|non-text|pairs.mjs registered
mark: buy disc on app (overlay off-pane)|buy|app|non-text|pairs.mjs registered
mark: sell square on app|sell|app|non-text|pairs.mjs registered
mark: CVD palette buy on canvas|cvd.buy|canvas|non-text|pairs.mjs registered (E47-S06)
mark: CVD palette sell on canvas|cvd.sell|canvas|non-text|pairs.mjs registered (E47-S06)
cap outline: 2 px ring, the mark's hue on canvas|sell|canvas|non-text|2 px of canvas gap
aged band: buy at PROPOSED opacity.bubble.aged 0.8 over canvas|buy@0.8|canvas|non-text|D-5; CR-1
aged band: sell at PROPOSED opacity.bubble.aged 0.8 over canvas|sell@0.8|canvas|non-text|D-5; CR-1
aged alt: buy at opacity.muted 0.7 over canvas|buy@0.7|canvas|rej-nt|BQ-18 default; D03-Q1
aged alt: sell at opacity.muted 0.7 over canvas|sell@0.7|canvas|rej-nt|BQ-18 default; D03-Q1
aged alt: buy at opacity.disabled 0.45 over canvas|buy@0.45|canvas|rej-nt|never a band
aged alt: sell at opacity.disabled 0.45 over canvas|sell@0.45|canvas|rej-nt|never a band
stale: buy at the data-ink uniform 0.85 over canvas|buy@0.85|canvas|reported|E11-D06 D13
stale: sell at the data-ink uniform 0.85 over canvas|sell@0.85|canvas|reported|E11-D06 D13
stale + aged: buy at 0.8 x 0.85 = 0.68 over canvas|buy@0.68|canvas|reported|D13 pane-wide; logged
stale + aged: sell at 0.8 x 0.85 = 0.68 over canvas|sell@0.68|canvas|reported|D13 pane-wide; logged
glyph: text.inverse on the fresh buy fill|inverse|buy|glyph|E30-D02 D3 numbers
glyph: text.inverse on the fresh sell fill|inverse|sell|glyph|E30-D02 D3 numbers
glyph alt: text.primary on the fresh buy fill|t1|buy|rej-nt|the rejected reading
glyph alt: text.primary on the fresh sell fill|t1|sell|rej-nt|the rejected reading
glyph on the aged buy fill (0.8 over canvas)|inverse|buy@0.8|glyph|r >= 10 px only
glyph on the aged sell fill (0.8 over canvas)|inverse|sell@0.8|glyph|r >= 10 px only
label / badge: text.primary beside the mark, 1 px canvas halo|t1|canvas|text|CP21 / the x7 badge
label alt: text.inverse on the fresh fill (label inside)|inverse|sell|rej-t|not drawn (D-6)
legend row: text.primary on canvas|t1|canvas|text|CMP-199 row
legend row hidden: text.tertiary on canvas|t3|canvas|text|eye off
legend (estimated): text.primary on status.info.subtle|t1|info.subtle|text|E25-D05 12.1 reproduced
legend (estimated): info.default outline on canvas|info.default|canvas|non-text|CMP-227 outline
legend pair swatch: the 1 px border.strong outline on canvas|b.strong|canvas|decorative|CMP-037
neutral chips, corner badge: text.secondary on neutral.subtle|t2|n.subtle|text|CMP-011 neutral
tooltip title / labels: text.secondary on overlay|t2|overlay|text|CMP-197
tooltip values: text.primary on overlay|t1|overlay|text|CMP-197
tooltip hairline: border.default on overlay|b.default|overlay|decorative|CMP-197
focus ring on canvas (outside the 1 px canvas halo)|ring|canvas|non-text|E30-D02 D3 double ring
focus ring on raised (tape row / strip)|ring|raised|non-text|CMP-039
tape: words and numerics on raised|t1|raised|text|memo 3.8 row 1
tape: text on the tier-2 buy fill|t1|buy.subtle|text|memo 3.8
tape: text on the tier-2 sell fill|t1|sell.subtle|text|memo 3.8
tape: dimmed HH:MM: prefix on raised|t3|raised|text|tiers 0-1
tape: tertiary prefix on buy.subtle|t3|buy.subtle|rej-t|memo F4: undimmed on tier 2
tape: tertiary prefix on selected|t3|selected|rej-t|D02 D7: undimmed on the located row
tape: the side word in the sell hue on raised|sell|raised|rej-t|memo 3.8: the word is never hued
tape: buy glyph + accent on raised|buy|raised|non-text|D02 10
tape: sell glyph + accent on raised|sell|raised|non-text|D02 10
tape: buy glyph on buy.subtle|buy|buy.subtle|non-text|D02 10
tape: sell glyph on sell.subtle|sell|sell.subtle|non-text|D02 10
tape: located row text on selected|t1|selected|text|D02 S6
tape: Paused chip text on status.warning.subtle|t1|warn.subtle|text|CMP-011 warning
tape: Paused chip warning glyph on warning.subtle|warn.strong|warn.subtle|non-text|CMP-011 warning
tape: status row / readout text.secondary on raised|t2|raised|text|CP3
T2: full label text.tertiary + lock on raised|t3|raised|text|E09-D09 2.2
T2: reason text.secondary on raised|t2|raised|text|E09-D09 2.2
T2: menu item label text.tertiary on overlay|t3|overlay|text|CMP-056 / More menu
T2: menu notice text.secondary on overlay|t2|overlay|text|S23 menu notice line
T2: hairline border.default on raised|b.default|raised|decorative|hairline + text carry the fill
validity alt: an editable field's label at opacity.disabled|t1@0.45|raised|rej-t|D02 D28 (3)
S10 scrim: row text under opacity.scrim of app|t1|raised|scrim|D02-C15; BQ-13
S10 scrim: readout under the scrim|t2|raised|scrim|D02-C15; BQ-13
S10 scrim: HH:MM: prefix under the scrim|t3|raised|scrim|D02-C15; BQ-13
S10 strip: SCR-152 text on raised above the scrim|t1|raised|text|BQ-13 default"""
PAIRS = rows_of(PAIRS_TXT)
E25_12_1 = {"t1|info.subtle": [10.74, 15.44, 12.16]}  # E25-D05 12.1, to the hundredth
E30_D3 = {"inverse|buy": [7.87, 5.39, 10.51], "inverse|sell": [4.94, 5.20, 8.02]}  # E30-D02 D3
D02_14: dict[str, list[float]] = json.loads(  # E22-D02 14 (dark / light / hc), to the hundredth
    '{"t1|raised": [14.35, 15.62, 16.25], "t3|raised": [5.62, 5.92, 11.21],'
    ' "t1|warn.subtle": [9.86, 15.62, 11.16], "buy|canvas": [7.45, 5.03, 9.96],'
    ' "sell|canvas": [4.68, 4.85, 7.60], "t1|buy.subtle": [10.21, 15.41, 11.56],'
    ' "t1|sell.subtle": [12.06, 14.64, 13.66], "t2|overlay": [8.14, 8.26, 13.27],'
    ' "t1|overlay": [13.27, 14.37, 15.02], "t1|canvas": [15.20, 16.78, 17.21]}'
)
# C. greyscale / deuteranopia (D02 10, memo 3.9 reproduced through d02.simulate; extended to the
# light and high-contrast themes and to the CVD-safe pair, which only this spec draws).
CVD_TOKENS = ("buy", "sell", "buy.subtle", "sell.subtle", "cvd.buy", "cvd.sell", "canvas", "raised")
D02_10_HEX = rows_of("""buy|#878787|#9F905E
sell|#787878|#81744B
buy.subtle|#2C2C2C|#332E20
sell.subtle|#262626|#292517""")  # E22-D02 10: token | greyscale | deuteranopia (dark)
D02_10_SEP = {"hue": [1.59, 1.23, 1.46], "fill": [1.18, 1.08, 1.13]}
D02_10_MARKS = {"sell glyph on raised": [4.42, 3.94, 3.75]}
D02_10_MARKS["sell mark on canvas"] = [4.68, 4.17, 3.97]
D02_10_MARKS["sell glyph on sell.subtle"] = [3.71, 3.43, 3.31]
D02_10_MARKS["buy glyph on buy.subtle"] = [5.01, 3.89, 4.27]
MARKS = {
    "sell glyph on raised": ("sell", "raised"),
    "sell mark on canvas": ("sell", "canvas"),
    "buy glyph on raised": ("buy", "raised"),
    "buy mark on canvas": ("buy", "canvas"),
    "sell glyph on sell.subtle": ("sell", "sell.subtle"),
    "buy glyph on buy.subtle": ("buy", "buy.subtle"),
    "CVD buy mark on canvas": ("cvd.buy", "canvas"),
    "CVD sell mark on canvas": ("cvd.sell", "canvas"),
}
# D. every token the spec and the boards bind; the last seven are DS requests and must be MISSING
NAMED_TXT = """
color.surface.app color.surface.canvas color.surface.raised color.surface.overlay
color.surface.hover color.surface.selected color.text.primary color.text.secondary
color.text.tertiary color.text.inverse color.border.default color.border.strong color.focus.ring
color.buy.default color.buy.hc color.buy.subtle color.sell.default color.sell.hc color.sell.subtle
color.cvd.buy color.cvd.sell color.status.info.subtle color.status.info.default
color.status.warning.subtle color.status.warning.strong color.neutral.subtle size.icon
color.data-confidence.stale.text color.data-confidence.stale.indicator
color.data-confidence.disconnected.text color.data-confidence.disconnected.indicator
size.row.compact size.row.comfortable size.control.compact size.control.comfortable size.icon.sm
size.target.min space.1 space.2 space.3 space.inset.xs space.inset.sm space.inset.md radius.badge
radius.card radius.pill border.hairline border.thick border.focus elevation.popover
font.family.mono font.family.ui font.weight.regular font.weight.medium font.weight.bold
type.num.xs type.num.sm type.num.base type.ui.caption type.ui.label opacity.muted opacity.disabled
opacity.scrim motion.duration.instant motion.duration.fast motion.duration.normal
size.bubble.scale color.marker.default font.mono space.filterbar.gap
color.text.buy color.text.sell color.chart.pane.bg.default
"""
NAMED = NAMED_TXT.split()
EXPECT_MISSING = set(NAMED[-7:])
# E. tools/contrast/pairs.mjs: registered today (a lost registration fails); PROPOSED rows printed
REGISTERED = rows_of("""color.buy.default|color.surface.canvas
color.sell.default|color.surface.canvas
color.buy.default|color.surface.app
color.sell.default|color.surface.app
color.cvd.buy|color.surface.canvas
color.cvd.sell|color.surface.canvas
color.status.warning.strong|color.status.warning.subtle""")
PROPOSED = rows_of(  # D02-G5's seven rows, then this spec's own (D03-G5)
    """color.text.primary|color.buy.subtle|TEXT|D02-G5
color.text.primary|color.sell.subtle|TEXT|D02-G5
color.text.tertiary|color.sell.subtle|TEXT|D02-G5
color.buy.default|color.surface.raised|NON_TEXT|D02-G5
color.sell.default|color.surface.raised|NON_TEXT|D02-G5
color.buy.default|color.buy.subtle|NON_TEXT|D02-G5
color.sell.default|color.sell.subtle|NON_TEXT|D02-G5
color.text.inverse|color.buy.default|NON_TEXT|D03-G5 (the side glyph)
color.text.inverse|color.sell.default|NON_TEXT|D03-G5 (the side glyph)
color.text.primary|color.surface.canvas|TEXT|D03-G5 (label, badge, legend)
color.text.tertiary|color.surface.canvas|TEXT|D03-G5 (hidden legend row; E25-D05 CR-5 too)
color.text.secondary|color.surface.overlay|TEXT|D03-G5 (tooltip labels)
color.text.primary|color.surface.overlay|TEXT|D03-G5 (tooltip values)
color.status.info.default|color.surface.canvas|NON_TEXT|D03-G5 (E25-D05 CR-5 too)
color.focus.ring|color.surface.canvas|NON_TEXT|D03-G5 (the mirror's ring)"""
)
# F. string gates: the fixed aria-label format, the names, the tooltips, the legend, the T2 reasons
MUST = (
    "Big {side}, {notional} USDT, {price}, {time}",
    "Big sell, 42,000 USDT, 65,410, 14:32:01",
    "Cluster of 7, 1.9 million USDT, sell, 14:02:11",
    "Cluster of 7, 1,900,000 USDT, sell, 14:02:11, estimated",
    "Big sell, 1,200,000 USDT, 64,012.0, 14:02:11",
    "Big sell · 1.2M USDT · 64,012.0 · 14:02:11.208",
    (
        "Cluster \u00d77 · 1.9M USDT · Sell · 7 prints within 250 ms / 1 tick · first print "
        "14:02:11.208 · bar 14:02 · (estimated)"
    ),
    "Big trades · area-linear · 250k → 3 px · 1M → 24 px · >1M labelled",
    "Big trades · log · 250k → 3 px · 1M → 24 px · >1M labelled",
    "(estimated)",
    "Estimated, Trade cluster",
    "Smaller prints hidden at this zoom",
    "Big trades visible",
    "1,200,000",
    "Nothing to pause while disconnected.",
    "Read-only while viewing as {user}.",
    "Your role can't change settings.",
    "Your role can't save workspaces.",
    "Read-only — your role can't change settings.",
    "Read-only — your role can't save workspaces.",
    "Not available",
)
SHARED = "Research PRs never edit `22`."
# the A-id <-> entry anchors (lens round 1 F-5): each sentence must cite the id the 12 table gives
# that entry, so a renumbering of the A-rows is caught (the table is parsed, never hard-coded)
A_ANCHORS = (
    ("CMP-195", "`color.marker.*` (CMP-195) does not exist and is not needed ({id})"),
    ("CMP-199", "the two-row alternative is {id}'s second option"),
    ("CMP-037", "for the Big trades legend row ({id199}, {id}; BQ-17)"),
)
FORBIDDEN = {
    "local path": re.compile(r"/(?:home|Users)/[^/\s]+/"),
    "Penpot host": re.compile(r"penpot\.[a-z0-9-]+\.[a-z]{2,}", re.IGNORECASE),
    "Penpot team / file / workspace ref": re.compile(r"team[-_]id=|file[-_]id=|#/work[s]pace"),
}
COUNT_RX = rows_of(  # the ids the spec's tables carry: what the boards and the draft quote
    r"""boards=^\| 0[1-9] +\| `
states=^\| S\d+[ ]
decisions=^\| D-\d+[ ]
cmp_states=^\| BS\d+[ ]
motion=^\| M-\d+[ ]
amendments=^\| A-\d+[ ]
c_own=^\| D03-C\d+[ ]
g_own=^\| D03-G\d+[ ]
q=^\| D03-Q\d+[ ]
bq=^\| BQ-\d\d[ ]
heuristics=^\| H-\d+[ ]
handoffs=^\| HO-\d+[ ]
stories=^\| `ChartEngine/BigTradeBubble`""",
    "=",
)
X = "\u00d7"


def tenths(vals: list[float]) -> str:
    return " / ".join(f"{v:.1f}" for v in vals)


def hundredths(vals: list[float]) -> str:
    return " / ".join(f"{v:.2f}" for v in vals)


def fg_of(theme: str, short: str, under: str) -> str:
    """A colour key, or `token@alpha` = the token composited at alpha over `under`."""
    if "@" in short:
        tok, a = short.split("@")
        return over(theme, tok, float(a), under)
    return col(theme, short)


def min_alpha_clearing(bar: float, step: float = 0.05) -> dict[str, float]:
    """The smallest band alpha (step 0.05) at which buy and sell clear `bar` on canvas per theme."""
    out: dict[str, float] = {}
    for t in THEMES:
        a = step
        while (
            a < 1.0 and min(ratio(over(t, s, a), col(t, "canvas")) for s in ("buy", "sell")) < bar
        ):
            a = round(a + step, 2)
        out[t] = a
    return out


def gates(
    text: str, label: str, constitution: str, problems: list[str], must: bool = True
) -> dict[str, Any]:
    """The string gates: the copy strings (spec only — a PR draft need not carry them), the
    "Est." rule, the shared sentence on G-rows, the hygiene patterns and the rule ids."""
    missing = [s for s in MUST if s not in text] if must else []
    problems += [f"{label}: missing {s!r}" for s in missing]
    if must:
        table = re.findall(r"^\| (A-\d+) +\| (CMP-\d+) +\|", text, re.MULTILINE)
        by_entry = {e: i for i, e in table if sum(1 for _, x in table if x == e) == 1}
        for entry, phrase in A_ANCHORS:
            want = phrase.format(id=by_entry.get(entry, "?"), id199=by_entry.get("CMP-199", "?"))
            if want not in text:
                problems.append(f"{label}: A-row anchor for {entry} not found: {want!r}")
            missing += [] if want in text else [want]
    for ln in text.splitlines():
        if "Est." in ln and not re.search(r"E11-D04|E25-D05|E25-D01|C15|Q4|never", ln):
            problems.append(f"{label}: 'Est.' outside a sibling citation")
        g_row = re.match(r"^\| (?:G\d+|D0[23]-G\d+) ", ln) and re.search(r"`2[23]`", ln)
        if g_row and SHARED not in ln:
            problems.append(f"{label}: a G-row names `22` / `23` without the shared sentence")
    hits = {name: sorted(set(rx.findall(text))) for name, rx in FORBIDDEN.items()}
    problems += [f"{label}: {name} {h!r}" for name, hs in hits.items() for h in hs]
    ids = sorted(set(re.findall(r"\bC-\d+\.\d+\b", text)))
    absent = [i for i in ids if not re.search(rf"\b{re.escape(i)}\b", constitution)]
    problems += [f"{label}: {i} not in CONSTITUTION.md" for i in absent]
    return {
        "missing": missing,
        "forbidden": {k: len(v) for k, v in hits.items()},
        "rule_ids": len(ids),
    }


def drift_phrases(out: dict[str, Any]) -> list[str]:
    """`--check`: the printed numbers as the spec's own sentences spell them (4.3, 4.4, 8.1)."""
    rad, side, dark = out["laws"]["radii"], out["laws"]["square_side_px"], out["matrix"]["dark"]
    KEYS = [f"{k:g}" for k in ANCHORS]
    c = out["laws"]["ticket_constants"]["majors"]
    aged, sim = out["matrix"]["aged"], out["cvd"]
    phr = [
        tenths([rad["3"][k]["sqrt"] for k in KEYS]),
        tenths([rad["3"][k]["log"] for k in KEYS]),
        tenths([rad["3"][k]["linear"] for k in KEYS]),
        tenths([rad["4"][k]["sqrt"] for k in KEYS]),
        tenths([rad["5"][k]["sqrt"] for k in KEYS]),
        tenths([side["3"], side["10"], side["24"]]),
        f"{side['4']} px",
        f"{side['5']} px",
        f"{c['k_log']:.2f} px",
        f"{c['k_lin'] * 1e6:.0f} px per 1M USDT",
        f"{out['laws']['area_per_step_px2']} px²",
        hundredths(aged["buy@0.8"]),
        hundredths(aged["sell@0.8"]),
        hundredths(aged["buy@0.7"]),
        hundredths(aged["sell@0.7"]),
        hundredths(aged["buy@0.85"]),
        hundredths(aged["sell@0.85"]),
        hundredths(dark["inverse|sell@0.8"]),
        f"first clears 3:1 at {out['matrix']['min_alpha_3to1']['dark']:.2f}",
        hundredths(dark["inverse|buy"]),
        hundredths(dark["inverse|sell"]),
        hundredths(dark["t1|canvas"]),
        hundredths(dark["ring|canvas"]),
        hundredths(dark["t1|info.subtle"]),
        hundredths(dark["info.default|canvas"]),
        hundredths(dark["t2|overlay"]),
        hundredths(dark["warn.strong|warn.subtle"]),
        hundredths(dark["t2|n.subtle"]),
        hundredths(dark["t1|overlay"]),
        hundredths(sim["separation"]["hue"]),
        hundredths(sim["separation"]["fill"]),
        hundredths(sim["separation"]["cvd_pair"]),
        hundredths(sim["marks"]["sell glyph on sell.subtle"]),
        hundredths(sim["marks"]["CVD sell mark on canvas"]),
        f"{out['matrix']['gated']} gated rows",
        f"FAIL {out['matrix']['fail']}",
        f"{out['matrix']['rows_total']} pairs {X} 3 themes",
        f"{out['counts']['states']} tape states",
        f"{out['counts']['cmp_states']} CMP-112 states",
        f"{out['counts']['amendments']} A-rows",
    ]
    return phr


def count_drift(out: dict[str, Any], text: str) -> list[str]:
    """`--check`: every occurrence of a counted phrase ("N gated rows", ...) must carry the computed
    N, so editing one copy of a repeated headline cannot pass on the strength of the others."""
    m, c = out["matrix"], out["counts"]
    fams = (
        (m["gated"], "gated rows"),
        (m["rows_total"], f"pairs {X} 3 themes"),
        (c["states"], "tape states"),
        (c["cmp_states"], "CMP-112 states"),
        (c["amendments"], "A-rows"),
    )
    bad: list[str] = []
    for want, suffix in fams:
        found = re.findall(rf"\b(\d+) {re.escape(suffix)}", text)
        bad += [f"{n} {suffix} (computed {want})" for n in found if int(n) != want]
    return bad


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true", help="fail on drift vs the spec's sentences")
    ap.add_argument("--spec", default=str(ROOT / "docs" / "design" / "E22" / "E22-D03.md"))
    ap.add_argument("--draft", default=None)
    a = ap.parse_args(argv)
    quiet, problems, out = bool(a.json), [], {}  # type: bool, list[str], dict[str, Any]

    def say(s: str) -> None:
        if not quiet:
            print(s)

    say("## A. The laws (E22-D02 D21 reproduced; the ticket's constants derived per class)\n")
    radii: dict[str, dict[str, dict[str, float]]] = {}
    for r_min in R_MIN_CANDIDATES:
        key = f"{r_min:g}"
        radii[key] = {f"{k:g}": law(k, r_min) for k in ANCHORS}
        for name in ("sqrt", "log", "linear"):
            vals = [radii[key][f"{k:g}"][name] for k in ANCHORS]
            tag = ""
            if r_min == R_MIN:
                ok = vals == D02_RADII[name] and all(
                    law(k)[name] == d02.radii(k)[name] for k in ANCHORS
                )
                tag = " MATCH" if ok else " MISMATCH"
                problems += (
                    [] if ok else [f"{name} at r_min 3: {vals} vs E22-D02 {D02_RADII[name]}"]
                )
            say(f"- r_min {key}: {name} {tenths(vals)} px at 1 / 1.5 / 2 / 3 / 4{X}{tag}")
    side = {f"{r:g}": round(r * math.sqrt(math.pi), 1) for r in (3.0, 4.0, 5.0, 10.0, 24.0)}
    ok_side = {side["3"], side["10"], side["24"]} == set(D02_SIDES.values())
    problems += [] if ok_side else [f"square sides {side} vs E22-D02 {D02_SIDES}"]
    say(f"- sell square side r·√π: {side} px {'MATCH' if ok_side else 'MISMATCH'}")
    area = round(math.pi * (R_MAX**2 - R_MIN**2) / (CAP_MULT - 1))
    consts = {name: ticket_constants(thr) for name, thr in CLASSES.items()}
    for name, c in consts.items():
        for lw in ("sqrt", "log", "linear"):
            got = [ticket_radius(lw, k * c["T"], c) for k in ANCHORS]
            if got != D02_RADII[lw]:
                problems.append(f"ticket constants ({name}, {lw}): {got} vs {D02_RADII[lw]}")
        say(
            f"- {name}: T {c['T']:,.0f} USDT → n0 = T, k_log {c['k_log']:.4f} px, "
            f"k_lin {c['k_lin']:.3e} px/USDT ({c['k_lin'] * 1e6:.0f} px per 1M USDT); "
            f"the anchors reproduce under both forms"
        )
    say(
        f"- equal area per 1{X} step: π(24² \u2212 3²)/3 = {area} px²; "
        f"glyph from r ≥ {GLYPH_R:g} px; cap outline r + 3, 2 px of canvas"
    )
    out["laws"] = {"radii": radii, "square_side_px": side, "ticket_constants": consts}
    out["laws"].update({"area_per_step_px2": area, "glyph_r_px": GLYPH_R, "r_min": R_MIN})
    out["laws"].update({"r_max": R_MAX, "cap_multiple": CAP_MULT, "cap_outline_r_px": R_MAX + 3})

    say("\n## B. Contrast matrix (three themes; unrounded compare; 4 decimals near a bar)\n")
    say("| Element | fg | bg | role | dark | light | hc | verdict |")
    say("|---|---|---|---|---|---|---|---|")
    rows, fails, gated, repro = [], 0, 0, []  # type: list[dict[str, Any]], int, int, list[Any]
    dark: dict[str, list[float]] = {}
    aged: dict[str, list[float]] = {}
    for element, fg, bg, role, note in PAIRS:
        if role == "scrim":
            vals = [ratio(d02.scrimmed(t, TOK[fg]), d02.scrimmed(t, TOK[bg])) for t in THEMES]
            bar: float | None = 4.5
        else:
            vals = [ratio(fg_of(t, fg, bg.split("@")[0]), fg_of(t, bg, "canvas")) for t in THEMES]
            bar = BAR[role]
        bad = [THEMES[i] for i, v in enumerate(vals) if bar is not None and v < bar]
        verdict = "PASS" if not bad else "FAIL: " + ", ".join(bad)
        if bar is None:
            verdict = "decorative (not gated)"
        elif role in ("reported", "reported-text", "scrim"):
            verdict = f"reported, not gated: would {verdict}"
        elif role.startswith("rej-"):
            bar_name = "non-text" if role == "rej-nt" else "text"
            verdict = f"rejected by design ({bar_name} bar): would {verdict}"
        else:
            gated += 1
            if bad:
                fails += 1
        if role == "glyph":
            verdict += "; vs the 4.5 text bar " + ", ".join(
                "PASS" if v >= 4.5 else "below" for v in vals
            )
        cells = " | ".join(f"{v:.4f}" if bar and abs(v - bar) < 0.005 else f"{v:.2f}" for v in vals)
        fgn = TOK.get(fg.split("@")[0], fg) + (f" @ {fg.split('@')[1]}" if "@" in fg else "")
        bgn = TOK.get(bg.split("@")[0], bg) + (f" @ {bg.split('@')[1]}" if "@" in bg else "")
        if role == "scrim":  # the measured bg is raised under app at opacity.scrim (BQ-13)
            bgn = f"{TOK['raised']} under {TOK['app']} @ {T['dark']['opacity.scrim']}"
        say(f"| {element} | `{fgn}` | `{bgn}` | {role} | {cells} | {verdict} — {note} |")
        r2, key = [round(v, 2) for v in vals], f"{fg}|{bg}"
        rows.append({"element": element, "fg": fgn, "bg": bgn, "role": role, "ratio": r2})
        dark.setdefault(key, r2)
        if "@" in fg and bg == "canvas":
            aged[fg] = r2
        for src, table in (
            ("E25-D05 12.1", E25_12_1),
            ("E30-D02 D3", E30_D3),
            ("E22-D02 14", D02_14),
        ):
            if key in table and key not in {e[1] for e in repro if e[0] == src}:
                repro.append([src, key, r2, table[key], r2 == table[key]])
    n_ok = sum(1 for e in repro if e[4])
    diff = "" if n_ok == len(repro) else f" DIFF {[e for e in repro if not e[4]]}"
    say(
        f"\n{len(rows)} pairs {X} 3 themes; {gated} gated rows; FAIL {fails}; "
        f"reproductions {n_ok}/{len(repro)} match{diff}"
    )
    alpha_min = min_alpha_clearing(3.0)
    say(f"- the smallest band alpha clearing 3:1 for both marks on canvas, per theme: {alpha_min}")
    resolved = {t: {TOK[k]: col(t, k) for k in TOK} for t in THEMES}
    out["matrix"] = {"rows": rows, "gated": gated, "fail": fails, "rows_total": len(rows)}
    out["matrix"].update({"reproductions": repro, "resolved": resolved, "dark": dark, "aged": aged})
    out["matrix"]["min_alpha_3to1"] = alpha_min

    say("\n## C. Greyscale and deuteranopia (D02 10 reproduced; light / hc and the CVD pair)\n")
    sw: dict[str, dict[str, dict[str, str]]] = {}
    for t in THEMES:
        sw[t] = {}
        for k in CVD_TOKENS:
            n0 = col(t, k)
            sw[t][TOK[k]] = {"normal": n0, "greyscale": d02.simulate(n0, "greyscale")}
            sw[t][TOK[k]]["deuteranopia"] = d02.simulate(n0, "deuteranopia")
    for k, g_exp, d_exp in D02_10_HEX:
        got_g, got_d = sw["dark"][TOK[k]]["greyscale"], sw["dark"][TOK[k]]["deuteranopia"]
        okc = (got_g, got_d) == (g_exp, d_exp)
        problems += [] if okc else [f"D02 10 {k}: {(got_g, got_d)} vs {(g_exp, d_exp)}"]
        say(
            f"- dark `{TOK[k]}` {sw['dark'][TOK[k]]['normal']} → {got_g} / {got_d} "
            f"{'MATCH' if okc else 'MISMATCH'}"
        )
    rend = ("normal", "greyscale", "deuteranopia")
    pairs = {"hue": ("buy", "sell"), "fill": ("buy.subtle", "sell.subtle")}
    pairs["cvd_pair"] = ("cvd.buy", "cvd.sell")
    sep: dict[str, list[float]] = {}
    sep_theme: dict[str, dict[str, list[float]]] = {}
    for name, (x, y) in pairs.items():
        sep[name] = [round(ratio(sw["dark"][TOK[x]][r], sw["dark"][TOK[y]][r]), 2) for r in rend]
        sep_theme[name] = {
            t: [round(ratio(sw[t][TOK[x]][r], sw[t][TOK[y]][r]), 2) for r in rend] for t in THEMES
        }
        want = D02_10_SEP.get(name)
        oks = "" if want is None else (" MATCH" if sep[name] == want else " MISMATCH")
        if want is not None and sep[name] != want:
            problems.append(f"D02 10 separation {name}: {sep[name]} vs {want}")
        say(
            f"- {x} vs {y} separation dark (normal / greyscale / deuteranopia) {sep[name]}{oks}; "
            f"light {sep_theme[name]['light']}; hc {sep_theme[name]['high-contrast']}"
        )
    marks: dict[str, list[float]] = {}
    marks_theme: dict[str, dict[str, list[float]]] = {}
    for mname, (x, y) in MARKS.items():
        marks[mname] = [round(ratio(sw["dark"][TOK[x]][r], sw["dark"][TOK[y]][r]), 2) for r in rend]
        marks_theme[mname] = {
            t: [round(ratio(sw[t][TOK[x]][r], sw[t][TOK[y]][r]), 2) for r in rend] for t in THEMES
        }
        want_m = D02_10_MARKS.get(mname)
        okm = "" if want_m is None else (" MATCH" if marks[mname] == want_m else " MISMATCH")
        if want_m is not None and marks[mname] != want_m:
            problems.append(f"D02 10 {mname}: {marks[mname]} vs {want_m}")
        lowest = min(min(v) for v in marks_theme[mname].values())
        say(
            f"- {mname} dark {marks[mname]}{okm}; light {marks_theme[mname]['light']}; "
            f"hc {marks_theme[mname]['high-contrast']}; lowest {lowest:.2f}"
        )
    out["cvd"] = {"swatches": sw, "separation": sep, "separation_by_theme": sep_theme}
    out["cvd"].update({"marks": marks, "marks_by_theme": marks_theme})

    say("\n## D. Token bindings (dark / light / hc, or MISSING = a DS request, never invented)\n")
    binds = {
        nm: " / ".join(str(T[t][nm]) for t in THEMES) if nm in T["dark"] else "MISSING"
        for nm in NAMED
    }
    for nm, bv in binds.items():
        say(f"- `{nm}`: {bv}")
    missing = {k for k, v in binds.items() if v == "MISSING"}
    if missing != EXPECT_MISSING:
        problems.append(f"MISSING set changed: {sorted(missing ^ EXPECT_MISSING)}")
    out["tokens"] = {"bindings": binds, "missing": sorted(missing), "named": len(NAMED)}
    opac = ("disabled", "muted", "scrim")
    out["tokens"]["opacity"] = {k: float(T["dark"][f"opacity.{k}"]) for k in opac}

    say("\n## E. tools/contrast/pairs.mjs: registered today; the PROPOSED rows (D02-G5 + D03-G5)\n")
    pj = re.sub(
        r"\s+", " ", (ROOT / "tools" / "contrast" / "pairs.mjs").read_text(encoding="utf-8")
    )
    reg = {(m[0], m[1]) for m in re.findall(r'fg: "([^"]+)", bg: "([^"]+)"', pj)}
    for fg, bg in REGISTERED:
        problems += [] if (fg, bg) in reg else [f"pairs.mjs no longer registers {fg} on {bg}"]
        say(f"- registered: `{fg}` on `{bg}`: {'yes' if (fg, bg) in reg else 'NO'}")
    already, own_open = 0, 0
    for fg, bg, thr, src in PROPOSED:
        state = "registered" if (fg, bg) in reg else "open"
        already += state == "registered"
        own_open += state == "open" and src.startswith("D03")
        say(f"- PROPOSED ({thr}, {src}): `{fg}` on `{bg}`: {state}")
    out["pairs"] = {"registered_total": len(reg), "checked": len(REGISTERED)}
    out["pairs"].update({"proposed": len(PROPOSED), "proposed_already": already})
    out["pairs"]["proposed_own"] = sum(1 for p in PROPOSED if p[3].startswith("D03"))
    out["pairs"]["proposed_own_open"] = own_open  # CR-3 adds the two composited aged rows

    say("\n## F. String gates and the counts the boards and the draft quote\n")
    constitution = (ROOT / "CONSTITUTION.md").read_text(encoding="utf-8")
    spec_path = Path(a.spec)
    spec_text = spec_path.read_text(encoding="utf-8") if spec_path.exists() else ""
    out["gates"] = {
        "spec": gates(spec_text, "spec", constitution, problems) if spec_text else "no spec"
    }
    if a.draft:
        draft_text = Path(a.draft).read_text(encoding="utf-8")
        out["gates"]["draft"] = gates(draft_text, "draft", constitution, problems, must=False)
        for rx_name, rx in (
            (
                "closing keyword",
                re.compile(r"\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\b\s*#\d", re.IGNORECASE),
            ),
        ):
            if rx.search(draft_text):
                problems.append(f"draft: {rx_name} present (PR 1 is Partial)")
    cnt: dict[str, int] = {k: len(re.findall(rx, spec_text, re.MULTILINE)) for k, rx in COUNT_RX}
    cnt.update({"laws": 3, "anchors": len(ANCHORS), "r_min_candidates": len(R_MIN_CANDIDATES)})
    cnt.update({"pairs_rows": len(rows), "pairs_gated": gated, "pairs_fail": fails})
    cnt["repro_match"] = n_ok
    say("- " + "; ".join(f"{k} {v}" for k, v in cnt.items()))
    out["counts"] = cnt
    if a.check:
        say("\n## I. Drift check (--check): the printed numbers as the spec's own sentences\n")
        drift = drift_phrases(out)
        low = spec_text.lower()
        missing_drift = [d for d in drift if d.lower() not in low]
        for d in drift:
            say(f"- {'DRIFT' if d in missing_drift else 'OK'}: {d}")
        problems += [f"drift: the spec lacks {d!r}" for d in missing_drift]
        stale_counts = count_drift(out, spec_text)
        for d in stale_counts:
            say(f"- DRIFT (a counted phrase): {d}")
        problems += [f"drift: the spec says {d}" for d in stale_counts]
        out["drift"] = {"phrases": len(drift), "missing": missing_drift}
    out["problems"] = problems
    if quiet:
        print(json.dumps(out, indent=1, ensure_ascii=False))
    else:
        tail = problems + ([f"{fails} gated contrast FAIL(s)"] if fails else [])
        ok_line = "OK: no gated failure; every reproduction matches; the MISSING set is as declared"
        print("\n" + ("\n".join(f"PROBLEM: {p}" for p in tail) or ok_line))
    return 1 if problems or fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
