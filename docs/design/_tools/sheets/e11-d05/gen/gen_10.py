"""Board 10 `E11-D05 / 10 ref-frames-b`: CMP-197 ChartTooltip (6), CMP-198 ChartWatermark (4), CMP-199 ChartLegend (8),
CMP-226 BarCountdown (4) = 22 per-state ref frames, dark, compact. Run: python3 -I -B gen/gen_10.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import e11d05kit as k  # noqa: E402

T1 = k.table1()
NN = 10
D10 = k.L("**Tooltip layout**", "d02")
FLIP = k.L("**Flip-not-clip and the priority stack.**", "d02")

# ---------------------------------------------------------------- CMP-197 ChartTooltip (360 x 260)
W197, H197 = 360, 320
TIP_W = 200


# m3: the overflow rows' values keep each band ordered upper >= middle >= lower (BB and Keltner both centre on the EMA 20
# row; the moving averages sit around the bars). Values before the frame's shift (SHIFT_197).
EMA20 = 64003.2
OVERFLOW = [("EMA 50", 63998.5), ("EMA 200", 63962.0), ("SMA 100", 64004.0), ("VWAP", 64001.5),
            ("BB upper", 64031.0), ("BB lower", 63975.4), ("Keltner up", 64022.7), ("Keltner dn", 63983.7)]
# r3 axis sweep: the docked / overflow frames widen the price range (the box clears the last-price band) and the
# last-price pill suppresses the 64,000 tick (D5), so the unshifted bars would sit below every visible tick. Their bars
# and series move up by SHIFT_197 and the range is set so the visible ticks (64,000-64,400, step 100) cover every value
# the frame shows: PX_197 px per price unit, the last close LP_Y_197 px down the plot.
SHIFT_197, PX_197, LP_Y_197 = 40.0, 0.65, 248


def tip_rows(c: k.Crop, i: int, overflow: bool = False, when: str = "13:38", shift: float = 0.0) -> list[k.Node]:
    b = c.bars[i]
    arrow = "▲" if b.c >= b.o else "▼"

    def cell(name: str, lab: str, val: str, full: bool = False) -> k.Node:
        return k.hbox(name, [k.text("label", lab, k.NUM, k.TEXT_2), k.text("value", val, k.NUM, k.TEXT_1)],
                      {"gap": k.INSET_SM}, w=(TIP_W - 16) / (1 if full else 2), h=14)

    def row(name: str, a: k.Node, b2: k.Node | None = None) -> k.Node:
        return k.hbox(name, [a, b2], None, w=TIP_W - 16, h=14)

    rows = [k.text("title", f"14 Oct {when} · 1m", k.CAPTION, k.TEXT_2),
            row("row OH", cell("O", "O", k.f_price(b.o)), cell("H", "H", k.f_price(b.h))),
            row("row LC", cell("L", "L", k.f_price(b.l)), cell("C", "C", f"{k.f_price(b.c)} {arrow}")),
            row("row vol", cell("Vol", "Vol", "1,204"), cell("delta", "Δ", "+200")),
            row("row EMA 20", cell("EMA 20", "─ EMA 20", k.f_price(EMA20 + shift), True))]
    if overflow:
        rows += [row(f"row {e}", cell(e, f"─ {e}", k.f_price(v + shift), True)) for e, v in OVERFLOW]
        rows.append(k.text("overflow", "+3 more · Alt+T", k.CAPTION, k.TEXT_2))
    return rows


def tooltip(c: k.Crop, i: int, x: float, y: float, *, overflow: bool = False, note: str = "",
            when: str = "13:38", shift: float = 0.0) -> k.Node:
    return k.vbox("CMP-197 tooltip", tip_rows(c, i, overflow, when, shift),
                  {"fill": k.OVERLAY, "stroke": k.BORDER, "strokeWidth": k.HAIR, "strokeAlign": "inner",
                   "radius": k.R_CARD, "pad": k.INSET_SM, "shadow": "elevation.popover"}, w=TIP_W, x=x, y=y,
                  note=("DOM, aria-hidden; values never coloured by direction (▲ / ▼ and the sign carry it). " + note
                        ).strip())


def tip_h(overflow: bool = False) -> int:
    return 16 + 13 + 14 * (12 if overflow else 4) + (13 if overflow else 0)


def f197(state: str) -> k.Node:
    c = k.Crop(W197, H197, gutter=72, n=14, times=("13:30", "13:35"))
    th = tip_h(state == "overflow")
    shift = 0.0
    if state in ("overflow", "docked"):  # widen the price range so the last-price band sits low and the 12 rows clear it
        shift = SHIFT_197
        for b in c.bars:
            b.o, b.h, b.l, b.c = b.o + shift, b.h + shift, b.l + shift, b.c + shift
        c.hi = c.last().c + LP_Y_197 / PX_197
        c.lo = c.hi - (c.ph - 1) / PX_197
        k.deviate(f"CMP-197 {state}: the frame's price range is widened so the last-price band sits low and the "
                  "box clears it (rule 4 priority), and its bars and series sit 40.0 higher so every value the frame "
                  "shows lies on its visible ticks (64,000-64,400); a layout choice of the crop, not a spec value")
    k.last_pill(c)
    ly = c.y(c.last().c)
    band = (ly - (17 / 2 + 4), ly + (17 / 2 + 4))
    i, py = {"follow": (3, 110), "flipped left": (12, 120), "flipped above": (2, c.ph - 30),
             "clear of last price": (2, round(ly - 22)), "docked": (6, 150), "overflow": (2, 4)}[state]
    xc = c.x(i)
    ch, inv = k.slot("color.chart.crosshair"), k.slot("color.chart.pill.text.inverse")
    c.pane.append(k.dashes("crosshair · vertical", xc, 0, c.ph, ch, vertical=True))
    c.pane.append(k.dashes("crosshair · horizontal", 0, py, c.pw, ch, vertical=False))
    when = c.clock_at(xc)  # m3: the time pill and the box's title read the time off the axis
    c.strip.append(c.strip_pill(k.pill("time pill", when, ch, inv, y=4), xc))
    # r3b: the crosshair price pill (CMP-190's, D9) at the horizontal line, its value read off the price axis there;
    # it never covers the last-price pill (E11-D02 D5 L205)
    c.gutter.append(k.pill("price pill", k.f_price(c.price_at(py)), ch, inv, x=4, y=py - 8,
                           note="GL text in the axis batch (A-9); tick precision; the price at the crosshair's y"))
    if c.lp_box and not (py - 8 + 17 <= c.lp_box[0] or py - 8 >= c.lp_box[1]):
        raise ValueError(f"CMP-197 {state}: the crosshair price pill covers the last-price pill")
    if c.strip[-1]["x"] != round(xc - k.est_width(c.strip[-1]) / 2):
        k.spec_gap("CMP-197: where the crosshair time pill would cover the zone tag's clock, E11-D02 L206 lets pills "
                   "cover tick labels only and L172 mirrors the cluster's exclusion zone at the tag; the pill flips "
                   "right of its anchor and is held at the zone's edge (8 px right of the tag), its value still the "
                   "crosshair's time")
    tx, ty = xc + 16, py + 16
    note = ""
    if state == "flipped left":
        tx, note = xc - 16 - TIP_W, "rule 1: the right edge would pass the plot's right edge − 8 px"
    elif state == "flipped above":
        ty, note = py - 16 - th, "rule 2: the bottom would pass the plot's bottom − 8 px"
    elif state == "clear of last price":
        room_below, room_above = c.ph - 8 - band[1], band[0] - 8
        ty = round(band[1] + 1) if room_below >= room_above else round(band[0] - th - 1)
        note = "rule 4: shifted vertically by the minimal distance that clears the last-price band"
    elif state == "docked":
        k.spec_gap("CMP-197 docked: D10 rule 6 says the docked box yields to the legend by sitting right of it; the "
                   "frame has no legend (CMP-199 is board 10's own row), so the box sits at the pane's top-right")
        tx, ty, note = c.pw - 8 - TIP_W, 8, "docked top-right (SCR-031 readout 'docked', or rule 5 on a short pane)"
    elif state == "overflow":
        note = "overflow after 12 rows, as text"
    if not (ty + th <= band[0] or ty >= band[1]) or ty < 0 or ty + th > c.ph - 8 or tx < 0 or tx + TIP_W > c.pw:
        raise ValueError(f"CMP-197 {state}: box ({tx}, {ty}, {TIP_W} x {th}) breaks the band {band} or the plot")
    c.pane.append(tooltip(c, i, tx, ty, overflow=state == "overflow", note=note, when=when, shift=shift))
    return c.build("f")


C197 = {"follow": f"E11-D02 L{D10}", "flipped left": f"E11-D02 L{FLIP} rule 1", "flipped above":
        f"E11-D02 L{FLIP} rule 2", "clear of last price": f"E11-D02 L{FLIP} rule 4", "docked":
        f"E11-D02 L{FLIP} rules 5-6", "overflow": f"E11-D02 L{D10}"}

# ---------------------------------------------------------------- CMP-198 ChartWatermark (320 x 200)
W198, H198 = 320, 200
D13 = k.L("### 7.6 CMP-198 ChartWatermark / PaneBackground (D13)", "d02")


def f198(state: str) -> k.Node:
    if state == "hidden below 120 px":
        c = k.Crop(W198, 112, strip=False, gutter=72, n=12)
        price = c.build("price pane · 112 px")
        vol = k.Crop(W198, H198 - 112 - 1, strip=False, gutter=72, n=12, minor=False, labels=False)
        vol.data = False
        vol.pane += [k.rect(f"vol {j:02d}", 10, 8 + (j * 7) % 40, k.WICK, x=vol.x(j) - 5,
                            y=vol.ph - 8 - (j * 7) % 40) for j in range(12)]
        return k.box("f", [dict(price, x=0, y=0, note="112 px tall: the watermark is hidden (below 120 px)"),
                           k.rect("splitter hairline", W198, 1, k.slot("color.chart.rule"), x=0, y=112),
                           dict(vol.build("volume pane"), x=0, y=113)],
                     {"fill": k.slot("color.chart.pane.bg.default"), "clip": True}, w=W198, h=H198)
    c = k.Crop(W198, H198, strip=False, gutter=72, n=12)
    if state == "dense 40 px":
        c.axis_typo = k.NUM_XS
    wm = "BTCUSDT · 1m · replay" if state == "replay suffix" else "BTCUSDT · 1m"
    c.pane.insert(0, k.watermark(c, wm, dense=state == "dense 40 px"))
    return c.build("f")


C198 = {"default": f"E11-D02 D13 L{D13}", "replay suffix": f"E11-D02 D13 L{D13}; D16 L"
        f"{k.L('| **replay**', 'd02')}", "hidden below 120 px": f"E11-D02 D13 L{D13}",
        "dense 40 px": f"E11-D02 D13 L{D13}; §2 Watermark row L{k.L('| Watermark ', 'd02')}"}

# ---------------------------------------------------------------- CMP-199 ChartLegend (340 x 300, the pane's top-left)
W199, H199 = 340, 300
D12 = k.L("### 7.5 CMP-199 ChartLegend (D12)", "d02")
# r3 axis sweep: every value lies on the frame's visible ticks (63,960-64,040, one step of 20 either side)
# r3b: the price row's value is bound per frame to the drawn last bar's close (f199), never a constant
SERIES = [("BTCUSDT 1m", "<last close>"), ("EMA 20", "64,003.2"), ("EMA 50", "63,980.5"), ("EMA 200", "63,946.0"),
          ("VWAP", "63,995.0"), ("BB 20 upper", "64,052.0")]
MORE = ["SMA 100", "Keltner up", "Keltner dn", "BB 20 lower", "Donchian hi", "Donchian lo", "Pivot P"]


def button(name: str, glyph: str, color: str = k.TEXT_2) -> k.Node:
    return k.hbox(name, [k.icon("glyph", glyph, color, k.ICON)], {"justify": "center"}, w=24, h=24)


def eye_off(color: str) -> k.Node:
    """m2: the eye-off glyph from primitives (the local icon set has no eye-off): the `show` eye plus a 2 px diagonal
    stroke, top-left to bottom-right, in the glyph's colour."""
    k.deviate("CMP-199 hidden rows: E11-D02 D12 (L119) and L343 draw an eye-off icon; the local icon set has none, so "
              "it is drawn from primitives - the `show` eye plus a 2 px diagonal stroke (13 2 x 2 steps) in "
              "color.text.tertiary; swap for the library icon when it lands")
    return k.box("glyph · eye-off", [k.icon("eye", "show", color, k.ICON, x=0, y=0),
                                     *[k.rect(f"slash {j:02d}", 2, 2, color, x=1 + j, y=1 + j) for j in range(13)]],
                 None, w=16, h=16, note="eye-off drawn from primitives: the show eye + a diagonal stroke (no eye-off "
                                        "icon in the local set)")


