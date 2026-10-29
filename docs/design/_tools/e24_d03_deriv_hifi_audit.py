"""E24-D03 hi-fi audit: every number the SCR-054 derivatives-panel hi-fi spec states, computed.

Standalone, offline, stdlib only (`python3 -I`). Themes resolve exactly as
`packages/ui/tokens/tests/verify_tokens.py` resolves them and contrast is `contrast_ratio()` from
`docs/design/_tools/contrast_check.py` (both imported with one loader, never re-implemented). The
E24-D02 wireframes' illustrative arithmetic is reproduced through `e24_d01_deriv_arith.py`'s own
functions (the annualisation, the countdown ladder, the cap check), never retyped. The greyscale,
deuteranopia and protanopia maths are `docs/design/_tools/cvd_sim.py`'s (Rec. 601 luma, the Machado
2009 matrices), re-stated here on single colours so the tool needs no numpy. Nothing here reads a
fixture or a network.

Sections: A the resolved tokens every binding names (a name that does not resolve is a FAIL; the
PROPOSED engine aliases of E11-D05 section 4.1b / E12-D09 resolve through their declared targets;
the A-rows' "today" cells quote `15` verbatim and are not scanned);
B the contrast matrix, every pair in dark / light / high-contrast compared unrounded against its
bar, composited rows (the 0.85 stale dim) by the E22-D03 `over()` method; C the E24 number-format
rows (the E25 sheet by reference) and the E24-D02 arithmetic; D the greyscale / deuteranopia /
protanopia statement; E the board plan (<= 10 boards, light twins <= one third, ids PENDING in
PR 1) and its Folds column against every state row's "-> D03 board" cell, both ways; F the spec's
own tables and strings (the chip bindings equal their catalogue entries, no
side hue on funding, the candle slots on the quadrants, one danger hue on liquidations, no chip on
recorded data, every predicted / zone carrier, the T2 look never dimmed, the K01 permitted sentences
and forbidden phrases, the A-rows' "today" text equal to `15` at the base, the `22` x-rbac rows the
spec cites, the `14` pointer line, the `pairs.mjs` registration column against the registry's
`PAIRS` fg / bg entries (parsed read-only), the E24-D02 strings carried verbatim, the hygiene
patterns, the rule ids).

Usage: python3 -I docs/design/_tools/e24_d03_deriv_hifi_audit.py [--json]
       python3 -I docs/design/_tools/e24_d03_deriv_hifi_audit.py --check [SPEC]
       python3 -I docs/design/_tools/e24_d03_deriv_hifi_audit.py --self-test [SPEC]
`--check` exits 1 on a gated FAIL, a lost reproduction, a failed table or string gate, or a number
the tool prints that the spec's own text does not carry (section G, drift). `--self-test` applies
MUTATIONS in memory (no file is ever written) — to the spec, or, where a gate reads another file,
to that file's text (`14`, `22`) or to the REPRO table: each must raise exactly one new FAIL, no two
the same, and the clean spec must pass before and after. Stdout is UTF-8.
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
TOOLS = ROOT / "docs" / "design" / "_tools"
SPEC = ROOT / "docs" / "design" / "E24" / "E24-D03.md"
CATALOGUE_15 = ROOT / "docs" / "plan" / "15-component-catalogue.md"
SCREENS_14 = ROOT / "docs" / "plan" / "14-screens-catalogue.md"
API_22 = ROOT / "docs" / "plan" / "22-api-openapi.yaml"
PAIRS_MJS = ROOT / "tools" / "contrast" / "pairs.mjs"
CONSTITUTION = ROOT / "CONSTITUTION.md"
FILES = {"14": SCREENS_14, "22": API_22, "pairs": PAIRS_MJS}  # read by a gate; mutable in self-test
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
arith = _load(TOOLS / "e24_d01_deriv_arith.py", "e24_d01_deriv_arith")


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

# The PROPOSED engine-prefix aliases the spec binds (E11-D05 section 4.1b; E12-D09 `16` line 57):
# each resolves through its declared target; none is a new token (rider (b) of the #661 ruling).
ALIASES = {
    "color.chart.line": "palette.purple.500",
    "color.chart.rule": "color.border.default",
    "color.chart.boundary": "color.text.tertiary",
    "color.chart.axis": "color.text.tertiary",
    "color.chart.hatch.texture": "color.border.strong",
}
for theme in THEMES:
    for alias, target in ALIASES.items():
        T[theme][alias] = T[theme][target]


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
inverse|color.text.inverse
b.default|color.border.default
b.strong|color.border.strong
b.selected|color.border.selected
ring|color.focus.ring
buy|color.buy.default
sell|color.sell.default
n.subtle|color.neutral.subtle
up|color.candle.up
down|color.candle.down
line|color.chart.line
profile|color.profile.bar
warn.default|color.status.warning.default
info.default|color.status.info.default
info.subtle|color.status.info.subtle
info.strong|color.status.info.strong
danger.default|color.status.danger.default
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
    if "@" in spec:
        tok, a = spec.split("@")
        return over(theme, tok, float(a), under)
    return col(theme, spec)


def fmt3(vals: list[float], bar: float | None) -> str:
    """Two decimals; four where a value would round onto its bar (the unrounded compare)."""
    out = []
    shown = 3.0 if bar is None else bar
    for v in vals:
        if round(v, 2) == shown and abs(v - shown) > 1e-9:
            out.append(f"{v:.4f}")
        else:
            out.append(f"{v:.2f}")
    return " / ".join(out)


def cells(ln: str) -> list[str]:
    return [c.strip() for c in ln.strip().strip("|").split("|")]


# A. the tokens the spec binds: every backticked token-like name must resolve in every theme
TOKEN_RX = re.compile(
    r"`((?:color|type|space|size|radius|border|motion|opacity|font|elevation)\.[a-z0-9.-]+)`"
)
NEVER_A_TOKEN = ("color.chart.liquidation",)  # the DS request stays a request (D03-G1)


def a_row_today_stripped(spec: str) -> str:
    """The spec without the A-rows' "today" cells: they quote `15` verbatim, unshipped names included."""
    out = []
    for ln in spec.splitlines():
        if re.match(r"^\| A-\d+ ", ln):
            c = cells(ln)
            if len(c) > 3:
                c[3] = ""
                ln = "| " + " | ".join(c) + " |"
        out.append(ln)
    return "\n".join(out)


def tokens(spec: str) -> dict[str, Any]:
    names = sorted(set(TOKEN_RX.findall(a_row_today_stripped(spec))))
    missing = [n for n in names if any(n not in T[t] for t in THEMES)]
    shipped = [n for n in NEVER_A_TOKEN if any(k.startswith(n) for k in T["dark"])]
    return {"named": len(names), "missing": missing, "aliases": sorted(ALIASES), "shipped": shipped}


