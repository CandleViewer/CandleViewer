"""E18-D01 footprint cell geometry over the plan's own scenes; provenance on every row.

Standalone, offline, stdlib only. Every input is a planning assumption quoted from a plan or design
document (named per constant); none is market evidence or came from a recorded tape. Per scene: the
cell height in CSS px (pane height / visible price rows); the `LOD_PROFILE_M0` rung it reaches when
zooming in (E06-D01 §2: L0 >= 12, L1 >= 10, L2 >= 6 px, else L3; down-switch 10.2 / 8.5 / 5.1 px);
the bar width (plot width / visible bars); the cell-width floor per mode from E06-D01 §4's widest
strings (7 glyphs per full number, 6 per signed delta) at 0.62 em plus E06-D01 §2's gutters, read
per side-cell, so the memo can say where width binds before height. Densities: E11-D02 D6's three
(comfortable / compact / dense; dense shares compact's glyph size and LOD bias). Displays: E18-D02's
artboards; chrome: E11-D02 §2 compact; scale: §6 rule 6.

Usage: python3 -I docs/design/_tools/e18_d01_cell_geometry.py [--json]
"""

from __future__ import annotations

import json
import sys
from decimal import ROUND_HALF_UP, Decimal

D = Decimal
PX, ZERO, ONE = D("0.1"), D(0), D(1)
TICK_BTCUSDT = D("0.10")  # packages/fixtures/bybit/2026-10-05/rest/instruments_after.json
DISPLAYS = {"2560x1440": (2560, 1440), "1280x800": (1280, 800)}  # E18-D02 artboards
# E11-D02 §2 compact: toolbar + status rows + time strip; the price gutter's FLOOR ("widest label
# + 8, min 48") + the drawing rail. A wider price label narrows the plot by the difference, so the
# bar-fit counts are upper bounds (memo §3.0, n1 of the text lens round 2).
CHROME_H, CHROME_W = 24 + 24 + 24, 48 + 24
LOD = {"L0": D(12), "L1": D(10), "L2": D(6)}  # E06-D01 §2, LOD_PROFILE_M0 (up-switch heights)
DOWN = {"L0": D("10.2"), "L1": D("8.5"), "L2": D("5.1")}  # E06-D01 §2; E06-K03 for the L2 step
GLYPHS = {"bid_ask": 7 + 1 + 7, "delta": 6, "volume": 7, "delta_total": 6 + 1 + 7}  # E06-D01 §4
# E06-D01 §2: "+4px gutter" on the two-number string, "+3px" on the one-number string. Read per
# side-cell (4 px per number of a two-number cell, the conservative reading, memo Q3); one-number
# modes take the 3 px. E06-D01 states the gutters once, without a density, so dense keeps them.
GUTTER = {"bid_ask": 8, "delta": 3, "volume": 3, "delta_total": 8}
# E11-D02 D6: comfortable {cellPadPx 4, fontSizeClass 1 (11 px), lodBias +1}, compact {2, 0 (10 px),
# 0}, dense {1, 0 (10 px), 0}: dense shares compact's glyph size and rungs (26 §5 rule 5's third).
FONT_PX = {"compact": D(10), "comfortable": D(11), "dense": D(10)}
LOD_BIAS = {"compact": ZERO, "comfortable": ONE, "dense": ZERO}  # px added to every LOD height
TEXT_SCALES = (ONE, D("1.12"), D("1.25"), D("1.5"))  # 16 §4 --cv-text-scale
RUNGS = (D(4), D(6), D(8), D(10), D("10.2"), D(12))  # the protocol's stimuli (ticket + E06-D01)
SCENES = {  # name: (visible bars, visible price rows, source)
    "US-FP-001 NFR": (60, 40, "11 §8 US-FP-001 NFR: 60 visible bars x 40 price levels"),
    "E18-K01 B3": (100, 25, "E18-K01 / E06-K03 B3: 2,500 visible cells (100 x 25)"),
}
BAR_TICKS, ROW_CAP = 400, 60  # 24 §4.1 sparsity example (30 traded levels); auto rule caps 60 rows
AGGS = (1, 2, 5, 7, 10)  # 1 / 2 / 5 / 10 ticks plus the auto value max(1, ceil(400 / 60)) = 7