def label_row(*, focused: bool = False, collapsed: bool = False) -> k.Node:
    kids = [k.rect("pane-focus bar", 2, 16, k.ACTION) if focused else None,
            k.text("pane label", "Price", k.LABEL, k.TEXT_1),
            button("collapse", "chevron-right" if collapsed else "chevron-down"), button("pane menu", "more-horizontal")]
    return k.hbox("row 0 · pane label", kids, {"gap": k.INSET_XS}, h=24,
                  note="pane-focus bar color.action.primary.default (2 px, D14)" if focused else None)


def series_row(i: int, name: str, value: str, *, hidden: bool = False) -> k.Node:
    if i == 0:
        sw = k.box("swatch · candle", [k.rect("wick", 1, 8, k.WICK, x=3, y=0), k.rect("body", 5, 5, k.UP, x=1, y=2)],
                   None, w=8, h=8)
    else:
        k.fallback("indicator")
        sw = k.box("swatch · line", [k.rect("line", 8, 2, k.INFO_STRONG, x=0, y=3)], None, w=8, h=8)
    c3 = k.TEXT_3 if hidden else None
    kids = [sw, k.text("label", name, k.LABEL, c3 or k.TEXT_1, w=118),
            k.text("value", "—" if hidden else value, k.NUM, c3 or k.TEXT_2, w=64, align="right"),
            (k.hbox("eye", [eye_off(k.TEXT_3)], {"justify": "center"}, w=24, h=24) if hidden
             else button("eye", "show", k.TEXT_2))]
    return k.hbox(f"row {i + 1} · {name}", kids, {"gap": k.INSET_SM}, h=24,
                  note=(f"eye toggle aria-pressed=false, stable name '{name} visible'; 'hidden' in the row's name"
                        if hidden else f"eye toggle aria-pressed=true, stable name '{name} visible'"))