# B. the matrix: id | element | fg | bg | role | pairs.mjs status
PAIRS = rows_of(
    """P1|header readouts, popover row labels, stub label, table cells on raised rows (t1 on raised)|t1|raised|text|registered
P2|secondary units, settled rate pending, T2 reason, basis source word, Last loaded (t2 on raised)|t2|raised|text|registered
P3|T2 label and lock glyph on the header row and stubs (t3 on raised)|t3|raised|text|registered
P4|legend rows, key row, feed cells, band labels, zone labels, table cells on canvas rows (t1 on canvas)|t1|canvas|text|registered
P5|completeness sentence, legend notes, retry-band second line, Not available to rules (t2 on canvas)|t2|canvas|text|registered
P6|boundary and coverage labels, axis tick labels (color.chart.axis / .boundary = t3 on canvas)|t3|canvas|text|PROPOSED (D03-G4)
P7|price-up quadrant bars, full width (color.candle.up on canvas)|up|canvas|non-text|registered
P8|price-down quadrant bars, half width (color.candle.down on canvas)|down|canvas|non-text|registered
P9|the ▲▼ tips on a price-up bar (text.inverse on candle.up)|inverse|up|non-text|PROPOSED (D03-G4)
P10|the ▲▼ tips on a price-down bar (text.inverse on candle.down)|inverse|down|non-text|PROPOSED (D03-G4)
P11|OI level line, funding steps and bars, the predicted marker outline (color.chart.line on canvas)|line|canvas|non-text|PROPOSED (E12-D09)
P12|zero line and axis rule (color.chart.rule = border.default on canvas; the 0 label carries)|b.default|canvas|decorative|—
P13|liquidation bars and CMP-127 fill, both sides (color.status.danger.default on canvas)|danger.default|canvas|non-text|PROPOSED (D03-G4)
P14|the ▲ / ▼ glyph inside CMP-127 (text.inverse on danger.default)|inverse|danger.default|non-text|PROPOSED (D03-G4)
P15|the ▲ / ▼ side glyph in the Liq readout and a feed row on raised (danger.default on raised)|danger.default|raised|non-text|PROPOSED (D03-G4)
P16|the ▲ / ▼ side glyph in a feed row on canvas; the heatmap cell outline until the ramp lands|danger.default|canvas|non-text|PROPOSED (D03-G4)
P17|the recorded (b) histogram bars (color.profile.bar on canvas)|profile|canvas|non-text|registered
P18|the (a) band outline and the CMP-227 marker on the canvas (info.default on canvas)|info.default|canvas|non-text|PROPOSED (E25-D03 CR-1)
P19|the (a) band fill (info.subtle on canvas; the hatch, the outline and the label carry)|info.subtle|canvas|decorative|—
P20|CMP-227 word on the fill (inline chip)|t1|info.subtle|text|registered
P21|CMP-227 glyph on the fill|info.default|info.subtle|non-text|PROPOSED (E25-D03 CR-1)
P22|CMP-227 inline outline on the header row (info.default on raised)|info.default|raised|non-text|PROPOSED (E25-D03 CR-1)
P23|CMP-239 stale text|stale.text|stale.surface|text|registered
P24|CMP-239 stale indicator dot and the strong chip's outline|stale.indicator|stale.surface|non-text|registered
P25|focus ring on raised|ring|raised|non-text|registered
P26|focus ring on the canvas|ring|canvas|non-text|registered
P27|the <5 min warning border on the header row (the sentence carries)|warn.default|raised|decorative|never (E25-D03 P7)
P28|popover, CMP-069, tooltip and dialog text (t1 on overlay)|t1|overlay|text|registered
P29|popover information line, tooltip second sentence, dialog body (t2 on overlay)|t2|overlay|text|registered
P30|T2 label in the popover and the dialog (t3 on overlay)|t3|overlay|text|registered
P31|basis source selected segment label; Pause pressed (t1 on action.selected)|t1|a.selected|text|registered
P32|basis source selected 2 px inner outline (border.selected on action.selected)|b.selected|a.selected|non-text|PROPOSED (E25-D03 CR-1)
P33|Retry, Restore, Recording settings route, dialog buttons (t1 on action.secondary)|t1|a.secondary|text|PROPOSED (E25-D03 CR-1)
P34|N new chip word (CMP-011 neutral: t2 on neutral.subtle)|t2|n.subtle|text|unregistered (E05)
P35|disconnected banner title (t1 on danger.subtle)|t1|danger.subtle|text|registered
P36|disconnected banner edge and glyph (danger.strong on danger.subtle)|danger.strong|danger.subtle|non-text|PROPOSED (E25-D03 CR-1)
P37|table header label (t1 on hover)|t1|hover|text|PROPOSED (E25-D03 CR-1)
P38|T2 hairline, collapsed stub border, chip stroke (border.default on raised)|b.default|raised|decorative|—
P39|gap band texture lines (color.chart.hatch.texture = border.strong on canvas; the edges and words carry)|b.strong|canvas|decorative|—
P40|stale 0.85 dim: t1 on the canvas|t1@0.85|canvas|reported|—
P41|stale 0.85 dim: candle.up on the canvas|up@0.85|canvas|reported|—
P42|stale 0.85 dim: candle.down on the canvas|down@0.85|canvas|reported|—
P43|stale 0.85 dim: chart.line on the canvas|line@0.85|canvas|reported|—
P44|stale 0.85 dim: danger.default on the canvas|danger.default@0.85|canvas|reported|—
P45|stale 0.85 dim: t1 on raised|t1@0.85|raised|reported|—
P46|stale 0.85 dim: t3 on raised|t3@0.85|raised|reported|—
P47|rejected: the funding rate in the buy hue on raised (a side hue on a cost)|buy|raised|rejected-text|—
P48|rejected: the funding rate in the sell hue on raised|sell|raised|rejected-text|—
P49|rejected: a hued (estimated) word (info.strong on info.subtle)|info.strong|info.subtle|rejected-text|—
P50|rejected: the liquidated side word in the danger hue on raised|danger.default|raised|rejected-text|—
P51|rejected: a long liquidated bar in the sell hue on canvas (passes; rejected by design, memo F16)|sell|canvas|rejected-non-text|registered
P52|the notional field's invalid 2 px boundary (danger.default on the app well)|danger.default|app|non-text|registered
P53|the notional field's danger glyph beside the message (danger.strong on the app well)|danger.strong|app|non-text|registered"""
)