def q(v: Decimal) -> str:
    return str(v.quantize(PX, rounding=ROUND_HALF_UP))


def rung(h: Decimal, bias: Decimal = ZERO, scale: Decimal = ONE) -> str:  # up-switch heights
    for level in ("L0", "L1", "L2"):
        if h >= (LOD[level] + bias) * scale:
            return level
    return "L3"


def pane(display: str) -> tuple[Decimal, Decimal]:
    w, h = DISPLAYS[display]
    return D(w - CHROME_W), D(h - CHROME_H)


def scene_row(display: str, scene: str, rows: int, bars: int, src: str) -> dict[str, str]:
    plot_w, pane_h = pane(display)
    cell_h = pane_h / rows
    bar_w = q(plot_w / bars) if bars > 1 else "-"
    return {"display": display, "scene": scene, "rows": str(rows), "bars": str(bars),
            "cell_h": q(cell_h), "rung": rung(cell_h), "bar_w": bar_w, "src": src}  # fmt: skip


def scenes() -> list[dict[str, str]]:
    out = []
    for display in DISPLAYS:
        for name, (bars, levels, src) in SCENES.items():
            out.append(scene_row(display, name, levels, bars, src))
        for agg in AGGS:
            name = f"24 §4.1 bar, aggregation_ticks {agg}" + (" (auto)" if agg == 7 else "")
            src = (f"{BAR_TICKS} ticks = {q(BAR_TICKS * TICK_BTCUSDT)} USDT at tick "
                   f"{TICK_BTCUSDT}; 30 traded levels; rows = ceil(400 / agg)")  # fmt: skip
            out.append(scene_row(display, name, -(-BAR_TICKS // agg), 1, src))
    return out


def floors() -> list[dict[str, str]]:
    out = []
    for density, font in FONT_PX.items():
        for mode, glyphs in GLYPHS.items():
            floor = glyphs * D("0.62") * font + GUTTER[mode]  # 0.62 em per mono glyph
            fit = {d: str(int(pane(d)[0] // floor)) for d in DISPLAYS}
            out.append({"density": density, "mode": mode, "glyphs": str(glyphs),
                        "width_floor": q(floor), "bars_2560": fit["2560x1440"],
                        "bars_1280": fit["1280x800"]})  # fmt: skip
    return out


def ladder() -> list[dict[str, str]]:
    return [{"rung_px": q(r), **{d: rung(r, LOD_BIAS[d]) for d in FONT_PX},
             **{f"x{s}": rung(r, scale=s) for s in TEXT_SCALES[1:]}} for r in RUNGS]  # fmt: skip


def table(rows: list[dict[str, str]], head: str) -> None:
    cols = [c.strip() for c in head.strip("|").split("|")]
    print(f"\n| {' | '.join(cols)} |\n|" + "---|" * len(cols))
    print("\n".join("| " + " | ".join(r[c] for c in cols) + " |" for r in rows))


def main(argv: list[str]) -> int:
    sc, fl, ld = scenes(), floors(), ladder()
    data = {
        "scenes": sc, "width_floors": fl, "ladder": ld,
        "down_switch_px": {k: q(v) for k, v in DOWN.items()},
        "floors_px": {f"x{s}": {k: q(v * s) for k, v in LOD.items()} for s in TEXT_SCALES},
        "row_cap_px_at_L0": q(ROW_CAP * LOD["L0"]), "pane_h_1280": q(pane("1280x800")[1]),
        "provenance": "planning assumptions from 11, 24, E06-D01, E11-D02, E18-D02; no market data",
    }  # fmt: skip
    if "--json" in argv:
        print(json.dumps(data, indent=2))
        return 0
    table(sc, "| display | scene | rows | bars | cell_h | rung | bar_w | src |")
    table(fl, "| density | mode | glyphs | width_floor | bars_2560 | bars_1280 |")
    table(ld, "| rung_px | compact | comfortable | dense | x1.12 | x1.25 | x1.5 |")
    print(f"\nDown-switch px {data['down_switch_px']}; {data['provenance']}; --json has the rest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
