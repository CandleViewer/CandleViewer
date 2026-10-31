"""Board 09 `E11-D05 / 09 ref-frames-a`: CMP-180 ChartRoot (10), CMP-188 PriceAxis (8), CMP-189 TimeAxis (9),
CMP-190 Crosshair (6) = 33 per-state ref frames, dark, compact (the trading default). Run: python3 -I -B gen/gen_09.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import e11d05kit as k  # noqa: E402

T1 = k.table1()
D16 = k.L("## 10. States per SCR-030 (D16)", "d02")


def d16(word: str) -> str:
    return f"E11-D02 D16 L{k.L(f'| **{word}**', 'd02', D16)}"


# ---------------------------------------------------------------- CMP-180 ChartRoot (480 x 300, status row kept)
W180, H180 = 480, 300


def base180(*, data: bool = True, n: int = 16) -> k.Crop:
    c = k.Crop(W180, H180, status=True, gutter=72, n=n, data=data)
    c.status_left.append(k.env_badge())
    return c


def f180_loading() -> k.Node:
    c = base180(data=False)
    c.labels = False
    major, _minor = c.levels()
    c.gutter += [k.rect(f"label block {i}", 44, 8, k.HOVER, {"radius": k.R_CONTROL}, x=8, y=c.y(p) - 4)
                 for i, p in enumerate(major) if 6 < c.y(p) < c.ph - 10]
    c.strip += [k.rect(f"label block {i}", 32, 8, k.HOVER, {"radius": k.R_CONTROL}, x=88 + 120 * i, y=8)
                for i in range(3)]
    tx = "Loading 5 000 bars…"
    c.pane.append(k.text("loading line", tx, k.BODY, k.TEXT_2, x=round((c.pw - k.text_w(tx, k.BODY)) / 2),
                         y=round(c.ph / 2 - 9), note="CMP-029; shimmer motion.duration.slow loop (static here)"))
    return c.build("f")


def streaming(c: k.Crop, *, wm: str = "BTCUSDT · 1m", countdown: str = "normal", cl: str = "following") -> None:
    c.pane.insert(0, k.watermark(c, wm))
    k.last_pill(c)
    c.status_right.append(k.countdown(countdown))
    cw = k.cluster_w(cl)
    c.strip.append(k.cluster(cl, x=round(c.w - cw), y=0))


def f180_streaming() -> k.Node:
    c = base180()
    streaming(c)
    return c.build("f")


def f180_stale() -> k.Node:
    c = base180()
    streaming(c)
    c.status_left.append(k.chip("feed chip · stale", "Stale 7s · last 13:42:05",
                                fill="color.data-confidence.stale.surface", color="color.data-confidence.stale.text",
                                stroke=None, dot="color.data-confidence.stale.indicator"))
    c.ink_group = "data ink · x0.85"
    dim = (f"E11-D02 D16 L{k.L('| D16 ', 'd02')} 'stale = data-ink uniform × 0.85 (no extra pass)'; E11-D05 "
           f"L{k.L('- The stale state multiplies the LUT')} and the dim85 rows L{k.L('| `dim85:color.candle.up`')}-"
           f"L{k.L('| `dim85:color.candle.wick`')}")
    k.spec_gap("CMP-180 stale: the x 0.85 dim is a colour multiply on the data-ink uniforms with no token and no "
               "opacity token (" + dim + "); the sheet groups the ink as 'data ink · x0.85' and the live step sets "
               "the spec's resolved dark values - a layer opacity 0.85 would blend with the pane, not multiply")
    k.live("CMP-180 stale frame, group 'data ink · x0.85': set every body fill on color.candle.up to #27A14C, on "
           "color.candle.down to #C33D41 and every wick to #767E86 (the dim85 dark column, " + dim + "); read "
           "back the three hex values; these are the frame's only unbound fills")
    return c.build("f")


def f180_disconnected() -> k.Node:
    c = base180()
    streaming(c)
    c.status_left.append(k.chip("feed chip · reconnecting", "Reconnecting (3)", fill=k.CANVAS,
                                color="color.data-confidence.reconnecting.text",
                                dot="color.data-confidence.reconnecting.indicator"))
    c.top.append(k.rect("scrim", c.w, c.ph + c.sh, k.APP, {"opacity": k.OPACITY_SCRIM}, x=0, y=c.st,
                        note="DOM scrim color.surface.app at opacity.scrim over the pane stack; frozen last-good frame"))
    tx = "Disconnected — last data 00:12"
    sw = k.text_w(tx, k.BODY) + 8 + 8 + 16
    c.top.append(k.hbox("disconnected strip", [k.node("ellipse", "dot", w=8, h=8,
                                                      o={"fill": "color.data-confidence.disconnected.indicator"}),
                                               k.text("label", tx, k.BODY, k.TEXT_1)],
                        {"fill": k.RAISED, "padX": k.INSET_SM, "gap": k.INSET_SM, "radius": k.R_CONTROL}, h=28,
                        x=round((c.w - sw) / 2), y=c.st + round(c.ph / 2) - 14))
    return c.build("f")


def f180_replay() -> k.Node:
    c = base180(n=16)
    vn = 10  # virtual now after bar 10
    c.bars = c.bars[:vn + 1]  # nothing exists right of virtual-now
    c.pane.insert(0, k.watermark(c, "BTCUSDT · 1m · replay"))
    rp = k.slot("color.chart.replay.border")
    xv = c.x(vn) + round(c.slot_w / 2)
    c.pane.append(k.rect("future dim", c.pw - xv, c.ph, k.APP, {"opacity": k.OPACITY_SCRIM}, x=xv, y=0,
                         note="one blended color.surface.app quad at opacity.scrim right of virtual-now"))
    c.pane.append(k.dashes("virtual-now line", xv, 0, c.ph, rp, vertical=True))
    # m3: the virtual now is read off this frame's time axis; in replay the zone tag's clock shows it (E11-D02 L276)
    now = c.clock_at(xv, secs=True)
    c.zone = f"UTC {now}"
    c.status_right.append(k.chip("replay chip", f"REPLAY {now}", stroke=rp, sw=k.FOCUS_W, glyph="refresh",
                                 gcolor=k.TEXT_1, note="the replay glyph (CR-7 icon/replay) is not in the set: refresh "
                                                       "stands in"))
    c.top.append(k.frame_rect("replay frame", c.w, c.ph + c.sh, rp, 4, x=0, y=c.st))
    k.deviate("CMP-180 replay: CR-7's icon/replay is not in the local icon set; the `refresh` glyph stands in")
    return c.build("f")


def corner_badge(c: k.Crop, tx: str) -> None:
    w = k.text_w(tx, k.CAPTION) + 12 + 4 + 16
    c.pane.append(k.chip("corner badge", tx, stroke=None, glyph="warning", gcolor=k.WARN_STRONG, x=8,
                         y=c.ph - 8 - 20, note=f"bottom-left, inset 8 (compact); est. w {w:.0f}"))


def f180_reduced() -> k.Node:
    c = base180()
    streaming(c)
    corner_badge(c, "Reduced detail — footprint text hidden")
    return c.build("f")


def f180_aggregated() -> k.Node:
    c = base180(n=30)
    streaming(c)
    c.status_left.append(k.chip("aggregation chip", "Zoomed out · 1 column = 12 bars",
                                note="disclosure button; the merge glyph is not in the local set (text carries it)"))
    k.deviate("CMP-180 aggregated: the chip's merge glyph is not in the local icon set; drawn text-only")
    return c.build("f")


def context_strip(c: k.Crop, tx: str) -> None:
    c.pane.append(k.hbox("context-loss strip", [k.icon("glyph", "warning", k.WARN_STRONG, k.ICON_SM),
                                                k.text("label", tx, k.CAPTION, k.TEXT_1, w=c.pw - 44)],
                         {"fill": k.WARN_SUBTLE, "padX": k.INSET_SM, "gap": k.INSET_XS}, w=c.pw, h=32, x=0, y=0,
                         note="CMP-028 warning strip, polite override (E11-D04 §12.2 CR-D04-10); last frame stays"))


def f180_context(attempt: int) -> k.Node:
    c = base180()
    streaming(c)
    nxt = {1: 1, 2: 2}[attempt]
    k.spec_gap("CMP-180 context lost / recovering: E11-D02 D16 has no row for them; Table 1 and `15` name the states "
               "and E11-D04 §12.2 gives the timeline: 'context lost' = t 0 (attempt 1 of 3), 'recovering' is read as "
               "a later restore attempt (attempt 2 of 3) - the restored frame itself has no visual of its own")
    context_strip(c, f"Graphics context lost — restoring… attempt {attempt} of 3 · next try in {nxt} s")
    return c.build("f")


def f180_empty() -> k.Node:
    c = k.Crop(W180, H180, status=True, strip=False, gutter=72, data=False, grid=False, labels=False)
    c.axes = False
    k.spec_gap("CMP-180 empty: E11-D02 D16 defers to E11-D04 (SCR-047); the frame draws reason 2's heading only, in "
               "the kept chassis; the cause sentence, action and link are E11-D04 §11's")
    c.status_left.append(k.env_badge())
    tx = "No bars for BTCUSDT 1m between 02:11 and 02:14 UTC."
    c.top.append(k.text("SCR-047 heading", tx, k.HEADING_SM, k.TEXT_1, w=360, x=24, y=c.st + 110,
                        note="CMP-026 EmptyState in the pane-stack region, no GL context; cause, action and link are "
                             "E11-D04 §11's (not drawn here)"))
    return c.build("f")


F180 = {
    "loading": (f180_loading, d16("loading")),
    "streaming": (f180_streaming, d16("streaming")),
    "stale": (f180_stale, d16("stale")),
    "disconnected": (f180_disconnected, d16("disconnected")),
    "replay": (f180_replay, d16("replay")),
    "reduced detail": (f180_reduced, d16("low-GPU / reduced detail")),
    "aggregated": (f180_aggregated, d16("aggregated (LOD chip)")),
    "context lost": (lambda: f180_context(1), f"E11-D04 §12.2 L{k.L('| 0 — context lost', 'd04')}"),
    "recovering": (lambda: f180_context(2), f"E11-D04 §12.2 L{k.L('| 1 s — attempt 1 fails', 'd04')}"),
    "empty": (f180_empty, f"E11-D02 D16 L{k.L('| empty / error', 'd02', D16)}; E11-D04 §11.2 "
                          f"L{k.L('| **2 no data in this range**', 'd04')}"),
}


# ---------------------------------------------------------------- CMP-188 PriceAxis (220 x 260, plot + right gutter)
W188, H188 = 220, 260
D7 = f"E11-D02 D7 L{k.L('### 7.1 CMP-188 PriceAxis (D7)', 'd02')}"


def base188(n: int = 9) -> k.Crop:
    return k.Crop(W188, H188, strip=False, gutter=72, n=n)


def lock_badge(c: k.Crop) -> None:
    c.gutter.append(k.hbox("lock badge", [k.icon("glyph", "locked", k.TEXT_1, k.ICON_SM)],
                           {"fill": k.RAISED, "stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR,
                            "strokeAlign": "inner", "radius": k.R_BADGE, "padX": k.INSET_XS, "justify": "center"},
                           w=24, h=20, x=8, y=3,
                           note="button named 'Price scale locked' (E11-D01 D2); its visible states are E11-D03's"))
    k.spec_gap("CMP-188 lock badge: D7 gives the pill's tokens, the lock glyph and the accessible name 'Price scale "
               "locked' but not its visible text in a 72 px gutter (badge states are E11-D03's); drawn glyph-only")


def f188(state: str) -> k.Node:
    c = base188()
    if state in ("last-price pill up", "last-price pill down"):
        k.force_dir(c, state.endswith("up"))
    if state == "last-price pill down":
        # m4: the seeded last bar is already down, so (auto) would equal this frame; here it closes at its low, so the
        # down pill sits below (auto)'s and (up)'s
        c.last().c = c.last().l
        k.deviate("CMP-188 last-price pill down: the seeded last bar is a down bar, so the (auto) frame already shows "
                  "a down pill; in this frame the bar closes at its low (" + k.f_price(c.last().l) + ") so the down "
                  "pill sits below (auto)'s, in color.candle.down with ▼")
    if state != "dragging":
        k.last_pill(c)
    if state == "locked":
        lock_badge(c)
    elif state == "mode tag":
        c.gutter.append(k.text("mode tag", "log", k.CAPTION, k.slot("color.chart.axis"), x=8, y=4,
                               note="log / % / inv, space-separated; hidden when linear and upright"))
    elif state == "mark pill":
        b = c.last()
        mk = b.c + 6.5
        yy = c.y(mk)
        c.pane.append(k.dashes("mark-price line", 0, yy, c.pw, k.slot("color.chart.boundary"), vertical=False,
                               dash=2, gap=6))
        c.gutter.append(k.pill("mark pill", f"M {k.f_price(mk)}", k.slot("color.chart.pill.bg"),
                               k.slot("color.chart.pill.text.default"), stroke=k.slot("color.chart.pill.border"),
                               x=0, y=yy - 8 - (0 if abs(yy - c.y(b.c)) > 19 else 19),
                               note="neutral GL pill below the last-price pill; yields vertically by 2 px"))
    elif state == "focused":
        c.top.append(k.ring("CMP-039 ring · axis", c.gw, c.ph, x=c.pw, y=0))
    elif state == "dragging":
        lock_badge(c)
        c.gutter.append(k.vbox("ns-resize cursor", [k.icon("up", "arrow-up", k.TEXT_1, k.ICON_SM),
                                                    k.icon("down", "arrow-down", k.TEXT_1, k.ICON_SM)],
                               None, w=12, h=24, x=40, y=round(c.ph / 2) - 12,
                               note="stand-in for the ns-resize cursor; the drag engages the lock; the crosshair "
                                    "and its pills are hidden while dragging"))
    return c.build("f")


C188 = {
    "auto": D7,
    "locked": f"{D7}; E11-D02 D16 L{k.L('| scale locked', 'd02', D16)}",
    "mode tag": D7,
    "last-price pill up": D7,
    "last-price pill down": D7,
    "mark pill": D7,
    "focused": f"E11-D02 L{k.L('Focus treatment: the CMP-039 ring drawn 2 px inside', 'd02')}",
    "dragging": f"E11-D02 L{k.L('**Pointer.** The whole gutter is the drag zone', 'd02')}",
}


# ---------------------------------------------------------------- CMP-189 TimeAxis (480 x 128, pane bottom + strip)
W189, H189 = 480, 128
D8 = f"E11-D02 D8 L{k.L('### 7.2 CMP-189 TimeAxis (D8)', 'd02')}"


def base189(zone: str = "UTC 13:47:05") -> k.Crop:
    return k.Crop(W189, H189, gutter=72, n=16, minor=False, times=("13:30", "13:35", "13:40"), zone=zone)


def hatch(name: str, w: int, h: int) -> k.Node:
    """pattern.hatch.gap: 45° texture lines (color.chart.hatch.texture) drawn as 2 x 2 steps every 8 px on
    diagonals 16 px apart, between two band edges (color.chart.boundary)."""
    tex, edge = k.slot("color.chart.hatch.texture"), k.slot("color.chart.boundary")
    kids, i = [], 0
    for d in range(-h, w, 16):
        for s in range(0, h, 8):
            x = d + s
            if 1 <= x < w - 3:
                kids.append(k.rect(f"t{i:03d}", 2, 2, tex, x=x, y=s))
                i += 1
    kids += [k.rect("edge left", 1, h, edge, x=0, y=0), k.rect("edge right", 1, h, edge, x=w - 1, y=0)]
    return k.box(name, kids, {"clip": True}, w=w, h=h)


def f189(state: str) -> k.Node:
    c = base189()
    cl = "paused" if state == "paused" else "following"
    if state not in ("virtual-now",):
        c.strip.append(k.cluster(cl, x=round(c.w - k.cluster_w(cl)), y=0))
    if state == "paused":
        # r3 axis sweep: "Paused at hh:mm" reads the newest bar on screen off this frame's axis (E11-D02 L267: hh:mm
        # of the newest bar on screen), not the zone tag's wall clock
        c.strip[-1] = k.cluster(cl, x=c.strip[-1]["x"], y=0, at=c.clock_at(c.x(len(c.bars) - 1)))
    if state == "boundary":
        xb = c.x(7) - round(c.slot_w / 2)
        c.pane.append(k.rect("session boundary", 1, c.ph, k.slot("color.chart.boundary"), x=xb, y=0,
                             note="the D1 boundary line through every pane (US-CHART-009)"))
        k.fallback("num-medium")
        c.times = ["13:35", "13:40"]
        c.drop_times = {0}  # live fold: the date replaces the time under the boundary label
        c.strip.append(k.text("boundary label", "14 Oct", k.NUM, k.slot("color.chart.axis"), x=xb - 19, y=6,
                              note="priority 0, medium weight"))
    elif state == "maintenance band":
        # r3 axis sweep: the band runs 13:31-13:38 on this axis, so its label sits between the 13:30 and 13:40 ticks
        # and covers only 13:35 (the one dropped label); both its times lie on the visible ticks
        x0, bw = 157, 150
        c.pane.append(dict(hatch("maintenance band", bw, c.ph), x=x0, y=0))
        c.strip.append(dict(hatch("maintenance band · strip", bw, c.sh - 1), x=x0, y=1))
        # m3: the band's times are read off this frame's axis (13:30 / 13:35 / 13:40)
        t0, t1 = c.clock_at(x0), c.clock_at(x0 + bw)
        c.strip.append(k.text("band label", f"{t0}–{t1} maintenance", k.CAPTION, k.TEXT_2, x=x0 + 6, y=5,
                              note="shown when the band is >= 48 px wide"))
        c.drop_times = {1}  # live fold: the band label covers this time label (dropped as a collision, D8)
    elif state == "loading band":
        lw = 132
        c.first = 6  # no bar loaded left of the oldest bar
        c.pane.insert(0, k.rect("loading band", lw, c.ph, k.HOVER, x=0, y=0))
        c.pane.append(k.text("loading band label", "Loading older bars…", k.CAPTION, k.TEXT_2, x=8,
                             y=round(c.ph / 2) - 7))
    elif state == "go-to-date marker":
        xg = c.x(6)
        mk = k.slot("color.chart.marker.goto")
        c.pane.append(k.dashes("go-to-date line", xg, 0, c.ph, mk, vertical=True))
        c.strip.append(k.rect("go-to-date line · strip", 1, 4, mk, x=xg, y=0))
        c.times = ["13:40"]
        c.strip.append(c.strip_pill(k.pill("go-to-date pill", c.clock_at(xg), mk,
                                           k.slot("color.chart.pill.text.on-marker"), y=4,
                                           note="GL pill; until the next navigation input, no timeout"), xg))
    elif state == "remote crosshair":
        xr = c.x(11)
        c.pane.append(k.dashes("remote crosshair", xr, 0, c.ph, k.slot("color.chart.crosshair"), vertical=True,
                               o={"opacity": k.OPACITY_MUTED}))
        c.times = ["13:30", "13:35"]
        c.strip.append(c.strip_pill(k.pill("remote time pill", c.clock_at(xr), k.slot("color.chart.pill.bg"),
                                           k.TEXT_2, stroke=k.slot("color.chart.pill.border"), y=4,
                                           note="neutral so it never reads as the local pill (D8: "
                                                "color.text.secondary)"), xr))
    elif state == "virtual-now":
        vn = 10
        c.bars = c.bars[:vn + 1]
        rp = k.slot("color.chart.replay.border")
        xv = c.x(vn) + round(c.slot_w / 2)
        c.pane.append(k.rect("future dim", c.pw - xv, c.ph, k.APP, {"opacity": k.OPACITY_SCRIM}, x=xv, y=0))
        c.pane.append(k.dashes("virtual-now line", xv, 0, c.ph, rp, vertical=True))
        c.times = ["13:30", "13:35", "13:40", "13:45"]
        # m3: the virtual now is read off this frame's axis; the zone tag's clock shows it (E11-D02 L276)
        now = c.clock_at(xv, secs=True)
        c.zone = f"UTC {now}"
        c.strip.append(c.strip_pill(k.pill("virtual-now clock pill", now, k.RAISED, k.TEXT_1, stroke=rp, y=4,
                                           note="the clock pill's tokens are not named in D8: neutral + replay "
                                                "hairline"), xv))
        k.spec_gap("CMP-189 virtual-now: D8 names the 1 px dashed replay line and 'a clock pill' but not the pill's "
                   "fill / text tokens; drawn neutral (surface.raised, text.primary) with a replay hairline")
    elif state == "focused":
        c.top.append(k.ring("CMP-039 ring · strip", c.w, c.sh, x=0, y=c.ph))
    return c.build("f")


C189 = {
    "following": f"E11-D02 L{k.L('holds the **cluster**', 'd02')}; D16 L{k.L('| **streaming**', 'd02', D16)}",
    "paused": f"{D8}; E11-D02 D16 L{k.L('| paused (follow off)', 'd02', D16)}",
    "boundary": f"E11-D02 L{k.L('- Session / day boundary (US-CHART-009)', 'd02')}",
    "maintenance band": f"E11-D02 L{k.L('- Maintenance window', 'd02')}",
    "loading band": f"E11-D02 L{k.L('- **Loading band**', 'd02')}",
    "go-to-date marker": f"E11-D02 L{k.L('- **Go-to-date marker**', 'd02')}",
    "remote crosshair": f"E11-D02 L{k.L('- **Remote crosshair**', 'd02')}",
    "virtual-now": f"E11-D02 L{k.L('- **Virtual-now**', 'd02')}",
    "focused": f"E11-D02 L{k.L('Focus treatment: ring inside the strip', 'd02')}",
}


# ---------------------------------------------------------------- CMP-190 Crosshair (320 x 220, pane + gutter + strip)
W190, H190 = 320, 220
D9 = f"E11-D02 D9 L{k.L('### 7.3 CMP-190 Crosshair and CMP-197 ChartTooltip (D9, D10)', 'd02')}"


def f190(state: str) -> k.Node:
    # magnet snap: the pill gains the 12 px glyph + 4 px gap, so the gutter widens to the widest label + 8 (D7)
    c = k.Crop(W190, H190, gutter=96 if state == "magnet snap" else 72, n=12, times=("13:30", "13:35"))
    i = 8
    b = c.bars[i]
    xc = c.x(i)
    ch, inv = k.slot("color.chart.crosshair"), k.slot("color.chart.pill.text.inverse")
    if state == "hidden during drag":
        c.pane.append(k.vbox("drag cursor", [k.icon("glyph", "drag-handle", k.TEXT_1, k.ICON)], None, w=16, h=16,
                             x=xc - 8, y=round(c.ph / 2) - 8,
                             note="stand-in for the grabbing pointer; lines and pills hidden during a drag or a "
                                  "wheel burst, back on the first idle frame; the keyboard column is unaffected"))
        return c.build("f")
    if state == "remote":
        c.pane.append(k.dashes("remote crosshair", xc, 0, c.ph, ch, vertical=True, o={"opacity": k.OPACITY_MUTED}))
        c.strip.append(c.strip_pill(k.pill("remote time pill", c.clock_at(xc), k.slot("color.chart.pill.bg"),
                                           k.slot("color.chart.pill.text.default"),
                                           stroke=k.slot("color.chart.pill.border"), y=4,
                                           note="neutral GL pill; suppressed while this chart has its own cursor"),
                                    xc))
        k.spec_gap("CMP-190 remote time pill text: E11-D02 D8 says color.text.secondary; `15` CMP-190 and E11-D05 "
                   "§4.1b bind color.chart.pill.text.default (= color.text.primary); drawn per `15` / §4.1b")
        return c.build("f")
    major, _minor = c.levels()
    if state == "magnet snap":
        price, label = b.h, f"H {k.f_price(b.h)}"
    elif state == "coincident gridline":
        price = min(major, key=lambda p: abs(c.y(p) - c.ph / 2))
        label = k.f_price(price)
    else:
        price = (c.hi + c.lo) / 2 + 3.5
        label = k.f_price(price)
    yy = c.y(price)
    c.pane.append(k.dashes("crosshair · horizontal", 0, yy, c.pw, ch, vertical=False,
                           note=("dashed 4 / 4 over the solid major line: pattern and luminance keep them two objects "
                                 "(D3)") if state == "coincident gridline" else None))
    if state == "keyboard column":
        fr, halo = k.slot("color.chart.focus.ring"), k.slot("color.chart.pane.bg.default")
        c.pane.append(k.box("keyboard cursor column", [k.rect("halo left", 1, c.ph, halo, x=0, y=0),
                                                       k.rect("column", 2, c.ph, fr, x=1, y=0),
                                                       k.rect("halo right", 1, c.ph, halo, x=3, y=0)],
                            None, w=4, h=c.ph, x=xc - 1, y=0,
                            note="E06-D03 D10 column: >= 2 px focus-ring colour with a 1 px pane-colour halo, "
                                 "replacing the vertical line while the chart root has focus"))
    else:
        c.pane.append(k.dashes("crosshair · vertical", xc, 0, c.ph, ch, vertical=True))
    c.gutter.append(k.pill("price pill", label, ch, inv, x=4, y=yy - 8, magnet=state == "magnet snap",
                           note="GL text in the axis batch (A-9); tick precision" +
                                ("; the snapped OHLC letter and the 12 px magnet glyph at its left edge "
                                 "(E11-D02 L302), the glyph drawn from primitives"
                                 if state == "magnet snap" else "")))
    c.strip.append(c.strip_pill(k.pill("time pill", c.clock_at(xc), ch, inv, y=4), xc))  # m3: read off the axis
    if state == "magnet snap":
        k.deviate("CMP-190 magnet snap: icon/magnet (E11-D02 CR-7) is not in the local icon set; the 12 px glyph "
                  "at the pill's left edge (E11-D02 L" + str(k.L("**Magnet affordance.**", "d02")) + ") is drawn "
                  "from primitives (a 12 x 12 horseshoe of three rects in the pill text colour) beside the OHLC "
                  "letter H (the frame's gutter is 96 px so the wider pill fits); swap for the library icon when CR-7 "
                  "lands")
    return c.build("f")


C190 = {
    "pointer": D9,
    "keyboard column": f"{D9}; E06-D03 D10; E11-D05 §4.1b",
    "magnet snap": f"E11-D02 L{k.L('**Magnet affordance.**', 'd02')}",
    "remote": f"E11-D02 L{k.L('- **Remote crosshair**', 'd02')}",
    "coincident gridline": f"E11-D02 D3 L{k.L('### 4.3 When the crosshair and a gridline coincide (D3)', 'd02')}",
    "hidden during drag": D9,
}


# ---------------------------------------------------------------- the board
NN = 9


def tok_line(used: list[str], extra: str) -> str:
    return "Tokens: slots " + ", ".join(f"{s} (= {k.SLOTS[s]})" for s in used) + " — pending #390, the alias bound; " \
        + extra


def main() -> None:
    g180, u180 = k.build_group("CMP-180", "ChartRoot", T1["CMP-180"], lambda st: F180[st][0](),
                               {st: F180[st][1] for st in T1["CMP-180"]}, 5)
    g188, u188 = k.build_group("CMP-188", "PriceAxis", T1["CMP-188"], f188, C188, 8)
    g189, u189 = k.build_group("CMP-189", "TimeAxis", T1["CMP-189"], f189, C189, 5)
    g190, u190 = k.build_group("CMP-190", "Crosshair", T1["CMP-190"], f190, C190, 6)
    groups = [g180, g188, g189, g190]
    n = sum(len(g.frames) for g in groups)
    if n != 33:
        raise RuntimeError(f"board 09 has {n} frames, not 33")
    t1 = k.L("### Table 1", "handoff")
    board_lines = [
        f"33 per-state ref frames (handoff Table 1 L{t1 + 4}–L{t1 + 7}: CMP-180 10, CMP-188 8, CMP-189 9, CMP-190 6); "
        "dark only; compact density.",
        "Ruling of record Q2 / Q3 (2026-10-30): boards 09 / 10 live in the per-set file `E11-D05 ref frames`, page "
        "`E11-D05 ref frames`; boards 01–08 stay on page `E11-D05` (§0).",
        f"Static ref frames, never library components (`16` §10 item 4; spec §8 L{k.L('## 8. The nine primitives')}); "
        "each frame's plugin-data note names its state, its source line and the slots it binds.",
        "Chart content is seeded synthetic data (seed 310), not a recorded series.",
        f"Export: {k.export_path(NN)}",
    ]
    blocks = [
        ("CMP-180 ChartRoot — 10 frames", [
            "Ownership (`15` L" + str(k.L("### CMP-180 ChartRoot", "cat")) + ", restated per `16` §10 item 3): `15` owns "
            "props / states / the a11y contract, `26` §2 / §6 / §8 the internals; the engine draws the pane fill, the "
            "grid and the replay frame; the DOM draws the status-row chips, the corner badge, the scrim and strips, "
            "and owns the mirror root and the two live regions.",
            f"States (§8.1 L{k.L('### 8.1 CMP-180 ChartRoot')}; E11-D02 D16 L{D16}): loading · streaming · stale · "
            "disconnected · replay · reduced detail · aggregated · context lost · recovering · empty. Context lost / "
            "recovering use E11-D04 §12.2's strip (attempt 1 / attempt 2); empty draws SCR-047 reason 2's heading.",
            tok_line(u180, "chips: color.data-confidence.*, color.surface.raised, color.env.demo; badge glyph "
                           "color.status.warning.strong; scrim color.surface.app at opacity.scrim."),
            k.density_line(" Watermark 48 px (40 dense), hidden below 120 px (160 comfortable)."),
            k.PRODUCTS + " Variants: single pane / multi pane.",
        ]),
        ("CMP-188 PriceAxis — 8 frames", [
            "Ownership (`15` L" + str(k.L("### CMP-188 PriceAxis", "cat")) + "): engine (GL, the axis batch) draws tick "
            "labels, the axis rule, the last-price / mark pills and their lines; the DOM owns the lock badge and the "
            "surrogate group 'Price axis, …' with its CMP-039 ring; `26` §8 PriceScale members are PROPOSED (G14).",
            f"States (§8.2 L{k.L('### 8.2 CMP-188 PriceAxis')}; D7 L{k.L('### 7.1 CMP-188 PriceAxis (D7)', 'd02')}): "
            "auto · locked · mode tag · last-price pill up · last-price pill down · mark pill · focused · dragging. "
            "Pill fill = the current bar's direction, ▲ / ▼ always; mark pill neutral with a 2 / 6 dashed line.",
            tok_line(u188, "pill fills color.candle.up / .down; lock badge color.surface.raised + "
                           "color.border.strong + color.text.primary; ring color.focus.ring."),
            k.density_line(),
            k.PRODUCTS + " Variants: right gutter / left gutter (two gutters per pane, D7).",
        ]),
        ("CMP-189 TimeAxis — 9 frames", [
            "Ownership (`15` L" + str(k.L("### CMP-189 TimeAxis", "cat")) + "): engine draws labels, the zone tag, the "
            "strip rule, the boundary / band / go-to-date / remote / virtual-now lines and their GL pills; the DOM owns "
            "the cluster [auto | fit | ›], the Paused pill and the loading-band text; TimeScale members PROPOSED (G14).",
            f"States (§8.3 L{k.L('### 8.3 CMP-189 TimeAxis')}; D8 L{k.L('### 7.2 CMP-189 TimeAxis (D8)', 'd02')}): "
            "following · paused · boundary · maintenance band · loading band · go-to-date marker · remote crosshair · "
            "virtual-now · focused. The pressed auto reads 'Live' (O-E: the owner may prefer 'Following').",
            tok_line(u189, "cluster color.surface.raised / .selected + color.border.*; Paused pill "
                           "color.status.warning.subtle + .strong; loading band color.surface.hover; dim "
                           "color.surface.app at opacity.scrim; remote line opacity.muted."),
            k.density_line(" Cluster segments 24 x 24 (32 comfortable); G time 80 px compact."),
            k.PRODUCTS + " Variants: per density.",
        ]),
        ("CMP-190 Crosshair — 6 frames", [
            "Ownership (`15` L" + str(k.L("### CMP-190 Crosshair", "cat")) + "): engine draws the dashed lines, the D10 "
            "cursor column and the GL pills (A-9); the readout box is CMP-197 (DOM); the focused bar's mirror row "
            "carries aria-current; chart.setMagnet is PROPOSED (G14).",
            f"States (§8.4 L{k.L('### 8.4 CMP-190 Crosshair')}; D9 L{k.L('### 7.3 CMP-190 Crosshair', 'd02')}): "
            "pointer · keyboard column · magnet snap · remote · coincident gridline · hidden during drag.",
            tok_line(u190, "remote line opacity.muted."),
            k.density_line(" Dash 4 / 4 CSS px."),
            k.PRODUCTS + " Variants: none (pointer / keyboard / remote / magnet are states).",
        ]),
    ]
    ann = k.annotations(NN, board_lines, blocks)
    k.live("each of the 33 frames reads back with the exact Table 1 name 'CMP-nnn · Name — ref frame (<state>)' and "
           "a non-empty plugin-data note naming its state")
    k.live("pick one bound shape per slot family (pane fill, grid major, axis label, pill text) and read back its "
           "fill token name = the alias target listed under Fallbacks")
    k.live("watermark texts (CMP-180 streaming / replay frames): set the font size to 48 px, weight 600 after the "
           "render (no type token carries 48 px); read back 48")
    p = k.write_sheet(NN, groups, ann)
    frames = [f["name"] for g in groups for f in g.frames]
    k.write_md(NN, p, summary="Board 09 of the E11-D05 ref-frame set (ruling Q2): the 33 per-state ref frames of "
                              "CMP-180 ChartRoot, CMP-188 PriceAxis, CMP-189 TimeAxis and CMP-190 Crosshair, dark, "
                              "compact, one labelled row group per component and one 400 px annotation column.",
               frames=frames)
    k.write_post_live(NN, p)  # the live fold's post-render step (BUILD.md)
    print(k.pack_sheet(p))


if __name__ == "__main__":
    main()