# Reproductions (to the hundredth; 2.9992 to the ten-thousandth): E25-D03 section 8.1, E22-D03
# section 8.1, E09-D09 section 11, E11-D05 section 7.1. A lost reproduction is a FAIL. `16` line 57
# is not a source: its 4.32 for `color.chart.line` on the canvas truncates the unrounded 4.3275
# (P11 is listed, not reproduced; a pencil note for the `16` owner via E12-D09).
REPRO: dict[str, tuple[float, float, float]] = {
    "P1": (14.35, 15.62, 16.25),
    "P2": (8.81, 8.98, 14.35),
    "P3": (5.62, 5.92, 11.21),
    "P4": (15.20, 16.78, 17.21),
    "P5": (9.33, 9.65, 15.20),
    "P6": (5.96, 6.36, 11.87),
    "P12": (1.50, 1.31, 3.03),
    "P18": (6.57, 3.74, 6.57),
    "P20": (10.74, 15.44, 12.16),
    "P21": (4.64, 3.44, 4.64),
    "P22": (6.20, 3.48, 6.20),
    "P23": (10.69, 7.37, 17.42),
    "P24": (13.36, 3.37, 13.36),
    "P25": (6.66, 5.86, 17.30),
    "P26": (7.05, 6.30, 18.32),
    "P27": (7.98, 2.9992, 7.98),
    "P29": (8.14, 8.26, 13.27),
    "P31": (12.33, 14.58, 13.96),
    "P32": (4.20, 3.86, 5.72),
    "P33": (10.17, 12.82, 11.51),
    "P34": (7.50, 8.26, 12.22),
    "P35": (12.06, 14.64, 13.66),
    "P36": (7.83, 3.85, 7.83),
    "P37": (12.22, 14.37, 13.83),
    "P38": (1.41, 1.22, 2.86),
    "P39": (1.91, 1.57, 1.91),
    "P40": (11.16, 10.85, 12.57),
    "P45": (10.63, 10.36, 11.97),
    "P46": (4.43, 4.25, 8.43),
    "P47": (7.03, 4.68, 9.40),
    "P48": (4.42, 4.51, 7.17),
    "P49": (7.30, 4.34, 7.30),
}