def summary(tx: str) -> k.Node:
    return k.hbox("summary", [k.text("label", tx, k.CAPTION, k.TEXT_2)], None, h=24)


def more_row(n: int) -> k.Node:
    return k.hbox("more row", [k.text("label", f"+{n} more", k.LABEL, k.TEXT_1)],
                  {"stroke": k.BORDER, "strokeWidth": k.HAIR, "strokeAlign": "inner", "radius": k.R_CONTROL,
                   "padX": k.INSET_SM}, h=24, note="button; opens the popover; Esc returns focus here")


def legend(rows: list[k.Node]) -> k.Node:
    return k.vbox("CMP-199 legend", rows, None, x=8, y=8, note="DOM; inset 8 (compact); one roving stop")


def clear_value(c: k.Crop, rows: list[int]) -> None:
    """Widen the crop's price range upwards until no candle crosses the value cell of the given legend rows (legend at
    (8, 8), 24 px rows, the value cell x 150-214)."""
    def hit() -> bool:
        for i, b in enumerate(c.bars):
            x = c.x(i)
            if 146 <= x <= 218 and any(c.y(b.h) < 8 + 24 * r + 24 and c.y(b.l) > 8 + 24 * r for r in rows):
                return True
        return False
    lifts = 0
    while hit():
        c.hi += 0.25 * (c.hi - c.lo)
        lifts += 1
    if lifts:
        k.deviate("CMP-199 one hidden: the frame's price range is widened so no candle crosses the hidden row's \"—\" "
                  "value (D12 gives the legend no row fill); a layout choice of the crop, not a spec value")