def matrix(
    problems: list[str], repro: dict[str, tuple[float, float, float]] | None = None
) -> dict[str, Any]:
    repro = REPRO if repro is None else repro
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
        if pid in repro:
            repro_n += 1
            exp = repro[pid]
            ok = all(
                abs(round(v, 4 if e == 2.9992 else 2) - e) < 1e-9
                for v, e in zip(vals, exp, strict=True)
            )
            repro_ok += int(ok)
            if not ok:
                problems.append(f"reproduction lost {pid}: {fmt3(vals, bar)} vs {exp}")
        base_fg = fg.split("@")[0]
        rows.append(
            {
                "id": pid,
                "element": element,
                "fg": TOK.get(base_fg, base_fg) + (("@" + fg.split("@")[1]) if "@" in fg else ""),
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


# C. the E24 format rows (the E25 sheet of E25-D03 section 2 by reference) and D02's arithmetic
THIN = "\u2009"
MINUS = "\u2212"
OI_BOTH_SIDES_USDT = Decimal(
    "4792254559.42"
)  # E24-D02 section 15: the memo's recorded both-sides OI
CASCADE_PUSH = {"prints": 620, "window_ms": 500}  # E24-D02 section 6: one 500 ms push of 620 prints
FEED_MARK = Decimal("82751.20")  # E24-D02 section 6: the illustrative feed row's bankruptcy price p


def signed(v: Decimal, places: str) -> str:
    q = v.quantize(Decimal(places), rounding=ROUND_HALF_UP)
    sign = MINUS if q < 0 else "+"
    return f"{sign}{abs(q)}"


def fmt_rate(rate: Decimal) -> str:
    """Funding rate: four decimals, the sign as text (U+2212), a space before %."""
    return f"{signed(rate * 100, '0.0001')} %"


def fmt_annualised(rate: Decimal, interval_min: int, with_sign: bool = False) -> str:
    pct = Decimal(arith.annualised_pct(rate, interval_min))
    body = signed(pct, "0.01") if with_sign else f"{pct:.2f}"
    return f"{body} % p.a."


def fmt_basis(mark: Decimal, index: Decimal, tick_decimals: int = 2) -> str:
    basis = (mark - index).quantize(Decimal(10) ** -tick_decimals, rounding=ROUND_HALF_UP)
    pct = ((mark - index) / index * 100).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return f"{signed(basis, '0.01')} ({signed(pct, '0.001')} %)".replace(
        "+", "", 1 if basis >= 0 else 0
    )


def fmt_abbrev(v: Decimal) -> str:
    for cut, suffix in ((Decimal(10**9), "B"), (Decimal(10**6), "M"), (Decimal(10**3), "k")):
        if v >= cut:
            return f"{(v / cut).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}{suffix}"
    return f"{v.quantize(Decimal(1)):,}"


def fmt_exact_usdt(v: Decimal) -> str:
    return f"{v.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,} USDT"


def fmt_change(pct: Decimal, window: str) -> str:
    return f"{signed(pct, '0.1')} % {window}"


def fmt_int(v: int) -> str:
    return f"{v:,d}"


SAMPLES: list[tuple[str, str]] = [
    ("funding rate +0.0001", fmt_rate(Decimal("0.0001"))),
    ("funding rate -0.005", fmt_rate(Decimal("-0.005"))),
    ("annualised 0.0001 @ 480", fmt_annualised(Decimal("0.0001"), 480)),
    ("annualised 0.0001 @ 60", fmt_annualised(Decimal("0.0001"), 60)),
    ("annualised -0.005 @ 480", fmt_annualised(Decimal("-0.005"), 480, with_sign=True)),
    ("basis 82751.20 / 82782.37", fmt_basis(Decimal("82751.20"), Decimal("82782.37"))),
    ("OI single side", f"{fmt_abbrev(OI_BOTH_SIDES_USDT / 2)} USDT"),
    ("OI both sides", f"{fmt_abbrev(OI_BOTH_SIDES_USDT)} USDT"),
    ("OI change +2.1 1h", fmt_change(Decimal("2.1"), "1h")),
    ("Liq long 4.2M", f"{fmt_abbrev(Decimal(4200000))} USDT"),
    ("Liq short 1.1M", f"{fmt_abbrev(Decimal(1100000))} USDT"),
    ("Liq long 9.8M", f"{fmt_abbrev(Decimal(9800000))} USDT"),
    ("feed notional 0.498 x p", fmt_exact_usdt(arith.FEED_SIZE * FEED_MARK)),
    ("cascade long row", fmt_exact_usdt(Decimal("48.00") * Decimal("82500.00"))),
    ("cascade short row", fmt_exact_usdt(Decimal("1.20") * Decimal("82600.00"))),
    (
        "prints per second",
        f"{fmt_int(CASCADE_PUSH['prints'] * 1000 // CASCADE_PUSH['window_ms'])} prints/s",
    ),
    ("charge", f"\u2248 {arith.CHARGE} USDT"),
    ("size at the qty step", f"{arith.FEED_SIZE} BTC"),
    ("cluster", f"\u00d7{arith.FEED_EVENTS}"),
    ("countdown >= 1 h", arith.hms(arith.LADDER_MS[0])),
    ("countdown < 1 h", arith.hms(arith.LADDER_MS[1])),
    ("countdown < 5 min", arith.hms(arith.LADDER_MS[2])),
    ("countdown < 1 min", arith.hms(arith.LADDER_MS[3])),
    ("settlement restart", arith.hms(arith.RESTART_MS)),
    ("interval", "/ 8 h"),
    ("at cap -0.005 / 0.005", arith.at_cap(Decimal("-0.005"), arith.CAP_EXAMPLE)),
    ("at cap +0.005 / 0.005", arith.at_cap(Decimal("0.005"), arith.CAP_EXAMPLE)),
    ("charge implied notional", f"{(arith.CHARGE / arith.RATE).quantize(Decimal(1)):,} USDT"),
    ("zone label", f"{fmt_int(82400)}\u2013{fmt_int(82520)} (estimated)"),
]
MONO_EM = 0.62  # the lane's mono advance (E25-D03 section 3.1)
NUM_SM_PX = 11  # type.num.sm = font.size.xs
FEED_FIRST_LINE = "09:14:02 \u00b7 Long liquidated \u25bc \u00b7 41,210.10 USDT"  # D02 section 12
GUTTER_MIN_PX = 48  # E11-D02 D7: the price gutter is >= 48 px wide
INSET_PX = 8  # space.inset.sm, both sides of the pane
FLOOR = {"bar_px": 6, "half_px": 3, "tips_from_px": 10}  # BQ-03 RULED, stamped Q12 / E24-S02


def formats(problems: list[str]) -> dict[str, Any]:
    if int(T["dark"]["font.size.xs"]) != NUM_SM_PX:
        problems.append("type.num.sm is no longer 11 px; the narrow-width line is stale")
    if int(T["dark"]["space.inset.sm"]) != INSET_PX:
        problems.append("space.inset.sm is no longer 8 px; the narrow-width line is stale")
    chars = len(FEED_FIRST_LINE)
    line_px = math.ceil(chars * NUM_SM_PX * MONO_EM)
    if FLOOR["half_px"] < 2:
        problems.append("the pattern floor's half-width bar is under 2 device px at 1x")
    return {
        "samples": SAMPLES,
        "feed_line_chars": chars,
        "feed_line_px": line_px,
        "narrow_min_px": line_px + GUTTER_MIN_PX + 2 * INSET_PX,
        "floor": FLOOR,
        "thin_space": "U+2009",
        "minus": "U+2212",
        "constant_in_funding_py": arith.MINUTES_PER_YEAR,
    }


# D. greyscale, deuteranopia and protanopia (cvd_sim.py's maths on single colours)
DEUT = (
    (0.367322, 0.860646, -0.227968),
    (0.280085, 0.672501, 0.047413),
    (-0.011820, 0.042940, 0.968881),
)
PROT = (
    (0.152286, 1.052583, -0.204868),
    (0.114503, 0.786281, 0.099216),
    (-0.003882, -0.048116, 1.051998),
)


def grey(h: str) -> str:
    r, g, b = rgb(h)
    y = r * 0.299 + g * 0.587 + b * 0.114
    return hexs((y, y, y))


def sim(h: str, m: tuple[tuple[float, float, float], ...]) -> str:
    c = rgb(h)
    out = tuple(sum(a * v for a, v in zip(row, c, strict=True)) for row in m)
    return hexs((out[0], out[1], out[2]))


CVD_PAIRS = rows_of("""quadrant palette: candle.up vs candle.down (position x width carry)|up|down
liquidation ink vs the canvas (axis half + glyph + word carry)|danger.default|canvas
CMP-127 danger vs candle.down on the price pane (bar-edge anchor + glyph carry)|danger.default|down
(a) band outline vs (b) bar in one pane (hatch vs solid + the chip carry)|info.default|profile
funding series vs the canvas (the hollow dashed marker + the word carry)|line|canvas""")


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
                "a_deut": sim(ha, DEUT),
                "a_prot": sim(ha, PROT),
                "b_grey": grey(hb),
                "b_deut": sim(hb, DEUT),
                "b_prot": sim(hb, PROT),
                "sep": (
                    ratio(ha, hb),
                    ratio(grey(ha), grey(hb)),
                    ratio(sim(ha, DEUT), sim(hb, DEUT)),
                    ratio(sim(ha, PROT), sim(hb, PROT)),
                ),
            }
        out["pairs"].append({"pair": label, "a": TOK[a], "b": TOK[b], "themes": per_theme})
    # the candle pair in dark must be the buy / sell pair E22-D03 section 8.3 simulated (one
    # primitive), so the greyscale / deuteranopia hexes reproduce
    d = out["pairs"][0]["themes"]["dark"]
    exp = ("#878787", "#9F905E", "#787878", "#81744B")
    got = (d["a_grey"], d["a_deut"], d["b_grey"], d["b_deut"])
    out["e22_d03_reproduced"] = got == exp
    if got != exp:
        problems.append(f"E22-D03 section 8.3 greyscale / deuteranopia not reproduced: {got}")
    return out


# E. the board plan and the spec's id tables
BOARD_RX = re.compile(r"^\| (0[1-9]|1[0-9]) +\| `")
MAX_BOARDS = 10
EXPECT_STATES = 78  # S54-1 … S54-78: every E24-D02 frame and inset (D02 section 21's Frames column)


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
    if [r for r in rows if len(r) < 6 or r[5] != "PENDING"]:
        problems.append("board plan: a board row is not PENDING in PR 1")
    if len(rows) <= MAX_BOARDS and f"{len(rows)} boards" not in spec:
        problems.append(f"board plan: the spec does not state {len(rows)} boards")
    if twins <= len(rows) // 3 and f"{twins} light twins" not in spec:
        problems.append(f"board plan: the spec does not state {twins} light twins")
    return {"boards": len(rows), "light_twins": twins, "slugs": slugs}


# the S54 rows' "`frame` (D02 board → D03 board)" cell; the D03 boards are the ones whose §0 Folds
# must carry the frame id, and every Folds id must be named by a row for that board (both ways)
FRAME_RX = re.compile(r"`([^`]+)` \(([\d, ]+) → ([\d, ]+)\)")
STATE_RX = re.compile(r"^\| S54-\d+")


def folds(spec: str, problems: list[str]) -> dict[str, Any]:
    on_board: dict[str, set[str]] = {}
    for ln in spec.splitlines():
        if BOARD_RX.match(ln):
            c = cells(ln)
            on_board[c[0]] = set(re.findall(r"`([^`]+)`", c[4])) if len(c) > 4 else set()
    named: dict[str, set[str]] = {}
    mapped = 0
    for ln in spec.splitlines():
        if not STATE_RX.match(ln):
            continue
        c = cells(ln)
        m = FRAME_RX.search(c[1]) if len(c) > 1 else None
        if m is None:
            problems.append(f"{c[0]}: no `frame` (D02 board → D03 board) cell")
            continue
        fid, to = m.group(1), [b.strip() for b in m.group(3).split(",")]
        mapped += 1
        lost = [b for b in to if fid not in on_board.get(b, set())]
        if lost:
            problems.append(f"{c[0]} `{fid}` → board {', '.join(lost)} whose §0 Folds lack it")
        for b in to:
            named.setdefault(b, set()).add(fid)
    for b, ids in sorted(on_board.items()):
        for fid in sorted(ids - named.get(b, set())):
            problems.append(f"board {b} Folds carry `{fid}` but no S54 row names board {b} for it")
    return {"state_rows_mapped": mapped, "fold_ids": sum(len(v) for v in on_board.values())}


# the `pairs.mjs` column: "registered" exactly when the fg / bg pair is a `PAIRS` entry of
# tools/contrast/pairs.mjs (parsed read-only; a composited `@` row is never a registry pair)
PAIR_ENTRY_RX = re.compile(r'fg:\s*"([^"]+)",\s*bg:\s*"([^"]+)"', re.DOTALL)
P_ROW_RX = re.compile(r"^\| P\d+ ")


def registered_pairs(pairs_text: str) -> set[tuple[str, str]]:
    block = section(pairs_text, "export const PAIRS = [", "\n];")
    return set(PAIR_ENTRY_RX.findall(block))


def registry(spec: str, problems: list[str], pairs_text: str) -> dict[str, Any]:
    reg = registered_pairs(pairs_text)
    if not reg:
        problems.append("tools/contrast/pairs.mjs: no PAIRS entries parsed")
    tool = {pid: cell for pid, _e, _fg, _bg, _r, cell in PAIRS}
    rows = 0
    for ln in spec.splitlines():
        if not P_ROW_RX.match(ln):
            continue
        c = cells(ln)
        if len(c) < 8:
            problems.append(f"{c[0]}: the matrix row has no pairs.mjs cell")
            continue
        pid, fg, bg, cell = c[0], c[2].strip("`"), c[3].strip("`"), c[7]
        rows += 1
        present = "@" not in fg and (fg, bg) in reg
        if cell.startswith("registered") != present or cell != tool.get(pid):
            has = "has" if present else "lacks"
            problems.append(
                f"pairs.mjs column {pid}: the spec says {cell!r}, the tool {tool.get(pid)!r}, "
                f"the registry {has} the pair"
            )
    if rows != len(PAIRS):
        problems.append(f"matrix rows: {rows} in the spec, {len(PAIRS)} in the tool")
    return {"registry_pairs": len(reg), "matrix_rows": rows}


def counts(spec: str, problems: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    out["S54"] = sum(1 for ln in spec.splitlines() if re.match(r"^\| S54-\d+ ", ln))
    if out["S54"] != EXPECT_STATES:
        problems.append(f"S54 rows: {out['S54']} (the spec's inventory carries {EXPECT_STATES})")
    for k, rx in (
        ("M", r"^\| M-\d+ "),
        ("A", r"^\| A-\d+ "),
        ("HO", r"^\| HO-\d+ "),
        ("AN", r"^\| AN-\d+ "),
        ("C", r"^\| D03-C\d+ "),
        ("G", r"^\| D03-G\d+ "),
        ("H", r"^\| H-\d+ "),
        ("D", r"^\| D-\d+ "),
        ("T2", r"^\| T2-\d+ "),
    ):
        out[k] = sum(1 for ln in spec.splitlines() if re.match(rx, ln))
    return out


# F. the spec's tables and strings
CHIP_RULES = rows_of(
    """CMP-227 inline (predicted funding, zone legend row)|color.status.info.subtle|color.status.info.default|color.text.primary
CMP-227 marker (the band chip on the price pane)|color.status.info.default|color.surface.canvas|pattern.dashed.estimated
Stale chip (CMP-239)|color.data-confidence.stale.surface|color.data-confidence.stale.text|color.data-confidence.stale.indicator
N new chip (CMP-011 neutral)|color.neutral.subtle|color.border.default|color.text.secondary"""
)
NEGATED = re.compile(
    r"\b(no|never|not|forbidden|crossed out|drops?|dropped|rejected|replacing|replaces|vs)\b",
    re.IGNORECASE,
)
SIDE_HUE = re.compile(r"color\.(buy|sell)\.|colorBySign")
CODE_RX = re.compile(
    r"`([^`\n]+)`"
)  # inline code spans, paired in order (never prose between two spans)
PREDICTED_EXEMPT = ("(estimated)", "predicted-", "-predicted", "predicted:", "Predicted")
ZONE_EXEMPT = ("estimated", "zones-", "-zones", "zones_", "zone section")
T2_DIM = re.compile(r"color\.text\.disabled|opacity\.disabled")
K01_FORBIDDEN = ("estimated liquidation levels",)
K01_PERMITTED = (
    "Shows where forced liquidations were actually recorded, grouped by price.",
    "Past liquidation clusters are not a forecast of future liquidations.",
    "Histogram of recorded liquidations by price level. Not a prediction.",
    "this is an estimate, not exchange-provided fact",
    "held back by E24-K01 §1 item 2",
    "not built until the real-data re-run",
    # K01 section 5 (a), verbatim — the failure-mode sentence E25-T07 takes as production copy
    (
        "wrong leverage mix shifts every zone; cross vs isolated margin, hedging and manual "
        "deleveraging are invisible; zones look precise but are invented."
    ),
)
SPOKEN_FORBIDDEN = ("/s", "hh:mm", "≈", " % ")
MUST = (  # E24-D02 strings the hi-fi carries verbatim (changes no word but the three ruled strings)
    "Derivatives context BTCUSDT",
    "Funding 0.0100 % / 8 h · 10.95 % p.a. · predicted (estimated) · next in 03:12:44",
    "Mark 82,751.20 · Index 82,782.37 · Basis −31.17 (−0.038 %)",
    "basis, mark − index · source",
    "OI 2.4B USDT (single side) · +2.1 % 1h",
    "OI 4.8B USDT (both sides) · +2.1 % 1h",
    "Liq 1 h · long 4.2M USDT · short 1.1M USDT",
    "Liq 1 h · long 9.8M USDT ▼ · short 1.2M USDT ▲ · 1,240 prints/s",
    "Liq 1 h · not recorded",
    "L/S ratio · source unavailable",
    "settled rate pending",
    "settles every 8 h",
    "settles every 1 h · changed 08:04 UTC",
    "at lower cap",
    "at upper cap",
    "next settlement time not published",
    "Funding n/a · settles every 8 h",
    "0.0100 % × (525600 / 480) = 10.95 % p.a.",
    "The rate accruing for the next settlement; it can still move until then. Bybit publishes no separate predicted rate.",
    "Funding settles in 00:04:12 — you pay ≈ 12.40 USDT on Demo 1 · DEMO",
    "Funding settles in 00:04:12 — you receive ≈ 12.40 USDT on Demo 1 · DEMO",
    "Funding settles in 00:00:59 — you pay ≈ 12.40 USDT on Demo 1 · DEMO",
    "price · OI: ▲▲ long build-up 12 · ▲▼ short covering 3 · ▼▲ short build-up 5 · ▼▼ long unwind 8",
    "classified on contracts",
    "3 unclassified (no OI sample)",
    "Native granularity 5 min",
    "Quadrants off",
    "Short liquidated ▲ above · Long liquidated ▼ below",
    "Showing prints ≥ 50,000 USDT",
    "Bybit publishes liquidations in 500 ms batches; every print is included — history is limited to what the recorder captured",
    "09:14:02 · Long liquidated ▼ · 0.498 BTC · 82,751.20 · 41,210.10 USDT · ×8",
    "Recorded from 09:14 UTC",
    "Not recorded before 09:14 UTC — this is not 'no liquidations'",
    "Not recorded 17:02–17:09 UTC · connection to Bybit dropped",
    "coverage unknown before 24 Jul",
    "Recording metadata is not available yet; retry shortly.",
    "Couldn't load OI history · Retry",
    "Last loaded 09:14:02 UTC",
    "No funding has settled for SOLUSDT yet",
    "Updates every 1 s, ×4 slower",
    "Realised liquidations (recorded)",
    "decay off",
    "Estimated zones (assumed leverage)",
    "82,400–82,520 (estimated)",
    "Show estimated zones?",
    "Recorded liquidations by price (this session) · Not available to rules",
    "Recording settings for BTCUSDT…",
    "Your role can't start recording.",
    "Only the owner can start recording.",
    "Your role can't change settings.",
    "Your role can't change alerts.",
    "Read-only while viewing as {user}.",
    "Display changes last for this session.",
    "Alert me 5 min before settlement",
    "predicted (estimated)",
    "Stale 7s · last 13:42:05",
    "Stale 15s · last 13:41:57",
)
FORBIDDEN = {  # assembled so this file does not itself carry the words it forbids
    "local path": re.compile("/ho" + r"me/\w+|/Us" + r"ers/\w+|C:\\\\"),
    "worker name": re.compile(r"\b[a-z]{2,5}-worker-\d+\b|wt-no" + r"tes|\bAgent [A-C]\b"),
    "host or url": re.compile(r"https?://|penpot\.[a-z]|\.candleviewer\.com"),
    "colour emoji": re.compile("[\U0001f300-\U0001faff\u2600-\u26ff]"),
    "page id or uuid": re.compile(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
    ),
}
RULE_RX = re.compile(r"\bC-\d+\.\d+\b")
CITE_22_RX = re.compile(r"`22` (\d{4,5})|`22:(\d{4,5})`")
RBAC_22 = {  # operationId -> the permission its x-rbac row must carry (verified, never assumed)
    "updateSettings": "settings:write",
    "createAlert": "alerts:write",
    "addRecordedSymbol": "recording:write",
    "getLiquidations": "marketdata:read",
}
POINTER_14 = "- **Hi-fi (E24-D03):** [E24-D03.md](../design/E24/E24-D03.md) (E24-D03; owner approval pending; text-first"
STALE_14 = "landing with their exports in a later PR"


def window(text: str, i: int, j: int, span: int = 60) -> str:
    return text[max(0, i - span) : j + span]


def unnegated(text: str, rx: re.Pattern[str]) -> bool:
    return any(not NEGATED.search(window(text, m.start(), m.end())) for m in rx.finditer(text))


def rbac_rows(api_text: str) -> dict[str, tuple[int, str]]:
    """The `22` x-rbac line after each operationId the spec cites: (line, permission)."""
    lines = api_text.splitlines()
    out: dict[str, tuple[int, str]] = {}
    for i, ln in enumerate(lines):
        for op in RBAC_22:
            if ln.strip() == f"operationId: {op}":
                for j in range(i, min(i + 40, len(lines))):
                    m = re.search(r"x-rbac: \{ permissions: \[([a-z:]+)\]", lines[j])
                    if m:
                        out[op] = (j + 1, m.group(1))
                        break
    return out


def table_gates(spec: str, problems: list[str], texts: dict[str, str]) -> dict[str, Any]:
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
    s_oi = section(spec, "\n## 4.", "\n## 5.")
    s_fund = section(spec, "\n## 5.", "\n## 6.")
    s_liq = section(spec, "\n## 6.", "\n## 7.")
    s_zone = section(spec, "\n## 7.", "\n## 8.")
    s_058 = section(spec, "\n## 14.", "\n## 15.")
    if not all((s_oi, s_fund, s_liq, s_zone, s_058)):
        problems.append(
            "sections 4 (OI), 5 (funding), 6 (liquidations), 7 (zones) or 14 (SCR-058) not found"
        )
    # the quadrants bind the candle slots; nothing in section 4 binds a trading-action hue
    if "`color.candle.up`" not in s_oi or "`color.candle.down`" not in s_oi:
        problems.append("OI section does not bind color.candle.up and color.candle.down")
    if unnegated(s_oi, SIDE_HUE):
        problems.append("OI section binds a buy / sell hue to a quadrant")
    # no side hue on funding; the predicted rate is never a step of the settled line
    if unnegated(s_fund, SIDE_HUE):
        problems.append("funding section binds a buy / sell hue or colorBySign")
    if "never a step of the settled line" not in s_fund:
        problems.append(
            "funding section does not state that the predicted rate is never a settled step"
        )
    if "`pattern.dashed.estimated`" not in s_fund:
        problems.append(
            "funding section does not bind pattern.dashed.estimated to the predicted marker"
        )
    # one danger hue on liquidations, both sides; never a buy / sell hue
    if "`color.status.danger.default`" not in s_liq:
        problems.append("liquidation section does not bind color.status.danger.default")
    if unnegated(s_liq, SIDE_HUE):
        problems.append("liquidation section binds a buy / sell hue to a liquidation")
    # no chip on recorded (b) data; every zone label carries (estimated)
    rec = next(
        (
            ln
            for ln in s_zone.splitlines()
            if "zones-k01-recorded" in ln and ln.startswith("| S54-")
        ),
        "",
    )
    if not rec:
        problems.append("zones section has no S54 row for zones-k01-recorded")
    elif unnegated(rec, re.compile("CMP-227|chip|badge")):
        problems.append("the recorded (b) histogram row draws a chip or badge")
    if "`pattern.hatch.estimated`" not in s_zone or "82,400–82,520 (estimated)" not in s_zone:
        problems.append("zones section lacks the hatch or the badged zone label")
    # every copy string with the word predicted carries its (estimated) chip; every zone string its word
    for s in CODE_RX.findall(spec):
        if re.search(r"\bpredicted\b", s) and not any(x in s for x in PREDICTED_EXEMPT):
            problems.append(f"a predicted string without its (estimated) carrier: {s!r}")
        if re.search(r"\bzones?\b", s, re.IGNORECASE) and not any(
            x in s.lower() for x in ZONE_EXEMPT
        ):
            problems.append(f"a zone string without its (estimated) carrier: {s!r}")
    # the T2 look never dims: no disabled text or opacity token bound anywhere
    if unnegated(spec, T2_DIM):
        problems.append("the T2 look binds color.text.disabled or opacity.disabled")
    # the SCR-058 section: the template words, the permitted sentences, the forbidden phrases
    for s in K01_PERMITTED:
        if s not in s_058:
            problems.append(f"SCR-058 section lacks {s!r}")
    for s in K01_FORBIDDEN:
        if s.lower() in s_058.lower():
            problems.append(f"SCR-058 section carries the forbidden phrase {s!r}")
    if unnegated(s_058, re.compile(r"liquidation zones(?! \(recorded\))", re.IGNORECASE)):
        problems.append("SCR-058 section says 'liquidation zones' without 'recorded'")
    if "Liquidation cluster (estimated)" not in s_058:
        problems.append("SCR-058 section heading is not 'Liquidation cluster (estimated)'")
    # motion: exactly the two standing timed transitions, both with a reduce cell
    m_rows = [cells(ln) for ln in lines if re.match(r"^\| M-\d+ ", ln)]
    timed = [r[0] for r in m_rows if "motion.duration." in r[2]]
    out["motion_rows"] = len(m_rows)
    if len(m_rows) != 2 or len(timed) != 2 or any(not r[3] for r in m_rows):
        problems.append(
            f"motion table: {len(m_rows)} rows, {len(timed)} timed — the spec states the two standing ones only"
        )
    # announcements in the spoken form
    an_rows = [cells(ln) for ln in lines if re.match(r"^\| AN-\d+ ", ln)]
    out["announcement_rows"] = len(an_rows)
    for r in an_rows:
        if any(f in r[2] for f in SPOKEN_FORBIDDEN):
            problems.append(f"announcement {r[0]} is not in the spoken form")
    # E24-D02 strings verbatim; the ruled OI strings replace D02's two-decimal ones
    problems += [f"E24-D02 string missing: {s!r}" for s in MUST if s not in spec]
    for ln in lines:
        if "2.40B" in ln and "C-6" not in ln and "D02" not in ln:
            problems.append("a two-decimal OI level survives outside the C-6 record")
    out["must"] = len(MUST)
    # A-rows: the "today" cell is `15` at the base, verbatim; the entry heading exists
    cat = CATALOGUE_15.read_text(encoding="utf-8")
    a_rows = [cells(ln) for ln in lines if re.match(r"^\| A-\d+ ", ln)]
    for r in a_rows:
        entry = r[1].strip("`")
        if entry.startswith("CMP-") and f"### {entry} " not in cat:
            problems.append(f"{r[0]}: `15` has no entry {entry}")
        today = r[3].strip().strip('"')
        if today and today not in cat:
            problems.append(f"{r[0]}: the today cell is not `15` text verbatim")
    out["a_rows"] = len(a_rows)
    # the `22` x-rbac rows the spec cites exist with the permission the spec claims
    rb = rbac_rows(texts["22"])
    out["rbac"] = rb
    for op, perm in RBAC_22.items():
        got = rb.get(op)
        if got is None or got[1] != perm:
            problems.append(f"`22` {op} does not carry x-rbac {perm}")
        elif f"`22` {got[0]}" not in spec and f"22:{got[0]}" not in spec:
            problems.append(f"the spec does not cite `22` {got[0]} for {op} ({perm})")
    # the `14` pointer line and the ruled :1291 edit (BQ-16)
    s14 = texts["14"]
    scr054 = section(s14, "\n### SCR-054 ", "\n### SCR-055 ")
    if POINTER_14 not in scr054:
        problems.append("`14` SCR-054 lacks the Hi-fi (E24-D03) pointer line")
    if STALE_14 in scr054:
        problems.append("`14` SCR-054 still says the D02 boards land in a later PR (BQ-16)")
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
def drift(spec: str, mx: dict[str, Any], fm: dict[str, Any], cv: dict[str, Any]) -> list[str]:
    need: list[str] = [r["text"] for r in mx["rows"]]
    need += [f"{mx['pairs']} pairs × 3 themes", f"{mx['gated']} gated", f"FAIL {mx['fail']}"]
    if mx["repro_ok"] == mx["repro_n"]:  # a lost reproduction is already its own FAIL (section B)
        need.append(f"{mx['repro_ok']} of {mx['repro_n']} reproductions")
    need += [s for _, s in fm["samples"]]
    need += [
        f"{fm['feed_line_chars']} mono chars",
        f"{fm['feed_line_px']} px",
        f"{fm['narrow_min_px']} px",
    ]
    need += [f"{fm['floor']['bar_px']} px per bar", f"{fm['floor']['tips_from_px']} px per bar"]
    for p in cv["pairs"]:
        for t in THEMES:
            s = p["themes"][t]["sep"]
            need.append(f"{s[0]:.2f} / {s[1]:.2f} / {s[2]:.2f} / {s[3]:.2f}")
    return [n for n in need if n not in spec]


def evaluate(
    spec: str,
    texts: dict[str, str] | None = None,
    repro: dict[str, tuple[float, float, float]] | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """`texts` overrides the files a gate reads (`14`, `22`, `pairs`); `repro` the REPRO table."""
    given = texts or {}
    files = {k: given.get(k) or read(p) for k, p in FILES.items()}
    problems: list[str] = []
    out: dict[str, Any] = {}
    out["tokens"] = tokens(spec)
    problems += [f"token does not resolve: {n}" for n in out["tokens"]["missing"]]
    problems += [
        f"a DS request shipped as a token; retire the G-row: {n}" for n in out["tokens"]["shipped"]
    ]
    out["matrix"] = matrix(problems, repro)
    out["registry"] = registry(spec, problems, files["pairs"])
    out["formats"] = formats(problems)
    out["cvd"] = cvd(problems)
    out["boards"] = boards(spec, problems)
    out["folds"] = folds(spec, problems)
    out["counts"] = counts(spec, problems)
    out["gates"] = table_gates(spec, problems, files)
    out["drift"] = drift(spec, out["matrix"], out["formats"], out["cvd"])
    problems += [f"drift: the spec does not carry {n!r}" for n in out["drift"]]
    out["problems"] = problems
    return problems, out


# ------------------------------------------------------------------ self-test -------------------
# (name, old, new[, times][, target]): `times` = occurrences to replace (-1 = all; default 1);
# `target` = "spec" (default), a FILES key ("14", "22", "pairs") whose text is mutated instead, or
# "repro" (old = the pair id, new = its JSON expectation) for a reproduction the tokens no longer give.
MUTATIONS: tuple[tuple[str | int, ...], ...] = (
    ("a contrast value drifts", "14.35 / 15.62 / 16.25", "14.36 / 15.62 / 16.25"),
    (
        "a token name is invented",
        "`color.status.danger.default` (fill",
        "`color.status.danger.deflt` (fill",
    ),
    ("a format sample drifts", "`−547.50 % p.a.`", "`−547.5 % p.a.`"),
    (
        "an eleventh board",
        "| 10  | `contrast-cvd-formats-ds-requests`",
        "| 11  | `extra` | x | dark | — | PENDING |\n| 10  | `contrast-cvd-formats-ds-requests`",
    ),
    ("an E24-D02 string changes", "Show estimated zones?", "Show estimated zones."),
    (
        "a side hue on the funding rate",
        "no side hue, no `colorBySign`",
        "the rate in `color.buy.default`",
    ),
    (
        "a quadrant in a trading hue",
        "price ↑ bars **`color.candle.up`**",
        "price ↑ bars **`color.buy.default`**",
    ),
    (
        "a liquidation in the sell hue",
        "one hue, **`color.status.danger.default`**, both sides",
        "two hues, `color.sell.default` for a long liquidated and `color.buy.default` for a short",
    ),
    (
        "a chip on recorded data",
        "no badge, no chip (K01 §1 item 1; E25-D05 §4.6)",
        "a CMP-227 chip beside the legend row",
    ),
    (
        "a predicted string loses its carrier",
        "· 0.0100 % predicted (estimated) ·",
        "· 0.0100 % predicted ·",
    ),
    ("a K01 forbidden phrase", "## 14. SCR-058", "## 14. SCR-058 estimated liquidation levels —"),
    (
        "a third timed transition",
        "| M-2 ",
        "| M-3  | collapse | `motion.duration.fast` | instant | the stub | — |\n| M-2 ",
    ),
    ("an announcement in the written form", "1,240 per second", "1,240 /s"),
    ("a local path leaks", "## 25. Summary", "## 25. Summary (/ho" + "me/someone/notes)"),
    ("a state row is lost", "| S54-78 |", "| S54-78x |"),
    (
        "a zone string loses its word",
        "`Estimated zones (assumed leverage)` as a CMP-004 switch",
        "`Zones (assumed leverage)` as a CMP-004 switch",
    ),
    (
        "the T2 look dims the label",
        "never `color.text.disabled` or `opacity.disabled`",
        "the label in `color.text.disabled` or `opacity.disabled`",
    ),
    ("a `22` x-rbac cite drifts", "(`22` 10229)", "(`22` 10228)"),
    (
        "a chip loses its binding",
        "`color.status.info.subtle` (fill), `color.status.info.default`",
        "`color.status.info.subtle` (fill), `color.status.info.strong`",
    ),
    ("a dangling rule cite", "(C-2.13 / C-2.14)", "(C-2.13 / C-9.99)"),
    ("an A-row misquotes 15", '"`color.status.danger`."', '"`color.status.danger.default`."'),
    (
        "a two-decimal OI level returns",
        "`OI 2.4B USDT (single side) · +2.1 % 1h`",
        "`OI 2.40B USDT (single side) · +2.1 % 1h`",
    ),
    (
        "a state row names a board whose Folds lack it",
        "`oi-empty` (05 → 03)",
        "`oi-empty` (05 → 03, 10)",
    ),
    ("a pairs.mjs claim is wrong", "PROPOSED (E12-D09)", "registered"),
    ("the `14` pointer line is lost", "- **Hi-fi (E24-D03):**", "- **Hi-fi (E24-D03x):**", "14"),
    (
        "a `22` x-rbac permission mismatches",
        "permissions: [settings:write]",
        "permissions: [settings:read]",
        -1,
        "22",
    ),
    ("a third of the boards go light", "| dark              | `", "| light             | `", 2),
    (
        "a chip row is missing",
        "| N new chip (CMP-011 neutral) ",
        "| N new chip (CMP-011 neutral)x ",
    ),
    ("a reproduction is lost", "P1", "[14.36, 15.62, 16.25]", "repro"),
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def mutate(
    spec: str, old: str, new: str, times: int, target: str
) -> tuple[str, dict[str, str] | None, dict[str, tuple[float, float, float]] | None, bool]:
    """The (spec, texts, repro) a mutation evaluates, and whether it applied."""
    if target == "repro":
        exp = json.loads(new)
        return spec, None, {**REPRO, old: (exp[0], exp[1], exp[2])}, old in REPRO
    text = spec if target == "spec" else read(FILES[target])
    applies = text.count(old) >= max(times, 1)
    mutated = text.replace(old, new, times)
    if target == "spec":
        return mutated, None, None, applies
    return spec, {target: mutated}, None, applies


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
        times = next((r for r in rest if isinstance(r, int)), 1)
        target = next((r for r in rest if isinstance(r, str)), "spec")
        m_spec, m_texts, m_repro, applies = mutate(spec, str(old), str(new), times, target)
        if not applies:
            ok = False
            print(f"mutation {no:02d} {name}: DOES NOT APPLY (the text to mutate is gone)")
            continue
        got, _ = evaluate(m_spec, m_texts, m_repro)
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
        tk = out["tokens"]
        print(f"A. tokens named {tk['named']}, missing {tk['missing']}, aliases {tk['aliases']}")
        print(
            f"B. matrix: {mx['pairs']} pairs × 3 themes, {mx['gated']} gated, FAIL {mx['fail']}, "
            f"{mx['repro_ok']} of {mx['repro_n']} reproductions"
        )
        for r in mx["rows"]:
            print(
                f"   {r['id']:<4} {r['role']:<17} {r['text']:<24} {r['verdict']:<28} {r['element']}"
            )
        fm = out["formats"]
        print("C. formats:")
        for k, s in fm["samples"]:
            print(f"   {k:<28} {s}")
        print(
            f"   the feed's first line at {fm['feed_line_chars']} mono chars is {fm['feed_line_px']} px; "
            f"+ gutter {GUTTER_MIN_PX} + insets 2 × {INSET_PX} = {fm['narrow_min_px']} px (PROPOSED, NG-4); "
            f"floor {fm['floor']}"
        )
        print("D. CVD (normal / greyscale / deuteranopia / protanopia separation):")
        for p in out["cvd"]["pairs"]:
            for t in THEMES:
                d = p["themes"][t]
                s = d["sep"]
                print(
                    f"   {t:<13} {p['pair']}: {d['a']} -> {d['a_grey']} / {d['a_deut']} / {d['a_prot']}; "
                    f"{d['b']} -> {d['b_grey']} / {d['b_deut']} / {d['b_prot']}; "
                    f"{s[0]:.2f} / {s[1]:.2f} / {s[2]:.2f} / {s[3]:.2f}"
                )
        print(
            f"E. boards {out['boards']['boards']}, light twins {out['boards']['light_twins']}, "
            f"folds {out['folds']}, registry {out['registry']}"
        )
        print(f"F. counts {out['counts']}; gates {out['gates']}")
        print(f"G. drift {len(out['drift'])}")
        for p in problems:
            print(f"FAIL {p}")
        print(f"rc {1 if problems else 0}")
    if "--check" in argv or "--json" in argv:
        return 1 if problems else 0
    own = ("contrast FAIL", "reproduction lost", "type.num.sm", "space.inset.sm", "E22-D03")
    return 1 if [p for p in problems if p.startswith(own)] else 0


if __name__ == "__main__":
    raise SystemExit(main())