def f199(state: str) -> k.Node:
    c = k.Crop(W199, H199, strip=False, gutter=72, n=14)
    s = [(SERIES[0][0], k.f_price(c.last().c)), *SERIES[1:]]  # r3b: the header value is the drawn last bar's close
    if state == "default":
        rows = [label_row(), *[series_row(i, n, v) for i, (n, v) in enumerate(s[:3])]]
    elif state == "one hidden":
        rows = [label_row(), *[series_row(i, n, v, hidden=i == 1) for i, (n, v) in enumerate(s[:3])]]
        # m2: lift the candles clear of the hidden row's "—" (the legend has no row fill in D12)
        clear_value(c, [2])
    elif state == "all hidden":
        rows = [label_row(), *[series_row(i, n, v, hidden=True) for i, (n, v) in enumerate(s)],
                summary("6 series · 6 hidden")]
        c.data = False  # m2: the price series is hidden too, so no candles are drawn behind the "—" values
        k.deviate("CMP-199 all hidden: every series row is hidden, the price series included, so the pane draws no "
                  "candles (grid and axis stay) and no \"—\" value sits over a wick")
    elif state in ('overflow "+N more"', "popover open"):
        n_vis = max(3, int(0.3 * c.ph // 24))
        total = len(s) + len(MORE)
        rows = [label_row(), *[series_row(i, n, v) for i, (n, v) in enumerate(s[:n_vis])], more_row(total - n_vis)]
        if state == "popover open":
            pop = k.vbox("popover", [series_row(n_vis + j, n, v) for j, (n, v) in enumerate(s[n_vis:n_vis + 3])],
                         {"fill": k.OVERLAY, "stroke": k.BORDER, "strokeWidth": k.HAIR, "strokeAlign": "inner",
                          "radius": k.R_CARD, "pad": k.INSET_XS, "shadow": "elevation.popover"},
                         x=8, y=8 + 24 * (n_vis + 2) + 4,
                         note="max height 60 % of the pane, scrollable; the same row component; Esc closes")
            c.pane.append(pop)
            c.pane.append(k.ring("CMP-039 ring · first popover row", 236, 24, x=12, y=8 + 24 * (n_vis + 2) + 8))
    elif state == "collapsed":
        rows = [label_row(collapsed=True), summary("6 series · 2 hidden")]
    elif state == "pane-label row focused":
        rows = [label_row(focused=True), *[series_row(i, n, v) for i, (n, v) in enumerate(s[:3])]]
        c.pane.append(k.ring("CMP-039 ring · pane label row", 120, 24, x=8, y=8))
    else:  # estimated series
        rows = [label_row(), series_row(0, *s[0]), series_row(1, "VWAP (estimated)", "63,995.0")]
    c.pane.insert(len(c.pane), legend(rows))
    if state == "popover open":
        c.pane.append(c.pane.pop(-3))  # popover and ring above the legend
        c.pane.append(c.pane.pop(-3))
    return c.build("f")


C199 = {"default": f"E11-D02 D12 L{D12}", "one hidden": f"E11-D02 L{k.L('**Hidden state.**', 'd02')}",
        "all hidden": f"E11-D02 L{k.L('**Hidden state.**', 'd02')}",
        'overflow "+N more"': f"E11-D02 L{k.L('**Overflow at 12 indicators.**', 'd02')}",
        "popover open": f"E11-D02 L{k.L('**Overflow at 12 indicators.**', 'd02')}",
        "collapsed": f"E11-D02 L{k.L('**Overflow at 12 indicators.**', 'd02')}",
        "pane-label row focused": f"E11-D02 D12 L{D12}; D14",
        "estimated series": f"`15` CMP-199 States L{k.L('estimated series (', 'cat')}"}

# ---------------------------------------------------------------- CMP-226 BarCountdown (240 x 48, the status row)
W226, H226 = 240, 48
D11 = k.L("### 7.4 CMP-226 BarCountdown (D11)", "d02")


def f226(state: str) -> k.Node:
    key = {"normal": "normal", 'warn "closing"': "warn", "closed": "closed", "non-time —": "na"}[state]
    cd = k.countdown(key)
    cw = k.est_width(cd)
    row = k.box("status row", [k.text("readout", "last 64,011.0", k.NUM, k.TEXT_1, x=8, y=5),
                               dict(cd, x=round(W226 - 8 - cw), y=2 if key == "warn" or key == "normal" else 5)],
                {"fill": k.RAISED}, w=W226, h=24, x=0, y=12)
    return k.box("f", [row], {"fill": k.APP, "clip": True}, w=W226, h=H226)


C226 = {"normal": f"E11-D02 D11 L{D11}", 'warn "closing"': f"E11-D02 D11 L{k.L('| **warn**', 'd02')}",
        "closed": f"E11-D02 D11 L{k.L('| **closed**', 'd02')}", "non-time —": f"E11-D02 D11 L{k.L('| **n/a**', 'd02')}"}


# ---------------------------------------------------------------- the board
def tok_line(used: list[str], extra: str) -> str:
    head = ("Tokens: slots " + ", ".join(f"{s} (= {k.SLOTS[s]})" for s in used) + " — pending #390, the alias "
            "bound; ") if used else "Tokens: "
    return head + extra


def main() -> None:
    g197, u197 = k.build_group("CMP-197", "ChartTooltip", T1["CMP-197"], f197, C197, 6)
    g198, u198 = k.build_group("CMP-198", "ChartWatermark", T1["CMP-198"], f198, C198, 4)
    g199, u199 = k.build_group("CMP-199", "ChartLegend", T1["CMP-199"], f199, C199, 4)
    g226, u226 = k.build_group("CMP-226", "BarCountdown", T1["CMP-226"], f226, C226, 4)
    groups = [g197, g198, g199, g226]
    n = sum(len(g.frames) for g in groups)
    if n != 22:
        raise RuntimeError(f"board 10 has {n} frames, not 22")
    t1 = k.L("### Table 1", "handoff")
    board_lines = [
        f"22 per-state ref frames (handoff Table 1 L{t1 + 9}–L{t1 + 12}: CMP-197 6, CMP-198 4, CMP-199 8, CMP-226 4); "
        "dark only; compact density.",
        "Ruling of record Q2 / Q3 (2026-10-30): boards 09 / 10 live in the per-set file `E11-D05 ref frames`, page "
        "`E11-D05 ref frames`; boards 01–08 stay on page `E11-D05` (§0). CMP-196 MultiChartLinker is non-visual: no "
        "frame (Table 1).",
        f"Static ref frames, never library components (`16` §10 item 4; spec §8 L{k.L('## 8. The nine primitives')}); "
        "each frame's plugin-data note names its state, its source line and the slots it binds.",
        "Chart content is seeded synthetic data (seed 310), not a recorded series.",
        f"Export: {k.export_path(NN)}",
    ]
    blocks = [
        ("CMP-197 ChartTooltip — 6 frames", [
            "Ownership (`15` L" + str(k.L("### CMP-197 ChartTooltip", "cat")) + ", restated per `16` §10 item 3): a "
            "DOM overlay, aria-hidden — the DOM mirror and the live region carry the values; the engine draws the "
            "crosshair and pills under it (CMP-190); `26` owns input coalescing (one reposition per frame).",
            f"States (§8.6 L{k.L('### 8.6 CMP-197 ChartTooltip')}; D10 L{D10}, L{FLIP}): follow · flipped left · "
            "flipped above · clear of last price · docked · overflow. Anchor = the crosshair intersection, default "
            "16 px right / below; priority: the last-price line and pill are never covered.",
            tok_line(u197, "box color.surface.overlay + color.border.default, radius.card, elevation.popover; title "
                           "and labels color.text.secondary, values color.text.primary, type.num.sm; pad "
                           "space.inset.sm."),
            k.density_line(" Width 200–260 px compact, ≤ 40 % of the pane."),
            k.PRODUCTS + " Variants: mode follow / docked / off ('off' draws no box: the legend is the readout).",
        ]),
        ("CMP-198 ChartWatermark / PaneBackground — 4 frames", [
            "Ownership (`15` L" + str(k.L("### CMP-198 ChartWatermark", "cat")) + "): engine only — the pane fill and "
            "the SDF watermark in the axis batch, aria-hidden (symbol and interval live in the toolbar and the canvas "
            "label); the pane fill never changes on focus (the D14 bar carries focus).",
            f"States (§8.7 L{k.L('### 8.7 CMP-198 ChartWatermark')}; D13 L{D13}): default · replay suffix · hidden "
            "below 120 px · dense 40 px. Centred in the price pane only, width ≤ 60 % of the plot, opacity fixed at 1.",
            tok_line(u198, "type: 48 / 40 px semibold, no token: display / heading-lg (Fallbacks); "
                           "the volume pane's bars color.candle.wick."),
            k.density_line(" Watermark 48 px compact, 40 px dense; hidden below 120 px (160 comfortable)."),
            k.PRODUCTS + " Variants: none (dense 40 px is a state).",
        ]),
        ("CMP-199 ChartLegend — 8 frames", [
            "Ownership (`15` L" + str(k.L("### CMP-199 ChartLegend", "cat")) + "): a DOM overlay — the one home for "
            "per-series visibility toggles and cursor values (A-14; CMP-224 becomes the toolbar's entry); the engine "
            "draws the series it toggles; `26` §8 Pane.legend is PROPOSED (G14).",
            f"States (§8.8 L{k.L('### 8.8 CMP-199 ChartLegend')}; D12 L{D12}): default · one hidden · all hidden · "
            "overflow \"+N more\" · popover open · collapsed · pane-label row focused · estimated series. Visible "
            "rows ≤ ⌊0.3 × pane / row⌋, min 3 (300 px pane: 3 + '+10 more').",
            tok_line(u199, "rows color.text.primary / .secondary, hidden color.text.tertiary; focus bar "
                           "color.action.primary.default; popover color.surface.overlay + elevation.popover; ring "
                           "color.focus.ring; swatch line color.status.info.strong (Fallbacks)."),
            k.density_line(" Legend rows 24 (32 comfortable, 24 dense), eye toggle 24 x 24, labels ellipsise at 18."),
            k.PRODUCTS + " Variants: per density.",
        ]),
        ("CMP-226 BarCountdown — 4 frames", [
            "Ownership (`15` L" + str(k.L("### CMP-226 BarCountdown", "cat")) + "): an Atom of the chart chrome, DOM, "
            "one home in the status row beside the readout; aria-live off; the non-time-bar replacement is E12-D06 "
            "D5's and E12-D09 owns it (C14, the entry is shared).",
            f"States (§8.9 L{k.L('### 8.9 CMP-226 BarCountdown')}; D11 L{D11}): normal · warn \"closing\" · closed · "
            "non-time —. The warn state changes a word and a weight, never only a colour; the amber is the fill.",
            tok_line(u226, "color.text.secondary (normal), color.status.warning.subtle + color.text.primary + "
                           "color.status.warning.strong glyph (warn), color.text.tertiary (closed / n/a), row "
                           "color.surface.raised; digits type.num.sm, label type.ui.caption."),
            k.density_line(),
            k.PRODUCTS + " Variants: comfortable / compact.",
        ]),
    ]
    ann = k.annotations(NN, board_lines, blocks)
    k.live("each of the 22 frames reads back with the exact Table 1 name 'CMP-nnn · Name — ref frame (<state>)' and "
           "a non-empty plugin-data note naming its state")
    k.live("CMP-197 frames: the tooltip box never overlaps the last-price pill's band (read back its y / h against "
           "the last-price line y ± 12.5)")
    k.live("CMP-198 watermark texts: set the font size to 48 px (40 px in 'dense 40 px'), weight 600 after the render; "
           "read back the sizes; the 'hidden below 120 px' frame has no watermark text")
    k.live("CMP-199 'popover open': the popover and its ring sit above the legend (z-order) and inside the frame")
    p = k.write_sheet(NN, groups, ann)
    frames = [f["name"] for g in groups for f in g.frames]
    k.write_md(NN, p, summary="Board 10 of the E11-D05 ref-frame set (ruling Q2): the 22 per-state ref frames of "
                              "CMP-197 ChartTooltip, CMP-198 ChartWatermark, CMP-199 ChartLegend and CMP-226 "
                              "BarCountdown, dark, compact, one labelled row group per component and one 400 px "
                              "annotation column.", frames=frames)
    k.write_post_live(NN, p)  # the live fold's post-render step (BUILD.md)
    print(k.pack_sheet(p))


if __name__ == "__main__":
    main()
